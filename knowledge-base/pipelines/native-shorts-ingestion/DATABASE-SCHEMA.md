# Native Shorts Ingestion - Database Schema

## Database Overview

| Attribute | Value |
|---|---|
| **Database Engine** | MongoDB |
| **Database Name** | `ingestion-data` |
| **Primary Collection** | `raw_videos_rss` |
| **Shared With** | Native Videos Ingestion pipeline |
| **Differentiator** | `contentType="shorts"` vs `contentType="videos"` |
| **Connection Secret** | `mongosh_de_uri` (GCP Secret Manager) |

## Collection: `raw_videos_rss`

### Purpose

Stores metadata and processing status for native short-form video content from all three sources (JioNewsDENativeVideos, yt-manual-upload, MRSS feeds). This collection is shared with the Native Videos pipeline; records are differentiated by the `contentType` field.

### Document Schema

| Field | BSON Type | Required | Shorts Value | Description |
|---|---|---|---|---|
| `_id` | ObjectId | Yes | Auto-generated | MongoDB document identifier |
| `contentType` | String | Yes | `"shorts"` | Content type discriminator (`"shorts"` or `"videos"`) |
| `sourceVideoOrientation` | String | Yes | `"portrait"` | Orientation (`"portrait"` for shorts, `"landscape"` for videos) |
| `title` | String | Yes | - | Video title from feed/upload |
| `sourceVideoUrl` | String | Yes | - | Original source video URL |
| `videoContentUrl` | String | Yes (after Stage 3) | - | CDN serving URL: `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| `thumbnailUrl` | String | Yes | - | Thumbnail image URL (from feed or default image) |
| `category` | String | Yes | - | Content category |
| `language` | String | Yes | - | Content language code |
| `publisher` | String | Yes | - | Publisher identifier |
| `processingStatus` | String | Yes | - | Processing state (e.g., `"completed"`) |
| `sourceDescription` | String | No | - | Video description (if available) |
| `publishedDate` | String/Date | No | - | Original publication date |
| `createdAt` | Date | No | - | Record creation timestamp |

### Source-Specific Fields

#### Source 1: JioNewsDENativeVideos Records

| Field | Value | Description |
|---|---|---|
| `contentType` | `"shorts"` | Set by editorial tagging |
| `sourceVideoOrientation` | `"portrait"` | Portrait orientation for shorts |
| `source` | Varies | Editorial source identifier |

#### Source 2: yt-manual-upload Records

| Field | Value | Description |
|---|---|---|
| `contentType` | `"shorts"` | Set during processing |
| `thumbnailUrl` | Derived from `oar2.jpg` | Specific thumbnail source |
| `sourceVideoOrientation` | `"portrait"` | Portrait orientation |

#### Source 3: MRSS Feed Records

| Field | Value | Description |
|---|---|---|
| `contentType` | `"shorts"` | Hardcoded in mrssshorts-processvideos |
| `sourceVideoOrientation` | `"portrait"` | Hardcoded in mrssshorts-processvideos |
| `processingStatus` | `"completed"` | Set by mrssshorts-downloadvideos after download |
| `videoContentUrl` | `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` | Set after GCS upload |

### Example Document (MRSS Source)

```json
{
  "_id": "ObjectId('65b2c3d4e5f6a7b8c9d0e1f2')",
  "contentType": "shorts",
  "sourceVideoOrientation": "portrait",
  "title": "Top Headlines in 30 Seconds",
  "sourceVideoUrl": "https://publisher-cdn.example.com/videos/headline-short-123.mp4",
  "videoContentUrl": "https://vcdn.jionews.com/raw_videos/65b2c3d4e5f6a7b8.mp4",
  "thumbnailUrl": "https://publisher-cdn.example.com/thumbs/headline-short-123.jpg",
  "category": "news",
  "language": "hindi",
  "publisher": "7777",
  "processingStatus": "completed",
  "sourceDescription": "Quick news update covering today's top stories",
  "publishedDate": "2025-01-15T08:00:00Z",
  "createdAt": "2025-01-15T08:15:00Z"
}
```

## Redis Cache Schema

### Cache: `de_mrss_shorts_cache`

| Attribute | Value |
|---|---|
| **Type** | Redis key-value store |
| **Key Format** | `{title}_{link}_{category}_{language}` |
| **Value** | Presence marker (e.g., `"1"`) |
| **TTL** | 48 hours (172800 seconds) |
| **Purpose** | Deduplication for MRSS feed records |

#### Key Construction Example

```
title: "Breaking News Short"
link: "https://publisher.com/video/123"
category: "news"
language: "hindi"

Key: "Breaking News Short_https://publisher.com/video/123_news_hindi"
```

#### Comparison with Videos Cache

| Attribute | Shorts Cache | Videos Cache |
|---|---|---|
| **Cache name** | `de_mrss_shorts_cache` | `de_mrss_videos_cache` |
| **Key format** | Same structure | Same structure |
| **TTL** | 48 hours | 48 hours |

## Write Operations

### Stage 2: mrssshorts-processvideos

```python
collection.insert_many(records)
```

| Attribute | Value |
|---|---|
| **Method** | `insert_many` |
| **Collection** | `raw_videos_rss` |
| **Batch** | Records processed in the current invocation |

### Stage 3: mrssshorts-downloadvideos

```python
collection.update_one(
    {"_id": record_id},
    {"$set": {
        "processingStatus": "completed",
        "videoContentUrl": f"https://vcdn.jionews.com/raw_videos/{video_id}.mp4"
    }}
)
```

| Attribute | Value |
|---|---|
| **Method** | `update_one` |
| **Filter** | Record `_id` |
| **Update** | Sets `processingStatus` and `videoContentUrl` |

## Recommended Indexes

| Index | Fields | Type | Rationale |
|---|---|---|---|
| Content type filter | `{ contentType: 1 }` | Regular | Separate shorts from videos in queries |
| Content + time | `{ contentType: 1, createdAt: -1 }` | Compound | Time-ordered queries filtered by content type |
| Processing status | `{ contentType: 1, processingStatus: 1 }` | Compound | Find incomplete records by type |
| Publisher filter | `{ publisher: 1, contentType: 1 }` | Compound | Per-publisher queries |
| Language filter | `{ language: 1, contentType: 1 }` | Compound | Language-specific content queries |

## Data Lifecycle

| Aspect | Detail |
|---|---|
| **Insert Stage** | Stage 2 (mrssshorts-processvideos) or shared Cloud Functions |
| **Update Stage** | Stage 3 (mrssshorts-downloadvideos) sets processingStatus and videoContentUrl |
| **Record Mutability** | Records are inserted in Stage 2, then updated in Stage 3 |
| **Retention Policy** | No TTL configured; records persist indefinitely |
| **Shared Collection** | Must query with `contentType="shorts"` to isolate shorts records |

## GCS Storage Schema

### Video Files

| Attribute | Value |
|---|---|
| **Bucket** | `hls_video_transcoder_storage_output_files` |
| **Path Pattern** | `raw_videos/{video_id}.mp4` |
| **Format** | Raw MP4 (no transcoding) |
| **CDN URL** | `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| **Access** | Public via CDN |
