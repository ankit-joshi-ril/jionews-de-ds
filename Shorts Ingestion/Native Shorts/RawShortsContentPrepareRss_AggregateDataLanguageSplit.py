import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from google.cloud import pubsub_v1
from google.cloud import secretmanager
from pymongo import MongoClient


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
            pubsub.publish(topic_path, data=message_bytes)
        except Exception as err:
            print(f"Message Publishing Error: {err}")


class MongoDB:
    def __init__(self, pubsub):
        self.pubsub = pubsub
        self.secret_name = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        connection_uri_de = self.get_secret()
        de_client = MongoClient(connection_uri_de)
        ingestion_db = de_client['ingestion-data']
        # self.shorts_collection = ingestion_db['raw_short_videos_ingestion_data']
        self.shorts_collection = ingestion_db['raw_videos_rss']

    def get_secret(self):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": self.secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload

    def map_categories(self, data):
        categories = {
            "news": "news",
            "cricket": "sports",
            "business": "business news",
            "technology": "science and technology",
            "automotive": "automobile",
            "entertainment": "entertainment",
            "health": "health",
            "spiritual": "astrology",
            "astrology": "astrology",
            "fashion": "lifestyle",
            "travel": "lifestyle",
            "food": "lifestyle",
            "diy": "lifestyle",
            "sports": "sports",
            "career": "education",
            "football": "sports",
            "agro": "news"
        }

        transformed_data = []

        for language_recs in data:
            language = language_recs['language']
            recs = language_recs['topVideos']

            for rec in recs:
                try:
                    rec['sourceCategoryName'] = categories[rec['sourceCategoryName']]
                except:
                    rec['sourceCategoryName'] = 'news'

            transformed_data.append({'language': language, 'topVideos': recs})

        return transformed_data

    def aggregate_top_videos(self):
        aggregated_data = []
        # pipeline = [
        #     {
        #         "$match": {
        #             "processingStatus": "completed",
        #             'contentType': "shorts"
        #         }
        #     },
        #     {
        #         '$project': {
        #             '_id': 0
        #         }
        #     },
        #     {
        #         "$sort": {
        #             "createdAt": -1
        #         }
        #     },
        #     {
        #         "$group": {
        #             "_id": {
        #                 "language": "$sourceLanguageId",
        #             },
        #             "topVideos": {
        #                 "$push": "$$ROOT"
        #             }
        #         }
        #     },
        #     {
        #         "$project": {
        #             "_id": 0,
        #             "language": "$_id.language",
        #             "topVideos": {
        #                 "$slice": ["$topVideos", 100]
        #             }
        #         }
        #     }
        # ]

        pipeline = [
            {
                "$match": {
                    "processingStatus": "completed",
                    "contentType": "shorts"
                }
            },
            {
                '$project': {
                    '_id': 0
                }
            },
            {
                "$setWindowFields": {
                    "partitionBy": "$sourceLanguageId",
                    "sortBy": {"createdAt": -1},
                    "output": {
                        "rank": {"$documentNumber": {}}
                    }
                }
            },
            {
                "$match": {
                    "rank": {"$lte": 100}
                }
            },
            {
                "$group": {
                    "_id": "$sourceLanguageId",
                    "topVideos": {"$push": "$$ROOT"}
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "language": "$_id",
                    "topVideos": 1
                }
            }
        ]

        try:
            aggregated_data = list(self.shorts_collection.aggregate(pipeline, allowDiskUse=True))
        except Exception as e:
            print(f"Exception caught in Mongo aggregation:{e}")

        return aggregated_data

    def publish_data_in_chunks(self, data):
        """
        Split data language-category combination data and push into pubsub.
        :param data:
        :return:
        """

        for batch in data:
            self.pubsub.publish_message_to_topic("RawShortsContentPrepareRss_AggregatedDataLanguageSplit", batch)


class Execute:
    def __init__(self):
        print("execution started")
        self.ps = PubSub()
        self.mongo = MongoDB(self.ps)

    def run(self):
        """
        ->First, run mongo aggregation to fetch top 100 records for each language
        ->Split the aggregated data and push to pubsub for further rss feed creation
        :return:
        """
        aggregated_data = self.mongo.aggregate_top_videos()
        transformed_data = self.mongo.map_categories(aggregated_data)

        # Save file locally
        # with open('transformed_data_shorts.json', 'w') as f:
        #     json.dump(transformed_data, f, indent=4)

        print(f"Total {len(transformed_data)} lang batches aggregated")
        self.mongo.publish_data_in_chunks(transformed_data)


def main(req_param_ph):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute()
    exe.run()
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}