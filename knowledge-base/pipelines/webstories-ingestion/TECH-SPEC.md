# Webstories Ingestion - Technical Specification

## Overview

This document provides implementation-level technical details for the Webstories Ingestion pipeline, including the configurable field mapping system, source type processing, thumbnail validation, and URL transformation logic.

## Runtime Environment

| Attribute        | Value                          |
|------------------|--------------------------------|
| Runtime          | Python 3.x                     |
| GCP Project      | `jiox-328108` (266686822828)   |
| Region           | `asia-south1`                  |
| Generation       | Cloud Functions Gen 2          |

## Function Specifications

### 1. RawWebStoriesIngestion

| Attribute          | Value                              |
|--------------------|------------------------------------|
| Trigger            | HTTP (Cloud Scheduler cron)        |
| Entry Point        | `main(req)` (implied)              |
| Pub/Sub Output     | `RawWebStoriesIngestion`           |
| Config Source       | Local `publishers.csv`            |

#### CSV Configuration Loading

```python
import csv
import json

def load_publishers():
    """Load publisher config from local CSV bundled with function."""
    publishers = []
    with open("publishers.csv", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["mapping"] = json.loads(row["mapping"])  # Parse JSON string
            publishers.append(row)
    return publishers
```

#### Publisher Config Row Example

```python
{
    "sys_pub_name": "example_publisher",
    "endpoint": "https://api.example.com/stories",
    "data_list_path": "data.stories",
    "type": "api",
    "mapping": {
        "title": "headline",
        "url": "story_url",
        "thumbnail": "cover_image",
        "published_date": "created_at"
    },
    "category": "entertainment",
    "language": "english"
}
```

#### API Source Processing

```python
import requests
import json

def fetch_api_source(publisher):
    """Fetch and parse API-type publisher source."""
    response = requests.get(publisher["endpoint"])
    data = response.json()

    # Navigate data_list_path to find the stories array
    path_parts = publisher["data_list_path"].split(".")
    items = data
    for part in path_parts:
        items = items[part]

    records = []
    mapping = publisher["mapping"]
    for item in items:
        record = apply_mapping(item, mapping, publisher)
        records.append(record)
    return records
```

#### Feed Source Processing

```python
import feedparser

def fetch_feed_source(publisher):
    """Fetch and parse Feed-type publisher source."""
    feed = feedparser.parse(publisher["endpoint"])

    records = []
    mapping = publisher["mapping"]
    for entry in feed.entries:
        record = apply_mapping(entry, mapping, publisher)
        records.append(record)
    return records
```

#### Field Mapping Application

```python
def apply_mapping(item, mapping, publisher):
    """Apply per-publisher field mapping to extract standard fields."""
    record = {}

    # Map each standard field using the publisher-specific field name
    for standard_field, publisher_field in mapping.items():
        if isinstance(item, dict):
            record[standard_field] = item.get(publisher_field, "")
        else:
            record[standard_field] = getattr(item, publisher_field, "")

    # Add metadata from CSV config
    record["sourceCategoryName"] = publisher["category"]
    record["sourceLanguageName"] = publisher["language"]
    record["sourcePublisherName"] = publisher["sys_pub_name"]

    return record
```

#### HTTPS Enforcement

```python
def enforce_https(url):
    """Replace http:// with https:// in URLs."""
    if url and url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url
```

#### UTM Parameter Appending

```python
def append_utm(url):
    """Append JioNewsStories UTM parameters to URL."""
    utm = "utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories"
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{utm}"
```

Note: The campaign value is `JioNewsStories` (distinct from Headlines/Summaries which use `JioNews`).

#### Thumbnail URL Validation

```python
def validate_thumbnail(thumbnail_url):
    """Validate thumbnail URL via HTTP GET request."""
    if not thumbnail_url:
        return None

    thumbnail_url = enforce_https(thumbnail_url)

    try:
        response = requests.get(thumbnail_url, timeout=10)
        if response.status_code == 200:
            return thumbnail_url
        return None
    except requests.RequestException:
        return None
```

#### Full Record Assembly

```python
import time

def build_record(raw_record, publisher):
    """Assemble final record for Pub/Sub publishing."""
    url = enforce_https(raw_record.get("url", ""))
    url = append_utm(url)

    thumbnail = validate_thumbnail(raw_record.get("thumbnail"))

    return {
        "sourceId": raw_record.get("sourceId", ""),
        "title": raw_record.get("title", ""),
        "sourcePublishedDate": raw_record.get("published_date", ""),
        "sourceCategoryName": publisher["category"],
        "sourceLanguageName": publisher["language"],
        "sourcePublisherName": publisher["sys_pub_name"],
        "sourceURL": url,
        "sourceThumbnailUrl": thumbnail,
        "createdAt": int(time.time())
    }
```

#### Main Execution Flow

```python
def main(req):
    """HTTP entry point triggered by Cloud Scheduler."""
    publishers = load_publishers()

    all_records = []
    for publisher in publishers:
        try:
            if publisher["type"] == "api":
                records = fetch_api_source(publisher)
            elif publisher["type"] == "feed":
                records = fetch_feed_source(publisher)
            else:
                continue

            for raw_record in records:
                record = build_record(raw_record, publisher)
                all_records.append(record)
        except Exception as e:
            # Log error, continue to next publisher
            print(f"Error processing {publisher['sys_pub_name']}: {e}")
            continue

    # Publish all records to Pub/Sub
    publish_batch(all_records, topic="RawWebStoriesIngestion")

    return "OK", 200
```

### 2. PushToMongoDB

| Attribute          | Value                                          |
|--------------------|-------------------------------------------------|
| Trigger            | CloudEvent (Pub/Sub)                            |
| Entry Point        | `write_to_mongodb(cloud_event)` (implied)       |
| Pub/Sub Input      | `RawWebStoriesIngestion`                        |
| MongoDB Collection | `ingestion-data.raw_web_stories_ingestion_data` |

#### Write Operation

```python
from pymongo import MongoClient

def write_to_mongodb(cloud_event):
    """CloudEvent handler to persist web story to MongoDB."""
    record = parse_cloud_event(cloud_event)

    client = MongoClient(secret("mongosh_de_uri"))
    db = client["ingestion-data"]
    collection = db["raw_web_stories_ingestion_data"]

    collection.insert_one(record)
```

## Key Libraries

| Library                | Purpose                                       |
|------------------------|-----------------------------------------------|
| `feedparser`           | RSS/XML feed parsing for feed-type sources    |
| `pymongo`              | MongoDB client                                |
| `google-cloud-pubsub`  | Pub/Sub publish                               |
| `requests`             | HTTP client for APIs, feeds, thumbnail validation |

## Error Handling

| Stage                | Error Type              | Handling                                      |
|----------------------|-------------------------|-----------------------------------------------|
| CSV Load             | File not found          | Fatal error, function returns 500             |
| CSV Parse            | Malformed row           | Log error, skip row                           |
| Mapping JSON Parse   | Invalid JSON string     | Log error, skip publisher                     |
| API Fetch            | HTTP error / timeout    | Log error, skip publisher                     |
| Feed Fetch           | Parse error             | Log error, skip publisher                     |
| data_list_path       | KeyError on navigation  | Log error, skip publisher                     |
| Field Mapping        | Missing publisher field | Default to empty string                       |
| Thumbnail Validation | HTTP error / timeout    | Set to null, continue                         |
| Pub/Sub Publish      | Publish error           | Log error                                     |
| MongoDB Write        | Write error             | Log error, message stays in Pub/Sub           |

## Secrets Management

| Secret Name      | Storage                   | Accessed By      |
|------------------|---------------------------|------------------|
| `mongosh_de_uri` | GCP Secret Manager        | `PushToMongoDB`  |

## Configuration Constants

| Constant                     | Value                  | Location                  |
|------------------------------|------------------------|---------------------------|
| UTM source                   | `JioNews`              | RawWebStoriesIngestion    |
| UTM medium                   | `referral`             | RawWebStoriesIngestion    |
| UTM campaign                 | `JioNewsStories`       | RawWebStoriesIngestion    |
| Thumbnail validation timeout | 10s (estimated)        | RawWebStoriesIngestion    |
| Config file                  | `publishers.csv`       | RawWebStoriesIngestion    |

## Deployment Notes

Since the publisher CSV is local to the Cloud Function, any changes to publisher configuration require:

1. Update the `publishers.csv` file.
2. Redeploy the `RawWebStoriesIngestion` Cloud Function.
3. The new configuration takes effect on the next Cloud Scheduler invocation.

This differs from Headlines and Summaries pipelines where the feed config CSV is stored on GCS and can be updated without redeployment.
