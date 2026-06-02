# Headlines Ingestion - AS-IS State

## Current State Summary

The Headlines Ingestion pipeline is the longest-running and most complex ingestion pipeline in the JioNews DE platform. It processes hundreds of publisher feeds across multiple languages, handling RSS/XML and JSON feed formats with publisher-specific parsing logic.

## Pipeline Flow (Current)

The pipeline executes as a 5-function linear chain with a terminal branch:

1. **Cloud Scheduler** fires an HTTP request on a cron schedule.
2. **fetchfeedsdata** reads the publisher feed CSV from GCS, fetches all feeds concurrently using `ThreadPoolExecutor(100)`, parses RSS/XML (via `feedparser`) and JSON feeds, and publishes raw records to Pub/Sub.
3. **processheadlines** receives raw records, deduplicates against Redis, scrapes article bodies from publisher URLs, enriches records with metadata, and publishes to Pub/Sub.
4. **imagecdn** downloads source thumbnail images, performs EXIF transpose, generates 5 image renditions, uploads to GCS `img-cdn-bucket`, and routes records to either the success or rejection Pub/Sub topic.
5. **PushToMongoDB** / **rejected-pushtomongo** persist records to their respective MongoDB collections.

## Known Issues and Technical Debt

### Critical

| ID   | Issue                                           | Impact                                                   |
|------|-------------------------------------------------|----------------------------------------------------------|
| H-01 | Dimension validation is commented out           | Oversized or undersized images pass through unchecked     |
| H-02 | Fallback scraper is HTTP (not HTTPS)            | Article body scraping fallback uses unencrypted transport |
| H-03 | Fallback scraper is English-only                | Non-English articles have no fallback scraping path       |

### Moderate

| ID   | Issue                                           | Impact                                                   |
|------|-------------------------------------------------|----------------------------------------------------------|
| H-04 | Custom `<image>` to `<thumbimage>` tag replacement | Fragile workaround for feedparser XML parsing issues   |
| H-05 | Hardcoded ESPNcricinfo URL extraction from `record['href']` | Publisher-specific branching in generic code path |
| H-06 | Epoch adjustment uses fixed 19800s offset       | Assumes IST; will break for non-IST publishers           |
| H-07 | ThreadPoolExecutor(100) for fetch, (50) for process | No adaptive concurrency; may overwhelm small publishers |
| H-08 | Newspoint publishers use completely different field mapping | Separate code path increases maintenance burden |

### Low

| ID   | Issue                                           | Impact                                                   |
|------|-------------------------------------------------|----------------------------------------------------------|
| H-09 | Default image selection (22 latest_news, 10 others) | Hardcoded default image pools; not configurable       |
| H-10 | 12-step thumbnail extraction priority chain     | Complex fallback logic; difficult to debug and extend    |
| H-11 | JPEG quality hardcoded at 90                    | No per-publisher or per-rendition quality configuration  |

## Feed Format Handling

### RSS/XML Feeds
- Parsed using `feedparser` library.
- Custom preprocessing: `<image>` tags are replaced with `<thumbimage>` tags before parsing to avoid feedparser conflicts with RSS `<image>` channel elements.
- Standard RSS fields mapped: `title`, `link`, `published`/`published_parsed`, `summary`, `media_content`, `media_thumbnail`.

### JSON Feeds
- Parsed using `json.loads()`.
- Expected structure: top-level key `items` containing an array of article objects.
- Direct field access on each item in the `items` array.

### Newspoint Publishers
- Publishers: `english-newspointapp`, `Indiatimes`, `Navbharat Times`, `Newspoint`.
- Field mapping differs from standard: `hl` -> title, `mwu` -> url, `dl` -> date, `sec` -> category.
- Requires separate parsing logic within the processing function.

## Concurrency Model

| Stage             | Executor                  | Max Workers | Purpose                          |
|-------------------|---------------------------|-------------|----------------------------------|
| Feed Fetching     | `ThreadPoolExecutor(100)` | 100         | Parallel HTTP GETs to publisher endpoints |
| Record Processing | `ThreadPoolExecutor(50)`  | 50          | Parallel dedup + scrape + enrich |

## Image Processing Pipeline (Current)

1. Download source thumbnail from `sourceThumbnailURL`.
2. Apply EXIF orientation transpose (auto-rotate based on EXIF data).
3. Generate 5 renditions:
   - `original` - Full source resolution
   - `fhd` - 1920x1080
   - `hd` - 1280x720
   - `sd` - 720x480
   - `low` - 480x320
4. Encode all renditions as JPEG with quality 90.
5. Upload to `img-cdn-bucket` with path pattern: `{rendition}/{sourceId}.jpeg`.
6. **Note**: Dimension validation is currently commented out, meaning all images pass regardless of source dimensions.

## Deduplication Strategy

Two independent Redis checks, both must pass for a record to proceed:

1. **Link-based dedup**: Key = `link_cat_lang` (composite of article URL + category + language). TTL = 48 hours. Cache name = `de_headlines_id_cache`.
2. **Title-based dedup**: Key = normalized title (lowercase, stripped). TTL = 48 hours. Cache name = `de_headlines_title_cache`.

If either cache returns a hit, the record is silently dropped (not routed to rejection).

## Rejection Criteria

Records are routed to `rejected-pushtomongo` when:
- Thumbnail URL is empty or missing after the 12-step extraction chain.
- Rejection reason is recorded as: "No thumbnail image url found".

## External Service Dependencies

| Service                | Protocol | Auth  | Timeout | Notes                                |
|------------------------|----------|-------|---------|--------------------------------------|
| Publisher RSS/JSON feeds | HTTP GET | None  | Default | Varies by publisher                 |
| Article Scraper (Primary) | HTTPS GET | None | Default | `service.jionews.com`             |
| Article Scraper (Fallback) | HTTP POST | None | Default | `34.36.231.72`, English only      |
| Redis                  | TCP      | Auth  | Default | Deduplication cache                 |
| MongoDB                | TCP      | URI   | Default | Persistence layer                   |
| GCS                    | HTTPS    | IAM   | Default | Feed config + image CDN storage     |

## Data Volume Characteristics

- Hundreds of publisher feeds across multiple languages.
- Each scheduler invocation processes the full feed list.
- Feed sizes vary from tens to thousands of articles per publisher.
- Image processing is the most resource-intensive stage.
- Redis deduplication prevents reprocessing of previously seen articles within 48h.
