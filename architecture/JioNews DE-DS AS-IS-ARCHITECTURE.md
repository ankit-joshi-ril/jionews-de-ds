# JioNews Data Engineering & Data Science — AS-IS Architecture Specification

> **Document Type:** Canonical AS-IS Architecture
> **Scope:** All data engineering ingestion pipelines and data science workflows
> **GCP Project ID:** `jiox-328108`
> **GCP Project Number:** `266686822828`
> **Generated:** 2026-02-23
> **Status:** Production — reflects current deployed state

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [GCP Infrastructure Map](#2-gcp-infrastructure-map)
3. [Pipeline 1: Headlines Ingestion](#3-pipeline-1-headlines-ingestion)
4. [Pipeline 2: Summaries Ingestion](#4-pipeline-2-summaries-ingestion)
5. [Pipeline 3: YouTube Videos Ingestion](#5-pipeline-3-youtube-videos-ingestion)
6. [Pipeline 4: Native Videos Ingestion](#6-pipeline-4-native-videos-ingestion)
7. [Pipeline 5: Video Transcoder Workflow](#7-pipeline-5-video-transcoder-workflow)
8. [Pipeline 6: YouTube Shorts Ingestion](#8-pipeline-6-youtube-shorts-ingestion)
9. [Pipeline 7: Native Shorts Ingestion](#9-pipeline-7-native-shorts-ingestion)
10. [Pipeline 8: Webstories Ingestion](#10-pipeline-8-webstories-ingestion)
11. [Pipeline 9: JioBharat Video Summaries](#11-pipeline-9-jiobharat-video-summaries)
12. [Pipeline 10: Auto Summarization (CMS Shortlisting)](#12-pipeline-10-auto-summarization-cms-shortlisting)
13. [Pipeline 11: RSS Feed Generation (Videos & Shorts)](#13-pipeline-11-rss-feed-generation-videos--shorts)
14. [Shared Infrastructure](#14-shared-infrastructure)
15. [Cross-Pipeline Data Flow Map](#15-cross-pipeline-data-flow-map)
16. [MongoDB Schema Registry](#16-mongodb-schema-registry)
17. [Pub/Sub Topic Registry](#17-pubsub-topic-registry)
18. [GCS Bucket Registry](#18-gcs-bucket-registry)
19. [Secret Manager Registry](#19-secret-manager-registry)
20. [External Service Dependency Map](#20-external-service-dependency-map)
21. [Image CDN Architecture](#21-image-cdn-architecture)
22. [LLM Integration Architecture](#22-llm-integration-architecture)
23. [Redis Caching Architecture](#23-redis-caching-architecture)
24. [Error Handling & Alerting Patterns](#24-error-handling--alerting-patterns)
25. [Ambiguities & Gaps](#25-ambiguities--gaps)

---

## 1. System Overview

### 1.1 Platform Summary

JioNews DE-DS is a production data engineering platform that ingests, processes, transforms, and distributes multi-format news content across multiple downstream consumers. The platform runs entirely on Google Cloud Platform (GCP) and processes seven distinct content types through independent but architecturally similar pipelines.

### 1.2 Content Types

| Content Type | Source Types | Pipeline Count | Deployment Model |
|---|---|---|---|
| Headlines | RSS/JSON feeds from publishers | 5 Cloud Functions | Cloud Functions (Gen 1 + Gen 2) |
| Summaries | RSS/JSON feeds from publishers + LLM generation | 5 Cloud Functions + 1 Cloud Run service | Cloud Functions + Cloud Run |
| YouTube Videos | YouTube channel HTML scraping + YouTube Data API | 3 Cloud Functions | Cloud Functions |
| Native Videos | Partner API, Editorial manual upload, MRSS feeds | 7 Cloud Functions + 2 REST services | Cloud Functions + Cloud Run/GCE |
| YouTube Shorts | YouTube channel HTML scraping + YouTube Data API | 2 Cloud Functions | Cloud Functions |
| Native Shorts | Partner API, Editorial manual upload, MRSS feeds | 3 Cloud Functions (+ shared services) | Cloud Functions |
| Webstories | Publisher APIs + RSS feeds | 2 Cloud Functions | Cloud Functions |

### 1.3 Ancillary Pipelines

| Pipeline | Purpose | Deployment Model |
|---|---|---|
| Video Transcoder Workflow | External transcoder submission and HLS URL resolution | 3 Cloud Functions |
| RSS Feed Generation (Videos) | RSS XML generation for JioHotstar consumption | 2 Cloud Functions |
| RSS Feed Generation (Shorts) | RSS XML generation for JioHotstar consumption | 2 Cloud Functions |
| JioBharat Video Summaries | TTS audio + attributed image assembly + SFTP delivery | 2 Cloud Functions + 1 FastAPI service |
| Auto Summarization | CMS-triggered LLM article summarization | 1 FastAPI service |

### 1.4 Architectural Pattern

All ingestion pipelines follow a common pattern with per-pipeline variations:

```
[Trigger: Scheduler/HTTP/API]
    |
    v
[Fetch Stage] -- Reads publisher config from GCS CSV, fetches feeds/data
    |
    v  (Pub/Sub message)
[Process Stage] -- Deduplication (Redis), field mapping, validation, article scraping
    |
    v  (Pub/Sub message)
[Image CDN Stage] -- Download, resize, upload thumbnails to GCS CDN bucket
    |
    v  (Pub/Sub message, branched: success/rejected)
[Persist Stage] -- Insert into MongoDB via Cloud Function (CloudEvent trigger)
```

### 1.5 Deployment Models

| Model | Services | Characteristics |
|---|---|---|
| **Cloud Functions Gen 1** | Most processing stages | Pub/Sub background trigger (`message, context` signature) |
| **Cloud Functions Gen 2** | All PushToMongoDB functions | CloudEvent trigger (`@functions_framework.cloud_event`) |
| **Cloud Functions (HTTP)** | Fetch stages, some process stages | HTTP trigger, invoked by Cloud Scheduler or Pub/Sub push subscriptions |
| **Cloud Run / GCE (Flask)** | `JioNewsDENativeVideos`, `yt-manual-upload` | Long-running Flask REST services on port 8080 |
| **Cloud Run (FastAPI)** | `jionews-de-image-attributor`, `jionews-summarization` | Long-running FastAPI services |
| **Cloud Run (Persistent Subscriber)** | `jionews-summarization-async` | Long-running Pub/Sub pull subscriber |

---

## 2. GCP Infrastructure Map

### 2.1 Project Identifiers

| Attribute | Value |
|---|---|
| GCP Project ID | `jiox-328108` |
| GCP Project Number | `266686822828` |
| Primary Region | `asia-south1` (Mumbai) |

### 2.2 Services Consumed

| GCP Service | Usage |
|---|---|
| Cloud Functions (Gen 1 + Gen 2) | Primary compute for pipeline stages |
| Cloud Run | Long-running REST/API services, persistent Pub/Sub subscribers |
| Cloud Pub/Sub | Inter-stage message passing, event-driven triggers |
| Cloud Storage (GCS) | Configuration storage, image CDN, video storage, RSS feed hosting |
| Secret Manager | MongoDB URIs, API keys, service account keys, SFTP credentials |
| Cloud Scheduler | Cron triggers for pipeline initiation (inferred) |
| Compute Engine | Redis instance hosting (inferred from static IP) |

---

## 3. Pipeline 1: Headlines Ingestion

### 3.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[newrawheadlinesingestion-fetchfeedsdata]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/headlines/headlines_publishers_feeds.csv
    |  Publishes: Pub/Sub "NewRawHeadlinesIngestion_raw_feeds_data"
    |  Concurrency: ThreadPoolExecutor(100)
    v
[newrawheadlinesingestion-processheadlines]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Reads: GCS de-raw-ingestion/headlines/headlines_publishers_feeds.csv
    |  Dedup: Redis sorted set "de_headlines_id_cache" + "de_headlines_title_cache"
    |  Scrapes: Article text via scraper APIs
    |  Publishes: Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    v
[newrawheadlinesingestion-imagecdn]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Downloads publisher thumbnail images
    |  Resizes to 5 renditions (original, fhd, hd, sd, low)
    |  Uploads to GCS "img-cdn-bucket"
    |
    +--[Success]--> Pub/Sub "NewRawHeadlinesIngestion_processed_data"
    |                   |
    |                   v
    |               [NewRawHeadlinesIngestion_PushToMongoDB]  -- Cloud Function (CloudEvent)
    |                   |  MongoDB: ingestion-data.raw_headlines_ingestion_data
    |                   v  (terminal)
    |
    +--[Rejected]--> Pub/Sub "NewRawHeadlinesIngestion_rejected_data"
                        |
                        v
                    [newrawheadlinesingestion-rejected-pushtomongo]  -- Cloud Function (CloudEvent)
                        |  MongoDB: ingestion-data.headlines_hygiene_failures
                        v  (terminal)
```

### 3.2 Stage Details

#### 3.2.1 FetchFeedsData

| Attribute | Value |
|---|---|
| **Entry Point** | `main(req_ph1)` |
| **Trigger** | HTTP (Cloud Scheduler) |
| **Config Source** | `gs://de-raw-ingestion/headlines/headlines_publishers_feeds.csv` |
| **Output Topic** | `NewRawHeadlinesIngestion_raw_feeds_data` |
| **Concurrency** | `ThreadPoolExecutor(max_workers=100)` |
| **Feed Formats** | RSS/XML (via feedparser) and JSON (via json.loads, key `['items']`) |
| **Custom Logic** | Replaces `<image>` tags with `<thumbimage>` for feedparser compatibility |
| **Feedparser Config** | `SANITIZE_HTML = 0` (HTML sanitization disabled) |

**Output Pub/Sub Message Schema:**
```json
{
  "feed_id": "<int, from CSV config>",
  "feed_data": ["<feedparser entry or JSON item>", "..."]
}
```

#### 3.2.2 ProcessHeadlines

| Attribute | Value |
|---|---|
| **Entry Point** | `main(req)` |
| **Trigger** | HTTP (Pub/Sub push subscription) |
| **Config Source** | `gs://de-raw-ingestion/headlines/headlines_publishers_feeds.csv` |
| **Output Topic** | `NewRawHeadlinesIngestion_image_cdn` |
| **Concurrency** | `ThreadPoolExecutor(max_workers=50)` |

**Deduplication (Redis):**

| Redis Sorted Set | Key Format | TTL |
|---|---|---|
| `de_headlines_title_cache` | `<normalized_title>` | 48 hours |
| `de_headlines_id_cache` | `<link>_<category_id>_<language_id>` | 48 hours |

**Article Scraping APIs (priority order):**

| Priority | Endpoint | Method | Timeout | Condition |
|---|---|---|---|---|
| 1 (Primary) | `https://service.jionews.com/v1/scrape/scrape/` | GET `?url=<url>` | 10s | All languages |
| 2 (Fallback) | `http://34.36.231.72/crawl` | POST (body=URL) | 15s | English only |

**UTM Parameter Injection:**
- Appends `utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews` to article URLs
- Exception: publisher `espncricinfo` uses `ex_cid=jionews` parameter instead

**Newspoint Publisher Special Handling (publishers: `english-newspointapp`, `Indiatimes`, `Navbharat Times`, `Newspoint`):**
- Field mapping differs: `hl`→title, `mwu`→url, `dl`→date, `sec`→category
- Publisher name normalized to `"Newspoint"`
- Category lookup via internal Newspoint category map

**ESPNcricinfo Special Handling:**
- Article URL sourced from `record_data['href']` instead of `record_data['link']`

**Image Thumbnail Extraction Priority Chain:**
1. `media_content[0].url` → 2. `media_thumbnail[0].url` → 3. `media_thumbnail` → 4. `thumbimage.url` → 5. `thumbimage` → 6. `fullimage` → 7. `fullimageimage` → 8. `image.url` → 9. `image.link` → 10. `image` → 11. `links[1].href` → 12. `images[0]` → 13. HTML `<img>` tag parsing (BeautifulSoup)

**Rejection Logic:**
- Headlines with empty `sourceThumbnailURL` are marked `processing_status: "rejected"` with `error_message: "No thumbnail image url found"`

**Epoch Adjustment:**
- If `publisher_epoch > epoch_now`: subtracts 19800 seconds (IST offset from UTC) to correct timezone mismatches

**Output Record Schema:**
```json
{
  "filename": "<sourceId>",
  "url": "<sourceThumbnailURL>",
  "category": "<sourceCategoryName>",
  "publisher": "<sourcePublisherName>",
  "content_type": "headlines",
  "data": {
    "title": "<whitespace-normalized>",
    "sourceDescription": "<summary>",
    "url": "<url with UTM params>",
    "sourcePublishDate": "<epoch>",
    "sourceThumbnailURL": "<original URL>",
    "thumbnailUrls": {
      "original": "https://icdn.jionews.com/original/<sourceId>.jpeg",
      "fhd": "https://icdn.jionews.com/fhd/<sourceId>.jpeg",
      "hd": "https://icdn.jionews.com/hd/<sourceId>.jpeg",
      "low": "https://icdn.jionews.com/low/<sourceId>.jpeg",
      "sd": "https://icdn.jionews.com/sd/<sourceId>.jpeg"
    },
    "sourceId": "<bson.ObjectId>",
    "createdAt": "<epoch>",
    "sourceLanguageId": "<string>",
    "sourceLanguageName": "<string>",
    "sourceCategoryId": "<string>",
    "sourceCategoryName": "<string>",
    "sourcePublisherId": "<string>",
    "sourcePublisherName": "<string>",
    "sourceFeedUrl": "<string>",
    "sourceFeedId": "<string>",
    "briefWordCount": "<int>",
    "publisherArticleBody": "<string>",
    "articleBody": "<string from scraper>",
    "articleHtml": "<string from scraper>"
  }
}
```

#### 3.2.3 ImageCDN (Shared Service)

See [Section 21: Image CDN Architecture](#21-image-cdn-architecture) for complete details. This function is shared across Headlines, Summaries, Videos, and Shorts pipelines.

#### 3.2.4 PushToMongoDB (Success)

| Attribute | Value |
|---|---|
| **Entry Point** | `write_to_mongodb(cloud_event)` |
| **Trigger** | Pub/Sub CloudEvent on `NewRawHeadlinesIngestion_processed_data` |
| **MongoDB Database** | `ingestion-data` |
| **MongoDB Collection** | `raw_headlines_ingestion_data` |
| **Operation** | `insert_many(ordered=False)` |
| **Secret** | `projects/266686822828/secrets/mongosh_de_uri/versions/latest` |

#### 3.2.5 Rejected PushToMongo

| Attribute | Value |
|---|---|
| **Entry Point** | `write_to_mongodb(cloud_event)` |
| **Trigger** | Pub/Sub CloudEvent on `NewRawHeadlinesIngestion_rejected_data` |
| **MongoDB Database** | `ingestion-data` |
| **MongoDB Collection** | `headlines_hygiene_failures` |
| **Operation** | `insert_many(ordered=False)` |

---

## 4. Pipeline 2: Summaries Ingestion

### 4.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[RawSummariesIngestion_FetchFeedsData]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/summaries/summaries_publishers_feeds.csv
    |  Publishes: Pub/Sub "RawSummariesIngestion_FeedsData"
    |  Concurrency: ThreadPoolExecutor(100)
    v
[RawSummariesIngestion_ProcessSummaries]  -- Cloud Function (Pub/Sub background)
    |  Reads: GCS de-raw-ingestion/summaries/summaries_publishers_feeds.csv
    |  Dedup: Redis sorted set "de_summaries_cache"
    |  Hygiene checks (English only): title 26-105 chars, summary 200-360 chars
    |
    +--[Hygienic records]--> Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    |                           |
    |                           v
    |                       [newrawheadlinesingestion-imagecdn]
    |                           |
    |                           v  Pub/Sub "RawSummariesIngestion_ProcessedData"
    |                           |
    |                           v
    |                       [RawSummariesIngestion_PushToMongoDB]  -- Cloud Function (CloudEvent)
    |                           |  MongoDB: ingestion-data.raw_summaries_insgestion_data
    |                           v  (terminal)
    |
    +--[Unhygienic records]--> Pub/Sub "RawSummariesIngestion_HygineFailure" (per record)
                                |
                                v
                            [jionews-summarization-async]  -- Cloud Run (persistent subscriber)
                                |  LLM: Gemini 2.5 Flash (re-generates title + summary)
                                |  Re-runs hygiene check on LLM output
                                |  MongoDB: ingestion-data.<MONGO_COLLECTION_NAME env var> (upsert)
                                |  Publishes success records to Pub/Sub <PUB_TOPIC_NAME env var>
                                v  (routes back to ImageCDN or direct to MongoDB)
```

### 4.2 Stage Details

#### 4.2.1 FetchFeedsData

Structurally identical to Headlines FetchFeedsData (Section 3.2.1).

| Attribute | Value |
|---|---|
| **Config Source** | `gs://de-raw-ingestion/summaries/summaries_publishers_feeds.csv` |
| **Output Topic** | `RawSummariesIngestion_FeedsData` |

#### 4.2.2 ProcessSummaries

| Attribute | Value |
|---|---|
| **Entry Point** | `main(msg, cntxt)` |
| **Trigger** | Pub/Sub background function |
| **Dedup Redis Set** | `de_summaries_cache` (key = normalized `title`, TTL 48h) |
| **Output Topics** | `NewRawHeadlinesIngestion_image_cdn` (hygienic), `RawSummariesIngestion_HygineFailure` (unhygienic, per-record) |

**Hygiene Rules (English language only):**

| Field | Rule | Threshold |
|---|---|---|
| Title | Not empty | — |
| Title | Min length | 26 characters |
| Title | Max length | 105 characters |
| Title | No HTML tags | Regex: `</?[a-z][\s\S]*>` |
| Title | Special char limit | < 3 from set `@#$%^&*()_+=[]{}\\|<>/?` |
| Summary | Not empty | — |
| Summary | Min length | 200 characters |
| Summary | Max length | 360 characters |
| Summary | No HTML tags | Same regex |
| Summary | Special char limit | < 3 from same set |

**Default Thumbnail Behavior:**
- When no thumbnail found: `isDefaultThumbnail = True`, `sourcePublisherName` changed to `"InsideMedia"`, `sourcePublisherId` changed to `"000"`

**Output Record Schema (additions beyond Headlines schema):**
```json
{
  "summary": "<string>",
  "isDefaultThumbnail": "<boolean>",
  "hygieneErrors": ["<error descriptions>"],
  "isHygienic": "<boolean>"
}
```

#### 4.2.3 PushToMongoDB

| Attribute | Value |
|---|---|
| **Trigger** | Pub/Sub CloudEvent on `RawSummariesIngestion_ProcessedData` |
| **MongoDB Collection** | `raw_summaries_insgestion_data` (**note: production typo "insgestion"**) |

#### 4.2.4 LLM Async Summarization

See [Section 22: LLM Integration Architecture](#22-llm-integration-architecture) for complete Gemini integration details.

| Attribute | Value |
|---|---|
| **Service Type** | Cloud Run (persistent Pub/Sub pull subscriber) |
| **Input** | Pub/Sub subscription on `RawSummariesIngestion_HygineFailure` |
| **LLM Model** | `gemini-2.5-flash` |
| **Two-Pass Strategy** | Pass 1: URL mode (Gemini fetches URL via `url_context` tool). Pass 2: Content mode (proxy fetches HTML, fed to Gemini) |
| **Proxy Service** | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` |
| **MongoDB** | `ingestion-data.<MONGO_COLLECTION_NAME>` (upsert by `sourceId`) |
| **Output Topic** | `<PUB_TOPIC_NAME>` env var (success records re-enter image CDN flow) |
| **Retry** | 3 attempts with exponential backoff (2^attempt seconds) on 503 errors |

---

## 5. Pipeline 3: YouTube Videos Ingestion

### 5.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[NewRawVideosIngestion_FetchYTChannelsData]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/videos/videos_publishers_config.csv (ISO-8859-1 encoding)
    |  Scrapes: YouTube channel pages (HTML) via HTTP GET
    |  Concurrency: ThreadPoolExecutor(10)
    |  Publishes: Pub/Sub "NewRawVideosIngestion_publishers_channel_data"
    v
[NewRawVideosIngestion_ProcessYTChannelsData]  -- Cloud Function (Pub/Sub background)
    |  Reads: GCS de-raw-ingestion/videos/videos_publishers_config.csv
    |  Dedup: Redis sorted set "de_videos_id_cache" (key: video_id_cat_lang, TTL 48h)
    |  24h recency filter
    |
    +--[to_scrape=False]--> Pub/Sub "NewRawVideosIngestion_processed_data"
    |                           |
    |                           v
    |                       [NewRawVideosIngestion_PushToMongoDB]  -- Cloud Function (CloudEvent)
    |                           |  MongoDB: ingestion-data.raw_videos_ingestion_data
    |                           v  (terminal)
    |
    +--[to_scrape=True]--> Pub/Sub "NewRawYoutubeScraper_metadata" (per record)
                               |
                               v  (external YouTube scraper service)
```

### 5.2 Stage Details

#### 5.2.1 FetchYTChannelsData

| Attribute | Value |
|---|---|
| **Entry Point** | `main(req_ph, req_ph2)` |
| **Scraping Target** | `https://www.youtube.com/channel/{channel_id}/videos` |
| **HTTP Timeout** | 5 seconds |
| **Parsing** | BeautifulSoup HTML → `ytInitialData` JSON extraction → JSONPath `$..videoRenderer` |
| **Concurrency** | `ThreadPoolExecutor(max_workers=10)` |

**Per-Video Extracted Fields:**
- `video_id`, `title`, `published_time` (relative → IST conversion), `duration`, `width`, `height`, `orientation` (landscape/portrait)

#### 5.2.2 ProcessYTChannelsData

| Attribute | Value |
|---|---|
| **Entry Point** | `main(message, context)` |
| **Redis Sorted Set** | `de_videos_id_cache` |
| **Redis Key Format** | `{video_id}_{category_id}_{language_id}` |
| **Redis TTL** | 48 hours |

**YouTube Thumbnail URL Pattern:**
```
https://i.ytimg.com/vi/{video_id}/{size}.jpg
Sizes: default(120x90), mqdefault(320x180), hqdefault(480x360), sddefault(640x480), maxresdefault(1280x720)
```

**Branching on `to_scrape` flag:**
- `False`: Batch publish to `NewRawVideosIngestion_processed_data`
- `True`: Individual publish to `NewRawYoutubeScraper_metadata` with HLS manifest URLs generated:
  - Pattern: `{video_id}_{publisher}_{language}_{category}.mp4/manifest.m3u8`
  - Bitrates: 360p, 720p, 1080p on `vcdn.jionews.com`

---

## 6. Pipeline 4: Native Videos Ingestion

### 6.1 Flow Diagram — Three Independent Sources

```
=== Source 1: Partner API Upload ===

[JioNewsDENativeVideos]  -- Flask REST API (Cloud Run, port 8080)
    |  POST /v1/de-native-video/upload/
    |  Auth: HTTP Basic Auth (env vars BASIC_AUTH_USER, BASIC_AUTH_PASS)
    |  Accepts: video (.mp4/.mov/.avi) + thumbnail (.jpg/.jpeg/.png/.webp) + metadata JSON
    |  Uploads video to GCS: hls_video_transcoder_storage_output_files/raw_videos/{source_id}.mp4
    |  Uploads thumbnail to GCS: img-cdn-bucket/original/{source_id}_{filename}
    |  Publishes: Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    v

=== Source 2: Editorial Manual Upload ===

[yt-manual-upload]  -- Flask Web UI + REST API (Cloud Run, port 8080)
    |  GET / (renders upload.html web UI)
    |  GET /metadata (returns categories, languages, publishers for dropdowns)
    |  POST /get_upload_url (generates GCS V4 signed URL, 300s expiration)
    |  POST /check_cdn (HEAD request to vcdn.jionews.com to verify upload)
    |  POST /upload (processes metadata, publishes to Pub/Sub)
    |  Publishes: Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    v

=== Source 3: MRSS Feeds / Partner APIs ===

Cloud Scheduler (cron)
    |
    v  HTTP trigger
[mrssvideos-fetchfeedsdata]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/videos/mrss_videos_feeds.csv
    |  Feed IDs 49, 50: JSON key = 'data' (IANS API); others: key = 'items'
    |  Concurrency: ThreadPoolExecutor(100)
    |  Publishes: Pub/Sub "MRSSVideosIngestion_RawFeedsData"
    v
[mrssvideos-processvideos]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Dedup: Redis sorted set "de_mrss_videos_cache" (key: title_link_cat_lang, TTL 48h)
    |  Publisher 7777/7778: filters by videotype (only "vod", "long video", "video", "videos", "longvideo")
    |  Publisher 7782 (IANS): video URL from record.get('video') instead of media_content
    |  Publishes: Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    v

=== All three sources converge at ImageCDN ===

[newrawheadlinesingestion-imagecdn]
    |  content_type = "videos" → process_video()
    |  Publishes: Pub/Sub "MRSSVideosIngestion_ProcessedData" (one per record)
    v

=== MRSS Videos: Download + Persist ===

[mrssvideos-downloadvideos]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Downloads video from publisher URL (streaming upload to GCS)
    |  GCS CDN: hls_video_transcoder_storage_output_files/raw_videos/{video_id}.mp4
    |  Copies to GCS transcoder: de_video_transcoder_input/{video_id}.mp4 (3 retries, 2s delay)
    |  Updates MongoDB: ingestion-data.raw_videos_rss (processingStatus, transcoderProcessingStatus)
    |  Skips processing for src="manual" or src="api" (already uploaded)
    v
[mrssvideos-pushtomongodb]  -- Cloud Function (CloudEvent)
    |  MongoDB: ingestion-data.raw_videos_rss
    |  Operation: insert_many(ordered=False)
    v  (terminal)
```

### 6.2 Source-Specific Details

#### 6.2.1 JioNewsDENativeVideos (Partner API)

| Attribute | Value |
|---|---|
| **Service Type** | Flask REST API |
| **Port** | 8080 |
| **Auth** | HTTP Basic Auth |
| **Publisher** | Hardcoded `"ANI"` (ID `"5001"`) |
| **`src` field** | `"api"` |
| **Accepted Video Types** | `.mp4`, `.mov`, `.avi` |
| **Accepted Image Types** | `.jpg`, `.jpeg`, `.png`, `.webp` |

**Hardcoded Category Map (ID → Name):**
```
3=entertainment, 5=fashion, 8=health, 9=food, 10=automotive, 11=travel,
12=sports, 13=news, 14=technology, 17=business, 18=cricket, 20=spiritual,
22=astrology, 26=Career
```

**Hardcoded Language Map (ID → Name):**
```
1=English, 2=Hindi, 3=Marathi, 4=Gujarati, 6=Malayalam, 7=Tamil, 8=Urdu,
9=Kannada, 10=Punjabi, 11=Telugu, 13=Bangla, 18=Odia, 19=Assamese
```

#### 6.2.2 yt-manual-upload (Editorial Upload)

| Attribute | Value |
|---|---|
| **Service Type** | Flask Web UI + REST API |
| **Port** | 8080 |
| **CORS** | Enabled for all origins (`*`) |
| **`src` field** | `"manual"` |
| **GCS Signed URL** | V4, PUT, 300s expiration, content-type `video/mp4` |
| **CDN Check** | HEAD `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |

**Thumbnail URL by Content Type:**
- Videos: `https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg`
- Shorts: `https://i.ytimg.com/vi/{video_id}/oar2.jpg`

**Metadata Sources:** `data/categories.csv`, `data/languages.csv`, `data/publishers.csv` (local files)

#### 6.2.3 MRSS Videos Process

| Attribute | Value |
|---|---|
| **Redis Sorted Set** | `de_mrss_videos_cache` |
| **Redis Key** | `{title}_{link}_{category_id}_{language_id}` |
| **`src` field** | `"publisher_mrss"` |
| **Initial Status** | `processingStatus: "processing"`, `isVideoMerged: false` |

---

## 7. Pipeline 5: Video Transcoder Workflow

### 7.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[transcoder-push-to-sftp-batching]  -- Cloud Function (HTTP)
    |  Queries MongoDB: contentType=videos, processingStatus=completed, transcoderProcessingStatus=initiated
    |  Limit: 30 records per execution
    |  Publishes each record to Pub/Sub "transcoder-push-to-sftp-batching"
    |  Updates MongoDB: transcoderProcessingStatus = "queued"
    v
[transcoder-push-to-sftp]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Downloads video from GCS: hls_video_transcoder_storage_output_files/raw_videos/
    |  Generates transcoder CSV metadata (54 fields)
    |  Uploads .mp4 + .csv to SFTP: /media/newcpp/jionews2jiohotstar/watch/
    |  Status transitions: queued → submitting → submitted (or failed)
    v
[EXTERNAL: CPP/SAAS Transcoder processes the video]
    v
Cloud Scheduler (cron, polling)
    |
    v
[transcoder-update-content-status]  -- Cloud Function (HTTP)
    |  Polls VOD API: GET /vod/v1/getallcontentstatus (limit=100, paginated)
    |  Filters: status = "Pu" (Published)
    |  For each: GET /vod/v1/getcontentdetails/{content_id}/jionews
    |  Constructs HLS URLs (AVC + HEVC)
    |  Concurrency: ThreadPoolExecutor(5) for API calls
    |  Updates MongoDB: transcoderProcessingStatus = "completed", hlsAvcUrl, hlsHevcUrl
    |  Publishes to Pub/Sub: "raw_native_videos" + "NewRawVideosIngestion_processed_data"
    v  (terminal)
```

### 7.2 Transcoder Status State Machine

```
(empty/None) → initiated → queued → submitting → submitted → completed
                                              └→ failed       └→ failed
```

### 7.3 External Transcoder API (CPP/SAAS)

| Attribute | Value |
|---|---|
| **Base URL** | `https://cppapi-saas.media.jio.com` |
| **Access Key** | `jionews1` |
| **Distributor Name** | `jionews` |
| **Distributor ID** | `685bc98ec9e754683750e182` |
| **Auth Mechanism** | HMAC-SHA256: payload = `{url_path}{access_key}{epoch}`, signed with API secret |
| **Retry** | 3 attempts, 5-second delay |
| **Thread Pool** | 5 workers for parallel `getcontentdetails` calls |

**HLS URL Construction:**
```
Base URL: https://videos.jionews.com/jvodnews
AVC:  {base_url}/{path with 'index_jnews_web_premium' replaced by 'master-_jnews_web_premium'}
HEVC: {base_url}/{hevc_path with same replacement}
```

### 7.4 SFTP Configuration

| Attribute | Value |
|---|---|
| **Secret** | `projects/266686822828/secrets/de_trascoder_sftp/versions/latest` (JSON: hostname, port, username, password) |
| **Remote Path** | `/media/newcpp/jionews2jiohotstar/watch/` |
| **Files Uploaded** | `{video_id}.mp4` + `{video_id}.csv` |
| **Library** | `paramiko` (Transport-based SFTP) |

### 7.5 Transcoder CSV Metadata

54-column CSV with fields: `FileName`, `ContentType`, `Title`, `Synopsis`, `ReleaseDate`, `RightsOwner`, `RightsStartDate`, `RightsEndDate`, `ReleaseTime`, `Genre`, `SubGenre`, `Language`, `Starcast`, `Director`, `MusicDirector`, `CensorCertification`, `Keywords`, `MaturityRating`, `MaturityDescriptor`, `Download`, `GeoBlock`, `Subscription`, `AdCueTime1-8`, `IntroCreditsStartTime`, `IntroCreditsEndTime`, `EndCreditsStartTime`, `EndCreditsEndTime`, `Producer`, `Writer`, `IMDBRating`, `ContentShortName`, `Characters`, `SeriesSeasonNumber`, `EpisodeName`, `EpisodeSynopsis`, `EpisodeNumber`, `Precap/Recap Credits`, `Singer`, `Lyricyst`, `Label`, `ShowID`, `AlbumName`, `LoopPlay`, `ChannelID`

**Populated fields:** Only `FileName` (sourceVideoId), `ContentType` ("Video"), `Language`. All others are empty strings. Language "Bangla" is mapped to "Bengali".

---

## 8. Pipeline 6: YouTube Shorts Ingestion

### 8.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[RawShortsIngestion_ScrapeVideoIds]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/shorts/shorts_publishers.csv (ISO-8859-1)
    |  Scrapes: http://www.youtube.com/{custom_url}/shorts (5s timeout)
    |  Parses: BeautifulSoup → ytInitialData → JSONPath $..videoId
    |  Dedup against MongoDB: ingestion-data.raw_short_videos_ingestion_data
    |  Publishes: Pub/Sub "cron_based_raw_youtube_shorts_ingestion"
    v
[RawShortsIngestion_YouTubeAPIToMongoDB]  -- Cloud Function (Pub/Sub background)
    |  Reads: GCS de-raw-ingestion/shorts/shorts_publishers.csv
    |  YouTube Data API v3:
    |    - videos().list(part="snippet,contentDetails", batch of 50 IDs)
    |  Validates: duration <= 60s AND duration > 0s AND URL redirect check
    |  24h recency filter on publishedAt
    |  MongoDB: ingestion-data.raw_short_videos_ingestion_data (insert_many)
    |  Publishes: Pub/Sub "raw_youtube_shorts_ingestion"
    v  (terminal — downstream consumers not in this codebase)
```

### 8.2 YouTube Shorts Validation

**Duration Filter:** `0 < duration_seconds <= 60` (ISO 8601 parsed via `isodate`)

**URL Redirect Validation:**
```
GET https://www.youtube.com/shorts/{video_id}  (allow_redirects=False)
→ HTTP 200 = is a Short
→ Any other status = not a Short (redirects to regular video page)
```

### 8.3 YouTube API Secret

| Secret Path | Purpose |
|---|---|
| `projects/266686822828/secrets/yt_api_access_token/versions/latest` | YouTube Data API v3 key |

### 8.4 Output Schema

```json
{
  "sourceVideoId": "<YouTube video ID>",
  "title": "<snippet.title>",
  "sourceThumbnailURL": "https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
  "sourceDate": "<snippet.publishedAt>",
  "sourceEpoch": "<epoch>",
  "sourceDescription": "<snippet.description>",
  "src": "youtube",
  "sourceThumbnails": "<full YouTube thumbnails object>",
  "sourceVideoDuration": "<seconds>",
  "sourceVideoWidth": 1080,
  "sourceVideoHeight": 1920,
  "sourceVideoOrientation": "portrait"
}
```

---

## 9. Pipeline 7: Native Shorts Ingestion

### 9.1 Flow Diagram

```
=== Source 1: Partner API — same as Native Videos (JioNewsDENativeVideos) ===
=== Source 2: Editorial Upload — same as Native Videos (yt-manual-upload, contentType="shorts") ===

=== Source 3: MRSS Feeds ===

Cloud Scheduler (cron)
    |
    v  HTTP trigger
[mrssshorts-fetchfeedsdata]  -- Cloud Function (HTTP)
    |  Reads: GCS de-raw-ingestion/shorts/mrss_shorts_feeds.csv
    |  Feed IDs 49, 50: JSON key = 'data'; others: key = 'items'
    |  Concurrency: ThreadPoolExecutor(100)
    |  Publishes: Pub/Sub "MRSSShortsIngestion_RawFeedsData"
    v
[mrssshorts-processvideos]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Dedup: Redis sorted set "de_mrss_shorts_cache" (key: title_link_cat_lang, TTL 48h)
    |  Publisher 7777/7778: filters by videotype (only "shorts", "short", "short video", "shortvideo")
    |  Publisher 7782 (IANS): video URL from record.get('video')
    |  contentType = "shorts", sourceVideoOrientation = "portrait"
    |  Publishes images: Pub/Sub "NewRawHeadlinesIngestion_image_cdn"
    |  Inserts records: MongoDB ingestion-data.raw_videos_rss (insert_many)
    |  Publishes records: Pub/Sub "MRSSShortsIngestion_ProcessedData" (per record)
    v
[mrssshorts-downloadvideos]  -- Cloud Function (HTTP, Pub/Sub push)
    |  Downloads video to GCS: hls_video_transcoder_storage_output_files/raw_videos/
    |  NO transcoder submission (shorts skip transcoding)
    |  Updates MongoDB: processingStatus = "completed"
    |  videoContentUrl = "https://vcdn.jionews.com/raw_videos/{video_id}.mp4"
    v  (terminal)
```

### 9.2 Key Differences from Native Videos

| Aspect | Native Videos | Native Shorts |
|---|---|---|
| **Videotype filter (7777/7778)** | "vod", "long video", "video", "videos", "longvideo" | "shorts", "short", "short video", "shortvideo" |
| **contentType field** | `"videos"` | `"shorts"` |
| **Orientation** | `"landscape"` | `"portrait"` |
| **Transcoding** | Full transcoder workflow (SFTP → CPP/SAAS → HLS) | Skipped — raw MP4 served directly |
| **Redis cache** | `de_mrss_videos_cache` | `de_mrss_shorts_cache` |
| **Pub/Sub topics** | `MRSSVideosIngestion_*` | `MRSSShortsIngestion_*` |
| **Default image random range** | 1-10 (or 1-22 for latest_news) | 1-5 |

---

## 10. Pipeline 8: Webstories Ingestion

### 10.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[RawWebStoriesIngestion]  -- Cloud Function (HTTP)
    |  Reads: publishers.csv (local file, not GCS)
    |  Supports: type="api" (JSON API) and type="feed" (RSS/Atom via feedparser)
    |  Field mapping defined per publisher in CSV (JSON mapping string)
    |  UTM params: utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories
    |  Validates thumbnail URLs via HTTP GET
    |  Publishes: Pub/Sub "RawWebStoriesIngestion"
    v
[RawWebStoriesIngestion_PushToMongoDB]  -- Cloud Function (CloudEvent)
    |  MongoDB: ingestion-data.raw_web_stories_ingestion_data
    |  Operation: insert_many(ordered=False)
    v  (terminal)
```

### 10.2 Publisher Configuration

| Attribute | Source |
|---|---|
| **Config File** | `publishers.csv` (local to Cloud Function, NOT on GCS) |
| **Columns** | `sys_pub_name`, `endpoint`, `data_list_path`, `type` (api/feed), `mapping` (JSON string), `category`, `language` |

### 10.3 Output Record Schema

```json
{
  "sourceId": "<from publisher mapping>",
  "title": "<from publisher mapping>",
  "sourcePublishedDate": "<from publisher mapping>",
  "sourceCategoryName": "<from CSV category column>",
  "sourceLanguageName": "<from CSV language column>",
  "sourcePublisherName": "<from CSV sys_pub_name column>",
  "sourceURL": "<HTTPS + UTM params>",
  "sourceThumbnailUrl": "<validated HTTPS URL or empty>",
  "createdAt": "<epoch IST>"
}
```

---

## 11. Pipeline 9: JioBharat Video Summaries

### 11.1 Flow Diagram

```
Cloud Scheduler (cron)
    |
    v  HTTP trigger
[JioBharat_AggregateSummariesPROD]  -- Cloud Function (HTTP)
    |  Reads PROD MongoDB: pie-production.summaries (aggregation pipeline)
    |    - createdAt: today (full IST day range)
    |    - language.code: HIN, TAM, TEL, KAN, MAR, BAN, MAL, GUJ
    |    - isAudioSummaryGenerated: true
    |    - isBreaking: false
    |    - Limit: 50 per language, sorted newest first
    |  Reads DE MongoDB: ingestion-data.jio_bharat_summaries (dedup: isSuccess=true)
    |  Publishes unprocessed summaries: Pub/Sub "JioBharat_AggregateSummariesProd"
    v
[jiobharat-pushtosftpprod]  -- Cloud Function (Pub/Sub background)
    |  For each summary:
    |    1. POST https://service.jionews.com/v1/image-attributor/generate-image
    |       → Renders HTML template with title + publisher overlay on thumbnail
    |       → Saves attributed image to GCS: img-cdn-bucket/jio_bharat/prod/{summary_id}.jpeg
    |    2. Downloads audio from GCS: audio-summaries-bucket/prd/{summary_id}.mp3
    |    3. Downloads attributed image from GCS: img-cdn-bucket/jio_bharat/prod/{summary_id}.jpeg
    |    4. Uploads to SFTP: mediaftp1.ril.com:33001
    |       Remote path: /media/prod/{language_folder}/{summary_id}_{lang}_{dd_mm_yyyy}.{ext}
    |  Records status: MongoDB ingestion-data.jio_bharat_summaries (insert_many)
    v  (terminal — external system creates videos from audio+image)
```

### 11.2 PROD MongoDB Aggregation Pipeline

```javascript
[
  { $match: {
    createdAt: { $gte: start_epoch, $lte: end_epoch },
    "language.code": { $in: ["HIN", "TAM", "TEL", "KAN", "MAR", "BAN", "MAL", "GUJ"] },
    isAudioSummaryGenerated: true,
    isBreaking: false
  }},
  { $sort: { createdAt: -1 } },
  { $group: { _id: "$language.code", summaries: { $push: { ... } } } },
  { $project: { _id: 0, summaries: { $slice: ["$summaries", 50] } } },
  { $unwind: "$summaries" },
  { $replaceRoot: { newRoot: "$summaries" } }
]
```

### 11.3 SFTP Configuration

| Attribute | Value |
|---|---|
| **Host** | `mediaftp1.ril.com` |
| **Port** | `33001` |
| **Username** | `FT_jionews_livenews` |
| **Base Path** | `/media/prod/{language_folder}/` |

**Language Folder Mapping:**
```
hin → taaza_kabrein_hin
kan → pramukha_Suddi_kan
tam → ungal_Seithigal_tam
tel → itivali_varthalu_tel
mar → taajya_baatmya_mar
ban → tatka_sangbad_ban
guj → taaza_samachar_guj
mal → puthiya_varthakal_mal
```

### 11.4 Image Attributor Service

| Attribute | Value |
|---|---|
| **Service Type** | FastAPI (Cloud Run) |
| **Route** | `POST /v1/image-attributor/generate-image` |
| **Rendering** | Jinja2 HTML template → headless Chromium screenshot (pyppeteer) |
| **Viewport** | 1920 x 1080 px |
| **Output Format** | JPEG |
| **Storage** | GCS `img-cdn-bucket/jio_bharat/{summary_id}.jpeg` |
| **Chromium Args** | `--no-sandbox`, `--disable-setuid-sandbox` |

---

## 12. Pipeline 10: Auto Summarization (CMS Shortlisting)

### 12.1 Flow Diagram

```
CMS Editorial Action (shortlists article)
    |
    v  HTTP POST
[jionews-summarization]  -- FastAPI Service (Cloud Run)
    |  POST /v1/jionews-summarization/summarize
    |  Request: { article_url, article_content, source_headline_id, model? }
    |
    |  Pass 1: Gemini 2.5 Flash with article_url (url_context tool)
    |    |
    |    +--[URL fetch failure detected]--> Proxy fetch via
    |    |  https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy?url=<encoded>
    |    |  (45s timeout)
    |    |
    |    +--[Retry with article_content]
    |
    |  MongoDB upsert: ingestion-data.auto_summarization (by sourceId)
    |
    v  HTTP response: { sourceId, summary, updateCount, createdAt, updatedAt }
```

### 12.2 LLM Configuration

| Attribute | Value |
|---|---|
| **Model** | `gemini-2.5-flash` (default, overridable per request) |
| **Temperature** | 0 (deterministic) |
| **Thinking** | Disabled (`include_thoughts=False`) |
| **Tools** | `[{"url_context": {}}]` (enables Gemini URL fetching) |
| **Summary Target** | 350-360 characters |

**System Instruction:**
```
You act as a news editor/writer and summarize news articles accurately and concisely.
Your output must be ONLY a single summary between 350 and 360 characters.
Do NOT include: reasoning, planning, steps, drafts, explanations,
notes, meta comments, chain-of-thought, or analysis.
Output ONLY the final summary text, nothing else.
```

**URL Failure Detection Substrings:**
`"unable to summarize"`, `"unable to access"`, `"unable to browse"`, `"could not be fetched"`, `"could not be accessed"`, `"URL did not contain"`, `"I am unable to"`

### 12.3 MongoDB Upsert Schema

```json
{
  "$set": {
    "articleContent": "<original content>",
    "articleUrl": "<original URL>",
    "summary": "<generated summary>",
    "processingSource": "publisher_url | publisher_content | proxy_url",
    "model": "gemini-2.5-flash",
    "error_message": "",
    "updatedAt": "<epoch>"
  },
  "$setOnInsert": { "createdAt": "<epoch>", "sourceId": "<id>" },
  "$inc": { "updateCount": 1 }
}
```

---

## 13. Pipeline 11: RSS Feed Generation (Videos & Shorts)

### 13.1 Videos HLS RSS Feed

```
Cloud Scheduler (cron)
    |
    v
[RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit]  -- Cloud Function (HTTP)
    |  MongoDB aggregation: top 100 per language
    |    - transcoderProcessingStatus: "completed", contentType: "videos"
    |    - $setWindowFields + $documentNumber for ranking
    |  Category mapping applied
    |  Publishes per-language: Pub/Sub "RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit"
    v
[RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit]  -- Cloud Function (Pub/Sub background)
    |  Generates RSS 2.0 XML with Media RSS (xmlns:media)
    |  Includes hlsAvcUrl and hlsHevcUrl elements
    |  Target languages: IDs 1-13
    |  Uploads to GCS: hls_video_transcoder_storage_output_files/rss/videos_hls/{language}/rss.xml
    v  (consumed by JioHotstar)
```

### 13.2 Shorts RSS Feed

```
Cloud Scheduler (cron)
    |
    v
[RawShortsContentPrepareRss_AggregateDataLanguageSplit]  -- Cloud Function (HTTP)
    |  MongoDB aggregation: top 100 per language
    |    - processingStatus: "completed", contentType: "shorts"
    |    - Same $setWindowFields ranking as Videos
    |  Category mapping applied
    |  Publishes per-language: Pub/Sub "RawShortsContentPrepareRss_AggregatedDataLanguageSplit"
    v
[RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit]  -- Cloud Function (Pub/Sub background)
    |  Generates RSS 2.0 XML with Media RSS (xmlns:media)
    |  NO HLS URL elements (shorts use raw MP4)
    |  Target languages: IDs 1-13
    |  Uploads to GCS: hls_video_transcoder_storage_output_files/rss/shorts/{language}/rss.xml
    v  (consumed by JioHotstar)
```

### 13.3 Category Mapping (Shared)

```
news → news                    cricket → sports
business → business news       technology → science and technology
automotive → automobile        entertainment → entertainment
health → health                spiritual → astrology
astrology → astrology          fashion → lifestyle
travel → lifestyle             food → lifestyle
diy → lifestyle                sports → sports
career → education             football → sports
agro → news                    [unmapped] → news (default)
```

### 13.4 RSS XML Structure

```xml
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>JioNews Videos RSS Feed</title>
    <link>https://jionews.com</link>
    <description>JioNews - RSS feed for videos</description>
    <item>
      <title>...</title>
      <link>videoContentUrl</link>
      <description>title</description>
      <pubDate>YYYY-MM-DDTHH:MM:SS.000+05:30</pubDate>
      <media:content url="..." duration="..." medium="video" type="video/mp4"/>
      <media:thumbnail url="..." type="image/jpeg"/>
      <hlsAvcUrl>...</hlsAvcUrl>          <!-- Videos only, not Shorts -->
      <hlsHevcUrl>...</hlsHevcUrl>        <!-- Videos only, not Shorts -->
      <keywords>news</keywords>
      <category>mapped category</category>
      <sourceVideoId>...</sourceVideoId>
      <thumbnailUrls>
        <default><url>...</url><width>...</width><height>...</height></default>
        <medium>...</medium>
        <high>...</high>
        <standard>...</standard>
        <maxres>...</maxres>
      </thumbnailUrls>
    </item>
  </channel>
</rss>
```

### 13.5 Thumbnail Key Normalization (RSS output)

| Source Key | RSS Key |
|---|---|
| `low` | `default` |
| `sd` | `medium` |
| `hd` | `high` |
| `fhd` | `standard` |
| `original` | `maxres` |

---

## 14. Shared Infrastructure

### 14.1 Common Libraries Across All Pipelines

| Library | Version | Usage |
|---|---|---|
| `google-cloud-pubsub` | — | Inter-stage messaging |
| `google-cloud-storage` | — | GCS operations |
| `google-cloud-secret-manager` | — | Credential retrieval |
| `pymongo` | — | MongoDB operations |
| `pandas` | — | CSV config reading |
| `requests` | — | HTTP calls (SSL verify disabled in many places) |
| `feedparser` | — | RSS/Atom feed parsing |
| `redis` | — | Deduplication caching |
| `Pillow` (PIL) | — | Image processing |
| `beautifulsoup4` | — | HTML parsing |
| `python-dateutil` | — | Flexible date parsing |
| `bson` | — | ObjectId generation |
| `pytz` / `zoneinfo` | — | Timezone handling (IST) |
| `paramiko` | — | SFTP operations |
| `google-genai` | — | Gemini LLM integration |
| `functions-framework` | — | Cloud Functions Gen 2 |
| `fastapi` | — | REST API services |
| `flask` | — | Web UI + REST services |
| `pyppeteer` | — | Headless Chromium for screenshots |
| `jinja2` | — | HTML template rendering |
| `isodate` | — | ISO 8601 duration parsing |
| `jsonpath-ng` | — | JSONPath queries |

### 14.2 Timezone Standard

All pipelines use `Asia/Kolkata` (IST, UTC+05:30) for:
- Epoch calculations
- Date/time logging
- Recency filters (24-hour windows)
- File naming conventions

### 14.3 ID Generation

All content records use `bson.ObjectId()` for `sourceId` / `sourceVideoId` generation, providing MongoDB-compatible unique identifiers.

---

## 15. Cross-Pipeline Data Flow Map

### 15.1 Shared Image CDN Function

The function `newrawheadlinesingestion-imagecdn` is the central image processing hub. It receives records from multiple pipelines via the shared topic `NewRawHeadlinesIngestion_image_cdn` and dispatches based on the `content_type` field:

```
                        ┌── Headlines pipeline ──────────┐
                        │                                 │
                        ├── Summaries pipeline ──────────┤
                        │                                 │
NewRawHeadlinesIngestion_image_cdn ←── MRSS Videos pipeline ──┤  content_type dispatcher
                        │                                 │
                        ├── MRSS Shorts pipeline ────────┤
                        │                                 │
                        ├── API Upload (Videos) ──────────┤
                        │                                 │
                        └── Manual Upload ────────────────┘

Dispatch:
  content_type="headlines"  → process_headline() → NewRawHeadlinesIngestion_processed_data / _rejected_data
  content_type="videos"     → process_video()    → MRSSVideosIngestion_ProcessedData (per record)
  content_type="summaries"  → process_summary()  → RawSummariesIngestion_ProcessedData
  content_type=<other>      → process_other_content() (no Pub/Sub, CDN only)
```

### 15.2 Shared MongoDB Collections

| Collection | Written By | Content Types |
|---|---|---|
| `raw_videos_rss` | mrssvideos-pushtomongodb, mrssvideos-processvideos, mrssshorts-processvideos, mrssvideos-downloadvideos, mrssshorts-downloadvideos, transcoder-* | Native Videos + Native Shorts (shared) |
| `raw_videos_ingestion_data` | NewRawVideosIngestion_PushToMongoDB | YouTube Videos only |
| `raw_short_videos_ingestion_data` | RawShortsIngestion_YouTubeAPIToMongoDB, RawShortsIngestion_ScrapeVideoIds (reads) | YouTube Shorts only |

---

## 16. MongoDB Schema Registry

### 16.1 Connection

| Attribute | Value |
|---|---|
| **URI Source** | Secret Manager: `projects/266686822828/secrets/mongosh_de_uri/versions/latest` |
| **Database** | `ingestion-data` (DE cluster) |
| **Secondary Database** | `pie-production` (PROD cluster, read-only by JioBharat pipeline) |
| **TLS** | Used by YouTube Shorts pipeline (via `certifi.where()`); other pipelines use default |

### 16.2 Collections

| Collection | Pipeline | Operations | Key Fields |
|---|---|---|---|
| `raw_headlines_ingestion_data` | Headlines | `insert_many(ordered=False)` | `sourceId`, `title`, `url`, `sourcePublishDate` |
| `headlines_hygiene_failures` | Headlines (rejected) | `insert_many(ordered=False)` | Same + `processing_status`, `error_message` |
| `raw_summaries_insgestion_data` | Summaries | `insert_many(ordered=False)` | `sourceId`, `title`, `summary`, `isHygienic` |
| `raw_videos_ingestion_data` | YouTube Videos | `insert_many(ordered=False)` | `sourceVideoId`, `title`, `src: "youtube"` |
| `raw_videos_rss` | Native Videos + Native Shorts | `insert_many`, `update_one`, aggregations | `sourceVideoId`, `contentType`, `processingStatus`, `transcoderProcessingStatus` |
| `raw_short_videos_ingestion_data` | YouTube Shorts | `insert_many(ordered=False)`, aggregation (dedup) | `sourceVideoId`, `src: "youtube"` |
| `raw_web_stories_ingestion_data` | Webstories | `insert_many(ordered=False)` | `sourceId`, `title`, `sourceURL` |
| `jio_bharat_summaries` | JioBharat | `insert_many`, query (dedup) | `summary_id`, `isSuccess`, `language` |
| `auto_summarization` | Auto Summarization | `find_one_and_update` (upsert) | `sourceId`, `summary`, `updateCount` |
| `<MONGO_COLLECTION_NAME>` (env var) | Summarization Async | `update_one` (upsert by sourceId) | `sourceId`, `reprocessingStatus` |
| `summaries` (pie-production) | JioBharat (read-only) | Aggregation pipeline | `_id`, `language.code`, `isAudioSummaryGenerated` |

---

## 17. Pub/Sub Topic Registry

### 17.1 Complete Topic Map

| # | Topic Name | Publisher(s) | Consumer(s) | Trigger Type |
|---|---|---|---|---|
| 1 | `NewRawHeadlinesIngestion_raw_feeds_data` | Headlines FetchFeedsData | Headlines ProcessHeadlines | Push subscription |
| 2 | `NewRawHeadlinesIngestion_image_cdn` | Headlines Process, Summaries Process, MRSS Videos Process, MRSS Shorts Process, API Upload, Manual Upload | ImageCDN (shared function) | Push subscription |
| 3 | `NewRawHeadlinesIngestion_processed_data` | ImageCDN (headlines), transcoder-update-content-status | Headlines PushToMongoDB | CloudEvent |
| 4 | `NewRawHeadlinesIngestion_rejected_data` | ImageCDN (rejected headlines) | Headlines Rejected PushToMongo | CloudEvent |
| 5 | `RawSummariesIngestion_FeedsData` | Summaries FetchFeedsData | Summaries ProcessSummaries | Background function |
| 6 | `RawSummariesIngestion_ProcessedData` | ImageCDN (summaries) | Summaries PushToMongoDB | CloudEvent |
| 7 | `RawSummariesIngestion_HygineFailure` | Summaries ProcessSummaries | jionews-summarization-async | Pull subscription |
| 8 | `NewRawVideosIngestion_publishers_channel_data` | YT FetchChannelsData | YT ProcessChannelsData | Background function |
| 9 | `NewRawVideosIngestion_processed_data` | YT ProcessChannelsData, transcoder-update-content-status | YT PushToMongoDB | CloudEvent |
| 10 | `NewRawYoutubeScraper_metadata` | YT ProcessChannelsData (to_scrape=True) | External scraper (not in codebase) | — |
| 11 | `MRSSVideosIngestion_RawFeedsData` | mrssvideos-fetchfeedsdata | mrssvideos-processvideos | Push subscription |
| 12 | `MRSSVideosIngestion_ProcessedData` | ImageCDN (videos) | mrssvideos-downloadvideos, mrssvideos-pushtomongodb | Push subscription + CloudEvent |
| 13 | `MRSSShortsIngestion_RawFeedsData` | mrssshorts-fetchfeedsdata | mrssshorts-processvideos | Push subscription |
| 14 | `MRSSShortsIngestion_ProcessedData` | mrssshorts-processvideos | mrssshorts-downloadvideos | Push subscription |
| 15 | `RawWebStoriesIngestion` | RawWebStoriesIngestion | RawWebStoriesIngestion_PushToMongoDB | CloudEvent |
| 16 | `cron_based_raw_youtube_shorts_ingestion` | ScrapeVideoIds | YouTubeAPIToMongoDB | Background function |
| 17 | `raw_youtube_shorts_ingestion` | YouTubeAPIToMongoDB | External consumer (not in codebase) | — |
| 18 | `JioBharat_AggregateSummariesProd` | JioBharat_AggregateSummariesPROD | jiobharat-pushtosftpprod | Background function |
| 19 | `transcoder-push-to-sftp-batching` | transcoder-push-to-sftp-batching | transcoder-push-to-sftp | Push subscription |
| 20 | `raw_native_videos` | transcoder-update-content-status | External consumer (not in codebase) | — |
| 21 | `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` | Videos RSS Aggregate | Videos RSS Process | Background function |
| 22 | `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` | Shorts RSS Aggregate | Shorts RSS Process | Background function |
| 23 | `<PUB_TOPIC_NAME>` (env var) | jionews-summarization-async | Downstream (re-enters ImageCDN or MongoDB) | — |

---

## 18. GCS Bucket Registry

### 18.1 Complete Bucket Map

| # | Bucket Name | Purpose | Access Patterns |
|---|---|---|---|
| 1 | `de-raw-ingestion` | Pipeline configuration CSVs | Read-only by Cloud Functions |
| 2 | `img-cdn-bucket` | Image CDN storage (thumbnails at 5 resolutions + defaults) | Read/Write by ImageCDN, Image Attributor |
| 3 | `hls_video_transcoder_storage_output_files` | Raw video storage + RSS feed hosting | Read/Write by video pipeline stages |
| 4 | `de_video_transcoder_input` | Transcoder input staging | Write by mrssvideos-downloadvideos |
| 5 | `audio-summaries-bucket` | TTS audio files for JioBharat | Read by jiobharat-pushtosftpprod |

### 18.2 Detailed Path Registry

| Bucket | Path | Content | Accessed By |
|---|---|---|---|
| `de-raw-ingestion` | `headlines/headlines_publishers_feeds.csv` | Headlines publisher config | Headlines Fetch + Process |
| `de-raw-ingestion` | `summaries/summaries_publishers_feeds.csv` | Summaries publisher config | Summaries Fetch + Process |
| `de-raw-ingestion` | `videos/videos_publishers_config.csv` | YouTube Videos publisher config | YT Videos Fetch + Process |
| `de-raw-ingestion` | `videos/mrss_videos_feeds.csv` | MRSS Videos feed config | MRSS Videos Fetch + Process + Download |
| `de-raw-ingestion` | `shorts/shorts_publishers.csv` | YouTube Shorts publisher config | YT Shorts Scrape + API |
| `de-raw-ingestion` | `shorts/mrss_shorts_feeds.csv` | MRSS Shorts feed config | MRSS Shorts Fetch + Process |
| `img-cdn-bucket` | `original/{id}.jpeg` | Original resolution images | ImageCDN (write), various (read) |
| `img-cdn-bucket` | `fhd/{id}.jpeg` | 1920x1080 images | ImageCDN (write) |
| `img-cdn-bucket` | `hd/{id}.jpeg` | 1280x720 images | ImageCDN (write) |
| `img-cdn-bucket` | `sd/{id}.jpeg` | 720x480 images | ImageCDN (write) |
| `img-cdn-bucket` | `low/{id}.jpeg` | 480x320 images | ImageCDN (write) |
| `img-cdn-bucket` | `default/{category}/{size}/{category}_{n}.png` | Default category images | ImageCDN (read/copy) |
| `img-cdn-bucket` | `jio_bharat/{summary_id}.jpeg` | Attributed images | Image Attributor (write) |
| `img-cdn-bucket` | `jio_bharat/prod/{summary_id}.jpeg` | Prod attributed images | JioBharat SFTP push (read) |
| `hls_video_transcoder_storage_output_files` | `raw_videos/{id}.mp4` | Raw video files | Video pipelines (write/read) |
| `hls_video_transcoder_storage_output_files` | `rss/videos_hls/{language}/rss.xml` | Videos RSS feeds | RSS Process (write), JioHotstar (read) |
| `hls_video_transcoder_storage_output_files` | `rss/shorts/{language}/rss.xml` | Shorts RSS feeds | RSS Process (write), JioHotstar (read) |
| `audio-summaries-bucket` | `prd/{summary_id}.mp3` | TTS audio files | JioBharat SFTP push (read) |

---

## 19. Secret Manager Registry

| # | Secret Path | Purpose | Consumers |
|---|---|---|---|
| 1 | `projects/266686822828/secrets/mongosh_de_uri/versions/latest` | MongoDB DE cluster URI | All pipelines |
| 2 | `projects/266686822828/secrets/GEMINI_API_KEY/versions/latest` | Google Gemini API key | jionews-summarization-async, jionews-summarization |
| 3 | `projects/266686822828/secrets/yt_api_access_token/versions/latest` | YouTube Data API v3 key | RawShortsIngestion_YouTubeAPIToMongoDB |
| 4 | `projects/266686822828/secrets/compute_engine_service_account_private_key/versions/latest` | GCS/Pub/Sub service account | yt-manual-upload |
| 5 | `projects/266686822828/secrets/de_trascoder_sftp/versions/latest` | SFTP credentials (JSON) | transcoder-push-to-sftp |

---

## 20. External Service Dependency Map

### 20.1 External APIs

| Service | Endpoint | Protocol | Used By | Purpose |
|---|---|---|---|---|
| Article Scraper (Primary) | `https://service.jionews.com/v1/scrape/scrape/` | HTTP GET | Headlines, Summaries | Article text extraction |
| Article Scraper (Fallback) | `http://34.36.231.72/crawl` | HTTP POST | Headlines, Summaries (English only) | Article text extraction |
| Article Proxy | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` | HTTP GET | Summarization services | JS-rendered HTML fetching |
| Image Attributor | `https://service.jionews.com/v1/image-attributor/generate-image` | HTTP POST | JioBharat pipeline | Title/publisher overlay on thumbnails |
| CPP/SAAS Transcoder API | `https://cppapi-saas.media.jio.com/vod/v1/` | HTTP GET (HMAC auth) | Transcoder workflow | Transcoding status + HLS URLs |
| YouTube Data API v3 | `googleapis.com/youtube/v3` | OAuth/API key | YouTube Shorts pipeline | Video metadata + duration |
| Google Gemini API | via `google.genai` SDK | HTTP | Summarization services | LLM text generation |

### 20.2 External Infrastructure

| Service | Endpoint | Protocol | Used By | Purpose |
|---|---|---|---|---|
| Redis | `34.93.131.211:6379` | Redis protocol | Headlines, Summaries, MRSS Videos, MRSS Shorts | Deduplication cache |
| SFTP (Transcoder) | Secret Manager (JSON) | SFTP (paramiko) | Transcoder workflow | Video + CSV upload to JioHotstar |
| SFTP (JioBharat) | `mediaftp1.ril.com:33001` | SFTP (paramiko) | JioBharat pipeline | Audio + image upload |

### 20.3 CDN Domains

| Domain | Purpose | Consumers |
|---|---|---|
| `icdn.jionews.com` | Image CDN (backed by GCS `img-cdn-bucket`) | All pipelines (thumbnail URLs) |
| `vcdn.jionews.com` | Video CDN (backed by GCS `hls_video_transcoder_storage_output_files`) | Video/Shorts pipelines |
| `videos.jionews.com` | HLS streaming CDN (path: `/jvodnews/...`) | Transcoder workflow (HLS URL construction) |
| `i.ytimg.com` | YouTube thumbnail CDN | YouTube Videos, YouTube Shorts, Manual Upload |

### 20.4 Web Scraping Targets

| Target | URL Pattern | Used By |
|---|---|---|
| YouTube Videos Page | `https://www.youtube.com/channel/{channel_id}/videos` | YT Videos FetchChannelsData |
| YouTube Shorts Page | `http://www.youtube.com/{custom_url}/shorts` | YT Shorts ScrapeVideoIds |
| YouTube Shorts Validation | `https://www.youtube.com/shorts/{video_id}` | YT Shorts API (redirect check) |
| Publisher RSS/JSON Feeds | Various URLs from CSV configs | All feed-based pipelines |

---

## 21. Image CDN Architecture

### 21.1 Shared Function: `newrawheadlinesingestion-imagecdn`

This single Cloud Function handles image processing for Headlines, Summaries, Videos, and Shorts. Copies of this function exist in multiple pipeline directories but are identical in behavior.

### 21.2 Image Processing Pipeline

```
1. Download image from publisher URL (10s timeout, SSL verify=False)
2. Open with Pillow, apply EXIF transpose (rotation correction)
3. Convert RGBA/P mode → RGB
4. Upload original to GCS: img-cdn-bucket/original/{sourceId}.jpeg
5. For each rendition size:
   a. Resize using thumbnail() with LANCZOS resampling (maintains aspect ratio)
   b. Save as JPEG quality=90
   c. Upload to GCS: img-cdn-bucket/{size}/{sourceId}.jpeg
```

### 21.3 Rendition Sizes

| Size Name | Dimensions (max) | GCS Path |
|---|---|---|
| original | Source size | `original/{id}.jpeg` |
| fhd | 1920 x 1080 | `fhd/{id}.jpeg` |
| hd | 1280 x 720 | `hd/{id}.jpeg` |
| sd | 720 x 480 | `sd/{id}.jpeg` |
| low | 480 x 320 | `low/{id}.jpeg` |

### 21.4 Content-Type-Specific Behavior

| Content Type | On Download Failure | Dimension Validation | Default Images | Output Destination |
|---|---|---|---|---|
| `headlines` | Rejected (no defaults) | Disabled (commented out) | No | `NewRawHeadlinesIngestion_processed_data` / `_rejected_data` |
| `videos` | Use defaults, mark processed | `MIN_SHORT_EDGE=480`, `MIN_LONG_EDGE=720` | Yes (always pass with defaults) | `MRSSVideosIngestion_ProcessedData` (per record) |
| `summaries` | Use defaults, rename publisher to "Inside Media" | None | Yes (always pass with defaults) | `RawSummariesIngestion_ProcessedData` |
| Other | Use defaults, send Teams alert | None | Yes | No Pub/Sub (CDN only) |

### 21.5 Default Category Images

| Category Folder | Max Random Number | Source Path |
|---|---|---|
| `latest_news` | 22 | `default/latest_news/{size}/latest_news_{1-22}.png` |
| All others | 10 | `default/{category}/{size}/{category}_{1-10}.png` |

**Category Map (21 entries):**
```
Agro→agro, Astrology→astrology, Auto→automobile, Business→business,
Money→business, Career→education, Entertainment→entertainment,
Movie Reviews→entertainment, Health→health, Corona→health,
National→india, Regional→india, World→international,
Top News→latest_news, Top Stories→latest_news, news→latest_news,
News→latest_news, Lifestyle→lifestyle, Fashion→lifestyle,
Sci & Tech→sci_and_tech, Sports→sports, cricket→cricket
```

### 21.6 Alerting

On image processing failure for "other" content types, a Microsoft Teams webhook alert is sent:
- **Webhook URL:** Office 365 Incoming Webhook (rilcloud.webhook.office.com)
- **Severity:** SEV-3
- **Card Format:** MessageCard with facts (Cloud Function name, Publisher, Error)

---

## 22. LLM Integration Architecture

### 22.1 Async Summarization (jionews-summarization-async)

| Attribute | Value |
|---|---|
| **Deployment** | Cloud Run (persistent Pub/Sub pull subscriber) |
| **Model** | `gemini-2.5-flash` |
| **Client** | `google.genai.Client(api_key=...)` |
| **Temperature** | 0 |
| **Tools** | `[{"url_context": {}}]` |
| **Thinking** | Disabled |
| **Max Retries** | 3 (exponential backoff: 2^attempt seconds on 503) |

**System Instruction:**
```
You are a senior news editor for a reputable, high-traffic digital news outlet.
Your responsibility is to generate publishable news content that is highly engaging,
editorially responsible, accurate, and ethical.
You act as a news editor/writer and summarize news articles accurately and concisely.
Do NOT include: reasoning, planning, steps, drafts, explanations,
notes, meta comments, chain-of-thought, or analysis.
Never exceed 15 words (must stay under 105 characters) for title and 45 words
(must stay under 105 characters) summary under any condition
If you cannot fit within the limits, rewrite and compress/expand while keeping meaning.
Make sure to generate the output in specified language
```

**User Prompt Template:**
```
Generate the following from the article below strictly in {language_name} language:

1) Engaging / Social Media Headline Title
   - Title length MUST be strictly between 6 to 18 words (must stay between 40 to 90 characters)
   - Must spark curiosity and sharing without being misleading
   - Must be accurate, ethical, and context-rich
   - Do not start the title with a city name

2) News Summary in {language_name} language
   - Summary length MUST be strictly between 45 to 60 words (must stay between 225 to 310 characters)
   - Focus on factual information, key developments, and outcomes

3) Compliance Score (0-100)

4) error_message (empty string if success)

Return STRICTLY valid, parsable JSON:
{ "title": "", "summary": "", "compliance_score": 0, "error_message": "" }
```

**Two-Pass Strategy:**
1. **Pass 1 (URL mode):** Sends `article_url` to Gemini. Gemini uses `url_context` tool to fetch the article.
2. **Pass 2 (Content fallback):** If Pass 1 returns access failure text, fetches article HTML via proxy service (`https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy`), then retries Gemini with raw content.

**Access Failure Detection Substrings:**
```
"unable to summarize", "unable to access", "unable to browse",
"could not be fetched", "could not be accessed", "url did not contain",
"i am unable to", "article unavailable", "provided article url",
"could not be browsed", "not retrievable", "please ensure the url",
"cannot access", "can't access", "content was not retrievable"
```

**JSON Parsing (3-stage):**
1. Direct `json.loads()`
2. Strip markdown code fences and retry
3. Extract first `{...}` block and retry

### 22.2 Sync Summarization (jionews-summarization)

| Attribute | Value |
|---|---|
| **Deployment** | FastAPI on Cloud Run |
| **Model** | `gemini-2.5-flash` (overridable per request) |
| **Summary Target** | 350-360 characters |
| **Proxy Timeout** | 45 seconds |
| **URL Failure Substrings** | Subset of async version (7 patterns) |

---

## 23. Redis Caching Architecture

### 23.1 Connection

| Attribute | Value |
|---|---|
| **Host** | `34.93.131.211` |
| **Port** | `6379` |
| **Username** | `default` |
| **Password** | `developpd` |
| **Connection URL** | `redis://default:developpd@34.93.131.211:6379` |

### 23.2 Sorted Sets

All deduplication uses Redis Sorted Sets (ZSets) with time-based expiration scores.

| Sorted Set Name | Pipeline | Key Format | TTL | Cleanup |
|---|---|---|---|---|
| `de_headlines_id_cache` | Headlines | `{link}_{category_id}_{language_id}` | 48h | `zremrangebyscore("-inf", now)` |
| `de_headlines_title_cache` | Headlines | `<normalized_title>` | 48h | Same |
| `de_summaries_cache` | Summaries | `<title>` | 48h | Same |
| `de_videos_id_cache` | YouTube Videos | `{video_id}_{category_id}_{language_id}` | 48h | Same |
| `de_mrss_videos_cache` | MRSS Videos | `{title}_{link}_{category_id}_{language_id}` | 48h | Same |
| `de_mrss_shorts_cache` | MRSS Shorts | `{title}_{link}_{category_id}_{language_id}` | 48h | Same |

### 23.3 Deduplication Pattern

```python
# Check existence
score = redis_client.zscore(set_name, compound_key)
if score is None:
    # New record — add with expiration score
    redis_client.zadd(set_name, {compound_key: current_timestamp + 172800})
    # Record passes through
else:
    # Duplicate — filter out

# Cleanup expired keys
redis_client.zremrangebyscore(set_name, "-inf", current_timestamp)
```

---

## 24. Error Handling & Alerting Patterns

### 24.1 Common Error Handling Patterns

| Pattern | Used By | Behavior |
|---|---|---|
| **BulkWriteError catch** | All PushToMongoDB functions | Catches `pymongo.errors.BulkWriteError`, logs `nInserted` count, continues (allows partial success) |
| **Per-record try/except** | All Process functions | Wraps individual record mapping in try/except, logs error, continues to next record |
| **MongoDB connection guards** | All MongoDB-connected functions | Catches `ServerSelectionTimeoutError`, `ConnectionFailure`, and generic `Exception` |
| **SSL verification disabled** | Most HTTP calls | `verify=False` with `InsecureRequestWarning` suppressed globally |
| **Always-acknowledge** | jionews-summarization-async | Pub/Sub messages always `ack()`'d even on processing errors to prevent infinite redelivery |

### 24.2 Alerting

| Channel | Trigger | Severity | Used By |
|---|---|---|---|
| Microsoft Teams Webhook | Image CDN processing failure (non-headline/video/summary content types) | SEV-3 | `newrawheadlinesingestion-imagecdn` |

### 24.3 Retry Patterns

| Component | Max Retries | Backoff | Trigger |
|---|---|---|---|
| Gemini API (async) | 3 | Exponential (2^attempt seconds) | HTTP 503 / overloaded errors |
| GCS copy (transcoder) | 3 | Fixed 2-second delay | Copy failure |
| CPP/SAAS API | 3 | Fixed 5-second delay | HTTP request failure |

### 24.4 Status Tracking

| Pipeline | Status Field | States |
|---|---|---|
| Native Videos (processing) | `processingStatus` | `processing` → `completed` / `failed` |
| Native Videos (transcoding) | `transcoderProcessingStatus` | `initiated` → `queued` → `submitting` → `submitted` → `completed` / `failed` |
| Native Shorts | `processingStatus` | `processing` → `completed` / `failed` |
| Summaries (LLM) | `reprocessingStatus` | `success` / `rejected` |
| JioBharat | `isSuccess` | `true` / `false` |

---
*End of AS-IS Architecture Specification*