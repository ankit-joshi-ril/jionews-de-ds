# RSS Feed Generation -- Data Specification

## Data Sources

### MongoDB Aggregation (Videos)

**Collection:** `ingestion-data.raw_videos_rss`

**Filter criteria:**
```json
{
  "transcoderProcessingStatus": "completed",
  "contentType": "videos"
}
```

**Aggregation pipeline stages:**
1. `$match`: Filter for completed transcoded videos.
2. `$setWindowFields`: Partition by language, apply `$documentNumber` for ranking.
3. `$match`: Select documents where `$documentNumber` <= 100 (top 100 per language).
4. `$group`: Group by language for per-language Pub/Sub messages.

### MongoDB Aggregation (Shorts)

**Collection:** `ingestion-data.raw_videos_rss`

**Filter criteria:**
```json
{
  "processingStatus": "completed",
  "contentType": "shorts"
}
```

Same aggregation approach as videos but with different filter criteria (uses `processingStatus` instead of `transcoderProcessingStatus`).

## Category Mapping

The mapping transforms internal JioNews categories to consumer-facing RSS categories. Unmapped categories default to `"news"`.

| Internal Category | RSS Category | Notes |
|---|---|---|
| `news` | `news` | Direct mapping |
| `cricket` | `sports` | Merged into sports |
| `business` | `business news` | Expanded name |
| `technology` | `science and technology` | Expanded name |
| `automotive` | `automobile` | Renamed |
| `entertainment` | `entertainment` | Direct mapping |
| `health` | `health` | Direct mapping |
| `spiritual` | `astrology` | Merged with astrology |
| `astrology` | `astrology` | Direct mapping |
| `fashion` | `lifestyle` | Merged into lifestyle |
| `travel` | `lifestyle` | Merged into lifestyle |
| `food` | `lifestyle` | Merged into lifestyle |
| `diy` | `lifestyle` | Merged into lifestyle |
| `sports` | `sports` | Direct mapping |
| `career` | `education` | Renamed |
| `football` | `sports` | Merged into sports |
| `agro` | `news` | Merged into news |
| (all others) | `news` | Default fallback |

### Category consolidation summary:

| RSS Category | Source Categories |
|---|---|
| `news` | news, agro, (default) |
| `sports` | cricket, sports, football |
| `lifestyle` | fashion, travel, food, diy |
| `astrology` | spiritual, astrology |
| `entertainment` | entertainment |
| `health` | health |
| `business news` | business |
| `science and technology` | technology |
| `automobile` | automotive |
| `education` | career |

## Thumbnail Key Normalization

| Source Key | Normalized Key | Typical Resolution |
|---|---|---|
| `low` | `default` | Smallest available |
| `sd` | `medium` | Standard definition |
| `hd` | `high` | High definition |
| `fhd` | `standard` | Full HD |
| `original` | `maxres` | Maximum resolution |

## Language Coverage

RSS feeds are generated for language IDs 1 through 13:

| Language ID | Language Name | RSS File Generated |
|---|---|---|
| 1 | English | Yes |
| 2 | Hindi | Yes |
| 3 | Marathi | Yes |
| 4 | Gujarati | Yes |
| 5 | (not assigned) | No |
| 6 | Malayalam | Yes |
| 7 | Tamil | Yes |
| 8 | Urdu | Yes |
| 9 | Kannada | Yes |
| 10 | Punjabi | Yes |
| 11 | Telugu | Yes |
| 12 | (not assigned) | No |
| 13 | Bangla | Yes |

Note: IDs 5 and 12 are not assigned in the language mapping. If no data exists for a language ID, an empty or minimal RSS feed may be generated.

## RSS XML Schema

### Channel-Level Elements

| Element | Value | Present in |
|---|---|---|
| `<title>` | `JioNews Videos RSS Feed` | Videos + Shorts |
| `<link>` | `https://jionews.com` | Videos + Shorts |
| `<description>` | Feed description | Videos + Shorts |
| Namespace declaration | `xmlns:media` (Media RSS) | Videos + Shorts |

### Item-Level Elements (Videos)

| Element | Type | Source | Description |
|---|---|---|---|
| `<title>` | string | `title` field | Video title |
| `<link>` | URL | Constructed | Link to video |
| `<description>` | string | `description` field | Video description |
| `<pubDate>` | RFC 822 date | Computed | Publication date |
| `<category>` | string | Category mapping | Mapped category name |
| `<guid>` | string | `source_id` | Unique identifier |
| `<hlsAvcUrl>` | URL | `hls_avc_url` | HLS AVC stream URL |
| `<hlsHevcUrl>` | URL | `hls_hevc_url` | HLS HEVC stream URL |
| Thumbnail elements | URL | Thumbnails (normalized keys) | Multiple resolution thumbnails |

### Item-Level Elements (Shorts)

| Element | Type | Source | Description |
|---|---|---|---|
| `<title>` | string | `title` field | Short title |
| `<link>` | URL | Constructed | Link to short |
| `<description>` | string | `description` field | Short description |
| `<pubDate>` | RFC 822 date | `sourceDate` (directly) | Uses sourceDate, not computed |
| `<category>` | string | Category mapping | Mapped category name |
| `<guid>` | string | `source_id` | Unique identifier |
| Thumbnail elements | URL | Thumbnails (normalized keys) | Multiple resolution thumbnails |

Key difference: Shorts RSS items do NOT include `<hlsAvcUrl>` or `<hlsHevcUrl>` elements.

## Pub/Sub Message Schemas

### Topic: RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit

| Field | Type | Description |
|---|---|---|
| `language` | string | Language name |
| `language_id` | integer | Language numeric ID |
| `records` | array[object] | Top 100 video records for this language |

### Topic: RawShortsContentPrepareRss_AggregatedDataLanguageSplit

| Field | Type | Description |
|---|---|---|
| `language` | string | Language name |
| `language_id` | integer | Language numeric ID |
| `records` | array[object] | Top 100 shorts records for this language |

## Output Files

### Videos RSS

| Attribute | Value |
|---|---|
| GCS bucket | `hls_video_transcoder_storage_output_files` |
| Path pattern | `rss/videos_hls/{language}/rss.xml` |
| Format | RSS 2.0 XML with Media RSS namespace |
| Content | Top 100 videos per language with HLS URLs |

### Shorts RSS

| Attribute | Value |
|---|---|
| GCS bucket | `hls_video_transcoder_storage_output_files` |
| Path pattern | `rss/shorts/{language}/rss.xml` |
| Format | RSS 2.0 XML |
| Content | Top 100 shorts per language without HLS URLs |

## Data Quality Rules

| Rule | Stage | Behavior |
|---|---|---|
| Videos must have `transcoderProcessingStatus=completed` | Aggregation | Not included in feed |
| Shorts must have `processingStatus=completed` | Aggregation | Not included in feed |
| Category must map to a known RSS category | XML generation | Defaults to `"news"` |
| Thumbnail keys must match normalization table | XML generation | Unknown keys may pass through unmapped |
| Language ID must be in range 1-13 | Aggregation | Languages outside range not processed |
| Records limited to top 100 per language | Aggregation | Excess records excluded |
