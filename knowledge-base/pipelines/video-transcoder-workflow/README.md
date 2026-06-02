# Video Transcoder Workflow Pipeline

## Overview

The Video Transcoder Workflow pipeline manages the end-to-end lifecycle of video transcoding by coordinating between the JioNews ingestion system, an external SFTP-based transcoding service (CPP/SAAS), and the downstream content delivery system. It handles batching of videos for transcoding, SFTP delivery of video files with metadata CSVs, and polling the external transcoder API for completion status and HLS URLs.

## Pipeline Identity

| Attribute | Value |
|---|---|
| Pipeline Name | Video Transcoder Workflow |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Runtime | Python (Cloud Functions) |
| Data Store | MongoDB (`ingestion-data.raw_videos_rss`) |
| External Service | CPP/SAAS API (`https://cppapi-saas.media.jio.com`) |
| SFTP Target | `/media/newcpp/jionews2jiohotstar/watch/` |
| CDN | `https://videos.jionews.com` |

## Function Chain

| Order | Cloud Function | Trigger | Purpose |
|---|---|---|---|
| 1 | `transcoder-push-to-sftp-batching` | Cloud Scheduler | Query MongoDB for eligible videos, batch and publish |
| 2 | `transcoder-push-to-sftp` | Pub/Sub (push) | Download video, generate CSV, upload to SFTP |
| 3 | `transcoder-update-content-status` | Cloud Scheduler | Poll CPP/SAAS API for transcoding status, publish HLS URLs |

## State Machine

The `transcoderProcessingStatus` field in MongoDB tracks each video through the transcoding lifecycle:

```
(empty/not set) --> initiated --> queued --> submitting --> submitted --> completed
                                                                          |
                                         failed <-- (possible at any stage)
```

| State | Set by | Meaning |
|---|---|---|
| `initiated` | Native Videos Ingestion (downloadvideos) | Video is ready for transcoding |
| `queued` | transcoder-push-to-sftp-batching | Record published to batching topic |
| `submitting` | transcoder-push-to-sftp | SFTP upload in progress |
| `submitted` | transcoder-push-to-sftp | SFTP upload completed successfully |
| `completed` | transcoder-update-content-status | External transcoder confirmed processing done |
| `failed` | Any function | Error occurred during processing |

## Key Behaviors

- Batching function limits to 30 records per execution to control SFTP load.
- SFTP upload includes both the video file (`.mp4`) and a 54-field metadata CSV.
- Language normalization maps "Bangla" to "Bengali" for the external system.
- External API authentication uses HMAC-SHA256 signing.
- HLS URL construction replaces `index` with `master-` in the path from the CPP API response.
- Status polling uses pagination (limit=100) and filters for status `"Pu"` (Published).

## External System Integration

### CPP/SAAS API

| Attribute | Value |
|---|---|
| Base URL | `https://cppapi-saas.media.jio.com` |
| Auth | HMAC-SHA256 |
| Access Key | `jionews1` |
| Distributor | `jionews` |
| Distributor ID | `685bc98ec9e754683750e182` |

### SFTP

| Attribute | Value |
|---|---|
| Target path | `/media/newcpp/jionews2jiohotstar/watch/` |
| Files per video | `{video_id}.mp4` + `{video_id}.csv` |
| Credentials | Secret Manager: `de_trascoder_sftp` (JSON) |

## Dependencies

- Google Cloud Storage (video file retrieval)
- Google Cloud Pub/Sub (batching topic, output topics)
- MongoDB Atlas (status tracking)
- SFTP server (video + metadata delivery)
- CPP/SAAS external API (status polling)
- Secret Manager (SFTP credentials, API keys)

## Related Pipelines

- Upstream: Native Videos Ingestion (sets `transcoderProcessingStatus=initiated`)
- Downstream: RSS Feed Generation (via `NewRawVideosIngestion_processed_data`)
- Downstream: Additional consumers (via `raw_native_videos`)
