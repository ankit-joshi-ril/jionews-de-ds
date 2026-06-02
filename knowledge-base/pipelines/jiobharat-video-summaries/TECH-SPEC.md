# JioBharat Video Summaries - Technical Specification

## Runtime Environment

| Attribute | Value |
|---|---|
| **Platform** | Google Cloud Functions (Gen1) + FastAPI microservice |
| **Runtime** | Python |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |

## Cloud Functions

### Function 1: JioBharat_AggregateSummariesPROD

| Attribute | Value |
|---|---|
| **Trigger Type** | HTTP |
| **Invocation** | Cloud Scheduler or manual HTTP request |
| **PROD MongoDB** | Base64-encoded hardcoded URI in source code |
| **DE MongoDB** | `mongosh_de_uri` from Secret Manager |
| **Output** | Pub/Sub `JioBharat_AggregateSummariesProd` |

### Function 2: jiobharat-pushtosftpprod

| Attribute | Value |
|---|---|
| **Trigger Type** | Pub/Sub (`JioBharat_AggregateSummariesProd`) |
| **Trigger** | Background function (Pub/Sub message) |
| **External APIs** | Image Attributor, GCS, SFTP |
| **Output** | SFTP files + DE MongoDB status record |

## FastAPI Microservice: Image Attributor

| Attribute | Value |
|---|---|
| **Framework** | FastAPI |
| **Route** | `POST /v1/image-attributor/generate-image` |
| **Host** | `service.jionews.com` |
| **Template Engine** | Jinja2 |
| **Browser Engine** | pyppeteer (headless Chromium) |
| **Viewport** | 1920x1080 |
| **Output Format** | JPEG screenshot |
| **Output Location** | GCS `img-cdn-bucket/jio_bharat/{summary_id}.jpeg` |

### Chromium Configuration

```python
browser = await launch({
    'args': ['--no-sandbox', '--disable-setuid-sandbox'],
    'headless': True
})
page = await browser.newPage()
await page.setViewport({'width': 1920, 'height': 1080})
```

| Argument | Purpose |
|---|---|
| `--no-sandbox` | Required for running in containerized environments without a sandboxing setup |
| `--disable-setuid-sandbox` | Disables setuid sandbox for container compatibility |

## Implementation Details

### Stage 1: JioBharat_AggregateSummariesPROD

#### PROD MongoDB Connection

```python
import base64

# Base64-encoded URI is hardcoded in the source
prod_uri = base64.b64decode(HARDCODED_BASE64_URI).decode('utf-8')
prod_client = MongoClient(prod_uri)
prod_db = prod_client['pie-production']
summaries_collection = prod_db['summaries']
```

This is a known deviation from the standard practice of using GCP Secret Manager for credentials.

#### Aggregation Pipeline Construction

```python
from datetime import datetime, timedelta, timezone

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))

# Today's IST day boundaries
today_start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)

pipeline = [
    {
        "$match": {
            "createdAt": {"$gte": today_start, "$lt": today_end},
            "language.code": {"$in": ["HIN", "TAM", "TEL", "KAN", "MAR", "BAN", "MAL", "GUJ"]},
            "isAudioSummaryGenerated": True,
            "isBreaking": False
        }
    },
    {"$sort": {"createdAt": -1}},
    {
        "$group": {
            "_id": "$language.code",
            "docs": {"$push": "$$ROOT"}
        }
    },
    {
        "$project": {
            "docs": {"$slice": ["$docs", 50]}
        }
    },
    {"$unwind": "$docs"},
    {"$replaceRoot": {"newRoot": "$docs"}}
]

results = list(summaries_collection.aggregate(pipeline))
```

#### Deduplication Against DE MongoDB

```python
de_client = MongoClient(de_mongo_uri)  # From Secret Manager
de_db = de_client['ingestion-data']
status_collection = de_db['jio_bharat_summaries']

# Get all successfully processed summary IDs
processed = status_collection.find(
    {"isSuccess": True},
    {"summary_id": 1}
)
processed_ids = {doc['summary_id'] for doc in processed}

# Filter to unprocessed summaries
unprocessed = [s for s in results if str(s['_id']) not in processed_ids]
```

#### Pub/Sub Publishing

```python
for summary in unprocessed:
    message = json.dumps({
        "summary_id": str(summary['_id']),
        "title": summary['title'],
        "language": summary['language']['code'],
        "publisher": summary.get('publisher', ''),
        "thumbnailUrl": summary.get('thumbnailUrl', ''),
        "createdAt": summary['createdAt'].timestamp()
    }).encode('utf-8')

    publisher.publish(topic_path, message)
```

### Stage 2: jiobharat-pushtosftpprod

#### Step 1: Image Generation

```python
import requests

response = requests.post(
    "https://service.jionews.com/v1/image-attributor/generate-image",
    json={
        "title": summary['title'],
        "publisher": summary['publisher'],
        "image_url": summary['thumbnailUrl'],
        "summary_id": summary['summary_id']
    }
)
```

The Image Attributor service processes this request by:
1. Rendering a Jinja2 HTML template with the title, publisher, and image.
2. Launching headless Chromium via pyppeteer.
3. Capturing a 1920x1080 JPEG screenshot.
4. Uploading the screenshot to `img-cdn-bucket/jio_bharat/{summary_id}.jpeg`.

#### Step 2: Audio Download

```python
from google.cloud import storage

storage_client = storage.Client()
audio_bucket = storage_client.bucket("audio-summaries-bucket")
audio_blob = audio_bucket.blob(f"prd/{summary_id}.mp3")
audio_data = audio_blob.download_as_bytes()
```

#### Step 3: Image Download

```python
image_bucket = storage_client.bucket("img-cdn-bucket")
image_blob = image_bucket.blob(f"jio_bharat/prod/{summary_id}.jpeg")
image_data = image_blob.download_as_bytes()
```

#### Step 4: SFTP Upload

```python
import paramiko

# Language folder mapping
LANGUAGE_FOLDERS = {
    "HIN": "taaza_kabrein_hin",
    "KAN": "pramukha_Suddi_kan",
    "TAM": "ungal_Seithigal_tam",
    "TEL": "itivali_varthalu_tel",
    "MAR": "taajya_baatmya_mar",
    "BAN": "tatka_sangbad_ban",
    "GUJ": "taaza_samachar_guj",
    "MAL": "puthiya_varthakal_mal"
}

lang_folder = LANGUAGE_FOLDERS[language_code]
date_str = datetime.now().strftime("%d_%m_%Y")
base_filename = f"{summary_id}_{language_code}_{date_str}"

# SFTP connection
transport = paramiko.Transport(("mediaftp1.ril.com", 33001))
transport.connect(username="FT_jionews_livenews", password=sftp_password)
sftp = paramiko.SFTPClient.from_transport(transport)

# Upload image
image_path = f"/media/prod/{lang_folder}/{base_filename}.jpeg"
sftp.putfo(BytesIO(image_data), image_path)

# Upload audio
audio_path = f"/media/prod/{lang_folder}/{base_filename}.mp3"
sftp.putfo(BytesIO(audio_data), audio_path)

sftp.close()
transport.close()
```

#### Step 5: Status Recording

```python
status_record = {
    "summary_id": summary_id,
    "title": title,
    "language": language_code,
    "thumbnailUrl": thumbnail_url,
    "publisher": publisher,
    "createdAt": epoch_timestamp,
    "isSuccess": True,
    "errorMessage": "",
    "uploadedPaths": [[image_path, audio_path]],
    "env": "prod"
}

status_collection.insert_one(status_record)
```

On failure at any step, the status record is inserted with `isSuccess=False` and the error message populated.

### Image Attributor Service

#### FastAPI Route

```python
from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader

app = FastAPI()
jinja_env = Environment(loader=FileSystemLoader("templates"))

@app.post("/v1/image-attributor/generate-image")
async def generate_image(request: ImageRequest):
    template = jinja_env.get_template("branded_image.html")
    html_content = template.render(
        title=request.title,
        publisher=request.publisher,
        image_url=request.image_url
    )

    browser = await launch({
        'args': ['--no-sandbox', '--disable-setuid-sandbox'],
        'headless': True
    })
    page = await browser.newPage()
    await page.setViewport({'width': 1920, 'height': 1080})
    await page.setContent(html_content)
    screenshot = await page.screenshot({'type': 'jpeg'})
    await browser.close()

    # Upload to GCS
    bucket = storage_client.bucket("img-cdn-bucket")
    blob = bucket.blob(f"jio_bharat/{request.summary_id}.jpeg")
    blob.upload_from_string(screenshot, content_type="image/jpeg")

    return {"path": f"jio_bharat/{request.summary_id}.jpeg"}
```

## Secrets and Configuration

### GCP Secret Manager

| Secret Name | Purpose | Used By |
|---|---|---|
| `mongosh_de_uri` | DE MongoDB connection URI | Both Cloud Functions |

### Hardcoded Configuration

| Configuration | Value | Location |
|---|---|---|
| PROD MongoDB URI | Base64-encoded in source | JioBharat_AggregateSummariesPROD |
| SFTP host | `mediaftp1.ril.com` | jiobharat-pushtosftpprod |
| SFTP port | `33001` | jiobharat-pushtosftpprod |
| SFTP user | `FT_jionews_livenews` | jiobharat-pushtosftpprod |
| Image Attributor URL | `https://service.jionews.com/v1/image-attributor/generate-image` | jiobharat-pushtosftpprod |
| Chromium viewport | 1920x1080 | Image Attributor |
| Languages | HIN, TAM, TEL, KAN, MAR, BAN, MAL, GUJ | JioBharat_AggregateSummariesPROD |
| Per-language limit | 50 | JioBharat_AggregateSummariesPROD |

## Pub/Sub Topics

| Topic | Publisher | Subscriber | Message Content |
|---|---|---|---|
| `JioBharat_AggregateSummariesProd` | JioBharat_AggregateSummariesPROD | jiobharat-pushtosftpprod | Individual summary record |

## GCS Buckets

| Bucket | Path | Access | Content |
|---|---|---|---|
| `audio-summaries-bucket` | `prd/{summary_id}.mp3` | Read | Source audio files |
| `img-cdn-bucket` | `jio_bharat/{summary_id}.jpeg` | Write (Image Attributor) | Generated branded images |
| `img-cdn-bucket` | `jio_bharat/prod/{summary_id}.jpeg` | Read (Stage 2) | Production images for SFTP |

## Dependencies

### Python Libraries

| Library | Purpose | Used In |
|---|---|---|
| `pymongo` | MongoDB driver | Both Cloud Functions |
| `google-cloud-pubsub` | Pub/Sub client | JioBharat_AggregateSummariesPROD |
| `google-cloud-storage` | GCS client | jiobharat-pushtosftpprod, Image Attributor |
| `google-cloud-secret-manager` | Secret Manager access | Both Cloud Functions |
| `paramiko` | SFTP client | jiobharat-pushtosftpprod |
| `requests` | HTTP client | jiobharat-pushtosftpprod |
| `fastapi` | Web framework | Image Attributor |
| `jinja2` | HTML template engine | Image Attributor |
| `pyppeteer` | Headless Chromium automation | Image Attributor |

## SFTP File Naming Convention

```
/media/prod/{language_folder}/{summary_id}_{language_code}_{dd_mm_yyyy}.{extension}
```

| Component | Description | Example |
|---|---|---|
| `language_folder` | Language-specific folder from mapping | `taaza_kabrein_hin` |
| `summary_id` | PROD MongoDB ObjectId as string | `65a1b2c3d4e5f6a7b8c9d0e1` |
| `language_code` | 3-letter language code | `HIN` |
| `dd_mm_yyyy` | Upload date (day_month_year) | `15_01_2025` |
| `extension` | File type | `mp3` or `jpeg` |

## Error Handling Summary

| Component | Error Type | Handling |
|---|---|---|
| PROD MongoDB connection | Connection failure | Function crashes (hardcoded URI) |
| PROD aggregation | No results | Function exits cleanly, no Pub/Sub messages |
| DE MongoDB connection | Connection failure | Function crashes |
| DE dedup query | Query failure | Function crashes |
| Pub/Sub publish | Publish failure | Summary not processed; no retry |
| Image Attributor API | HTTP error / timeout | Status: `isSuccess=false`, `errorMessage` populated |
| Chromium launch | Browser failure | Image Attributor returns error to caller |
| GCS audio download | Blob not found | Status: `isSuccess=false`, `errorMessage` populated |
| GCS image download | Blob not found | Status: `isSuccess=false`, `errorMessage` populated |
| SFTP connection | Connection timeout | Status: `isSuccess=false`, `errorMessage` populated |
| SFTP upload | Transfer failure | Status: `isSuccess=false`, `errorMessage` populated |
| MongoDB status insert | Insert failure | Status not recorded; may cause reprocessing |

## Monitoring and Observability

| Aspect | Mechanism |
|---|---|
| Function execution | Cloud Functions logs (Cloud Logging) |
| Aggregation results | Log count of summaries per language |
| Image generation | Image Attributor service logs |
| SFTP delivery | Status records in `jio_bharat_summaries` (`isSuccess` field) |
| Failed deliveries | Query `jio_bharat_summaries` where `isSuccess=false` |
| Daily throughput | Count status records per day |
