import json
import logging
import os
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from google.cloud import pubsub_v1
from google.cloud import storage
from werkzeug.utils import secure_filename

# Set up basic configuration for logging
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG if you need detailed tracing
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # This handler will write to stdout
    ]
)

BASE_PATH = "/v1/de-native-video"

app = Flask(__name__)

# Load environment variables
load_dotenv()

# Configure MongoDB
# client = MongoClient(os.getenv('MONGO_URI'))
# db = client.get_database(os.getenv('MONGO_DB_NAME'))
# metadata_collection = db.get_collection(os.getenv('MONGO_COLLECTION_NAME'))

# Configure Google Cloud Storage
# gcs = storage.Client.from_service_account_json(os.getenv('SERVICE_ACCOUNT'))
# gcs = storage.Client()

# Retrieve the JSON string from the environment variable
service_account_json_str = os.getenv('SERVICE_ACCOUNT')
service_account_pubsub_json_str = os.getenv('SERVICE_ACCOUNT_PUBSUB')

# Convert the JSON string to a dictionary
service_account_info = json.loads(service_account_json_str)
service_account_pubsub_info = json.loads(service_account_pubsub_json_str)

# Create a Google Cloud Storage client using the service account info
gcs = storage.Client.from_service_account_info(service_account_info)

# video_bucket = gcs.bucket(os.getenv('GCS_BUCKET_NAME'))
# img_bucket = gcs.bucket(os.getenv('GCS_BUCKET_NAME'))

video_bucket = gcs.bucket("hls_video_transcoder_storage_output_files")
img_bucket = gcs.bucket("img-cdn-bucket")


# PubSub Client
def publish_message_to_topic(topic_name, data):
    project_id = "jiox-328108"
    # pubsub = pubsub_v1.PublisherClient()
    pubsub = pubsub_v1.PublisherClient.from_service_account_info(service_account_pubsub_info)
    topic_path = pubsub.topic_path(project_id, topic_name)

    json_string = json.dumps(data)
    print(f"Final JSON String: {json_string}")
    logging.info(f"Final JSON String: {json_string}")
    message_bytes = json_string.encode("utf-8")
    try:
        future = pubsub.publish(topic_path, data=message_bytes)
        print(f"Message published successfully!")
        logging.info(f"Message published successfully!")
        future.result()
    except Exception as err:
        print(f"Message Publishing Error: {err}")
        logging.info(f"Message Publishing Error: {err}")


def get_resource(name):
    with open(f"src/resources/{name}", 'r', encoding='utf-8') as data:
        file_str = data.read()
        data_recs = json.loads(file_str)

    return data_recs


# Basic Authentication
def check_auth(username, password):
    return username == os.getenv('BASIC_AUTH_USER') and password == os.getenv('BASIC_AUTH_PASS')


def authenticate():
    return jsonify({"message": "Authentication Required"}), 401


def generate_object_id():
    return str(ObjectId())


# def get_current_epoch_ist():
#     ist = pytz.timezone('Asia/Kolkata')
#     current_time = datetime.now(ist)
#     epoch_time = int(time.mktime(current_time.timetuple()))
#     return epoch_time

def get_current_epoch_ist():
    zone = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz=zone)
    return int(now.timestamp())


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


@app.route('/', methods=['GET'])
def healthcheck():
    return jsonify({"message": "Service is up and running"}), 200


@app.route(f'{BASE_PATH}/upload/', methods=['POST'])
@requires_auth
def upload_file():
    # Check for missing files
    if 'video' not in request.files:
        return jsonify({"message": "Missing video file"}), 400
    if 'thumbnail' not in request.files:
        return jsonify({"message": "Missing thumbnail image"}), 400
    if 'metadata' not in request.form:
        return jsonify({"message": "Missing metadata"}), 400

    # Retrieve files and metadata
    video = request.files['video']
    thumbnail = request.files['thumbnail']
    metadata = request.form['metadata']

    logging.info(f"metadata: {metadata}")

    # Load categories and languages
    # categories = get_resource("categories.json")
    # languages = get_resource("languages.json")

    categories = {
        "3": "entertainment",
        "5": "fashion",
        "8": "health",
        "9": "food",
        "10": "automotive",
        "11": "travel",
        "12": "sports",
        "13": "news",
        "14": "technology",
        "17": "business",
        "18": "cricket",
        "20": "spiritual",
        "22": "astrology",
        "26": "Career"
    }

    languages = {
        "1": "English",
        "2": "Hindi",
        "3": "Marathi",
        "4": "Gujarati",
        "6": "Malayalam",
        "7": "Tamil",
        "8": "Urdu",
        "9": "Kannada",
        "10": "Punjabi",
        "11": "Telugu",
        "13": "Bangla",
        "18": "Odia",
        "19": "Assamese"
    }

    # Validate file names
    if not video.filename:
        return jsonify({"message": "Video file is missing"}), 400
    if not thumbnail.filename:
        return jsonify({"message": "Thumbnail file is missing"}), 400

    # Validate video file type and size
    if not video.filename.lower().endswith(('.mp4', '.mov', '.avi')):
        return jsonify({"message": "Invalid video file type. Only MP4, MOV, AVI allowed."}), 400
    # if video.content_length > 500 * 1024 * 1024:  # 500 MB limit
    #     return jsonify({"message": "Video file is too large. Maximum allowed size is 500MB."}), 400
    #
    # # Validate thumbnail file type and size
    if not thumbnail.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
        return jsonify({"message": "Invalid thumbnail image type. Only JPG, JPEG, PNG, webp allowed."}), 400
    # if thumbnail.content_length > 5 * 1024 * 1024:  # 5 MB limit
    #     return jsonify({"message": "Thumbnail image is too large. Maximum allowed size is 5MB."}), 400

    # Validate metadata JSON format
    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError:
        return jsonify({"message": "Invalid metadata format"}), 400

    # Check for missing metadata fields
    required_metadata_fields = ['title', 'categoryId', 'languageId']
    missing_fields = [field for field in required_metadata_fields if not metadata_dict.get(field)]
    if missing_fields:
        return jsonify({"message": f"Missing metadata fields: {', '.join(missing_fields)}"}), 400

    # Validate category and language IDs
    category_id = str(metadata_dict['categoryId'])
    language_id = str(metadata_dict['languageId'])

    if category_id not in categories:
        return jsonify({"message": f"Invalid category ID: {category_id}"}), 400
    if language_id not in languages:
        return jsonify({"message": f"Invalid language ID: {language_id}"}), 400

    category_name = ""
    language_name = ""
    source_id = generate_object_id()

    try:
        category_name = categories[category_id]
        language_name = languages[language_id]
    except:
        return jsonify({"message": f"Invalid language/category ID: {language_id}"}), 400

    print(f"Debug:: Uploading files to gcs..")
    logging.info(f"Debug:: Uploading files to gcs..")
    # Save video and thumbnail to GCS
    video_filename = f"{source_id}.mp4"
    thumbnail_filename = f"{source_id}_{secure_filename(thumbnail.filename)}"

    video_blob = video_bucket.blob(f"raw_videos/{video_filename}")
    thumbnail_blob = img_bucket.blob(f"original/{thumbnail_filename}")

    video_blob.upload_from_file(video, content_type='video/mp4')
    thumbnail_blob.upload_from_file(thumbnail, content_type='image/jpeg')
    print(f"Debug:: Files uploaded to gcs!")
    logging.info(f"Debug:: Files uploaded to gcs!")

    zone = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz=zone)

    source_thumbnail_url = f"https://icdn.jionews.com/original/{thumbnail_filename}"
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

    # Prepare MongoDB record
    mongo_rec = {
        "sourceVideoId": source_id,
        "title": metadata_dict['title'],
        "sourceCategoryId": category_id,
        "sourceLanguageId": language_id,
        "sourceCategoryName": category_name,
        "sourceLanguageName": language_name,
        "sourceThumbnailURL": source_thumbnail_url,
        "sourceDate": now.isoformat() + "Z",
        "sourceEpoch": get_current_epoch_ist(),
        "sourcePublisherId": "5001",
        "sourcePublisherName": "ANI",
        "src": "api",
        "createdAt": get_current_epoch_ist(),
        "updatedAt": get_current_epoch_ist(),
        "thumbnailUrls": thumbnail_urls,
        "sourceVideoWidth": 0,
        "sourceVideoHeight": 0,
        "sourceVideoOrientation": "portrait",
        "contentType": "shorts",
        "processingStatus": "completed",
        "transcoderProcessingStatus": "initiated",
        "videoContentUrl": f"https://vcdn.jionews.com/raw_videos/{video_filename}"
    }

    # Insert into MongoDB and publish a message
    # metadata_collection.insert_one(mongo_rec)

    processed_record = {"filename": source_id, "url": source_thumbnail_url, "category": category_name,
                        "publisher": "ANI", "content_type": "shorts", "data": mongo_rec}

    print(f"Debug:: Publishing message to pubsub")
    logging.info(f"Debug:: Publishing message to pubsub")
    publish_message_to_topic("NewRawHeadlinesIngestion_image_cdn", [processed_record])
    print(f"Debug:: Message published to pubsub")
    logging.info(f"Debug:: Message published to pubsub")

    return jsonify({"message": f"File and metadata uploaded successfully, (ref:{source_id})"}), 200


# main block
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)