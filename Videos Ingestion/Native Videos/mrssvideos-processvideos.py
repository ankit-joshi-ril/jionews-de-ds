import base64
import json
import random
import re
import time
import warnings
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import pytz
import redis
from bs4 import BeautifulSoup
from bson import ObjectId
from dateutil import parser
from google.cloud import pubsub_v1, storage, secretmanager
from pymongo import MongoClient, errors

# Filter out the specific warning
warnings.filterwarnings("ignore", category=UserWarning)

RUN_LOCAL = False


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)


class Utils:

    @staticmethod
    def convert_to_epoch(parsed_date):
        if parsed_date:
            try:
                epoch_time = int(parsed_date.timestamp())
                return epoch_time
            except Exception as e:
                print(f"Error converting date to epoch, parsed_date - {parsed_date}: {e}")
                return None
        else:
            return None

    @staticmethod
    def epoch_now():
        zone = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=zone)
        return int(now.timestamp())

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


class PubSub:
    def __init__(self, debug):
        self.debug = debug
        self.topic_name = "NewRawHeadlinesIngestion_processed_data"
        self.project_id = "jiox-328108"
        self.pubsub = pubsub_v1.PublisherClient()
        self.topic_path = self.pubsub.topic_path(self.project_id, self.topic_name)

    @staticmethod
    def publish_message_to_topic(topic_name, data):
        print(f"Publishing message to topic: {topic_name} || data: {data}")
        project_id = "jiox-328108"
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(project_id, topic_name)

        json_string = json.dumps(data, cls=EnhancedJSONEncoder)
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

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class GCS:
    def __init__(self, debug):
        self.debug = debug
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "videos/mrss_videos_feeds.csv"
        self.feeds_config = None

    def read_csv_from_gcs(self):
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes))
        self.feeds_config = df


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

    def insert_records_to_mongo(self, recs):
        if not recs:
            print(f"No records to insert into MongoDB.")
            return
        try:
            result = self.raw_videos_rss.insert_many(recs, ordered=False)
            print(f"Inserted {len(result.inserted_ids)} records into MongoDB.")
        except Exception as e:
            print(f"Exception caught while inserting records to MongoDB: {e}")


class Processor:
    def __init__(self, debug, feeds_config, ps):
        self.debug = debug
        self.feeds_config = feeds_config
        self.ps = ps
        self.max_threads = 50
        self.all_feeds_data = []
        self.empty_feeds = 0
        self.non_existing_records = []
        self.cdn_image_data = []
        # self.image_url_mappings = []

        self.redis_url = "redis://:u4YIVWZBcNiYCPFj!@35.200.220.40:6379"
        self.redis_client = redis.StrictRedis.from_url(self.redis_url)
        self.set_name = "de_mrss_videos_cache"
        self.expiration_seconds = 30 * 24 * 3600  # 30 days in seconds

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

    def get_current_timestamp(self):
        return int(time.time())

    def filter_records_from_cache(self, data, category_id, language_id):
        non_existing_records = []
        current_timestamp = self.get_current_timestamp()
        # # Turing off deduplication
        # non_existing_records = data
        # return None
        if RUN_LOCAL:
            print(f"RUN_LOCAL:: {RUN_LOCAL} || skipping cache deduplication")
            self.non_existing_records = data
            return True

        # Purge ZSet entries whose expiration score has passed before checking.
        # Without this, entries added >48h ago are never removed and block records
        # indefinitely (ZSet scores are not auto-expired by Redis).
        self.cleanup_expired_keys()

        for rec in data:
            # Generate the compound key
            link = rec.get('link', rec.get('mwu', ""))
            title = rec.get('title', rec.get('video', ""))
            compound_key = f"{title}_{link}_{category_id}_{language_id}"
            rec['compound_key'] = compound_key

            # Check if the compound key exists AND has not expired.
            # zscore() returns None when absent; numeric score otherwise.
            # Treat score <= current_timestamp as expired (same as not cached).
            score = self.redis_client.zscore(self.set_name, compound_key)
            if score is None or score <= current_timestamp:
                non_existing_records.append(rec)
                self.redis_client.zadd(self.set_name, {compound_key: current_timestamp + self.expiration_seconds})

        self.non_existing_records = non_existing_records

    def cleanup_expired_keys(self):
        current_timestamp = self.get_current_timestamp()
        # Remove all records with scores (timestamps) older than the current time
        self.redis_client.zremrangebyscore(self.set_name, "-inf", current_timestamp)

    def get_image_url_from_html(self, record):
        # List of possible keys where HTML content might be embedded
        html_keys = [
            ('content_html',),
            ('description_html',),
            ('summary_html',),
            ('content',),
            ('summary',),
            ('summary_detail', 'value')
        ]

        for key in html_keys:
            value = record
            try:
                for k in key:
                    value = value[k]
                if value and isinstance(value, str):  # Check if the extracted value is a non-empty string
                    soup = BeautifulSoup(value, 'html.parser')
                    img_tag = soup.find('img')
                    if img_tag and 'src' in img_tag.attrs:
                        print(f"get_image_url_from_html triggered:: {img_tag['src']}")
                        return img_tag['src']

            except (KeyError, IndexError, TypeError):
                continue

        # print(f"get_image_url_from_html triggered but:: {record}")
        return ""

    def get_image_thumbnail_url(self, record):
        try:
            # Prioritize thumbnail/image fields first, then fallback to media_content
            keys = [
                ('media_thumbnail', 0, 'url'),
                ('media_thumbnail',),
                ('thumbimage', 'url'),
                ('thumbimage',),
                ('fullimage',),
                ('fullimageimage',),
                ('image', 'url'),
                ('image', 'link'),
                ('image',),
                ('links', 1, 'href'),
                ('images', 0),
                ('media_content', 0, 'url'),  # moved after thumbnails
                ('thumbnail',)
            ]

            for key in keys:
                value = record
                try:
                    for k in key:
                        value = value[k]

                    if value:
                        # Skip if it looks like a video file (mp4, webm, etc.)
                        if isinstance(value, str) and value.lower().endswith((".mp4", ".webm", ".avi", ".mov", ".mkv")):
                            continue
                        return value
                except (KeyError, IndexError, TypeError):
                    continue

            # If no URL is found using the above keys, attempt to extract from HTML
            return self.get_image_url_from_html(record)
        except Exception:
            return ""

    def get_default_image(self, category):
        category_map = {"Agro": "Agro", "Astrology": "Astrology", "Auto": "Automobile", "Business": "Business",
                        "Money": "Business", "Career": "Education", "Entertainment": "Entertainment",
                        "Movie Reviews": "Entertainment", "Health": "Health", "Corona": "Health", "National": "India",
                        "Regional": "India", "World": "International", "Top News": "Latest News",
                        "Top Stories": "Latest News", "Lifestyle": "Lifestyle", "Fashion": "Lifestyle",
                        "Sci & Tech": "Sci and Tech", "Sports": "Sports", "cricket": "cricket"}

        mapped_category = category_map.get(category.strip(), "")
        processed_categories = {}

        if mapped_category:
            random_num = random.randint(1, 5)
            category_name = mapped_category.lower().replace(' ', '_')
            processed_categories[
                'source_thumbnail_url'] = f"https://icdn.jionews.com/default/{category_name}/original/{category_name}_{random_num}.png"
            processed_categories['thumbnail_urls'] = {
                "default": {
                    "url": f"https://icdn.jionews.com/default/{category_name}/original/{category_name}_{random_num}.png",
                    "width": 120,
                    "height": 90
                },
                "medium": {
                    "url": f"https://icdn.jionews.com/default/{category_name}/sd/{category_name}_{random_num}.png",
                    "width": 320,
                    "height": 180
                },
                "high": {
                    "url": f"https://icdn.jionews.com/default/{category_name}/low/{category_name}_{random_num}.png",
                    "width": 480,
                    "height": 360
                },
                "standard": {
                    "url": f"https://icdn.jionews.com/default/{category_name}/hd/{category_name}_{random_num}.png",
                    "width": 640,
                    "height": 480
                },
                "maxres": {
                    "url": f"https://icdn.jionews.com/default/{category_name}/fhd/{category_name}_{random_num}.png",
                    "width": 1280,
                    "height": 720
                }
            }
            # processed_categories['thumbnail_urls'] = {
            #     "original": f"https://icdn.jionews.com/default/{category_name}/original/{category_name}_{random_num}.png",
            #     "fhd": f"https://icdn.jionews.com/default/{category_name}/fhd/{category_name}_{random_num}.png",
            #     "hd": f"https://icdn.jionews.com/default/{category_name}/hd/{category_name}_{random_num}.png",
            #     "low": f"https://icdn.jionews.com/default/{category_name}/low/{category_name}_{random_num}.png",
            #     "sd": f"https://icdn.jionews.com/default/{category_name}/sd/{category_name}_{random_num}.png"
            # }

            # return f"{mapped_category.lower().replace(' ', '_')}_{random_num}.png"
            return processed_categories
        else:
            print(f"Issue in get_default_image: Category not found: {category}")
            return None

    def publisher_date_to_epoch(self, input_date):
        try:
            parsed_date = Utils.generic_parse_date(input_date)
            date_epoch = Utils.convert_to_epoch(parsed_date)
            return date_epoch
        except:
            return None

    def adjust_publisher_epoch(self, epoch_now, publisher_epoch):

        try:
            if publisher_epoch > epoch_now:
                # Remove 5 hours and 30 minutes (19800 seconds) from publisher_epoch
                adjusted_epoch = publisher_epoch - 19800
                return adjusted_epoch
            return publisher_epoch
        except:
            return epoch_now

    def process_mapping(self, record_data, default_values):
        source_id = str(ObjectId())
        title = re.sub(r'\s+', ' ', record_data.get('title', "").strip())
        source_category_id = str(default_values["category_id"].iloc[0])
        source_category_name = str(default_values["category_name"].iloc[0])
        source_language_id = str(default_values["language_id"].iloc[0])
        source_language_name = str(default_values["language_name"].iloc[0])
        source_publisher_id = str(default_values["publication_id"].iloc[0])
        source_publisher_name = str(default_values["pub_name"].iloc[0])

        # Third-party API partner: metadata comes from the API record, not the CSV config
        if source_publisher_id == "7784":
            source_language_name = record_data.get('ch_language', source_language_name)
            source_category_name = record_data.get('ch_category', source_category_name)
            source_publisher_name = record_data.get('ch_publication_name', source_publisher_name)

        if source_publisher_id in ["7777", "7778"]:
            video_type = record_data.get('videotype', record_data.get('videoType', "")).lower()
            if not video_type:
                print(f"No videotype mapping found for {source_publisher_id}::{source_publisher_name}")
            if video_type not in ["vod", "long video", "video", "videos", "longvideo"]:
                return None
        elif source_publisher_id == "7784":
            if record_data.get('vid_type', '').lower() != 'video':
                return None

        source_thumbnail_url = self.get_image_thumbnail_url(record_data)
        if source_publisher_id == "7784":
            source_thumbnail_url = record_data.get('vid_thumbnail', source_thumbnail_url)
        thumbnail_urls = {
            "default": {
                "url": f"https://icdn.jionews.com/original/{source_id}.jpeg",
                "width": 120,
                "height": 90
            },
            "medium": {
                "url": f"https://icdn.jionews.com/low/{source_id}.jpeg",
                "width": 320,
                "height": 180
            },
            "high": {
                "url": f"https://icdn.jionews.com/sd/{source_id}.jpeg",
                "width": 480,
                "height": 360
            },
            "standard": {
                "url": f"https://icdn.jionews.com/hd/{source_id}.jpeg",
                "width": 640,
                "height": 480
            },
            "maxres": {
                "url": f"https://icdn.jionews.com/fhd/{source_id}.jpeg",
                "width": 1280,
                "height": 720
            }
        }

        # Moving all image processing to cdn flow making the workflow synchronous
        # if source_thumbnail_url:
        #     self.debug(f"source_thumbnail_url:: {source_thumbnail_url}")
        #     # self.cdn_image_data.append(
        #     #     {"filename": source_id, "url": source_thumbnail_url, "category": source_category_name,
        #     #      "publisher": source_publisher_name, "source": 'publisher_mrss'})
        #
        #     # thumbnail_urls = {
        #     #     "original": f"https://icdn.jionews.com/original/{source_id}.jpeg",
        #     #     "fhd": f"https://icdn.jionews.com/fhd/{source_id}.jpeg",
        #     #     "hd": f"https://icdn.jionews.com/hd/{source_id}.jpeg",
        #     #     "low": f"https://icdn.jionews.com/low/{source_id}.jpeg",
        #     #     "sd": f"https://icdn.jionews.com/sd/{source_id}.jpeg"
        #     # }
        #
        #     source_thumbnail_url = f"https://icdn.jionews.com/original/{source_id}.jpeg"
        # else:
        #     default_image = self.get_default_image(source_category_name)
        #     source_thumbnail_url = default_image['source_thumbnail_url']
        #     thumbnail_urls = default_image['thumbnail_urls']

        epoch_now = Utils.epoch_now()
        if source_publisher_id == "7784" and record_data.get('vid_youtube_date'):
            source_date = record_data['vid_youtube_date']
        else:
            source_date = datetime.fromtimestamp(epoch_now, tz=ZoneInfo("Asia/Kolkata")).isoformat(
                timespec='milliseconds')
        source_publish_date = self.publisher_date_to_epoch(source_date) or epoch_now
        source_epoch = self.adjust_publisher_epoch(epoch_now, source_publish_date)
        # For IANS Api
        if source_publisher_id == "7782":
            publisher_video_url = record_data.get('video', "")
            print(f"IANS API Identified")
        elif source_publisher_id == "7784":
            publisher_video_url = record_data.get('vid_file', "")
        else:
            publisher_video_url = (
                record_data.get('media_content', [{}])[0].get('url', "")
                if record_data.get('media_content') and len(record_data['media_content']) > 0
                else ""
            )

        final_record = {
            "sourceVideoId": source_id,
            "title": title,
            "sourceCategoryId": source_category_id,
            "sourceCategoryName": source_category_name,
            "sourceLanguageId": source_language_id,
            "sourceLanguageName": source_language_name,
            # "sourceThumbnailURL": source_thumbnail_url,
            "sourceThumbnailURL": source_thumbnail_url,
            "sourceDate": source_date,
            "sourceEpoch": source_epoch,
            "sourcePublisherId": source_publisher_id,
            "sourcePublisherName": source_publisher_name,
            "src": "third_party" if source_publisher_id == "7784" else "publisher_mrss",
            "sourceExternalid": source_id,
            "sourceVideoWidth": 0,
            "sourceVideoHeight": 0,
            "sourceVideoOrientation": "landscape",
            "createdAt": epoch_now,
            "updatedAt": epoch_now,
            "duration": "0",
            "sourceChannelID": source_publisher_id,
            "thumbnailUrls": thumbnail_urls,
            "contentType": "videos",
            "processingStatus": "processing",
            "isVideoMerged": False,
            "audioUrl": "",
            "videoUrl": "",
            "videoContentUrl": "",
            "publisherVideoUrl": publisher_video_url
        }

        processed_record = {"filename": source_id, "url": source_thumbnail_url, "category": source_category_name,
                            "publisher": source_publisher_name, "content_type": "videos", "data": final_record}

        return processed_record

    def process_all_records(self, feed_id, default_values):
        processed_data = []
        self.debug(f"self.non_existing_records: {self.non_existing_records}")
        for record in self.non_existing_records:
            # print(f"default_values: {default_values}")
            try:
                mapped_record = self.process_mapping(record, default_values)
                if mapped_record:
                    processed_data.append(mapped_record)
            except Exception as e:
                print(f"Exception caught while mapping. feed_id:{feed_id}, Exception:{e}")
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
        self.db = MongoDB()
        self.logger = Logger(debugger)
        self.debug = self.logger.debug
        self.ps = PubSub(self.debug)

        self.gcs = GCS(self.debug)
        self.gcs.read_csv_from_gcs()
        self.feeds_config = self.gcs.feeds_config
        self.processor = Processor(self.debug, self.feeds_config, self.ps)

    def run(self, message):
        """ => Fetch feed_id and feed_data from pubsub for a single
        feed Message format: {"feed_id": 1234, "feed_data": [...]}"""

        if not RUN_LOCAL:
            videos_data = self.ps.parse_message(message)
        else:
            print(f"*** THIS IS A LOCAL EXECUTION FOR TESTING ***")
            videos_data = message  # Message format: {"feed_id": 1234, "feed_data": [...]}
            print(f"videos_data:: {videos_data}")
        all_records = videos_data['feed_data']
        feed_id = videos_data['feed_id']
        default_values = self.feeds_config.query(f"id == {feed_id}")
        print(f"{feed_id}:: Total {len(all_records)} records received")
        print(f"{feed_id}:: all_records: {all_records}")

        print(f"{feed_id}:: Applying deduplication logic to filter out existing records in cache")
        """Deduplication logic to filter out data already existing. title+url+categoryId+languageId"""
        source_language_id = str(default_values["language_id"].iloc[0])
        source_category_id = str(default_values["category_id"].iloc[0])

        self.processor.filter_records_from_cache(all_records, source_category_id, source_language_id)
        print(
            f"{feed_id}:: Total {len(self.processor.non_existing_records)} unique records from {len(all_records)} received")

        """Data procession and mapping"""
        processed_data = self.processor.process_all_records(feed_id, default_values)
        print(f"{feed_id}:: Total processed records: {len(processed_data)}")

        """Publish thumbnail images to pubsub for cdn"""

        if not RUN_LOCAL:
            # if self.processor.cdn_image_data:
            #     PubSub.publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", self.processor.cdn_image_data)
            # self.debug(f"Finale processed Data: {len(processed_data)}")
            #
            # """Publish final processed data to pubsub->mongodb"""
            # if processed_data:
            #     self.db.insert_records_to_mongo(processed_data)
            #
            #     for rec in processed_data:
            #         data = [rec]
            #         PubSub.publish_message_to_topic("MRSSVideosIngestion_ProcessedData", data)
            # PubSub.publish_message_to_topic("MRSSVideosIngestion_ProcessedData", processed_data)

            """
            *** Making the workflow synchronous to streamline rejection of videos with lower resolution image asset.
            *** Data will flow directly through img-cdn flow
            """
            if processed_data:
                PubSub.publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", processed_data)
            else:
                print(f"{feed_id}:: All records already in cache")
            return feed_id
        else:
            # Save files locally
            with open(f'mrss_videos_processed_output_{feed_id}_new.json', 'w') as f:
                json.dump(processed_data, f, cls=EnhancedJSONEncoder, indent=4)

            with open(f'mrss_videos_cdn_images_{feed_id}_new.json', 'w') as f:
                json.dump(self.processor.cdn_image_data, f, cls=EnhancedJSONEncoder, indent=4)


def main(req):
    message = []
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    try:
        request_json = req.get_json()
        message = request_json['message']
    except Exception as e:
        print(f"Exception caught while fetching req data: {e}")
    exe = Execute(debugger=False)
    feed_id = exe.run(message)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minute -- {feed_id}")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}


def test_locally(test_feeds_filename):
    global RUN_LOCAL
    RUN_LOCAL = True
    message = []
    execution_start_time = time.time()
    print(f"(Local Test) Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")

    # read json file
    with open(test_feeds_filename, 'r') as file:
        all_feeds_records = json.load(file)

    exe = Execute(debugger=False)
    for feed_records in all_feeds_records:
        print(f"(Local Test) Processing feed_id: {feed_records['feed_id']}")
        feed_id = exe.run(feed_records)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"(Local Test) Execution processing time: {execution_processing_time} minute")
    print(f"(Local Test) Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}

# test_locally('mrss_videos_sep25.json')
