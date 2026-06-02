import json
import re
import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
import requests
from google.cloud import pubsub_v1
from google.cloud import storage

# Filter out the specific warning
warnings.filterwarnings("ignore", category=UserWarning)

RUN_LOCAL = False


class PubSub:
    def __init__(self):
        # self.topic_name = "MRSSVideosIngestion_RawFeedsData"
        self.topic_name = "MRSSShortsIngestion_RawFeedsData"
        self.project_id = "jiox-328108"
        self.pubsub = pubsub_v1.PublisherClient()
        self.topic_path = self.pubsub.topic_path(self.project_id, self.topic_name)

    def publish_message(self, records):
        json_string = json.dumps(records)
        print(f"Final JSON String: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            self.pubsub.publish(self.topic_path, data=message_bytes)
            print("Message published.")
            return "success"
        except Exception as err:
            # print(f"Message Publishing Error: {err}")
            return f"Message Publishing Error: {err}"


class GCS:
    def __init__(self):
        self.bucket_name = "de-raw-ingestion"
        self.file_path = "shorts/mrss_shorts_feeds.csv"
        self.feeds_config = None

    def read_csv_from_gcs(self):
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self.file_path)
        csv_bytes = blob.download_as_string()
        df = pd.read_csv(BytesIO(csv_bytes))
        self.feeds_config = df


class Processor:
    def __init__(self, feeds_config, ps):
        self.total_failures = 0
        self.total_successes = 0
        self.feeds_config = feeds_config
        self.ps = ps
        self.max_threads = 100
        self.all_feeds_data = []
        self.empty_feeds = 0

    def handle_custom_image_tags(self, raw_response):
        """
        This method replaces <image> tags with <thumbimage> tags; to be picked by feedparser;
        since <image> is a custom tag and not recognized by feedparser
        """
        if raw_response:
            return re.sub(r"(?<!<thumbimage>)(</?image>)(?!</thumbimage>)",
                          lambda m: "<thumbimage>" if m.group(0) == "<image>" else "</thumbimage>", raw_response)
        else:
            return ""

    def get_raw_feeds(self, feed_url, feed_id):
        # AJ- Json handler patch as per STORY 35583 (261124)
        response_data = {'content_type': "", 'response_text': ""}
        response = None
        try:
            response = requests.get(feed_url)
            response.raise_for_status()  # Raise an exception for HTTP error codes
            content_type = response.headers.get('Content-Type', '').lower()
            raw_response = response.text
            if 'application/json' in content_type:
                response_data['content_type'] = 'json'
                response_data['response_text'] = raw_response
            else:
                response_data['content_type'] = 'xml'
                response_data['response_text'] = self.handle_custom_image_tags(raw_response)
        except requests.exceptions.RequestException as e:
            status_code = None
            if response is not None:
                status_code = response.status_code
            print(
                f"LogId{feed_id} || Error fetching feed from {feed_url} || Exception: {str(e)} || status_code:{status_code}")  # Log error message
        return response_data

    def fetch_third_party_api_data(self, channels_url, feed_id):
        """Fetch data from third-party partner API (channels endpoint → paginated videos per channel)."""
        feed_list = []
        try:
            response = requests.get(channels_url)
            response.raise_for_status()
            channels = response.json()
            base_url = channels_url.rsplit('/channels', 1)[0]
            videos_url = base_url + '/videos'
        except Exception as e:
            print(f"LogId{feed_id} || Error fetching channels from {channels_url}: {e}")
            return feed_list

        for channel in channels:
            if channel.get('status') != 'active':
                continue
            ch_id = channel.get('ch_id')
            if not ch_id:
                continue
            page = 1
            while True:
                try:
                    v_response = requests.get(videos_url, params={'channel_id': ch_id, 'page': page})
                    v_response.raise_for_status()
                    v_data = v_response.json()
                    channel_info = v_data.get('channel', {})
                    total_pages = v_data.get('total_pages', 1)
                    for video in v_data.get('videos', []):
                        video['ch_publication_name'] = channel_info.get('ch_publication_name', '')
                        video['ch_language'] = channel_info.get('ch_language', '')
                        video['ch_category'] = channel_info.get('ch_category', '')
                        # Normalise to fields expected by downstream deduplication + process_mapping
                        video['link'] = video.get('vid_url', '')
                        if not video.get('title'):
                            video['title'] = video.get('vid_title', '')
                        feed_list.append(video)
                    if page >= total_pages:
                        break
                    page += 1
                except Exception as e:
                    print(f"LogId{feed_id} || Error fetching videos ch_id={ch_id} page={page}: {e}")
                    break

        # Only pass records the third party downloaded in the last 24h and that have
        # a valid video file. This prevents re-ingesting the partner's full historical
        # catalogue every time Redis dedup entries expire (was causing 479 vs 293 gap).
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        before = len(feed_list)
        feed_list = [
            v for v in feed_list
            if (v.get('vid_file') or '').strip()  # skip records with no downloadable video
               and v.get('vid_download_date')
               and datetime.fromisoformat(
                v['vid_download_date'].replace('Z', '+00:00')
            ) >= cutoff
        ]
        print(
            f"LogId{feed_id} || third_party: {len(feed_list)}/{before} records after 24h download_date + vid_file filter")

        return feed_list

    def fetch_feed_data(self, feeds_data):
        """
        -> First try with the raw response through requests and then parse through feedparser
        -> If that doesn't work, use feedparser to fetch the data directly through URL
        :param feeds_data:
        :return:
        # AJ- Json handler patch as per STORY 35583 (261124)
        """
        feed_url = feeds_data['feed_url']
        feed_id = feeds_data['id']
        publication_id = feeds_data['publication_id']
        feed_list = []

        if publication_id == 7784:
            feed_list = self.fetch_third_party_api_data(feed_url, feed_id)
        else:
            response_data = self.get_raw_feeds(feed_url, feed_id)
            content_type = response_data.get('content_type', "")
            raw_feed = response_data.get('response_text', "")

            if raw_feed:
                if content_type == 'json':
                    if feed_id in [49, 50]:
                        feed_list = json.loads(raw_feed)['data']
                    else:
                        feed_list = json.loads(raw_feed)['items']
                else:
                    feed = feedparser.parse(raw_feed)
                    feed_list = feed.entries
            else:
                try:
                    feed = feedparser.parse(feed_url)
                    feed_list = feed.entries
                except Exception as e:
                    print(f"LogId{feed_id}:: Feed Error exception fetching data feed_id-{feed_id} :: {e}")

        if len(feed_list) > 0:
            records = {'feed_id': feed_id, 'feed_data': feed_list}
            publish_status = None
            if RUN_LOCAL:
                self.all_feeds_data.append(records)
            else:
                publish_status = self.ps.publish_message(records)

                if publish_status != 'success':
                    print(f"LogId{feed_id}:: Feed Error publishing for feed_id {feed_id}::: {publish_status}")
        else:
            print(f"LogId{feed_id}:: Feed Error no data feed_id-{feed_id}")
            self.empty_feeds += 1

    # return {'feed_id': feed_id, 'feed_data': feed_list}

    def fetch_all_feeds_data(self):
        total_processed = 0
        # active_feeds = self.feeds_config.query("is_active")
        # only where publication_id is '7782'
        # active_feeds = self.feeds_config[self.feeds_config['publication_id'] == 7782]
        active_feeds = self.feeds_config

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = [executor.submit(self.fetch_feed_data, row) for i, row in active_feeds.iterrows()]
            i = 0
            for future in futures:
                i += 1
                try:
                    result = future.result()
                    if result:
                        self.total_successes += 1
                    else:
                        self.total_failures += 1
                except Exception as e:
                    print(f"Exception caught while executing thread::: {e}")
                    traceback.print_exc()
                finally:
                    total_processed += 1
                    if i % 100 == 0:
                        print(
                            f"processed {total_processed}/{len(active_feeds)} s:{self.total_successes}, f:{self.total_failures}  -- {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")


class Execute:
    """
    -> Get all the publisher Feed details from 'de-raw-ingestion/videos/mrss_videos_feeds.csv'
    -> Iterate through all the publishers and fetch feeds data in multiple threads.
    -> Publish data to pubsub for further processing.
    """

    def __init__(self):
        print("execution started")
        self.ps = PubSub()
        self.gcs = GCS()
        self.gcs.read_csv_from_gcs()
        self.feeds_config = self.gcs.feeds_config
        self.processor = Processor(self.feeds_config, self.ps)

    def run(self):
        self.processor.fetch_all_feeds_data()
        if RUN_LOCAL:
            with open('mrss_videos_Nov25.json', "w") as json_file:
                json.dump(self.processor.all_feeds_data, json_file)
        print(f"total empty_feeds: {self.processor.empty_feeds}")


def main(req_ph1):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute()
    exe.run()
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}
