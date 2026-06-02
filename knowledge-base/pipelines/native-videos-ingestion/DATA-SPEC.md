# Native Videos Ingestion -- Data Specification

## Data Sources

### Source 1: REST API Upload

**Endpoint:** `POST /v1/de-native-video/upload/`

| Part | Type | Validation | Description |
|---|---|---|---|
| `video` | file (multipart) | `.mp4`, `.mov`, `.avi` | Video file |
| `thumbnail` | file (multipart) | `.jpg`, `.jpeg`, `.png`, `.webp` | Thumbnail image |
| `metadata` | JSON (multipart) | Required fields vary | Video metadata |

**Hardcoded values:**
- Publisher: `"ANI"` (ID: `"5001"`)
- `src`: `"api"`

**Output storage:** `hls_video_transcoder_storage_output_files/raw_videos/{source_id}.mp4`

### Source 2: Manual Upload

**Endpoints:**

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Web UI |
| `/metadata` | GET | Retrieve category/language/publisher lists |
| `/get_upload_url` | POST | Generate GCS V4 signed URL (300s TTL) |
| `/check_cdn` | POST | HEAD check on `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| `/upload` | POST | Finalize upload with metadata |

**Metadata sources (local CSVs):**
- `data/categories.csv`
- `data/languages.csv`
- `data/publishers.csv`

**Hardcoded values:**
- `src`: `"manual"`

### Source 3: MRSS Feeds

**Feed configuration:** GCS `de-raw-ingestion/videos/mrss_videos_feeds.csv`

**Feed parsing rules:**

| Feed IDs | JSON Key | Publisher | Notes |
|---|---|---|---|
| 49, 50 | `data` | IANS | Special JSON structure |
| All others | `items` | Various | Standard MRSS format |

**Publisher-specific rules:**

| Publisher ID | Rule |
|---|---|
| 7777, 7778 | Only accept `videotype` in: `"vod"`, `"long video"`, `"video"`, `"videos"`, `"longvideo"` |
| 7782 (IANS) | Video URL extracted from `record.get('video')` |

## Category Reference Data

| Category ID | Category Name |
|---|---|
| 3 | entertainment |
| 5 | fashion |
| 8 | health |
| 9 | food |
| 10 | automotive |
| 11 | travel |
| 12 | sports |
| 13 | news |
| 14 | technology |
| 17 | business |
| 18 | cricket |
| 20 | spiritual |
| 22 | astrology |
| 26 | Career |

## Language Reference Data

| Language ID | Language Name |
|---|---|
| 1 | English |
| 2 | Hindi |
| 3 | Marathi |
| 4 | Gujarati |
| 6 | Malayalam |
| 7 | Tamil |
| 8 | Urdu |
| 9 | Kannada |
| 10 | Punjabi |
| 11 | Telugu |
| 13 | Bangla |
| 18 | Odia |
| 19 | Assamese |

Note: Language IDs 5, 12, 14-17 are not assigned in the current mapping.

## Pub/Sub Message Schemas

### Topic: NewRawHeadlinesIngestion_image_cdn

Published by all three sources. Carries video metadata for image CDN processing.

| Field | Type | Description |
|---|---|---|
| `source_id` | string | Unique identifier for the video |
| `src` | string | Source marker: `"api"`, `"manual"`, or `"publisher_mrss"` |
| `content_type` | string | `"videos"` |
| `title` | string | Video title |
| `category` | string/integer | Content category |
| `language` | string/integer | Content language |
| `publisher_id` | string | Publisher identifier |
| `publisher_name` | string | Publisher display name |
| `video_url` | string | URL or GCS path to the video file |
| `thumbnail_url` | string | URL or GCS path to the thumbnail |
| `processingStatus` | string | `"processing"` (MRSS) or varies |
| `isVideoMerged` | boolean | `false` (MRSS default) |

### Topic: MRSSVideosIngestion_RawFeedsData

Published by `mrssvideos-fetchfeedsdata`.

| Field | Type | Description |
|---|---|---|
| `feed_id` | integer | Feed configuration ID |
| `feed_url` | string | Source feed URL |
| `items` | array[object] | Raw feed items |
| `publisher_config` | object | Publisher metadata from feed CSV |

### Topic: MRSSVideosIngestion_ProcessedData

Published by imagecdn function when `content_type="videos"`. Per-record publish.

| Field | Type | Description |
|---|---|---|
| `source_id` | string | Unique video identifier |
| `title` | string | Video title |
| `cdn_thumbnail_url` | string | CDN-processed thumbnail URL |
| `video_url` | string | Video file URL |
| `category` | string | Category name |
| `language` | string | Language name |
| `publisher` | object | Publisher metadata |
| `src` | string | Source marker |

## Redis Cache Schema (MRSS)

| Attribute | Value |
|---|---|
| Instance | `de_mrss_videos_cache` |
| Key format | `{title}_{link}_{category}_{language}` |
| Value | Existence flag |
| TTL | 48 hours |

## MRSS Record Defaults

| Field | Default Value | Description |
|---|---|---|
| `src` | `"publisher_mrss"` | Source marker for MRSS-ingested videos |
| `processingStatus` | `"processing"` | Initial processing state |
| `isVideoMerged` | `false` | Video merge flag |
| `transcoderProcessingStatus` | `"initiated"` | Set after download completes |

## GCS Storage Layout

```
hls_video_transcoder_storage_output_files/
  raw_videos/
    {source_id}.mp4          -- Uploaded or downloaded video files

de_video_transcoder_input/
    {source_id}.mp4          -- Copy for transcoder processing

de-raw-ingestion/
  videos/
    mrss_videos_feeds.csv    -- MRSS feed configuration

img-cdn-bucket/
    {various paths}          -- Processed thumbnail images
```

## Data Quality Rules

| Rule | Source | Stage | Behavior |
|---|---|---|---|
| Video extension must be .mp4/.mov/.avi | API | Upload | Request rejected (400) |
| Thumbnail extension must be .jpg/.jpeg/.png/.webp | API | Upload | Request rejected (400) |
| HTTP Basic Auth required | API | Request | Unauthorized (401) |
| Signed URL expires after 300s | Manual | Upload | Upload fails |
| Redis dedup key must not exist | MRSS | Process | Record skipped |
| Videotype must match allowed list | MRSS (7777/7778) | Process | Record filtered out |
| Download must succeed within 3 retries | MRSS | Download | Record not persisted |
| src must not be "manual" or "api" | MRSS | Download | Download skipped (handled by source) |

## Data Volume Characteristics

| Source | Typical Volume | Frequency |
|---|---|---|
| REST API | Low (on-demand) | Event-driven |
| Manual Upload | Low (human-initiated) | Ad-hoc |
| MRSS Feeds | Medium-High (automated) | Scheduled |
