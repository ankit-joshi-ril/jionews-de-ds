import base64
import csv
import json
import os
import time
import warnings
from datetime import datetime, timedelta
from math import gcd
from zoneinfo import ZoneInfo

import paramiko
import pytz
from bson import ObjectId
from google.cloud import secretmanager
from google.cloud import storage
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pymongo import MongoClient, errors, UpdateOne

# Ignore all warnings
warnings.filterwarnings("ignore")

_run_local = False
_zone = ZoneInfo("Asia/Kolkata")
path = os.path
root = path.dirname(path.abspath(__file__))

# Supported resolutions for horizontal (landscape) video content
# Source: transcoder team spec — files outside these dimensions will be rejected
ALLOWED_RESOLUTIONS = {(1920, 1080), (1280, 720)}


class Utils:
    @staticmethod
    def generate_epoch_range(interval_minutes):
        timezone = pytz.timezone('Asia/Kolkata')
        now = datetime.now(timezone)
        start_minute = (now.minute // interval_minutes) * interval_minutes - interval_minutes
        start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=start_minute)
        end_time = start_time + timedelta(minutes=interval_minutes) - timedelta(seconds=1)
        start_epoch = int(start_time.timestamp())
        end_epoch = int(end_time.timestamp())

        return {'start_epoch': start_epoch, 'end_epoch': end_epoch}

    @staticmethod
    def get_current_epoch():
        now = datetime.now(_zone)
        current_epoch = int(now.timestamp())
        return current_epoch

    @staticmethod
    def get_secret(secret_name):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload


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
        self.blob = "raw_videos"

    def download_file_from_gcs(self, source_blob_name: str, destination_file_name: str):
        print(f"Downloading file from GCS: {source_blob_name}")
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(f"{self.blob}/{source_blob_name}")
        try:
            blob.download_to_filename(destination_file_name)
            print(f"Downloaded {source_blob_name} to {destination_file_name}")
            return True
        except Exception as e:
            print(f"Failed to download {source_blob_name}: {e}")
            return False

    def delete_gcs_file(self, file_name):
        try:
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(file_name)

            if blob.exists():
                blob.delete()
            else:
                print(f"File not found: {file_name} in bucket: {self.bucket_name}")

        except Exception as e:
            print(f"Error deleting file: {file_name}")
            print(str(e))


class VideoMetadataExtractor:
    """
    Extracts technical metadata from a local MP4 file using hachoir (pure Python).
    Falls back to file-size-only if hachoir fails.

    Fields written to MongoDB:
      videoWidth, videoHeight, videoDurationSecs, videoFileSizeBytes, videoAspectRatio
    """

    @staticmethod
    def _safe_int(val, default=0):
        try:
            return int(val) if val is not None and val != '' else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _aspect_ratio(width, height):
        try:
            w, h = int(width), int(height)
            if not w or not h:
                return ""
            g = gcd(w, h)
            return f"{w // g}:{h // g}"
        except (ValueError, TypeError, ZeroDivisionError):
            return ""

    @classmethod
    def extract(cls, file_path):
        """
        Main entry point. Returns metadata dict. Never raises.
        hachoir reads width/height/duration directly from the MP4 moov box — accurate and fast.
        Falls back to size_only if hachoir fails.
        """
        try:
            parser = createParser(file_path)
            if not parser:
                raise RuntimeError("hachoir: could not create parser")
            with parser:
                meta = extractMetadata(parser)
            if not meta:
                raise RuntimeError("hachoir: extractMetadata returned None")

            # hachoir's meta.get() RAISES (not returns None) on absent keys — always guard with meta.has()
            width = cls._safe_int(meta.get('width')) if meta.has('width') else 0
            height = cls._safe_int(meta.get('height')) if meta.has('height') else 0

            duration_secs = 0.0
            if meta.has('duration'):
                dur = meta.get('duration')
                try:
                    duration_secs = round(dur.total_seconds(), 3)
                except AttributeError:
                    duration_secs = round(float(str(dur).replace(' seconds', '').strip()), 3)

            return {
                'videoWidth': width,
                'videoHeight': height,
                'videoDurationSecs': duration_secs,
                'videoFileSizeBytes': cls._safe_int(os.path.getsize(file_path)),
                'videoAspectRatio': cls._aspect_ratio(width, height),
            }

        except Exception as e:
            print(f"[metadata] hachoir failed: {e} — using file size only")

        # Fallback: file size only
        file_size = 0
        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            pass
        return {
            'videoWidth': 0, 'videoHeight': 0, 'videoDurationSecs': 0.0,
            'videoFileSizeBytes': file_size, 'videoAspectRatio': '',
        }


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

    def get_mongo_record(self, video_id):
        try:
            record = self.raw_videos_rss.find_one({"sourceVideoId": video_id})
            if record:
                return record
            else:
                print(f"No record found for video_id: {video_id}")
                return None
        except Exception as e:
            print(f"Failed to get record for video_id {video_id}: {e}")
            return None

    def update_records_in_mongodb(self, records, use_source_video_id=True):
        """
        Updates records in MongoDB using bulk operations.
        Works for both a single record (dict) and a list of records.

        :param records: dict or list of dicts containing record(s) to update
        :param use_source_video_id: bool - if True, update using 'sourceVideoId',
                                      else update using '_id'
        :return: number of modified records
        """
        if not records:
            print("No records received for update.")
            return 0

        # Normalize input to a list
        if isinstance(records, dict):
            records = [records]

        bulk_operations = []
        key_field = "sourceVideoId" if use_source_video_id else "_id"

        for record in records:
            try:
                if key_field not in record:
                    print(f"Skipping record without '{key_field}': {record}")
                    continue

                # Prepare filter for MongoDB update
                if key_field == "_id":
                    filter_query = {"_id": ObjectId(record["_id"])}
                else:
                    filter_query = {"sourceVideoId": record["sourceVideoId"]}

                # Remove the key field from update payload
                update_data = {k: v for k, v in record.items() if k != key_field}

                bulk_operations.append(
                    UpdateOne(filter_query, {"$set": update_data})
                )

            except Exception as e:
                print(f"Error preparing update for record {record.get(key_field)}: {e}")

        if not bulk_operations:
            print("No valid bulk operations to execute.")
            return 0

        try:
            result = self.raw_videos_rss.bulk_write(bulk_operations)
            return result.modified_count
        except Exception as e:
            print(f"MongoDB bulk update failed: {e}")
            return 0


class SFTP:
    def __init__(self):
        secret_name = "projects/266686822828/secrets/de_trascoder_sftp/versions/latest"
        sftp_creds = Utils.get_secret(secret_name)
        self.sftp_details = json.loads(sftp_creds)

    def connect(self):
        transport = paramiko.Transport((self.sftp_details['hostname'], self.sftp_details['port']))
        transport.connect(username=self.sftp_details['username'], password=self.sftp_details['password'])
        return paramiko.SFTPClient.from_transport(transport)

    def upload_to_sftp(self, local_file_path, remote_file_path):
        upload_status = ""
        sftp = self.connect()
        remote_dir = os.path.dirname(remote_file_path)
        try:
            sftp.stat(remote_dir)
        except Exception as e:
            upload_status = f"failed to find remote directory {remote_dir}: {e}"
            print(upload_status)
        try:
            sftp.put(local_file_path, remote_file_path)
            upload_status = "success"
        except Exception as e:
            upload_status = f"Failed to upload {local_file_path}: {e}"
            print(upload_status)
        finally:
            sftp.close()
            return upload_status


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.gcs = GCS()
        self.db = MongoDB()
        self.sftp = SFTP()

        if _run_local:
            self.tmp_dir = 'tmp'
        else:
            self.tmp_dir = '/tmp'

    def generate_transcoder_csv(self, filename_no_ext: str, language: str, output_path: str):
        headers = ["FileName", "ContentType", "Title", "Synopsis", "ReleaseDate", "RightsOwner", "RightsStartDate",
                   "RightsEndDate", "ReleaseTime", "Genre", "SubGenre", "Language", "Starcast", "Director",
                   "MusicDirector", "CensorCertification", "Keywords", "MaturityRating", "MaturityDescriptor",
                   "Download", "GeoBlock", "Subscription", "AdCueTime1 ", "AdCueTime2", "AdCueTime3", "AdCueTime4",
                   "AdCueTime5", "AdCueTime6", "AdCueTime7", "AdCueTime8", "IntroCreditsStart Time",
                   "IntroCreditsEndTime", "EndCreditsStartTime", "EndCreditsEndTime", "Producer", "Writer",
                   "IMDBRating", "ContentShortName", "Characters", "SeriesSeasonNumber", "EpisodeName",
                   "EpisodeSynopsis", "EpisodeNumber", "Precap Credits: Start Time (00:00:00)",
                   "Precap Credits: End Time (00:00:00)", "Recap Credits: Start Time (00:00:00)",
                   "Recap Credits: End Time (00:00:00)", "Singer", "Lyricyst", "Label", "ShowID", "AlbumName",
                   "LoopPlay", "ChannelID"]

        # Update lanuge name to standard ISO format
        if language == "Bangla":
            language = "Bengali"

        # Build values strictly in *exact* header order
        values = []
        for header in headers:
            if header == "FileName":
                values.append(filename_no_ext)
            elif header == "ContentType":
                values.append("Video")
            elif header == "Language":
                values.append(language)
            else:
                values.append("")  # Fill remaining fields with empty values

        with open(output_path, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            writer.writerow(values)

    def cleanup_files(self, *files: str) -> None:
        for file in files:
            if os.path.exists(file):
                os.remove(file)

    def process(self, video_rec):

        video_id = video_rec.get('sourceVideoId')
        file_name = f"{video_id}.mp4"
        print(f"{video_id}:: meta_data: {video_rec}")
        language_name = video_rec['sourceLanguageName']

        try:
            print(f"{video_id}:: Generating csv..")
            local_csv_path = f"{self.tmp_dir}/{video_id}.csv"
            self.generate_transcoder_csv(video_id, language_name, local_csv_path)
            print(f"{video_id}:: csv generated successfully at {local_csv_path}")

            print(f"{video_id}:: Fetching video from GCS..")
            local_video_path = f"{self.tmp_dir}/{file_name}"
            self.gcs.download_file_from_gcs(file_name, local_video_path)
            print(f"{video_id}:: Video fetched from GCS at {local_video_path}")

            # Extract metadata while file is already on disk — zero extra cost
            print(f"{video_id}:: Extracting video metadata..")
            metadata = VideoMetadataExtractor.extract(local_video_path)
            video_rec.update(metadata)
            w, h = metadata.get('videoWidth', 0), metadata.get('videoHeight', 0)
            print(f"{video_id}:: Metadata: {w}x{h} "
                  f"dur={metadata.get('videoDurationSecs')}s "
                  f"size={metadata.get('videoFileSizeBytes')}B "
                  f"ratio={metadata.get('videoAspectRatio')}")

            # Resolution hygiene check — reject files with unsupported dimensions
            # GCS file is intentionally preserved for audit; only local temp files are cleaned up
            if w == 0 or h == 0:
                # hachoir could not read dimensions from the file
                print(f"{video_id}:: Hygiene check FAILED — could not extract video dimensions")
                self.cleanup_files(local_csv_path, local_video_path)
                video_rec['isHygienic'] = False
                video_rec['hygieneFailureReason'] = "METADATA_UNREADABLE"
                video_rec['errorMessage'] = "Could not extract video dimensions from file"
                video_rec['transcoderProcessingStatus'] = "failed"
                return video_rec

            if (w, h) not in ALLOWED_RESOLUTIONS:
                error_detail = (
                    f"Unsupported resolution {w}x{h}. "
                    f"Supported: {', '.join(f'{rw}x{rh}' for rw, rh in sorted(ALLOWED_RESOLUTIONS))}"
                )
                print(f"{video_id}:: Hygiene check FAILED — {error_detail}")
                self.cleanup_files(local_csv_path, local_video_path)
                video_rec['isHygienic'] = False
                video_rec['hygieneFailureReason'] = "RESOLUTION_MISMATCH"
                video_rec['errorMessage'] = error_detail
                video_rec['transcoderProcessingStatus'] = "failed"
                return video_rec

            video_rec['isHygienic'] = True
            print(f"{video_id}:: Hygiene check PASSED — resolution {w}x{h} is supported")

            print(f"{video_id}:: Uploading video to SFTP..")
            upload_status = self.sftp.upload_to_sftp(local_video_path,
                                                     f"/media/newcpp/jionews2jiohotstar/watch/{video_id}.mp4")
            if upload_status != 'success':
                video_rec['transcoderProcessingStatus'] = "failed"
                video_rec['errorMessage'] = upload_status
                return video_rec
            print(f"{video_id}:: Video uploaded to SFTP successfully")

            print(f"{video_id}:: Uploading csv to SFTP...")
            upload_status = self.sftp.upload_to_sftp(local_csv_path,
                                                     f"/media/newcpp/jionews2jiohotstar/watch/{video_id}.csv")
            if upload_status != 'success':
                video_rec['transcoderProcessingStatus'] = "failed"
                video_rec['errorMessage'] = upload_status
                return video_rec
            print(f"{video_id}:: csv uploaded to SFTP successfully")

            # Cleanup local files
            self.cleanup_files(local_csv_path, local_video_path)

            video_rec['transcoderProcessingStatus'] = "submitted"
            return video_rec
        except Exception as e:
            error_message = f"Failed to process video to sftp. Exception: {e}"
            print(error_message)
            video_rec['transcoderProcessingStatus'] = "failed"
            video_rec['errorMessage'] = error_message
            return video_rec

    def run(self, message):
        video_rec = self.pubsub.parse_message(message)[0]
        video_id = video_rec['sourceVideoId']
        print(f"Processing for video_id: {video_id}")

        # Always re-fetch from DB — never trust payload status (payload is stale 'initiated' on every retry)
        current_db_record = self.db.get_mongo_record(video_id)
        if not current_db_record:
            # DB lookup failed or record not found — fall back to payload status (safe degradation, avoids silent drop)
            print(f"Video {video_id}: DB lookup returned None. Falling back to payload status check.")
            t_processing_status = video_rec.get('transcoderProcessingStatus', "")
        else:
            t_processing_status = current_db_record.get('transcoderProcessingStatus', "")
        print(f"Video {video_id} transcoderProcessingStatus: {t_processing_status}")

        # Skip only true terminal states. 'submitting' is NOT in this list — it is a transient in-flight state.
        # Including 'submitting' would permanently block retries if Cloud Run crashes mid-SFTP upload.
        if t_processing_status not in ["completed", "submitted"]:
            video_rec['transcoderProcessingStatus'] = "submitting"
            video_rec['updatedAt'] = Utils.get_current_epoch()
            self.db.update_records_in_mongodb([video_rec])

            updated_video_rec = self.process(video_rec)
            updated_video_rec['updatedAt'] = Utils.get_current_epoch()

            self.db.update_records_in_mongodb([updated_video_rec])
        else:
            print(f"Video {video_id} is already in {t_processing_status} status. Skipping.")


def main(req):
    message = []
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    try:
        request_json = req.get_json()
        message = request_json['message']
        print(f"type(message): {type(message)}")
        print(f"message: {message}")
    except Exception as e:
        print(f"Exception caught while fetching req data: {e}")
    exe = Execute()
    exe.run(message)
    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}
