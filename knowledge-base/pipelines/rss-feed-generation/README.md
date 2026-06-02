# RSS Feed Generation Pipeline

## Overview

The RSS Feed Generation pipeline produces RSS 2.0 XML feeds for both videos (with HLS streams) and shorts content. It aggregates the top 100 items per language from MongoDB, applies category mapping, and writes language-specific RSS XML files to GCS for consumption by JioHotstar.

## Pipeline Identity

| Attribute | Value |
|---|---|
| Pipeline Name | RSS Feed Generation |
| GCP Project | `jiox-328108` (Project Number: `266686822828`) |
| Runtime | Python (Cloud Functions) |
| Data Store | MongoDB (`ingestion-data.raw_videos_rss`) |
| Output | GCS: `hls_video_transcoder_storage_output_files/rss/` |
| Consumer | JioHotstar |

## Sub-Pipeline Architecture

The pipeline has two parallel sub-pipelines, each with two Cloud Functions:

### Videos RSS Sub-Pipeline

| Order | Cloud Function | Trigger | Purpose |
|---|---|---|---|
| 1 | `RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit` | Cloud Scheduler | Aggregate top 100 videos per language |
| 2 | `RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit` | Pub/Sub (background) | Generate RSS XML with HLS elements |

### Shorts RSS Sub-Pipeline

| Order | Cloud Function | Trigger | Purpose |
|---|---|---|---|
| 1 | `RawShortsContentPrepareRss_AggregateDataLanguageSplit` | Cloud Scheduler | Aggregate top 100 shorts per language |
| 2 | `RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit` | Pub/Sub (background) | Generate RSS XML without HLS elements |

## Output Locations

| Content Type | GCS Path | Languages |
|---|---|---|
| Videos | `hls_video_transcoder_storage_output_files/rss/videos_hls/{language}/rss.xml` | IDs 1-13 |
| Shorts | `hls_video_transcoder_storage_output_files/rss/shorts/{language}/rss.xml` | IDs 1-13 |

## Key Behaviors

- MongoDB aggregation uses `$setWindowFields` with `$documentNumber` to select the top 100 records per language.
- Videos RSS includes `hlsAvcUrl` and `hlsHevcUrl` elements (Media RSS namespace).
- Shorts RSS does NOT include HLS elements; uses `sourceDate` directly for `pubDate`.
- Category names are mapped from internal names to consumer-facing names (17 entries, default: `"news"`).
- Thumbnail keys are normalized: `low` -> `default`, `sd` -> `medium`, `hd` -> `high`, `fhd` -> `standard`, `original` -> `maxres`.

## RSS XML Channel Metadata

| Element | Value |
|---|---|
| `<title>` | JioNews Videos RSS Feed |
| `<link>` | https://jionews.com |
| Namespace | Media RSS (xmlns:media) |

## Category Mapping

| Internal Category | RSS Category |
|---|---|
| news | news |
| cricket | sports |
| business | business news |
| technology | science and technology |
| automotive | automobile |
| entertainment | entertainment |
| health | health |
| spiritual | astrology |
| astrology | astrology |
| fashion | lifestyle |
| travel | lifestyle |
| food | lifestyle |
| diy | lifestyle |
| sports | sports |
| career | education |
| football | sports |
| agro | news |

## Related Pipelines

- Upstream: Video Transcoder Workflow (provides `transcoderProcessingStatus=completed` records)
- Upstream: Native Videos Ingestion (provides `processingStatus=completed` records for shorts)
- Consumer: JioHotstar (reads generated RSS XML files)
