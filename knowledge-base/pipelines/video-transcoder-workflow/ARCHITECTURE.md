# Video Transcoder Workflow -- Architecture Document

## System Context

The Video Transcoder Workflow pipeline bridges the internal JioNews video ingestion system with an external CPP/SAAS transcoding service. It manages video delivery via SFTP, tracks transcoding status through the external API, and publishes completed HLS URLs for downstream consumption. All components run on Google Cloud Platform (project: `jiox-328108`).

## High-Level Architecture

```mermaid
flowchart TB
    subgraph "Schedulers"
        CS1[Cloud Scheduler<br>Batching]
        CS2[Cloud Scheduler<br>Status Polling]
    end

    subgraph "Cloud Functions"
        CF1[transcoder-push-to-sftp-batching]
        CF2[transcoder-push-to-sftp]
        CF3[transcoder-update-content-status]
    end

    subgraph "Data Stores"
        MongoDB[(MongoDB:<br>raw_videos_rss)]
        GCS[(GCS:<br>raw_videos/)]
        SM[Secret Manager]
    end

    subgraph "Pub/Sub Topics"
        PS1[transcoder-push-to-sftp-batching]
        PS2[raw_native_videos]
        PS3[NewRawVideosIngestion_processed_data]
    end

    subgraph "External Systems"
        SFTP[SFTP Server<br>/media/newcpp/jionews2jiohotstar/watch/]
        CPP[CPP/SAAS API<br>cppapi-saas.media.jio.com]
        CDN[videos.jionews.com<br>HLS CDN]
    end

    CS1 -->|Trigger| CF1
    CF1 -->|Query initiated records| MongoDB
    CF1 -->|Publish per record| PS1
    CF1 -->|Update: initiated->queued| MongoDB

    PS1 -->|Push trigger| CF2
    CF2 -->|Download video| GCS
    CF2 -->|Get SFTP creds| SM
    CF2 -->|Upload .mp4 + .csv| SFTP
    CF2 -->|Update: queued->submitting->submitted| MongoDB

    CS2 -->|Trigger| CF3
    CF3 -->|Poll status API| CPP
    CF3 -->|Get content details| CPP
    CF3 -->|Construct HLS URLs| CDN
    CF3 -->|Publish completed| PS2
    CF3 -->|Publish completed| PS3
    CF3 -->|Update: submitted->completed| MongoDB
```

## Detailed Sequence: Batching and SFTP Delivery

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant Batch as transcoder-push-to-sftp-batching
    participant Mongo as MongoDB
    participant PS as Pub/Sub: batching topic
    participant SFTP_Fn as transcoder-push-to-sftp
    participant GCS as GCS (raw_videos)
    participant SM as Secret Manager
    participant SFTP as SFTP Server

    CS->>Batch: Scheduled trigger
    Batch->>Mongo: Query: contentType=videos,<br>processingStatus=completed,<br>transcoderProcessingStatus=initiated<br>(limit=30)
    Mongo-->>Batch: Up to 30 records

    loop Each record
        Batch->>PS: Publish record
        Batch->>Mongo: Update transcoderProcessingStatus: initiated -> queued
    end

    PS->>SFTP_Fn: Push trigger (per message)
    SFTP_Fn->>Mongo: Update transcoderProcessingStatus: queued -> submitting
    SFTP_Fn->>GCS: Download {video_id}.mp4
    GCS-->>SFTP_Fn: Video file bytes

    SFTP_Fn->>SFTP_Fn: Generate 54-field CSV<br>(FileName, ContentType=Video, Language)
    SFTP_Fn->>SFTP_Fn: Normalize language (Bangla -> Bengali)

    SFTP_Fn->>SM: Get secret: de_trascoder_sftp
    SM-->>SFTP_Fn: SFTP credentials (JSON)

    SFTP_Fn->>SFTP: Upload {video_id}.mp4
    SFTP_Fn->>SFTP: Upload {video_id}.csv
    SFTP-->>SFTP_Fn: Upload confirmed

    SFTP_Fn->>Mongo: Update transcoderProcessingStatus: submitting -> submitted

    Note over SFTP_Fn,Mongo: On failure: status set to "failed"
```

## Detailed Sequence: Status Polling and HLS URL Publishing

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant Poll as transcoder-update-content-status
    participant CPP as CPP/SAAS API
    participant Mongo as MongoDB
    participant PS1 as Pub/Sub: raw_native_videos
    participant PS2 as Pub/Sub: processed_data

    CS->>Poll: Scheduled trigger

    Poll->>Poll: Generate HMAC-SHA256 signature<br>(url_path + jionews1 + epoch)

    loop Paginated (limit=100)
        Poll->>CPP: GET vod/v1/getallcontentstatus<br>(status=Pu, limit=100)
        CPP-->>Poll: Page of published content
    end

    loop Each published item (ThreadPoolExecutor max=5)
        loop Retry (max 3, delay 5s)
            Poll->>CPP: GET vod/v1/getcontentdetails/{content_id}/jionews
            CPP-->>Poll: Content details + HLS paths
        end

        Poll->>Poll: Construct HLS URL:<br>https://videos.jionews.com/jvodnews + path<br>(replace index with master-)

        Poll->>PS1: Publish with HLS URLs
        Poll->>PS2: Publish with HLS URLs
        Poll->>Mongo: Update transcoderProcessingStatus: submitted -> completed
    end
```

## State Machine Diagram

```mermaid
flowchart LR
    A["(not set)"] -->|"Native Videos<br>Ingestion"| B[initiated]
    B -->|"Batching function<br>publishes to topic"| C[queued]
    C -->|"SFTP function<br>starts processing"| D[submitting]
    D -->|"SFTP upload<br>succeeds"| E[submitted]
    D -->|"SFTP upload<br>fails"| F[failed]
    E -->|"CPP API returns<br>status=Pu"| G[completed]
    B -->|"Any error"| F
    C -->|"Any error"| F
    E -->|"Transcoding<br>error"| F
```

## Component Details

### transcoder-push-to-sftp-batching

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler |
| MongoDB query limit | 30 records |
| Output | Pub/Sub: `transcoder-push-to-sftp-batching` |
| Status transition | `initiated` -> `queued` |

### transcoder-push-to-sftp

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub push |
| Input | Single video record from batching topic |
| GCS source | `hls_video_transcoder_storage_output_files/raw_videos/` |
| SFTP destination | `/media/newcpp/jionews2jiohotstar/watch/` |
| Artifacts | `{video_id}.mp4` + `{video_id}.csv` |
| Status transitions | `queued` -> `submitting` -> `submitted` (or `failed`) |
| Credentials | Secret Manager: `de_trascoder_sftp` |

### transcoder-update-content-status

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler |
| External API | `https://cppapi-saas.media.jio.com` |
| Auth | HMAC-SHA256 (access key: `jionews1`) |
| Concurrency | `ThreadPoolExecutor(max_workers=5)` |
| Retry | 3 attempts, 5-second delay |
| Pagination | limit=100 per page |
| Status filter | `"Pu"` (Published) |
| HLS CDN | `https://videos.jionews.com/jvodnews` |
| Output topics | `raw_native_videos`, `NewRawVideosIngestion_processed_data` |
| Status transition | `submitted` -> `completed` |

## Infrastructure Dependencies

| Resource | Type | Identifier |
|---|---|---|
| GCP Project | Project | `jiox-328108` (266686822828) |
| GCS Bucket | Storage | `hls_video_transcoder_storage_output_files` |
| Pub/Sub Topic | Messaging | `transcoder-push-to-sftp-batching` |
| Pub/Sub Topic | Messaging | `raw_native_videos` |
| Pub/Sub Topic | Messaging | `NewRawVideosIngestion_processed_data` |
| MongoDB Collection | Database | `ingestion-data.raw_videos_rss` |
| Secret Manager Secret | Credentials | `de_trascoder_sftp` |
| Cloud Scheduler Job | Trigger | Batching schedule |
| Cloud Scheduler Job | Trigger | Status polling schedule |

## Network and Security

| Connection | Protocol | Auth | Notes |
|---|---|---|---|
| Cloud Function -> MongoDB | MongoDB wire protocol | Connection URI (Secret Manager) | Encrypted in transit |
| Cloud Function -> GCS | GCS API (HTTPS) | IAM service account | Default Cloud Function SA |
| Cloud Function -> SFTP | SFTP (SSH) | Credentials from Secret Manager | JSON-formatted credentials |
| Cloud Function -> CPP API | HTTPS | HMAC-SHA256 signature | Custom auth scheme |
| Cloud Function -> Secret Manager | HTTPS (GCP API) | IAM service account | Automatic |
| Cloud Function -> Pub/Sub | gRPC | IAM service account | Automatic |
