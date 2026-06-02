# RSS Feed Generation -- Architecture Document

## System Context

The RSS Feed Generation pipeline reads aggregated content from MongoDB and produces RSS 2.0 XML feeds for downstream consumption by JioHotstar. It operates as two parallel sub-pipelines (Videos and Shorts), each with an aggregation function and an XML generation function, running on Google Cloud Platform (project: `jiox-328108`).

## High-Level Architecture

```mermaid
flowchart TB
    subgraph "Schedulers"
        CS1[Cloud Scheduler<br>Videos]
        CS2[Cloud Scheduler<br>Shorts]
    end

    subgraph "Videos RSS Sub-Pipeline"
        VA[AggregateDataLanguageSplit<br>Videos HLS]
        VP[ProcessRssFeedLanguageSplit<br>Videos HLS]
    end

    subgraph "Shorts RSS Sub-Pipeline"
        SA[AggregateDataLanguageSplit<br>Shorts]
        SP[ProcessRssFeedLanguageSplit<br>Shorts]
    end

    subgraph "Pub/Sub Topics"
        PV[RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit]
        PS[RawShortsContentPrepareRss_AggregatedDataLanguageSplit]
    end

    subgraph "Data Stores"
        MongoDB[(MongoDB:<br>raw_videos_rss)]
        GCS[(GCS:<br>hls_video_transcoder_storage_output_files)]
    end

    subgraph "Consumer"
        JH[JioHotstar]
    end

    CS1 -->|Trigger| VA
    CS2 -->|Trigger| SA

    VA -->|Query top 100 per lang<br>transcoderProcessingStatus=completed| MongoDB
    SA -->|Query top 100 per lang<br>processingStatus=completed| MongoDB

    VA -->|Publish per language| PV
    SA -->|Publish per language| PS

    PV -->|Background trigger| VP
    PS -->|Background trigger| SP

    VP -->|Write rss/videos_hls/{lang}/rss.xml| GCS
    SP -->|Write rss/shorts/{lang}/rss.xml| GCS

    GCS -->|Read RSS feeds| JH
```

## Videos RSS Sequence

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant Agg as Videos Aggregate Function
    participant Mongo as MongoDB
    participant PS as Pub/Sub: Videos Aggregated
    participant RSS as Videos RSS Function
    participant GCS as GCS

    CS->>Agg: Scheduled trigger

    Agg->>Mongo: Aggregation pipeline:<br>$match transcoderProcessingStatus=completed, contentType=videos<br>$setWindowFields partition by language<br>$documentNumber top 100
    Mongo-->>Agg: Top 100 videos per language

    Agg->>Agg: Apply category mapping (17 entries, default=news)
    Agg->>Agg: Group by language

    loop Each language (IDs 1-13)
        Agg->>PS: Publish language group
    end

    loop Each language message
        PS->>RSS: Background trigger
        RSS->>RSS: Build RSS 2.0 XML with Media RSS namespace
        RSS->>RSS: Set channel: title=JioNews Videos RSS Feed, link=jionews.com

        loop Each video record
            RSS->>RSS: Create item element
            RSS->>RSS: Add hlsAvcUrl element
            RSS->>RSS: Add hlsHevcUrl element
            RSS->>RSS: Normalize thumbnail keys<br>(low->default, sd->medium, hd->high, fhd->standard, original->maxres)
        end

        RSS->>GCS: Upload rss/videos_hls/{language}/rss.xml
    end
```

## Shorts RSS Sequence

```mermaid
sequenceDiagram
    participant CS as Cloud Scheduler
    participant Agg as Shorts Aggregate Function
    participant Mongo as MongoDB
    participant PS as Pub/Sub: Shorts Aggregated
    participant RSS as Shorts RSS Function
    participant GCS as GCS

    CS->>Agg: Scheduled trigger

    Agg->>Mongo: Aggregation pipeline:<br>$match processingStatus=completed, contentType=shorts<br>$setWindowFields partition by language<br>$documentNumber top 100
    Mongo-->>Agg: Top 100 shorts per language

    Agg->>Agg: Apply category mapping (17 entries, default=news)
    Agg->>Agg: Group by language

    loop Each language (IDs 1-13)
        Agg->>PS: Publish language group
    end

    loop Each language message
        PS->>RSS: Background trigger
        RSS->>RSS: Build RSS 2.0 XML
        RSS->>RSS: Set channel: title=JioNews Videos RSS Feed, link=jionews.com

        loop Each short record
            RSS->>RSS: Create item element
            RSS->>RSS: Set pubDate from sourceDate directly
            Note over RSS: NO hlsAvcUrl or hlsHevcUrl elements
            RSS->>RSS: Normalize thumbnail keys
        end

        RSS->>GCS: Upload rss/shorts/{language}/rss.xml
    end
```

## Parallel Sub-Pipeline Comparison

```mermaid
flowchart LR
    subgraph "Videos Sub-Pipeline"
        direction TB
        VA[Aggregate<br>Filter: transcoderProcessingStatus=completed<br>contentType=videos]
        VP[Generate RSS<br>Includes: hlsAvcUrl, hlsHevcUrl<br>pubDate: computed]
        VA --> VP
        VP --> VG[GCS: rss/videos_hls/]
    end

    subgraph "Shorts Sub-Pipeline"
        direction TB
        SA[Aggregate<br>Filter: processingStatus=completed<br>contentType=shorts]
        SP[Generate RSS<br>Excludes: HLS elements<br>pubDate: sourceDate directly]
        SA --> SP
        SP --> SG[GCS: rss/shorts/]
    end
```

## Category Mapping Flow

```mermaid
flowchart TD
    A[Internal Category] --> B{Map lookup}
    B -->|news| C1[news]
    B -->|cricket| C2[sports]
    B -->|business| C3[business news]
    B -->|technology| C4[science and technology]
    B -->|automotive| C5[automobile]
    B -->|entertainment| C6[entertainment]
    B -->|health| C7[health]
    B -->|spiritual| C8[astrology]
    B -->|astrology| C8
    B -->|fashion| C9[lifestyle]
    B -->|travel| C9
    B -->|food| C9
    B -->|diy| C9
    B -->|sports| C2
    B -->|career| C10[education]
    B -->|football| C2
    B -->|agro| C1
    B -->|unknown| C1
```

## Component Details

### RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler |
| Input | MongoDB aggregation |
| Filter | `transcoderProcessingStatus=completed`, `contentType=videos` |
| Aggregation | `$setWindowFields` + `$documentNumber`, top 100 per language |
| Output | Pub/Sub: `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` |

### RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub background |
| Input | Language-grouped video records |
| Processing | RSS 2.0 XML generation with HLS elements |
| Output | GCS: `rss/videos_hls/{language}/rss.xml` |

### RawShortsContentPrepareRss_AggregateDataLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Cloud Scheduler |
| Input | MongoDB aggregation |
| Filter | `processingStatus=completed`, `contentType=shorts` |
| Aggregation | `$setWindowFields` + `$documentNumber`, top 100 per language |
| Output | Pub/Sub: `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` |

### RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit

| Attribute | Value |
|---|---|
| Trigger | Pub/Sub background |
| Input | Language-grouped shorts records |
| Processing | RSS 2.0 XML generation WITHOUT HLS elements |
| Output | GCS: `rss/shorts/{language}/rss.xml` |

## Infrastructure Dependencies

| Resource | Type | Identifier |
|---|---|---|
| GCP Project | Project | `jiox-328108` (266686822828) |
| GCS Bucket | Storage | `hls_video_transcoder_storage_output_files` |
| Pub/Sub Topic | Messaging | `RawVideosHLSContentPrepareRss_AggregatedDataLanguageSplit` |
| Pub/Sub Topic | Messaging | `RawShortsContentPrepareRss_AggregatedDataLanguageSplit` |
| MongoDB Collection | Database | `ingestion-data.raw_videos_rss` |
| Cloud Scheduler Jobs | Trigger | 2 jobs (Videos + Shorts aggregation) |

## GCS Output Structure

```
hls_video_transcoder_storage_output_files/
  rss/
    videos_hls/
      English/rss.xml
      Hindi/rss.xml
      Marathi/rss.xml
      Gujarati/rss.xml
      Malayalam/rss.xml
      Tamil/rss.xml
      Urdu/rss.xml
      Kannada/rss.xml
      Punjabi/rss.xml
      Telugu/rss.xml
      Bangla/rss.xml
      ...
    shorts/
      English/rss.xml
      Hindi/rss.xml
      Marathi/rss.xml
      ...
```
