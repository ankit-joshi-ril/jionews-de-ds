import base64
import csv
import io
import json
import time
import warnings
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import pytz
import redis
import requests
from dateutil import parser
from google.cloud import pubsub_v1
from google.cloud import storage
from urllib3.exceptions import InsecureRequestWarning

# Filter out the specific warning
warnings.filterwarnings("ignore", category=InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)


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
            if 'T' in date_str:
                date_time = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
            else:
                date_time = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S.%f%z')

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
    def convert_dicts_to_csv_string(data_list):
        if not data_list:
            return ''
        fieldnames = data_list[0].keys()
        csv_output = io.StringIO()
        writer = csv.DictWriter(csv_output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data_list)

        csv_string = csv_output.getvalue()
        csv_output.close()

        return csv_string

    @staticmethod
    def generic_parse_date(date_string):
        try:
            # Attempt to parse the date using dateutil's parser
            parsed_date = parser.parse(date_string)
            return parsed_date
        except (ValueError, TypeError) as e:
            # Return None or raise an error if parsing fails
            print(f"Error parsing date, date_string - {date_string}: {e}")
            return None


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

    def publish_message(self, records):
        json_string = json.dumps(records)
        self.debug(f"PubSub Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            self.pubsub.publish(self.topic_path, data=message_bytes)
            print("Message published.")
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    @staticmethod
    def publish_message_to_topic(topic_name, data):
        project_id = "jiox-328108"
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(project_id, topic_name)

        json_string = json.dumps(data)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            pubsub.publish(topic_path, data=message_bytes)
            # ps_future = pubsub.publish(topic_path, data=message_bytes)
            # ps_result = ps_future.result()
            # print(f"Message published with result:: {ps_result}")
            # print(f"Message published!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class GCS:
    def __init__(self, debug):
        self.debug = debug
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "videos/videos_publishers_config.csv"
        self.publishers_config = None

    def read_csv_from_gcs(self):
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes), encoding='ISO-8859-1')
        self.publishers_config = df

    def save_data_string_to_cloud_storage(self, data, bucket_name, destination_blob_name):
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(data)


class Processor:
    def __init__(self, debug, publishers_config, ps):
        self.debug = debug
        self.publishers_config = publishers_config
        self.ps = ps
        self.max_threads = 50
        self.all_feeds_data = []
        self.empty_feeds = 0
        self.non_existing_records = []
        self.cdn_image_data = []
        # self.image_url_mappings = []

        self.redis_url = "redis://:u4YIVWZBcNiYCPFj!@35.200.220.40:6379"
        self.redis_client = redis.StrictRedis.from_url(self.redis_url)
        self.set_name = "de_videos_id_cache"
        self.expiration_seconds = 48 * 3600  # 48 hours in seconds

    def is_within_last_24_hours(self, date_string):
        # Parse the date string
        parsed_date = Utils.generic_parse_date(date_string)

        if parsed_date is None:
            return False

        # Get the current time in IST
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist)

        # Convert parsed date to IST
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=ist)
        parsed_date_ist = parsed_date.astimezone(ist)

        # Calculate the time difference
        time_difference = current_time - parsed_date_ist

        # Check if the parsed date is not older than the last 24 hours (allow future dates)
        return time_difference <= timedelta(days=1)

    def _get_current_timestamp(self):
        return int(time.time())

    def filter_records_from_cache(self, all_records, category_id, language_id):
        non_existing_records = []
        current_timestamp = self._get_current_timestamp()
        # # Turing off deduplication
        # non_existing_records = data
        # return None

        for rec in all_records:
            # Generate the compound key
            compound_key = f"{rec['video_id']}_{category_id}_{language_id}"
            rec['compound_key'] = compound_key

            # Check if the compound key exists in the ZSet
            if not self.redis_client.zscore(self.set_name, compound_key):
                # Add the record to non-existing records list
                non_existing_records.append(rec)

                # Add the compound key to the ZSet with expiration time
                self.redis_client.zadd(self.set_name, {compound_key: current_timestamp + self.expiration_seconds})

        self.non_existing_records = non_existing_records

    def cleanup_expired_keys(self):
        current_timestamp = self._get_current_timestamp()
        # Remove all records with scores (timestamps) older than the current time
        self.redis_client.zremrangebyscore(self.set_name, "-inf", current_timestamp)

    def analyze_get_image_thumbnail_url(self, record, publication_id):
        url = ""
        image_map = ""
        if 'media_content' in record and record['media_content']:
            url = record['media_content'][0]['url']
            image_map = 'media_content.0.url'
        elif 'media_thumbnail' in record and record['media_thumbnail']:
            url = record['media_thumbnail'][0]['url']
            image_map = 'media_thumbnail.0.url'
        elif 'thumbimage' in record:
            url = record['thumbimage']
            image_map = 'thumbimage'

        self.image_url_mappings.append({"publication_id": publication_id, "image_map": image_map})
        return url

    def get_image_thumbnail_url(self, record):
        if 'media_content' in record and record['media_content']:
            return record['media_content'][0]['url']
        elif 'media_thumbnail' in record and record['media_thumbnail']:
            return record['media_thumbnail'][0]['url']
        else:
            return record.get('thumbimage', "")

    def get_article_body(self, url):
        article_api_url = "http://34.36.231.72/crawl"
        headers = {
            'accept': 'application/json',
            'Content-Type': 'text/plain'
        }
        response = requests.post(article_api_url, headers=headers, data=url, timeout=15)
        response_json = response.json()
        return response_json

    def process_get_article(self, doc):
        url = doc['url']
        # source_id = doc['sourceId']
        # lang = doc['sourceLanguageName']
        # if lang != 'English':
        #     return ""
        article_body = ""
        article_response = None
        try:
            article_response = self.get_article_body(url)
            try:
                article_body = article_response['article_body']
            except:
                article_body = article_response['Result']['article_body']
            return article_body
        except Exception as e:
            return ""

    def process_mapping(self, record_data, default_values):

        # mapping_schema = json.loads(default_values["mapping_schema"][0])
        # record_data = record['feed_data']

        # Main mapping
        # title = Utils.get_object_node(record_data, )
        video_id = record_data['video_id']
        title = record_data['title']
        published_time = record_data['published_time']
        duration = record_data['duration']
        width = record_data['width']
        height = record_data['height']
        orientation = record_data['orientation']

        if not self.is_within_last_24_hours(published_time):
            return None

        (self.debug(f"default_values:: {default_values}"))
        source_language_id = str(default_values["language_id"].iloc[0])
        source_language_name = str(default_values["language"].iloc[0])
        source_category_id = str(default_values["category_id"].iloc[0])
        source_category_name = str(default_values["category"].iloc[0])
        source_publisher_id = str(default_values["publication_id"].iloc[0])
        source_publisher_name = str(default_values["publisher_name"].iloc[0])
        source_channel_id = str(default_values["channel_id"].iloc[0])
        to_scrape = bool(default_values["to_scrape"].iloc[0])

        final_record = {
            "sourceVideoId": video_id,
            "title": title,
            "sourceCategoryId": source_category_id,
            "sourceCategoryName": source_category_name,
            "sourceLanguageId": source_language_id,
            "sourceLanguageName": source_language_name,
            "sourceThumbnailURL": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            "sourceDate": published_time,
            "sourceEpoch": Utils.convert_to_epoch(published_time),
            "sourcePublisherId": source_publisher_id,
            "sourcePublisherName": source_publisher_name,
            "src": "youtube",
            "sourceExternalid": video_id,
            "sourceVideoWidth": width,
            "sourceVideoHeight": height,
            "sourceVideoOrientation": orientation,
            "createdAt": Utils.epoch_now(),

            "duration": duration,
            "sourceChannelID": source_channel_id,
            "thumbnailUrls": {
                "default": {
                    "url": f"https://i.ytimg.com/vi/{video_id}/default.jpg",
                    "width": 120,
                    "height": 90
                },
                "medium": {
                    "url": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                    "width": 320,
                    "height": 180
                },
                "high": {
                    "url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "width": 480,
                    "height": 360
                },
                "standard": {
                    "url": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                    "width": 640,
                    "height": 480
                },
                "maxres": {
                    "url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                    "width": 1280,
                    "height": 720
                }
            },
        }

        if to_scrape:
            final_record["src"] = "youtube_scraped"
            final_record[
                "url"] = f"https://vcdn.jionews.com/{video_id}_{source_publisher_name}_{source_language_name}_{source_category_name}.mp4/manifest.m3u8"
            final_record["bitrates"] = {
                "low": f"https://vcdn.jionews.com/{video_id}_{source_publisher_name}_{source_language_name}_{source_category_name}.mp4/360p.m3u8",
                "medium": f"https://vcdn.jionews.com/{video_id}_{source_publisher_name}_{source_language_name}_{source_category_name}.mp4/720p.m3u8",
                "high": f"https://vcdn.jionews.com/{video_id}_{source_publisher_name}_{source_language_name}_{source_category_name}.mp4/1080p.m3u8",
                "auto": f"https://vcdn.jionews.com/{video_id}_{source_publisher_name}_{source_language_name}_{source_category_name}.mp4/manifest.m3u8"
            }

        self.debug(f"final_record:: {final_record}")

        return final_record

    def process_all_records(self, publication_id):
        processed_data = []
        self.debug(f"self.non_existing_records: {self.non_existing_records}")
        default_values = self.publishers_config.query(f"publication_id == {publication_id}")
        to_scrape = bool(default_values["to_scrape"].iloc[0])
        for record in self.non_existing_records:
            # print(f"default_values: {default_values}")
            try:
                mapped_record = self.process_mapping(record, default_values)
                if mapped_record:
                    if to_scrape:
                        print(f"to_scrape: {to_scrape}")
                        self.ps.publish_message_to_topic("NewRawYoutubeScraper_metadata", mapped_record)
                    else:
                        processed_data.append(mapped_record)
            except Exception as e:
                print(f"Exception caught while mapping. publication_id:{publication_id}, Exception:{e}")
            # return processed_data
        return processed_data


class Execute:
    """
    -> Fetch publisher feed wise data from pubsub subscription.
    -> Deduplication logic to filter out existing record in bigquery.
    -> Curation & Data Mapping.
    -> Fetch article body through API
    -> publish processed records as pubsub messages for further consumption
    """

    def __init__(self, debugger=True):
        print("execution started")
        self.logger = Logger(debugger)
        self.debug = self.logger.debug
        self.ps = PubSub(self.debug)

        self.gcs = GCS(self.debug)
        self.gcs.read_csv_from_gcs()
        self.publishers_config = self.gcs.publishers_config
        self.processor = Processor(self.debug, self.publishers_config, self.ps)

    def run(self, message):
        videos_data = self.ps.parse_message(message)
        # videos_data = message  # Message format: {"publication_id": 12, "data": [...]}
        print(videos_data)
        all_records = videos_data['data']
        publication_id = videos_data['publication_id']
        print(f"Total {len(all_records)} records received")

        default_values = self.publishers_config.query(f"publication_id == {publication_id}")

        """Deduplication logic to filter out data already existing. url+categoryId+languageId"""
        source_language_id = str(default_values["language_id"].iloc[0])
        source_category_id = str(default_values["category_id"].iloc[0])

        self.processor.filter_records_from_cache(all_records, source_category_id, source_language_id)
        self.debug(
            f"Total {len(self.processor.non_existing_records)} unique records from {len(videos_data)} received")

        processed_data = self.processor.process_all_records(publication_id)

        print(f"Total processed records: {len(processed_data)}")
        if processed_data:
            PubSub.publish_message_to_topic("NewRawVideosIngestion_processed_data", processed_data)
        else:
            print("All records already in cache")

        # with open('videos_processed_data.json', "w") as json_file:
        #     json.dump(processed_data, json_file)


def main(message, context):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute(debugger=False)
    exe.run(message)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}

# main(message, context)