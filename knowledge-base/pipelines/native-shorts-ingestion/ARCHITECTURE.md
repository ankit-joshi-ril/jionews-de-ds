# Native Shorts Ingestion - Architecture

## System Context Diagram

```mermaid
flowchart LR
    subgraph "Source 1: Editorial"
        ED_UPLOAD["JioNews Editorial\nUploads"]
    end

    subgraph "Source 2: YouTube Manual"
        YT_MANUAL["YouTube Manual\nUploads"]
    end

    subgraph "Source 3: MRSS Feeds"
        MRSS_FEEDS["External Publisher\nMRSS Endpoints"]
    end

    subgraph "GCP Project: jiox-328108"
        CF_NATIVE["Cloud Function:\nJioNewsDENativeVideos\n(shared)"]
        CF_YTMAN["Cloud Function:\nyt-manual-upload\n(shared)"]
        CF_FETCH["Cloud Function:\nmrssshorts-fetchfeedsdata"]
        CF_PROC["Cloud Function:\nmrssshorts-processvideos"]
        CF_DL["Cloud Function:\nmrssshorts-downloadvideos"]
        PS_RAW["Pub/Sub:\nMRSSShortsIngestion_\nRawFeedsData"]
        PS_PROC["Pub/Sub:\nMRSSShortsIngestion_\nProcessedData"]
        PS_IMG["Pub/Sub:\nNewRawHeadlinesIngestion_\nimage_cdn"]
        GCS_CFG["GCS:\nde-raw-ingestion/shorts/\nmrss_shorts_feeds.csv"]
        GCS_VID["GCS:\nhls_video_transcoder_\nstorage_output_files/\nraw_videos/"]
        REDIS["Redis:\nde_mrss_shorts_cache"]
    end

    subgraph "Data Store"
        MONGO["MongoDB:\ningestion-data.\nraw_videos_rss"]
    end

    ED_UPLOAD --> CF_NATIVE
    YT_MANUAL --> CF_YTMAN
    CF_NATIVE -->|"contentType=shorts"| MONGO
    CF_YTMAN -->|"contentType=shorts"| MONGO

    GCS_CFG --> CF_FETCH
    CF_FETCH --> MRSS_FEEDS
    CF_FETCH --> PS_RAW
    PS_RAW --> CF_PROC
    CF_PROC --> REDIS
    CF_PROC --> MONGO
    CF_PROC --> PS_IMG
    CF_PROC --> PS_PROC
    PS_PROC --> CF_DL
    CF_DL --> GCS_VID
    CF_DL --> MONGO
```

## MRSS Shorts Pipeline - Detailed Sequence

```mermaid
sequenceDiagram
    participant SCHED as Cloud Scheduler
    participant CF1 as mrssshorts-fetchfeedsdata
    participant GCS_CFG as GCS (Feed CSV)
    participant FEEDS as MRSS Publisher Feeds
    participant PS1 as Pub/Sub (RawFeedsData)
    participant CF2 as mrssshorts-processvideos
    participant REDIS as Redis Cache
    participant MONGO as MongoDB
    participant PS_IMG as Pub/Sub (image_cdn)
    participant PS2 as Pub/Sub (ProcessedData)
    participant CF3 as mrssshorts-downloadvideos
    participant GCS_VID as GCS (raw_videos)

    Note over SCHED,GCS_VID: Stage 1 - Fetch Feed Data

    SCHED->>CF1: HTTP trigger
    CF1->>GCS_CFG: Read mrss_shorts_feeds.csv
    GCS_CFG-->>CF1: Feed URLs and config

    par ThreadPoolExecutor(100)
        CF1->>FEEDS: GET feed URL (Feed ID != 49,50)
        FEEDS-->>CF1: JSON response (key: 'items')
        CF1->>FEEDS: GET feed URL (Feed ID 49 or 50)
        FEEDS-->>CF1: JSON response (key: 'data')
    end

    loop For each feed record
        CF1->>PS1: Publish raw feed record
    end

    Note over SCHED,GCS_VID: Stage 2 - Process Videos

    PS1->>CF2: Trigger with raw feed record
    CF2->>REDIS: Check de_mrss_shorts_cache (key: title_link_cat_lang)

    alt Record exists in cache
        Note over CF2: Skip (duplicate)
    else Record not in cache
        CF2->>REDIS: SET key with 48h TTL

        alt Publisher 7777/7778
            Note over CF2: Check videotype filter
            Note over CF2: Accept: shorts, short, short video, shortvideo
        end

        alt Publisher 7782 (IANS)
            Note over CF2: Video URL from record.get('video')
        end

        Note over CF2: Set contentType="shorts"
        Note over CF2: Set sourceVideoOrientation="portrait"
        Note over CF2: Default image range: 1-5 (if no thumbnail)

        CF2->>PS_IMG: Publish thumbnail for CDN processing
        CF2->>MONGO: insert_many into raw_videos_rss
        CF2->>PS2: Publish processed record
    end

    Note over SCHED,GCS_VID: Stage 3 - Download Videos

    PS2->>CF3: Trigger with processed record
    CF3->>FEEDS: Download video file (source URL)
    FEEDS-->>CF3: Raw MP4 video data
    CF3->>GCS_VID: Upload raw_videos/{video_id}.mp4
    Note over CF3: NO transcoder submission (shorts skip transcoding)
    CF3->>MONGO: Update record: processingStatus="completed"
    Note over CF3: videoContentUrl = https://vcdn.jionews.com/raw_videos/{video_id}.mp4
```

## Three-Source Convergence Diagram

```mermaid
flowchart TD
    subgraph "Source 1: JioNewsDENativeVideos"
        S1_IN["Editorial Upload\nPub/Sub Event"]
        S1_CF["JioNewsDENativeVideos\nCloud Function\n(shared)"]
        S1_IN --> S1_CF
        S1_CF -->|"contentType=shorts\norientation=portrait"| MONGO
    end

    subgraph "Source 2: yt-manual-upload"
        S2_IN["YouTube Manual\nUpload Event"]
        S2_CF["yt-manual-upload\nCloud Function\n(shared)"]
        S2_IN --> S2_CF
        S2_CF -->|"contentType=shorts\nthumbnail=oar2.jpg"| MONGO
    end

    subgraph "Source 3: MRSS Shorts Pipeline"
        S3_FETCH["mrssshorts-fetchfeedsdata"]
        S3_PS1["Pub/Sub:\nRawFeedsData"]
        S3_PROC["mrssshorts-processvideos"]
        S3_PS2["Pub/Sub:\nProcessedData"]
        S3_DL["mrssshorts-downloadvideos"]

        S3_FETCH --> S3_PS1
        S3_PS1 --> S3_PROC
        S3_PROC --> S3_PS2
        S3_PS2 --> S3_DL
        S3_PROC -->|"contentType=shorts\norientation=portrait"| MONGO
        S3_DL -->|"processingStatus=completed\nvideoContentUrl set"| MONGO
    end

    MONGO["MongoDB:\ningestion-data.raw_videos_rss\n(shared collection)"]

    MONGO --> CDN["CDN:\nvcdn.jionews.com/raw_videos/"]
    MONGO --> DOWNSTREAM["Downstream:\nEditorial & Recommendation\nSystems"]
```

## MRSS Stage 1: Feed Fetching - Internal Flow

```mermaid
flowchart TD
    A["Start: HTTP trigger"] --> B["Read mrss_shorts_feeds.csv\nfrom GCS"]
    B --> C["Parse feed configurations"]
    C --> D["Create ThreadPoolExecutor\n(max_workers=100)"]
    D --> E["Submit all feed URLs\nfor concurrent fetching"]

    E --> F{"Feed ID\n49 or 50?"}
    F -->|Yes| G["Parse JSON:\ndata = response['data']"]
    F -->|No| H["Parse JSON:\ndata = response['items']"]

    G --> I["Collect feed records"]
    H --> I

    I --> J["Publish each record to\nMRSSShortsIngestion_RawFeedsData"]
    J --> K["End: Stage 1 complete"]
```

## MRSS Stage 2: Processing - Internal Flow

```mermaid
flowchart TD
    A["Start: Pub/Sub message\n(raw feed record)"] --> B["Construct dedup key:\ntitle + link + category + language"]
    B --> C["Check Redis:\nde_mrss_shorts_cache"]
    C --> D{Key exists\nin cache?}
    D -->|Yes| E["Skip: Duplicate record"]
    D -->|No| F["Set Redis key\n(TTL: 48 hours)"]
    F --> G{Publisher\n7777 or 7778?}
    G -->|Yes| H{videotype matches\nshorts variants?}
    H -->|No| E
    H -->|Yes| I["Process record"]
    G -->|No| J{Publisher\n7782 IANS?}
    J -->|Yes| K["Extract video URL\nfrom record.get('video')"]
    K --> I
    J -->|No| I
    I --> L["Set metadata:\ncontentType=shorts\norientation=portrait"]
    L --> M{Thumbnail\navailable?}
    M -->|Yes| N["Use provided thumbnail"]
    M -->|No| O["Select random default\nimage (range 1-5)"]
    N --> P["Publish to\nNewRawHeadlinesIngestion_image_cdn"]
    O --> P
    P --> Q["insert_many into\nMongoDB raw_videos_rss"]
    Q --> R["Publish to\nMRSSShortsIngestion_ProcessedData"]
    R --> S["End: Stage 2 complete"]
```

## MRSS Stage 3: Download - Internal Flow

```mermaid
flowchart TD
    A["Start: Pub/Sub message\n(processed record)"] --> B["Extract source video URL"]
    B --> C["Download video file\nfrom source URL"]
    C --> D{Download\nsucceeded?}
    D -->|No| E["Log error\nEnd: Download failed"]
    D -->|Yes| F["Upload to GCS:\nhls_video_transcoder_storage_output_files/\nraw_videos/{video_id}.mp4"]
    F --> G["Update MongoDB record:\nprocessingStatus=completed"]
    G --> H["Set videoContentUrl:\nhttps://vcdn.jionews.com/\nraw_videos/{video_id}.mp4"]
    H --> I["End: Stage 3 complete\n(NO transcoder submission)"]
```

## Infrastructure Topology

```mermaid
flowchart TB
    subgraph "Shared Cloud Functions"
        CF_NAT["JioNewsDENativeVideos"]
        CF_YT["yt-manual-upload"]
    end

    subgraph "MRSS Shorts Cloud Functions"
        CF_F["mrssshorts-fetchfeedsdata"]
        CF_P["mrssshorts-processvideos"]
        CF_D["mrssshorts-downloadvideos"]
    end

    subgraph "Pub/Sub Topics"
        PS1["MRSSShortsIngestion_RawFeedsData"]
        PS2["MRSSShortsIngestion_ProcessedData"]
        PS3["NewRawHeadlinesIngestion_image_cdn"]
    end

    subgraph "Storage"
        GCS_CFG["GCS: de-raw-ingestion/shorts/"]
        GCS_VID["GCS: hls_video_transcoder_storage_output_files/raw_videos/"]
        REDIS["Redis: de_mrss_shorts_cache"]
        MONGO["MongoDB: ingestion-data.raw_videos_rss"]
    end

    subgraph "External"
        MRSS["MRSS Publisher Feeds"]
        CDN["vcdn.jionews.com"]
    end

    CF_NAT --> MONGO
    CF_YT --> MONGO

    CF_F --> GCS_CFG
    CF_F --> MRSS
    CF_F --> PS1
    PS1 --> CF_P
    CF_P --> REDIS
    CF_P --> MONGO
    CF_P --> PS3
    CF_P --> PS2
    PS2 --> CF_D
    CF_D --> GCS_VID
    CF_D --> MONGO
    GCS_VID --> CDN
```

## Networking and Security

- **Shared Cloud Functions** (JioNewsDENativeVideos, yt-manual-upload) are triggered by internal Pub/Sub events and share the same codebase with the Native Videos pipeline.
- **MRSS Cloud Functions** execute within the GCP default VPC and access external MRSS feeds over the public internet.
- **Redis** is accessed over a private network connection for deduplication.
- **MongoDB** is accessed via the connection URI from Secret Manager (`mongosh_de_uri`).
- **GCS** access uses default service account credentials.
- **CDN** (`vcdn.jionews.com`) serves raw MP4 files from the GCS bucket via a CDN layer.
