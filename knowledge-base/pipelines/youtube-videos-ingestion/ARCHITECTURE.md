# YouTube Videos Ingestion -- Architecture Document

## System Context

The YouTube Videos Ingestion pipeline is a serverless, event-driven system running on Google Cloud Platform (project: `jiox-328108`). It discovers new video content from YouTube channels via HTML scraping and routes processed metadata through Pub/Sub for downstream consumption and persistence.

## High-Level Architecture

```mermaid
flowchart TB
    subgraph Trigger
        CS[Cloud Scheduler]
    end

    subgraph "Cloud Functions"
        CF1[FetchYTChannelsData]
        CF2[ProcessYTChannelsData]
        CF3[PushToMongoDB]
    end

    subgraph "Data Stores"
        GCS[(GCS: de-raw-ingestion)]
        Redis[(Redis: de_videos_id_cache)]
        MongoDB[(MongoDB: raw_videos_ingestion_data)]
    end

    subgraph "Pub/Sub Topics"
        PS1[NewRawVideosIngestion_publishers_channel_data]
        PS2[NewRawVideosIngestion_processed_data]
        PS3[NewRawYoutubeScraper_metadata]
    end

    subgraph External
        YT[YouTube Channel Pages]
        VCDN[vcdn.jionews.com]
    end

    CS -->|HTTP| CF1
    CF1 -->|Read config CSV| GCS
    CF1 -->|Scrape HTML| YT
    CF1 -->|Publish| PS1
    PS1 -->|Background trigger| CF2
    CF2 -->|Dedup check| Redis
    CF2 -->|"Batch publish (to_scrape=False)"| PS2
    CF2 -->|"Per-record publish (to_scrape=True)"| PS3
    PS3 -->|CloudEvent trigger| CF3
    CF3 -->|Insert| MongoDB
    CF2 -.->|HLS URLs reference| VCDN
```

## Detailed Sequence Flow

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant CF1 as FetchYTChannelsData
    participant GCS as GCS Config
    participant YT as YouTube
    participant PS1 as Pub/Sub: publishers_channel_data
    participant CF2 as ProcessYTChannelsData
    participant Redis as Redis Cache
    participant PS2 as Pub/Sub: processed_data
    participant PS3 as Pub/Sub: scraper_metadata
    participant CF3 as PushToMongoDB
    participant Mongo as MongoDB

    CS->>CF1: HTTP trigger
    CF1->>GCS: Read videos_publishers_config.csv (ISO-8859-1)
    GCS-->>CF1: Publisher config rows

    loop Each channel (ThreadPoolExecutor max=10)
        CF1->>YT: GET /channel/{channel_id}/videos (5s timeout)
        YT-->>CF1: HTML page
        CF1->>CF1: BeautifulSoup parse -> ytInitialData -> $..videoRenderer
    end

    CF1->>PS1: Publish scraped channel data

    PS1->>CF2: Background trigger (per message)

    loop Each video record (ThreadPoolExecutor max=50)
        CF2->>CF2: Extract video_id, title, published_time, duration, orientation
        CF2->>CF2: Apply 24h recency filter
        CF2->>Redis: Check key: video_id_cat_lang
        Redis-->>CF2: Exists / Not exists

        alt Not in cache (new video)
            CF2->>Redis: Set key with 48h TTL

            alt to_scrape = False
                CF2->>PS2: Batch publish processed data
            else to_scrape = True
                CF2->>PS3: Per-record publish with HLS URLs
            end
        else In cache (duplicate)
            CF2->>CF2: Skip record
        end
    end

    PS3->>CF3: CloudEvent trigger
    CF3->>Mongo: Insert into raw_videos_ingestion_data
```

## to_scrape Branching Logic

```mermaid
flowchart TD
    A[Processed Video Record] --> B{to_scrape?}
    B -->|False| C[Batch publish to<br>NewRawVideosIngestion_processed_data]
    B -->|True| D[Attach HLS manifest URLs<br>from vcdn.jionews.com]
    D --> E[Per-record publish to<br>NewRawYoutubeScraper_metadata]
    E --> F[PushToMongoDB via CloudEvent]
    F --> G[(MongoDB: raw_videos_ingestion_data)]
    C --> H[Downstream consumers]
```

## Component Details

### FetchYTChannelsData

| Attribute | Value |
|---|---|
| Trigger | HTTP (Cloud Scheduler) |
| Entry point | `main(req_ph, req_ph2)` |
| Concurrency model | `ThreadPoolExecutor(max_workers=10)` |
| External dependency | YouTube public web pages |
| Output | Pub/Sub: `NewRawVideosIngestion_publishers_channel_data` |

### ProcessYTChannelsData

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub background |
| Entry point | `main(message, context)` |
| Concurrency model | `ThreadPoolExecutor(max_workers=50)` |
| External dependency | Redis for deduplication |
| Output | Pub/Sub: `NewRawVideosIngestion_processed_data` or `NewRawYoutubeScraper_metadata` |

### PushToMongoDB

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub CloudEvent |
| Entry point | `write_to_mongodb(cloud_event)` |
| External dependency | MongoDB Atlas |
| Output | MongoDB document insert |

## Infrastructure Dependencies

| Resource | Type | Identifier |
|---|---|---|
| GCP Project | Project | `jiox-328108` (266686822828) |
| GCS Bucket | Storage | `de-raw-ingestion` |
| Pub/Sub Topic | Messaging | `NewRawVideosIngestion_publishers_channel_data` |
| Pub/Sub Topic | Messaging | `NewRawVideosIngestion_processed_data` |
| Pub/Sub Topic | Messaging | `NewRawYoutubeScraper_metadata` |
| Redis Instance | Cache | `de_videos_id_cache` |
| MongoDB Collection | Database | `ingestion-data.raw_videos_ingestion_data` |

## Scalability Considerations

- Thread pool sizes (10 for fetch, 50 for process) are hardcoded and bound by Cloud Function instance memory/CPU.
- Each Pub/Sub message triggers an independent function invocation, providing horizontal scale at the message level.
- Redis deduplication is the primary bottleneck for concurrent writes (single-threaded Redis model).
- YouTube scraping is rate-limited by the 5-second timeout and potential IP-based throttling from YouTube.
