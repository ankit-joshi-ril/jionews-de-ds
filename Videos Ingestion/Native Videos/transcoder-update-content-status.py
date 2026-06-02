import base64
import hashlib
import hmac
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytz
import requests
from bson import ObjectId
from google.cloud import secretmanager, pubsub_v1, storage
from pymongo import MongoClient, errors, UpdateOne

# Ignore all warnings
warnings.filterwarnings("ignore")

_run_local = False
_zone = ZoneInfo("Asia/Kolkata")
path = os.path
root = path.dirname(path.abspath(__file__))


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)


class Utils:
    @staticmethod
    def generate_epoch_range(interval_minutes):
        timezone = pytz.timezone('Asia/Kolkata')
        now = datetime.now(timezone)
        start_minute = (now.minute // interval_minutes) * interval_minutes - interval_minutes
        start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=start_minute)
        end_time = start_time + timedelta(minutes=interval_minutes) - timedelta(seconds=1)
        start_epoch = int(start_time.timestamp())
        end_epoch = int(end_time.timestamp())

        return {'start_epoch': start_epoch, 'end_epoch': end_epoch}

    @staticmethod
    def get_current_epoch():
        now = datetime.now(_zone)
        current_epoch = int(now.timestamp())
        return current_epoch

    @staticmethod
    def get_secret(secret_name):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data

    def publish_message_to_topic(self, topic_name, data):
        project_id = "jiox-328108"
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(project_id, topic_name)

        json_string = json.dumps(data, cls=JSONEncoder)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            ps_future = pubsub.publish(topic_path, data=message_bytes)
            ps_future.result()
            print(f"Message published!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")


class GCS:
    def __init__(self):
        self.bucket_name = "de_video_transcoder_input"

    def download_file_from_gcs(self, source_blob_name: str, destination_file_name: str):
        print(f"Downloading file from GCS: {source_blob_name}")
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(source_blob_name)
        try:
            blob.download_to_filename(destination_file_name)
            print(f"Downloaded {source_blob_name} to {destination_file_name}")
            return True
        except Exception as e:
            print(f"Failed to download {source_blob_name}: {e}")
            return False

    def delete_gcs_file(self, file_name):
        try:
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(file_name)

            if blob.exists():
                blob.delete()
            else:
                print(f"File not found: {file_name} in bucket: {self.bucket_name}")

        except Exception as e:
            print(f"Error deleting file: {file_name}")
            print(str(e))


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

    def get_mongo_records(self, video_ids):
        pipeline = [
            {
                '$match': {
                    'sourceVideoId': {
                        '$in': video_ids
                    },
                    # Filter out processed records
                    'transcoderProcessingStatus': {
                        '$ne': 'completed'
                    }
                }

            }
        ]

        try:
            records = list(self.raw_videos_rss.aggregate(pipeline))
            return records
        except Exception as e:
            print(f"Error fetching recs from mongo")
            return None

    def get_mongo_record(self, video_id):
        try:
            record = self.raw_videos_rss.find_one({"sourceVideoId": video_id})
            if record:
                return record
            else:
                print(f"No record found for video_id: {video_id}")
                return None
        except Exception as e:
            print(f"Failed to get record for video_id {video_id}: {e}")
            return None

    def update_records_in_mongodb(self, records):
        """
        Updates multiple fields for each record in MongoDB using bulk operations.
        Skips any record without a valid _id.
        """
        if not records:
            print("No records received for update.")
            return 0

        bulk_operations = []
        for record in records:
            try:
                if '_id' not in record:
                    print(f"Skipping record without '_id': {record}")
                    continue
                update_data = {k: v for k, v in record.items() if k != '_id'}
                bulk_operations.append(
                    UpdateOne({'_id': ObjectId(record['_id'])}, {'$set': update_data})
                )
            except Exception as e:
                print(f"Error preparing update for record {record.get('_id')}: {e}")

        if not bulk_operations:
            print("No valid bulk operations to execute.")
            return 0

        try:
            result = self.raw_videos_rss.bulk_write(bulk_operations)
            return result.modified_count
        except Exception as e:
            print(f"MongoDB bulk update failed: {e}")
            return 0


class VOD:
    def __init__(self):
        self.api_access_key = "jionews1"
        self.api_secret = "Kn4U5r0hYPrXwWFBm2YCNnsl12S7MaAk"
        self.api_base_url = "https://cppapi-saas.media.jio.com"
        self.current_epoch = Utils.get_current_epoch()

        self.distributor_name = "jionews"
        self.distributor_id = "685bc98ec9e754683750e182"

    def generate_hmac_for_get(self, url_path):
        payload = f"{url_path}{self.api_access_key}{self.current_epoch}"
        hmac_token = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac_token

    def get_all_content_status(self, limit=5, retries=3, retry_delay=5, page=None):
        url_path = "vod/v1/getallcontentstatus"
        url = f"{self.api_base_url}/{url_path}?limit={limit}&distributorName={self.distributor_name}"

        if page:
            url = f"{self.api_base_url}/{url_path}?limit={limit}&distributorName={self.distributor_name}&page={page}"

        for attempt in range(1, retries + 1):
            try:
                self.current_epoch = Utils.get_current_epoch()
                hmac_token = self.generate_hmac_for_get(url_path)
                headers = {
                    "distributorId": self.distributor_id,
                    "accessKey": self.api_access_key,
                    "timestamp": str(self.current_epoch),
                    "Authorization": hmac_token
                }

                response = requests.get(url, headers=headers)
                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                print(f"[Attempt {attempt}] Failed to fetch content status: {e}")
                if attempt < retries:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print("All retries failed.")
                    return None

    def get_content_details(self, content_id, retries=3, retry_delay=5):
        # "https://cppapi-saas.media.jio.com/vod/v1/getcontentdetails/6892be8ccdfa49a23d69393c/jionews"
        url_path = f"vod/v1/getcontentdetails/{content_id}/jionews"
        url = f"{self.api_base_url}/{url_path}"

        print(f"Processing getcontentdetails for {url}")

        for attempt in range(1, retries + 1):
            try:
                self.current_epoch = Utils.get_current_epoch()
                hmac_token = self.generate_hmac_for_get(url_path)
                headers = {
                    "distributorId": self.distributor_id,
                    "accessKey": self.api_access_key,
                    "timestamp": str(self.current_epoch),
                    "Authorization": hmac_token
                }

                response = requests.get(url, headers=headers)
                response.raise_for_status()
                print(f"Success getcontentdetails for {url}")
                return response.json()

            except requests.exceptions.RequestException as e:
                print(f"[Attempt {attempt}] Failed to fetch content details for {content_id}: {e}")
                if attempt < retries:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print("All retries failed.")
                    return None

    def get_content_status_all_pages(self):
        all_pages_recs = []
        total_pages = self.get_all_content_status(limit=100)['totalPages']
        print(f"total_pages: {total_pages}")
        for i in range(1, total_pages + 1):
            response = self.get_all_content_status(limit=100, page=i)
            records = response['data']
            print(f"Total {len(records)} recs fetched from page {i}")
            all_pages_recs.extend(records)

        print(f"Total {len(all_pages_recs)} records fetched")

        # with open("all_pages_recs.json", 'w') as f:
        #     json.dump(all_pages_recs, f, indent=4)

        return all_pages_recs


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.gcs = GCS()
        self.db = MongoDB()
        self.vod = VOD()

        if _run_local:
            self.tmp_dir = 'tmp'
        else:
            self.tmp_dir = '/tmp'

    def process_record(self, record):
        transcoder_content_id = record.get('transcoderContentId')
        content_details = self.vod.get_content_details(transcoder_content_id, retries=3)

        if not content_details:
            record['transcoderProcessingStatus'] = "failed"
            record['errorMessage'] = "Filed to fetch hls url from getcontentdetails API "
            return record

        # updated_recs = []
        hls_path = content_details['data']['playingUrl']['urlMetaData'][0]
        base_url = "https://videos.jionews.com/jvodnews"
        avc_file_path = hls_path['url'].replace("index_jnews_web_premium", "master-_jnews_web_premium")
        hevc_file_path = hls_path['hevcUrl'].replace("index_jnews_web_premium", "master-_jnews_web_premium")
        record['hlsAvcUrl'] = f"{base_url}{avc_file_path}"
        record['hlsHevcUrl'] = f"{base_url}{hevc_file_path}"
        record['duration'] = str(content_details["data"]["duration"])
        record['transcoderProcessingStatus'] = "completed"
        record['updatedAt'] = Utils.get_current_epoch()

        # updated_recs.append(record)
        # self.db.update_records_in_mongodb(updated_recs)

        return record

    def process_recs(self, mongo_meta_data):
        updated_records = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.process_record, record) for record in mongo_meta_data]

            for future in as_completed(futures):
                updated_record = future.result()
                updated_records.append(updated_record)

        return updated_records

    def transform_native(self, all_recs):
        for rec in all_recs:
            hls_url = rec.get('hlsHevcUrl', '')
            rec["bitrates"] = {
                "low": hls_url,
                "medium": hls_url,
                "high": hls_url,
                "auto": hls_url
            }
            # rec['src'] = "native"
        return all_recs

    def process(self):

        try:
            status_recs = []
            for page in range(1, 6):
                response = self.vod.get_all_content_status(limit=100, page=page)
                if not response or not response.get('data'):
                    break
                status_recs.extend(response['data'])
                if page >= response.get('totalPages', 1):
                    break
            print(f"Total {len(status_recs)} records fetched from CPP (up to 5 pages)")
        except Exception as e:
            print(f"Failed to fetch content status from API. Exception: {e}")
            return None

        success_status_recs = [rec for rec in status_recs if rec['status'] == "Pu"]
        print(
            f"Total {len(status_recs)} video records fetched from API. {len(success_status_recs)} videos are successfully transcoded")
        video_ids = [rec['name'] for rec in success_status_recs]
        print(f"--debug:: video_ids: {video_ids}")
        mongo_meta_data = self.db.get_mongo_records(video_ids)
        # print(f"--debug:: mongo_meta_data: {mongo_meta_data}")
        print(f"Total {len(mongo_meta_data)} non-processed records fetched from DB")

        if not mongo_meta_data:
            print(f"All recs already processed")
            return None

        # Build lookup from success_status_recs
        content_id_map = {rec["name"]: rec["contentId"] for rec in success_status_recs}
        # print(f"--debug:: content_id_map: {content_id_map}")

        # Update mongo_meta_data with contentId where sourceVideoId matches
        for rec in mongo_meta_data:
            if rec.get("sourceVideoId") in content_id_map:
                rec["transcoderContentId"] = content_id_map[rec["sourceVideoId"]]

        # print(f"--debug:: mongo_meta_data after update: {mongo_meta_data}")
        updated_recs = self.process_recs(mongo_meta_data)

        videos_recs = [r for r in updated_recs if r.get('contentType') != 'shorts']
        shorts_recs = [r for r in updated_recs if r.get('contentType') == 'shorts']

        if videos_recs:
            self.pubsub.publish_message_to_topic("raw_native_videos", self.transform_native(videos_recs))
            self.pubsub.publish_message_to_topic("NewRawVideosIngestion_processed_data",
                                                 self.transform_native(videos_recs))

        if shorts_recs:
            # **Staging**
            self.pubsub.publish_message_to_topic("native-shorts-ingestion-stg", self.transform_native(shorts_recs))
            # **Prod**
            # self.pubsub.publish_message_to_topic("native-shorts-ingestion-prod", self.transform_native(shorts_recs))

        # Update records in MongoDB
        self.db.update_records_in_mongodb(updated_recs)

    def run(self):
        try:
            self.process()
        except Exception as e:
            print(f"Error processing. Exception caught:: {e}")


def main(req_param_ph):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=_zone)}")

    exe = Execute()
    exe.run()

    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=_zone)}")
    return {'result': 'success'}
