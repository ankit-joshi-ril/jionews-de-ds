import base64
import json
import time
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import certifi
import googleapiclient.discovery
import isodate
import pandas as pd
import requests
from google.cloud import pubsub_v1
from google.cloud import secretmanager
from google.cloud import storage
from googleapiclient.errors import HttpError
from pymongo import MongoClient
from pymongo.errors import BulkWriteError


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

    @staticmethod
    def is_within_last_24_hours(date_string):
        try:
            if 'Z' in date_string:

                parsed_date = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            else:

                parsed_date = datetime.fromisoformat(date_string)

        except ValueError:
            return False

        parsed_date_ist = parsed_date.astimezone(ZoneInfo("Asia/Kolkata"))

        current_time = datetime.now(ZoneInfo("Asia/Kolkata"))

        return (current_time - parsed_date_ist) <= timedelta(days=1)


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


class YoutubeApi:
    def __init__(self, debug, publishers_config):
        self.debug = debug
        self.publishers_config = publishers_config
        # self.pub = Publishers(debug)
        # self.config = Utils.load_config()
        # self.access_token = self.config['yt_api_access_token']
        secret_name = f"projects/266686822828/secrets/yt_api_access_token/versions/latest"
        self.access_token = Utils.get_secret(secret_name)

        self.youtube = self.init_api()
        self.all_video_ids = []
        self.all_videos = []
        self.all_short_videos = []

    def init_api(self, api_service_name="youtube", api_version="v3"):
        return googleapiclient.discovery.build(api_service_name, api_version, developerKey=self.access_token)

    def get_channel_video_ids(self, channel_id, last_n_hours):
        """
        Fetches all the videos form a publisher's channel for last n hours; calling the Search:list API. Child method of fetch_all_video_ids()
        :param channel_id: publisher's channel_id
        :param last_n_hours: to get last n hours of data
        :return: nothing. saves data in the list self.all_video_ids
        """
        is_success = True
        self.debug(f"inside get_channel_video_ids for channel_id:{channel_id}")
        published_after = (datetime.now(tz=ZoneInfo("Asia/Kolkata")) - timedelta(hours=last_n_hours)).replace(minute=0,
                                                                                                              second=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        request = self.youtube.search().list(part="snippet", channelId=channel_id, maxResults=50,
                                             publishedAfter=published_after, type="video", videoDuration="short")
        try:
            response = request.execute()
            self.debug(f"Response for channel_id:{channel_id}: \n{response}")
            print(f"Total Results for {channel_id}: {response['pageInfo']['totalResults']}")
            if len(response['items']) != 0:
                curr_channel_video_ids = [item['id']['videoId'] for item in response['items'] if len(item)]
                # print(f"curr_channel_video_ids for {channel_id}: {curr_channel_video_ids}")
                self.all_video_ids.extend(curr_channel_video_ids)
            else:
                self.debug(f"No videos published for {channel_id} in {last_n_hours} hours")
            return is_success
        except HttpError as he:
            print(f"Http Error Caught!\n {he}")
            is_success = False
            return is_success

    def fetch_all_video_ids(self, last_n_hours):
        """
        Loops through all the publisher's channel_ids and fetches all the video IDs
        :param last_n_hours: to get last n hours of data
        :return: nothing, self.all_video_ids is populated.
        """
        self.debug("fetch_all_video_ids started")
        # all_publishers_list = list(self.pub.all_publishers_channels['channel_id'])
        all_publishers_list = list(self.publishers_config['channel_id'])
        publishers_processed_count = 0
        for channel_id in all_publishers_list:
            self.debug(f"processing for channel_id:{channel_id}")
            is_success = self.get_channel_video_ids(channel_id, last_n_hours)
            if is_success:
                publishers_processed_count += 1
            else:
                break
        print(f"{publishers_processed_count} of {len(all_publishers_list)} publishers processed")
        self.debug(f"Initial video ids length: {len(self.all_video_ids)}")
        self.all_video_ids = list(set(self.all_video_ids))
        self.debug(f"video ids length after removing duplicates: {len(self.all_video_ids)}")
        print(f"Total videos fetched from last {last_n_hours} hours: {len(self.all_video_ids)}")

    def fetch_batch_videos(self, video_ids):
        """
        Will take all the video Ids and call the YT Video:list API in batches of 50 to get all the video's data.
        # Takes self.all_video_ids and populates self.all_videos
        :return:
        """
        video_ids_param = ','.join(video_ids)
        request = self.youtube.videos().list(
            part="snippet,contentDetails",
            id=video_ids_param,
            maxResults=50)
        response = request.execute()
        self.all_videos.extend(response['items'])
        pass

    def fetch_all_videos(self, video_ids):
        Utils.process_list_in_batches(video_ids, 50, self.fetch_batch_videos)

    def get_all_videos_from_json(self):
        """
        To process any adhoc json files having the shorts data
        :return:
        """
        videos = Utils.read_json_file('ExtractedVediosDataForAdhocRun.json')
        self.all_videos = videos['items']

    def is_short_video(self, video_id):
        youtube_short_url = f"https://www.youtube.com/shorts/{video_id}"
        try:
            # print("Sending req..")
            response = requests.get(youtube_short_url, allow_redirects=False)
            # print("success")

            status_code = response.status_code

            # print(f"Response json: {response.json()}")
            # print(f"Response status code: {status_code}")
            # print(f"Response headers: {response.headers}")

            if status_code == 200:
                return True
            else:
                return False

        except Exception as e:
            print(f"Error encountered while accessing the shorts endpoint: {str(e)}")
            return False

    def filter_shorts_video(self):
        """
        Identifies all the short videos from self.all_videos by checking the duration of the video.
        :return: Nothing, populates self.all_short_videos

        PMA-13326 --> Filter out non-short videos further by checking url redirection
        """
        for video_item in self.all_videos:
            duration_seconds = Utils.iso8601_to_seconds(video_item['contentDetails']['duration'])

            if 60 >= duration_seconds > 0 and self.is_short_video(video_item['id']):
                self.all_short_videos.append(video_item)

        # self.all_short_videos = [video_item for video_item in self.all_videos if
        #                          ((Utils.iso8601_to_seconds(video_item['contentDetails']['duration']) <= 60) and (
        #                                  Utils.iso8601_to_seconds(video_item['contentDetails']['duration']) != 0))]


class Ingestion:
    def __init__(self, debug, publishers_config):
        self.debug = debug
        self.transformed_shorts = []
        self.publishers_config = publishers_config
        self.all_publishers_channels = publishers_config

    def shorts_data_mapping(self, raw_shorts_list):
        for item in raw_shorts_list:
            channel_id = item['snippet']['channelId']
            self.debug(f"channel_id:{channel_id}")
            language = self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('language').iloc[0]
            self.debug(f"language:{language}")
            category = self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('category').iloc[0]
            self.debug(f"category:{category}")
            language_id = self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('language_id').iloc[0]
            self.debug(f"language:{language}")
            category_id = self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('category_id').iloc[0]
            self.debug(f"category:{category}")
            publisher_name = \
                self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('publisher_name').iloc[0]
            self.debug(f"publisher_name:{publisher_name}")
            publisher_id = self.all_publishers_channels.query(f"channel_id == '{channel_id}'").get('publisher_id').iloc[
                0]
            self.debug(f"publisher_id:{publisher_id}")
            published_date = item['snippet']['publishedAt']
            self.debug(f"published_date:{published_date}")
            video_id = item['id']
            self.debug(f"video_id:{video_id}")

            try:
                if not Utils.is_within_last_24_hours(published_date):
                    print(f"Skipping {video_id} as it is older than 24 hours. published_date: {published_date}")
                    continue
            except Exception as e:
                print(
                    f"Error while checking the published date for {video_id}. published_date: {published_date}::: {e}")

            transformed_item = {
                'sourceVideoId': video_id,
                'title': item['snippet']['title'],
                'sourceCategoryId': str(category_id),
                'sourceLanguageId': str(language_id),
                'sourceCategoryName': category,
                'sourceLanguageName': language,
                "sourceThumbnailURL": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                'sourceDate': published_date,
                'sourceEpoch': Utils.convert_to_epoch(published_date),
                'sourceDescription': item['snippet']['description'],
                'sourcePublisherId': str(publisher_id),
                'sourcePublisherName': publisher_name,
                'src': 'youtube',
                'sourceExternalid': video_id,
                'createdAt': Utils.epoch_now(),
                'sourceThumbnails': item['snippet']['thumbnails'],
                'sourceVideoDuration': Utils.iso8601_to_seconds(item['contentDetails']['duration']),
                'sourceChannelID': channel_id,
                "sourceVideoWidth": 1080,
                "sourceVideoHeight": 1920,
                "sourceVideoOrientation": "portrait",

            }
            self.transformed_shorts.append(transformed_item)


class MongoDB:
    def __init__(self, debug):
        self.debug = debug
        self.debug("Establishing MongoDB connection")
        secret_name = f"projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        self.connection_uri_de_self_hosted = Utils.get_secret(secret_name)
        self.de_client_self_hosted = MongoClient(self.connection_uri_de_self_hosted, tlsCAFile=certifi.where())
        # self.ingestion_db = self.de_client['ingestion-data']
        self.ingestion_db_self_hosted = self.de_client_self_hosted['ingestion-data']
        # self.short_videos_ingest_collection = self.ingestion_db['raw_short_videos_ingestion_data']
        self.short_videos_ingest_collection_self_hosted = self.ingestion_db_self_hosted[
            'raw_short_videos_ingestion_data']
        self.debug("Connected!")

    # def ingest_shorts(self, curated_shorts_list):
    #     if len(curated_shorts_list) != 0:
    #         print(f"Total curated shorts: {len(curated_shorts_list)}")
    #         try:
    #             self.short_videos_ingest_collection.insert_many(curated_shorts_list, ordered=False)
    #             print(f"{len(curated_shorts_list)} total documents inserted")
    #         except BulkWriteError as bwe:
    #             num_inserted = bwe.details['nInserted']
    #             num_skipped = len(curated_shorts_list) - num_inserted
    #             print(f"{num_inserted} documents inserted!")
    #             print(f"{num_skipped} documents were duplicates and skipped.")
    #     else:
    #         print("No Shorts Fetched")

    def ingest_shorts_self_hosted(self, curated_shorts_list):
        if len(curated_shorts_list) != 0:
            print(f"Total curated shorts: {len(curated_shorts_list)}")
            try:
                self.short_videos_ingest_collection_self_hosted.insert_many(curated_shorts_list, ordered=False)
                print(f"{len(curated_shorts_list)} total documents inserted")
            except BulkWriteError as bwe:
                num_inserted = bwe.details['nInserted']
                num_skipped = len(curated_shorts_list) - num_inserted
                print(f"{num_inserted} documents inserted!")
                print(f"{num_skipped} documents were duplicates and skipped.")
        else:
            print("No Shorts Fetched")

    def close_clients(self):
        # self.de_client.close()
        self.de_client_self_hosted.close()

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
        self.topic_name = "raw_youtube_shorts_ingestion"
        self.project_id = "jiox-328108"

    def parse_message(self, pubsub_message):
        message_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        message_object_data = json.loads(message_data)
        data = message_object_data
        return data

    def publish(self, shorts_data):
        self.debug(f"Converting following data to string::\n{shorts_data[0]}")
        json_string = json.dumps(shorts_data)
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

        self.ytapi = YoutubeApi(self.debug, self.publishers_config)
        self.inges = Ingestion(self.debug, self.publishers_config)
        self.db = MongoDB(self.debug)
        self.ps = PubSub(self.debug)

    def run(self, pubsub_message):
        # self.ytapi.fetch_all_video_ids(12)
        # self.debug(self.ytapi.all_video_ids)
        video_ids = self.ps.parse_message(pubsub_message)
        # video_ids = pubsub_message
        print(f"video_ids: {video_ids}")
        print(f"Total {len(video_ids)} videos fetched from pubsub")
        self.ytapi.fetch_all_videos(video_ids)
        self.debug(f"all_videos: {self.ytapi.all_videos}")
        self.ytapi.filter_shorts_video()
        # self.ytapi.all_short_videos = self.ytapi.all_videos
        self.debug(f"all_short_videos: {self.ytapi.all_short_videos}")
        self.debug(f"all_short_videos length: {len(self.ytapi.all_short_videos)}")
        self.inges.shorts_data_mapping(self.ytapi.all_short_videos)
        self.debug(f"transformed_shorts:{self.inges.transformed_shorts}")
        if len(self.inges.transformed_shorts) > 0:
            # self.db.ingest_shorts(self.inges.transformed_shorts)
            self.ps.publish(self.inges.transformed_shorts)
            self.db.ingest_shorts_self_hosted(self.inges.transformed_shorts)
            self.debug(f"transformed_shorts--ck3:{self.inges.transformed_shorts[0]}")
        else:
            print("No records to publish")
        self.db.close_clients()
        pass


def main(pubsub_message, context):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    # try:
    exe = Execute(debugger=False)
    exe.run(pubsub_message)
    # except Exception as e:
    #     print(f"Exception caught::\n{e}")
    # finally:
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}