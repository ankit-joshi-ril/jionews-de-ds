# YouTube Shorts Ingestion - Technical Specification

## Runtime Environment

| Attribute | Value |
|---|---|
| **Platform** | Google Cloud Functions (Gen1) |
| **Runtime** | Python |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |

## Cloud Functions

### Function 1: ScrapeVideoIds

| Attribute | Value |
|---|---|
| **Entry Point** | `main(req_param_ph)` |
| **Trigger Type** | HTTP (invoked by Cloud Scheduler) |
| **Parameter** | `req_param_ph` - HTTP request object (unused placeholder) |

### Function 2: YouTubeAPIToMongoDB

| Attribute | Value |
|---|---|
| **Entry Point** | `main(pubsub_message, context)` |
| **Trigger Type** | Pub/Sub (`cron_based_raw_youtube_shorts_ingestion`) |
| **Parameters** | `pubsub_message` - Pub/Sub message envelope; `context` - event metadata |

## Dependencies

### Python Libraries

| Library | Purpose | Used In |
|---|---|---|
| `certifi` | TLS CA certificate bundle for secure MongoDB connections | Both functions |
| `isodate` | Parse ISO 8601 duration strings (e.g., `PT45S`) | YouTubeAPIToMongoDB |
| `jsonpath_ng` | JSONPath expression evaluation (`$..videoId`) | ScrapeVideoIds |
| `google-api-python-client` (`googleapiclient`) | YouTube Data API v3 client | YouTubeAPIToMongoDB |
| `beautifulsoup4` | HTML parsing for YouTube channel pages | ScrapeVideoIds |
| `requests` | HTTP client for web scraping and redirect checks | Both functions |
| `pymongo` | MongoDB driver | Both functions |
| `google-cloud-pubsub` | Pub/Sub publisher client | Both functions |
| `google-cloud-storage` | GCS client for reading publisher CSV | ScrapeVideoIds |
| `google-cloud-secret-manager` | Secret Manager access | Both functions |

## Secrets and Configuration

### GCP Secret Manager

| Secret Name | Purpose | Used By |
|---|---|---|
| `mongosh_de_uri` | MongoDB connection URI | Both functions |
| `yt_api_access_token` | YouTube Data API v3 key | YouTubeAPIToMongoDB |

### GCS Configuration Files

| Path | Purpose | Encoding |
|---|---|---|
| `gs://de-raw-ingestion/shorts/shorts_publishers.csv` | Publisher channel list | ISO-8859-1 |

## Pub/Sub Topics

| Topic | Publisher | Subscriber | Message Content |
|---|---|---|---|
| `cron_based_raw_youtube_shorts_ingestion` | ScrapeVideoIds | YouTubeAPIToMongoDB | Batch of new video IDs |
| `raw_youtube_shorts_ingestion` | YouTubeAPIToMongoDB | Downstream consumers | Enriched video records |

## Implementation Details

### Stage 1: ScrapeVideoIds

#### Publisher CSV Reading

```
Bucket: de-raw-ingestion
Path: shorts/shorts_publishers.csv
Encoding: ISO-8859-1
```

The CSV is read with ISO-8859-1 encoding (not UTF-8) to handle special characters in publisher names. The `custom_url` column is extracted for URL construction.

#### Web Scraping Logic

1. **URL Construction:** `http://www.youtube.com/{custom_url}/shorts`
   - Note: Uses HTTP (not HTTPS) for the initial request.
2. **HTTP Request:** GET with a 5-second timeout per publisher.
3. **HTML Parsing:** BeautifulSoup parses the HTML response.
4. **JSON Extraction:** Locates the `ytInitialData` variable in `<script>` tags and parses it as JSON.
5. **Video ID Extraction:** Applies JSONPath expression `$..videoId` to recursively find all `videoId` fields in the JSON structure.

#### Deduplication

- Collects all scraped video IDs across all publishers.
- Queries MongoDB with an aggregation pipeline to retrieve existing `sourceVideoId` values.
- Computes set difference: `new_ids = scraped_ids - existing_ids`.
- Only net-new IDs are published to Pub/Sub.

### Stage 2: YouTubeAPIToMongoDB

#### YouTube API Interaction

```python
youtube = build('youtube', 'v3', developerKey=api_key)
response = youtube.videos().list(
    part='snippet,contentDetails',
    id=','.join(batch_of_50_ids)
).execute()
```

- API calls are batched at 50 IDs per request (YouTube API limit).
- The `snippet` part provides title, description, publishedAt, thumbnails.
- The `contentDetails` part provides duration.

#### Validation Pipeline

Each video from the API response passes through three sequential validation gates:

**Gate 1: Duration Check**

```python
duration_seconds = isodate.parse_duration(content_details['duration']).total_seconds()
valid = (duration_seconds > 0) and (duration_seconds <= 60)
```

**Gate 2: URL Redirect Check**

```python
response = requests.get(
    f'https://www.youtube.com/shorts/{video_id}',
    allow_redirects=False
)
is_short = (response.status_code == 200)
```

A 200 response means the URL resolved directly to a Shorts page. A 3xx redirect means YouTube does not classify this video as a Short.

**Gate 3: Recency Check**

```python
published_at = parse_datetime(snippet['publishedAt'])
is_recent = (now - published_at) <= timedelta(hours=24)
```

#### Record Transformation

Videos passing all three gates are transformed into the output schema:

```python
record = {
    "sourceVideoId": video['id'],
    "title": snippet['title'],
    "sourceThumbnailURL": f"https://i.ytimg.com/vi/{video['id']}/sddefault.jpg",
    "sourceDate": snippet['publishedAt'],
    "sourceEpoch": int(parse_datetime(snippet['publishedAt']).timestamp()),
    "sourceDescription": snippet['description'],
    "src": "youtube",
    "sourceThumbnails": snippet['thumbnails'],
    "sourceVideoDuration": int(duration_seconds),
    "sourceVideoWidth": 1080,
    "sourceVideoHeight": 1920,
    "sourceVideoOrientation": "portrait"
}
```

#### MongoDB Insert

```python
collection.insert_many(qualified_records, ordered=False)
```

Using `ordered=False` ensures that if any individual insert fails (e.g., duplicate key), the remaining inserts continue.

#### Downstream Publishing

After successful MongoDB insertion, each record is published individually to the `raw_youtube_shorts_ingestion` Pub/Sub topic.

## Hardcoded Values Reference

| Value | Field | Rationale |
|---|---|---|
| `1080` | `sourceVideoWidth` | YouTube Shorts standard width |
| `1920` | `sourceVideoHeight` | YouTube Shorts standard height |
| `"portrait"` | `sourceVideoOrientation` | YouTube Shorts are always vertical |
| `"youtube"` | `src` | Source platform identifier |
| `"sddefault.jpg"` | Thumbnail URL suffix | Standard definition thumbnail |
| `50` | API batch size | YouTube API maximum IDs per request |
| `5` seconds | Scrape timeout | HTTP timeout per publisher page |
| `60` seconds | Max duration | YouTube Shorts maximum length |
| `24` hours | Recency window | Content freshness threshold |

## Error Handling Summary

| Component | Error Type | Handling |
|---|---|---|
| GCS read | Bucket/file not found | Unhandled; function crashes |
| Web scraping | HTTP timeout (5s) | Publisher skipped; loop continues |
| Web scraping | Parse failure (no ytInitialData) | Publisher skipped; loop continues |
| YouTube API | Quota exceeded (403) | Function fails for remaining batch |
| YouTube API | Invalid video IDs | Silently skipped (not in response) |
| Duration validation | Out of range | Video excluded |
| Redirect check | Non-200 response | Video excluded |
| Recency check | Older than 24h | Video excluded |
| MongoDB insert | Duplicate key | Ignored (`ordered=False`) |
| MongoDB insert | Connection failure | Function fails |
| Pub/Sub publish | Publish failure | Message lost; no application-level retry |

## Monitoring and Observability

| Aspect | Mechanism |
|---|---|
| Function execution | Cloud Functions logs (Cloud Logging) |
| Invocation failures | Cloud Scheduler monitors HTTP response codes |
| Pub/Sub delivery | Pub/Sub dead-letter topics (if configured) |
| MongoDB connectivity | Connection errors in function logs |
| API quota usage | YouTube API Console quota dashboard |
