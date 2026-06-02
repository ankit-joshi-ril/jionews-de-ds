# Webstories Ingestion - AS-IS State

## Current State Summary

The Webstories Ingestion pipeline is the simplest content acquisition pipeline in JioNews DE. It consists of just 2 Cloud Functions: one to fetch and process web stories from publisher APIs and RSS feeds, and one to persist results to MongoDB. Unlike other pipelines, it has no image CDN stage, no Redis deduplication, and no hygiene branching.

## Pipeline Flow (Current)

1. **Cloud Scheduler** fires an HTTP request on a cron schedule.
2. **RawWebStoriesIngestion** reads the local publisher CSV, fetches data from each publisher (API or RSS), applies per-publisher field mapping, validates thumbnail URLs, appends UTM parameters, enforces HTTPS, and publishes records to Pub/Sub.
3. **PushToMongoDB** receives records via CloudEvent and inserts them into MongoDB.

## Known Issues and Technical Debt

### Moderate

| ID   | Issue                                           | Impact                                                   |
|------|-------------------------------------------------|----------------------------------------------------------|
| W-01 | Publisher CSV is local (not on GCS)             | Config changes require function redeployment             |
| W-02 | No Redis deduplication                          | Duplicate stories may be ingested on consecutive runs    |
| W-03 | No image CDN processing                         | Thumbnail URLs point directly to publisher sources       |
| W-04 | Thumbnail validation via HTTP GET               | Synchronous HTTP call per record adds latency            |

### Low

| ID   | Issue                                           | Impact                                                   |
|------|-------------------------------------------------|----------------------------------------------------------|
| W-05 | Field mapping stored as JSON string in CSV      | Complex to edit and prone to CSV escaping issues         |
| W-06 | No hygiene validation                           | No quality checks on title/description content           |
| W-07 | http->https replacement is blanket              | May break publishers that only serve over HTTP           |

## Source Type Handling

### API Sources (type: `api`)

- HTTP GET to the publisher endpoint.
- Response parsed as JSON.
- `data_list_path` CSV column specifies the JSON path to the array of story objects (e.g., `data.stories`, `results`).
- Per-publisher `mapping` JSON string defines field extraction from each story object.

### Feed Sources (type: `feed`)

- HTTP GET to the publisher feed URL.
- Response parsed using `feedparser` library.
- Standard RSS field extraction.
- Per-publisher `mapping` JSON string defines field extraction overrides.

## Field Mapping System

Each publisher row in the CSV contains a `mapping` column with a JSON string that maps the publisher's proprietary field names to the standard JioNews schema.

Example mapping JSON:
```json
{
  "title": "headline",
  "url": "story_url",
  "thumbnail": "cover_image",
  "published_date": "created_at"
}
```

This allows each publisher to have completely different response structures while producing a uniform output record.

## URL Processing

### UTM Parameters

All web story URLs are appended with:
```
utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories
```

Note: The campaign value is `JioNewsStories` (not `JioNews` as in Headlines).

### HTTPS Enforcement

All URLs undergo `http://` to `https://` replacement:
```python
url = url.replace("http://", "https://")
```

This applies to both article URLs and thumbnail URLs.

## Thumbnail Validation

Unlike Headlines (which has a 12-step extraction chain) and Summaries (which has default thumbnails), Webstories validates thumbnails via a direct HTTP GET request:

1. Extract thumbnail URL from the mapped field.
2. Perform HTTP GET to the thumbnail URL.
3. If the response is successful (2xx), the URL is considered valid.
4. If the response fails, the thumbnail URL may be set to empty or the record may be skipped (implementation-dependent).

## Comparison with Other Pipelines

| Feature                | Headlines | Summaries | Webstories |
|------------------------|-----------|-----------|------------|
| Cloud Functions        | 5         | 5 + 1 CR  | 2          |
| Image CDN              | Yes       | Yes (shared) | No      |
| Redis Dedup            | Yes (2 caches) | Yes (1 cache) | No  |
| Hygiene Validation     | Thumbnail only | English content | None |
| LLM Processing         | No        | Yes       | No         |
| Config Source           | GCS       | GCS       | Local CSV  |
| UTM Campaign           | JioNews   | JioNews   | JioNewsStories |
| Article Scraping       | Yes       | No        | No         |
| Thumbnail Validation   | 12-step chain | Default fallback | HTTP GET |

## External Service Dependencies

| Service            | Protocol | Auth  | Timeout | Notes                                |
|--------------------|----------|-------|---------|--------------------------------------|
| Publisher APIs     | HTTP/S   | None  | Default | JSON API endpoints                   |
| Publisher Feeds    | HTTP/S   | None  | Default | RSS feed endpoints                   |
| Thumbnail URLs     | HTTP/S   | None  | Default | Validation via HTTP GET              |
| MongoDB            | TLS      | URI   | Default | Persistence layer                    |
