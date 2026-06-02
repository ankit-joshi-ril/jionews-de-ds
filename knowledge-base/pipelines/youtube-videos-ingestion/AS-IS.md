# YouTube Videos Ingestion -- AS-IS Process Document

## Current State Description

The YouTube Videos Ingestion pipeline is a production system that discovers new video content from YouTube channels by scraping public channel pages. It runs on a scheduled cadence via Cloud Scheduler, processes discovered videos through a three-function chain, and persists results to MongoDB.

## Process Flow (Current State)

1. **Cloud Scheduler** fires an HTTP request to `FetchYTChannelsData`.
2. `FetchYTChannelsData` reads the publisher configuration CSV from GCS (`de-raw-ingestion/videos/videos_publishers_config.csv`, ISO-8859-1 encoded).
3. For each configured channel, the function constructs the URL `https://www.youtube.com/channel/{channel_id}/videos` and scrapes the page with a 5-second timeout.
4. BeautifulSoup parses the HTML response and extracts the `ytInitialData` JavaScript object from the page source.
5. JSONPath expression `$..videoRenderer` is applied to extract individual video renderer objects.
6. Extracted video metadata is published to Pub/Sub topic `NewRawVideosIngestion_publishers_channel_data`.
7. Fetch operations run concurrently using `ThreadPoolExecutor(10)`.
8. `ProcessYTChannelsData` receives each message and processes video records using `ThreadPoolExecutor(50)`.
9. For each video, the function extracts: `video_id`, `title`, `published_time` (relative time string converted to IST), `duration`, `width`, `height`, and `orientation`.
10. A 24-hour recency filter discards videos older than 24 hours based on the computed publication time.
11. Redis is queried with the composite key `video_id_cat_lang` to deduplicate (TTL: 48 hours).
12. Thumbnail URLs are constructed for all standard YouTube sizes.
13. The `to_scrape` flag determines routing:
    - `to_scrape=False`: Records are batch-published to `NewRawVideosIngestion_processed_data`.
    - `to_scrape=True`: Each record is individually published to `NewRawYoutubeScraper_metadata` with HLS manifest URLs on `vcdn.jionews.com`.
14. `PushToMongoDB` receives processed data via CloudEvent and writes to `ingestion-data.raw_videos_ingestion_data`.

## Current Limitations and Known Issues

| Issue | Impact | Severity |
|---|---|---|
| HTML scraping is fragile; YouTube page structure changes can break extraction | Pipeline silently produces zero results when YouTube changes page layout | High |
| 5-second timeout on channel page fetch may be insufficient for slow responses | Individual channels may be skipped on network congestion | Medium |
| Relative time parsing ("2 hours ago") is inherently imprecise | Publication timestamps may have minute-level inaccuracy | Low |
| No dead-letter queue configured for failed Pub/Sub messages | Failed messages may be retried indefinitely or dropped | Medium |
| ISO-8859-1 encoding on config CSV limits character set for publisher names | Publisher names with non-Latin characters may be corrupted | Low |
| Redis cache TTL (48h) means a video re-published after 48h could be re-ingested | Possible duplicate entries if a video re-surfaces | Low |

## Operational Characteristics

| Metric | Value |
|---|---|
| Fetch concurrency | 10 threads |
| Process concurrency | 50 threads |
| Recency window | 24 hours |
| Dedup cache TTL | 48 hours |
| Scrape timeout | 5 seconds |
| Trigger mechanism | Cloud Scheduler (HTTP) |

## Data Flow Summary

```
Cloud Scheduler
  --> FetchYTChannelsData (HTTP)
       --> GCS (read config CSV)
       --> YouTube (scrape channel pages)
       --> Pub/Sub: NewRawVideosIngestion_publishers_channel_data
            --> ProcessYTChannelsData (background)
                 --> Redis (dedup check)
                 --> Pub/Sub: NewRawVideosIngestion_processed_data (to_scrape=False, batch)
                 --> Pub/Sub: NewRawYoutubeScraper_metadata (to_scrape=True, per-record)
                      --> PushToMongoDB (CloudEvent)
                           --> MongoDB: ingestion-data.raw_videos_ingestion_data
```

## Integration Points

| System | Direction | Protocol | Purpose |
|---|---|---|---|
| YouTube | Inbound | HTTPS (scraping) | Video metadata discovery |
| GCS (`de-raw-ingestion`) | Inbound | GCS API | Publisher configuration |
| Redis | Bidirectional | Redis protocol | Deduplication |
| Pub/Sub (3 topics) | Outbound | gRPC | Inter-function messaging |
| MongoDB Atlas | Outbound | MongoDB wire protocol | Persistent storage |
| vcdn.jionews.com | Referenced | HTTPS | HLS manifest URLs for scraped videos |
