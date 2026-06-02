# Native Shorts Ingestion - Technical Specification

## Runtime Environment

| Attribute | Value |
|---|---|
| **Platform** | Google Cloud Functions (Gen1) |
| **Runtime** | Python |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |

## Cloud Functions

### Shared Functions (Used by Both Shorts and Videos Pipelines)

#### JioNewsDENativeVideos

| Attribute | Value |
|---|---|
| **Trigger Type** | Pub/Sub |
| **Shared With** | Native Videos Ingestion pipeline |
| **Shorts Behavior** | Tags content with `contentType="shorts"` based on editorial metadata |
| **Orientation** | Sets `sourceVideoOrientation="portrait"` for shorts |

#### yt-manual-upload

| Attribute | Value |
|---|---|
| **Trigger Type** | Pub/Sub |
| **Shared With** | Native Videos Ingestion pipeline |
| **Shorts Behavior** | Sets `contentType="shorts"` for shorts content |
| **Thumbnail** | Uses `oar2.jpg` as thumbnail source |

### Dedicated MRSS Shorts Functions

#### mrssshorts-fetchfeedsdata

| Attribute | Value |
|---|---|
| **Trigger Type** | HTTP (Cloud Scheduler) |
| **Input** | GCS `de-raw-ingestion/shorts/mrss_shorts_feeds.csv` |
| **Output** | Pub/Sub `MRSSShortsIngestion_RawFeedsData` |
| **Concurrency** | `ThreadPoolExecutor(max_workers=100)` |

#### mrssshorts-processvideos

| Attribute | Value |
|---|---|
| **Trigger Type** | Pub/Sub (`MRSSShortsIngestion_RawFeedsData`) |
| **Dedup** | Redis `de_mrss_shorts_cache` (48h TTL) |
| **Output DB** | MongoDB `ingestion-data.raw_videos_rss` |
| **Output Pub/Sub** | `MRSSShortsIngestion_ProcessedData`, `NewRawHeadlinesIngestion_image_cdn` |

#### mrssshorts-downloadvideos

| Attribute | Value |
|---|---|
| **Trigger Type** | Pub/Sub (`MRSSShortsIngestion_ProcessedData`) |
| **Output GCS** | `hls_video_transcoder_storage_output_files/raw_videos/` |
| **Post-Processing** | None (no transcoding) |
| **Status Update** | MongoDB `processingStatus="completed"` |

## Implementation Details

### Stage 1: mrssshorts-fetchfeedsdata

#### Feed Configuration Loading

```
Bucket: de-raw-ingestion
Path: shorts/mrss_shorts_feeds.csv
```

The CSV contains feed URLs, feed IDs, and publisher metadata.

#### Concurrent Feed Fetching

```python
with ThreadPoolExecutor(max_workers=100) as executor:
    futures = {
        executor.submit(fetch_feed, feed_url): feed_config
        for feed_config in feed_configs
    }
    for future in as_completed(futures):
        result = future.result()
        # Process and publish records
```

Up to 100 concurrent threads fetch MRSS feeds simultaneously. Each thread handles one feed URL.

#### Feed Response Parsing

The response JSON key depends on the feed ID:

```python
if feed_id in [49, 50]:
    records = response_json['data']
else:
    records = response_json['items']
```

This is a hardcoded branching condition. Feed IDs 49 and 50 use the `'data'` key, while all other feeds use `'items'`.

### Stage 2: mrssshorts-processvideos

#### Redis Deduplication

```python
cache_key = f"{record['title']}_{record['link']}_{record['category']}_{record['language']}"

if redis_client.exists(cache_key):
    return  # Skip duplicate

redis_client.setex(cache_key, timedelta(hours=48), "1")
```

The composite key ensures that records with the same title, link, category, and language combination are not processed twice within a 48-hour window.

#### Publisher-Specific Processing

**Publishers 7777/7778 - Videotype Filter:**

```python
SHORTS_VIDEOTYPES = {"shorts", "short", "short video", "shortvideo"}

if publisher_id in [7777, 7778]:
    videotype = record.get('videotype', '').lower()
    if videotype not in SHORTS_VIDEOTYPES:
        return  # Exclude non-shorts content
```

These publishers include both video and shorts content in their feeds. The videotype filter ensures only shorts content is ingested by this pipeline.

**Publisher 7782 (IANS) - Non-Standard Video URL:**

```python
if publisher_id == 7782:
    video_url = record.get('video')
else:
    video_url = record.get('video_url')
```

IANS uses the field name `'video'` instead of the standard `'video_url'`.

#### Content Metadata Assignment

```python
record['contentType'] = "shorts"
record['sourceVideoOrientation'] = "portrait"
```

These values are hardcoded for all shorts records, regardless of source.

#### Default Image Selection

```python
import random

if not thumbnail_url:
    default_image_number = random.randint(1, 5)  # Range 1-5 for shorts (vs 1-10 for videos)
    thumbnail_url = get_default_image(default_image_number)
```

When a feed record lacks a thumbnail URL, a random default image is selected from a pool of 5 images (compared to 10 for the videos pipeline).

#### Image CDN Publishing

```python
pubsub_client.publish(
    "NewRawHeadlinesIngestion_image_cdn",
    json.dumps({"image_url": thumbnail_url, ...}).encode()
)
```

Thumbnail images are published to the image CDN pipeline for processing and distribution.

#### MongoDB Insert

```python
collection.insert_many(processed_records)
```

#### Per-Record Pub/Sub Publishing

```python
for record in processed_records:
    pubsub_client.publish(
        "MRSSShortsIngestion_ProcessedData",
        json.dumps(record).encode()
    )
```

Each processed record is published individually to trigger Stage 3.

### Stage 3: mrssshorts-downloadvideos

#### Video Download and GCS Upload

```python
# Download video from source
response = requests.get(source_video_url)
video_data = response.content

# Upload to GCS
bucket = storage_client.bucket("hls_video_transcoder_storage_output_files")
blob = bucket.blob(f"raw_videos/{video_id}.mp4")
blob.upload_from_string(video_data, content_type="video/mp4")
```

#### No Transcoding

Unlike the Native Videos pipeline, shorts skip transcoding entirely. The raw MP4 file is served directly via CDN.

```python
# Native Videos pipeline would submit to transcoder here
# Shorts pipeline: NO transcoder submission
```

#### MongoDB Status Update

```python
collection.update_one(
    {"_id": record_id},
    {"$set": {
        "processingStatus": "completed",
        "videoContentUrl": f"https://vcdn.jionews.com/raw_videos/{video_id}.mp4"
    }}
)
```

## Pub/Sub Topics

| Topic | Publisher | Subscriber | Message Content |
|---|---|---|---|
| `MRSSShortsIngestion_RawFeedsData` | mrssshorts-fetchfeedsdata | mrssshorts-processvideos | Raw feed records |
| `MRSSShortsIngestion_ProcessedData` | mrssshorts-processvideos | mrssshorts-downloadvideos | Processed video records |
| `NewRawHeadlinesIngestion_image_cdn` | mrssshorts-processvideos | Image CDN pipeline | Thumbnail image URLs |

## Secrets and Configuration

### GCP Secret Manager

| Secret Name | Purpose | Used By |
|---|---|---|
| `mongosh_de_uri` | MongoDB connection URI | All functions |

### GCS Configuration Files

| Path | Purpose |
|---|---|
| `gs://de-raw-ingestion/shorts/mrss_shorts_feeds.csv` | MRSS feed endpoint list |

### Redis Configuration

| Attribute | Value |
|---|---|
| **Cache Name** | `de_mrss_shorts_cache` |
| **TTL** | 48 hours |
| **Key Format** | `{title}_{link}_{category}_{language}` |

## Hardcoded Values Reference

| Value | Context | Rationale |
|---|---|---|
| `"shorts"` | `contentType` field | Distinguishes from `"videos"` in shared collection |
| `"portrait"` | `sourceVideoOrientation` | Shorts are vertical content |
| `100` | ThreadPoolExecutor workers | Maximum concurrent feed fetches |
| `48` hours | Redis TTL | Dedup window for feed records |
| `1-5` | Default image range | Smaller pool than videos (1-10) |
| `[49, 50]` | Feed IDs using `'data'` key | Publisher-specific JSON format |
| `[7777, 7778]` | Publishers with videotype filter | Mixed content publishers |
| `7782` | IANS publisher ID | Non-standard video URL field |
| `"shorts"`, `"short"`, `"short video"`, `"shortvideo"` | Accepted videotype values | Filter criteria for publishers 7777/7778 |

## Comparison with Native Videos Pipeline

| Aspect | Shorts | Videos |
|---|---|---|
| contentType | `"shorts"` | `"videos"` |
| Orientation | `"portrait"` | `"landscape"` |
| Redis cache | `de_mrss_shorts_cache` | `de_mrss_videos_cache` |
| Default image range | 1-5 | 1-10 |
| Pub/Sub prefix | `MRSSShortsIngestion_` | `MRSSVideosIngestion_` |
| videotype filter | shorts/short/short video/shortvideo | video/videos variants |
| Post-download | Raw MP4, no transcoding | HLS transcoding |
| Serving URL | `vcdn.jionews.com/raw_videos/{id}.mp4` | HLS manifest URL |

## Error Handling Summary

| Component | Error Type | Handling |
|---|---|---|
| Feed CSV read | GCS error | Function fails |
| Feed fetch (ThreadPool) | HTTP error | Individual feed skipped; executor handles exception |
| Redis check | Connection failure | All records treated as new (no dedup) |
| Redis set | Write failure | Record processes but dedup state not persisted |
| Videotype filter | No match | Record excluded (publishers 7777/7778) |
| MongoDB insert | Insert failure | Partial failure handling |
| Video download | HTTP error | Record not updated in MongoDB |
| GCS upload | Upload failure | Record not updated in MongoDB |
| MongoDB update | Update failure | Record stuck in non-completed state |

## Monitoring and Observability

| Aspect | Mechanism |
|---|---|
| Function execution | Cloud Functions logs (Cloud Logging) |
| Feed fetch failures | ThreadPoolExecutor exception handling in logs |
| Redis connectivity | Connection errors in function logs |
| MongoDB operations | Operation errors in function logs |
| Video download failures | HTTP errors in function logs |
| GCS upload status | GCS operation logs |
