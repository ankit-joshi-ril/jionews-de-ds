# YouTube Shorts Ingestion - Data Specification

## Data Flow Summary

```
GCS (publisher CSV) -> ScrapeVideoIds -> Pub/Sub -> YouTubeAPIToMongoDB -> MongoDB + Pub/Sub
```

## Input Data

### Publisher List CSV

| Attribute | Value |
|---|---|
| **Location** | `gs://de-raw-ingestion/shorts/shorts_publishers.csv` |
| **Encoding** | ISO-8859-1 |
| **Format** | CSV with headers |

#### CSV Schema

| Column | Type | Description | Example |
|---|---|---|---|
| `custom_url` | string | YouTube channel custom URL path segment | `@IndiaTV` |
| Additional columns | varies | Publisher metadata (name, category, etc.) | varies |

**Usage:** The `custom_url` field is used to construct the scrape target URL: `http://www.youtube.com/{custom_url}/shorts`

### YouTube Data API v3 Response

| Attribute | Value |
|---|---|
| **API Endpoint** | `youtube.videos().list()` |
| **Parts Requested** | `snippet`, `contentDetails` |
| **Batch Size** | Up to 50 video IDs per request |
| **Authentication** | API key from Secret Manager (`yt_api_access_token`) |

#### Relevant API Response Fields

| Field Path | Type | Usage |
|---|---|---|
| `items[].id` | string | YouTube video ID |
| `items[].snippet.title` | string | Video title |
| `items[].snippet.description` | string | Video description |
| `items[].snippet.publishedAt` | string (ISO 8601) | Publication timestamp |
| `items[].snippet.thumbnails` | object | Thumbnail URLs at various resolutions |
| `items[].contentDetails.duration` | string (ISO 8601 duration) | Video duration (e.g., `PT45S`) |

## Intermediate Data

### Pub/Sub Message: `cron_based_raw_youtube_shorts_ingestion`

| Attribute | Value |
|---|---|
| **Direction** | ScrapeVideoIds -> YouTubeAPIToMongoDB |
| **Format** | JSON (base64-encoded in Pub/Sub envelope) |
| **Content** | Batch of new video IDs not yet in MongoDB |

#### Message Schema

```json
{
  "video_ids": ["videoId1", "videoId2", "..."]
}
```

## Output Data

### MongoDB Document: `raw_short_videos_ingestion_data`

| Attribute | Value |
|---|---|
| **Database** | `ingestion-data` |
| **Collection** | `raw_short_videos_ingestion_data` |
| **Insert Method** | `insert_many(ordered=False)` |

#### Document Schema

| Field | Type | Source | Description |
|---|---|---|---|
| `sourceVideoId` | string | YouTube API `items[].id` | Unique YouTube video identifier |
| `title` | string | `items[].snippet.title` | Video title |
| `sourceThumbnailURL` | string | Constructed | `https://i.ytimg.com/vi/{video_id}/sddefault.jpg` |
| `sourceDate` | string (ISO 8601) | `items[].snippet.publishedAt` | Original publication timestamp |
| `sourceEpoch` | number | Derived from `publishedAt` | Unix epoch timestamp (seconds) |
| `sourceDescription` | string | `items[].snippet.description` | Video description text |
| `src` | string | Hardcoded | Always `"youtube"` |
| `sourceThumbnails` | object | `items[].snippet.thumbnails` | Full YouTube thumbnails object with all resolutions |
| `sourceVideoDuration` | integer | Derived from `contentDetails.duration` | Duration in seconds (0 < value <= 60) |
| `sourceVideoWidth` | integer | Hardcoded | Always `1080` |
| `sourceVideoHeight` | integer | Hardcoded | Always `1920` |
| `sourceVideoOrientation` | string | Hardcoded | Always `"portrait"` |

#### Example Document

```json
{
  "sourceVideoId": "dQw4w9WgXcQ",
  "title": "Breaking News Update",
  "sourceThumbnailURL": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg",
  "sourceDate": "2025-01-15T10:30:00Z",
  "sourceEpoch": 1736935800,
  "sourceDescription": "Latest breaking news coverage...",
  "src": "youtube",
  "sourceThumbnails": {
    "default": { "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg", "width": 120, "height": 90 },
    "medium": { "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", "width": 320, "height": 180 },
    "high": { "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "width": 480, "height": 360 },
    "standard": { "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg", "width": 640, "height": 480 }
  },
  "sourceVideoDuration": 45,
  "sourceVideoWidth": 1080,
  "sourceVideoHeight": 1920,
  "sourceVideoOrientation": "portrait"
}
```

### Pub/Sub Message: `raw_youtube_shorts_ingestion`

| Attribute | Value |
|---|---|
| **Direction** | YouTubeAPIToMongoDB -> Downstream consumers |
| **Format** | JSON (base64-encoded in Pub/Sub envelope) |
| **Content** | Individual enriched short video record |

The message payload matches the MongoDB document schema above.

## Validation Rules

### Duration Validation

| Rule | Implementation |
|---|---|
| **Minimum duration** | `duration > 0 seconds` |
| **Maximum duration** | `duration <= 60 seconds` |
| **Parsing** | ISO 8601 duration via `isodate` library |
| **Rejection** | Videos outside range are silently excluded |

### URL Redirect Validation

| Rule | Implementation |
|---|---|
| **Request** | `GET https://www.youtube.com/shorts/{video_id}` |
| **Method** | `allow_redirects=False` |
| **Pass condition** | HTTP status code `200` |
| **Fail condition** | Any non-200 status (redirect = not a Short) |

### Recency Validation

| Rule | Implementation |
|---|---|
| **Window** | 24 hours from function execution time |
| **Field** | `snippet.publishedAt` |
| **Rejection** | Videos older than 24 hours are excluded |

### Deduplication

| Rule | Implementation |
|---|---|
| **Check** | MongoDB aggregation on `sourceVideoId` |
| **Collection** | `ingestion-data.raw_short_videos_ingestion_data` |
| **Stage** | Performed in ScrapeVideoIds before Pub/Sub publish |

## Data Volume Estimates

| Metric | Typical Value |
|---|---|
| Publishers in CSV | Varies (tens to hundreds) |
| Video IDs scraped per run | Varies by publisher activity |
| Videos passing all validations | Subset of scraped IDs |
| YouTube API calls per run | ceil(total_new_ids / 50) |
