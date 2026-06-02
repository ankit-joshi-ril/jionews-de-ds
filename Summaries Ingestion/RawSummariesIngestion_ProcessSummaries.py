import base64
import csv
import html
import io
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
import requests
from bs4 import BeautifulSoup
from bson import ObjectId
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

    @staticmethod
    def clean_html_message(text):
        if not isinstance(text, str):
            return text
        text = re.sub(r'<!\[CDATA\[(.*?)(\]\]>|\]\])', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


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
            print(f"Message published!")
        except Exception as err:
            print(f"Message Publishing Error: {err}")

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data

    def parse_html_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        feed_data = decoded_data.get("feed_data")

        if isinstance(feed_data, list):
            for item in feed_data:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("title"), str):
                    item["title"] = Utils.clean_html_message(item["title"])

                if isinstance(item.get("summary"), str):
                    item["summary"] = Utils.clean_html_message(item["summary"])

        return decoded_data


class GCS:
    def __init__(self, debug):
        self.debug = debug
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "summaries/summaries_publishers_feeds.csv"
        self.feeds_config = None

    def read_csv_from_gcs(self):
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes))
        self.feeds_config = df

    def save_data_string_to_cloud_storage(self, data, bucket_name, destination_blob_name):
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(data)


# Blocklist: (sourcePublisherName, sourceCategoryName) pairs - auto-published summaries for these are blocked.
# Comparison is case-insensitive; category is normalized (strip, lower, html unescape).
BLOCKED_PUBLISHER_CATEGORIES = frozenset([
    ("jagran josh", "latest news"),
    ("jagran josh", "top news"),
    ("latestly", "education"),
    ("latestly", "information"),
    ("news18", "opinion"),
    ("news18", "photogallery"),
    ("news18 hindi", "photo"),
    ("news9 live", "opinion & analysis"),
    ("news9 live", "spirituality"),
    ("prabhasakshi", "breaking news"),
    ("republic bharat", "shows"),
    ("republic bharat", "videos"), ])


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
        self.unhygienic_records = []
        self.blocked_by_category_count = 0

        self.redis_url = "redis://:u4YIVWZBcNiYCPFj!@35.200.220.40:6379"
        self.redis_client = redis.StrictRedis.from_url(self.redis_url)
        # self.set_name = "de_headlines_id_cache"
        # self.set_name = "de_summaries_cache_stg"
        self.set_name = "de_summaries_cache"
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

    def get_current_timestamp(self):
        return int(time.time())

    def filter_records_from_cache(self, all_records, category_id, language_id):
        non_existing_records = []

        # # Pausing deduplication logic for testing
        # self.non_existing_records = all_records
        # return None

        current_timestamp = self.get_current_timestamp()

        for rec in all_records:
            # Generate the compound key
            # link = rec.get('link', rec.get('mwu', ""))
            title = rec.get('title', rec.get('hl', ""))
            # compound_key = f"{link}_{category_id}_{language_id}"
            compound_key = f"{title}"
            rec['compound_key'] = compound_key

            # Check if the compound key exists in the ZSet
            if not self.redis_client.zscore(self.set_name, compound_key):
                # Add the record to non-existing records list
                non_existing_records.append(rec)

                # Add the compound key to the ZSet with expiration time
                self.redis_client.zadd(self.set_name, {compound_key: current_timestamp + self.expiration_seconds})

        self.non_existing_records = non_existing_records

    def cleanup_expired_keys(self):
        current_timestamp = self.get_current_timestamp()
        # Remove all records with scores (timestamps) older than the current time
        self.redis_client.zremrangebyscore(self.set_name, "-inf", current_timestamp)

    @staticmethod
    def is_blocked_publisher_category(publisher_name, category_name):
        """Check if (publisher, category) is in the blocklist for auto-published summaries."""
        if not publisher_name or not category_name:
            return False
        pub = str(publisher_name).strip().lower()
        cat = html.unescape(str(category_name).strip()).strip().lower()
        return (pub, cat) in BLOCKED_PUBLISHER_CATEGORIES

    def append_utm_params(self, url):
        # Define UTM parameters as a set of query keys
        utm_keys = {'utm_source', 'utm_medium', 'utm_campaign'}
        utm_params = "utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews"

        # Check if the URL already has any UTM parameters
        if any(re.search(f'{key}=', url) for key in utm_keys):
            return url  # Return the URL as-is if UTM parameters are already present

        # Append UTM parameters if not found
        if '?' in url:
            if url.endswith('?') or url.endswith('&'):
                new_url = url + utm_params
            else:
                new_url = url + '&' + utm_params
        else:
            new_url = url + '?' + utm_params

        return new_url

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
            # List of possible keys in the order of priority
            keys = [
                ('media_content', 0, 'url'),
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
                ('images', 0)
            ]

            for key in keys:
                value = record
                try:
                    for k in key:
                        value = value[k]
                    if value:  # Check if the extracted value is not empty
                        return value
                except (KeyError, IndexError, TypeError):
                    continue

            # If no URL is found using the above keys, attempt to extract from HTML
            return self.get_image_url_from_html(record)
        except Exception as e:
            # Log the exception if needed, but still return an empty string
            return ""

    def get_default_image(self, category):
        category_map = {"Agro": "Agro", "Astrology": "Astrology", "Auto": "Automobile", "Business": "Business",
                        "Money": "Business", "Career": "Education", "Entertainment": "Entertainment",
                        "Movie Reviews": "Entertainment", "Health": "Health", "Corona": "Health", "National": "India",
                        "Regional": "India", "World": "International", "Top News": "Latest News",
                        "Top Stories": "Latest News", "Lifestyle": "Lifestyle", "Fashion": "Lifestyle",
                        "Sci & Tech": "Sci and Tech", "Sports": "Sports", "cricket": "Sports"}

        mapped_category = category_map.get(category.strip(), "")
        processed_categories = {}

        if mapped_category:
            category_name = mapped_category.lower().replace(' ', '_') or "latest_news"
            if category_name == "latest_news":
                random_num = random.randint(1, 22)
            else:
                random_num = random.randint(1, 10)
            processed_categories[
                'source_thumbnail_url'] = f"https://icdn.jionews.com/default/{category_name}/original/{category_name}_{random_num}.png"
            processed_categories['thumbnail_urls'] = {
                "original": f"https://icdn.jionews.com/default/{category_name}/original/{category_name}_{random_num}.png",
                "fhd": f"https://icdn.jionews.com/default/{category_name}/fhd/{category_name}_{random_num}.png",
                "hd": f"https://icdn.jionews.com/default/{category_name}/hd/{category_name}_{random_num}.png",
                "low": f"https://icdn.jionews.com/default/{category_name}/low/{category_name}_{random_num}.png",
                "sd": f"https://icdn.jionews.com/default/{category_name}/sd/{category_name}_{random_num}.png"
            }

            # return f"{mapped_category.lower().replace(' ', '_')}_{random_num}.png"
            return processed_categories
        else:
            print(f"Issue in get_default_image: Category not found: {category}")
            return None

    def get_article_text(self, url):
        article_api_url = "http://34.36.231.72/crawl"
        article_body = ""
        headers = {
            'accept': 'application/json',
            'Content-Type': 'text/plain'
        }

        try:
            response = requests.post(article_api_url, headers=headers, data=url, timeout=15)
            article_response = response.json()
            try:
                article_body = article_response['article_body']
            except:
                article_body = article_response['Result']['article_body']
            return article_body
        except Exception as e:
            return ""

    def get_article_text_new(self, url):
        api_endpoint = "https://service.jionews.com/v1/scrape/scrape/"
        params = {'url': url}
        headers = {
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(api_endpoint, params=params, headers=headers, timeout=10, verify=False)
            if response.status_code == 200:
                data = response.json()
                article_text = data.get('article_text')
                if article_text:
                    return article_text
                else:
                    print("Article text not found in the response.")
                    return ""
            else:
                print("Article text not found in the response.")
                return ""
        except Exception as e:
            print(f"Exception caught: {e}")
            return ""

    def process_get_article(self, doc):
        url = doc['url']
        lang = doc['sourceLanguageName']

        article_text = self.get_article_text_new(url)

        if article_text:
            return article_text

        # Fallback logic using old scraper service
        article_response = ""
        if lang == 'English':
            try:
                article_response = self.get_article_text(url)
                try:
                    article_text = article_response['article_body']
                except Exception as e:
                    article_text = article_response['Result']['article_body']
                return article_text
            except Exception as e:
                return article_text
        else:
            return article_text

    def get_np_category(self, src_cat_name):
        categories_map = {
            "business": {"name": "Business", "id": 5},
            "entertainment": {"name": "Entertainment", "id": 11},
            "lifestyle": {"name": "Lifestyle", "id": 4},
            "city": {"name": "Latest news", "id": 173},
            "top-news": {"name": "Latest news", "id": 173},
            "education": {"name": "Education", "id": 156},
            "regional": {"name": "Latest news", "id": 191},
            "astrology": {"name": "Astrology", "id": 161},
            "auto": {"name": "Automobile", "id": 44},
            "india": {"name": "India", "id": 58},
            "world": {"name": "International", "id": 9}
        }

        return categories_map.get(src_cat_name, {"name": "Latest news", "id": 173})

    def publisher_date_to_epoch(self, input_date):
        try:
            parsed_date = Utils.generic_parse_date(input_date)
            date_epoch = Utils.convert_to_epoch(parsed_date)
            return date_epoch
        except:
            return None

    def contains_html_tags(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        return bool(re.search(r"</?[a-z][\s\S]*>", text, re.IGNORECASE))

    def special_char_check(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        special_chars = "@#$%^&*()_+=[]{}\\|<>/?"
        count = sum(1 for ch in text if ch in special_chars)
        return count >= 3

    def check_publisher_summary_hygiene(self, record) -> dict:
        title = record.get('title', "")
        summary = record.get('summary', "")
        errors = []

        try:
            # ---- TITLE CHECKS ----
            if not title:
                errors.append({"key": "title", "value": "Title is empty"})
            else:
                if len(title) < 26:
                    errors.append({"key": "title", "value": "Title is less than 26 characters"})
                if len(title) > 105:
                    errors.append({"key": "title", "value": "Title is more than 105 characters"})
                if self.contains_html_tags(title):
                    errors.append({"key": "title", "value": "Title contains HTML characters"})

            if self.special_char_check(title):
                errors.append({"key": "title", "value": "Title contains special characters"})

            # ---- SUMMARY CHECKS ----
            if not summary:
                errors.append({"key": "summary", "value": "Summary is empty"})
            else:
                if len(summary) < 200:
                    errors.append({"key": "summary", "value": "Summary is less than 20 characters"})
                if len(summary) > 360:
                    errors.append({"key": "summary", "value": "Summary is more than 360 characters"})
                if self.contains_html_tags(summary):
                    errors.append({"key": "summary", "value": "Summary contains HTML characters"})
                if self.special_char_check(summary):
                    errors.append({"key": "title", "value": "Title contains special characters"})

            return {
                "isHygienic": len(errors) == 0,
                "errors": errors
            }

        except Exception as e:
            return {
                "isHygienic": False,
                "errors": [{"key": "", "value": str(e)}]
            }

    def process_mapping(self, record_data, default_values):

        source_feed_url = str(default_values["feed_url"].iloc[0])
        source_category_id = "0"
        source_category_name = "Latest News"  # Default category [STORY 42675]

        if 'nprssfeeds.indiatimes.com' in source_feed_url:
            title = record_data['hl']
            summary = record_data['syn']
            url = record_data['mwu']
            source_publish_date = record_data['dl']
            source_category_name = record_data.get('sec', 'Latest News')  # [STORY 42675]
        else:
            title = record_data['title']
            summary = record_data.get('shorts_bulletin', '') or record_data.get('summary', '')
            url = record_data['link']
            source_publish_date = record_data.get('published', '') or record_data.get('pubDate', '')
            tag = record_data.get('tags', "")
            source_category_name = tag[0].get('term') if isinstance(tag,
                                                                    list) and tag else 'Latest News'  # [STORY 42675]
            # source_category_name = record_data.get('category', 'Latest News')  # [STORY 42675]

        try:
            url = self.append_utm_params(url)
        except Exception as e:
            print(f"Error adding URL params: {e}")
            url = ""
        epoch_now = Utils.epoch_now()

        # source_publish_date = self.publisher_date_to_epoch(source_publish_date) or epoch_now
        source_publish_date = epoch_now
        source_thumbnail_url = self.get_image_thumbnail_url(record_data)

        source_id = str(ObjectId())
        # source_category_id = str(default_values["category_id"].iloc[0])
        # source_category_name = str(default_values["category_name"].iloc[0])
        source_publisher_id = str(default_values["publication_id"].iloc[0])
        source_publisher_name = str(default_values["pub_name"].iloc[0])

        # STORY 51524 - disabling async image processing to synchronize the process and rename publisher with default thumbnail
        # if source_thumbnail_url:
        #     self.cdn_image_data.append(
        #         {"filename": source_id, "url": source_thumbnail_url, "category": source_category_name,
        #          "publisher": source_publisher_name})

        # print(f"Debugg--- languageee")
        # print(f"default_values: {default_values}")

        source_language_id = str(default_values["language_id"].iloc[0])
        source_language_name = str(default_values["language_name"].iloc[0])

        source_feed_id = str(default_values["id"].iloc[0])

        publisher_article_body = (record_data.get('content') or [{}])[0].get('value') or record_data.get('summary', '')

        final_record = {
            "title": re.sub(r'\s+', ' ', title.strip()),
            "summary": re.sub(r'\s+', ' ', summary.strip()),
            "url": url,
            "sourcePublishDate": source_publish_date,
            "sourceThumbnailURL": source_thumbnail_url,
            "thumbnailUrls": {
                "original": f"https://icdn.jionews.com/original/{source_id}.jpeg",
                "fhd": f"https://icdn.jionews.com/fhd/{source_id}.jpeg",
                "hd": f"https://icdn.jionews.com/hd/{source_id}.jpeg",
                "low": f"https://icdn.jionews.com/low/{source_id}.jpeg",
                "sd": f"https://icdn.jionews.com/sd/{source_id}.jpeg"
            },
            "sourceId": source_id,
            'createdAt': epoch_now,
            "sourceLanguageId": source_language_id,
            "sourceLanguageName": source_language_name,
            "sourceCategoryId": source_category_id,
            "sourceCategoryName": source_category_name,
            "sourcePublisherId": source_publisher_id,
            "sourcePublisherName": source_publisher_name,
            "sourceFeedUrl": source_feed_url,
            "sourceFeedId": source_feed_id,
            "briefWordCount": len(re.findall(r'\b\w+\b', summary)),
            "isDefaultThumbnail": False,
            "publisherArticleBody": publisher_article_body
        }

        # Block (publisher, category) pairs in blocklist - skip auto-publish for these
        if self.is_blocked_publisher_category(source_publisher_name, source_category_name):
            self.blocked_by_category_count += 1
            return None

        # Add default category image if no thumbnail found (BUG-33735)
        if source_thumbnail_url == "":
            default_image = self.get_default_image(source_category_name)
            if default_image:
                final_record['sourceThumbnailURL'] = default_image['source_thumbnail_url']
                final_record['thumbnailUrls'] = default_image['thumbnail_urls']
                final_record['isDefaultThumbnail'] = True
                final_record['sourcePublisherName'] = "InsideMedia"
                final_record['sourcePublisherId'] = "000"

        processed_record = {"filename": source_id, "url": source_thumbnail_url, "category": source_category_name,
                            "publisher": source_publisher_name, "content_type": "summaries", "data": final_record}

        return processed_record

    def process_all_records(self, feed_id, default_values):
        processed_data = []
        self.debug(f"self.non_existing_records: {self.non_existing_records}")
        for record in self.non_existing_records:
            # print(f"default_values: {default_values}")
            try:
                processed_record = self.process_mapping(record, default_values)
                mapped_record = processed_record.get('data', {})
                if mapped_record:
                    # check if the record is hygienic
                    language_name = mapped_record.get('sourceLanguageName', '').lower()
                    # Hygiene reprocessing only for English
                    if language_name in ['english', 'hindi', 'marathi', 'kannada']:
                        hygiene_check = self.check_publisher_summary_hygiene(mapped_record)
                        isHygienic = hygiene_check['isHygienic']
                        if not isHygienic:
                            mapped_record['hygieneErrors'] = hygiene_check['errors']
                            mapped_record['isHygienic'] = isHygienic
                            self.unhygienic_records.append(mapped_record)
                            continue
                    processed_data.append(processed_record)
            except Exception as e:
                print(f"Exception caught while mapping. feed_id:{feed_id}, Exception:{e}")
            # return processed_data
        print(
            f"Processing Status::Total Records:{len(self.non_existing_records)}||blocked(pub/cat):{self.blocked_by_category_count}||unhygienic:{len(self.unhygienic_records)}||Processed Records:{len(processed_data)}")
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
        self.feeds_config = self.gcs.feeds_config
        self.processor = Processor(self.debug, self.feeds_config, self.ps)

    def run(self, message):
        """ => Fetch feed_id and feed_data from pubsub for a single
        feed Message format: {"feed_id": 1234, "feed_data": [...]}"""
        headlines_data = self.ps.parse_html_message(message)
        # headlines_data = message  # Message format: {"feed_id": 1234, "feed_data": [...]}
        all_records = headlines_data['feed_data']
        feed_id = headlines_data['feed_id']
        default_values = self.feeds_config.query(f"id == {feed_id}")
        # print(f"Default values: {default_values}")

        # print(f"Total {len(all_records)} records received")
        print(f"Total {len(all_records)} records received for feed_id: {feed_id}")

        """Deduplication logic to filter out data already existing. url+categoryId+languageId"""
        # """Turning off deduplication for bigquery cost optimisation"""
        # self.processor.non_existing_records = all_records
        source_language_id = str(default_values["language_id"].iloc[0])
        source_category_id = str(default_values["category_id"].iloc[0])

        self.processor.filter_records_from_cache(all_records, source_category_id, source_language_id)
        # print(f"Total {len(self.processor.non_existing_records)} unique, non processed records from {len(all_records)} received")
        print(
            f"Total Received: {len(all_records)} | Unique After Cache Filter: {len(self.processor.non_existing_records)} | feed_id: {feed_id}")

        """Data procession and mapping"""
        processed_data = self.processor.process_all_records(feed_id, default_values)
        # print(f"Total processed records: {len(processed_data)}")
        print(f"Total processed records: {len(processed_data)} for feed_id: {feed_id}")

        # """Publish thumbnail images to pubsub for cdn"""
        # if self.processor.cdn_image_data:
        #     # Save image data to json file
        #     # with open('image_data.json', 'w') as json_file:
        #     #     json.dump(self.processor.cdn_image_data, json_file)
        #     PubSub.publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", self.processor.cdn_image_data)
        # self.debug(f"Finale processed Data: {len(processed_data)}")
        #
        # """Publish final processed data to pubsub->mongodb"""
        # if processed_data:
        #     # save processed data to json file
        #     # with open('processed_data.json', 'w') as json_file:
        #     #     json.dump(processed_data, json_file)
        #     PubSub.publish_message_to_topic("RawSummariesIngestion_ProcessedData", processed_data)
        # else:
        #     print("All records already in cache")

        """
        *** Renaming publisher for summaries with no image (STORY 51524) ***
        Making the workflow synchronous to streamline handling of summaries without original image asset.
        """
        if processed_data:
            PubSub.publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", processed_data)

        """publish unhygienic records to separate pubsub topic"""
        if self.processor.unhygienic_records:
            for rec in self.processor.unhygienic_records:
                PubSub.publish_message_to_topic("RawSummariesIngestion_HygineFailure", [rec])
        print(f"Feed Processing Completed for Feed ID: {feed_id}")

        return feed_id


def main(msg, cntxt):
    execution_start_time = time.time()
    # print(f"debug:: msg:{type(msg)}, cntxt: {type(cntxt)}")
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    # try:
    exe = Execute(debugger=False)
    feed_id = exe.run(msg)
    # except Exception as e:
    #     print(f"Exception caught::\n{e}")
    # finally:
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minute -- {feed_id}")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}
