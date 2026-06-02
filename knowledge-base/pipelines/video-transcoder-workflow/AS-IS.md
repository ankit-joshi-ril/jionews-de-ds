# Video Transcoder Workflow -- AS-IS Process Document

## Current State Description

The Video Transcoder Workflow is a three-function pipeline that manages the submission of videos to an external transcoding service and the retrieval of transcoded HLS URLs. It operates in a batched, scheduled manner with SFTP as the delivery mechanism and REST API polling for status updates.

## Process Flow (Current State)

### Phase 1: Batching (transcoder-push-to-sftp-batching)

1. Cloud Scheduler triggers the batching function on a recurring schedule.
2. The function queries MongoDB (`ingestion-data.raw_videos_rss`) for records matching:
   - `contentType` = `"videos"`
   - `processingStatus` = `"completed"`
   - `transcoderProcessingStatus` = `"initiated"`
3. Results are limited to 30 records per execution.
4. For each matching record, a message is published to Pub/Sub topic `transcoder-push-to-sftp-batching`.
5. After publishing, the function updates each record's `transcoderProcessingStatus` from `"initiated"` to `"queued"`.

### Phase 2: SFTP Delivery (transcoder-push-to-sftp)

1. Pub/Sub push delivers a message to the function for each queued video.
2. The function updates `transcoderProcessingStatus` to `"submitting"`.
3. The video file is downloaded from GCS bucket `hls_video_transcoder_storage_output_files/raw_videos/{video_id}.mp4`.
4. A 54-field CSV metadata file is generated. Only three fields are populated:
   - `FileName`: the video file name
   - `ContentType`: `"Video"`
   - `Language`: the video's language (with "Bangla" normalized to "Bengali")
   - All remaining 51 fields are left empty.
5. SFTP credentials are retrieved from Secret Manager (`de_trascoder_sftp`, JSON format).
6. Both files (`{video_id}.mp4` and `{video_id}.csv`) are uploaded to SFTP at `/media/newcpp/jionews2jiohotstar/watch/`.
7. On success, `transcoderProcessingStatus` is updated to `"submitted"`.
8. On failure, `transcoderProcessingStatus` is updated to `"failed"`.

### Phase 3: Status Polling (transcoder-update-content-status)

1. Cloud Scheduler triggers the status polling function on a recurring schedule.
2. The function authenticates with the CPP/SAAS API using HMAC-SHA256:
   - Payload: `url_path + access_key + epoch_timestamp`
   - Signed with the secret key
   - Access key: `jionews1`
3. The function calls `GET vod/v1/getallcontentstatus` with parameters:
   - `limit`: 100
   - Status filter: `"Pu"` (Published)
   - Paginated (iterates through all pages)
4. For each published content item, the function calls `GET vod/v1/getcontentdetails/{content_id}/jionews` to retrieve HLS URLs.
5. HLS URL construction: the base URL `https://videos.jionews.com/jvodnews` is prepended to the path from the API response, with `index` replaced by `master-` in the path.
6. Processing uses `ThreadPoolExecutor(5)` with retry logic (3 attempts, 5-second delay).
7. Processed records are published to two Pub/Sub topics:
   - `raw_native_videos`
   - `NewRawVideosIngestion_processed_data`
8. `transcoderProcessingStatus` is updated to `"completed"`.

## Current Limitations and Known Issues

| Issue | Impact | Severity |
|---|---|---|
| Batch size hardcoded to 30 | Cannot adapt to varying queue depths | Low |
| SFTP is a single point of failure | SFTP outage blocks all transcoding | High |
| 54-field CSV with only 3 populated fields | Wasteful; external system may evolve to need more fields | Low |
| Status polling is scheduled, not event-driven | Delay between transcoding completion and status update | Medium |
| Language normalization only handles "Bangla" -> "Bengali" | Other language name mismatches may exist | Low |
| ThreadPoolExecutor(5) for status polling | Limited concurrency for large batches | Medium |
| SFTP credential secret named "de_trascoder_sftp" (typo) | Confusing naming; not a functional issue | Low |
| No dead-letter handling for failed SFTP uploads | Failed records marked as "failed" but no automatic retry | Medium |

## State Transition Diagram

```
initiated ─── [batching publishes to topic] ──→ queued
    queued ─── [SFTP function picks up] ──────→ submitting
submitting ─── [SFTP upload succeeds] ────────→ submitted
submitting ─── [SFTP upload fails] ───────────→ failed
 submitted ─── [CPP API returns status=Pu] ──→ completed
 submitted ─── [CPP API indicates failure] ──→ failed
```

## Operational Characteristics

| Metric | Value |
|---|---|
| Batch size (per execution) | 30 records |
| SFTP path | `/media/newcpp/jionews2jiohotstar/watch/` |
| CSV fields (total) | 54 |
| CSV fields (populated) | 3 |
| Status poll page size | 100 |
| Status poll concurrency | 5 threads |
| Status poll retry | 3 attempts, 5s delay |
| HLS CDN base | `https://videos.jionews.com/jvodnews` |
| API status filter | `"Pu"` (Published) |

## Integration Points

| System | Direction | Protocol | Purpose |
|---|---|---|---|
| MongoDB Atlas | Bidirectional | MongoDB wire protocol | Status tracking, record queries |
| GCS | Inbound | GCS API | Video file retrieval |
| SFTP server | Outbound | SFTP | Video + CSV delivery |
| CPP/SAAS API | Inbound | HTTPS (REST) | Transcoding status polling |
| Secret Manager | Inbound | GCP API | SFTP and API credentials |
| Pub/Sub | Outbound | gRPC | Batching, downstream publishing |
| videos.jionews.com | Referenced | HTTPS | HLS video delivery CDN |
