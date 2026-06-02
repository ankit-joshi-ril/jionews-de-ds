# RSS Feed Generation -- AS-IS Process Document

## Current State Description

The RSS Feed Generation pipeline produces language-specific RSS 2.0 XML feeds for two content types: videos (with HLS streaming URLs) and shorts (without HLS). The feeds are consumed by JioHotstar and stored in GCS. The pipeline operates on a scheduled basis with two parallel sub-pipelines.

## Videos RSS Sub-Pipeline -- Current Flow

### Step 1: Aggregation (RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit)

1. Cloud Scheduler triggers the aggregation function.
2. The function runs a MongoDB aggregation pipeline on `ingestion-data.raw_videos_rss`:
   - Filters for `transcoderProcessingStatus=completed` and `contentType=videos`.
   - Uses `$setWindowFields` with `$documentNumber` partitioned by language to rank records.
   - Selects the top 100 records per language (based on recency or relevance).
3. The category mapping (17 entries) is applied to translate internal category names to consumer-facing names. Default category is `"news"`.
4. Aggregated data is grouped by language.
5. Each language group is published as a message to Pub/Sub topic `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit`.

### Step 2: RSS XML Generation (RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit)

1. Pub/Sub triggers the function for each language group.
2. The function builds an RSS 2.0 XML document with Media RSS namespace.
3. Channel-level elements:
   - `<title>`: "JioNews Videos RSS Feed"
   - `<link>`: "https://jionews.com"
4. For each video record, an `<item>` element is created with:
   - Standard RSS fields (title, link, description, pubDate, category)
   - `hlsAvcUrl` element (HLS AVC stream URL)
   - `hlsHevcUrl` element (HLS HEVC stream URL)
   - Thumbnail elements with normalized keys
5. Thumbnail key normalization is applied:
   - `low` -> `default`
   - `sd` -> `medium`
   - `hd` -> `high`
   - `fhd` -> `standard`
   - `original` -> `maxres`
6. The generated XML is uploaded to GCS: `hls_video_transcoder_storage_output_files/rss/videos_hls/{language}/rss.xml`.
7. Languages covered: IDs 1 through 13.

## Shorts RSS Sub-Pipeline -- Current Flow

### Step 1: Aggregation (RawShortsContentPrepareRss_AggregateDataLanguageSplit)

1. Cloud Scheduler triggers the aggregation function.
2. The function runs a MongoDB aggregation pipeline on `ingestion-data.raw_videos_rss`:
   - Filters for `processingStatus=completed` and `contentType=shorts`.
   - Uses the same `$setWindowFields` + `$documentNumber` approach as the videos sub-pipeline.
   - Selects the top 100 records per language.
3. The same category mapping is applied.
4. Aggregated data is published per language to `RawShortsContentPrepareRss_AggregatedDataLanguageSplit`.

### Step 2: RSS XML Generation (RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit)

1. Pub/Sub triggers the function for each language group.
2. The function builds an RSS 2.0 XML document.
3. Key differences from videos RSS:
   - **No HLS elements** (`hlsAvcUrl`, `hlsHevcUrl` are NOT included).
   - `pubDate` uses `sourceDate` directly from the record.
4. Thumbnail key normalization is applied (same as videos).
5. The generated XML is uploaded to GCS: `hls_video_transcoder_storage_output_files/rss/shorts/{language}/rss.xml`.
6. Languages covered: IDs 1 through 13.

## Current Limitations and Known Issues

| Issue | Impact | Severity |
|---|---|---|
| Top 100 limit per language is hardcoded | Cannot adjust feed size without code change | Low |
| Category mapping default to "news" may miscategorize unknown categories | Videos with new categories appear as "news" | Low |
| No incremental updates; full regeneration each run | Higher processing cost; all 100 records re-processed | Medium |
| Language IDs 1-13 are hardcoded | New languages require code change | Low |
| Same MongoDB collection for videos and shorts | Query performance may degrade as collection grows | Medium |
| No feed validation (RSS 2.0 schema) | Malformed XML possible if data contains special characters | Medium |
| Thumbnail key normalization assumes specific key names | New thumbnail sizes would not be mapped | Low |

## Operational Characteristics

| Metric | Value |
|---|---|
| Records per language | Top 100 |
| Language range | IDs 1-13 |
| Feed format | RSS 2.0 with Media RSS namespace |
| Content types | Videos (with HLS), Shorts (without HLS) |
| Output format | XML |
| Category mapping entries | 17 |
| Default category | "news" |
| Consumer | JioHotstar |

## Integration Points

| System | Direction | Protocol | Purpose |
|---|---|---|---|
| MongoDB Atlas | Inbound | MongoDB wire protocol | Source data aggregation |
| Pub/Sub (4 topics) | Internal | gRPC | Language-split message passing |
| GCS | Outbound | GCS API | RSS XML file storage |
| JioHotstar | Outbound (file-based) | GCS read | RSS feed consumption |
