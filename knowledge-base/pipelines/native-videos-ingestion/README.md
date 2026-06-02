# Native Videos Ingestion Pipeline

## Overview

The Native Videos Ingestion pipeline handles video content from three independent sources that converge into a unified processing flow. It supports direct API uploads, manual YouTube video uploads via a web UI, and automated MRSS (Media RSS) feed ingestion. All sources ultimately persist to MongoDB and route through an image CDN processing step.

## Pipeline Identity

| Attribute | Value |
|---|---|
| Pipeline Name | Native Videos Ingestion |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Runtime | Python (Cloud Functions + Cloud Run / App Engine) |
| Data Store | MongoDB (`ingestion-data.raw_videos_rss`) |
| Cache | Redis (`de_mrss_videos_cache`, TTL 48h) |
| Sources | REST API, Web UI, MRSS Feeds |

## Source Architecture

### Source 1: JioNewsDENativeVideos (REST API)

| Attribute | Value |
|---|---|
| Type | Flask REST API |
| Port | 8080 |
| Auth | HTTP Basic Authentication |
| Endpoint | `POST /v1/de-native-video/upload/` |
| Publisher | Hardcoded: "ANI" (ID: `5001`), `src: "api"` |
| Accepts | Multipart: video (.mp4/.mov/.avi) + thumbnail (.jpg/.jpeg/.png/.webp) + metadata JSON |
| Storage | GCS: `hls_video_transcoder_storage_output_files/raw_videos/{source_id}.mp4` |
| Output | Pub/Sub: `NewRawHeadlinesIngestion_image_cdn` |

### Source 2: yt-manual-upload (Web UI + REST API)

| Attribute | Value |
|---|---|
| Type | Flask Web UI + REST API |
| Port | 8080 |
| Source marker | `src: "manual"` |
| Endpoints | `GET /` (UI), `GET /metadata`, `POST /get_upload_url`, `POST /check_cdn`, `POST /upload` |
| CDN Check | `HEAD https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| Upload mechanism | GCS V4 signed URL (300s expiry) |
| Metadata | Local CSVs: `data/categories.csv`, `data/languages.csv`, `data/publishers.csv` |

### Source 3: MRSS Feeds (Automated)

| Attribute | Value |
|---|---|
| Type | 4 Cloud Functions (event-driven chain) |
| Config | GCS: `de-raw-ingestion/videos/mrss_videos_feeds.csv` |
| Cache | Redis: `de_mrss_videos_cache` (key: `title_link_cat_lang`, TTL 48h) |
| Source marker | `src: "publisher_mrss"` |
| MongoDB | `ingestion-data.raw_videos_rss` |

MRSS Function Chain:

| Order | Function | Trigger | Purpose |
|---|---|---|---|
| 1 | `mrssvideos-fetchfeedsdata` | Cloud Scheduler | Fetch MRSS feed URLs from config, parse feeds |
| 2 | `mrssvideos-processvideos` | Pub/Sub | Deduplicate, validate, enrich records |
| 3 | `mrssvideos-downloadvideos` | Pub/Sub | Download video files to GCS |
| 4 | `mrssvideos-pushtomongodb` | Pub/Sub | Persist to MongoDB |

## Convergence Point

All three sources converge at the `imagecdn` processing step, which publishes to `MRSSVideosIngestion_ProcessedData` per record when `content_type="videos"`.

## Key Reference Data

### Category Map (ID to Name)

| ID | Category |
|---|---|
| 3 | entertainment |
| 5 | fashion |
| 8 | health |
| 9 | food |
| 10 | automotive |
| 11 | travel |
| 12 | sports |
| 13 | news |
| 14 | technology |
| 17 | business |
| 18 | cricket |
| 20 | spiritual |
| 22 | astrology |
| 26 | Career |

### Language Map (ID to Name)

| ID | Language |
|---|---|
| 1 | English |
| 2 | Hindi |
| 3 | Marathi |
| 4 | Gujarati |
| 6 | Malayalam |
| 7 | Tamil |
| 8 | Urdu |
| 9 | Kannada |
| 10 | Punjabi |
| 11 | Telugu |
| 13 | Bangla |
| 18 | Odia |
| 19 | Assamese |

## GCS Buckets

| Bucket | Purpose |
|---|---|
| `de-raw-ingestion` | MRSS feed configuration |
| `hls_video_transcoder_storage_output_files` | Raw video storage (`raw_videos/` prefix) |
| `de_video_transcoder_input` | Transcoder input staging |
| `img-cdn-bucket` | Image CDN assets |

## Secrets (Secret Manager)

| Secret Name | Purpose |
|---|---|
| `mongosh_de_uri` | MongoDB connection URI |
| `compute_engine_service_account_private_key` | Service account key for GCS signed URLs |

## Related Pipelines

- Downstream: Video Transcoder Workflow (videos copied to `de_video_transcoder_input`)
- Downstream: RSS Feed Generation (via processed data topics)
- Shared: Image CDN pipeline (`NewRawHeadlinesIngestion_image_cdn`)
