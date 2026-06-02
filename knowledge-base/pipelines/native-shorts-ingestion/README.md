# Native Shorts Ingestion Pipeline

## Pipeline Identity

| Field | Value |
|---|---|
| **Pipeline Name** | Native Shorts Ingestion |
| **Pipeline ID** | `native-shorts-ingestion` |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |
| **Domain** | Data Engineering - Content Ingestion |
| **Content Type** | Native Shorts (vertical video, portrait orientation) |
| **Output Collection** | `ingestion-data.raw_videos_rss` (shared with Native Videos, differentiated by `contentType`) |

## Purpose

This pipeline ingests short-form vertical video content from three distinct native sources into a unified MongoDB collection. It handles JioNews direct uploads, YouTube manual uploads repackaged for the platform, and MRSS (Media RSS) feed-based shorts from external publishers. All three sources converge on the same output collection with `contentType="shorts"` to distinguish them from native video content.

## Pipeline Overview

The pipeline has three independent source paths that all write to the same MongoDB collection:

1. **Source 1 - JioNewsDENativeVideos:** Shared Cloud Function that tags incoming content as Shorts based on editorial metadata. Sets `contentType="shorts"`.
2. **Source 2 - yt-manual-upload:** Shared Cloud Function that processes manually uploaded YouTube content for the platform. Uses `oar2.jpg` as the thumbnail source. Sets `contentType="shorts"`.
3. **Source 3 - MRSS Feeds (Dedicated Shorts Pipeline):** A three-stage Cloud Function pipeline that fetches, processes, and downloads short videos from external publisher MRSS feeds.

## MRSS Shorts Pipeline Stages

| Stage | Cloud Function | Trigger | Description |
|---|---|---|---|
| 1 | `mrssshorts-fetchfeedsdata` | Scheduler/HTTP | Fetches raw feed data from publisher MRSS endpoints |
| 2 | `mrssshorts-processvideos` | Pub/Sub | Deduplicates, validates, and transforms feed records |
| 3 | `mrssshorts-downloadvideos` | Pub/Sub | Downloads video files to GCS (no transcoding) |

## Key Characteristics

- **Multi-Source Convergence:** Three independent sources write to the same MongoDB collection
- **Shared Collection:** `raw_videos_rss` is shared with Native Videos pipeline; differentiated by `contentType` field
- **No Transcoding:** Unlike native videos, shorts skip the transcoding step and serve raw MP4 files directly
- **Portrait Orientation:** All shorts are tagged with `sourceVideoOrientation="portrait"`
- **Redis Deduplication:** MRSS source uses Redis cache (`de_mrss_shorts_cache`) with 48-hour TTL
- **Concurrent Feed Fetching:** `ThreadPoolExecutor(100)` for parallel MRSS feed retrieval

## Key Differences from Native Videos Pipeline

| Aspect | Native Shorts | Native Videos |
|---|---|---|
| `contentType` | `"shorts"` | `"videos"` |
| `sourceVideoOrientation` | `"portrait"` | `"landscape"` |
| Transcoding | None (raw MP4) | Yes (HLS transcoding) |
| Redis cache key | `de_mrss_shorts_cache` | `de_mrss_videos_cache` |
| Default image range | 1-5 | 1-10 |
| Pub/Sub prefix | `MRSSShortsIngestion_*` | `MRSSVideosIngestion_*` |
| videotype filter values | `"shorts"`, `"short"`, `"short video"`, `"shortvideo"` | `"video"`, `"videos"`, etc. |

## Infrastructure Components

| Component | Type | Name/Identifier |
|---|---|---|
| Cloud Function (shared) | Pub/Sub-triggered | JioNewsDENativeVideos |
| Cloud Function (shared) | Pub/Sub-triggered | yt-manual-upload |
| Cloud Function | HTTP/Scheduler | mrssshorts-fetchfeedsdata |
| Cloud Function | Pub/Sub-triggered | mrssshorts-processvideos |
| Cloud Function | Pub/Sub-triggered | mrssshorts-downloadvideos |
| Pub/Sub Topic | Message bus | `MRSSShortsIngestion_RawFeedsData` |
| Pub/Sub Topic | Message bus | `MRSSShortsIngestion_ProcessedData` |
| Pub/Sub Topic | Image processing | `NewRawHeadlinesIngestion_image_cdn` |
| GCS Bucket | Config | `de-raw-ingestion` |
| GCS Bucket | Video storage | `hls_video_transcoder_storage_output_files` |
| Redis | Dedup cache | `de_mrss_shorts_cache` |
| MongoDB Database | Data store | `ingestion-data` |

## Quick Links

| Document | Description |
|---|---|
| [AS-IS.md](./AS-IS.md) | Current operational state and known issues |
| [DATA-SPEC.md](./DATA-SPEC.md) | Input/output data specifications and schemas |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System architecture with Mermaid diagrams |
| [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) | MongoDB collection schemas and indexes |
| [TECH-SPEC.md](./TECH-SPEC.md) | Technical implementation details |

## Upstream Dependencies

| Dependency | Type | Description |
|---|---|---|
| GCS `de-raw-ingestion/shorts/mrss_shorts_feeds.csv` | Configuration | MRSS feed endpoint list |
| External MRSS publisher feeds | External API | JSON/XML feeds from content publishers |
| Redis `de_mrss_shorts_cache` | Cache | Deduplication cache with 48h TTL |
| JioNews editorial uploads | Internal | Direct video uploads via JioNewsDENativeVideos |
| YouTube manual uploads | Internal | Repackaged YouTube content via yt-manual-upload |

## Downstream Consumers

| Consumer | Interface | Description |
|---|---|---|
| Image CDN pipeline | Pub/Sub `NewRawHeadlinesIngestion_image_cdn` | Processes thumbnail images |
| Content delivery | GCS `hls_video_transcoder_storage_output_files/raw_videos/` | Raw MP4 served via CDN |
| Editorial/Recommendation | MongoDB `raw_videos_rss` queries | Content discovery and curation |
