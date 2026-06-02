import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup
from google.cloud import pubsub_v1
from google.cloud import storage
from jsonpath_ng import parse


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
    def convert_relative_to_timestamp(time_str):
        """
        Converts relative time (X seconds/minutes/hours/days/weeks/months/years ago) to timestamp.
        :param time_str: relative time string (e.g. "17 minutes ago", "2 days ago", "3 weeks ago")
        :return: formatted timestamp in IST, or None if unparseable
        """
        if not time_str:
            return None

        zone = ZoneInfo("Asia/Kolkata")
        current_time = datetime.now(tz=zone)
        time_str_lower = time_str.lower()

        parts = time_str_lower.split()
        if not parts:
            return None
        try:
            amount = int(parts[0])
        except (ValueError, IndexError):
            return None

        if 'second' in time_str_lower:
            timestamp = current_time - timedelta(seconds=amount)
        elif 'minute' in time_str_lower:
            timestamp = current_time - timedelta(minutes=amount)
        elif 'hour' in time_str_lower:
            timestamp = current_time - timedelta(hours=amount)
        elif 'day' in time_str_lower:
            timestamp = current_time - timedelta(days=amount)
        elif 'week' in time_str_lower:
            timestamp = current_time - timedelta(weeks=amount)
        elif 'month' in time_str_lower:
            timestamp = current_time - timedelta(days=amount * 30)
        elif 'year' in time_str_lower:
            timestamp = current_time - timedelta(days=amount * 365)
        else:
            return None
        return str(timestamp)

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
        self.topic_name = "NewRawVideosIngestion_publishers_channel_data"
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
        except Exception as err:
            print(f"Message Publishing Error: {err}")


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


class Scrapper:
    def __init__(self, debug):
        self.debug = debug
        # self.scraped_video_ids = []

    def fetch_html(self, publisher_custom_url: str):
        """
        Scrapes HTML of the YT channel shorts page
        :param publisher_custom_url: unique channel ID/name appended with '@' | eg: @bqprime
        :return: Raw HTML String
        """
        url = f"http://www.youtube.com/{publisher_custom_url}/shorts"
        try:
            response = requests.get(url, timeout=5)
            return response.text
        except Exception as e:
            print(f"Exception caught fetching {url}: {e}")
            return ""

    def extract_video_ids(self, html_string: str):
        """
        Extracts YT shorts videoIds from raw HTML page
        :param html_string: Raw HTML string
        :return: Stores the curated video IDs to self.scraped_video_ids
        """
        soup = BeautifulSoup(html_string, 'html.parser')
        filtered_tags = soup.find_all(lambda tag: tag.name == 'script' and 'videoId' in tag.text)
        script_content = filtered_tags[0].text
        start_index = script_content.find('{"responseContext"')
        end_index = script_content.rfind('}};') + 2
        json_content = script_content[start_index:end_index]
        yt_initial_data = json.loads(json_content)
        expression = parse("$..videoId")
        video_ids = list(set([match.value for match in expression.find(yt_initial_data)]))
        # self.scraped_video_ids.extend(video_ids)

        return video_ids

    def scrape_channel_shorts(self, publisher_custom_url: str):
        """
        Extracts and curates YT shorts videoIds from YT shorts page
        :param publisher_custom_url: unique channel ID/name appended with '@' | eg: @bqprime
        :return: Stores the curated video IDs
        """

        html_string = self.fetch_html(publisher_custom_url)
        video_ids = []
        try:
            video_ids = self.extract_video_ids(html_string)
        except Exception as e:
            print(f"Exception caught while parsing HTML for channel: {publisher_custom_url}")

        return video_ids


class Processor:
    def __init__(self, debug, publishers_config, ps):
        self.total_failures = 0
        self.total_successes = 0
        self.debug = debug
        self.publishers_config = publishers_config
        self.ps = ps
        self.max_threads = 10
        self.all_channels_data = []

    @staticmethod
    def _find_all(data, key, _depth=0, _max_depth=20):
        """
        Pure-Python replacement for jsonpath_ng '$..key'.
        Returns a list of every value mapped to 'key' at any nesting depth.
        """
        if _depth > _max_depth:
            return []
        results = []
        if isinstance(data, dict):
            if key in data:
                results.append(data[key])
            for v in data.values():
                results.extend(Processor._find_all(v, key, _depth + 1, _max_depth))
        elif isinstance(data, list):
            for item in data:
                results.extend(Processor._find_all(item, key, _depth + 1, _max_depth))
        return results

    def fetch_html(self, channel_id):
        """
        Scrapes HTML of the YT channel 'videos' section
        :param channel_id: unique channel_id
        :return: Raw HTML String
        """
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        try:
            response = requests.get(url, timeout=10, headers=headers)
            return response.text
        except Exception as e:
            print(f"Exception caught fetching {url}: {e}")
            return ""

    def get_channel_videos_data(self, page_html_string):
        """
        Parses ytInitialData from a YouTube channel /videos page and extracts video metadata.

        Handles three YouTube page layouts:
          1. Legacy  -videoRenderer inside gridRenderer
          2. Mid-gen -videoRenderer nested inside richItemRenderer.content
          3. New     -lockupViewModel inside richItemRenderer.content (2024+)

        Returns a list of dicts with keys:
            video_id, title, published_time, duration, width, height, orientation
        Returns [] on any unrecoverable parse failure (never raises).
        """
        soup = BeautifulSoup(page_html_string, 'html.parser')

        # --- 1. Locate the ytInitialData script tag -----------------------------------
        # Older layout: tag contains 'videoId' directly.
        # New layout (lockupViewModel): tag contains 'ytInitialData' but no 'videoId'.
        # Using 'ytInitialData' as the selector covers both.
        yt_data_tags = [t for t in soup.find_all('script') if 'ytInitialData' in (t.string or '')]
        if not yt_data_tags:
            print("get_channel_videos_data: no ytInitialData script tag found -bot/consent page?")
            return []

        script_content = yt_data_tags[0].string
        start_index = script_content.find('{"responseContext"')
        if start_index == -1:
            print("get_channel_videos_data: responseContext marker not found in ytInitialData")
            return []

        end_index = script_content.rfind('}};') + 2
        if end_index <= start_index:
            end_index = len(script_content)

        try:
            yt_initial_data = json.loads(script_content[start_index:end_index])
        except json.JSONDecodeError as e:
            print(f"get_channel_videos_data: JSON parse error -{e}")
            return []

        all_channel_videos = []

        # --- 2. Layout A: legacy videoRenderer (gridRenderer or standalone) -----------
        video_renderer_matches = self._find_all(yt_initial_data, 'videoRenderer')
        for rv in video_renderer_matches:
            try:
                video_id = rv.get('videoId', '') if isinstance(rv, dict) else ''
                if not video_id:
                    continue

                title = ''
                try:
                    runs = rv['title']['runs']
                    title = runs[0]['text'] if runs else ''
                except (KeyError, IndexError, TypeError):
                    title = rv.get('title', {}).get('simpleText', '') if isinstance(rv, dict) else ''

                published_time = ''
                try:
                    published_time = rv['publishedTimeText']['simpleText']
                except (KeyError, TypeError):
                    pass

                duration = ''
                try:
                    duration = rv['lengthText']['simpleText']
                except (KeyError, TypeError):
                    pass

                width, height = 0, 0
                try:
                    thumb = rv['thumbnail']['thumbnails'][0]
                    width = thumb.get('width', 0)
                    height = thumb.get('height', 0)
                except (KeyError, IndexError, TypeError):
                    pass

                all_channel_videos.append({
                    'video_id': video_id,
                    'title': title,
                    'published_time': Utils.convert_relative_to_timestamp(published_time),
                    'duration': duration,
                    'width': width,
                    'height': height,
                    'orientation': 'landscape' if width >= height else 'portrait',
                })
            except Exception:
                continue  # skip malformed record, never crash the whole channel

        if all_channel_videos:
            return all_channel_videos

        # --- 3. Layout B: new lockupViewModel (richItemRenderer, 2024+) ---------------
        lvm_matches = self._find_all(yt_initial_data, 'lockupViewModel')
        for lvm in lvm_matches:
            try:
                if not isinstance(lvm, dict):
                    continue
                if lvm.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
                    continue

                video_id = lvm.get('contentId', '')
                if not video_id:
                    continue

                title = ''
                try:
                    title = lvm['metadata']['lockupMetadataViewModel']['title']['content']
                except (KeyError, TypeError):
                    pass

                # Published time is the metadataPart that contains the word "ago"
                published_time = ''
                try:
                    rows = lvm['metadata']['lockupMetadataViewModel']['metadata']['contentMetadataViewModel'][
                        'metadataRows']
                    for row in rows:
                        for part in row.get('metadataParts', []):
                            val = part.get('text', {}).get('content', '')
                            if 'ago' in val:
                                published_time = val
                                break
                        if published_time:
                            break
                except (KeyError, TypeError):
                    pass

                # Duration is in the thumbnail overlay badge text (e.g. "3:30")
                duration = ''
                try:
                    overlays = lvm['contentImage']['thumbnailViewModel']['overlays']
                    for overlay in overlays:
                        for badge in overlay.get('thumbnailBottomOverlayViewModel', {}).get('badges', []):
                            badge_text = badge.get('thumbnailBadgeViewModel', {}).get('text', '')
                            if badge_text:
                                duration = badge_text
                                break
                        if duration:
                            break
                except (KeyError, TypeError):
                    pass

                # Thumbnail -use the largest source (last in list)
                width, height = 0, 0
                try:
                    sources = lvm['contentImage']['thumbnailViewModel']['image']['sources']
                    if sources:
                        width = sources[-1].get('width', 0)
                        height = sources[-1].get('height', 0)
                except (KeyError, TypeError, IndexError):
                    pass

                all_channel_videos.append({
                    'video_id': video_id,
                    'title': title,
                    'published_time': Utils.convert_relative_to_timestamp(published_time),
                    'duration': duration,
                    'width': width,
                    'height': height,
                    'orientation': 'landscape' if width >= height else 'portrait',
                })
            except Exception:
                continue  # skip malformed record, never crash the whole channel

        return all_channel_videos

    def fetch_publish_channel_data(self, publisher_channel_details):
        publication_id = publisher_channel_details['publication_id']
        channel_id = publisher_channel_details['channel_id']
        publisher_name = publisher_channel_details['publisher_name']

        html_string = self.fetch_html(channel_id)
        if html_string:
            try:
                all_channel_videos = self.get_channel_videos_data(html_string)
            except Exception as e:
                print(f"Exception caught parsing HTML for {publisher_name}({channel_id}): {e}")
                all_channel_videos = []
            if len(all_channel_videos) > 0:
                records = {'publication_id': publication_id, 'data': all_channel_videos}
                self.ps.publish_message(records)
                print(f"Total {len(all_channel_videos)} videos published for {publisher_name}({channel_id})")
                self.all_channels_data.append(records)
            else:
                print(f"No data for {publisher_name}({channel_id})")
        else:
            print(f"No HTML fetched for {publisher_name}({channel_id})")

    def process_all_channels_data(self):
        self.debug(f"fetch_all_channels_data started -- {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
        total_processed = 0
        # active_feeds = self.publishers_config.query("is_active")

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = [executor.submit(self.fetch_publish_channel_data, row) for i, row in
                       self.publishers_config.iterrows()]
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
                            f"processed {total_processed}/{len(self.publishers_config)} -- {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")

            self.debug(f"fetch_all_feeds_data ended -- {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")


class Execute:
    """
    -> Read publisher channels list form GCS
    -> Scrape videos data form each publisher channel
    -> Push to pubsub for further processing
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

    def run(self):
        self.processor.process_all_channels_data()
        # with open('videos_all_channels_data_set2.json', "w") as json_file:
        #     json.dump(self.processor.all_channels_data, json_file)


def main(req_ph, req_ph2):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    # try:
    exe = Execute(debugger=True)
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