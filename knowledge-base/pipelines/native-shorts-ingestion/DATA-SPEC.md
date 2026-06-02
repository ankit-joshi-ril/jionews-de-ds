# Native Shorts Ingestion - Data Specification

## Data Flow Summary

```
Source 1 (JioNewsDENativeVideos): Editorial uploads -> Pub/Sub -> MongoDB
Source 2 (yt-manual-upload): YouTube repackaged -> Pub/Sub -> MongoDB
Source 3 (MRSS): GCS config -> Feed fetch -> Process -> Download -> GCS + MongoDB
```

All three sources converge on MongoDB `ingestion-data.raw_videos_rss` with `contentType="shorts"`.

## Input Data

### MRSS Feed Configuration CSV

| Attribute | Value |
|---|---|
| **Location** | `gs://de-raw-ingestion/shorts/mrss_shorts_feeds.csv` |
| **Format** | CSV with headers |
| **Used By** | `mrssshorts-fetchfeedsdata` |

#### CSV Schema

| Column | Type | Description |
|---|---|---|
| Feed ID | integer | Unique feed identifier (e.g., 49, 50, 7777, 7778, 7782) |
| Feed URL | string | MRSS endpoint URL |
| Publisher metadata | varies | Publisher name, category, language, etc. |

### MRSS Feed Response Formats

#### Standard Feed Response (Most Feed IDs)

```json
{
  "items": [
    {
      "title": "Video title",
      "link": "Source URL",
      "category": "News category",
      "language": "Language code",
      "video_url": "Direct video URL",
      "thumbnail": "Thumbnail URL",
      "videotype": "shorts",
      "published_date": "Publication date"
    }
  ]
}
```

#### Feed IDs 49 and 50 (Alternative Format)

```json
{
  "data": [
    {
      "title": "Video title",
      "link": "Source URL",
      "category": "News category",
      "language": "Language code",
      "video_url": "Direct video URL",
      "thumbnail": "Thumbnail URL"
    }
  ]
}
```

**Key difference:** The data array is accessed via `response['data']` instead of `response['items']`.

### Publisher 7782 (IANS) - Video URL

| Attribute | Value |
|---|---|
| **Video URL field** | `record.get('video')` (non-standard) |
| **Other publishers** | Standard `video_url` field |

### Source 1: JioNewsDENativeVideos Input

| Attribute | Value |
|---|---|
| **Source** | Editorial Pub/Sub message |
| **Content tagging** | `contentType="shorts"` set by editorial metadata |
| **Orientation** | `sourceVideoOrientation="portrait"` |

### Source 2: yt-manual-upload Input

| Attribute | Value |
|---|---|
| **Source** | Manual YouTube upload Pub/Sub message |
| **Thumbnail** | Derived from `oar2.jpg` |
| **Content tagging** | `contentType="shorts"` |
| **Orientation** | `sourceVideoOrientation="portrait"` |

## Intermediate Data

### Pub/Sub: `MRSSShortsIngestion_RawFeedsData`

| Attribute | Value |
|---|---|
| **Direction** | mrssshorts-fetchfeedsdata -> mrssshorts-processvideos |
| **Content** | Raw feed records from all publisher endpoints |
| **Format** | JSON-serialized feed record |

### Pub/Sub: `MRSSShortsIngestion_ProcessedData`

| Attribute | Value |
|---|---|
| **Direction** | mrssshorts-processvideos -> mrssshorts-downloadvideos |
| **Content** | Validated and enriched individual short video records |
| **Format** | JSON-serialized processed record |

### Pub/Sub: `NewRawHeadlinesIngestion_image_cdn`

| Attribute | Value |
|---|---|
| **Direction** | mrssshorts-processvideos -> Image CDN pipeline |
| **Content** | Thumbnail image URLs for CDN processing |
| **Purpose** | Offloads image downloading and CDN distribution |

## Redis Deduplication

### Cache: `de_mrss_shorts_cache`

| Attribute | Value |
|---|---|
| **Cache Name** | `de_mrss_shorts_cache` |
| **Key Construction** | Concatenation of `title`, `link`, `category`, `language` |
| **TTL** | 48 hours |
| **Purpose** | Prevent re-processing of recently seen feed items |

#### Dedup Logic

```
cache_key = f"{title}_{link}_{category}_{language}"
if redis.exists(cache_key):
    skip record (already processed)
else:
    redis.setex(cache_key, ttl=48h, value=1)
    process record
```

## Validation Rules

### Publisher 7777/7778 - Videotype Filter

| Accepted Values | Format |
|---|---|
| `"shorts"` | Lowercase |
| `"short"` | Lowercase |
| `"short video"` | Lowercase with space |
| `"shortvideo"` | Lowercase no space |

Records from publishers 7777/7778 that do not match one of these videotype values are excluded.

### Default Image Selection

| Attribute | Shorts | Videos (comparison) |
|---|---|---|
| **Range** | 1-5 | 1-10 |
| **Selection** | Random within range | Random within range |
| **Usage** | When no thumbnail URL is available in the feed record |

## Output Data

### MongoDB Document: `raw_videos_rss`

| Attribute | Value |
|---|---|
| **Database** | `ingestion-data` |
| **Collection** | `raw_videos_rss` |
| **Insert Method** | `insert_many` |
| **Shared With** | Native Videos pipeline |
| **Differentiator** | `contentType="shorts"` |

#### Key Output Fields (MRSS Source)

| Field | Type | Source | Description |
|---|---|---|---|
| `contentType` | string | Hardcoded | `"shorts"` |
| `sourceVideoOrientation` | string | Hardcoded | `"portrait"` |
| `title` | string | Feed record | Video title |
| `sourceVideoUrl` | string | Feed record | Original video URL from feed |
| `videoContentUrl` | string | Set after download | `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| `thumbnailUrl` | string | Feed record or default | Thumbnail image URL |
| `processingStatus` | string | Updated by Stage 3 | `"completed"` after download |
| `category` | string | Feed record | Content category |
| `language` | string | Feed record | Content language |
| `publisher` | string | Feed configuration | Publisher identifier |

### GCS Video Storage

| Attribute | Value |
|---|---|
| **Bucket** | `hls_video_transcoder_storage_output_files` |
| **Path** | `raw_videos/{video_id}.mp4` |
| **CDN URL** | `https://vcdn.jionews.com/raw_videos/{video_id}.mp4` |
| **Format** | Raw MP4 (no transcoding) |

## Data Volume Estimates

| Metric | Typical Value |
|---|---|
| MRSS feeds configured | Varies (listed in CSV) |
| Records per feed fetch | Varies by publisher |
| Records passing dedup (Redis) | Subset of fetched records |
| Records passing videotype filter | Subset for publishers 7777/7778 |
| Videos downloaded per cycle | Count of new, validated records |

## Comparison: Shorts vs Videos Data Paths

| Data Aspect | Shorts Pipeline | Videos Pipeline |
|---|---|---|
| Redis cache name | `de_mrss_shorts_cache` | `de_mrss_videos_cache` |
| Pub/Sub topic prefix | `MRSSShortsIngestion_` | `MRSSVideosIngestion_` |
| contentType value | `"shorts"` | `"videos"` |
| Orientation value | `"portrait"` | `"landscape"` |
| Default image range | 1-5 | 1-10 |
| Post-download processing | None (raw MP4) | HLS transcoding |
| Video serving URL | `vcdn.jionews.com/raw_videos/{id}.mp4` | HLS manifest URL |
