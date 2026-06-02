# YouTube Videos Ingestion -- Data Specification

## Data Sources

### Publisher Configuration CSV

| Attribute | Value |
|---|---|
| Location | GCS: `de-raw-ingestion/videos/videos_publishers_config.csv` |
| Encoding | ISO-8859-1 |
| Format | CSV with headers |

The CSV contains channel-level configuration including channel IDs, publisher metadata, category, language, and the `to_scrape` flag that controls downstream routing.

### YouTube Channel Page

| Attribute | Value |
|---|---|
| URL Pattern | `https://www.youtube.com/channel/{channel_id}/videos` |
| Format | HTML |
| Extraction Target | `ytInitialData` JavaScript object embedded in page source |
| JSONPath | `$..videoRenderer` |

## Extracted Video Fields

| Field | Type | Source | Description |
|---|---|---|---|
| `video_id` | string | `videoRenderer.videoId` | YouTube video identifier |
| `title` | string | `videoRenderer.title.runs[0].text` | Video title |
| `published_time` | datetime (IST) | `videoRenderer.publishedTimeText.simpleText` | Converted from relative time string (e.g., "2 hours ago") to IST absolute timestamp |
| `duration` | string | `videoRenderer.lengthText.simpleText` | Video duration in `HH:MM:SS` or `MM:SS` format |
| `width` | integer | `videoRenderer.thumbnail.thumbnails[].width` | Thumbnail width in pixels |
| `height` | integer | `videoRenderer.thumbnail.thumbnails[].height` | Thumbnail height in pixels |
| `orientation` | string | Computed from width/height | `landscape`, `portrait`, or `square` |

## Thumbnail URL Specification

Base pattern: `https://i.ytimg.com/vi/{video_id}/{size}.jpg`

| Size Key | Dimensions | URL Suffix |
|---|---|---|
| `default` | 120 x 90 | `default.jpg` |
| `mqdefault` | 320 x 180 | `mqdefault.jpg` |
| `hqdefault` | 480 x 360 | `hqdefault.jpg` |
| `sddefault` | 640 x 480 | `sddefault.jpg` |
| `maxresdefault` | 1280 x 720 | `maxresdefault.jpg` |

## Pub/Sub Message Schemas

### Topic: NewRawVideosIngestion_publishers_channel_data

Published by `FetchYTChannelsData`. Contains raw scraped channel data including all `videoRenderer` objects and publisher config metadata.

| Field | Type | Description |
|---|---|---|
| `channel_id` | string | YouTube channel identifier |
| `publisher_config` | object | Row from publisher config CSV |
| `video_renderers` | array[object] | Raw `videoRenderer` JSON objects |
| `scrape_timestamp` | string (ISO 8601) | Time of scrape in IST |

### Topic: NewRawVideosIngestion_processed_data

Published by `ProcessYTChannelsData` when `to_scrape=False`. Batch publish.

| Field | Type | Description |
|---|---|---|
| `video_id` | string | YouTube video identifier |
| `title` | string | Video title |
| `published_time` | string (ISO 8601) | Publication time in IST |
| `duration` | string | Video duration |
| `thumbnails` | object | Map of size key to URL |
| `orientation` | string | `landscape` / `portrait` / `square` |
| `publisher` | object | Publisher metadata from config |
| `category` | string | Content category |
| `language` | string | Content language |

### Topic: NewRawYoutubeScraper_metadata

Published by `ProcessYTChannelsData` when `to_scrape=True`. Per-record publish.

Includes all fields from `NewRawVideosIngestion_processed_data` plus:

| Field | Type | Description |
|---|---|---|
| `to_scrape` | boolean | Always `True` |
| `hls_manifest_url` | string | HLS manifest URL on `vcdn.jionews.com` |

## Redis Cache Schema

| Attribute | Value |
|---|---|
| Instance | `de_videos_id_cache` |
| Key format | `{video_id}_{category}_{language}` |
| Value | Existence check (set membership or simple value) |
| TTL | 48 hours |

## Recency Filter

- Only videos with a computed `published_time` within the last 24 hours from the current IST time are retained.
- Videos older than 24 hours are silently discarded during processing.

## Data Quality Rules

| Rule | Stage | Behavior on Violation |
|---|---|---|
| `video_id` must be non-empty | ProcessYTChannelsData | Record skipped |
| `published_time` must be parseable | ProcessYTChannelsData | Record skipped |
| Video must be within 24h recency window | ProcessYTChannelsData | Record filtered out |
| Composite key must not exist in Redis | ProcessYTChannelsData | Record deduplicated (skipped) |
| Config CSV must be valid ISO-8859-1 | FetchYTChannelsData | Function may error |

## Data Volume Estimates

| Metric | Typical Value |
|---|---|
| Configured channels | Varies per config CSV |
| Videos per channel page | 10-30 (YouTube default load) |
| Videos passing 24h filter | ~5-15 per channel |
| Net new videos per run (post-dedup) | Depends on schedule frequency |
