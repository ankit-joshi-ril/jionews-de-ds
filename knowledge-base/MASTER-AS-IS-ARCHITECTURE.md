# JioNews DE-DS — Master AS-IS Architecture

> **Document Type:** Canonical AS-IS Architecture — Master Overview
> **Scope:** All data engineering ingestion pipelines and data science workflows
> **GCP Project ID:** `jiox-328108` | **Project Number:** `266686822828`
> **Status:** Production — reflects current deployed state
> **Detailed Docs:** See `pipelines/<name>/` for per-pipeline specifications

---

## 1. System Overview

### 1.1 Platform Summary

JioNews DE-DS is a production data engineering platform running on GCP that ingests, processes, transforms, and distributes multi-format news content. It processes 7 content types through 11 independent pipelines.

### 1.2 Content Types & Pipelines

| # | Pipeline | Content Type | Sources | Deployment | Docs |
|---|---|---|---|---|---|
| 1 | Headlines Ingestion | News headlines | RSS/JSON feeds | 5 Cloud Functions | `pipelines/headlines-ingestion/` |
| 2 | Summaries Ingestion | Article summaries | RSS/JSON feeds + LLM | 5 CF + 1 Cloud Run | `pipelines/summaries-ingestion/` |
| 3 | YouTube Videos | Full-length videos | YT scraping + API | 3 Cloud Functions | `pipelines/youtube-videos-ingestion/` |
| 4 | Native Videos | Full-length videos | Partner API, Manual, MRSS | 7 CF + 2 REST services | `pipelines/native-videos-ingestion/` |
| 5 | Video Transcoder | HLS transcoding | SFTP + CPP/SAAS API | 3 Cloud Functions | `pipelines/video-transcoder-workflow/` |
| 6 | YouTube Shorts | Short-form videos | YT scraping + API | 2 Cloud Functions | `pipelines/youtube-shorts-ingestion/` |
| 7 | Native Shorts | Short-form videos | Partner API, Manual, MRSS | 3 CF + shared services | `pipelines/native-shorts-ingestion/` |
| 8 | Webstories | Web stories | Publisher APIs + RSS | 2 Cloud Functions | `pipelines/webstories-ingestion/` |
| 9 | JioBharat Summaries | Video summaries | PROD MongoDB + TTS + SFTP | 2 CF + 1 FastAPI | `pipelines/jiobharat-video-summaries/` |
| 10 | Auto Summarization | CMS summaries | HTTP API + Gemini LLM | 1 FastAPI service | `pipelines/auto-summarization/` |
| 11 | RSS Feed Generation | RSS XML feeds | MongoDB aggregation + GCS | 4 Cloud Functions | `pipelines/rss-feed-generation/` |

### 1.3 GCP Services Consumed

| GCP Service | Usage |
|---|---|
| Cloud Functions (Gen 1 + Gen 2) | Primary compute for pipeline stages |
| Cloud Run | Long-running REST/API services, persistent Pub/Sub subscribers |
| Cloud Pub/Sub | Inter-stage messaging, event-driven triggers (23 topics) |
| Cloud Storage (GCS) | Config storage, image CDN, video storage, RSS feeds (5 buckets) |
| Secret Manager | MongoDB URIs, API keys, service accounts, SFTP credentials (5 secrets) |
| Cloud Scheduler | Cron triggers for pipeline initiation |
| Compute Engine | Redis instance hosting |

---

## 2. Complete System Data Flow

```mermaid
flowchart TB
    subgraph Sources["External Sources"]
        RSS["RSS/JSON Publisher Feeds"]
        YT["YouTube Channels"]
        API["Partner APIs"]
        CMS["CMS Editorial"]
        MANUAL["Manual Upload UI"]
    end

    subgraph Ingestion["Ingestion Pipelines"]
        HL["Headlines Pipeline"]
        SUM["Summaries Pipeline"]
        YTV["YouTube Videos Pipeline"]
        NV["Native Videos Pipeline"]
        YTS["YouTube Shorts Pipeline"]
        NS["Native Shorts Pipeline"]
        WS["Webstories Pipeline"]
    end

    subgraph Processing["Shared Processing"]
        IMGCDN["Image CDN Service"]
        LLM["LLM Summarization"]
        REDIS["Redis Dedup Cache"]
    end

    subgraph Storage["Data Stores"]
        MONGO[("MongoDB\ningestion-data")]
        GCS[("GCS Buckets")]
        PRODMONGO[("MongoDB\npie-production")]
    end

    subgraph Distribution["Distribution"]
        TC["Video Transcoder Workflow"]
        RSS_GEN["RSS Feed Generation"]
        JB["JioBharat Pipeline"]
        AUTO["Auto Summarization API"]
    end

    subgraph Consumers["Downstream Consumers"]
        JHS["JioHotstar"]
        JBD["JioBharat Devices"]
        CMSUI["CMS UI"]
        VCDN["Video CDN"]
    end

    RSS --> HL & SUM & NV & NS & WS
    YT --> YTV & YTS
    API --> NV & NS
    MANUAL --> NV & NS
    CMS --> AUTO

    HL & SUM & NV & NS --> IMGCDN
    HL & SUM & NV & NS & YTV & YTS --> REDIS
    SUM --> LLM

    IMGCDN --> MONGO
    YTV & YTS & WS --> MONGO
    LLM --> MONGO
    AUTO --> MONGO
    NV --> GCS

    MONGO --> TC & RSS_GEN
    PRODMONGO --> JB
    TC --> VCDN
    RSS_GEN --> GCS --> JHS
    JB --> JBD
    AUTO --> CMSUI
```

---

## 3. Pipeline Architectures (Mermaid)

### 3.1 Headlines Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant FETCH as fetchfeedsdata
    participant PS1 as Pub/Sub: raw_feeds_data
    participant PROC as processheadlines
    participant PS2 as Pub/Sub: image_cdn
    participant CDN as imagecdn
    participant PS3 as Pub/Sub: processed_data
    participant PS4 as Pub/Sub: rejected_data
    participant DB1 as MongoDB: raw_headlines
    participant DB2 as MongoDB: hygiene_failures
    participant REDIS as Redis
    participant SCRAPER as Article Scraper

    SCH->>FETCH: HTTP trigger (cron)
    FETCH->>FETCH: Read GCS config CSV (100 threads)
    FETCH->>FETCH: Fetch all publisher RSS/JSON feeds
    FETCH->>PS1: Publish per-feed batch

    PS1->>PROC: Push subscription
    PROC->>REDIS: Dedup (title cache + ID cache, 48h TTL)
    PROC->>SCRAPER: Scrape article text (primary + fallback)
    PROC->>PROC: Map fields, generate sourceId, apply UTM params
    PROC->>PS2: Publish processed records

    PS2->>CDN: Push subscription
    CDN->>CDN: Download thumbnail, resize to 5 renditions
    CDN->>CDN: Upload to GCS img-cdn-bucket

    alt Thumbnail Success
        CDN->>PS3: Publish processed headlines
        PS3->>DB1: CloudEvent → insert_many
    else Thumbnail Failed
        CDN->>PS4: Publish rejected headlines
        PS4->>DB2: CloudEvent → insert_many
    end
```

### 3.2 Summaries Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant FETCH as FetchFeedsData
    participant PS1 as Pub/Sub: FeedsData
    participant PROC as ProcessSummaries
    participant PS2 as Pub/Sub: image_cdn
    participant PS3 as Pub/Sub: HygineFailure
    participant CDN as imagecdn
    participant PS4 as Pub/Sub: ProcessedData
    participant DB as MongoDB: raw_summaries
    participant LLM as summarization-async
    participant REDIS as Redis
    participant GEMINI as Gemini 2.5 Flash

    SCH->>FETCH: HTTP trigger (cron)
    FETCH->>FETCH: Read GCS config, fetch feeds (100 threads)
    FETCH->>PS1: Publish per-feed batch

    PS1->>PROC: Background trigger
    PROC->>REDIS: Dedup (title cache, 48h TTL)
    PROC->>PROC: Hygiene check (English only)

    alt Passes Hygiene
        PROC->>PS2: Publish to image CDN
        PS2->>CDN: Process thumbnails
        CDN->>PS4: Publish processed summaries
        PS4->>DB: CloudEvent → insert_many
    else Fails Hygiene
        PROC->>PS3: Publish per-record
        PS3->>LLM: Pull subscription
        LLM->>GEMINI: Pass 1: URL mode (url_context tool)
        alt URL Access Fails
            LLM->>LLM: Fetch via proxy service
            LLM->>GEMINI: Pass 2: Content mode
        end
        LLM->>LLM: Re-run hygiene on LLM output
        LLM->>DB: Upsert by sourceId
    end
```

### 3.3 YouTube Videos Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant FETCH as FetchYTChannelsData
    participant PS1 as Pub/Sub: channel_data
    participant PROC as ProcessYTChannelsData
    participant PS2 as Pub/Sub: processed_data
    participant PS3 as Pub/Sub: scraper_metadata
    participant DB as MongoDB: raw_videos
    participant REDIS as Redis

    SCH->>FETCH: HTTP trigger (cron)
    FETCH->>FETCH: Read GCS config (ISO-8859-1)
    FETCH->>FETCH: Scrape YouTube channel pages (10 threads)
    FETCH->>FETCH: Parse ytInitialData → videoRenderer
    FETCH->>PS1: Publish per-channel video list

    PS1->>PROC: Background trigger
    PROC->>REDIS: Dedup (video_id+cat+lang, 48h TTL)
    PROC->>PROC: 24h recency filter, map fields

    alt to_scrape = false
        PROC->>PS2: Batch publish processed videos
        PS2->>DB: CloudEvent → insert_many
    else to_scrape = true
        PROC->>PS3: Per-record publish (with HLS URLs)
        Note over PS3: External YouTube scraper consumes
    end
```

### 3.4 Native Videos Ingestion

```mermaid
flowchart TB
    subgraph Source1["Source 1: Partner API"]
        API_REQ["POST /v1/de-native-video/upload/"]
        API_PROC["Upload video to GCS<br/>Upload thumbnail to GCS"]
    end

    subgraph Source2["Source 2: Manual Upload"]
        MAN_UI["Editorial Web UI"]
        MAN_SIGN["Generate GCS signed URL"]
        MAN_UP["Direct browser upload to GCS"]
    end

    subgraph Source3["Source 3: MRSS Feeds"]
        MRSS_FETCH["mrssvideos-fetchfeedsdata<br/>ThreadPool(100)"]
        MRSS_PROC["mrssvideos-processvideos<br/>Redis dedup + field mapping"]
    end

    PS_CDN["Pub/Sub: image_cdn<br/>(content_type=videos)"]
    CDN["imagecdn<br/>Download + resize thumbnails"]
    PS_PROCESSED["Pub/Sub: ProcessedData"]
    DOWNLOAD["mrssvideos-downloadvideos<br/>Stream video to GCS"]
    PUSH["mrssvideos-pushtomongodb"]
    DB[("MongoDB: raw_videos_rss")]
    TC["→ Video Transcoder Workflow"]

    API_REQ --> API_PROC --> PS_CDN
    MAN_UI --> MAN_SIGN --> MAN_UP --> PS_CDN
    MRSS_FETCH --> MRSS_PROC --> PS_CDN

    PS_CDN --> CDN --> PS_PROCESSED
    PS_PROCESSED --> DOWNLOAD --> DB
    PS_PROCESSED --> PUSH --> DB
    DB --> TC
```

### 3.5 Video Transcoder Workflow

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant BATCH as sftp-batching
    participant PS1 as Pub/Sub: batching
    participant SFTP_PUSH as push-to-sftp
    participant GCS as GCS: raw_videos
    participant SFTP as SFTP Server
    participant EXT as CPP/SAAS Transcoder
    participant STATUS as update-content-status
    participant API as VOD API
    participant DB as MongoDB: raw_videos_rss
    participant PS2 as Pub/Sub: processed_data

    SCH->>BATCH: HTTP trigger (cron)
    BATCH->>DB: Query: initiated, limit 30
    BATCH->>PS1: Publish each record
    BATCH->>DB: Update: initiated → queued

    PS1->>SFTP_PUSH: Push subscription
    SFTP_PUSH->>DB: Update: queued → submitting
    SFTP_PUSH->>GCS: Download video MP4
    SFTP_PUSH->>SFTP_PUSH: Generate 54-field CSV
    SFTP_PUSH->>SFTP: Upload .mp4 + .csv
    SFTP_PUSH->>DB: Update: submitting → submitted

    Note over EXT: External transcoder processes video

    SCH->>STATUS: HTTP trigger (polling cron)
    STATUS->>API: GET getallcontentstatus (HMAC auth)
    STATUS->>API: GET getcontentdetails (5 threads)
    STATUS->>STATUS: Construct HLS URLs (AVC + HEVC)
    STATUS->>DB: Update: submitted → completed
    STATUS->>PS2: Publish with HLS URLs
```

### 3.6 YouTube Shorts Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant SCRAPE as ScrapeVideoIds
    participant YT_PAGE as YouTube /shorts page
    participant DB as MongoDB: raw_shorts
    participant PS1 as Pub/Sub: cron_based
    participant API_FUNC as YouTubeAPIToMongoDB
    participant YT_API as YouTube Data API v3
    participant YT_URL as YouTube /shorts/{id}
    participant PS2 as Pub/Sub: raw_shorts

    SCH->>SCRAPE: HTTP trigger (cron)
    SCRAPE->>YT_PAGE: Scrape channel shorts pages
    SCRAPE->>SCRAPE: Parse ytInitialData → videoId (JSONPath)
    SCRAPE->>DB: Filter out existing IDs (aggregation)
    SCRAPE->>PS1: Publish new video IDs

    PS1->>API_FUNC: Background trigger
    API_FUNC->>YT_API: videos.list (batches of 50)
    API_FUNC->>API_FUNC: Filter: 0 < duration <= 60s
    API_FUNC->>YT_URL: Redirect check (200 = short)
    API_FUNC->>API_FUNC: 24h recency filter
    API_FUNC->>DB: insert_many (shorts data)
    API_FUNC->>PS2: Publish enriched shorts
```

### 3.7 Native Shorts Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant FETCH as mrssshorts-fetchfeedsdata
    participant PS1 as Pub/Sub: RawFeedsData
    participant PROC as mrssshorts-processvideos
    participant PS_CDN as Pub/Sub: image_cdn
    participant CDN as imagecdn
    participant PS2 as Pub/Sub: ProcessedData
    participant DL as mrssshorts-downloadvideos
    participant GCS as GCS: raw_videos
    participant DB as MongoDB: raw_videos_rss
    participant REDIS as Redis

    SCH->>FETCH: HTTP trigger (cron)
    FETCH->>FETCH: Fetch MRSS/RSS feeds (100 threads)
    FETCH->>PS1: Publish per-feed batch

    PS1->>PROC: Push subscription
    PROC->>REDIS: Dedup (de_mrss_shorts_cache, 48h)
    PROC->>PROC: Map fields (contentType=shorts, portrait)
    PROC->>PS_CDN: Publish thumbnail for CDN
    PROC->>DB: insert_many
    PROC->>PS2: Publish per-record

    PS_CDN->>CDN: Process thumbnails

    PS2->>DL: Push subscription
    DL->>GCS: Stream download MP4
    Note over DL: NO transcoder (shorts skip transcoding)
    DL->>DB: Update: processingStatus=completed
```

### 3.8 Webstories Ingestion

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant FETCH as RawWebStoriesIngestion
    participant PUB as Publisher APIs/Feeds
    participant PS as Pub/Sub: RawWebStoriesIngestion
    participant DB as MongoDB: raw_web_stories

    SCH->>FETCH: HTTP trigger (cron)
    FETCH->>FETCH: Read local publishers.csv
    loop Each Publisher
        alt type = api
            FETCH->>PUB: HTTP GET JSON
        else type = feed
            FETCH->>PUB: feedparser parse
        end
        FETCH->>FETCH: Transform via mapping JSON
        FETCH->>FETCH: Validate thumbnail URL (HTTP GET)
        FETCH->>FETCH: Apply UTM params (JioNewsStories)
    end
    FETCH->>PS: Publish per-publisher batch
    PS->>DB: CloudEvent → insert_many
```

### 3.9 JioBharat Video Summaries

```mermaid
sequenceDiagram
    participant SCH as Cloud Scheduler
    participant AGG as AggregateSummaries
    participant PROD as PROD MongoDB: summaries
    participant DE_DB as DE MongoDB: jio_bharat
    participant PS as Pub/Sub: Aggregate
    participant PUSH as pushtosftpprod
    participant ATTR as Image Attributor
    participant GCS_A as GCS: audio-summaries
    participant GCS_I as GCS: img-cdn-bucket
    participant SFTP as SFTP: mediaftp1.ril.com

    SCH->>AGG: HTTP trigger (cron)
    AGG->>PROD: Aggregate: today, 8 languages, audio=true, limit 50/lang
    AGG->>DE_DB: Query: already processed (isSuccess=true)
    AGG->>AGG: Filter out processed summaries
    AGG->>PS: Publish unprocessed list

    PS->>PUSH: Background trigger
    loop Each Summary
        PUSH->>ATTR: POST /generate-image (title, publisher, image_url)
        Note over ATTR: Jinja2 → Chromium screenshot → JPEG → GCS
        PUSH->>GCS_A: Download audio (prd/{id}.mp3)
        PUSH->>GCS_I: Download attributed image
        PUSH->>SFTP: Upload audio + image to language folder
    end
    PUSH->>DE_DB: Insert processing status records
```

### 3.10 Auto Summarization

```mermaid
sequenceDiagram
    participant CMS as CMS Editorial
    participant API as FastAPI: /summarize
    participant GEMINI as Gemini 2.5 Flash
    participant PROXY as Article Render Proxy
    participant DB as MongoDB: auto_summarization

    CMS->>API: POST /v1/jionews-summarization/summarize
    Note over API: {article_url?, article_content?, source_headline_id}

    alt article_url provided
        API->>GEMINI: Generate summary (URL mode, url_context tool)
        alt URL access failure detected
            API->>PROXY: GET /proxy?url={encoded}
            PROXY-->>API: Raw HTML content
            API->>GEMINI: Retry with article_content
        end
    else article_content provided
        API->>GEMINI: Generate summary (content mode)
    end

    API->>DB: Upsert by sourceId ($set, $setOnInsert, $inc updateCount)
    API-->>CMS: {sourceId, summary, updateCount, createdAt, updatedAt}
```

### 3.11 RSS Feed Generation

```mermaid
flowchart TB
    subgraph Videos_RSS["Videos HLS RSS"]
        VA["AggregateDataLanguageSplit<br/>Top 100/language<br/>transcoderStatus=completed"]
        VP["ProcessRssFeedLanguageSplit<br/>RSS 2.0 + Media RSS<br/>Includes hlsAvcUrl + hlsHevcUrl"]
    end

    subgraph Shorts_RSS["Shorts RSS"]
        SA["AggregateDataLanguageSplit<br/>Top 100/language<br/>processingStatus=completed"]
        SP["ProcessRssFeedLanguageSplit<br/>RSS 2.0 + Media RSS<br/>NO HLS elements, raw MP4"]
    end

    DB[("MongoDB: raw_videos_rss")]
    PS_V["Pub/Sub: Videos Aggregated"]
    PS_S["Pub/Sub: Shorts Aggregated"]
    GCS_V["GCS: rss/videos_hls/{lang}/rss.xml"]
    GCS_S["GCS: rss/shorts/{lang}/rss.xml"]
    JHS["JioHotstar"]

    DB --> VA --> PS_V --> VP --> GCS_V --> JHS
    DB --> SA --> PS_S --> SP --> GCS_S --> JHS
```

---

## 4. Shared Infrastructure Overview

### 4.1 Image CDN (Shared Function)

Central image processing hub consuming from `NewRawHeadlinesIngestion_image_cdn` topic. Routes by `content_type` field. Resizes to 5 renditions, uploads to `img-cdn-bucket`. CDN domain: `icdn.jionews.com`.

**Details:** `shared/image-cdn/`

### 4.2 LLM Integration

Two Gemini 2.5 Flash-powered services: async (Pub/Sub subscriber for hygiene failures) and sync (FastAPI for CMS shortlisting). Both use two-pass strategy with proxy fallback.

**Details:** `shared/llm-integration/`

### 4.3 Redis Deduplication

6 sorted sets across 4 pipelines, all 48h TTL, ZADD/ZSCORE pattern with time-based expiration scores.

**Details:** `shared/redis-caching/`

---

## 5. Infrastructure Registries (Quick Reference)

### 5.1 MongoDB Collections

| Collection | Pipeline | DB | Details |
|---|---|---|---|
| `raw_headlines_ingestion_data` | Headlines | ingestion-data | `shared/infrastructure/MONGODB-REGISTRY.md` |
| `headlines_hygiene_failures` | Headlines (rejected) | ingestion-data | |
| `raw_summaries_insgestion_data` | Summaries | ingestion-data | **Note: typo in prod** |
| `raw_videos_ingestion_data` | YouTube Videos | ingestion-data | |
| `raw_videos_rss` | Native Videos + Shorts | ingestion-data | Shared, differentiated by contentType |
| `raw_short_videos_ingestion_data` | YouTube Shorts | ingestion-data | |
| `raw_web_stories_ingestion_data` | Webstories | ingestion-data | |
| `jio_bharat_summaries` | JioBharat | ingestion-data | |
| `auto_summarization` | Auto Summarization | ingestion-data | |
| `summaries` | JioBharat (read-only) | pie-production | Cross-cluster |

**Full details:** `shared/infrastructure/MONGODB-REGISTRY.md`

### 5.2 Pub/Sub Topics (23 total)

**Full registry:** `shared/infrastructure/PUBSUB-REGISTRY.md`

### 5.3 GCS Buckets (5 total)

| Bucket | Purpose |
|---|---|
| `de-raw-ingestion` | Pipeline config CSVs |
| `img-cdn-bucket` | Image CDN (5 renditions + defaults) |
| `hls_video_transcoder_storage_output_files` | Raw videos + RSS feeds |
| `de_video_transcoder_input` | Transcoder input staging |
| `audio-summaries-bucket` | TTS audio for JioBharat |

**Full details:** `shared/infrastructure/GCS-REGISTRY.md`

### 5.4 Secrets (5 total)

| Secret | Purpose |
|---|---|
| `mongosh_de_uri` | MongoDB DE cluster URI |
| `GEMINI_API_KEY` | Google Gemini API key |
| `yt_api_access_token` | YouTube Data API v3 key |
| `compute_engine_service_account_private_key` | GCS/Pub/Sub service account |
| `de_trascoder_sftp` | SFTP credentials (JSON) |

**Full details:** `shared/infrastructure/SECRETS-REGISTRY.md`

### 5.5 External Dependencies

| Service | Type |
|---|---|
| Article Scraper (Primary + Fallback) | HTTP API |
| Article Render Proxy | Cloud Run service |
| CPP/SAAS Transcoder API | HTTP API (HMAC auth) |
| YouTube Data API v3 | Google API |
| Google Gemini API | LLM API |
| Redis (`34.93.131.211:6379`) | Cache |
| SFTP (Transcoder + JioBharat) | File transfer |
| CDN: `icdn.jionews.com`, `vcdn.jionews.com`, `videos.jionews.com` | Content delivery |

**Full details:** `shared/infrastructure/EXTERNAL-DEPENDENCIES.md`

---

## 6. Deployment Models

| Model | Services | Trigger |
|---|---|---|
| Cloud Functions Gen 1 | Processing stages | Pub/Sub background (`message, context`) |
| Cloud Functions Gen 2 | All PushToMongoDB | CloudEvent (`@functions_framework.cloud_event`) |
| Cloud Functions (HTTP) | Fetch stages, some processors | HTTP (Cloud Scheduler / Pub/Sub push) |
| Cloud Run (Flask) | JioNewsDENativeVideos, yt-manual-upload | REST API (port 8080) |
| Cloud Run (FastAPI) | Image Attributor, Auto Summarization | REST API |
| Cloud Run (Subscriber) | summarization-async | Pub/Sub pull subscriber |

---

## 7. Common Architectural Pattern

All ingestion pipelines follow this pattern with per-pipeline variations:

```mermaid
flowchart LR
    TRIGGER["Scheduler/HTTP/API"] --> FETCH["Fetch Stage<br/>Read GCS config<br/>Fetch feeds/data"]
    FETCH --> |"Pub/Sub"| PROCESS["Process Stage<br/>Redis dedup<br/>Field mapping<br/>Validation"]
    PROCESS --> |"Pub/Sub"| CDN["Image CDN<br/>Download, resize<br/>Upload to GCS"]
    CDN --> |"Pub/Sub"| PERSIST["Persist Stage<br/>MongoDB insert"]
```

---

## 8. Known Gaps & Ambiguities

See `pipelines/*/AS-IS.md` for pipeline-specific gaps. Cross-cutting gaps:

| Gap | Description |
|---|---|
| No CI/CD configs | Deployment mechanism undocumented |
| No requirements.txt | Python dependency versions not pinned |
| No Cloud Scheduler configs | Cron frequencies unknown |
| No Pub/Sub subscription configs | Push/pull modes, ack deadlines undocumented |
| No Cloud Function deployment configs | Memory, timeout, instances undocumented |
| No structured logging | Only basic `print()` statements |
| Hardcoded credentials | Redis password, PROD MongoDB URI, transcoder API keys in source |
| Collection name typo | `raw_summaries_insgestion_data` in production |

---

*For detailed pipeline specifications, navigate to `pipelines/<pipeline-name>/`. For infrastructure registries, see `shared/infrastructure/`. For skill definitions, see `skills/`.*
