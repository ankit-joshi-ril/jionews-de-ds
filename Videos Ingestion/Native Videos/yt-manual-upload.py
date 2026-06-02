import csv
import json
import logging
import os
import time
from datetime import datetime

from flask import Flask, request, render_template, jsonify
from google.auth import default
from google.cloud import storage, secretmanager, pubsub_v1
from pymongo import MongoClient

# Flask app setup
app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manual-uploader")


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"
        self.publisher_client = self.get_pubsub_clients()

    def get_pubsub_clients(self):
        # Configure Pub/Sub Clients
        if service_account_info:
            # Use the service account credentials from the environment variable
            publisher_client = pubsub_v1.PublisherClient.from_service_account_info(service_account_info)
        else:
            # Use the default credentials for local development
            credentials, project = default()
            publisher_client = pubsub_v1.PublisherClient(credentials=credentials)

        return publisher_client

    def publish_message_to_topic(self, topic_name, data):
        pubsub = self.publisher_client
        topic_path = pubsub.topic_path(self.project_id, topic_name)

        json_string = json.dumps(data)
        logger.info(f"Final JSON String for pubsub: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            pubsub.publish(topic_path, data=message_bytes)
        except Exception as err:
            logger.info(f"Message Publishing Error: {err}")


def get_secret(secret_name):
    sm_client = secretmanager.SecretManagerServiceClient()
    response = sm_client.access_secret_version(request={"name": secret_name})
    payload = response.payload.data.decode("UTF-8")
    return payload


pk_secret_name = f"projects/266686822828/secrets/compute_engine_service_account_private_key/versions/latest"
uri_secret_name = f"projects/266686822828/secrets/mongosh_de_uri/versions/latest"
PRIVATE_KEY_JSON = get_secret(pk_secret_name)
service_account_info = json.loads(PRIVATE_KEY_JSON)
MONGO_URI = get_secret(uri_secret_name)

# GCS & Mongo Config
BUCKET_NAME = "hls_video_transcoder_storage_output_files"
BLOB_FOLDER = "raw_videos"
client = MongoClient(MONGO_URI)
db = client["ingestion-data"]
collection = db["raw_videos_rss"]
# collection = db["raw_videos_native"]
storage_client = storage.Client.from_service_account_info(service_account_info)
bucket = storage_client.bucket(BUCKET_NAME)
ps = PubSub()


# Load metadata from CSVs
def load_metadata():
    base_path = os.path.join(os.path.dirname(__file__), 'data')
    categories, languages, publishers = {}, {}, {}

    with open(os.path.join(base_path, 'categories.csv')) as f:
        for row in csv.DictReader(f):
            categories[row['categoryName'].strip()] = row['categoryId']

    with open(os.path.join(base_path, 'languages.csv')) as f:
        for row in csv.DictReader(f):
            languages[row['languageName'].strip()] = row['languageId']

    with open(os.path.join(base_path, 'publishers.csv')) as f:
        for row in csv.DictReader(f):
            name = row['publisher_name'].strip()
            if name not in publishers:
                publishers[name] = {
                    "publisher_id": row['publisher_id'],
                    "channel_id": row['channel_id']
                }

    return categories, languages, publishers


CATEGORY_MAP, LANGUAGE_MAP, PUBLISHER_MAP = load_metadata()


@app.after_request
def apply_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/metadata")
def metadata():
    return jsonify({
        "categories": [{"name": k, "id": v} for k, v in CATEGORY_MAP.items()],
        "languages": [{"name": k, "id": v} for k, v in LANGUAGE_MAP.items()],
        "publishers": [{"name": k, "id": v["publisher_id"]} for k, v in PUBLISHER_MAP.items()]
    })


@app.route("/get_upload_url", methods=["POST"])
def get_upload_url():
    try:
        data = request.get_json()
        video_id = data.get("videoId")
        if not video_id:
            return jsonify({"error": "Missing videoId"}), 400

        blob_path = f"{BLOB_FOLDER}/{video_id}.mp4"
        blob = bucket.blob(blob_path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=300,
            method="PUT",
            content_type="video/mp4"
        )
        logger.info(f"Generated signed URL for {video_id}")
        return jsonify({"signedUrl": url})
    except Exception as e:
        logger.exception("Error generating signed URL")
        return jsonify({"error": str(e)}), 500


@app.route("/check_cdn", methods=["POST"])
def check_cdn():
    video_id = request.form.get("videoId")
    if not video_id:
        return jsonify({"error": "Video ID required"}), 400

    cdn_url = f"https://vcdn.jionews.com/raw_videos/{video_id}.mp4"
    try:
        import requests
        response = requests.head(cdn_url, timeout=5)
        logger.info(f"CDN check for {video_id}: {response.status_code}")
        return jsonify({"exists": response.status_code == 200, "url": cdn_url})
    except Exception as e:
        logger.exception("Error checking CDN")
        return jsonify({"exists": False, "error": str(e)})


@app.route("/upload", methods=["POST"])
def upload():
    try:
        video_id = request.form.get("videoId")
        title = request.form.get("title")
        category = request.form.get("sourceCategoryName")
        language = request.form.get("sourceLanguageName")
        publisher = request.form.get("sourcePublisherName")
        content_type = request.form.get("contentType")

        print(
            f"Received upload request for video_id: {video_id}, title: {title}, category: {category}, language: {language}, publisher: {publisher}, content_type: {content_type}")

        if not all([video_id, title, category, language, publisher, content_type]):
            return "Missing required fields", 400

        category_id = CATEGORY_MAP.get(category, "0")
        language_id = LANGUAGE_MAP.get(language, "0")
        publisher_meta = PUBLISHER_MAP.get(publisher, {"publisher_id": "0", "channel_id": ""})

        now = datetime.utcnow()
        now_epoch = int(time.mktime(now.timetuple()))

        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg" if content_type == "videos" else f"https://i.ytimg.com/vi/{video_id}/oar2.jpg"
        print(f"content_type: {content_type}, thumbnail_url: {thumbnail_url}")

        metadata = {
            "sourceVideoId": video_id,
            "title": title,
            "sourceCategoryId": category_id,
            "sourceLanguageId": language_id,
            "sourceCategoryName": category,
            "sourceLanguageName": language,
            "sourceThumbnailURL": thumbnail_url,
            "sourceDate": now.isoformat() + "Z",
            "sourceEpoch": now_epoch,
            "sourceDescription": "",
            "sourcePublisherId": publisher_meta["publisher_id"],
            "sourcePublisherName": publisher,
            "src": "manual",
            "sourceExternalid": video_id,
            "createdAt": now_epoch,
            "thumbnailUrls": {
                "default": {"url": f"https://i.ytimg.com/vi/{video_id}/default.jpg", "width": 120, "height": 90},
                "medium": {"url": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg", "width": 320, "height": 180},
                "high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", "width": 480, "height": 360},
                "standard": {"url": f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg", "width": 640, "height": 480},
                "maxres": {"url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg", "width": 1280, "height": 720},
            },
            "sourceVideoDuration": 0,
            "sourceChannelID": publisher_meta["channel_id"],
            "sourceVideoWidth": 0,
            "sourceVideoHeight": 0,
            "sourceVideoOrientation": "",
            "contentType": content_type,
            "processingStatus": "completed",
            "isVideoMerged": True,
            "audioUrl": "",
            "videoUrl": "",
            "videoContentUrl": f"https://vcdn.jionews.com/raw_videos/{video_id}.mp4",
            "updatedAt": int(time.time()),
            "errorMessage": ""
        }

        if content_type == 'videos':
            metadata["transcoderProcessingStatus"] = "initiated"

        processed_record = {"filename": video_id, "url": thumbnail_url, "category": category,
                            "publisher": publisher, "content_type": "videos", "data": metadata}

        # publish to pubsub for image processing
        ps.publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", [processed_record])

        return "Upload successful!", 200

        # inserted = collection.insert_one(metadata)
        # logger.info(f"Metadata inserted for {video_id} with _id: {inserted.inserted_id}")
        # return "Upload successful!", 200

        # result = collection.update_one(
        #     {"sourceVideoId": metadata["sourceVideoId"], "contentType": metadata["contentType"]},
        #     {"$set": metadata},
        #     upsert=True
        # )
        #

        # if result.upserted_id:
        #     logger.info(f"Metadata inserted for {video_id} with _id: {result.upserted_id}")
        # else:
        #     logger.info(f"Metadata updated for {video_id}")
        #
        # return "Upload successful!", 200

    except Exception as e:
        logger.exception("Upload failed")
        return f"Upload failed: {str(e)}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)