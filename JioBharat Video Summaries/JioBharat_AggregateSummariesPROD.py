import base64
import collections
import json
import time
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytz
from google.cloud import pubsub_v1, secretmanager
from pymongo import MongoClient, errors

warnings.filterwarnings("ignore")

_zone = ZoneInfo("Asia/Kolkata")


class Utils:
    @staticmethod
    def generate_epoch_range(interval_minutes):
        # Define the timezone for Asia/Kolkata
        timezone = pytz.timezone('Asia/Kolkata')

        # Get the current time in Asia/Kolkata timezone
        now = datetime.now(timezone)

        # Calculate the previous interval's start time
        start_minute = (now.minute // interval_minutes) * interval_minutes - interval_minutes
        start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=start_minute)

        # Calculate the end time
        end_time = start_time + timedelta(minutes=interval_minutes) - timedelta(seconds=1)

        # Convert the start time and end time to epoch
        start_epoch = int(start_time.timestamp())
        end_epoch = int(end_time.timestamp())

        return {'start_epoch': start_epoch, 'end_epoch': end_epoch}

    @staticmethod
    def generate_day_epoch_range():
        # Define the timezone for Asia/Kolkata
        timezone = pytz.timezone('Asia/Kolkata')

        # Get the current time in Asia/Kolkata timezone
        now = datetime.now(timezone)

        # Calculate the start of the day
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate the end of the day
        end_of_day = start_of_day + timedelta(hours=23, minutes=59, seconds=59)

        # Convert the start time and end time to epoch
        start_epoch = int(start_of_day.timestamp())
        end_epoch = int(end_of_day.timestamp())

        return {'start_epoch': start_epoch, 'end_epoch': end_epoch}

    @staticmethod
    def encode_base64(data):
        return base64.b64encode(data.encode()).decode()

    @staticmethod
    def decode_base64(data):
        return base64.b64decode(data).decode()


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

    def publish_message_to_topic(self, topic_name, data):
        # publish_data = []
        # publish_data.append(data)
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(self.project_id, topic_name)

        json_string = json.dumps(data)
        print(f"Final JSON String for pubsub: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            res = pubsub.publish(topic_path, data=message_bytes)
            result = res.result()
            print(f"Message published successfully: {result}")
        except Exception as err:
            print(f"Message Publishing Error: {err}")


class MongoDB:
    def __init__(self):
        e_uri = "bW9uZ29kYitzcnY6Ly9kYXRhZnVzaW9uLXVzZXI6SGl5c2RFZGJ0ZXNzdHllZEcyczYzZEhAamlvbmV3cy1wcm9kLW1vbmdvLmppb25ld3MuY29tL3BpZS1wcm9kdWN0aW9uP3Rscz10cnVlJmF1dGhTb3VyY2U9YWRtaW4="
        self.connection_uri_prod = Utils.decode_base64(e_uri)
        try:
            self.prod_client = MongoClient(self.connection_uri_prod)
            self.prod_db = self.prod_client['pie-production']
            self.summaries_collection = self.prod_db['summaries']
            print("PROD: MongoDB connection established successfully.")
        except errors.ServerSelectionTimeoutError as err:
            print(f"PROD: Server selection timeout error: {err}")
        except errors.ConnectionFailure as err:
            print(f"PROD: Connection failure: {err}")
        except Exception as err:
            print(f"PROD: An error occurred: {err}")

        self.secret_name = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        connection_uri_de = self.get_secret()

        try:
            de_client = MongoClient(connection_uri_de)
            ingestion_db = de_client['ingestion-data']
            self.jio_bharat_summaries_collection = ingestion_db['jio_bharat_summaries']
            print("DE: MongoDB connection established successfully.")
        except errors.ServerSelectionTimeoutError as err:
            print(f"DE: Server selection timeout error: {err}")
        except errors.ConnectionFailure as err:
            print(f"DE: Connection failure: {err}")
        except Exception as err:
            print(f"DE: An error occurred: {err}")

    def get_secret(self):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": self.secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload

    def get_summaries(self):
        # epoch_range = Utils.generate_epoch_range(30)
        epoch_range = Utils.generate_day_epoch_range()
        print(f"Epoch Range: {epoch_range}")
        # epoch_range = {'start_epoch': 1742409000, 'end_epoch': 1742495399}
        start_epoch = epoch_range['start_epoch']
        end_epoch = epoch_range['end_epoch']

        pipeline = [
            {
                '$match': {
                    'createdAt': {
                        '$gte': start_epoch,
                        '$lte': end_epoch
                    },
                    'language.code': {
                        '$in': [
                            'HIN', 'TAM', 'TEL', 'KAN', 'MAR', 'BAN', 'MAL', 'GUJ'
                        ]
                    },
                    'isAudioSummaryGenerated': True,
                    'isBreaking': False
                }
            },
            {
                '$sort': {
                    'createdAt': -1
                }
            },
            {
                '$group': {
                    '_id': '$language.code',
                    'summaries': {
                        '$push': {
                            'summary_id': {
                                '$toString': '$_id'
                            },
                            'title': '$title',
                            'language': '$language.code',
                            'thumbnailUrl': '$thumbnailUrl.original',
                            'publisher': '$headlinePublisher.name',
                            'createdAt': '$createdAt'
                        }
                    }
                }
            },
            {
                '$project': {
                    '_id': 0,
                    'summaries': {
                        '$slice': ['$summaries', 50]
                    }
                }
            },
            {
                '$unwind': '$summaries'
            },
            {
                '$replaceRoot': {
                    'newRoot': '$summaries'
                }
            }
        ]

        data = list(self.summaries_collection.aggregate(pipeline))
        return data

    def filter_unprocessed_summaries(self, summaries):
        # Extract summary_ids from the summaries list
        summary_ids = [summary['summary_id'] for summary in summaries]

        # Query to find processed summaries
        processed_summaries = self.jio_bharat_summaries_collection.find(
            {'summary_id': {'$in': summary_ids}, 'isSuccess': True},
            {'summary_id': 1, '_id': 0}
        )

        # Create a set of processed summary_ids
        processed_summary_ids = {summary['summary_id'] for summary in processed_summaries}

        # Filter out processed summaries
        unprocessed_summaries = [summary for summary in summaries if summary['summary_id'] not in processed_summary_ids]

        return unprocessed_summaries

    def __del__(self):
        self.prod_client.close()


class Execute:
    def __init__(self):
        print("execution started")
        self.pubsub = PubSub()
        self.db = MongoDB()

    def get_language_count(self, all_summaries):
        language_counts = collections.defaultdict(int)
        for summary in all_summaries:
            language_counts[summary['language']] += 1
        language_counts = dict(language_counts)
        return language_counts

    def run(self):
        print("Fetchin Summaries")
        summaries = self.db.get_summaries()
        print(f"Total Summaries: {len(summaries)}")

        language_counts = self.get_language_count(summaries)
        print(f"Language split count: {language_counts}")

        print("Filtering unprocessed summaries")
        summaries = self.db.filter_unprocessed_summaries(summaries)
        print(f"Total Summaries after filtering: {len(summaries)}")

        language_counts = self.get_language_count(summaries)
        print(f"Language split count after filtering: {language_counts}")

        # with open("summaries_sample.json", "w") as f:
        #     json.dump(summaries, f)

        self.pubsub.publish_message_to_topic("JioBharat_AggregateSummariesProd", summaries)


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