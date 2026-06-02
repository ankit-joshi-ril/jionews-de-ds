# YouTube Shorts Ingestion Pipeline

## Pipeline Identity

| Field | Value |
|---|---|
| **Pipeline Name** | YouTube Shorts Ingestion |
| **Pipeline ID** | `youtube-shorts-ingestion` |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |
| **Domain** | Data Engineering - Content Ingestion |
| **Content Type** | YouTube Shorts (vertical video, <=60s) |
| **Output Collection** | `ingestion-data.raw_short_videos_ingestion_data` |

## Purpose

This pipeline discovers and ingests YouTube Shorts metadata from a curated list of publisher channels. It scrapes YouTube channel pages to find new short video IDs, validates them against the YouTube Data API v3, and stores qualified records in MongoDB for downstream consumption by editorial and recommendation systems.

## Pipeline Overview

The pipeline operates as a two-stage Cloud Function chain triggered by Cloud Scheduler on a cron schedule:

1. **Stage 1 (ScrapeVideoIds):** Reads a publisher list from GCS, scrapes each channel's `/shorts` page, extracts video IDs via HTML parsing, deduplicates against MongoDB, and publishes new IDs to Pub/Sub.
2. **Stage 2 (YouTubeAPIToMongoDB):** Receives video IDs from Pub/Sub, enriches them via YouTube Data API v3, validates duration and recency constraints, and inserts qualified records into MongoDB.

## Key Characteristics

- **Trigger:** Cloud Scheduler (HTTP) on a recurring cron schedule
- **Execution Model:** Two sequential Cloud Functions connected via Pub/Sub
- **Data Flow:** GCS (publisher list) -> Web Scraping -> YouTube API -> MongoDB
- **Deduplication:** MongoDB aggregation query on `sourceVideoId` field
- **Validation Gates:** Duration (0-60s), URL redirect check (must be a Short), 24-hour recency filter
- **Output Format:** Standardized video metadata documents with portrait orientation defaults

## Infrastructure Components

| Component | Type | Name/Identifier |
|---|---|---|
| Cloud Function 1 | HTTP-triggered | ScrapeVideoIds |
| Cloud Function 2 | Pub/Sub-triggered | YouTubeAPIToMongoDB |
| Cloud Scheduler | Cron trigger | Triggers ScrapeVideoIds via HTTP |
| Pub/Sub Topic (internal) | Message bus | `cron_based_raw_youtube_shorts_ingestion` |
| Pub/Sub Topic (output) | Message bus | `raw_youtube_shorts_ingestion` |
| GCS Bucket | Config storage | `de-raw-ingestion` |
| MongoDB Database | Data store | `ingestion-data` |
| Secret Manager | Credentials | `mongosh_de_uri`, `yt_api_access_token` |

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
| GCS `de-raw-ingestion/shorts/shorts_publishers.csv` | Configuration | Publisher channel list (CSV, ISO-8859-1 encoded) |
| YouTube website | External | Channel `/shorts` pages for scraping |
| YouTube Data API v3 | External API | Video metadata enrichment |
| MongoDB `ingestion-data` | Database | Deduplication lookups and record storage |

## Downstream Consumers

| Consumer | Interface | Description |
|---|---|---|
| Downstream processing pipelines | Pub/Sub `raw_youtube_shorts_ingestion` | Receives enriched short video records |
| Editorial/Recommendation systems | MongoDB reads | Queries `raw_short_videos_ingestion_data` collection |
