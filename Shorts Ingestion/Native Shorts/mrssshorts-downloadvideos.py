import base64
import json
import time
import warnings
from datetime import datetime
from io import BytesIO
from time import sleep
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from google.cloud import pubsub_v1, storage, secretmanager
from pymongo import MongoClient, errors

# Filter out the specific warning
warnings.filterwarnings("ignore", category=UserWarning)


class Utils:

    @staticmethod
    def epoch_now():
        zone = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=zone)
        return int(now.timestamp())

    @staticmethod
    def get_secret(secret_name):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload


class Logger:
    def __init__(self, debug_on):
        self.debug_on = debug_on

    def debug(self, print_val):
        if self.debug_on:
            print(f"--debug::: {print_val}")
        else:
            pass


class PubSub:
    def __init__(self, debug):
        self.debug = debug
        self.topic_name = "NewRawHeadlinesIngestion_processed_data"
        self.project_id = "jiox-328108"
        self.pubsub = pubsub_v1.PublisherClient()
        self.topic_path = self.pubsub.topic_path(self.project_id, self.topic_name)

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class GCS:
    def __init__(self, debug):
        self.debug = debug

        self.storage_client = storage.Client()
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "videos/mrss_videos_feeds.csv"
        self.feeds_config = None

        self.cdn_bucket_name = "hls_video_transcoder_storage_output_files"
        self.cdn_blob = "raw_videos/"

        self.transcoder_bucket_name = "de_video_transcoder_input"

    def read_csv_from_gcs(self):
        bucket = self.storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes))
        self.feeds_config = df

    def upload_mp4_to_gcs(self, cdn_url, cdn_filename):
        try:
            if not cdn_url or not cdn_url.endswith(".mp4"):
                print(f"Invalid url: {cdn_url}. It should end with .mp4")
                return False

            blob_path = f"{self.cdn_blob}{cdn_filename}"
            bucket = self.storage_client.bucket(self.cdn_bucket_name)
            blob = bucket.blob(blob_path)

            # Stream download and upload without saving to disk
            with requests.get(cdn_url, stream=True, verify=False) as response:
                response.raise_for_status()
                blob.upload_from_file(response.raw, rewind=False, content_type='video/mp4')

            print(f"Successfully uploaded {cdn_url} to GCS at {blob_path}")

            return True
        except Exception as e:
            print(f"Error uploading {cdn_url} to GCS: {e}")
            return False

    def copy_file_to_transcoder(self, file_name, max_retries=3):
        source_bucket = self.storage_client.bucket(self.cdn_bucket_name)
        source_blob = source_bucket.blob(f"{self.cdn_blob}{file_name}")

        destination_bucket = self.storage_client.bucket(self.transcoder_bucket_name)

        destination_blob_name = file_name
        for attempt in range(max_retries):
            try:
                # Perform the copy
                source_bucket.copy_blob(
                    source_blob, destination_bucket, destination_blob_name
                )

                print(
                    f"Successfully copied {file_name} from {self.cdn_bucket_name}/{self.cdn_blob} to {self.transcoder_bucket_name}/{destination_blob_name}")
                return True


            except Exception as e:
                print(f"Copy attempt {attempt + 1} failed: {e}")
                sleep(2)

        print(f"Failed to copy {file_name} after {max_retries} attempts")
        return False


class MongoDB:
    def __init__(self):
        secret_name = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        connection_uri_de = Utils.get_secret(secret_name)

        try:
            de_client = MongoClient(connection_uri_de)
            ingestion_db = de_client['ingestion-data']
            self.raw_videos_rss = ingestion_db['raw_videos_rss']
            print("MongoDB connection established successfully.")
        except errors.ServerSelectionTimeoutError as err:
            print(f"Server selection timeout error: {err}")
        except errors.ConnectionFailure as err:
            print(f"Connection failure: {err}")
        except Exception as err:
            print(f"An error occurred: {err}")

    def get_record(self, video_id):
        try:
            return self.raw_videos_rss.find_one({"sourceVideoId": video_id})
        except Exception as e:
            print(f"Error fetching record for {video_id}: {e}")
            return None

    def update_video_record_in_mongo(self, video_id, updated_fields):
        try:

            result = self.raw_videos_rss.update_one(
                {"sourceVideoId": video_id},
                {"$set": updated_fields}
            )

            if result.matched_count > 0:
                print(f"Successfully updated record for videoId: {video_id}")
                return True
            else:
                print(f"No record found in DB with videoId: {video_id}")
                return False

        except Exception as e:
            print(f"Error updating DB for videoId {video_id}: {e}")
            return False


class Execute:
    def __init__(self, debugger=True):
        print("execution started")
        self.db = MongoDB()
        self.logger = Logger(debugger)
        self.debug = self.logger.debug
        self.ps = PubSub(self.debug)

        self.gcs = GCS(self.debug)
        self.gcs.read_csv_from_gcs()
        self.feeds_config = self.gcs.feeds_config

    def process_video(self, video_rec):
        processing_status = {"processingStatus": "processing_video_download", "transcoderProcessingStatus": "",
                             "errorMessage": "", "transcoderErrorMessage": ""}
        video_id = video_rec.get('sourceVideoId')
        publisher_video_url = video_rec.get('publisherVideoUrl')

        print(f"{video_id}:: Processing URL: {publisher_video_url}")

        if not publisher_video_url or ".mp4" not in publisher_video_url:
            processing_status["processingStatus"] = "failed"
            processing_status["errorMessage"] = f"Invalid video URL: {publisher_video_url}"
            print(f"{video_id}:: Invalid video URL: {publisher_video_url}")
            return processing_status

        print(f"{video_id}:: Uploading publisher video to GCS..")
        video_uploaded = self.gcs.upload_mp4_to_gcs(publisher_video_url, f"{video_id}.mp4")

        if video_uploaded:
            processing_status["transcoderProcessingStatus"] = "initiated"
            processing_status["processingStatus"] = "completed"
            processing_status["videoContentUrl"] = f"https://vcdn.jionews.com/raw_videos/{video_id}.mp4"
        else:
            processing_status["processingStatus"] = "failed"
            processing_status["errorMessage"] = f"Failed to upload video {video_id} to GCS."
            print(f"{video_id}:: Failed to upload video to GCS.")

        return processing_status

    def run(self, message):
        video_rec = self.ps.parse_message(message)[0]
        video_id = video_rec['sourceVideoId']

        # Guard against PubSub retry death loop: if already completed in DB, do not re-download/re-upload
        current_record = self.db.get_record(video_id)
        if current_record and current_record.get('processingStatus') == 'completed':
            print(f"{video_id}:: Already completed in DB. Skipping to break PubSub retry loop.")
            return

        processing_status = self.process_video(video_rec)

        processing_status["updatedAt"] = Utils.epoch_now()
        for key, value in processing_status.items():
            video_rec[key] = value

        self.db.update_video_record_in_mongo(video_id, processing_status)


def main(req):
    message = []
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    try:
        request_json = req.get_json()
        message = request_json['message']
        print(f"type(message): {type(message)}")
        print(f"message: {message}")
    except Exception as e:
        print(f"Exception caught while fetching req data: {e}")
    exe = Execute(debugger=False)
    exe.run(message)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}