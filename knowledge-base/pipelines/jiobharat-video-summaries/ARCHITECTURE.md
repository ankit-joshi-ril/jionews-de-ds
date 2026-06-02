# JioBharat Video Summaries - Architecture

## System Context Diagram

```mermaid
flowchart LR
    subgraph "PROD Environment"
        PROD_MONGO["PROD MongoDB:\npie-production.\nsummaries"]
        GCS_AUDIO["GCS:\naudio-summaries-bucket\n/prd/"]
    end

    subgraph "GCP Project: jiox-328108"
        CF1["Cloud Function:\nJioBharat_Aggregate\nSummariesPROD"]
        PS["Pub/Sub:\nJioBharat_Aggregate\nSummariesProd"]
        CF2["Cloud Function:\njihobharat-\npushtosftpprod"]
        IMG_ATTR["FastAPI Service:\nImage Attributor\nservice.jionews.com"]
        GCS_IMG["GCS:\nimg-cdn-bucket\n/jio_bharat/"]
        SM["Secret Manager"]
    end

    subgraph "DE Environment"
        DE_MONGO["DE MongoDB:\ningestion-data.\njio_bharat_summaries"]
    end

    subgraph "Delivery"
        SFTP["SFTP Server:\nmediaftp1.ril.com:33001"]
        JIOBHARAT["JioBharat\nDevices"]
    end

    CF1 -->|"Aggregation\npipeline"| PROD_MONGO
    CF1 -->|"Dedup query\n(isSuccess=true)"| DE_MONGO
    SM -->|"mongosh_de_uri"| CF1
    SM -->|"mongosh_de_uri"| CF2
    CF1 -->|"Publish unprocessed"| PS
    PS -->|"Trigger"| CF2
    CF2 -->|"POST generate-image"| IMG_ATTR
    IMG_ATTR -->|"Upload JPEG"| GCS_IMG
    CF2 -->|"Download MP3"| GCS_AUDIO
    CF2 -->|"Download JPEG"| GCS_IMG
    CF2 -->|"Upload audio + image"| SFTP
    CF2 -->|"Insert status"| DE_MONGO
    SFTP -->|"Serve content"| JIOBHARAT
```

## Detailed Pipeline Flow

```mermaid
sequenceDiagram
    participant SCHED as Cloud Scheduler
    participant CF1 as JioBharat_AggregateSummariesPROD
    participant PROD as PROD MongoDB (pie-production)
    participant DE_DB as DE MongoDB (ingestion-data)
    participant PS as Pub/Sub (JioBharat)
    participant CF2 as jiobharat-pushtosftpprod
    participant IMG_API as Image Attributor API
    participant GCS_IMG as GCS (img-cdn-bucket)
    participant GCS_AUD as GCS (audio-summaries-bucket)
    participant SFTP as SFTP Server

    Note over SCHED,SFTP: Stage 1 - Aggregate and Deduplicate

    SCHED->>CF1: HTTP trigger
    CF1->>PROD: Aggregation pipeline on summaries
    Note over CF1,PROD: Match: today IST, 8 languages,<br/>isAudioSummaryGenerated=true,<br/>isBreaking=false
    Note over CF1,PROD: Sort: createdAt desc
    Note over CF1,PROD: Group by language, limit 50 per language
    PROD-->>CF1: Up to 400 summaries (50 x 8 languages)

    CF1->>DE_DB: Query jio_bharat_summaries (isSuccess=true)
    DE_DB-->>CF1: Set of already-processed summary_ids

    Note over CF1: Compute unprocessed = PROD - DE processed

    loop For each unprocessed summary
        CF1->>PS: Publish summary record
    end

    Note over SCHED,SFTP: Stage 2 - Generate Image, Download, Upload to SFTP

    PS->>CF2: Trigger with summary record

    CF2->>IMG_API: POST /v1/image-attributor/generate-image
    Note over CF2,IMG_API: Body: {title, publisher, image_url, summary_id}
    IMG_API->>IMG_API: Render Jinja2 HTML template
    IMG_API->>IMG_API: Headless Chromium screenshot (1920x1080)
    IMG_API->>GCS_IMG: Upload jio_bharat/{summary_id}.jpeg
    IMG_API-->>CF2: Image generation response

    CF2->>GCS_AUD: Download prd/{summary_id}.mp3
    GCS_AUD-->>CF2: Audio MP3 data

    CF2->>GCS_IMG: Download jio_bharat/prod/{summary_id}.jpeg
    GCS_IMG-->>CF2: Image JPEG data

    Note over CF2: Determine language folder mapping
    Note over CF2: Construct SFTP paths with date pattern

    CF2->>SFTP: Upload {summary_id}_{lang}_{date}.mp3
    CF2->>SFTP: Upload {summary_id}_{lang}_{date}.jpeg
    SFTP-->>CF2: Upload confirmation

    CF2->>DE_DB: Insert status (isSuccess=true, uploadedPaths)
```

## Stage 1: Aggregation Flow

```mermaid
flowchart TD
    A["Start: HTTP trigger"] --> B["Connect to PROD MongoDB\n(base64-encoded hardcoded URI)"]
    B --> C["Execute aggregation on\npie-production.summaries"]

    C --> D["$match:\ncreatedAt = today IST\nlanguage.code in 8 languages\nisAudioSummaryGenerated = true\nisBreaking = false"]
    D --> E["$sort: createdAt desc"]
    E --> F["$group: by language\ncollect all docs"]
    F --> G["$slice: limit 50 per language"]
    G --> H["$unwind + $replaceRoot:\nflatten to individual docs"]

    H --> I["Connect to DE MongoDB\n(mongosh_de_uri from Secret Manager)"]
    I --> J["Query jio_bharat_summaries\nwhere isSuccess = true"]
    J --> K["Compute set difference:\nunprocessed summaries"]
    K --> L{Unprocessed\nsummaries found?}
    L -->|No| M["End: Nothing to process"]
    L -->|Yes| N["Publish each to Pub/Sub:\nJioBharat_AggregateSummariesProd"]
    N --> O["End: Stage 1 complete"]
```

## Stage 2: SFTP Push Flow

```mermaid
flowchart TD
    A["Start: Pub/Sub message\n(summary record)"] --> B["Extract summary metadata:\ntitle, publisher, image_url,\nsummary_id, language"]

    B --> C["POST to Image Attributor:\nservice.jionews.com/v1/\nimage-attributor/generate-image"]
    C --> D{Image generation\nsucceeded?}
    D -->|No| E["Record failure in MongoDB:\nisSuccess=false\nerrorMessage set"]
    D -->|Yes| F["Download audio:\naudio-summaries-bucket/\nprd/{summary_id}.mp3"]

    F --> G{Audio download\nsucceeded?}
    G -->|No| E
    G -->|Yes| H["Download image:\nimg-cdn-bucket/jio_bharat/\nprod/{summary_id}.jpeg"]

    H --> I{Image download\nsucceeded?}
    I -->|No| E
    I -->|Yes| J["Determine language folder:\nHIN -> taaza_kabrein_hin\nTAM -> ungal_Seithigal_tam\netc."]

    J --> K["Connect to SFTP:\nmediaftp1.ril.com:33001\nuser: FT_jionews_livenews"]

    K --> L["Upload to SFTP:\n/media/prod/{lang_folder}/\n{summary_id}_{lang}_{date}.jpeg"]
    L --> M["Upload to SFTP:\n/media/prod/{lang_folder}/\n{summary_id}_{lang}_{date}.mp3"]

    M --> N{SFTP upload\nsucceeded?}
    N -->|No| E
    N -->|Yes| O["Record success in MongoDB:\nisSuccess=true\nuploadedPaths set"]

    E --> P["End: Summary processed"]
    O --> P
```

## Image Attributor Service Architecture

```mermaid
flowchart TD
    subgraph "FastAPI Service"
        A["POST /v1/image-attributor/\ngenerate-image"] --> B["Parse request:\ntitle, publisher,\nimage_url, summary_id"]
        B --> C["Render Jinja2 HTML template\nwith summary metadata"]
        C --> D["Launch headless Chromium\nvia pyppeteer"]
        D --> E["Set viewport: 1920x1080"]
        E --> F["Navigate to rendered HTML"]
        F --> G["Capture JPEG screenshot"]
        G --> H["Upload to GCS:\nimg-cdn-bucket/jio_bharat/\n{summary_id}.jpeg"]
        H --> I["Return GCS path"]
    end

    subgraph "Chromium Configuration"
        J["Args:\n--no-sandbox\n--disable-setuid-sandbox"]
    end

    D -.-> J
```

## Infrastructure Topology

```mermaid
flowchart TB
    subgraph "Cloud Functions"
        CF1["JioBharat_AggregateSummariesPROD\n(HTTP trigger)"]
        CF2["jiobharat-pushtosftpprod\n(Pub/Sub trigger)"]
    end

    subgraph "Pub/Sub"
        PS["JioBharat_AggregateSummariesProd"]
    end

    subgraph "FastAPI Microservice"
        IMG["Image Attributor\nservice.jionews.com\n/v1/image-attributor/generate-image"]
    end

    subgraph "Google Cloud Storage"
        GCS_A["audio-summaries-bucket\n/prd/{summary_id}.mp3"]
        GCS_I["img-cdn-bucket\n/jio_bharat/{summary_id}.jpeg\n/jio_bharat/prod/{summary_id}.jpeg"]
    end

    subgraph "MongoDB"
        PROD["PROD: pie-production.summaries\n(source data)"]
        DE["DE: ingestion-data.jio_bharat_summaries\n(status tracking)"]
    end

    subgraph "External"
        SFTP["SFTP: mediaftp1.ril.com:33001\nuser: FT_jionews_livenews"]
    end

    subgraph "Secret Manager"
        SM["mongosh_de_uri"]
    end

    CF1 --> PROD
    CF1 --> DE
    CF1 --> SM
    CF1 --> PS
    PS --> CF2
    CF2 --> SM
    CF2 --> IMG
    IMG --> GCS_I
    CF2 --> GCS_A
    CF2 --> GCS_I
    CF2 --> SFTP
    CF2 --> DE
```

## SFTP Directory Structure

```mermaid
flowchart TD
    ROOT["/media/prod/"] --> HIN["taaza_kabrein_hin/"]
    ROOT --> KAN["pramukha_Suddi_kan/"]
    ROOT --> TAM["ungal_Seithigal_tam/"]
    ROOT --> TEL["itivali_varthalu_tel/"]
    ROOT --> MAR["taajya_baatmya_mar/"]
    ROOT --> BAN["tatka_sangbad_ban/"]
    ROOT --> GUJ["taaza_samachar_guj/"]
    ROOT --> MAL["puthiya_varthakal_mal/"]

    HIN --> HIN_MP3["{summary_id}_HIN_{date}.mp3"]
    HIN --> HIN_JPG["{summary_id}_HIN_{date}.jpeg"]
    TAM --> TAM_MP3["{summary_id}_TAM_{date}.mp3"]
    TAM --> TAM_JPG["{summary_id}_TAM_{date}.jpeg"]
```

## Networking and Security

- **PROD MongoDB:** Accessed via a base64-encoded hardcoded connection URI (not Secret Manager). This is a known deviation from standard security practices.
- **DE MongoDB:** Accessed via `mongosh_de_uri` from GCP Secret Manager.
- **Image Attributor:** Internal service at `service.jionews.com`, accessed over HTTPS.
- **GCS Buckets:** Accessed using default service account credentials.
- **SFTP:** Accessed via SSH on port 33001 with user `FT_jionews_livenews`. Credentials are stored in the function configuration.
- **Chromium:** Runs with `--no-sandbox` flag for container compatibility. This disables the Chromium sandbox security model.
