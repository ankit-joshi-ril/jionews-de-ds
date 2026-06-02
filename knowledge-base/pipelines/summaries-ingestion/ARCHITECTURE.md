# Summaries Ingestion - Architecture

## Overview

The Summaries Ingestion pipeline is a hybrid serverless architecture combining 5 Cloud Functions with 1 Cloud Run service. It implements a hygiene-based branching pattern: records passing English-language quality checks flow through the standard image CDN path, while failing records are routed to an LLM-based summarization service for content regeneration.

## System Context Diagram

```mermaid
flowchart TB
    subgraph External["External Systems"]
        CS[Cloud Scheduler]
        PF[Publisher Feeds<br/>RSS/XML & JSON]
        Gemini[Gemini 2.5 Flash<br/>LLM API]
    end

    subgraph GCP["GCP - jiox-328108"]
        subgraph CF["Cloud Functions"]
            F1[FetchFeedsData]
            F2[ProcessSummaries]
            F3[imagecdn<br/>Shared with Headlines]
            F4[PushToMongoDB]
        end

        subgraph CR["Cloud Run"]
            SA[summarization-async]
            Proxy[jn-article-render-proxy]
        end

        subgraph PubSub["Pub/Sub Topics"]
            T1[RawSummariesIngestion<br/>_FeedsData]
            T2[NewRawHeadlinesIngestion<br/>_image_cdn<br/>SHARED]
            T3[RawSummariesIngestion<br/>_ProcessedData]
            T4[RawSummariesIngestion<br/>_HygineFailure]
        end

        subgraph Storage["Storage"]
            Redis[(Redis Cache<br/>de_summaries_cache)]
            MongoDB[(MongoDB<br/>ingestion-data)]
            GCS_CDN[GCS: img-cdn-bucket]
        end
    end

    CS -->|HTTP trigger| F1
    F1 -->|Fetch feeds| PF
    F1 -->|Publish| T1
    T1 --> F2
    F2 -->|Dedup check| Redis
    F2 -->|Hygienic| T2
    F2 -->|Unhygienic| T4
    T2 --> F3
    F3 -->|Upload images| GCS_CDN
    F3 -->|Publish| T3
    T3 --> F4
    F4 -->|Write| MongoDB
    T4 --> SA
    SA -->|Pass 1: URL mode| Gemini
    SA -->|Pass 2: Content fetch| Proxy
    SA -->|Upsert| MongoDB
```

## Pipeline Sequence Diagram

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant F1 as FetchFeedsData
    participant PS1 as Pub/Sub: FeedsData
    participant F2 as ProcessSummaries
    participant Redis as Redis Cache
    participant PS2 as Pub/Sub: image_cdn (shared)
    participant PS4 as Pub/Sub: HygineFailure
    participant F3 as imagecdn
    participant CDN as GCS (img-cdn-bucket)
    participant PS3 as Pub/Sub: ProcessedData
    participant F4 as PushToMongoDB
    participant SA as summarization-async
    participant Gemini as Gemini 2.5 Flash
    participant Proxy as Article Render Proxy
    participant Mongo as MongoDB

    CS->>F1: HTTP trigger (cron)

    loop Each feed
        F1->>F1: Fetch and parse publisher feed
        F1->>PS1: Publish raw records
    end

    PS1->>F2: Push subscription

    loop Each record
        F2->>Redis: Check de_summaries_cache (title)
        Redis-->>F2: Hit / Miss

        alt Cache Hit
            Note over F2: Drop duplicate silently
        else Cache Miss
            F2->>Redis: Set cache key (TTL 48h)

            alt English record
                F2->>F2: Validate hygiene rules
                alt Hygienic
                    Note over F2: Title 26-105 chars<br/>Summary 200-360 chars<br/>No HTML, <3 special chars
                    F2->>PS2: Publish to shared image_cdn topic
                else Unhygienic
                    F2->>PS4: Publish to HygineFailure topic
                end
            else Non-English record
                Note over F2: Skip hygiene, route to image CDN
                F2->>PS2: Publish to shared image_cdn topic
            end
        end
    end

    PS2->>F3: Push subscription
    F3->>CDN: Upload 5 image renditions
    F3->>PS3: Publish processed record

    PS3->>F4: CloudEvent trigger
    F4->>Mongo: Insert to raw_summaries_insgestion_data

    PS4->>SA: Trigger summarization-async

    Note over SA: Pass 1: URL Mode
    SA->>Gemini: Generate summary from URL (url_context tool)

    alt URL Mode Success
        Gemini-->>SA: Summary JSON
    else URL Mode Failure
        Note over SA: Pass 2: Content Fallback
        SA->>Proxy: GET /proxy?url={article_url}
        Proxy-->>SA: Rendered article content
        SA->>Gemini: Generate summary from content
        Gemini-->>SA: Summary JSON
    end

    Note over SA: 3-stage JSON parsing
    SA->>Mongo: Upsert by sourceId
```

## Hygiene Routing Flow

```mermaid
flowchart TD
    IN[Incoming Record]
    LANG{Language?}
    HYG[Apply Hygiene Rules]
    TITLE{Title 26-105<br/>chars?}
    SUMMARY{Summary 200-360<br/>chars?}
    HTML{Contains<br/>HTML?}
    SPECIAL{>= 3 Special<br/>chars?}
    HYGIENIC[Route: Hygienic<br/>imagecdn topic]
    UNHYGIENIC[Route: Unhygienic<br/>HygineFailure topic]

    IN --> LANG
    LANG -->|English| HYG
    LANG -->|Non-English| HYGIENIC
    HYG --> TITLE
    TITLE -->|No| UNHYGIENIC
    TITLE -->|Yes| SUMMARY
    SUMMARY -->|No| UNHYGIENIC
    SUMMARY -->|Yes| HTML
    HTML -->|Yes| UNHYGIENIC
    HTML -->|No| SPECIAL
    SPECIAL -->|Yes| UNHYGIENIC
    SPECIAL -->|No| HYGIENIC
```

## LLM Summarization Flow

```mermaid
flowchart TD
    IN[Unhygienic Record]
    P1[Pass 1: URL Mode<br/>Gemini + url_context tool]
    P1_CHECK{URL Mode<br/>Succeeded?}
    P2_FETCH[Fetch Content via Proxy]
    P2[Pass 2: Content Mode<br/>Gemini + article content]
    PARSE[3-Stage JSON Parse]
    S1{Direct<br/>json.loads?}
    S2{Strip Markdown<br/>Fences?}
    S3{Extract First<br/>JSON Object?}
    UPSERT[MongoDB Upsert<br/>by sourceId]
    FAIL[Log Error]

    IN --> P1
    P1 --> P1_CHECK
    P1_CHECK -->|Yes| PARSE
    P1_CHECK -->|No| P2_FETCH
    P2_FETCH --> P2
    P2 --> PARSE

    PARSE --> S1
    S1 -->|Success| UPSERT
    S1 -->|Failure| S2
    S2 -->|Success| UPSERT
    S2 -->|Failure| S3
    S3 -->|Success| UPSERT
    S3 -->|Failure| FAIL
```

## Retry Strategy (LLM Calls)

```mermaid
sequenceDiagram
    participant SA as summarization-async
    participant Gemini as Gemini 2.5 Flash

    SA->>Gemini: Attempt 1
    alt 503 Response
        Note over SA: Wait 2^1 = 2 seconds
        SA->>Gemini: Attempt 2
        alt 503 Response
            Note over SA: Wait 2^2 = 4 seconds
            SA->>Gemini: Attempt 3
            alt 503 Response
                Note over SA: Max retries exceeded<br/>Log error
            else Success
                Gemini-->>SA: Response
            end
        else Success
            Gemini-->>SA: Response
        end
    else Success
        Gemini-->>SA: Response
    end
```

## Default Thumbnail Flow

```mermaid
flowchart TD
    REC[Record with Thumbnail]
    CHECK{isDefaultThumbnail<br/>== true?}
    KEEP[Keep original<br/>publisher info]
    RENAME["Rename publisher:<br/>name = 'InsideMedia'<br/>id = '000'"]
    PROCEED[Continue to<br/>image CDN]

    REC --> CHECK
    CHECK -->|No| KEEP
    CHECK -->|Yes| RENAME
    KEEP --> PROCEED
    RENAME --> PROCEED
```

## Infrastructure Summary

| Component              | GCP Service        | Configuration                      |
|------------------------|--------------------|------------------------------------|
| `FetchFeedsData`       | Cloud Functions    | HTTP trigger, Gen 2                |
| `ProcessSummaries`     | Cloud Functions    | Pub/Sub push (HTTP), Gen 2        |
| `imagecdn`             | Cloud Functions    | Pub/Sub push (HTTP), Gen 2 (shared)|
| `PushToMongoDB`        | Cloud Functions    | CloudEvent trigger, Gen 2         |
| `summarization-async`  | Cloud Run          | Pub/Sub push trigger               |
| `jn-article-render-proxy` | Cloud Run       | Internal HTTP service              |
| Dedup Cache            | Redis              | Single cache, 48h TTL             |
| Persistence            | MongoDB Atlas      | `ingestion-data` database         |
| Image CDN              | Cloud Storage      | `img-cdn-bucket` (shared)         |
| Messaging              | Pub/Sub            | 4 topics (1 shared with Headlines)|
| Scheduling             | Cloud Scheduler    | Cron-based HTTP trigger           |

## Network and Security

| Connection                   | Protocol | Authentication                |
|------------------------------|----------|-------------------------------|
| Cloud Scheduler -> CF        | HTTPS    | IAM service account           |
| CF -> Publisher Feeds        | HTTP/S   | None (public feeds)           |
| CF -> Redis                  | TCP      | Redis AUTH                    |
| CF -> MongoDB                | TLS      | URI with credentials (Secret) |
| CF -> Pub/Sub                | HTTPS    | IAM service account           |
| CF -> GCS                    | HTTPS    | IAM service account           |
| Cloud Run -> Gemini          | HTTPS    | API Key (Secret)              |
| Cloud Run -> Proxy           | HTTPS    | IAM (Cloud Run to Cloud Run)  |
| Cloud Run -> MongoDB         | TLS      | URI with credentials (Secret) |
