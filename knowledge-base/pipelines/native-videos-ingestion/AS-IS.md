# Native Videos Ingestion -- AS-IS Process Document

## Current State Description

The Native Videos Ingestion pipeline ingests video content from three independent sources: a direct REST API for programmatic uploads, a web-based manual upload interface for YouTube videos, and an automated MRSS feed ingestion system. All sources converge at an image CDN processing step before final persistence to MongoDB.

## Source 1: JioNewsDENativeVideos (REST API) -- Current Flow

1. External client sends `POST /v1/de-native-video/upload/` with HTTP Basic Auth credentials.
2. Request contains multipart form data: video file, thumbnail image, and metadata JSON.
3. Video file validation: accepted extensions are `.mp4`, `.mov`, `.avi`.
4. Thumbnail validation: accepted extensions are `.jpg`, `.jpeg`, `.png`, `.webp`.
5. Publisher is hardcoded to "ANI" with ID `5001`. The `src` field is set to `"api"`.
6. Video file is uploaded to GCS at `hls_video_transcoder_storage_output_files/raw_videos/{source_id}.mp4`.
7. Metadata is published to Pub/Sub topic `NewRawHeadlinesIngestion_image_cdn`.
8. Image CDN function processes the thumbnail and publishes to `MRSSVideosIngestion_ProcessedData`.

## Source 2: yt-manual-upload (Web UI) -- Current Flow

1. User accesses the web UI at `GET /`.
2. UI loads metadata from local CSV files: `data/categories.csv`, `data/languages.csv`, `data/publishers.csv`.
3. User fills in video metadata and requests an upload URL via `POST /get_upload_url`.
4. Server generates a GCS V4 signed URL with a 300-second expiry for direct browser-to-GCS upload.
5. User optionally checks CDN availability via `POST /check_cdn`, which issues a `HEAD` request to `https://vcdn.jionews.com/raw_videos/{video_id}.mp4`.
6. User triggers the upload via `POST /upload`.
7. The `src` field is set to `"manual"`.
8. Metadata is published to Pub/Sub for downstream processing.

## Source 3: MRSS Feeds -- Current Flow

1. **mrssvideos-fetchfeedsdata** (Cloud Scheduler trigger):
   - Reads MRSS feed configuration from GCS at `de-raw-ingestion/videos/mrss_videos_feeds.csv`.
   - For each feed URL, fetches and parses the feed content using `ThreadPoolExecutor(100)`.
   - Feed IDs 49 and 50 (IANS): JSON response is parsed with `key='data'`.
   - All other feed IDs: JSON response is parsed with `key='items'`.
   - Publishes raw feed data to Pub/Sub topic `MRSSVideosIngestion_RawFeedsData`.

2. **mrssvideos-processvideos** (Pub/Sub trigger):
   - Receives raw feed data from `MRSSVideosIngestion_RawFeedsData`.
   - Queries Redis cache `de_mrss_videos_cache` using composite key `title_link_cat_lang` (TTL: 48h).
   - Applies publisher-specific filtering:
     - Publisher 7777/7778: Only accepts `videotype` values in `["vod", "long video", "video", "videos", "longvideo"]`.
     - Publisher 7782 (IANS): Extracts video URL from `record.get('video')`.
   - Sets `src: "publisher_mrss"`, `processingStatus: "processing"`, `isVideoMerged: false`.
   - Publishes to `NewRawHeadlinesIngestion_image_cdn` with `content_type="videos"`.

3. **mrssvideos-downloadvideos** (Pub/Sub trigger):
   - Downloads the video file via HTTP streaming to GCS.
   - Copies the downloaded file to `de_video_transcoder_input` bucket.
   - Implements 3 retries with a 2-second delay between attempts.
   - **Skips** records where `src="manual"` or `src="api"` (these sources handle their own uploads).
   - Updates MongoDB: `processingStatus` set to `"completed"`, `transcoderProcessingStatus` set to `"initiated"`.

4. **mrssvideos-pushtomongodb** (Pub/Sub trigger):
   - Receives processed records.
   - Inserts documents into MongoDB collection `ingestion-data.raw_videos_rss` using `insert_many(ordered=False)`.

## Convergence at Image CDN

All three sources publish to `NewRawHeadlinesIngestion_image_cdn`. When the image CDN function processes a record with `content_type="videos"`, it publishes to `MRSSVideosIngestion_ProcessedData` on a per-record basis.

## Current Limitations and Known Issues

| Issue | Impact | Severity |
|---|---|---|
| REST API publisher is hardcoded to "ANI" (5001) | Cannot ingest from other publishers via API without code change | Medium |
| GCS signed URL has only 300s expiry | Large video uploads may fail on slow connections | Medium |
| MRSS feed fetch uses 100 concurrent threads | May overwhelm publisher feed servers | Medium |
| `insert_many(ordered=False)` silently skips duplicate key errors | Duplicates are not logged or tracked | Low |
| Video download has only 3 retries with 2s delay | Persistent network issues cause permanent data loss | Medium |
| No centralized health check across all three sources | Difficult to monitor overall pipeline health | Low |
| Manual upload metadata comes from local CSVs, not a shared config | Category/language lists may drift from MRSS source | Low |

## Operational Characteristics

| Metric | Value |
|---|---|
| API port | 8080 |
| API auth | HTTP Basic Auth |
| Manual upload signed URL TTL | 300 seconds |
| MRSS fetch concurrency | 100 threads |
| MRSS download retries | 3 (2s delay) |
| MRSS dedup cache TTL | 48 hours |
| MongoDB write strategy | `insert_many(ordered=False)` |

## Integration Points

| System | Direction | Protocol | Purpose |
|---|---|---|---|
| External API clients | Inbound | HTTPS (REST) | Video upload (Source 1) |
| Browser (Web UI) | Inbound | HTTPS | Manual video upload (Source 2) |
| MRSS Feed servers | Inbound | HTTPS | Feed data (Source 3) |
| GCS (multiple buckets) | Bidirectional | GCS API | Video storage and config |
| Redis | Bidirectional | Redis protocol | MRSS deduplication |
| Pub/Sub (multiple topics) | Outbound | gRPC | Inter-function messaging |
| MongoDB Atlas | Outbound | MongoDB wire protocol | Persistent storage |
| vcdn.jionews.com | Outbound | HTTPS HEAD | CDN availability check |
| Image CDN pipeline | Outbound | Pub/Sub | Thumbnail processing |
| Secret Manager | Inbound | GCP API | Credentials retrieval |
