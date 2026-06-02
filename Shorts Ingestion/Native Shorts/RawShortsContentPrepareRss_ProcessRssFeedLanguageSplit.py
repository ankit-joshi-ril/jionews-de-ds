import base64
import datetime
import json
import time
import traceback
import warnings
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.cloud import storage

# Filter all warnings
warnings.filterwarnings("ignore")


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class GCS:
    def __init__(self):
        self.bucket_name = "hls_video_transcoder_storage_output_files"
        self.blob = "rss/shorts"

    def upload_xml_string_to_gcs(self, xml_string, file_name):
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(self.bucket_name)
            destination_blob_name = f"{self.blob}/{file_name}"
            blob = bucket.blob(destination_blob_name)
            blob.upload_from_string(xml_string.encode('utf-8'), content_type='application/rss+xml; charset=UTF-8')
            print(f"XML content uploaded to {self.bucket_name}/{destination_blob_name}.")
        except Exception as e:
            print(f"Exception caught while uploading XML to GCS:: {e}")


class RSS:

    def format_date_ist(self, date_str):
        try:
            if date_str[0].isdigit():
                # ISO format
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                # RFC 2822 format
                date = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        except Exception as e:
            print(f"Failed to parse date: {date_str} - {e}")
            # Use current UTC time as timezone-aware datetime
            date = datetime.now(timezone.utc)

        # Convert to IST (UTC+5:30)
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        date_ist = date.astimezone(ist_offset)

        # Format: Mon, 23 Jun 2025 03:50:37 GMT+0530
        return date_ist.strftime('%a, %d %b %Y %H:%M:%S GMT+0530')

    def pretty_print_xml(self, xml_bytes):
        try:
            parsed = xml.dom.minidom.parseString(xml_bytes)
            return parsed.toprettyxml(encoding='utf-8').decode('utf-8')
        except Exception as e:
            print(f"Failed to parse XML: {e}")
            return ""

    def prepare_rss(self, data_list):

        print("Preparing RSS Feed...")

        namespaces = {
            'media': 'http://search.yahoo.com/mrss/'
        }

        rss = ET.Element('rss', {'version': '2.0'})
        channel = ET.SubElement(rss, 'channel')
        ET.SubElement(channel, 'title').text = 'JioNews Videos RSS Feed'
        ET.SubElement(channel, 'link').text = 'https://jionews.com'
        ET.SubElement(channel, 'description').text = 'JioNews - RSS feed for videos'

        try:
            for item in data_list:
                # print(f"Processing item: {item}")
                item_elem = ET.SubElement(channel, 'item')
                ET.SubElement(item_elem, 'title').text = item['title']
                ET.SubElement(item_elem, 'link').text = item['videoContentUrl']
                ET.SubElement(item_elem, 'description').text = item['title']
                # PubDate
                # ET.SubElement(item_elem, 'pubDate').text = self.format_date_ist(item.get('sourceDate', ""))
                ET.SubElement(item_elem, 'pubDate').text = item['sourceDate']

                # Media:content
                media_content_elem = ET.SubElement(item_elem, '{{{media}}}content'.format(**namespaces))
                media_content_elem.set('url', item['videoContentUrl'])
                media_content_elem.set('duration', str(item.get('duration', '0')))
                media_content_elem.set('medium', 'video')
                media_content_elem.set('type', 'video/mp4')

                # Media:thumbnail
                media_thumbnail_elem = ET.SubElement(item_elem, '{{{media}}}thumbnail'.format(**namespaces))
                media_thumbnail_elem.set('url', item['sourceThumbnailURL'])
                media_thumbnail_elem.set('type', 'image/jpeg')

                # Keywords
                ET.SubElement(item_elem, 'keywords').text = 'news'

                # Category
                ET.SubElement(item_elem, 'category').text = item['sourceCategoryName']

                # SourceVideoId
                ET.SubElement(item_elem, 'sourceVideoId').text = item['sourceVideoId']

                # SourceCategoryId
                ET.SubElement(item_elem, 'sourceCategoryId').text = item['sourceCategoryId']

                # SourceLanguageId
                ET.SubElement(item_elem, 'sourceLanguageId').text = item['sourceLanguageId']

                # SourceLanguageName
                ET.SubElement(item_elem, 'sourceLanguageName').text = item['sourceLanguageName']

                # SourceThumbnailURL
                ET.SubElement(item_elem, 'sourceThumbnailURL').text = item['sourceThumbnailURL']

                # SourceDate
                ET.SubElement(item_elem, 'sourceDate').text = item['sourceDate']

                # Additional fields
                ET.SubElement(item_elem, 'sourceEpoch').text = str(item['sourceEpoch'])
                ET.SubElement(item_elem, 'sourcePublisherId').text = item['sourcePublisherId']
                ET.SubElement(item_elem, 'sourcePublisherName').text = item['sourcePublisherName']
                ET.SubElement(item_elem, 'sourceVideoWidth').text = str(item['sourceVideoWidth'])
                ET.SubElement(item_elem, 'sourceVideoHeight').text = str(item['sourceVideoHeight'])
                ET.SubElement(item_elem, 'sourceVideoOrientation').text = item['sourceVideoOrientation']
                ET.SubElement(item_elem, 'createdAt').text = str(item['createdAt'])

                # # thumbnail_mark = item.get('thumbnailUrls', item.get('sourceThumbnails', {}))
                # # print(f"Thumbnail mark: {thumbnail_mark}")
                # # print(f"type of thumbnail mark: {type(thumbnail_mark)}")
                # # print(f"items: {thumbnail_mark.items()}")
                # thumbnails_elem = ET.SubElement(item_elem, 'thumbnailUrls')
                # for key, value in item.get('thumbnailUrls', item.get('sourceThumbnails', {})).items():
                #     thumbnail_elem = ET.SubElement(thumbnails_elem, key)
                #     ET.SubElement(thumbnail_elem, 'url').text = value['url']
                #     ET.SubElement(thumbnail_elem, 'width').text = str(value['width'])
                #     ET.SubElement(thumbnail_elem, 'height').text = str(value['height'])

                thumbnails_elem = ET.SubElement(item_elem, 'thumbnailUrls')

                thumbnail_data = item.get('thumbnailUrls') or item.get('sourceThumbnails', {})

                # Define mapping from new format to old-style keys
                thumbnail_key_mapping = {
                    'low': 'default',
                    'sd': 'medium',
                    'hd': 'high',
                    'fhd': 'standard',
                    'original': 'maxres'
                }

                for key, value in thumbnail_data.items():
                    # Normalize key
                    normalized_key = thumbnail_key_mapping.get(key, key)

                    thumbnail_elem = ET.SubElement(thumbnails_elem, normalized_key)

                    if isinstance(value, dict):
                        ET.SubElement(thumbnail_elem, 'url').text = value.get('url', '')
                        ET.SubElement(thumbnail_elem, 'width').text = str(value.get('width', ''))
                        ET.SubElement(thumbnail_elem, 'height').text = str(value.get('height', ''))
                    elif isinstance(value, str):
                        # New format: just the URL string
                        ET.SubElement(thumbnail_elem, 'url').text = value
                        ET.SubElement(thumbnail_elem, 'width').text = ''
                        ET.SubElement(thumbnail_elem, 'height').text = ''
                    else:
                        print(f"Unexpected thumbnail format for key '{key}': {value}")

            for ns_prefix, ns_uri in namespaces.items():
                ET.register_namespace(ns_prefix, ns_uri)
            print(f"Rss Feed created successfully!")
        except Exception as e:
            print(f"Exception caught while preparing RSS Feed:: {e}")
            print(f"Error for item:: {item}")
            traceback.print_exc()

        xml_bytes = ET.tostring(rss, encoding='utf-8', method='xml')
        return self.pretty_print_xml(xml_bytes)


class Execute:
    def __init__(self):
        print("execution started")
        self.pubsub = PubSub()
        self.gcs = GCS()
        self.rss = RSS()

    def run(self, message):
        data = self.pubsub.parse_message(message)
        # data = message
        language = data["language"]
        target_languages = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13']
        if language not in target_languages:
            print(f"Language {language} not in target languages {target_languages}. Skipping processing.")
            return None
        data_records = data['topVideos']
        language = data_records[0]['sourceLanguageName'].replace(" ", "").lower()

        print(f"Total {len(data_records)} received for {language}")
        filename = f"{language}/rss.xml"

        print(f"filename:{filename}")

        xml_string = self.rss.prepare_rss(data_records)

        if xml_string:
            self.gcs.upload_xml_string_to_gcs(xml_string, filename)
        else:
            print(f"Error in the feed for language: {language}")


def main(message, context):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute()
    exe.run(message)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}