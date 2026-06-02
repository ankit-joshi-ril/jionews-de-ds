# YouTube Shorts Ingestion - Architecture

## System Context Diagram

```mermaid
flowchart LR
    subgraph External
        YT_WEB["YouTube Website\n(Channel /shorts pages)"]
        YT_API["YouTube Data API v3"]
    end

    subgraph "GCP Project: jiox-328108"
        SCHED["Cloud Scheduler"]
        CF1["Cloud Function:\nScrapeVideoIds"]
        PS1["Pub/Sub:\ncron_based_raw_youtube_\nshorts_ingestion"]
        CF2["Cloud Function:\nYouTubeAPIToMongoDB"]
        PS2["Pub/Sub:\nraw_youtube_shorts_\ningestion"]
        GCS["GCS:\nde-raw-ingestion/shorts/\nshorts_publishers.csv"]
        SM["Secret Manager"]
    end

    subgraph Data Store
        MONGO["MongoDB:\ningestion-data.\nraw_short_videos_\ningestion_data"]
    end

    SCHED -->|"HTTP trigger"| CF1
    GCS -->|"Read publisher list"| CF1
    CF1 -->|"Scrape /shorts pages"| YT_WEB
    CF1 -->|"Dedup query"| MONGO
    CF1 -->|"Publish new IDs"| PS1
    PS1 -->|"Trigger"| CF2
    SM -->|"yt_api_access_token"| CF2
    SM -->|"mongosh_de_uri"| CF1
    SM -->|"mongosh_de_uri"| CF2
    CF2 -->|"videos().list()"| YT_API
    CF2 -->|"Redirect check"| YT_WEB
    CF2 -->|"insert_many"| MONGO
    CF2 -->|"Publish records"| PS2
    PS2 -->|"Downstream"| DOWNSTREAM["Downstream\nConsumers"]
```

## Detailed Pipeline Flow

```mermaid
sequenceDiagram
    participant SCHED as Cloud Scheduler
    participant CF1 as ScrapeVideoIds
    participant GCS as GCS (Publisher CSV)
    participant YT_WEB as YouTube Website
    participant MONGO as MongoDB
    participant PS1 as Pub/Sub (cron_based)
    participant CF2 as YouTubeAPIToMongoDB
    participant SM as Secret Manager
    participant YT_API as YouTube Data API v3
    participant PS2 as Pub/Sub (output)

    Note over SCHED,PS2: Stage 1 - Video ID Discovery

    SCHED->>CF1: HTTP trigger (cron schedule)
    CF1->>SM: Fetch mongosh_de_uri
    SM-->>CF1: MongoDB connection URI
    CF1->>GCS: Read shorts_publishers.csv (ISO-8859-1)
    GCS-->>CF1: Publisher rows with custom_url

    loop For each publisher
        CF1->>YT_WEB: GET http://www.youtube.com/{custom_url}/shorts (5s timeout)
        YT_WEB-->>CF1: HTML response
        Note over CF1: Parse with BeautifulSoup
        Note over CF1: Extract ytInitialData JSON
        Note over CF1: JSONPath $..videoId
    end

    CF1->>MONGO: Aggregation query: existing sourceVideoIds
    MONGO-->>CF1: Set of known video IDs
    Note over CF1: Filter out already-known IDs
    CF1->>PS1: Publish batch of new video IDs

    Note over SCHED,PS2: Stage 2 - API Enrichment and Storage

    PS1->>CF2: Trigger with video ID batch
    CF2->>SM: Fetch yt_api_access_token
    SM-->>CF2: YouTube API key
    CF2->>SM: Fetch mongosh_de_uri
    SM-->>CF2: MongoDB connection URI

    loop Batches of 50 IDs
        CF2->>YT_API: videos().list(part=snippet,contentDetails, ids=batch)
        YT_API-->>CF2: Video metadata response
    end

    loop For each video
        Note over CF2: Parse ISO 8601 duration (isodate)
        Note over CF2: Validate: 0s < duration <= 60s

        CF2->>YT_WEB: GET https://www.youtube.com/shorts/{id} (allow_redirects=False)
        YT_WEB-->>CF2: HTTP status code

        Note over CF2: Validate: status == 200 (is a Short)
        Note over CF2: Validate: publishedAt within 24 hours
        Note over CF2: Transform to output schema
    end

    CF2->>MONGO: insert_many(ordered=False) qualified records
    MONGO-->>CF2: Insert result

    loop For each inserted record
        CF2->>PS2: Publish enriched record
    end

    PS2-->>PS2: Available for downstream consumers
```

## Stage 1: ScrapeVideoIds - Internal Flow

```mermaid
flowchart TD
    A["Start: HTTP trigger from Cloud Scheduler"] --> B["Read publisher CSV from GCS\n(ISO-8859-1 encoding)"]
    B --> C["Iterate over publisher rows"]
    C --> D["Construct URL:\nhttp://www.youtube.com/{custom_url}/shorts"]
    D --> E["HTTP GET with 5s timeout"]
    E --> F{Request\nsucceeded?}
    F -->|No| C
    F -->|Yes| G["Parse HTML with BeautifulSoup"]
    G --> H["Extract ytInitialData JSON\nfrom script tag"]
    H --> I["JSONPath: $..videoId\nExtract all video IDs"]
    I --> J["Accumulate video IDs"]
    J --> K{More\npublishers?}
    K -->|Yes| C
    K -->|No| L["Query MongoDB:\nExisting sourceVideoIds"]
    L --> M["Compute set difference:\nnew_ids = scraped - existing"]
    M --> N{New IDs\nfound?}
    N -->|No| O["End: No new videos"]
    N -->|Yes| P["Publish to Pub/Sub:\ncron_based_raw_youtube_shorts_ingestion"]
    P --> Q["End: Stage 1 complete"]
```

## Stage 2: YouTubeAPIToMongoDB - Internal Flow

```mermaid
flowchart TD
    A["Start: Pub/Sub message received"] --> B["Decode message:\nExtract video ID batch"]
    B --> C["Fetch secrets:\nyt_api_access_token, mongosh_de_uri"]
    C --> D["Batch video IDs\n(groups of 50)"]
    D --> E["Call YouTube API:\nvideos().list(part=snippet,contentDetails)"]
    E --> F["Process each video in response"]
    F --> G["Parse duration\n(ISO 8601 via isodate)"]
    G --> H{Duration > 0s\nAND <= 60s?}
    H -->|No| F
    H -->|Yes| I["HTTP GET:\nhttps://www.youtube.com/shorts/{id}\nallow_redirects=False"]
    I --> J{HTTP 200?\n(Is a Short)}
    J -->|No| F
    J -->|Yes| K{publishedAt\nwithin 24h?}
    K -->|No| F
    K -->|Yes| L["Transform to output schema:\n- sourceVideoId, title, thumbnails\n- sourceDate, sourceEpoch\n- duration, dimensions, orientation"]
    L --> M["Add to qualified batch"]
    M --> N{More videos\nto process?}
    N -->|Yes| F
    N -->|No| O["insert_many(ordered=False)\ninto MongoDB"]
    O --> P["Publish each record to\nraw_youtube_shorts_ingestion"]
    P --> Q["End: Stage 2 complete"]
```

## Infrastructure Topology

```mermaid
flowchart TB
    subgraph "Cloud Scheduler"
        CRON["Cron Job"]
    end

    subgraph "Cloud Functions"
        CF1["ScrapeVideoIds\n(HTTP trigger)"]
        CF2["YouTubeAPIToMongoDB\n(Pub/Sub trigger)"]
    end

    subgraph "Pub/Sub Topics"
        PS1["cron_based_raw_youtube_\nshorts_ingestion"]
        PS2["raw_youtube_shorts_\ningestion"]
    end

    subgraph "Google Cloud Storage"
        GCS["de-raw-ingestion/\nshorts/shorts_publishers.csv"]
    end

    subgraph "Secret Manager"
        S1["mongosh_de_uri"]
        S2["yt_api_access_token"]
    end

    subgraph "MongoDB Atlas"
        DB["ingestion-data.\nraw_short_videos_\ningestion_data"]
    end

    subgraph "External"
        YT1["YouTube Website"]
        YT2["YouTube Data API v3"]
    end

    CRON -->|HTTP| CF1
    CF1 --> GCS
    CF1 --> YT1
    CF1 --> DB
    CF1 --> S1
    CF1 --> PS1
    PS1 --> CF2
    CF2 --> S1
    CF2 --> S2
    CF2 --> YT2
    CF2 --> YT1
    CF2 --> DB
    CF2 --> PS2
```

## Networking and Security

- **Cloud Functions** execute within the GCP project's default VPC.
- **Secret Manager** provides `mongosh_de_uri` (MongoDB connection string) and `yt_api_access_token` (YouTube API key) at runtime.
- **MongoDB** is accessed over the public internet using the connection URI from Secret Manager. TLS is enforced via the `certifi` library for CA bundle verification.
- **YouTube API** calls are authenticated via API key (not OAuth).
- **YouTube website scraping** uses plain HTTP GET requests with no authentication.
