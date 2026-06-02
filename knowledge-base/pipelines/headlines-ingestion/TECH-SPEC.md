# Headlines Ingestion - Technical Specification

## Overview

This document provides implementation-level technical details for the Headlines Ingestion pipeline, including function signatures, library usage, concurrency patterns, error handling, and configuration specifics.

## Runtime Environment

| Attribute        | Value                          |
|------------------|--------------------------------|
| Runtime          | Python 3.x                     |
| GCP Project      | `jiox-328108` (266686822828)   |
| Region           | `asia-south1`                  |
| Generation       | Cloud Functions Gen 2          |

## Function Specifications

### 1. fetchfeedsdata

| Attribute          | Value                                    |
|--------------------|------------------------------------------|
| Trigger            | HTTP (Cloud Scheduler cron)              |
| Entry Point        | `main(req_ph1)`                          |
| Pub/Sub Output     | `NewRawHeadlinesIngestion_raw_feeds_data`|
| Concurrency Model  | `ThreadPoolExecutor(max_workers=100)`    |

#### Execution Flow

1. Read feed configuration CSV from `gs://de-raw-ingestion/headlines/headlines_publishers_feeds.csv`.
2. For each feed row, submit a fetch task to `ThreadPoolExecutor(100)`.
3. Each task:
   a. HTTP GET the feed URL.
   b. Detect feed type (RSS/XML vs JSON).
   c. For RSS/XML: Replace `<image>` tags with `<thumbimage>` tags, then parse with `feedparser`.
   d. For JSON: Parse with `json.loads()`, extract `items` array.
   e. Map fields based on publisher type (standard, Newspoint, ESPNcricinfo).
   f. Extract thumbnail using the 12-step priority chain.
4. Batch-publish raw records to Pub/Sub topic.

#### Feed Parsing Details

**XML Tag Replacement**:
```python
# Before feedparser parsing
xml_content = xml_content.replace("<image>", "<thumbimage>")
xml_content = xml_content.replace("</image>", "</thumbimage>")
```

This prevents feedparser from conflating article-level `<image>` tags with the RSS channel-level `<image>` element.

**JSON Feed Parsing**:
```python
data = json.loads(response_text)
items = data['items']  # Top-level 'items' key required
```

**Newspoint Field Mapping**:
```python
# Publishers: english-newspointapp, Indiatimes, Navbharat Times, Newspoint
record = {
    "title": item["hl"],        # Headline
    "url": item["mwu"],         # Mobile Web URL
    "date": item["dl"],         # Date Line
    "category": item["sec"]     # Section
}
```

**ESPNcricinfo Special Handling**:
```python
# URL extraction
url = record['href']  # NOT record['link']

# UTM parameter
url = url + ("&" if "?" in url else "?") + "ex_cid=jionews"
```

### 2. processheadlines

| Attribute          | Value                                          |
|--------------------|------------------------------------------------|
| Trigger            | HTTP (Pub/Sub push subscription)               |
| Entry Point        | `main(req)`                                    |
| Pub/Sub Input      | `NewRawHeadlinesIngestion_raw_feeds_data`      |
| Pub/Sub Output     | `NewRawHeadlinesIngestion_image_cdn`           |
| Concurrency Model  | `ThreadPoolExecutor(max_workers=50)`           |

#### Deduplication Implementation

```python
# Step 1: Link-based dedup
link_key = f"{article_url}_{category_id}_{language_id}"
if redis_cache.get("de_headlines_id_cache", link_key):
    return  # Silently drop

# Step 2: Title-based dedup
title_key = normalize(title)  # lowercase + strip
if redis_cache.get("de_headlines_title_cache", title_key):
    return  # Silently drop

# Step 3: Set both keys on double miss
redis_cache.set("de_headlines_id_cache", link_key, "1", ttl=172800)
redis_cache.set("de_headlines_title_cache", title_key, "1", ttl=172800)
```

#### UTM Parameter Appending

```python
# Standard publishers
utm = "utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews"
separator = "&" if "?" in url else "?"
url = f"{url}{separator}{utm}"

# ESPNcricinfo exception
url = f"{url}{separator}ex_cid=jionews"
```

#### Epoch Conversion and Correction

```python
import calendar
import time
from dateutil import parser as dateutil_parser

# Convert to epoch
if hasattr(entry, 'published_parsed') and entry.published_parsed:
    epoch = calendar.timegm(entry.published_parsed)
elif hasattr(entry, 'published'):
    dt = dateutil_parser.parse(entry.published)
    epoch = int(dt.timestamp())

# IST offset correction
current_epoch = int(time.time())
if epoch > current_epoch:
    epoch = epoch - 19800  # Subtract IST offset (5h 30m = 19800s)
```

#### Article Body Scraping

```python
# Primary scraper
response = requests.get(
    f"https://service.jionews.com/v1/scrape/scrape/?url={encoded_url}"
)

if response.status_code != 200 and language == "english":
    # Fallback scraper (English only)
    response = requests.post(
        "http://34.36.231.72/crawl",
        json={"url": article_url}
    )
```

#### Record Enrichment

```python
import bson

record["sourceId"] = str(bson.ObjectId())
record["createdAt"] = int(time.time())
# Language, category, publisher metadata copied from feed config
```

### 3. imagecdn

| Attribute          | Value                                          |
|--------------------|------------------------------------------------|
| Trigger            | HTTP (Pub/Sub push subscription)               |
| Entry Point        | `main(req)`                                    |
| Pub/Sub Input      | `NewRawHeadlinesIngestion_image_cdn`           |
| Pub/Sub Output (Success) | `NewRawHeadlinesIngestion_processed_data`|
| Pub/Sub Output (Failure) | `NewRawHeadlinesIngestion_rejected_data` |

#### Image Processing Pipeline

```python
from PIL import Image, ImageOps
import io

# 1. Download source image
response = requests.get(source_thumbnail_url)
img = Image.open(io.BytesIO(response.content))

# 2. EXIF orientation transpose
img = ImageOps.exif_transpose(img)

# 3. Generate renditions
renditions = {
    "original": img,  # No resize
    "fhd": img.resize((1920, 1080)),
    "hd": img.resize((1280, 720)),
    "sd": img.resize((720, 480)),
    "low": img.resize((480, 320)),
}

# 4. Encode and upload each rendition
for rendition_name, rendition_img in renditions.items():
    buffer = io.BytesIO()
    rendition_img.save(buffer, format="JPEG", quality=90)
    buffer.seek(0)

    blob_path = f"{rendition_name}/{source_id}.jpeg"
    bucket.blob(blob_path).upload_from_file(buffer, content_type="image/jpeg")
```

**Note**: Dimension validation code exists but is currently **commented out**. All images pass regardless of source dimensions.

#### CDN URL Construction

```python
cdn_base = "https://icdn.jionews.com"
thumbnail_urls = {
    "original": f"{cdn_base}/original/{source_id}.jpeg",
    "fhd": f"{cdn_base}/fhd/{source_id}.jpeg",
    "hd": f"{cdn_base}/hd/{source_id}.jpeg",
    "sd": f"{cdn_base}/sd/{source_id}.jpeg",
    "low": f"{cdn_base}/low/{source_id}.jpeg",
}
```

#### Routing Logic

```python
if source_thumbnail_url:
    # Process image and publish to success topic
    publish_to("NewRawHeadlinesIngestion_processed_data", record)
else:
    record["rejectionReason"] = "No thumbnail image url found"
    publish_to("NewRawHeadlinesIngestion_rejected_data", record)
```

#### Default Image Handling

When a record has no thumbnail, before rejection a default image may be assigned:

| Category       | Pool Size | Selection   |
|----------------|-----------|-------------|
| `latest_news`  | 22        | Random pick |
| All others     | 10        | Random pick |

### 4. PushToMongoDB

| Attribute          | Value                                          |
|--------------------|------------------------------------------------|
| Trigger            | CloudEvent (Pub/Sub)                           |
| Entry Point        | `write_to_mongodb(cloud_event)`                |
| Pub/Sub Input      | `NewRawHeadlinesIngestion_processed_data`      |
| MongoDB Collection | `ingestion-data.raw_headlines_ingestion_data`  |

#### Write Operation

```python
from pymongo import MongoClient

client = MongoClient(secret("mongosh_de_uri"))
db = client["ingestion-data"]
collection = db["raw_headlines_ingestion_data"]

# Simple insert
collection.insert_one(record)
```

### 5. rejected-pushtomongo

| Attribute          | Value                                          |
|--------------------|------------------------------------------------|
| Trigger            | CloudEvent (Pub/Sub)                           |
| Entry Point        | `write_to_mongodb(cloud_event)`                |
| Pub/Sub Input      | `NewRawHeadlinesIngestion_rejected_data`       |
| MongoDB Collection | `ingestion-data.headlines_hygiene_failures`    |

#### Write Operation

```python
collection = db["headlines_hygiene_failures"]
collection.insert_one(record)
# record includes rejectionReason and rejectedAt fields
```

## Key Libraries

| Library        | Version | Purpose                                       |
|----------------|---------|-----------------------------------------------|
| `feedparser`   | Latest  | RSS/XML feed parsing                          |
| `Pillow`       | Latest  | Image processing (resize, EXIF, JPEG encode)  |
| `bson`         | Latest  | ObjectId generation for sourceId              |
| `pymongo`      | Latest  | MongoDB client                                |
| `redis`        | Latest  | Redis client for deduplication caching        |
| `google-cloud-pubsub` | Latest | Pub/Sub publish                        |
| `google-cloud-storage` | Latest | GCS read (config) and write (images)  |
| `requests`     | Latest  | HTTP client for feeds and scrapers            |
| `python-dateutil` | Latest | Date string parsing                        |

## Error Handling

| Stage            | Error Type                | Handling                                   |
|------------------|---------------------------|--------------------------------------------|
| Feed Fetch       | HTTP error / timeout      | Log warning, skip feed, continue others    |
| Feed Parse       | Malformed XML/JSON        | Log error, skip feed                       |
| Redis            | Connection error          | Log error, allow record to pass (fail-open)|
| Article Scrape   | Primary failure           | Try fallback (English only) or continue    |
| Image Download   | HTTP error                | Route to rejection topic                   |
| Image Process    | PIL error                 | Route to rejection topic                   |
| GCS Upload       | Upload failure            | Retry or route to rejection                |
| MongoDB Write    | Write error               | Log error, message remains in Pub/Sub      |

## Secrets Management

| Secret Name      | Storage                   | Accessed By                                |
|------------------|---------------------------|--------------------------------------------|
| `mongosh_de_uri` | GCP Secret Manager        | `PushToMongoDB`, `rejected-pushtomongo`    |

## Configuration Constants

| Constant                    | Value          | Location    |
|-----------------------------|----------------|-------------|
| Fetch thread pool size      | 100            | fetchfeedsdata |
| Process thread pool size    | 50             | processheadlines |
| Redis link cache TTL        | 172800s (48h)  | processheadlines |
| Redis title cache TTL       | 172800s (48h)  | processheadlines |
| JPEG quality                | 90             | imagecdn    |
| IST epoch offset            | 19800s         | processheadlines |
| FHD dimensions              | 1920x1080      | imagecdn    |
| HD dimensions               | 1280x720       | imagecdn    |
| SD dimensions               | 720x480        | imagecdn    |
| Low dimensions              | 480x320        | imagecdn    |
| Default images (latest_news)| 22             | imagecdn    |
| Default images (other)      | 10             | imagecdn    |
