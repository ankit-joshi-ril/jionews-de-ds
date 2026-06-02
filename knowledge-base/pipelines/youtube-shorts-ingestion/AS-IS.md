# YouTube Shorts Ingestion - AS-IS State

## Current Operational State

| Attribute | Value |
|---|---|
| **Status** | Production |
| **Environment** | GCP `jiox-328108` |
| **Trigger** | Cloud Scheduler -> HTTP -> Cloud Function |
| **Execution Runtime** | Python (Cloud Functions Gen1) |
| **Data Freshness** | Near-real-time (24-hour recency window) |

## Current Behavior

### Stage 1: ScrapeVideoIds

1. Cloud Scheduler fires an HTTP request to the `ScrapeVideoIds` Cloud Function.
2. The function reads the publisher list from `gs://de-raw-ingestion/shorts/shorts_publishers.csv` using ISO-8859-1 encoding.
3. For each publisher row, it constructs the URL `http://www.youtube.com/{custom_url}/shorts` and issues an HTTP GET request with a 5-second timeout.
4. The HTML response is parsed with BeautifulSoup to extract the embedded `ytInitialData` JavaScript object.
5. A JSONPath expression (`$..videoId`) extracts all video IDs from the parsed JSON structure.
6. The function queries MongoDB `ingestion-data.raw_short_videos_ingestion_data` using an aggregation pipeline to find which of the discovered video IDs already exist (matching on `sourceVideoId`).
7. Only net-new video IDs (not present in MongoDB) are published to the Pub/Sub topic `cron_based_raw_youtube_shorts_ingestion`.

### Stage 2: YouTubeAPIToMongoDB

1. Triggered by messages on the `cron_based_raw_youtube_shorts_ingestion` Pub/Sub topic.
2. Decodes the incoming message to extract a batch of video IDs.
3. Calls the YouTube Data API v3 `videos().list()` endpoint with `part="snippet,contentDetails"`, batching up to 50 IDs per request.
4. For each video returned by the API:
   - Parses the ISO 8601 duration string using the `isodate` library and converts to seconds.
   - Validates that the duration is > 0 seconds AND <= 60 seconds.
   - Performs an HTTP GET to `https://www.youtube.com/shorts/{video_id}` with `allow_redirects=False`. Only videos returning HTTP 200 (no redirect) are confirmed as Shorts.
   - Checks that `publishedAt` is within the last 24 hours.
5. Qualified records are transformed into the output schema and inserted into MongoDB via `insert_many(ordered=False)`.
6. Each inserted record is also published to the `raw_youtube_shorts_ingestion` Pub/Sub topic for downstream consumers.

## Known Limitations and Considerations

### Web Scraping Fragility

- The scraping approach depends on YouTube's HTML structure and the embedded `ytInitialData` JSON object. Changes to YouTube's frontend rendering can silently break video ID extraction.
- The 5-second HTTP timeout per publisher page may cause missed channels under high latency conditions.
- No retry mechanism exists for failed scrape attempts of individual publisher pages.

### YouTube API Quota

- The YouTube Data API v3 has a daily quota (default 10,000 units). Each `videos().list()` call costs 1 unit per request (not per video ID). Batching at 50 IDs per call is efficient, but high publisher volumes can accumulate quota usage.
- The API key is stored in Secret Manager as `yt_api_access_token`.

### URL Redirect Validation

- The redirect check (`allow_redirects=False`) to confirm a video is genuinely a YouTube Short adds one HTTP request per video ID. This can become a bottleneck when processing large batches.
- If YouTube changes its redirect behavior for Shorts URLs, this validation gate could produce false negatives.

### Deduplication Strategy

- Deduplication is performed only at the MongoDB level by checking existing `sourceVideoId` values. There is no in-memory or cross-batch dedup within a single execution cycle.
- If two scheduler invocations overlap, there is a small window for duplicate Pub/Sub messages, though `insert_many(ordered=False)` will silently skip duplicates if a unique index exists on `sourceVideoId`.

### Recency Filter

- The 24-hour recency filter on `publishedAt` means videos published more than 24 hours ago are permanently excluded, even if they were not previously ingested.
- Clock skew between the Cloud Function execution environment and YouTube's `publishedAt` timestamps could cause edge-case exclusions.

### Hardcoded Values

- Thumbnail URL pattern: `https://i.ytimg.com/vi/{video_id}/sddefault.jpg`
- Video dimensions: `sourceVideoWidth=1080`, `sourceVideoHeight=1920`
- Video orientation: `sourceVideoOrientation="portrait"`
- Source identifier: `src="youtube"`

## Error Handling

| Scenario | Current Behavior |
|---|---|
| Publisher CSV not found in GCS | Function fails with unhandled exception |
| YouTube page scrape timeout (5s) | Individual publisher skipped, others continue |
| YouTube API quota exceeded | API returns 403; function fails for remaining batch |
| YouTube API returns no results for IDs | Those IDs are silently skipped |
| Duration validation fails | Video excluded from output |
| Redirect check fails (non-200) | Video excluded from output |
| MongoDB insert failure | `ordered=False` allows partial success; errors logged |
| Pub/Sub publish failure | Message lost; no retry at application level |

## Operational Notes

- The `certifi` library is used to ensure TLS certificate verification works correctly in the Cloud Function environment.
- MongoDB connection uses the URI from Secret Manager key `mongosh_de_uri`.
- The pipeline produces records with a fixed portrait orientation assumption (1080x1920), which is correct for YouTube Shorts.
