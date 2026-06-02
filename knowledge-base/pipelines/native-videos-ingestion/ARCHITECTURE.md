# Native Videos Ingestion -- Architecture Document

## System Context

The Native Videos Ingestion pipeline consists of three independent ingestion sources that converge at a shared image CDN processing step. It runs on Google Cloud Platform (project: `jiox-328108`) using a combination of Cloud Functions, Cloud Run/App Engine services, and event-driven Pub/Sub messaging.

## High-Level Architecture

```mermaid
flowchart TB
    subgraph "Source 1: REST API"
        API[JioNewsDENativeVideos<br>Flask API :8080]
    end

    subgraph "Source 2: Manual Upload"
        UI[yt-manual-upload<br>Flask Web UI :8080]
    end

    subgraph "Source 3: MRSS Feeds"
        SCHED[Cloud Scheduler]
        FF[mrssvideos-fetchfeedsdata]
        PV[mrssvideos-processvideos]
        DV[mrssvideos-downloadvideos]
        PM[mrssvideos-pushtomongodb]
    end

    subgraph "Shared Processing"
        ICDN[imagecdn Function]
    end

    subgraph "Data Stores"
        GCS1[(GCS: hls_video_transcoder_storage_output_files)]
        GCS2[(GCS: de-raw-ingestion)]
        GCS3[(GCS: de_video_transcoder_input)]
        GCS4[(GCS: img-cdn-bucket)]
        Redis[(Redis: de_mrss_videos_cache)]
        MongoDB[(MongoDB: raw_videos_rss)]
    end

    subgraph "Pub/Sub Topics"
        PS_IMG[NewRawHeadlinesIngestion_image_cdn]
        PS_RAW[MRSSVideosIngestion_RawFeedsData]
        PS_PROC[MRSSVideosIngestion_ProcessedData]
    end

    subgraph "External"
        CLIENT[API Client]
        BROWSER[Browser]
        FEEDS[MRSS Feed Servers]
        CDN[vcdn.jionews.com]
    end

    CLIENT -->|POST /v1/de-native-video/upload/| API
    API -->|Upload video| GCS1
    API -->|Publish| PS_IMG

    BROWSER -->|Web UI| UI
    UI -->|Signed URL upload| GCS1
    UI -->|Check CDN| CDN
    UI -->|Publish| PS_IMG

    SCHED -->|Trigger| FF
    FF -->|Read config| GCS2
    FF -->|Fetch feeds| FEEDS
    FF -->|Publish| PS_RAW
    PS_RAW -->|Trigger| PV
    PV -->|Dedup| Redis
    PV -->|Publish| PS_IMG
    PS_IMG -->|Trigger| ICDN
    ICDN -->|Process thumbnails| GCS4
    ICDN -->|"Publish (content_type=videos)"| PS_PROC
    PS_PROC -->|Trigger| DV
    DV -->|Download video| GCS1
    DV -->|Copy to transcoder| GCS3
    DV -->|Update status| MongoDB
    PS_PROC -->|Trigger| PM
    PM -->|insert_many| MongoDB
```

## Source 1: REST API Sequence

```mermaid
sequenceDiagram
    participant Client as API Client
    participant API as JioNewsDENativeVideos
    participant GCS as GCS (raw_videos/)
    participant PS as Pub/Sub: image_cdn
    participant ICDN as imagecdn
    participant PS2 as Pub/Sub: ProcessedData

    Client->>API: POST /v1/de-native-video/upload/<br>(Basic Auth, multipart)
    API->>API: Validate video (.mp4/.mov/.avi)
    API->>API: Validate thumbnail (.jpg/.jpeg/.png/.webp)
    API->>API: Set publisher=ANI (5001), src=api
    API->>GCS: Upload {source_id}.mp4
    GCS-->>API: Upload confirmed
    API->>PS: Publish metadata (content_type=videos)
    PS->>ICDN: Trigger
    ICDN->>ICDN: Process thumbnail
    ICDN->>PS2: Publish per record
    API-->>Client: 200 OK
```

## Source 2: Manual Upload Sequence

```mermaid
sequenceDiagram
    participant User as Browser
    participant App as yt-manual-upload
    participant GCS as GCS (raw_videos/)
    participant CDN as vcdn.jionews.com
    participant PS as Pub/Sub: image_cdn

    User->>App: GET / (load web UI)
    App-->>User: HTML form
    User->>App: GET /metadata
    App->>App: Read local CSVs (categories, languages, publishers)
    App-->>User: Metadata JSON

    User->>App: POST /get_upload_url
    App->>GCS: Generate V4 signed URL (300s TTL)
    GCS-->>App: Signed URL
    App-->>User: Signed URL

    User->>GCS: Direct upload via signed URL
    GCS-->>User: Upload confirmed

    User->>App: POST /check_cdn
    App->>CDN: HEAD https://vcdn.jionews.com/raw_videos/{video_id}.mp4
    CDN-->>App: 200 OK / 404
    App-->>User: CDN status

    User->>App: POST /upload (metadata, src=manual)
    App->>PS: Publish metadata
    App-->>User: 200 OK
```

## Source 3: MRSS Feeds Sequence

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant FF as fetchfeedsdata
    participant GCS as GCS Config
    participant Feeds as MRSS Feeds
    participant PS1 as Pub/Sub: RawFeedsData
    participant PV as processvideos
    participant Redis as Redis Cache
    participant PS2 as Pub/Sub: image_cdn
    participant ICDN as imagecdn
    participant PS3 as Pub/Sub: ProcessedData
    participant DV as downloadvideos
    participant GCS2 as GCS (raw_videos)
    participant GCS3 as GCS (transcoder_input)
    participant PM as pushtomongodb
    participant Mongo as MongoDB

    CS->>FF: Trigger
    FF->>GCS: Read mrss_videos_feeds.csv
    GCS-->>FF: Feed config

    loop Each feed (ThreadPoolExecutor max=100)
        FF->>Feeds: Fetch feed data
        Feeds-->>FF: JSON response
        FF->>FF: Parse with key='data' (IDs 49/50) or key='items'
    end

    FF->>PS1: Publish raw feed data
    PS1->>PV: Trigger

    loop Each record
        PV->>Redis: Check key: title_link_cat_lang
        Redis-->>PV: Exists / Not exists

        alt New record
            PV->>Redis: Set key (48h TTL)
            PV->>PV: Apply publisher filters (7777/7778 videotype, 7782 video URL)
            PV->>PV: Set src=publisher_mrss, processingStatus=processing
            PV->>PS2: Publish (content_type=videos)
        end
    end

    PS2->>ICDN: Trigger
    ICDN->>PS3: Publish per record

    PS3->>DV: Trigger
    DV->>DV: Check src != manual and src != api

    loop Download (3 retries, 2s delay)
        DV->>GCS2: Stream download video
    end

    DV->>GCS3: Copy to transcoder input
    DV->>Mongo: Update processingStatus=completed, transcoderProcessingStatus=initiated

    PS3->>PM: Trigger
    PM->>Mongo: insert_many(ordered=False)
```

## Source Convergence Diagram

```mermaid
flowchart LR
    subgraph Sources
        S1[REST API<br>src=api]
        S2[Manual Upload<br>src=manual]
        S3[MRSS Feeds<br>src=publisher_mrss]
    end

    S1 --> ICDN[imagecdn<br>content_type=videos]
    S2 --> ICDN
    S3 --> ICDN

    ICDN --> PS[Pub/Sub:<br>MRSSVideosIngestion_ProcessedData]

    PS --> DV[mrssvideos-downloadvideos]
    PS --> PM[mrssvideos-pushtomongodb]

    DV -->|"Skip if src=manual or src=api"| GCS[(GCS)]
    DV --> Mongo[(MongoDB)]
    PM --> Mongo
```

## Infrastructure Dependencies

| Resource | Type | Identifier |
|---|---|---|
| GCP Project | Project | `jiox-328108` (266686822828) |
| GCS Bucket | Storage | `de-raw-ingestion` |
| GCS Bucket | Storage | `hls_video_transcoder_storage_output_files` |
| GCS Bucket | Storage | `de_video_transcoder_input` |
| GCS Bucket | Storage | `img-cdn-bucket` |
| Pub/Sub Topic | Messaging | `NewRawHeadlinesIngestion_image_cdn` |
| Pub/Sub Topic | Messaging | `MRSSVideosIngestion_RawFeedsData` |
| Pub/Sub Topic | Messaging | `MRSSVideosIngestion_ProcessedData` |
| Redis Instance | Cache | `de_mrss_videos_cache` |
| MongoDB Collection | Database | `ingestion-data.raw_videos_rss` |
| Secret Manager | Secrets | `mongosh_de_uri` |
| Secret Manager | Secrets | `compute_engine_service_account_private_key` |

## Security Architecture

| Component | Auth Mechanism |
|---|---|
| REST API (Source 1) | HTTP Basic Authentication |
| Manual Upload (Source 2) | GCS V4 signed URLs (300s expiry) |
| MRSS Feeds (Source 3) | None (public feeds) |
| MongoDB | Connection URI from Secret Manager (`mongosh_de_uri`) |
| GCS Signed URLs | Service account key from Secret Manager |
| Inter-function | GCP IAM (Pub/Sub push/pull permissions) |
