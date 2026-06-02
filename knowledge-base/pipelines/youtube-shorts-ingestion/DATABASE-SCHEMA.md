# YouTube Shorts Ingestion - Database Schema

## Database Overview

| Attribute | Value |
|---|---|
| **Database Engine** | MongoDB |
| **Database Name** | `ingestion-data` |
| **Primary Collection** | `raw_short_videos_ingestion_data` |
| **Connection Secret** | `mongosh_de_uri` (GCP Secret Manager) |
| **TLS** | Enforced via `certifi` CA bundle |

## Collection: `raw_short_videos_ingestion_data`

### Purpose

Stores enriched metadata for YouTube Shorts that have passed all validation gates (duration, URL redirect, recency). This collection serves as the primary data store for ingested YouTube Shorts content, used by downstream processing pipelines and editorial systems.

### Document Schema

| Field | BSON Type | Required | Default | Description |
|---|---|---|---|---|
| `_id` | ObjectId | Yes | Auto-generated | MongoDB document identifier |
| `sourceVideoId` | String | Yes | - | YouTube video ID (e.g., `dQw4w9WgXcQ`) |
| `title` | String | Yes | - | Video title from YouTube API `snippet.title` |
| `sourceThumbnailURL` | String | Yes | - | SD thumbnail: `https://i.ytimg.com/vi/{id}/sddefault.jpg` |
| `sourceDate` | String | Yes | - | ISO 8601 publication timestamp from YouTube API |
| `sourceEpoch` | Number (Int64) | Yes | - | Unix epoch derived from `publishedAt` |
| `sourceDescription` | String | Yes | - | Video description from YouTube API `snippet.description` |
| `src` | String | Yes | `"youtube"` | Source platform identifier (always `"youtube"`) |
| `sourceThumbnails` | Object | Yes | - | Full YouTube thumbnails object (all resolutions) |
| `sourceVideoDuration` | Number (Int32) | Yes | - | Duration in seconds (range: 1-60) |
| `sourceVideoWidth` | Number (Int32) | Yes | `1080` | Video width in pixels (hardcoded) |
| `sourceVideoHeight` | Number (Int32) | Yes | `1920` | Video height in pixels (hardcoded) |
| `sourceVideoOrientation` | String | Yes | `"portrait"` | Video orientation (hardcoded) |

### Nested Object: `sourceThumbnails`

The `sourceThumbnails` field contains the full YouTube API thumbnails object with the following sub-objects:

| Sub-field | Type | Description |
|---|---|---|
| `sourceThumbnails.default` | Object | Default thumbnail (120x90) |
| `sourceThumbnails.default.url` | String | Thumbnail URL |
| `sourceThumbnails.default.width` | Number | Width in pixels |
| `sourceThumbnails.default.height` | Number | Height in pixels |
| `sourceThumbnails.medium` | Object | Medium thumbnail (320x180) |
| `sourceThumbnails.high` | Object | High thumbnail (480x360) |
| `sourceThumbnails.standard` | Object | Standard thumbnail (640x480) |
| `sourceThumbnails.maxres` | Object | Max resolution thumbnail (optional, 1280x720) |

Each sub-object follows the same structure: `{ url: String, width: Number, height: Number }`.

### Example Document

```json
{
  "_id": "ObjectId('65a1b2c3d4e5f6a7b8c9d0e1')",
  "sourceVideoId": "dQw4w9WgXcQ",
  "title": "Breaking News: Major Policy Update",
  "sourceThumbnailURL": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg",
  "sourceDate": "2025-01-15T10:30:00Z",
  "sourceEpoch": 1736935800,
  "sourceDescription": "Watch the latest breaking news update on the major policy changes...",
  "src": "youtube",
  "sourceThumbnails": {
    "default": {
      "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
      "width": 120,
      "height": 90
    },
    "medium": {
      "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
      "width": 320,
      "height": 180
    },
    "high": {
      "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
      "width": 480,
      "height": 360
    },
    "standard": {
      "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg",
      "width": 640,
      "height": 480
    }
  },
  "sourceVideoDuration": 45,
  "sourceVideoWidth": 1080,
  "sourceVideoHeight": 1920,
  "sourceVideoOrientation": "portrait"
}
```

## Indexes

### Deduplication Index

| Attribute | Value |
|---|---|
| **Field** | `sourceVideoId` |
| **Type** | Used in aggregation pipeline for dedup lookups |
| **Purpose** | ScrapeVideoIds queries this field to determine which video IDs already exist |

**Aggregation Pattern Used:**

```javascript
db.raw_short_videos_ingestion_data.aggregate([
  { $match: { sourceVideoId: { $in: [<list_of_scraped_ids>] } } },
  { $group: { _id: null, existingIds: { $addToSet: "$sourceVideoId" } } }
])
```

A unique index on `sourceVideoId` is recommended (if not already present) to:
1. Accelerate deduplication queries during Stage 1.
2. Enforce uniqueness at the database level as a safety net for `insert_many(ordered=False)`.

### Recommended Indexes

| Index | Fields | Type | Rationale |
|---|---|---|---|
| Primary dedup | `{ sourceVideoId: 1 }` | Unique | Prevent duplicate inserts; accelerate dedup queries |
| Temporal query | `{ sourceEpoch: -1 }` | Regular | Support time-range queries by downstream consumers |
| Source filter | `{ src: 1, sourceEpoch: -1 }` | Compound | Filter by source and sort by time |

## Write Operations

### Insert Pattern

```python
collection.insert_many(documents, ordered=False)
```

| Attribute | Value |
|---|---|
| **Method** | `insert_many` |
| **ordered** | `False` (continues inserting on duplicate key errors) |
| **Batch size** | All qualified records from a single Pub/Sub message |
| **Conflict handling** | Duplicate `sourceVideoId` entries cause individual insert failures that are silently ignored |

## Read Operations

### Deduplication Query (Stage 1)

```python
pipeline = [
    {"$match": {"sourceVideoId": {"$in": scraped_video_ids}}},
    {"$group": {"_id": None, "ids": {"$addToSet": "$sourceVideoId"}}}
]
existing = collection.aggregate(pipeline)
```

This aggregation returns the set of `sourceVideoId` values that already exist in the collection, used to compute the set difference for net-new IDs.

## Data Lifecycle

| Aspect | Detail |
|---|---|
| **Insertion Frequency** | Per scheduler invocation (cron-driven) |
| **Record Immutability** | Records are insert-only; no updates after insertion |
| **Retention Policy** | No TTL configured; records persist indefinitely |
| **Archival** | Not configured at the pipeline level |
