# Video Transcoder Workflow -- Data Specification

## Data Sources

### MongoDB Query (Batching)

The batching function queries `ingestion-data.raw_videos_rss` with the following filter:

```json
{
  "contentType": "videos",
  "processingStatus": "completed",
  "transcoderProcessingStatus": "initiated"
}
```

Limit: 30 documents per execution.

### GCS Video Files

| Attribute | Value |
|---|---|
| Bucket | `hls_video_transcoder_storage_output_files` |
| Path pattern | `raw_videos/{video_id}.mp4` |
| Format | MP4 video |

### CPP/SAAS API Responses

**Get All Content Status:**
- Endpoint: `GET vod/v1/getallcontentstatus`
- Pagination: `limit=100`, iterated through all pages
- Filter: `status="Pu"` (Published)

**Get Content Details:**
- Endpoint: `GET vod/v1/getcontentdetails/{content_id}/jionews`
- Returns HLS URLs and content metadata

## SFTP Delivery Artifacts

### Video File

| Attribute | Value |
|---|---|
| Filename | `{video_id}.mp4` |
| Source | GCS `raw_videos/{video_id}.mp4` |
| Destination | SFTP: `/media/newcpp/jionews2jiohotstar/watch/{video_id}.mp4` |

### Metadata CSV

| Attribute | Value |
|---|---|
| Filename | `{video_id}.csv` |
| Fields | 54 total |
| Populated fields | 3 |
| Destination | SFTP: `/media/newcpp/jionews2jiohotstar/watch/{video_id}.csv` |

**CSV Field Specification:**

| Field # | Field Name | Populated | Value |
|---|---|---|---|
| 1 | FileName | Yes | `{video_id}.mp4` |
| 2 | ContentType | Yes | `"Video"` |
| 3 | Language | Yes | Video language (normalized) |
| 4-54 | Various metadata fields | No | Empty string |

**Language Normalization:**

| Input Value | Output Value |
|---|---|
| `Bangla` | `Bengali` |
| All others | Passed through unchanged |

## CPP/SAAS API Authentication

| Attribute | Value |
|---|---|
| Method | HMAC-SHA256 |
| Access Key | `jionews1` |
| Distributor | `jionews` |
| Distributor ID | `685bc98ec9e754683750e182` |

**Signature construction:**

```
payload = url_path + access_key + epoch_timestamp
signature = HMAC-SHA256(secret_key, payload)
```

The `epoch_timestamp` is the current Unix epoch time as a string.

## API Response Schema

### getallcontentstatus Response

| Field | Type | Description |
|---|---|---|
| `content_id` | string | External content identifier |
| `status` | string | Processing status (`"Pu"` = Published) |
| `title` | string | Content title |
| `pagination` | object | Contains total count and page info |

### getcontentdetails Response

| Field | Type | Description |
|---|---|---|
| `content_id` | string | External content identifier |
| `hls_urls` | object | HLS stream URLs (AVC and HEVC) |
| `path` | string | CDN path component |
| `metadata` | object | Content metadata |

## HLS URL Construction

Base URL: `https://videos.jionews.com/jvodnews`

**Transformation rule:**
- Take the `path` field from the API response.
- Replace `index` with `master-` in the path string.
- Prepend the base URL.

**Example:**
```
API path:   /some/path/index.m3u8
HLS URL:    https://videos.jionews.com/jvodnews/some/path/master-.m3u8
```

## Pub/Sub Message Schemas

### Topic: transcoder-push-to-sftp-batching

Published by the batching function, consumed by the SFTP push function.

| Field | Type | Description |
|---|---|---|
| `_id` | string | MongoDB document ID |
| `source_id` | string | Video identifier |
| `video_id` | string | Video identifier |
| `language` | string | Video language |
| `contentType` | string | `"videos"` |
| `processingStatus` | string | `"completed"` |
| `transcoderProcessingStatus` | string | `"queued"` |

### Topic: raw_native_videos

Published by the status polling function after transcoding is confirmed complete.

| Field | Type | Description |
|---|---|---|
| `source_id` | string | Video identifier |
| `hls_avc_url` | string | HLS AVC stream URL |
| `hls_hevc_url` | string | HLS HEVC stream URL |
| `content_id` | string | External CPP content ID |
| `transcoderProcessingStatus` | string | `"completed"` |

### Topic: NewRawVideosIngestion_processed_data

Published by the status polling function. Same schema as `raw_native_videos`.

## State Machine Data

### transcoderProcessingStatus Values

| State | Set By | MongoDB Update |
|---|---|---|
| `initiated` | Native Videos Ingestion pipeline | `{transcoderProcessingStatus: "initiated"}` |
| `queued` | transcoder-push-to-sftp-batching | `{transcoderProcessingStatus: "queued"}` |
| `submitting` | transcoder-push-to-sftp | `{transcoderProcessingStatus: "submitting"}` |
| `submitted` | transcoder-push-to-sftp | `{transcoderProcessingStatus: "submitted"}` |
| `completed` | transcoder-update-content-status | `{transcoderProcessingStatus: "completed"}` |
| `failed` | Any (on error) | `{transcoderProcessingStatus: "failed"}` |

## Secret Manager References

| Secret Name | Format | Content | Used by |
|---|---|---|---|
| `de_trascoder_sftp` | JSON | SFTP host, port, username, password/key | transcoder-push-to-sftp |

Note: The secret name contains a typo ("trascoder" instead of "transcoder"). This is the actual production name and must be used as-is.

## Data Quality Rules

| Rule | Stage | Behavior |
|---|---|---|
| Record must have `transcoderProcessingStatus=initiated` | Batching | Not selected for processing |
| Record must have `processingStatus=completed` | Batching | Not selected for processing |
| Record must have `contentType=videos` | Batching | Not selected for processing |
| Video file must exist in GCS | SFTP push | Status set to `failed` |
| SFTP upload must succeed | SFTP push | Status set to `failed` |
| CPP API status must be `"Pu"` | Status polling | Record not processed (still pending) |
| Language "Bangla" must be normalized | SFTP push (CSV) | Mapped to "Bengali" |
