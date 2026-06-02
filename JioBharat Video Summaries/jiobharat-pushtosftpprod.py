import base64
import json
import os
import time
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import paramiko
import pytz
import requests
from google.cloud import secretmanager
from google.cloud import storage
from pymongo import MongoClient, errors

# Ignore all warnings
warnings.filterwarnings("ignore")

_run_local = False
_zone = ZoneInfo("Asia/Kolkata")
path = os.path
root = path.dirname(path.abspath(__file__))


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


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

    def parse_message(self, message):
        data = base64.b64decode(message["data"])
        decoded_data = json.loads(data.decode('utf-8'))
        return decoded_data


class GCS:
    def __init__(self):
        self.audio_bucket_name = "audio-summaries-bucket"
        self.audio_blob = "prd"
        self.img_bucket_name = "img-cdn-bucket"
        self.img_blob = "jio_bharat/prod"

    def download_file_from_gcs(self, bucket_name: str, source_blob_name: str, destination_file_name: str):
        print(f"Downloading file from GCS: {source_blob_name}")
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        try:
            blob.download_to_filename(destination_file_name)
            print(f"Downloaded {source_blob_name} to {destination_file_name}")
            return True
        except Exception as e:
            print(f"Failed to download {source_blob_name}: {e}")
            return False


class MongoDB:
    def __init__(self):
        self.secret_name = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"
        connection_uri_de = self.get_secret()

        try:
            de_client = MongoClient(connection_uri_de)
            ingestion_db = de_client['ingestion-data']
            self.jio_bharat_summaries_collection = ingestion_db['jio_bharat_summaries']
            print("MongoDB connection established successfully.")
        except errors.ServerSelectionTimeoutError as err:
            print(f"Server selection timeout error: {err}")
        except errors.ConnectionFailure as err:
            print(f"Connection failure: {err}")
        except Exception as err:
            print(f"An error occurred: {err}")

    def get_secret(self):
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": self.secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload

    def push_records_to_collection(self, records):
        try:
            self.jio_bharat_summaries_collection.insert_many(records)
            print("Records inserted successfully")
        except Exception as e:
            print(f"Failed to insert records: {e}")


class SFTP:
    def __init__(self):
        self.sftp_details = {
            'hostname': 'mediaftp1.ril.com',
            'port': 33001,
            'username': 'FT_jionews_livenews',
            'password': 'Ji0nEw$!iXe@2o$5'
        }

    def connect(self):
        transport = paramiko.Transport((self.sftp_details['hostname'], self.sftp_details['port']))
        transport.connect(username=self.sftp_details['username'], password=self.sftp_details['password'])
        return paramiko.SFTPClient.from_transport(transport)

    def upload_to_sftp(self, local_file_path, remote_file_path):
        print(f"Uploading file to SFTP: {local_file_path} -> {remote_file_path}")
        sftp = self.connect()
        remote_dir = os.path.dirname(remote_file_path)
        try:
            sftp.stat(remote_dir)
        except IOError:
            print(f"Remote directory {remote_dir} does not exist. Creating it.")
            try:
                sftp.mkdir(remote_dir)
            except Exception as e:
                print(f"Failed to create directory {remote_dir}: {e}")
        try:
            sftp.put(local_file_path, remote_file_path)
            print(f"Uploaded {local_file_path} to {remote_file_path}")
        except Exception as e:
            print(f"Failed to upload {local_file_path}: {e}")
        finally:
            sftp.close()


class Processor:
    def __init__(self, sftp, gcs):
        self.sftp = sftp
        self.gcs = gcs
        if _run_local:
            self.tmp_dir = 'tmp'
        else:
            self.tmp_dir = '/tmp'

    def generate_image_from_service(self, title: str, publisher_name: str, image_url: str, summary_id: str):
        url = "https://service.jionews.com/v1/image-attributor/generate-image"
        payload = json.dumps({
            "title": title,
            "publisher": publisher_name,
            "image_url": image_url,
            "summary_id": summary_id
        })
        headers = {
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                print(f"Image generation service call successful for summary_id: {summary_id}")
                return True
            else:
                print(f"Image generation service call failed for summary_id: {summary_id}, Response: {response.text}")
                return False
        except Exception as e:
            print(f"Error calling image generation service: {e}")
            return False

    def process_summary(self, summary):
        remote_paths = []

        summary_id = summary['summary_id']
        title = summary['title']
        publisher = summary['publisher']
        thumbnailUrl = summary['thumbnailUrl']
        language = summary['language'].lower()

        # Map old folder names to new folder names
        folder_mappings = {
            'hin': 'taaza_kabrein_hin',
            'kan': 'pramukha_Suddi_kan',
            'tam': 'ungal_Seithigal_tam',
            'tel': 'itivali_varthalu_tel',
            'mar': 'taajya_baatmya_mar',
            'ban': 'tatka_sangbad_ban',
            'guj': 'taaza_samachar_guj',
            'mal': 'puthiya_varthakal_mal'
        }

        # Process image generation
        image_generate_status = self.generate_image_from_service(title, publisher, thumbnailUrl, summary_id)

        if image_generate_status:
            print(f"Processing summary: {summary_id}")

            audio_bucket_name = "audio-summaries-bucket"
            image_bucket_name = "img-cdn-bucket"
            audio_blob = f"prd/{summary_id}.mp3"
            image_blob = f"jio_bharat/prod/{summary_id}.jpeg"

            filename = f"{summary_id}_{language}_{datetime.now().strftime('%d_%m_%Y')}"
            audio_file_name = f"{filename}.mp3"
            image_file_name = f"{filename}.jpeg"
            local_audio_path = f"{self.tmp_dir}/{audio_file_name}"
            local_image_path = f"{self.tmp_dir}/{image_file_name}"

            audio_download_status = self.gcs.download_file_from_gcs(audio_bucket_name, audio_blob, local_audio_path)
            image_download_status = self.gcs.download_file_from_gcs(image_bucket_name, image_blob, local_image_path)

            # If both audio and image download is successful, upload to SFTP
            if audio_download_status and image_download_status:
                new_folder = folder_mappings.get(language, language)
                remote_audio_path = f"/media/prod/{new_folder}/{audio_file_name}"
                remote_image_path = f"/media/prod/{new_folder}/{image_file_name}"

                self.sftp.upload_to_sftp(local_audio_path, remote_audio_path)
                self.sftp.upload_to_sftp(local_image_path, remote_image_path)

                remote_paths.append((remote_image_path, remote_audio_path))

                os.remove(local_audio_path)
                os.remove(local_image_path)
            else:
                print("Error downloading asset from GCS")
        else:
            print(f"Image generation failed for summary_id: {summary_id}")

        return remote_paths


class Execute:
    def __init__(self):
        print("Execution started")
        self.pubsub = PubSub()
        self.gcs = GCS()
        self.db = MongoDB()
        self.sftp = SFTP()
        self.processor = Processor(self.sftp, self.gcs)

    def run(self, message):
        data = self.pubsub.parse_message(message)
        # data = message
        print(f"Total {len(data)} summary records received from PubSub::: {data}")

        for summary in data:
            is_success = True
            error_message = ""
            remote_paths = []
            try:
                remote_paths = self.processor.process_summary(summary)
            except Exception as e:
                is_success = False
                error_message = f"Error processing summary to SFTP:: {e} "
                print(error_message)
            finally:
                summary['createdAt'] = Utils.get_current_epoch()
                summary['isSuccess'] = is_success
                summary['errorMessage'] = error_message
                summary['uploadedPaths'] = remote_paths
                summary['env'] = "prod"

        self.db.push_records_to_collection(data)


def main(message, context):
    execution_start_time = time.time()
    print(f"Execution started at: {datetime.now(tz=_zone)}")

    exe = Execute()
    exe.run(message)

    execution_end_time = time.time()
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    print(f"Execution processing time: {execution_processing_time} minutes")
    print(f"Execution Ended at: {datetime.now(tz=_zone)}")

    return {'result': 'success'}