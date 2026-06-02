# Video Transcoder Workflow -- Technical Specification

## Runtime Environment

| Attribute | Value |
|---|---|
| Platform | Google Cloud Functions |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Language | Python |
| Trigger types | Cloud Scheduler (HTTP), Pub/Sub push |

## Function Specifications

### transcoder-push-to-sftp-batching

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler (scheduled) |
| Batch limit | 30 records per execution |
| Output topic | `transcoder-push-to-sftp-batching` |

**Processing Logic:**

1. Connect to MongoDB using connection URI from Secret Manager.
2. Execute query on `ingestion-data.raw_videos_rss`:
   ```python
   collection.find({
       "contentType": "videos",
       "processingStatus": "completed",
       "transcoderProcessingStatus": "initiated"
   }).limit(30)
   ```
3. For each matching document:
   a. Publish the document as a Pub/Sub message to `transcoder-push-to-sftp-batching`.
   b. Update the document: `transcoderProcessingStatus` = `"queued"`.

**Status transitions:**
- On each record: `initiated` -> `queued`

### transcoder-push-to-sftp

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub push (from `transcoder-push-to-sftp-batching`) |
| GCS source | `hls_video_transcoder_storage_output_files/raw_videos/` |
| SFTP destination | `/media/newcpp/jionews2jiohotstar/watch/` |
| Credentials | Secret Manager: `de_trascoder_sftp` (JSON) |

**Processing Logic:**

1. Decode the Pub/Sub message containing the video record.
2. Update MongoDB: `transcoderProcessingStatus` = `"submitting"`.
3. Download the video file from GCS: `hls_video_transcoder_storage_output_files/raw_videos/{video_id}.mp4`.
4. Generate the 54-field metadata CSV:
   ```python
   row = [""] * 54
   row[0] = f"{video_id}.mp4"    # FileName
   row[1] = "Video"               # ContentType
   row[2] = normalize_language(language)  # Language
   ```
5. Apply language normalization:
   ```python
   def normalize_language(lang: str) -> str:
       if lang == "Bangla":
           return "Bengali"
       return lang
   ```
6. Retrieve SFTP credentials from Secret Manager (`de_trascoder_sftp`).
7. Establish SFTP connection using the credentials.
8. Upload `{video_id}.mp4` to `/media/newcpp/jionews2jiohotstar/watch/`.
9. Upload `{video_id}.csv` to `/media/newcpp/jionews2jiohotstar/watch/`.
10. On success: Update MongoDB `transcoderProcessingStatus` = `"submitted"`.
11. On failure: Update MongoDB `transcoderProcessingStatus` = `"failed"`.

**Status transitions:**
- Start: `queued` -> `submitting`
- Success: `submitting` -> `submitted`
- Failure: `submitting` -> `failed`

### transcoder-update-content-status

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler (scheduled) |
| External API | `https://cppapi-saas.media.jio.com` |
| Concurrency | `ThreadPoolExecutor(max_workers=5)` |
| Retry | 3 attempts, 5-second delay |
| Output topics | `raw_native_videos`, `NewRawVideosIngestion_processed_data` |

**Processing Logic:**

1. Generate HMAC-SHA256 authentication signature:
   ```python
   import hmac
   import hashlib
   import time

   epoch = str(int(time.time()))
   payload = url_path + access_key + epoch
   signature = hmac.new(
       secret_key.encode(),
       payload.encode(),
       hashlib.sha256
   ).hexdigest()
   ```

2. Paginate through all published content:
   ```python
   page = 0
   while True:
       response = requests.get(
           f"{base_url}/vod/v1/getallcontentstatus",
           params={"limit": 100, "page": page, "status": "Pu"},
           headers=auth_headers
       )
       items = response.json().get("items", [])
       if not items:
           break
       process_items(items)
       page += 1
   ```

3. For each published item, fetch content details using `ThreadPoolExecutor(5)`:
   ```python
   def fetch_details(content_id):
       for attempt in range(3):
           try:
               response = requests.get(
                   f"{base_url}/vod/v1/getcontentdetails/{content_id}/jionews",
                   headers=auth_headers
               )
               return response.json()
           except Exception:
               if attempt < 2:
                   time.sleep(5)
               else:
                   raise
   ```

4. Construct HLS URLs:
   ```python
   def construct_hls_url(api_path: str) -> str:
       base = "https://videos.jionews.com/jvodnews"
       transformed_path = api_path.replace("index", "master-")
       return base + transformed_path
   ```

5. Publish completed records to both output Pub/Sub topics.
6. Update MongoDB: `transcoderProcessingStatus` = `"completed"`, add `hls_avc_url` and `hls_hevc_url`.

**Status transitions:**
- On each confirmed-published record: `submitted` -> `completed`

## CPP/SAAS API Integration Details

### Authentication

| Attribute | Value |
|---|---|
| Scheme | HMAC-SHA256 |
| Access Key | `jionews1` |
| Distributor | `jionews` |
| Distributor ID | `685bc98ec9e754683750e182` |
| Signature payload | `{url_path}{access_key}{epoch}` |

### Endpoints

#### GET /vod/v1/getallcontentstatus

| Parameter | Type | Value |
|---|---|---|
| `limit` | integer | 100 |
| `page` | integer | 0-indexed, incremented until empty response |
| `status` | string | `"Pu"` (Published) |

#### GET /vod/v1/getcontentdetails/{content_id}/jionews

| Parameter | Type | Source |
|---|---|---|
| `content_id` | string (path) | From getallcontentstatus response |

## Pub/Sub Topic Configuration

| Topic | Publisher | Subscriber | Mode |
|---|---|---|---|
| `transcoder-push-to-sftp-batching` | Batching function | SFTP push function | Per-record (push) |
| `raw_native_videos` | Status polling function | Downstream consumers | Per-record |
| `NewRawVideosIngestion_processed_data` | Status polling function | Downstream consumers | Per-record |

## Key Libraries and Dependencies

| Library | Purpose | Used by |
|---|---|---|
| `pymongo` | MongoDB client | All three functions |
| `google-cloud-storage` | GCS operations | SFTP push (download video) |
| `google-cloud-pubsub` | Pub/Sub publishing | All three functions |
| `google-cloud-secret-manager` | Secrets access | SFTP push (credentials) |
| `paramiko` or `pysftp` | SFTP client | SFTP push |
| `requests` | HTTP client | Status polling (CPP API) |
| `hmac` / `hashlib` | HMAC-SHA256 signing | Status polling |
| `concurrent.futures` | Thread pool | Status polling |
| `csv` | CSV generation | SFTP push |

## Error Handling

| Component | Error Scenario | Handling | Recovery |
|---|---|---|---|
| Batching | MongoDB connection failure | Function fails | Cloud Scheduler retries on next schedule |
| Batching | Pub/Sub publish failure | Exception raised | Cloud Function error reporting |
| SFTP Push | GCS download failure | Status set to `failed` | Manual intervention required |
| SFTP Push | SFTP connection failure | Status set to `failed` | Manual intervention required |
| SFTP Push | SFTP upload failure | Status set to `failed` | Manual intervention required |
| Status Poll | API auth failure | Function fails | Cloud Scheduler retries on next schedule |
| Status Poll | API timeout (per detail call) | Retry 3x with 5s delay | Skipped after 3 failures |
| Status Poll | HLS URL construction failure | Record skipped | Picked up on next poll cycle |

## Monitoring Considerations

| Metric | Alert Condition | Description |
|---|---|---|
| `transcoderProcessingStatus=failed` count | Count increasing | Videos failing transcoding |
| `transcoderProcessingStatus=initiated` age | Records older than expected | Batching not picking up records |
| `transcoderProcessingStatus=submitted` age | Records older than expected | External transcoder not completing |
| SFTP upload duration | Exceeding threshold | SFTP server performance degradation |
| CPP API response time | Exceeding threshold | External API performance issues |
