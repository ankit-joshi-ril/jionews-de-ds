import base64
import json
import time
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytz
from bson import ObjectId
from google.cloud import secretmanager, pubsub_v1
from pymongo import MongoClient, errors, UpdateOne

# Ignore all warnings
warnings.filterwarnings("ignore")

_run_local = False
_zone = ZoneInfo("Asia/Kolkata")


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
        self.pubsub = pubsub_v1.PublisherClient()

    def publish_message_to_topic(self, topic_name, data):

        topic_path = self.pubsub.topic_path(self.project_id, topic_name)
        json_string = json.dumps(data)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            self.pubsub.publish(topic_path, data=message_bytes)
            # ps_future = self.pubsub.publish(topic_path, data=message_bytes)
            # ps_result = ps_future.result()
            # print(f"Message published with result:: {ps_result}")
            print(f"Message published!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


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
                    'contentType': 'videos',
                    'processingStatus': 'completed',
                    # 'createdAt': {
                    #     '$gte': 1769884200
                    # },
                    #         'src': {
                    #     '$in': [
                    #         'publisher_mrss', 'api'
                    #     ]
                    # },
                    'transcoderProcessingStatus': {
                        '$in': [
                            'initiated'
                            # '', None # Pausing
                        ]
                    }
                }
            }, {
                '$sort': {
                    'createdAt': -1
                }
            }, {
                '$limit': 30
            }, {
                '$project': {
                    '_id': 0
                }
            }
        ]

        try:
            records = list(self.raw_videos_rss.aggregate(pipeline))
            if len(records) == 0:
                print("No records found matching the criteria.")
                return None
            else:
                return records
        except Exception as e:
            print(f"Failed to fetch records from MongoDB: {e}")
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


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.db = MongoDB()

    def run(self):
        print("Fetching records from MongoDB...")
        filtered_records = self.db.fetch_records_from_mongo()
        print(f"Fetched {len(filtered_records) if filtered_records else 0} records from MongoDB.")
        if not filtered_records:
            print("No records found for processing.")
            return

        # Track successfully published records for status update
        published_records = []

        for record in filtered_records:
            try:
                self.pubsub.publish_message_to_topic("transcoder-push-to-sftp-batching", [record])
                # Collect record for status update (need to fetch _id separately)
                mongo_record = self.db.get_mongo_record(record.get('sourceVideoId'))
                if mongo_record and '_id' in mongo_record:
                    published_records.append({
                        '_id': str(mongo_record['_id']),
                        'transcoderProcessingStatus': 'queued'
                    })
            except Exception as e:
                print(f"Failed to publish record {record.get('sourceVideoId')}: {e}")

        # Update status to 'queued' for all successfully published records
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