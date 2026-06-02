import base64
import json
import time
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

from bson import ObjectId
from google.cloud import secretmanager, pubsub_v1
from pymongo import MongoClient, errors, UpdateOne

warnings.filterwarnings("ignore")

_zone = ZoneInfo("Asia/Kolkata")

PUBSUB_TOPIC = "transcoder-shorts-push-to-sftp-batching"
CREATED_AT_GTE = 1778437800  # Start of today — only process shorts from this point forward
BATCH_LIMIT = 30


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
        self.pubsub = pubsub_v1.PublisherClient()

    def publish_message_to_topic(self, topic_name, data):
        topic_path = self.pubsub.topic_path(self.project_id, topic_name)
        message_bytes = json.dumps(data).encode("utf-8")
        try:
            self.pubsub.publish(topic_path, data=message_bytes)
            print(f"Message published to {topic_name}")
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        return json.loads(data.decode('utf-8'))


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

    def fetch_records_from_mongo(self):
        pipeline = [
            {
                '$match': {
                    'contentType': 'shorts',
                    'processingStatus': 'completed',
                    'createdAt': {
                        '$gte': CREATED_AT_GTE
                    },
                    'transcoderProcessingStatus': {
                        '$in': ['initiated']
                    }
                }
            },
            {
                '$sort': {'createdAt': -1}
            },
            {
                '$limit': BATCH_LIMIT
            },
            {
                '$project': {'_id': 0}
            }
        ]

        try:
            records = list(self.raw_videos_rss.aggregate(pipeline))
            if not records:
                print("No records found matching the criteria.")
                return None
            return records
        except Exception as e:
            print(f"Failed to fetch records from MongoDB: {e}")
            return None

    def get_mongo_record(self, video_id):
        try:
            record = self.raw_videos_rss.find_one({"sourceVideoId": video_id})
            if record:
                return record
            print(f"No record found for video_id: {video_id}")
            return None
        except Exception as e:
            print(f"Failed to get record for video_id {video_id}: {e}")
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


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.db = MongoDB()

    def run(self):
        print("Fetching shorts records from MongoDB...")
        filtered_records = self.db.fetch_records_from_mongo()
        print(f"Fetched {len(filtered_records) if filtered_records else 0} records from MongoDB.")
        if not filtered_records:
            print("No records found for processing.")
            return

        published_records = []

        for record in filtered_records:
            try:
                self.pubsub.publish_message_to_topic(PUBSUB_TOPIC, [record])
                mongo_record = self.db.get_mongo_record(record.get('sourceVideoId'))
                if mongo_record and '_id' in mongo_record:
                    published_records.append({
                        '_id': str(mongo_record['_id']),
                        'transcoderProcessingStatus': 'queued'
                    })
            except Exception as e:
                print(f"Failed to publish record {record.get('sourceVideoId')}: {e}")

        if published_records:
            updated_count = self.db.update_records_in_mongodb(published_records)
            print(f"Updated {updated_count} records to 'queued' status.")


def main(param_ph):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=_zone)}")

    exe = Execute()
    exe.run()

    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=_zone)}")
    return {'status': 'success'}
