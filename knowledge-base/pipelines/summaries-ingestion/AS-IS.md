# Summaries Ingestion - AS-IS State

## Current State Summary

The Summaries Ingestion pipeline processes summary-format content from publisher feeds, applying hygiene validation rules to determine whether records meet quality standards. Hygienic records flow through the standard image CDN and MongoDB persistence path. Unhygienic records are routed to an LLM-based async summarization service that uses Gemini 2.5 Flash to regenerate compliant summaries.

## Pipeline Flow (Current)

1. **Cloud Scheduler** fires an HTTP trigger on a cron schedule.
2. **FetchFeedsData** reads publisher feed configurations, fetches all feeds, parses RSS/XML and JSON formats, and publishes raw records to Pub/Sub.
3. **ProcessSummaries** receives raw records, performs Redis-based deduplication (by title), applies hygiene validation rules (English only), and routes:
   - **Hygienic records**: Published to the shared image CDN topic for standard processing.
   - **Unhygienic records**: Published to the hygiene failure topic for LLM re-summarization.
4. **imagecdn** (shared with Headlines pipeline) processes images and publishes to the summaries-specific processed data topic.
5. **PushToMongoDB** persists hygienic records to MongoDB.
6. **summarization-async** (Cloud Run) receives unhygienic records, calls Gemini 2.5 Flash for re-summarization, and upserts results directly to MongoDB.

## Known Issues and Technical Debt

### Critical

| ID   | Issue                                           | Impact                                                     |
|------|-------------------------------------------------|------------------------------------------------------------|
| S-01 | MongoDB collection name typo (`insgestion`)     | Production collection has permanent typo; changing would require migration |
| S-02 | Hygiene rules are English-only                  | Non-English summaries have no quality validation            |

### Moderate

| ID   | Issue                                           | Impact                                                     |
|------|-------------------------------------------------|------------------------------------------------------------|
| S-03 | Shared image CDN topic with Headlines           | Coupling between pipelines; topic naming mismatch           |
| S-04 | Default thumbnail publisher rename to `InsideMedia` | Obscures actual publisher identity for default-image records |
| S-05 | LLM proxy fallback adds latency                 | Two-pass strategy doubles processing time on URL failures   |
| S-06 | 3-stage JSON parsing for LLM responses          | Indicates unreliable structured output from Gemini          |

### Low

| ID   | Issue                                           | Impact                                                     |
|------|-------------------------------------------------|------------------------------------------------------------|
| S-07 | Topic name typo `HygineFailure`                 | Inconsistent naming convention in Pub/Sub topics            |
| S-08 | Exponential backoff hardcoded to 2^attempt      | No configuration for retry behavior                        |

## Hygiene Validation Rules

Hygiene validation is applied to **English-language records only**. Non-English records bypass hygiene checks entirely.

| Rule                    | Criteria                        | Failure Action                    |
|-------------------------|---------------------------------|-----------------------------------|
| Title length            | 26 to 105 characters            | Route to LLM re-summarization    |
| Summary length          | 200 to 360 characters           | Route to LLM re-summarization    |
| HTML content            | No HTML tags allowed             | Route to LLM re-summarization    |
| Special characters      | Fewer than 3 special characters  | Route to LLM re-summarization    |

## Default Thumbnail Handling

When a record has a default/placeholder thumbnail:

| Field               | Original Value      | Modified Value |
|----------------------|---------------------|----------------|
| `isDefaultThumbnail` | `true`              | `true`         |
| `sourcePublisherName`| (actual publisher)  | `InsideMedia`  |
| `sourcePublisherId`  | (actual publisher ID)| `000`         |

This re-attribution is applied before MongoDB persistence.

## LLM Async Summarization Service

The `summarization-async` Cloud Run service handles records that fail hygiene validation.

### Two-Pass Strategy

1. **Pass 1 (URL Mode)**: Send the article URL to Gemini 2.5 Flash with `url_context` tool enabled. The model attempts to access and summarize the content directly from the URL.
2. **Pass 2 (Content Fallback)**: If URL mode fails, fetch article content through the proxy service (`jn-article-render-proxy`), then send the rendered content to Gemini as input.

### Proxy Service

| Attribute    | Value                                                             |
|--------------|-------------------------------------------------------------------|
| URL          | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` |
| Purpose      | Render and extract article content for LLM consumption            |
| Protocol     | HTTPS GET                                                         |

### LLM Configuration

| Parameter    | Value                     |
|--------------|---------------------------|
| Model        | `gemini-2.5-flash`        |
| Temperature  | `0`                       |
| Tools        | `[{"url_context": {}}]`   |

### Retry Strategy

| Parameter         | Value                          |
|-------------------|--------------------------------|
| Max Attempts      | 3                              |
| Backoff           | Exponential: `2^attempt` seconds |
| Retry On          | HTTP 503 responses             |

### JSON Response Parsing

The LLM response undergoes 3-stage parsing to extract structured JSON:

1. **Direct parse**: `json.loads(response_text)` - attempt direct JSON parsing.
2. **Strip markdown fences**: Remove `` ```json `` and `` ``` `` markers, then parse.
3. **Extract JSON object**: Regex extract first `{...}` block from response text, then parse.

## Deduplication Strategy

Single Redis cache check by normalized title:

| Attribute    | Value                     |
|--------------|---------------------------|
| Cache Name   | `de_summaries_cache`      |
| Key          | `title` (article title)   |
| TTL          | 48 hours                  |

## Shared Infrastructure

The Summaries Ingestion pipeline shares the following infrastructure with Headlines Ingestion:

| Component         | Shared Resource                              | Notes                                |
|-------------------|----------------------------------------------|--------------------------------------|
| Image CDN         | `imagecdn` Cloud Function                    | Same function processes both pipelines |
| Pub/Sub Topic     | `NewRawHeadlinesIngestion_image_cdn`         | Shared input topic for image CDN     |
| GCS Bucket        | `img-cdn-bucket`                             | Same bucket for all image renditions |

## External Service Dependencies

| Service                  | Protocol | Auth       | Timeout | Notes                                |
|--------------------------|----------|------------|---------|--------------------------------------|
| Publisher Feeds          | HTTP/S   | None       | Default | Varies by publisher                 |
| Gemini 2.5 Flash         | HTTPS    | API Key    | Default | LLM summarization                   |
| Article Render Proxy     | HTTPS    | IAM        | Default | Content extraction for LLM fallback |
| Redis                    | TCP      | Auth       | Default | Deduplication cache                 |
| MongoDB                  | TLS      | URI Secret | Default | Persistence layer                   |
