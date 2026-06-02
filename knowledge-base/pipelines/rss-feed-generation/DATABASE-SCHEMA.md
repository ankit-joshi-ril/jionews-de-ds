# RSS Feed Generation -- Database Schema

## MongoDB

### Collection: `ingestion-data.raw_videos_rss`

This pipeline reads from the same MongoDB collection used by the Native Videos Ingestion and Video Transcoder Workflow pipelines. It does not write to MongoDB; it is a read-only consumer.

### Fields Used by RSS Generation

| Field | Type | Used by Videos RSS | Used by Shorts RSS | Description |
|---|---|---|---|---|
| `_id` | ObjectId | Yes | Yes | Document ID |
| `source_id` | string | Yes | Yes | Unique video/short identifier |
| `title` | string | Yes | Yes | Content title |
| `description` | string | Yes | Yes | Content description |
| `category` | string | Yes | Yes | Internal category name (input to mapping) |
| `language` | string | Yes | Yes | Language name (used for partitioning) |
| `language_id` | integer | Yes | Yes | Language numeric ID |
| `contentType` | string | Yes | Yes | `"videos"` or `"shorts"` |
| `processingStatus` | string | No | Yes (filter) | Processing status |
| `transcoderProcessingStatus` | string | Yes (filter) | No | Transcoder processing status |
| `hls_avc_url` | string | Yes | No | HLS AVC stream URL |
| `hls_hevc_url` | string | Yes | No | HLS HEVC stream URL |
| `sourceDate` | datetime | No | Yes (pubDate) | Original source date |
| `thumbnails` | object | Yes | Yes | Thumbnail URL map |
| `publisher_name` | string | Yes | Yes | Publisher display name |
| `published_date` | datetime | Yes | No | Publication date |

### Query Patterns

#### Videos Aggregation Pipeline

```javascript
[
  {
    $match: {
      transcoderProcessingStatus: "completed",
      contentType: "videos"
    }
  },
  {
    $setWindowFields: {
      partitionBy: "$language",
      sortBy: { /* recency field */ : -1 },
      output: {
        rowNumber: { $documentNumber: {} }
      }
    }
  },
  {
    $match: {
      rowNumber: { $lte: 100 }
    }
  }
]
```

#### Shorts Aggregation Pipeline

```javascript
[
  {
    $match: {
      processingStatus: "completed",
      contentType: "shorts"
    }
  },
  {
    $setWindowFields: {
      partitionBy: "$language",
      sortBy: { /* recency field */ : -1 },
      output: {
        rowNumber: { $documentNumber: {} }
      }
    }
  },
  {
    $match: {
      rowNumber: { $lte: 100 }
    }
  }
]
```

### Indexes (Recommended for RSS Generation)

| Index | Fields | Type | Purpose |
|---|---|---|---|
| Videos aggregation | `contentType`, `transcoderProcessingStatus`, `language` | Compound | Efficient videos aggregation |
| Shorts aggregation | `contentType`, `processingStatus`, `language` | Compound | Efficient shorts aggregation |
| Sort support | Recency field (descending) | Single | Support `$setWindowFields` sort |

## GCS Output Schema

### Videos RSS Files

| Attribute | Value |
|---|---|
| Bucket | `hls_video_transcoder_storage_output_files` |
| Path pattern | `rss/videos_hls/{language}/rss.xml` |
| Format | RSS 2.0 XML with Media RSS namespace |
| Encoding | UTF-8 |
| Content-Type | `application/xml` or `application/rss+xml` |

### Shorts RSS Files

| Attribute | Value |
|---|---|
| Bucket | `hls_video_transcoder_storage_output_files` |
| Path pattern | `rss/shorts/{language}/rss.xml` |
| Format | RSS 2.0 XML |
| Encoding | UTF-8 |
| Content-Type | `application/xml` or `application/rss+xml` |

### GCS File Inventory (per execution)

Videos RSS generates up to 13 files (one per language ID 1-13 where data exists):

| Language | GCS Path |
|---|---|
| English | `rss/videos_hls/English/rss.xml` |
| Hindi | `rss/videos_hls/Hindi/rss.xml` |
| Marathi | `rss/videos_hls/Marathi/rss.xml` |
| Gujarati | `rss/videos_hls/Gujarati/rss.xml` |
| Malayalam | `rss/videos_hls/Malayalam/rss.xml` |
| Tamil | `rss/videos_hls/Tamil/rss.xml` |
| Urdu | `rss/videos_hls/Urdu/rss.xml` |
| Kannada | `rss/videos_hls/Kannada/rss.xml` |
| Punjabi | `rss/videos_hls/Punjabi/rss.xml` |
| Telugu | `rss/videos_hls/Telugu/rss.xml` |
| Bangla | `rss/videos_hls/Bangla/rss.xml` |

Shorts RSS generates the same set under `rss/shorts/{language}/rss.xml`.

## RSS XML Structure

### Videos RSS Example Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>JioNews Videos RSS Feed</title>
    <link>https://jionews.com</link>
    <description>...</description>
    <item>
      <title>Video Title</title>
      <link>...</link>
      <description>...</description>
      <pubDate>Mon, 10 Mar 2026 12:00:00 +0530</pubDate>
      <category>sports</category>
      <guid>source_id_value</guid>
      <hlsAvcUrl>https://videos.jionews.com/...</hlsAvcUrl>
      <hlsHevcUrl>https://videos.jionews.com/...</hlsHevcUrl>
      <!-- Thumbnails with normalized keys -->
      <media:thumbnail url="..." key="default"/>
      <media:thumbnail url="..." key="medium"/>
      <media:thumbnail url="..." key="high"/>
      <media:thumbnail url="..." key="standard"/>
      <media:thumbnail url="..." key="maxres"/>
    </item>
    <!-- Up to 100 items per language -->
  </channel>
</rss>
```

### Shorts RSS Example Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>JioNews Videos RSS Feed</title>
    <link>https://jionews.com</link>
    <description>...</description>
    <item>
      <title>Short Title</title>
      <link>...</link>
      <description>...</description>
      <pubDate>Mon, 10 Mar 2026 12:00:00 +0530</pubDate>
      <category>lifestyle</category>
      <guid>source_id_value</guid>
      <!-- NO hlsAvcUrl or hlsHevcUrl elements -->
      <!-- Thumbnails with normalized keys -->
      <media:thumbnail url="..." key="default"/>
      <media:thumbnail url="..." key="medium"/>
      <media:thumbnail url="..." key="high"/>
      <media:thumbnail url="..." key="standard"/>
      <media:thumbnail url="..." key="maxres"/>
    </item>
    <!-- Up to 100 items per language -->
  </channel>
</rss>
```

## Thumbnail Key Normalization Reference

| Source Key (MongoDB) | Normalized Key (RSS XML) |
|---|---|
| `low` | `default` |
| `sd` | `medium` |
| `hd` | `high` |
| `fhd` | `standard` |
| `original` | `maxres` |

## Category Mapping Reference

| Input (MongoDB `category`) | Output (RSS `<category>`) |
|---|---|
| `news` | `news` |
| `cricket` | `sports` |
| `business` | `business news` |
| `technology` | `science and technology` |
| `automotive` | `automobile` |
| `entertainment` | `entertainment` |
| `health` | `health` |
| `spiritual` | `astrology` |
| `astrology` | `astrology` |
| `fashion` | `lifestyle` |
| `travel` | `lifestyle` |
| `food` | `lifestyle` |
| `diy` | `lifestyle` |
| `sports` | `sports` |
| `career` | `education` |
| `football` | `sports` |
| `agro` | `news` |
| (unmapped) | `news` (default) |
