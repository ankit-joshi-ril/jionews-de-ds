# Webstories Ingestion Pipeline

## Overview

The Webstories Ingestion pipeline fetches web story content from publisher API endpoints and RSS feeds, maps publisher-specific fields via configurable JSON mappings, validates thumbnails, and persists records to MongoDB. It is the simplest ingestion pipeline in the JioNews DE platform with only 2 Cloud Functions.

## Pipeline Identity

| Attribute             | Value                                                    |
|-----------------------|----------------------------------------------------------|
| Pipeline Name         | Webstories Ingestion                                     |
| GCP Project           | `jiox-328108`                                            |
| GCP Project Number    | `266686822828`                                           |
| Region                | `asia-south1`                                            |
| Trigger               | Cloud Scheduler (cron) -> HTTP                           |
| Pipeline Type         | Simple linear chain (2 functions)                        |
| Number of Functions   | 2 Cloud Functions                                        |
| Primary Database      | MongoDB (`ingestion-data.raw_web_stories_ingestion_data`)|
| Config Source         | Local CSV file (bundled with Cloud Function)             |

## Function Chain

```
Cloud Scheduler (HTTP)
    |
    v
RawWebStoriesIngestion ──Pub/Sub──> PushToMongoDB
```

## Cloud Functions

| Function                  | Trigger Type  | Purpose                                          |
|---------------------------|---------------|--------------------------------------------------|
| `RawWebStoriesIngestion`  | HTTP          | Fetch, parse, validate, and publish web stories  |
| `PushToMongoDB`           | CloudEvent    | Persist records to MongoDB                        |

## Pub/Sub Topics

| Topic Name                | Publisher                  | Subscriber    |
|---------------------------|----------------------------|---------------|
| `RawWebStoriesIngestion`  | `RawWebStoriesIngestion`   | `PushToMongoDB` |

## Configuration

Unlike other pipelines, the publisher configuration CSV is **local to the Cloud Function** (not stored on GCS). The CSV is bundled with the function deployment package.

### CSV Columns

| Column           | Type   | Description                                      |
|------------------|--------|--------------------------------------------------|
| `sys_pub_name`   | string | System publisher name identifier                 |
| `endpoint`       | string | Publisher API or feed endpoint URL               |
| `data_list_path` | string | JSON path to the array of stories in API response|
| `type`           | string | `api` or `feed`                                  |
| `mapping`        | string | JSON string defining field mapping               |
| `category`       | string | Content category                                 |
| `language`       | string | Content language                                 |

## External Dependencies

| Dependency        | Type     | Endpoint                          |
|-------------------|----------|-----------------------------------|
| Publisher APIs    | HTTP GET | Various publisher API endpoints   |
| Publisher Feeds   | HTTP GET | Various publisher RSS feed URLs   |

## Secrets

| Secret Name      | Purpose                  |
|------------------|--------------------------|
| `mongosh_de_uri` | MongoDB connection string|

## Key Business Rules

1. **Two Source Types**: Supports both API (JSON) and Feed (RSS via feedparser) sources.
2. **Configurable Field Mapping**: Each publisher has a JSON mapping string defining how to extract fields.
3. **UTM Parameters**: All URLs tagged with `utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories`.
4. **HTTPS Enforcement**: All `http://` URLs are replaced with `https://`.
5. **Thumbnail Validation**: Thumbnail URLs are validated via HTTP GET request.
6. **Local Config**: Publisher CSV is local to the Cloud Function, not on GCS.

## Related Documentation

- [AS-IS.md](./AS-IS.md) - Current state analysis and known issues
- [DATA-SPEC.md](./DATA-SPEC.md) - Data schemas, field definitions, transformations
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture with Mermaid diagrams
- [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) - MongoDB collections
- [TECH-SPEC.md](./TECH-SPEC.md) - Technical implementation details
