# Headlines Ingestion Pipeline

## Overview

The Headlines Ingestion pipeline is the primary content acquisition system for JioNews. It fetches article headlines from external publisher RSS/XML feeds and JSON APIs, processes them through deduplication, enrichment, image CDN upload, and hygiene checks, then persists hygienic records to MongoDB and routes rejected records to a separate failure collection.

## Pipeline Identity

| Attribute             | Value                                                    |
|-----------------------|----------------------------------------------------------|
| Pipeline Name         | Headlines Ingestion                                      |
| GCP Project           | `jiox-328108`                                            |
| GCP Project Number    | `266686822828`                                           |
| Region                | `asia-south1`                                            |
| Trigger               | Cloud Scheduler (cron) -> HTTP                           |
| Pipeline Type         | Linear chain with branching (success/failure paths)      |
| Number of Functions   | 5 Cloud Functions                                        |
| Primary Database      | MongoDB (`ingestion-data.raw_headlines_ingestion_data`)  |
| Failure Database      | MongoDB (`ingestion-data.headlines_hygiene_failures`)    |
| Cache Layer           | Redis                                                    |
| Image Storage         | GCS (`img-cdn-bucket`)                                   |

## Function Chain

```
Cloud Scheduler (HTTP)
    |
    v
fetchfeedsdata ──Pub/Sub──> processheadlines ──Pub/Sub──> imagecdn
                                                             |
                                                    ┌───────┴────────┐
                                                    v                v
                                             PushToMongoDB   rejected-pushtomongo
                                             (success)       (failure)
```

## Cloud Functions

| Function                 | Trigger Type           | Entry Point                  | Purpose                                      |
|--------------------------|------------------------|------------------------------|----------------------------------------------|
| `fetchfeedsdata`         | HTTP                   | `main(req_ph1)`              | Fetch raw feeds from publisher endpoints      |
| `processheadlines`       | HTTP (Pub/Sub push)    | `main(req)`                  | Deduplicate, enrich, scrape article bodies    |
| `imagecdn`               | HTTP (Pub/Sub push)    | `main(req)`                  | Download, resize, upload images to CDN        |
| `PushToMongoDB`          | CloudEvent             | `write_to_mongodb(cloud_event)` | Persist hygienic records to MongoDB        |
| `rejected-pushtomongo`   | CloudEvent             | `write_to_mongodb(cloud_event)` | Persist rejected records to failure collection |

## Pub/Sub Topics

| Topic Name                                      | Publisher            | Subscriber               |
|-------------------------------------------------|----------------------|--------------------------|
| `NewRawHeadlinesIngestion_raw_feeds_data`       | `fetchfeedsdata`     | `processheadlines`       |
| `NewRawHeadlinesIngestion_image_cdn`            | `processheadlines`   | `imagecdn`               |
| `NewRawHeadlinesIngestion_processed_data`       | `imagecdn`           | `PushToMongoDB`          |
| `NewRawHeadlinesIngestion_rejected_data`        | `imagecdn`           | `rejected-pushtomongo`   |

## External Dependencies

| Dependency            | Type        | Endpoint                                              |
|-----------------------|-------------|-------------------------------------------------------|
| Article Scraper (Primary) | HTTP GET | `https://service.jionews.com/v1/scrape/scrape/`      |
| Article Scraper (Fallback)| HTTP POST| `http://34.36.231.72/crawl` (English only)            |
| Publisher Feeds       | HTTP GET    | Various publisher RSS/JSON endpoints                   |
| GCS Feed Config       | File        | `de-raw-ingestion/headlines/headlines_publishers_feeds.csv` |

## Secrets

| Secret Name       | Purpose                  |
|-------------------|--------------------------|
| `mongosh_de_uri`  | MongoDB connection string |

## Key Business Rules

1. **Deduplication**: Two-layer Redis cache checks by `link_cat_lang` and `normalized_title` (both 48h TTL).
2. **UTM Tagging**: All URLs appended with `utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews`, except ESPNcricinfo which uses `ex_cid=jionews`.
3. **Image Processing**: 5 renditions generated (original, fhd, hd, sd, low) with JPEG quality 90.
4. **Thumbnail Fallback**: 12-step priority chain; records with no thumbnail are rejected.
5. **Newspoint Publishers**: Use different field mapping (`hl`->title, `mwu`->url, `dl`->date, `sec`->category).
6. **Epoch Correction**: Subtracts 19800s (IST offset) if publisher epoch exceeds current time.
7. **Default Images**: 22 variants for `latest_news` category, 10 for others.

## Related Documentation

- [AS-IS.md](./AS-IS.md) - Current state analysis and known issues
- [DATA-SPEC.md](./DATA-SPEC.md) - Data schemas, field definitions, transformations
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture with Mermaid diagrams
- [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) - MongoDB collections, Redis keys, GCS layout
- [TECH-SPEC.md](./TECH-SPEC.md) - Technical implementation details
