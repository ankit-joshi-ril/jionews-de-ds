# Webstories Ingestion - Architecture

## Overview

The Webstories Ingestion pipeline is a minimal 2-function serverless architecture on Google Cloud Platform. It follows a simple linear pattern: fetch and process web stories, then persist to MongoDB. There is no image CDN stage, no Redis deduplication, and no hygiene branching.

## System Context Diagram

```mermaid
flowchart TB
    subgraph External["External Systems"]
        CS[Cloud Scheduler]
        PA[Publisher APIs<br/>JSON endpoints]
        PF[Publisher Feeds<br/>RSS endpoints]
    end

    subgraph GCP["GCP - jiox-328108"]
        subgraph CF["Cloud Functions"]
            F1[RawWebStoriesIngestion]
            F2[PushToMongoDB]
        end

        subgraph PubSub["Pub/Sub"]
            T1[RawWebStoriesIngestion<br/>Topic]
        end

        subgraph Storage["Storage"]
            CSV[Local CSV<br/>publishers.csv]
            MongoDB[(MongoDB<br/>ingestion-data)]
        end
    end

    CS -->|HTTP trigger| F1
    F1 -->|Read config| CSV
    F1 -->|HTTP GET| PA
    F1 -->|HTTP GET| PF
    F1 -->|Validate thumbnails| PA
    F1 -->|Validate thumbnails| PF
    F1 -->|Publish| T1
    T1 -->|CloudEvent| F2
    F2 -->|Write| MongoDB
```

## Pipeline Sequence Diagram

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant F1 as RawWebStoriesIngestion
    participant CSV as Local publishers.csv
    participant API as Publisher API
    participant Feed as Publisher Feed
    participant Thumb as Thumbnail URL
    participant PS as Pub/Sub Topic
    participant F2 as PushToMongoDB
    participant Mongo as MongoDB

    CS->>F1: HTTP trigger (cron)
    F1->>CSV: Read publisher config

    loop Each publisher
        alt type == "api"
            F1->>API: HTTP GET endpoint
            API-->>F1: JSON response
            Note over F1: Navigate data_list_path<br/>Apply field mapping JSON
        else type == "feed"
            F1->>Feed: HTTP GET endpoint
            Feed-->>F1: RSS/XML response
            Note over F1: feedparser parse<br/>Apply field mapping JSON
        end

        loop Each story record
            Note over F1: Replace http:// with https://
            Note over F1: Append UTM params<br/>campaign=JioNewsStories

            F1->>Thumb: HTTP GET thumbnail URL
            alt 200 OK
                Thumb-->>F1: Valid thumbnail
                Note over F1: Keep validated thumbnail URL
            else Non-200 or Error
                Thumb-->>F1: Invalid thumbnail
                Note over F1: Set thumbnail to null
            end

            F1->>PS: Publish processed record
        end
    end

    PS->>F2: CloudEvent trigger
    F2->>Mongo: Insert to raw_web_stories_ingestion_data
```

## Component Architecture

```mermaid
flowchart LR
    subgraph RawWebStoriesIngestion["RawWebStoriesIngestion (HTTP)"]
        direction TB
        A1[Read Local CSV Config]
        A2{Source Type?}
        A3[API Parser<br/>JSON + data_list_path]
        A4[Feed Parser<br/>feedparser]
        A5[Field Mapping<br/>Per-publisher JSON]
        A6[HTTPS Enforcement<br/>http -> https]
        A7[UTM Appender<br/>JioNewsStories]
        A8[Thumbnail Validator<br/>HTTP GET]
        A9[Pub/Sub Publisher]

        A1 --> A2
        A2 -->|api| A3
        A2 -->|feed| A4
        A3 --> A5
        A4 --> A5
        A5 --> A6
        A6 --> A7
        A7 --> A8
        A8 --> A9
    end

    subgraph PushToMongoDB["PushToMongoDB (CloudEvent)"]
        direction TB
        B1[Receive CloudEvent]
        B2[Parse record from message]
        B3[Insert to MongoDB]

        B1 --> B2
        B2 --> B3
    end
```

## Field Mapping Flow

```mermaid
flowchart TD
    PUB[Publisher Response]
    CSV_MAP["CSV mapping column<br/>(JSON string)"]
    PARSE["json.loads(mapping)"]
    MAP_TABLE["Mapping Table:<br/>title -> publisher_title_field<br/>url -> publisher_url_field<br/>thumbnail -> publisher_thumb_field<br/>published_date -> publisher_date_field"]
    APPLY["Apply mapping to each record"]
    STD["Standard Schema Record"]

    PUB --> APPLY
    CSV_MAP --> PARSE
    PARSE --> MAP_TABLE
    MAP_TABLE --> APPLY
    APPLY --> STD
```

## Source Type Decision Flow

```mermaid
flowchart TD
    CONFIG[Read Publisher Row from CSV]
    TYPE{type column?}

    subgraph API_PATH["API Path"]
        GET_API[HTTP GET endpoint]
        JSON_PARSE[json.loads response]
        NAV["Navigate data_list_path<br/>e.g., response.data.stories"]
        ITEMS_API[Extract story items]
    end

    subgraph FEED_PATH["Feed Path"]
        GET_FEED[HTTP GET endpoint]
        FP[feedparser.parse response]
        ITEMS_FEED[Extract feed entries]
    end

    MAP[Apply per-publisher field mapping]

    CONFIG --> TYPE
    TYPE -->|api| GET_API
    GET_API --> JSON_PARSE
    JSON_PARSE --> NAV
    NAV --> ITEMS_API
    ITEMS_API --> MAP

    TYPE -->|feed| GET_FEED
    GET_FEED --> FP
    FP --> ITEMS_FEED
    ITEMS_FEED --> MAP
```

## Infrastructure Summary

| Component                | GCP Service        | Configuration                |
|--------------------------|--------------------|------------------------------|
| `RawWebStoriesIngestion` | Cloud Functions    | HTTP trigger, Gen 2          |
| `PushToMongoDB`          | Cloud Functions    | CloudEvent trigger, Gen 2    |
| Publisher Config         | Local File         | Bundled CSV in function pkg  |
| Persistence              | MongoDB Atlas      | `ingestion-data` database    |
| Messaging                | Pub/Sub            | 1 topic with CloudEvent sub  |
| Scheduling               | Cloud Scheduler    | Cron-based HTTP trigger      |

## Comparison with Other Pipeline Architectures

```mermaid
flowchart LR
    subgraph Headlines["Headlines (5 Functions)"]
        H1[Fetch] --> H2[Process] --> H3[ImageCDN] --> H4[MongoDB]
        H3 --> H5[Rejected MongoDB]
    end

    subgraph Summaries["Summaries (5 Functions + 1 Cloud Run)"]
        S1[Fetch] --> S2[Process] --> S3[ImageCDN] --> S4[MongoDB]
        S2 --> S5[LLM Async]
    end

    subgraph Webstories["Webstories (2 Functions)"]
        W1[Fetch + Process] --> W2[MongoDB]
    end
```

## Network and Security

| Connection                | Protocol | Authentication           |
|---------------------------|----------|--------------------------|
| Cloud Scheduler -> CF     | HTTPS    | IAM service account      |
| CF -> Publisher APIs      | HTTPS    | None (public APIs)       |
| CF -> Publisher Feeds     | HTTPS    | None (public feeds)      |
| CF -> Thumbnail URLs      | HTTPS    | None (public URLs)       |
| CF -> MongoDB             | TLS      | URI with credentials     |
| CF -> Pub/Sub             | HTTPS    | IAM service account      |
