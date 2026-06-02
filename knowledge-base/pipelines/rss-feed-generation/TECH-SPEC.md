# RSS Feed Generation -- Technical Specification

## Runtime Environment

| Attribute | Value |
|---|---|
| Platform | Google Cloud Functions |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Language | Python |
| Trigger types | Cloud Scheduler, Pub/Sub background |

## Function Specifications

### RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler (scheduled) |
| Input | MongoDB aggregation on `ingestion-data.raw_videos_rss` |
| Output | Pub/Sub: `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` |

**Processing Logic:**

1. Connect to MongoDB.
2. Execute aggregation pipeline:
   ```python
   pipeline = [
       {"$match": {
           "transcoderProcessingStatus": "completed",
           "contentType": "videos"
       }},
       {"$setWindowFields": {
           "partitionBy": "$language",
           "sortBy": {"_id": -1},  # or recency field
           "output": {
               "rowNumber": {"$documentNumber": {}}
           }
       }},
       {"$match": {"rowNumber": {"$lte": 100}}}
   ]
   results = collection.aggregate(pipeline)
   ```
3. Apply category mapping to each record:
   ```python
   CATEGORY_MAP = {
       "news": "news",
       "cricket": "sports",
       "business": "business news",
       "technology": "science and technology",
       "automotive": "automobile",
       "entertainment": "entertainment",
       "health": "health",
       "spiritual": "astrology",
       "astrology": "astrology",
       "fashion": "lifestyle",
       "travel": "lifestyle",
       "food": "lifestyle",
       "diy": "lifestyle",
       "sports": "sports",
       "career": "education",
       "football": "sports",
       "agro": "news",
   }

   def map_category(category: str) -> str:
       return CATEGORY_MAP.get(category.lower(), "news")
   ```
4. Group results by language.
5. Publish each language group to Pub/Sub topic `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit`.

### RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub background (from aggregated data topic) |
| Input | Language-grouped video records |
| Output | GCS: `rss/videos_hls/{language}/rss.xml` |

**Processing Logic:**

1. Decode Pub/Sub message containing language and records array.
2. Initialize RSS 2.0 XML document with Media RSS namespace:
   ```python
   from xml.etree.ElementTree import Element, SubElement, tostring

   rss = Element("rss", version="2.0")
   rss.set("xmlns:media", "http://search.yahoo.com/mrss/")

   channel = SubElement(rss, "channel")
   SubElement(channel, "title").text = "JioNews Videos RSS Feed"
   SubElement(channel, "link").text = "https://jionews.com"
   ```
3. For each video record, create an `<item>` element:
   ```python
   item = SubElement(channel, "item")
   SubElement(item, "title").text = record["title"]
   SubElement(item, "description").text = record.get("description", "")
   SubElement(item, "pubDate").text = format_rfc822(record["published_date"])
   SubElement(item, "category").text = mapped_category
   SubElement(item, "guid").text = record["source_id"]
   SubElement(item, "hlsAvcUrl").text = record["hls_avc_url"]
   SubElement(item, "hlsHevcUrl").text = record["hls_hevc_url"]
   ```
4. Normalize and add thumbnail elements:
   ```python
   THUMBNAIL_KEY_MAP = {
       "low": "default",
       "sd": "medium",
       "hd": "high",
       "fhd": "standard",
       "original": "maxres",
   }

   for src_key, norm_key in THUMBNAIL_KEY_MAP.items():
       if src_key in record.get("thumbnails", {}):
           thumb = SubElement(item, "media:thumbnail")
           thumb.set("url", record["thumbnails"][src_key])
           thumb.set("key", norm_key)
   ```
5. Serialize XML to string.
6. Upload to GCS: `hls_video_transcoder_storage_output_files/rss/videos_hls/{language}/rss.xml`.

### RawShortsContentPrepareRss_AggregateDataLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler (scheduled) |
| Input | MongoDB aggregation on `ingestion-data.raw_videos_rss` |
| Output | Pub/Sub: `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` |

**Processing Logic:**

Identical to the videos aggregation function except:
- Filter uses `processingStatus=completed` (not `transcoderProcessingStatus`).
- Filter uses `contentType=shorts` (not `videos`).

```python
pipeline = [
    {"$match": {
        "processingStatus": "completed",
        "contentType": "shorts"
    }},
    {"$setWindowFields": {
        "partitionBy": "$language",
        "sortBy": {"_id": -1},
        "output": {
            "rowNumber": {"$documentNumber": {}}
        }
    }},
    {"$match": {"rowNumber": {"$lte": 100}}}
]
```

### RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub background |
| Input | Language-grouped shorts records |
| Output | GCS: `rss/shorts/{language}/rss.xml` |

**Processing Logic:**

Similar to the videos RSS generation function with two key differences:

1. **No HLS elements**: The `<hlsAvcUrl>` and `<hlsHevcUrl>` elements are NOT included in item elements.
2. **pubDate uses sourceDate directly**: Instead of computing pubDate from other fields, the `sourceDate` field value is used directly.

```python
item = SubElement(channel, "item")
SubElement(item, "title").text = record["title"]
SubElement(item, "description").text = record.get("description", "")
SubElement(item, "pubDate").text = format_rfc822(record["sourceDate"])  # Direct use
SubElement(item, "category").text = mapped_category
SubElement(item, "guid").text = record["source_id"]
# NO hlsAvcUrl or hlsHevcUrl
```

Upload path: `rss/shorts/{language}/rss.xml`.

## Pub/Sub Topic Configuration

| Topic | Publisher | Subscriber | Mode |
|---|---|---|---|
| `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` | Videos aggregation | Videos RSS generation | Per-language |
| `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` | Shorts aggregation | Shorts RSS generation | Per-language |

## Key Libraries and Dependencies

| Library | Purpose | Used by |
|---|---|---|
| `pymongo` | MongoDB client (aggregation pipelines) | Aggregation functions |
| `google-cloud-storage` | GCS upload for RSS XML files | RSS generation functions |
| `google-cloud-pubsub` | Pub/Sub messaging | All functions |
| `xml.etree.ElementTree` | XML document construction | RSS generation functions |
| `email.utils` | RFC 822 date formatting for RSS | RSS generation functions |

## MongoDB Aggregation Details

### $setWindowFields Usage

The `$setWindowFields` stage with `$documentNumber` is used to implement a "top N per group" pattern:

- **Partition**: by `language` field (each language is independently ranked).
- **Sort**: by recency (descending order on a timestamp or `_id` field).
- **Output**: `$documentNumber` assigns a sequential rank within each partition.
- **Post-filter**: `rowNumber <= 100` selects the top 100 per language.

This approach is more efficient than `$group` + `$slice` for large collections because it avoids accumulating all records in memory before slicing.

## RSS 2.0 Compliance Notes

| Requirement | Implementation |
|---|---|
| XML declaration | `<?xml version="1.0" encoding="UTF-8"?>` |
| RSS version attribute | `version="2.0"` |
| Channel required elements | `<title>`, `<link>`, `<description>` |
| Item guid | Uses `source_id` as unique identifier |
| pubDate format | RFC 822 (e.g., `Mon, 10 Mar 2026 12:00:00 +0530`) |
| Media RSS namespace | `xmlns:media="http://search.yahoo.com/mrss/"` |

## Error Handling

| Component | Error Scenario | Handling |
|---|---|---|
| Aggregation | MongoDB connection failure | Function fails; Cloud Scheduler retries on next schedule |
| Aggregation | Empty result set for a language | No message published for that language; no RSS file generated |
| Aggregation | Pub/Sub publish failure | Exception raised; Cloud Function error reporting |
| RSS Generation | Invalid XML characters in data | May produce malformed XML |
| RSS Generation | Missing required fields (title, source_id) | May produce incomplete RSS items |
| RSS Generation | GCS upload failure | Function fails; Pub/Sub retries message |
| RSS Generation | Missing thumbnail keys | Thumbnail elements omitted for missing keys |

## Consumer Integration

| Consumer | Access Method | Frequency |
|---|---|---|
| JioHotstar | GCS bucket read | On-demand or scheduled polling |

JioHotstar reads the generated RSS XML files from the GCS bucket paths. The files are overwritten on each pipeline execution, so JioHotstar always reads the latest top-100 feed for each language.

## Differences Between Videos and Shorts Sub-Pipelines

| Aspect | Videos RSS | Shorts RSS |
|---|---|---|
| Filter field | `transcoderProcessingStatus=completed` | `processingStatus=completed` |
| Content type | `videos` | `shorts` |
| HLS elements | `hlsAvcUrl` + `hlsHevcUrl` included | NOT included |
| pubDate source | Computed from publication date | `sourceDate` field directly |
| Output path | `rss/videos_hls/{language}/rss.xml` | `rss/shorts/{language}/rss.xml` |
| Pub/Sub topic | `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` | `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` |
