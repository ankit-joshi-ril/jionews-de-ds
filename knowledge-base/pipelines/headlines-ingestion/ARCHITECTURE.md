# Headlines Ingestion - Architecture

## Overview

The Headlines Ingestion pipeline is a 5-function serverless architecture on Google Cloud Platform. It follows a linear Pub/Sub-chained execution model with a terminal branch that separates successful records from rejected records into distinct MongoDB collections.

## System Context Diagram

```mermaid
flowchart TB
    subgraph External["External Systems"]
        CS[Cloud Scheduler]
        PF[Publisher Feeds<br/>RSS/XML & JSON]
        AS1[Article Scraper<br/>service.jionews.com]
        AS2[Article Scraper Fallback<br/>34.36.231.72]
    end

    subgraph GCP["GCP - jiox-328108"]
        subgraph CF["Cloud Functions"]
            F1[fetchfeedsdata]
            F2[processheadlines]
            F3[imagecdn]
            F4[PushToMongoDB]
            F5[rejected-pushtomongo]
        end

        subgraph PubSub["Pub/Sub Topics"]
            T1[raw_feeds_data]
            T2[image_cdn]
            T3[processed_data]
            T4[rejected_data]
        end

        subgraph Storage["Storage"]
            GCS_Config[GCS: de-raw-ingestion<br/>Feed Config CSV]
            GCS_CDN[GCS: img-cdn-bucket<br/>Image Renditions]
            Redis[(Redis Cache<br/>Deduplication)]
            MongoDB[(MongoDB<br/>ingestion-data)]
        end
    end

    CS -->|HTTP trigger| F1
    F1 -->|Fetch feeds| PF
    F1 -->|Read config| GCS_Config
    F1 -->|Publish| T1
    T1 -->|Push subscription| F2
    F2 -->|Dedup check| Redis
    F2 -->|Scrape article| AS1
    F2 -->|Fallback scrape| AS2
    F2 -->|Publish| T2
    T2 -->|Push subscription| F3
    F3 -->|Upload images| GCS_CDN
    F3 -->|Publish success| T3
    F3 -->|Publish failure| T4
    T3 -->|CloudEvent| F4
    T4 -->|CloudEvent| F5
    F4 -->|Write| MongoDB
    F5 -->|Write| MongoDB
```

## Pipeline Sequence Diagram

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant F1 as fetchfeedsdata
    participant GCS as GCS (Config)
    participant PF as Publisher Feeds
    participant PS1 as Pub/Sub: raw_feeds_data
    participant F2 as processheadlines
    participant Redis as Redis Cache
    participant Scraper as Article Scraper
    participant PS2 as Pub/Sub: image_cdn
    participant F3 as imagecdn
    participant CDN as GCS (img-cdn-bucket)
    participant PS3 as Pub/Sub: processed_data
    participant PS4 as Pub/Sub: rejected_data
    participant F4 as PushToMongoDB
    participant F5 as rejected-pushtomongo
    participant Mongo as MongoDB

    CS->>F1: HTTP trigger (cron)
    F1->>GCS: Read headlines_publishers_feeds.csv
    GCS-->>F1: Feed config rows

    loop Each feed (ThreadPoolExecutor 100)
        F1->>PF: HTTP GET feed URL
        PF-->>F1: RSS/XML or JSON response
        Note over F1: Parse feed<br/>Replace image tags<br/>Map fields per publisher type
        F1->>PS1: Publish raw records (batch)
    end

    PS1->>F2: Push subscription (HTTP)

    loop Each record (ThreadPoolExecutor 50)
        F2->>Redis: Check de_headlines_id_cache (link_cat_lang)
        Redis-->>F2: Hit / Miss

        alt Cache Hit (duplicate)
            Note over F2: Drop record silently
        else Cache Miss (new)
            F2->>Redis: Check de_headlines_title_cache (normalized_title)
            Redis-->>F2: Hit / Miss

            alt Title Cache Hit
                Note over F2: Drop record silently
            else Title Cache Miss
                F2->>Redis: Set both cache keys (TTL 48h)
                Note over F2: Enrich record:<br/>Generate sourceId<br/>Append UTM params<br/>Epoch conversion

                F2->>Scraper: GET /v1/scrape/scrape/?url={url}
                alt Scrape Success
                    Scraper-->>F2: Article body
                else Scrape Failure (English only)
                    F2->>Scraper: POST /crawl (fallback)
                    Scraper-->>F2: Article body or empty
                end

                F2->>PS2: Publish enriched record
            end
        end
    end

    PS2->>F3: Push subscription (HTTP)

    Note over F3: Download source thumbnail
    Note over F3: EXIF transpose
    Note over F3: Generate 5 renditions

    alt Thumbnail exists
        F3->>CDN: Upload original, fhd, hd, sd, low
        CDN-->>F3: Upload confirmation
        Note over F3: Set thumbnailUrls with CDN paths
        F3->>PS3: Publish to processed_data
    else No thumbnail
        Note over F3: Set rejectionReason
        F3->>PS4: Publish to rejected_data
    end

    PS3->>F4: CloudEvent trigger
    F4->>Mongo: Insert to raw_headlines_ingestion_data

    PS4->>F5: CloudEvent trigger
    F5->>Mongo: Insert to headlines_hygiene_failures
```

## Component Architecture

```mermaid
flowchart LR
    subgraph fetchfeedsdata["fetchfeedsdata (HTTP)"]
        direction TB
        A1[Read GCS Config CSV]
        A2[ThreadPoolExecutor 100]
        A3[RSS Parser<br/>feedparser + tag replace]
        A4[JSON Parser<br/>json.loads items array]
        A5[Newspoint Mapper<br/>hl/mwu/dl/sec]
        A6[Standard Mapper<br/>title/link/published]
        A7[Pub/Sub Publisher]

        A1 --> A2
        A2 --> A3
        A2 --> A4
        A3 --> A5
        A3 --> A6
        A4 --> A6
        A5 --> A7
        A6 --> A7
    end

    subgraph processheadlines["processheadlines (Pub/Sub Push)"]
        direction TB
        B1[Receive Pub/Sub Message]
        B2[ThreadPoolExecutor 50]
        B3[Redis Link Dedup]
        B4[Redis Title Dedup]
        B5[Enrichment<br/>sourceId, UTM, epoch]
        B6[Article Scraper Primary]
        B7[Article Scraper Fallback]
        B8[Pub/Sub Publisher]

        B1 --> B2
        B2 --> B3
        B3 -->|Miss| B4
        B4 -->|Miss| B5
        B5 --> B6
        B6 -->|Failure + English| B7
        B6 -->|Success| B8
        B7 --> B8
    end

    subgraph imagecdn["imagecdn (Pub/Sub Push)"]
        direction TB
        C1[Receive Pub/Sub Message]
        C2[Download Source Image]
        C3[EXIF Transpose]
        C4[Resize: 5 Renditions]
        C5[JPEG Encode q90]
        C6[GCS Upload]
        C7{Thumbnail<br/>Valid?}
        C8[Pub/Sub: processed_data]
        C9[Pub/Sub: rejected_data]

        C1 --> C2
        C2 --> C3
        C3 --> C4
        C4 --> C5
        C5 --> C6
        C6 --> C7
        C7 -->|Yes| C8
        C7 -->|No| C9
    end
```

## Image CDN Rendition Flow

```mermaid
flowchart TD
    SRC[Source Thumbnail URL]
    DL[Download Image]
    EXIF[EXIF Orientation Transpose]

    SRC --> DL --> EXIF

    EXIF --> R1[Original<br/>Source dimensions]
    EXIF --> R2[FHD<br/>1920x1080]
    EXIF --> R3[HD<br/>1280x720]
    EXIF --> R4[SD<br/>720x480]
    EXIF --> R5[Low<br/>480x320]

    R1 --> ENC[JPEG Encode q90]
    R2 --> ENC
    R3 --> ENC
    R4 --> ENC
    R5 --> ENC

    ENC --> UP[Upload to img-cdn-bucket]

    UP --> U1["original/{sourceId}.jpeg"]
    UP --> U2["fhd/{sourceId}.jpeg"]
    UP --> U3["hd/{sourceId}.jpeg"]
    UP --> U4["sd/{sourceId}.jpeg"]
    UP --> U5["low/{sourceId}.jpeg"]
```

## Deduplication Flow

```mermaid
flowchart TD
    IN[Incoming Record]
    C1{Redis Check<br/>de_headlines_id_cache<br/>key: link_cat_lang}
    C2{Redis Check<br/>de_headlines_title_cache<br/>key: normalized_title}
    DROP[Drop Record<br/>Silent discard]
    SET[Set Both Cache Keys<br/>TTL 48h]
    PROC[Continue Processing]

    IN --> C1
    C1 -->|Hit| DROP
    C1 -->|Miss| C2
    C2 -->|Hit| DROP
    C2 -->|Miss| SET
    SET --> PROC
```

## Infrastructure Summary

| Component           | GCP Service        | Configuration                      |
|---------------------|--------------------|------------------------------------|
| `fetchfeedsdata`    | Cloud Functions    | HTTP trigger, Gen 2                |
| `processheadlines`  | Cloud Functions    | Pub/Sub push (HTTP), Gen 2        |
| `imagecdn`          | Cloud Functions    | Pub/Sub push (HTTP), Gen 2        |
| `PushToMongoDB`     | Cloud Functions    | CloudEvent trigger, Gen 2         |
| `rejected-pushtomongo` | Cloud Functions | CloudEvent trigger, Gen 2         |
| Feed Config         | Cloud Storage      | `de-raw-ingestion` bucket         |
| Image CDN           | Cloud Storage      | `img-cdn-bucket` bucket           |
| Dedup Cache         | Redis              | Two cache instances, 48h TTL      |
| Persistence         | MongoDB Atlas      | `ingestion-data` database         |
| Messaging           | Pub/Sub            | 4 topics, push + CloudEvent subs  |
| Scheduling          | Cloud Scheduler    | Cron-based HTTP trigger           |

## Network and Security

| Connection                | Protocol | Authentication                |
|---------------------------|----------|-------------------------------|
| Cloud Scheduler -> CF     | HTTPS    | IAM service account           |
| CF -> Publisher Feeds     | HTTP/S   | None (public feeds)           |
| CF -> Article Scraper     | HTTPS    | None (internal service)       |
| CF -> Article Scraper FB  | HTTP     | None (IP-based)               |
| CF -> Redis               | TCP      | Redis AUTH                    |
| CF -> MongoDB             | TLS      | URI with credentials (Secret) |
| CF -> GCS                 | HTTPS    | IAM service account           |
| CF -> Pub/Sub             | HTTPS    | IAM service account           |
