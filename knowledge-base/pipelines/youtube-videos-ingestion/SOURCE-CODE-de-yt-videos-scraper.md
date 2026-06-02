# Source Code: Nem-Emerging-World-of-Journalism/de-yt-videos-scraper
> Auto-synced from GitHub on 2026-04-14 11:54 UTC
> Branch: `master` | Role: YouTube video scraper and metadata fetcher

## Repository Structure
```
Dockerfile
jenkinsfile
k8s/production/deployment.yaml
k8s/production/hpa.yaml
k8s/staging/deployment.yaml
k8s/staging/hpa.yaml
prodjenkins.groovy
requirements.txt
src/main.py
```

## `requirements.txt`
```text
requests
google-auth
google-cloud-pubsub
google-cloud-storage
pymongo
pytubefix
```

## `Dockerfile`
```
FROM python:3.12

# Install system dependencies
RUN apt-get update && apt-get install -y curl && apt-get clean

# Install Node.js (latest LTS)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    node -v && npm -v

# Set working directory
WORKDIR /src

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY ./src /src

# Set the working directory back to /src
WORKDIR /src

# Command to run the app
CMD ["python", "main.py"]
```

## `src/main.py`
```python
import base64
import json
import logging
import os
import random
import sys
import time
import warnings
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import requests
from bson import ObjectId
from google.auth import default
from google.cloud import pubsub_v1, storage
from pymongo import MongoClient, errors, UpdateOne
from pytubefix import YouTube

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,  # Explicitly set INFO level
    format="%(levelname)s:%(name)s:%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # Direct logs to stdout
    ]
)

logger = logging.getLogger(__name__)


class Utils:
    @staticmethod
    def epoch_now():
        zone = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=zone)
        return int(now.timestamp())


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"
        # self.subscription_name = "RawVideosContentRss_FilteredPublishersData_Sub"
        self.subscription_name = "RawVideosContentRss_ScrapperBatching_Sub"
        # self.subscription_name = "youtube_scrapper_test_sub"
        self.subscriber_client, self.publisher_client = self.get_pubsub_clients()
        self.subscription_path = self.subscriber_client.subscription_path(self.project_id, self.subscription_name)

    def get_pubsub_clients(self):
        # Configure Pub/Sub Clients
        service_account_json_str = os.getenv('SERVICE_ACCOUNT_PUBSUB')
        if service_account_json_str:
            # Use the service account credentials from the environment variable
            service_account_info = json.loads(service_account_json_str)
            subscriber_client = pubsub_v1.SubscriberClient.from_service_account_info(service_account_info)
            publisher_client = pubsub_v1.PublisherClient.from_service_account_info(service_account_info)
        else:
            # Use the default credentials for local development
            credentials, project = default()
            subscriber_client = pubsub_v1.SubscriberClient(credentials=credentials)
            publisher_client = pubsub_v1.PublisherClient(credentials=credentials)

        return subscriber_client, publisher_client

    def publish_message_to_topic(self, topic_name, data):
        pubsub = self.publisher_client
        topic_path = pubsub.topic_path(self.project_id, topic_name)

        json_string = json.dumps(data)
        print(f"Final JSON String for pubsub: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            pubsub.publish(topic_path, data=message_bytes)
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class MongoDBHandler:
    def __init__(self):
        mongo_uri = os.getenv('MONGO_URI')
        try:
            self.client = MongoClient(mongo_uri)
            self.db = self.client["ingestion-data"]
            self.videos_rss_collection = self.db['raw_videos_rss']
            self.client.server_info()
            print("Connected to MongoDB successfully.")
        except Exception as e:
            logging.error(f"MongoDB connection failed: {e}")
            raise RuntimeError("Error connecting to MongoDB.")

    def update_records_in_mongodb(self, records):
        """
        Updates multiple fields for each record in MongoDB.
        """
        try:
            # Prepare bulk update operations
            bulk_operations = [
                UpdateOne({'_id': ObjectId(record['_id'])}, {'$set': {k: v for k, v in record.items() if k != '_id'}})
                for record in records
            ]

            # Execute bulk update
            if bulk_operations:
                result = self.videos_rss_collection.bulk_write(bulk_operations)
            else:
                print("No records to update.")
        except Exception as e:
            print(f"An error occurred while updating records: {e}")

    def insert_record(self, record: dict):
        try:
            self.videos_rss_collection.insert_one(record)
        except errors.PyMongoError as e:
            logging.error(f"Database operation failed: {e}")


class GCS:
    def __init__(self):
        self.bucket_name = "hls_video_transcoder_storage_output_files"
        self.blob = "raw_videos"

        self.storage_client = self.get_gcs_client()

    def get_gcs_client(self):
        # Configure GCS Client
        service_account_json_str = os.getenv('SERVICE_ACCOUNT_GSC')
        if service_account_json_str:
            # Use the service account credentials from the environment variable
            service_account_info = json.loads(service_account_json_str)
            gcs_client = storage.Client.from_service_account_info(service_account_info)
        else:
            # Use the default credentials for local development
            credentials, project = default()
            gcs_client = storage.Client(credentials=credentials, project=project)

        return gcs_client

    def upload_video_to_gcs(self, video_buffer, file_name):
        # storage_client = storage.Client()
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(f"{self.blob}/{file_name}")
        blob.upload_from_file(video_buffer, content_type='video/mp4')


class Alert:
    def __init__(self):
        self.webhook_url = "https://rilcloud.webhook.office.com/webhookb2/50d9b364-0092-40a4-a5c4-95d82953ae66@fe1d95a9-4ce1-41a5-8eab-6dd43aa26d9f/IncomingWebhook/6889dbbdf66c409197589ecf13512be6/6c18cadb-8d47-4378-bbd9-016fd8e3b86b/V2qQJ9tP6Ts8bbC0MZ8emMNuYKIBY2GMQZ2Qy30gw_U_81"

    def send_alert(self, message, publisher_name, channel_id):
        custom_message = {
            "title": "Content Type: Videos - RSS",
            "text": "Error Scraping Video",
            "sections": [
                {
                    "facts": [
                        {
                            "name": "Severity",
                            "value": "SEV-3"
                        },
                        {
                            "name": "Cloud Function name",
                            "value": "RawVideosContentRss_ScrapeVideoContent"
                        },
                        {
                            "name": "Publisher Name",
                            "value": publisher_name
                        },
                        {
                            "name": "Channel ID",
                            "value": channel_id
                        },
                        {
                            "name": "Error Message",
                            "value": message
                        }
                    ],
                    "markdown": True
                }
            ]
        }
        response = requests.post(self.webhook_url, json=custom_message, verify=False)

        if response.status_code == 200:
            print("Alert Message sent successfully!")
        else:
            print(f"Failed to send Alert message. Status code: {response.status_code}")


class Processor:
    def __init__(self, gcs, db):
        self.gcs = gcs
        self.db = db
        self.processed_recs = []
        self.success_recs = []
        self.alert = Alert()

    def print_current_timestamp_ist(self):
        ist_time = datetime.now(tz=ZoneInfo('Asia/Kolkata'))
        return str(ist_time)

    def is_cdn_file_available(self, cdn_url: str) -> bool:
        try:
            response = requests.head(cdn_url, timeout=5, allow_redirects=True, verify=False)
            return response.status_code == 200
        except requests.RequestException as e:
            logger.info(f"Error checking CDN URL: {e}")
            return False

    def download_video_audio_by_resolution(self, url, video_id, publisher_name, channel_id, resolution="720p"):
        """Download YouTube video at the specified resolution and the highest quality audio, then upload to GCS."""
        status = {'processing_status': "", 'error_message': ""}

        # *** Check if the CDN file is available ***
        video_cdn_url = f"https://vcdn.jionews.com/raw_videos/temp/{video_id}_video.mp4"
        audio_cdn_url = f"https://vcdn.jionews.com/raw_videos/temp/{video_id}_audio.mp4"

        if self.is_cdn_file_available(video_cdn_url) and self.is_cdn_file_available(audio_cdn_url):
            print(f"Audio and video files already available for {video_id}")
            status['processing_status'] = "av_ready"
            return status

        # *** Fetch AV streams trying with all the clients ***
        clients = [
            'WEB',
            'WEB_EMBED',
            'WEB_MUSIC',
            'WEB_CREATOR',
            'WEB_SAFARI',
            'MWEB',
            'WEB_KIDS',
            'ANDROID',
            'ANDROID_VR',
            'ANDROID_MUSIC',
            'ANDROID_CREATOR',
            'ANDROID_TESTSUITE',
            'ANDROID_PRODUCER',
            'ANDROID_KIDS',
            'IOS',
            'IOS_MUSIC',
            'IOS_CREATOR',
            'IOS_KIDS',
            'TV',
            'TV_EMBED',
            'MEDIA_CONNECT'
        ]
        video_streams = None
        audio_streams = None

        for client in clients:
            try:
                print(f"Inspecting streams for {url}")
                print(f"Trying client: {client}")
                yt = YouTube(url, client)
                print(f"Streams inspected successfully with client {client}")
                # print(f"yt: {yt}")

                # Get video-only and audio-only adaptive streams
                video_streams = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True)
                audio_streams = yt.streams.filter(adaptive=True, file_extension='mp4', only_audio=True)

                if video_streams and audio_streams:
                    break
            except Exception as e:
                print(f"Error inspecting streams for {url} with client {client}. Exception:{e}")

        if not video_streams or not audio_streams:
            error_message = f"Couldn't download for url: {url}. No suitable streams found."
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "failed"
            status['error_message'] = f"Error inspecting streams with all clients."
            return status

        # *** Process Video Streams ***

        # Filter video streams based on the desired resolution
        video_stream = video_streams.filter(resolution=resolution).first()
        if not video_stream:
            available_resolutions = [stream.resolution for stream in video_streams]
            error_message = (f"Couldn't download for url: {url}. Video is not available in {resolution} resolution.\n"
                             f"Available resolutions: {', '.join(available_resolutions)}")
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "skipped"
            status['error_message'] = f"Video is not available in {resolution} resolution."
            return status

        # *** Process Video Streams ***

        # Get the highest quality audio stream
        best_audio_stream = audio_streams.order_by('abr').desc().first()

        if not best_audio_stream:
            print("\nAlert: No audio stream available.")
            error_message = f"Couldn't download for url: {url}. No suitable audio stream found."
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "failed"
            status['error_message'] = f"No audio stream available."
            return status

        # *** Downloading Video ***
        try:
            # Download the selected video stream to a buffer
            print(
                f"Downloading the video stream at {resolution}: {video_stream}")
            video_buffer = BytesIO()
            video_stream.stream_to_buffer(video_buffer)
            video_buffer.seek(0)
            print(f"Video downloaded successfully at {resolution}")
        except Exception as e:
            print(f"Error downloading video stream for {url}. Exception: {e}")
            error_message = f"Couldn't download video stream for url: {url}.\nException: {e}"
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "failed"
            status['error_message'] = f"Error downloading video stream. Exception: {e}"
            return status

        # *** Downloading Audio ***
        try:
            # Download audio stream to a buffer
            print(f"Downloading the audio stream: {best_audio_stream}")
            audio_buffer = BytesIO()
            best_audio_stream.stream_to_buffer(audio_buffer)
            audio_buffer.seek(0)
            print(f"Audio downloaded successfully")
        except Exception as e:
            print(
                f"Error downloading audio stream for {url}. Exception: {e}")
            error_message = f"Couldn't download audio stream for url: {url}.\nException: {e}"
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "failed"
            status['error_message'] = f"Error downloading audio stream. Exception: {e}"
            return status

        # *** Uploading Audio-Video files to GCS ***
        try:
            # Generate filenames based on video ID and resolution
            video_filename = f"temp/{video_id}_video.mp4"
            audio_filename = f"temp/{video_id}_audio.mp4"

            # Save video and audio files to GCS with appropriate filenames
            print(f"Saving video file {video_filename} to GCS")
            self.gcs.upload_video_to_gcs(video_buffer, video_filename)
            print(f"Saved video file {video_filename} to GCS")

            print(f"Saving audio file {audio_filename} to GCS")
            self.gcs.upload_video_to_gcs(audio_buffer, audio_filename)
            print(f"Saved audio file {audio_filename} to GCS")

            status['processing_status'] = "av_ready"
            return status

        except Exception as e:
            print(
                f"Error uploading streams to GCP for {url}. Exception: {e}")
            error_message = f"Error uploading streams to GCP for url: {url}.\nException: {e}"
            self.alert.send_alert(error_message, publisher_name, channel_id)
            status['processing_status'] = "failed"
            status['error_message'] = f"Error uploading streams to GCP. Exception: {e}"
            return status

    def process_video(self, rec):
        """Process a single video by downloading it and uploading to GCS."""
        yt_id = rec['sourceExternalid']
        publisher_name = rec['sourcePublisherName']
        channel_id = rec['sourceChannelID']
        url = f"https://www.youtube.com/watch?v={yt_id}"
        status = self.download_video_audio_by_resolution(url, yt_id, publisher_name, channel_id)
        processing_status = status['processing_status']
        error_message = status['error_message']
        rec['processingStatus'] = processing_status
        rec['errorMessage'] = error_message

        if processing_status == "av_ready":
            # Update the record with the new status and URLs
            rec['videoUrl'] = f"https://vcdn.jionews.com/raw_videos/temp/{yt_id}_audio.mp4"
            rec['audioUrl'] = f"https://vcdn.jionews.com/raw_videos/temp/{yt_id}_video.mp4"
            rec['updatedAt'] = Utils.epoch_now()
        #     self.success_recs.append(rec)
        # self.processed_recs.append(rec)

        return rec

    def process_videos(self, data_list, max_workers=5):
        """Process multiple videos concurrently using ThreadPoolExecutor."""

        # with ThreadPoolExecutor(max_workers=max_workers) as executor:
        #     future_to_rec = {executor.submit(self.process_video, rec): rec for rec in data_list}
        #
        #     for future in as_completed(future_to_rec):
        #         rec = future_to_rec[future]
        #         try:
        #             future.result()
        #         except Exception as e:
        #             print(f"Exception Caught process_videos: {e}")

        processed_data = []

        for rec in data_list:
            try:
                processed_rec = self.process_video(rec)
                processed_data.append(processed_rec)
            except Exception as e:
                logger.info(f"Exception Caught process_videos: {e}")
                rec['processingStatus'] = 'failed'
                rec['errorMessage'] = f'Error in merging video. Exception:: {e}'
                # self.processed_recs.append(rec)
                processed_data.append(rec)

        return processed_data


class Execute:

    def __init__(self):
        print("execution started")
        self.ps = PubSub()
        self.gcs = GCS()
        self.db = MongoDBHandler()
        self.processor = Processor(self.gcs, self.db)

    def append_fields(self, data_list, additional_fields):
        for rec in data_list:
            for field, value in additional_fields.items():
                rec[field] = value

        return data_list

    def process(self, message):
        # Parse message
        data = json.loads(message.data.decode("utf-8"))

        # print(f"Updating processing status to 'processing' for {len(data)} records")
        print(f"Updating processing status to 'processing'")
        # Update processing status
        updates = {'processingStatus': 'processing', 'updatedAt': Utils.epoch_now()}
        data = self.append_fields(data, updates)
        self.db.update_records_in_mongodb(data)

        print(f"Processing {len(data)} record")
        # Process videos
        processed_recs = self.processor.process_videos(data)

        print(f"Processing completed for {len(data)} records.")

        if len(processed_recs) > 0:
            print(f"Updating processing updated status to db")
            # Update processing status
            # self.db.update_records_in_mongodb(self.processor.processed_recs)
            self.db.update_records_in_mongodb(processed_recs)

            success_records = [rec for rec in processed_recs if rec['processingStatus'] == 'av_ready']

            print(f"Publishing success recs to pubsub")
            # Publish success recs to pubsub
            # self.ps.publish_message_to_topic("RawVideosContentRss_ProcessedData", self.processor.success_recs)
            self.ps.publish_message_to_topic("RawVideosContentRss_ProcessedData", success_records)

    def callback(self, message):
        try:
            print(f"Received message: {message.data}")
            delay = random.uniform(0, 7)
            print(f"Delaying message processing for {delay} seconds")
            time.sleep(delay)  # staggered start
            self.process(message)

            # Acknowledge the message
            message.ack()
            logger.info("Message processed successfully.")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            message.nack()

    def run(self):
        print(f"Listening for messages on {self.ps.subscription_path}")
        future = self.ps.subscriber_client.subscribe(self.ps.subscription_path, callback=self.callback)

        try:
            future.result()
        except Exception as e:
            logger.info(f"Subscriber encountered an error: {e}")


def main():
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute()
    exe.run()
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}


main()
```
