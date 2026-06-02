import hashlib
import hmac
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bson import ObjectId
from google.cloud import secretmanager, pubsub_v1
from pymongo import MongoClient, errors, UpdateOne

warnings.filterwarnings("ignore")

_zone = ZoneInfo("Asia/Kolkata")

PUBSUB_TOPIC = "RawShortsIngestion_processed_data"
CREATED_AT_GTE = 1778437800  # Only process shorts created from today onwards


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)


class Utils:
    @staticmethod
    def get_current_epoch():
        now = datetime.now(_zone)
        return int(now.timestamp())

    @staticmethod
    def get_secret(secret_name):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8")


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

    def publish_message_to_topic(self, topic_name, data):
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(self.project_id, topic_name)
        json_string = json.dumps(data, cls=JSONEncoder)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            ps_future = pubsub.publish(topic_path, data=message_bytes)
            ps_result = ps_future.result()
            print(f"Message published to {topic_name}!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")


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
                    'sourceVideoId': {'$in': video_ids},
                    'contentType': 'shorts',
                    'createdAt': {'$gte': CREATED_AT_GTE},
                    'transcoderProcessingStatus': {'$ne': 'completed'}
                }
            }
        ]

        try:
            records = list(self.raw_videos_rss.aggregate(pipeline))
            return records
        except Exception as e:
            print(f"Error fetching records from mongo: {e}")
            return None

    def update_records_in_mongodb(self, records):
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

    def get_all_content_status(self, limit=100, retries=3, retry_delay=5, page=None):
        url_path = "vod/v1/getallcontentstatus"
        url = f"{self.api_base_url}/{url_path}?limit={limit}&distributorName={self.distributor_name}"
        if page:
            url += f"&page={page}"

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

    def get_content_details(self, content_id, retries=3, retry_delay=3):
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
        return all_pages_recs


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.db = MongoDB()
        self.vod = VOD()

    def process_record(self, record):
        transcoder_content_id = record.get('transcoderContentId')
        content_details = self.vod.get_content_details(transcoder_content_id, retries=3)

        if not content_details:
            record['transcoderProcessingStatus'] = "failed"
            record['transcoderErrorMessage'] = "Failed to fetch hls url from getcontentdetails API"
            return record

        hls_path = content_details['data']['playingUrl']['urlMetaData'][0]
        base_url = "https://videos.jionews.com/jvodnews"
        avc_file_path = hls_path['url'].replace("index_jnews_web_premium", "master-_jnews_web_premium")
        hevc_file_path = hls_path['hevcUrl'].replace("index_jnews_web_premium", "master-_jnews_web_premium")

        record['hlsAvcUrl'] = f"{base_url}{avc_file_path}"
        record['hlsHevcUrl'] = f"{base_url}{hevc_file_path}"
        record['duration'] = str(content_details["data"]["duration"])
        record['transcoderProcessingStatus'] = "completed"
        record['updatedAt'] = Utils.get_current_epoch()

        return record

    def process_recs(self, mongo_meta_data):
        updated_records = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.process_record, record) for record in mongo_meta_data]
            for future in as_completed(futures):
                updated_records.append(future.result())
        return updated_records

    def transform_shorts(self, all_recs):
        for rec in all_recs:
            hls_url = rec.get('hlsHevcUrl', '')
            rec["bitrates"] = {
                "low": hls_url,
                "medium": hls_url,
                "high": hls_url,
                "auto": hls_url
            }
        return all_recs

    def process(self):
        try:
            status_recs = self.vod.get_content_status_all_pages()
        except Exception as e:
            print(f"Failed to fetch content status from API. Exception: {e}")
            return None
        success_status_recs = [rec for rec in status_recs if rec.get('status') == "Pu"]
        print(f"Total {len(status_recs)} records fetched from API. {len(success_status_recs)} successfully transcoded.")

        video_ids = [rec['name'] for rec in success_status_recs]
        print(f"--debug:: video_ids: {video_ids}")

        mongo_meta_data = self.db.get_mongo_records(video_ids)
        print(f"Total {len(mongo_meta_data) if mongo_meta_data else 0} non-processed shorts records fetched from DB")

        if not mongo_meta_data:
            print("All shorts records already processed.")
            return None

        content_id_map = {rec["name"]: rec["contentId"] for rec in success_status_recs}

        for rec in mongo_meta_data:
            if rec.get("sourceVideoId") in content_id_map:
                rec["transcoderContentId"] = content_id_map[rec["sourceVideoId"]]

        updated_recs = self.process_recs(mongo_meta_data)

        self.pubsub.publish_message_to_topic(PUBSUB_TOPIC, self.transform_shorts(updated_recs))
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
