import csv
import json
import os
import warnings

import paramiko
from google.cloud import secretmanager, storage

warnings.filterwarnings("ignore")

# Sample record to test
SAMPLE_RECORD = {
    "sourceVideoId": "6a013c6216d4ff96d751c649",
    "sourceLanguageName": "English"
}

SFTP_REMOTE_DIR = "/media/newcpp/jionews2jiohotstar_ver/watch"
GCS_BUCKET = "hls_video_transcoder_storage_output_files"
GCS_BLOB_PREFIX = "raw_videos"
TMP_DIR = "tmp"


def get_secret(secret_name):
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("UTF-8")


def download_from_gcs(video_id: str, local_path: str) -> bool:
    print(f"Downloading gs://{GCS_BUCKET}/{GCS_BLOB_PREFIX}/{video_id}.mp4 ...")
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"{GCS_BLOB_PREFIX}/{video_id}.mp4")
        blob.download_to_filename(local_path)
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        print(f"Downloaded {size_mb:.2f} MB to {local_path}")
        return True
    except Exception as e:
        print(f"GCS download failed: {e}")
        return False


def generate_csv(video_id: str, language: str, output_path: str):
    headers = [
        "FileName", "ContentType", "Title", "Synopsis", "ReleaseDate", "RightsOwner",
        "RightsStartDate", "RightsEndDate", "ReleaseTime", "Genre", "SubGenre", "Language",
        "Starcast", "Director", "MusicDirector", "CensorCertification", "Keywords",
        "MaturityRating", "MaturityDescriptor", "Download", "GeoBlock", "Subscription",
        "AdCueTime1 ", "AdCueTime2", "AdCueTime3", "AdCueTime4", "AdCueTime5", "AdCueTime6",
        "AdCueTime7", "AdCueTime8", "IntroCreditsStart Time", "IntroCreditsEndTime",
        "EndCreditsStartTime", "EndCreditsEndTime", "Producer", "Writer", "IMDBRating",
        "ContentShortName", "Characters", "SeriesSeasonNumber", "EpisodeName", "EpisodeSynopsis",
        "EpisodeNumber", "Precap Credits: Start Time (00:00:00)", "Precap Credits: End Time (00:00:00)",
        "Recap Credits: Start Time (00:00:00)", "Recap Credits: End Time (00:00:00)",
        "Singer", "Lyricyst", "Label", "ShowID", "AlbumName", "LoopPlay", "ChannelID"
    ]

    if language == "Bangla":
        language = "Bengali"

    values = []
    for header in headers:
        if header == "FileName":
            values.append(video_id)
        elif header == "ContentType":
            values.append("Video")
        elif header == "Language":
            values.append(language)
        else:
            values.append("")

    with open(output_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(values)
    print(f"CSV generated at {output_path}")


def get_sftp_client():
    secret_name = "projects/266686822828/secrets/de_trascoder_sftp/versions/latest"
    sftp_creds = json.loads(get_secret(secret_name))
    transport = paramiko.Transport((sftp_creds['hostname'], sftp_creds['port']))
    transport.connect(username=sftp_creds['username'], password=sftp_creds['password'])
    return paramiko.SFTPClient.from_transport(transport)


def upload_to_sftp(sftp, local_path: str, remote_path: str) -> bool:
    remote_dir = os.path.dirname(remote_path)
    try:
        sftp.stat(remote_dir)
    except Exception as e:
        print(f"Remote directory check failed for {remote_dir}: {e}")
        return False
    try:
        sftp.put(local_path, remote_path)
        print(f"Uploaded {local_path} -> {remote_path}")
        return True
    except Exception as e:
        print(f"SFTP upload failed: {e}")
        return False


def run():
    video_id = SAMPLE_RECORD["sourceVideoId"]
    language = SAMPLE_RECORD["sourceLanguageName"]

    os.makedirs(TMP_DIR, exist_ok=True)
    local_video = f"{TMP_DIR}/{video_id}.mp4"
    local_csv = f"{TMP_DIR}/{video_id}.csv"

    print(f"\n{'=' * 60}")
    print(f"SHORTS SFTP SMOKE TEST")
    print(f"Video ID : {video_id}")
    print(f"Language : {language}")
    print(f"SFTP dir : {SFTP_REMOTE_DIR}")
    print(f"{'=' * 60}\n")

    # Step 1: GCS download
    if not download_from_gcs(video_id, local_video):
        print("FAILED: GCS download. Aborting.")
        return

    # Step 2: Generate CSV
    generate_csv(video_id, language, local_csv)

    # Step 3: SFTP upload
    print("Connecting to SFTP...")
    sftp = get_sftp_client()
    print("SFTP connection established.")

    video_remote = f"{SFTP_REMOTE_DIR}/{video_id}.mp4"
    csv_remote = f"{SFTP_REMOTE_DIR}/{video_id}.csv"

    video_ok = upload_to_sftp(sftp, local_video, video_remote)
    csv_ok = upload_to_sftp(sftp, local_csv, csv_remote)
    sftp.close()

    # Step 4: Cleanup
    for f in [local_video, local_csv]:
        if os.path.exists(f):
            os.remove(f)
    print("Local temp files cleaned up.")

    print(f"\n{'=' * 60}")
    print(f"RESULT: video={'OK' if video_ok else 'FAILED'}  csv={'OK' if csv_ok else 'FAILED'}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    run()
