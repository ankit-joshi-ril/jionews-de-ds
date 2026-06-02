import json
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import isodate
import pandas as pd
import requests
from google.cloud import pubsub_v1
from google.cloud import secretmanager


# from urllib3.exceptions import InsecureRequestWarning

# Filter out the specific warning
# warnings.filterwarnings("ignore", category=InsecureRequestWarning)


class Utils:
    @staticmethod
    def save_output_to_file(output, output_type, file_name):
        out_dir = 'out/'
        file_path = f'{out_dir + file_name}.{output_type}'
        print(f'file_path: {file_path}')

        if output_type == 'csv':
            if isinstance(output, str):
                # If the output is a CSV string, directly write it to the file
                with open(file_path, 'w') as file:
                    file.write(output)
            elif isinstance(output, pd.DataFrame):
                # If the output is a pandas DataFrame, save it to a CSV file
                output.to_csv(file_path, index=False)
            else:
                raise ValueError("Invalid output format for CSV.")
        elif output_type == 'json':
            if isinstance(output, str):
                # If the output is a JSON string, directly write it to the file
                with open(file_path, 'w') as file:
                    file.write(output)
            elif isinstance(output, dict):
                # If the output is a JSON object, convert it to a JSON string and save it to the file
                with open(file_path, 'w') as file:
                    json.dump(output, file)
            else:
                raise ValueError("Invalid output format for JSON.")
        else:
            raise ValueError("Invalid output type. Supported types: 'csv', 'json.'")

    @staticmethod
    def iso8601_to_seconds(duration_str):
        duration = isodate.parse_duration(duration_str)
        return int(duration.total_seconds())

    @staticmethod
    def json_string_to_dict(json_string):
        try:
            # Use json.loads() to parse the JSON string into a dictionary
            data_dict = json.loads(json_string)
            return data_dict
        except json.JSONDecodeError:
            # Handle the case when the JSON string is invalid
            print("Error: Invalid JSON string.")
            return None

    @staticmethod
    def read_json_file(file_path):
        try:
            # Read the content of the file
            with open(file_path, 'r') as file:
                json_string = file.read()
                # Use json.loads() to parse the JSON string into a dictionary
                data_dict = json.loads(json_string)
                return data_dict
        except FileNotFoundError:
            print("Error: File not found.")
            return None
        except json.JSONDecodeError:
            # Handle the case when the JSON content is invalid
            print("Error: Invalid JSON content.")
            return None

    @staticmethod
    def load_config():
        with open('config.json') as config_file:
            config = json.load(config_file)
        return config

    @staticmethod
    def convert_to_epoch(date_str):
        try:
            # Parse the date string into a datetime object
            date_time = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')

            # Convert the datetime object to epoch time in seconds
            epoch_time = int(date_time.timestamp())
            return epoch_time
        except ValueError:
            print("Error: Invalid date format.")
            return None

    @staticmethod
    def epoch_now():
        zone = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=zone)
        return int(now.timestamp())

    @staticmethod
    def process_list_in_batches(inp_list, batch_size, method_to_be_executed):
        for i in range(0, len(inp_list), batch_size):
            batch = inp_list[i:i + batch_size]
            method_to_be_executed(batch)

    @staticmethod
    def get_object_node(dict_object, path_to_node):
        """
        path_to_node is a dot separated string to the target node path
        """
        target_node = dict_object
        for curr_node in path_to_node.split('.'):
            if curr_node.isdigit():
                curr_node = int(curr_node)
            target_node = target_node[curr_node]
        return target_node

    @staticmethod
    def get_secret(secret_name):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload

    @staticmethod
    def is_image_url_valid(image_url):
        try:
            response = requests.get(image_url)
            if response.status_code == 200:
                return image_url
            else:
                return ""
        except Exception as e:
            print("Error:", e)
            return ""

    @staticmethod
    def replace_http_with_https(text):
        return re.sub(r'http://(\S+)', r'https://\1', text)


class Logger:
    def __init__(self, debug_on):
        self.debug_on = debug_on

    def debug(self, print_val):
        if self.debug_on:
            print(f"--debug::: {print_val}")
        else:
            pass


class Publishers:
    def __init__(self, debug, pub_list_path='publishers.csv'):
        self.all_publishers = pd.read_csv(pub_list_path)
        self.debug = debug
        # print(self.all_publishers)


# class MongoDB:
#     def __init__(self, debug):
#         self.debug = debug
#         self.debug("Establishing MongoDB connection")
#         # self.config = Utils.load_config()
#         secret_name = f"projects/266686822828/secrets/mongosh_de_uri/versions/latest"
#         self.connection_uri_de = Utils.get_secret(secret_name)
#         # self.connection_uri_de = f"mongodb+srv://{self.config['mongodb_creds']['id']}:{self.config['mongodb_creds']['pw']}@jio-news-de-cluster-v2.7azsc.mongodb.net/?retryWrites=true&w=majority"
#         # self.connection_uri_de = f"mongodb://{self.config['mongodb_creds']['id']}:{self.config['mongodb_creds']['pw']}@jionews-de-mongo-replica1.pie.news:54545/?tls=true&directConnection=true"
#         self.de_client = MongoClient(self.connection_uri_de, tlsCAFile=certifi.where())
#         self.ingestion_db = self.de_client['ingestion-data']
#         # self.short_videos_ingest_collection = self.ingestion_db['raw_short_videos_ingestion_data']
#         self.raw_web_stories_ingestion_data = self.ingestion_db['raw_web_stories_ingestion_data']
#         self.debug("Connected!")
#
#     def ingest(self, data):
#         if len(data) > 0:
#             print(f"Total records: {len(data)}")
#             try:
#                 self.raw_web_stories_ingestion_data.insert_many(data, ordered=False)
#                 print(f"{len(data)} total documents inserted")
#             except BulkWriteError as bwe:
#                 num_inserted = bwe.details['nInserted']
#                 num_skipped = len(data) - num_inserted
#                 print(f"{num_inserted} documents inserted!")
#                 print(f"{num_skipped} documents were duplicates and skipped.")
#         else:
#             print("No Webstories Fetched")
#
#     def close_clients(self):
#         self.de_client.close()
#
#     def remove_duplicates_by_field(self, field_name):
#
#         # Create an aggregation pipeline to identify duplicates based on the specified field
#         pipeline = [
#             {'$group': {'_id': f"${field_name}", 'duplicates': {'$push': '$_id'}, 'count': {'$sum': 1}}},
#             {'$match': {'count': {'$gt': 1}}}
#         ]
#
#         duplicates_cursor = self.raw_web_stories_ingestion_data.aggregate(pipeline)
#
#         # Iterate over the duplicates and keep one document for each distinct value
#         for duplicate in duplicates_cursor:
#             duplicates_to_keep = duplicate['duplicates'][1:]  # Keep one document and remove the rest
#             self.raw_web_stories_ingestion_data.delete_many({'_id': {'$in': duplicates_to_keep}})


class PubSub:
    def __init__(self, debug):
        self.debug = debug
        self.topic_name = "RawWebStoriesIngestion"
        self.project_id = "jiox-328108"
        self.pubsub = pubsub_v1.PublisherClient()
        self.topic_path = self.pubsub.topic_path(self.project_id, self.topic_name)

    def publish_message_to_topic(self, data):
        project_id = "jiox-328108"
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(project_id, self.topic_name)

        json_string = json.dumps(data)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            pubsub.publish(topic_path, data=message_bytes)
            # ps_future = pubsub.publish(topic_path, data=message_bytes)
            # ps_result = ps_future.result()
            # print(f"Message published with result:: {ps_result}")
            print(f"Message published!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")


class WebStories:
    def __init__(self, debug):
        self.debug = debug

    def api_get_json(self, url):
        try:
            response = requests.get(url)
            data = response.json()
            return data
        except requests.exceptions.SSLError:
            response = requests.get(url, verify=False)
            data = response.json()
            return data
        except Exception as e:
            print(f"Error fetching api:: {e}")
            return {}

    def feed_get_json(self, url):
        try:
            feed = feedparser.parse(url)
            return feed
        except Exception as e:
            print(f"Error fetching api:: {e}")
            return {}

    def process_api(self, publisher_data):
        data_list = []
        publisher_name = publisher_data['sys_pub_name']
        url = publisher_data['endpoint']
        data_list_path = publisher_data['data_list_path']
        # self.debug(f"publisher_name:{publisher_name}, url:{url}, data_list_path:{data_list_path}")

        raw_json = self.api_get_json(url)
        # self.debug(f"raw_json:{raw_json}")
        if len(raw_json) > 0:
            data_list = Utils.get_object_node(raw_json, data_list_path)
            # self.debug(f"data_list size: {len(data_list)} ::: sample: {data_list[0]}")
            self.debug(f"publisher_name:{publisher_name}, data_list size: {len(data_list)}")
            return data_list
        else:
            return data_list

    def process_feed(self, publisher_data):
        data_list = []
        publisher_name = publisher_data['sys_pub_name']
        url = publisher_data['endpoint']

        feed = self.feed_get_json(url)
        data_list = feed.entries

        self.debug(f"publisher_name:{publisher_name}, data_list size: {len(data_list)}, endpoint: {url}")

        return data_list

    def transform(self, record, publisher_data):
        try:
            mapping = json.loads(publisher_data['mapping'])
            if len(mapping) == 0:
                return {}
        except Exception as e:
            print(f"Exception caught while reading the mapping for {publisher_data['sys_pub_name']}::: {e}")
            return {}

        try:
            if mapping['sourceThumbnailUrl'] == "":
                source_thumbnail_url = ""
                self.debug("No thumbnail URL for this publisher")
            elif '.' in mapping['sourceThumbnailUrl']:
                source_thumbnail_url = Utils.get_object_node(record, mapping['sourceThumbnailUrl'])
                self.debug("Thumbnail URL with path")
            else:
                source_thumbnail_url = record[mapping['sourceThumbnailUrl']]
                self.debug(f"Normal Thumbnail URL with field: {mapping['sourceThumbnailUrl']}")

            # Replace http with https for urls and image urls, append UTM param for sourceURLs
            source_url = Utils.replace_http_with_https(record[mapping['sourceURL']])
            source_thumbnail_url = Utils.replace_http_with_https(source_thumbnail_url)
            if source_url:
                source_url = source_url + "?utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories"

            # Check if source thumbnail image is valid, else return empty string
            source_thumbnail_url = Utils.is_image_url_valid(source_thumbnail_url)

            transformed_record = {
                'sourceId': record[mapping['sourceId']],
                'title': record[mapping['title']],
                'sourcePublishedDate': record[mapping['sourcePublishedDate']],
                'sourceCategoryName': publisher_data['category'],
                'sourceLanguageName': publisher_data['language'],
                'sourcePublisherName': publisher_data['sys_pub_name'],
                'sourceURL': source_url,
                'sourceThumbnailUrl': source_thumbnail_url,
                'createdAt': Utils.epoch_now()
            }
            return transformed_record
        except Exception as e:
            print(f"Exception caught while maaping record for {publisher_data['sys_pub_name']}::: {e}")
            return {}

    def process(self, publishers_data, pubsub):
        raw_data_list = []
        transformed_data_list = []

        sample_recs = {}
        # Iterate through each publisher
        for i, row in publishers_data.iterrows():
            print(f"publisher: {row['sys_pub_name']}")
            processing_type = row['type'].lower()
            mapping = row['mapping']
            self.debug(f"processing_type:: {processing_type}")
            # print(f"Publisher: {row['sys_pub_name']}, type:{type(mapping)} Mapping-->{mapping}<--")
            # continue

            # Fetch respective type publisher webstories data_list
            if str(mapping) in ['nan', None, ""]:
                continue
            if processing_type == 'api':
                raw_data_list = self.process_api(row)
                self.debug(f"Total {len(raw_data_list)} records fetched for {row['sys_pub_name']}")
            elif processing_type == 'feed':
                raw_data_list = self.process_feed(row)
                self.debug(f"Total {len(raw_data_list)} records fetched for {row['sys_pub_name']}")

            if len(raw_data_list) > 0:
                sample_recs[row['endpoint']] = raw_data_list[0]

            # Transform the data list
            for record in raw_data_list:
                transformed_record = self.transform(record, row)
                self.debug(f"transformed_record:: {transformed_record}")
                if len(transformed_record) > 0:
                    transformed_data_list.append(transformed_record)

            self.debug(f"transformed_data_list: {transformed_data_list}")

            # Push into MongoDB
            # db.ingest(transformed_data_list)

            # publish to pubsub
            pubsub.publish_message_to_topic(transformed_data_list)

        # print(f"total sample recs: {len(sample_recs)}")
        # print(f"sample_recs::: {sample_recs}")
        # Utils.save_output_to_file(sample_recs, 'json', 'all_publishers_sample_recs')


class Execute:
    """
    -> Get all the publisher details 'from publishers.csv'
    -> Iterate through all the publishers
    -> Have separate handling for API and Feed URLs
    """

    def __init__(self, debugger=True):
        print("execution started")
        self.logger = Logger(debugger)
        self.debug = self.logger.debug
        self.pub = Publishers(self.debug)
        # self.db = MongoDB(self.debug)
        self.webst = WebStories(self.debug)
        self.pubsub = PubSub(self.debug)

    def run(self):
        publishers_data: pd.DataFrame = self.pub.all_publishers
        print()
        self.webst.process(publishers_data, self.pubsub)
        # self.db.close_clients()


def main(req_ph):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    # try:
    exe = Execute(debugger=False)
    exe.run()
    # except Exception as e:
    #     print(f"Exception caught::\n{e}")
    # finally:
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}

# main({})