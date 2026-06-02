# YouTube Videos Ingestion Pipeline

## Overview

The YouTube Videos Ingestion pipeline scrapes public YouTube channel pages to discover and ingest new video metadata into the JioNews content ecosystem. It operates as a scheduled, event-driven pipeline built on three Google Cloud Functions connected via Pub/Sub topics.

## Pipeline Identity

| Attribute | Value |
|---|---|
| Pipeline Name | YouTube Videos Ingestion |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Trigger | Cloud Scheduler (HTTP) |
| Runtime | Python (Cloud Functions Gen1/Gen2) |
| Data Store | MongoDB (`ingestion-data.raw_videos_ingestion_data`) |
| Cache | Redis (`de_videos_id_cache`, TTL 48h) |
| Source | Public YouTube channel pages (HTML scraping) |

## Function Chain

| Order | Cloud Function | Trigger | Output |
|---|---|---|---|
| 1 | `FetchYTChannelsData` | Cloud Scheduler (HTTP) | Pub/Sub: `NewRawVideosIngestion_publishers_channel_data` |
| 2 | `ProcessYTChannelsData` | Pub/Sub (background) | Pub/Sub: `NewRawVideosIngestion_processed_data` or `NewRawYoutubeScraper_metadata` |
| 3 | `PushToMongoDB` | Pub/Sub (CloudEvent) | MongoDB write |

## Key Behaviors

- Scrapes YouTube channel `/videos` pages using BeautifulSoup to extract `ytInitialData` JSON.
- Uses JSONPath `$..videoRenderer` to locate video metadata within the YouTube initial data payload.
- Applies a 24-hour recency filter to only ingest recently published videos.
- Uses Redis deduplication with a composite key `video_id_cat_lang` and a 48-hour TTL.
- Branches on `to_scrape` flag: `False` publishes in batch to `NewRawVideosIngestion_processed_data`; `True` publishes per-record to `NewRawYoutubeScraper_metadata` with HLS manifest URLs.
- Concurrent execution: `ThreadPoolExecutor(10)` for fetch, `ThreadPoolExecutor(50)` for processing.

## Configuration

- Publisher channel list: GCS `de-raw-ingestion/videos/videos_publishers_config.csv` (ISO-8859-1 encoding).
- YouTube thumbnail URL pattern: `https://i.ytimg.com/vi/{video_id}/{size}.jpg`
  - `default`: 120x90
  - `mqdefault`: 320x180
  - `hqdefault`: 480x360
  - `sddefault`: 640x480
  - `maxresdefault`: 1280x720

## Entry Points

| Function | Signature | Trigger Type |
|---|---|---|
| FetchYTChannelsData | `main(req_ph, req_ph2)` | HTTP |
| ProcessYTChannelsData | `main(message, context)` | Pub/Sub background |
| PushToMongoDB | `write_to_mongodb(cloud_event)` | CloudEvent |

## Dependencies

- Google Cloud Storage (publisher config CSV)
- Google Cloud Pub/Sub (3 topics)
- MongoDB Atlas (final persistence)
- Redis (deduplication cache)
- BeautifulSoup4 (HTML parsing)
- YouTube public web pages (data source)

## Related Pipelines

- Downstream: Video Transcoder Workflow (for `to_scrape=True` videos with HLS)
- Downstream: RSS Feed Generation (via `NewRawVideosIngestion_processed_data`)
