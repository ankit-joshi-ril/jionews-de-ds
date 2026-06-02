import json
import time
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import certifi
import isodate
import pandas as pd
import requests
from bs4 import BeautifulSoup
from google.cloud import pubsub_v1
from google.cloud import secretmanager
from google.cloud import storage
from pymongo import MongoClient


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


class GCS:
    def __init__(self):
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "shorts/shorts_publishers.csv"
        self.publishers_config = None

    def read_csv_from_gcs(self):
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes), encoding='ISO-8859-1')
        self.publishers_config = df


# class Publishers:
#     def __init__(self, debug, pub_list_path='ShortsPublisherDetails.csv'):
#         self.all_publishers_channels = pd.read_csv(pub_list_path)
#         self.debug = debug
#         # print(self.all_publishers_channels)
#
#     def get_channel_ids_as_str(self):
#         return ','.join(list(self.all_publishers_channels['channel_id'][50:]))


class Scrapper:
    def __init__(self, debug):
        self.debug = debug

    def fetch_html(self, publisher_custom_url: str):
        """
        Scrapes HTML of the YT channel shorts page.
        :param publisher_custom_url: unique channel ID/name appended with '@' | eg.: @bqprime
        :return: Raw HTML String
        """
        url = f"http://www.youtube.com/{publisher_custom_url}/shorts"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        try:
            response = requests.get(url, timeout=10, headers=headers)
            return response.text
        except Exception as e:
            print(f"Exception caught fetching {url}: {e}")
            return ""

    @staticmethod
    def _find_all(data, key, _depth=0, _max_depth=20):
        """Recursively collect all values for a given key in nested dicts/lists."""
        if _depth > _max_depth:
            return []
        results = []
        if isinstance(data, dict):
            if key in data:
                results.append(data[key])
            for v in data.values():
                results.extend(Scrapper._find_all(v, key, _depth + 1, _max_depth))
        elif isinstance(data, list):
            for item in data:
                results.extend(Scrapper._find_all(item, key, _depth + 1, _max_depth))
        return results

    def extract_video_ids(self, html_string: str):
        """
        Extracts YT shorts videoIds from raw HTML page.
        Handles both the legacy layout (videoRenderer / videoId) and the
        2024+ layout (lockupViewModel / contentId).
        :param html_string: Raw HTML string
        :return: List of unique video ID strings
        """
        soup = BeautifulSoup(html_string, 'html.parser')

        # Selector fixed: look for ytInitialData tag, not 'videoId' in text
        # (new lockupViewModel pages don't contain the string 'videoId' at all)
        yt_data_tags = [t for t in soup.find_all('script') if 'ytInitialData' in (t.string or '')]
        if not yt_data_tags:
            print(f"extract_video_ids: no ytInitialData script tag found - bot/consent page?")
            return []

        script_content = yt_data_tags[0].string
        start_index = script_content.find('{"responseContext"')
        if start_index == -1:
            print(f"extract_video_ids: responseContext marker not found in ytInitialData")
            return []

        end_index = script_content.rfind('}};') + 2
        if end_index <= start_index:
            end_index = len(script_content)

        try:
            yt_initial_data = json.loads(script_content[start_index:end_index])
        except json.JSONDecodeError as e:
            print(f"extract_video_ids: JSON parse error - {e}")
            return []

        # Layout A: legacy videoRenderer (videoId field)
        video_ids = list(set(self._find_all(yt_initial_data, 'videoId')))

        if video_ids:
            return video_ids

        # Layout B: 2024+ lockupViewModel (contentId field, type must be VIDEO)
        lvm_list = self._find_all(yt_initial_data, 'lockupViewModel')
        ids_from_lvm = []
        for lvm in lvm_list:
            if not isinstance(lvm, dict):
                continue
            if lvm.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
                continue
            cid = lvm.get('contentId', '')
            if cid:
                ids_from_lvm.append(cid)
        return list(set(ids_from_lvm))

    def scrape_channel_shorts(self, publisher_custom_url: str):
        """
        Extracts and curates YT shorts videoIds from YT shorts page.
        :param publisher_custom_url: unique channel ID/name appended with '@' | eg.: @bqprime
        :return: List of video ID strings (may be empty on failure)
        """
        html_string = self.fetch_html(publisher_custom_url)
        if not html_string:
            return []
        video_ids = []
        try:
            video_ids = self.extract_video_ids(html_string)
        except Exception as e:
            print(f"Exception caught while parsing HTML for channel: {publisher_custom_url}")
        return video_ids


class MongoDB:
    def __init__(self, debug):
        self.debug = debug
        self.debug("Establishing MongoDB connection")
        # self.config = Utils.load_config()
        secret_name = f"projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        self.connection_uri_de = Utils.get_secret(secret_name)
        # self.connection_uri_de = f"mongodb+srv://{self.config['mongodb_creds']['id']}:{self.config['mongodb_creds']['pw']}@jio-news-de-cluster-v2.7azsc.mongodb.net/?retryWrites=true&w=majority"
        # New self-hosted instance
        # self.connection_uri_de = f"mongodb://{self.config['mongodb_creds']['id']}:{self.config['mongodb_creds']['pw']}@jionews-de-mongo-master.pie.news:54545/?tls=true&directConnection=true"
        self.de_client = MongoClient(self.connection_uri_de, tlsCAFile=certifi.where())
        self.ingestion_db = self.de_client['ingestion-data']
        self.short_videos_ingest_collection = self.ingestion_db['raw_short_videos_ingestion_data']
        self.debug("Connected!")

    def close_clients(self):
        self.de_client.close()

    def filter_missing_video_ids(self, video_ids: list):
        agg_out = list(self.short_videos_ingest_collection.aggregate([{"$match": {"sourceVideoId": {"$in": video_ids}}},
                                                                      {"$project": {"_id": 0, "sourceVideoId": 1}}]))
        existing_video_ids = [video_rec['sourceVideoId'] for video_rec in agg_out]
        missing_video_ids = list(set(video_ids) - set(existing_video_ids))
        return missing_video_ids

    def remove_duplicates_by_field(self, field_name):
        # Create an aggregation pipeline to identify duplicates based on the specified field
        pipeline = [
            {'$group': {'_id': f"${field_name}", 'duplicates': {'$push': '$_id'}, 'count': {'$sum': 1}}},
            {'$match': {'count': {'$gt': 1}}}
        ]

        duplicates_cursor = self.short_videos_ingest_collection.aggregate(pipeline)

        # Iterate over the duplicates and keep one document for each distinct value
        for duplicate in duplicates_cursor:
            duplicates_to_keep = duplicate['duplicates'][1:]  # Keep one document and remove the rest
            self.short_videos_ingest_collection.delete_many({'_id': {'$in': duplicates_to_keep}})


class PubSub:
    def __init__(self, debug):
        self.debug = debug
        self.pubsub = pubsub_v1.PublisherClient()
        self.topic_name = "cron_based_raw_youtube_shorts_ingestion"
        self.project_id = "jiox-328108"

    def publish(self, data):
        json_string = json.dumps(data)
        # print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")

        try:
            topic_path = self.pubsub.topic_path(self.project_id, self.topic_name)
            self.pubsub.publish(topic_path, data=message_bytes)
            print("Message published.")
        except Exception as err:
            print(f"Message Publishing Error: {err}")


class Execute:
    """
    ->Load All Publishers
    ->Get all Video IDs from Channel IDs --YouTube Search:list API
    ->
    """

    def __init__(self, debugger=True):
        print("execution started")
        self.logger = Logger(debugger)
        self.debug = self.logger.debug
        # self.pub = Publishers(self.debug)

        self.gcs = GCS()
        self.gcs.read_csv_from_gcs()
        self.publishers_config = self.gcs.publishers_config

        self.sc = Scrapper(self.debug)
        self.db = MongoDB(self.debug)
        self.ps = PubSub(self.debug)

    def run(self):
        # all_channel_custom_urls = list(self.pub.all_publishers_channels['custom_url'])
        all_channel_custom_urls = list(self.publishers_config['custom_url'])
        for channel in all_channel_custom_urls:
            scraped_video_ids = self.sc.scrape_channel_shorts(channel)
            filtered_video_ids = self.db.filter_missing_video_ids(scraped_video_ids)
            print(
                f"Channel {channel}, Scraped: {len(scraped_video_ids)}, Filtered: {len(filtered_video_ids)}")
            if len(filtered_video_ids) > 0:
                self.ps.publish(filtered_video_ids)
        self.db.close_clients()


def main(req_param_ph):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    # try:
    exe = Execute(debugger=False)
    exe.run()
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}

# main("req")
