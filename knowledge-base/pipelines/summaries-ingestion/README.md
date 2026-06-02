# Summaries Ingestion Pipeline

## Overview

The Summaries Ingestion pipeline fetches summary-format content from publisher feeds, processes records through hygiene validation, routes hygienic records through image CDN and into MongoDB, and sends unhygienic records to an LLM-based async summarization service for content regeneration.

## Pipeline Identity

| Attribute             | Value                                                      |
|-----------------------|------------------------------------------------------------|
| Pipeline Name         | Summaries Ingestion                                        |
| GCP Project           | `jiox-328108`                                              |
| GCP Project Number    | `266686822828`                                             |
| Region                | `asia-south1`                                              |
| Trigger               | Cloud Scheduler (cron) -> HTTP                             |
| Pipeline Type         | Linear chain with hygiene-based branching                  |
| Number of Functions   | 5 Cloud Functions + 1 Cloud Run service                    |
| Primary Database      | MongoDB (`ingestion-data.raw_summaries_insgestion_data`)   |
| Cache Layer           | Redis                                                      |
| Image Storage         | GCS (`img-cdn-bucket`, shared with Headlines)              |

**Note**: The MongoDB collection name contains a production typo: `raw_summaries_insgestion_data` (not `ingestion`). This is intentional documentation of the actual production state.

## Function Chain

```
Cloud Scheduler (HTTP)
    |
    v
FetchFeedsData ──Pub/Sub──> ProcessSummaries ──Pub/Sub──> imagecdn
                                                            |
                                                   ┌───────┴────────┐
                                                   v                v
                                            PushToMongoDB   summarization-async
                                            (hygienic)      (Cloud Run, unhygienic)
```

## Cloud Functions and Services

| Component              | Type            | Purpose                                          |
|------------------------|-----------------|--------------------------------------------------|
| `FetchFeedsData`       | Cloud Function  | Fetch raw feeds from publisher endpoints          |
| `ProcessSummaries`     | Cloud Function  | Deduplicate, validate hygiene, enrich records     |
| `imagecdn`             | Cloud Function  | Download, resize, upload images to CDN (shared)   |
| `PushToMongoDB`        | Cloud Function  | Persist hygienic records to MongoDB               |
| `summarization-async`  | Cloud Run       | LLM-based summarization for unhygienic records    |

## Pub/Sub Topics

| Topic Name                                | Publisher           | Subscriber             |
|-------------------------------------------|---------------------|------------------------|
| `RawSummariesIngestion_FeedsData`         | `FetchFeedsData`    | `ProcessSummaries`     |
| `NewRawHeadlinesIngestion_image_cdn`      | `ProcessSummaries`  | `imagecdn` (shared)    |
| `RawSummariesIngestion_ProcessedData`     | `imagecdn`          | `PushToMongoDB`        |
| `RawSummariesIngestion_HygineFailure`     | `ProcessSummaries`  | `summarization-async`  |

**Note**: The `imagecdn` Pub/Sub topic (`NewRawHeadlinesIngestion_image_cdn`) is shared with the Headlines Ingestion pipeline.

## External Dependencies

| Dependency         | Type        | Endpoint                                                   |
|--------------------|-------------|------------------------------------------------------------|
| Publisher Feeds    | HTTP GET    | Various publisher RSS/JSON endpoints                        |
| Gemini LLM        | HTTPS       | Gemini 2.5 Flash API                                       |
| Article Proxy      | HTTPS       | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` |

## Secrets

| Secret Name        | Purpose                   | Used By                 |
|--------------------|---------------------------|-------------------------|
| `mongosh_de_uri`   | MongoDB connection string | `PushToMongoDB`         |
| `GEMINI_API_KEY`   | Gemini LLM API key        | `summarization-async`   |

## Key Business Rules

1. **Deduplication**: Redis cache `de_summaries_cache` keyed by title with 48h TTL.
2. **Hygiene Rules (English only)**: Title 26-105 characters, summary 200-360 characters, no HTML tags, fewer than 3 special characters.
3. **Default Thumbnail Handling**: Records with `isDefaultThumbnail=true` have publisher renamed to `InsideMedia` with ID `000`.
4. **LLM Summarization**: Unhygienic records are sent to Gemini 2.5 Flash for re-summarization.
5. **Two-Pass LLM Strategy**: URL-based grounding first, content fallback via proxy on failure.
6. **JSON Parsing Resilience**: 3-stage parsing (direct, strip markdown fences, extract `{}`).

## Related Documentation

- [AS-IS.md](./AS-IS.md) - Current state analysis and known issues
- [DATA-SPEC.md](./DATA-SPEC.md) - Data schemas, field definitions, transformations
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture with Mermaid diagrams
- [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) - MongoDB collections, Redis keys
- [TECH-SPEC.md](./TECH-SPEC.md) - Technical implementation details
