# Headlines Ingestion - Data Specification

## Overview

This document defines all data schemas, field definitions, transformations, and validation rules for the Headlines Ingestion pipeline. It covers data from initial feed ingestion through final MongoDB persistence.

## Feed Configuration Schema

**Source**: `gs://de-raw-ingestion/headlines/headlines_publishers_feeds.csv`

The CSV file contains publisher feed configurations. Each row defines a single feed endpoint for a publisher-language-category combination.

| Column              | Type   | Description                                      |
|---------------------|--------|--------------------------------------------------|
| `publisher_name`    | string | Display name of the publisher                    |
| `publisher_id`      | string | Unique identifier for the publisher              |
| `feed_url`          | string | RSS/XML or JSON endpoint URL                     |
| `feed_id`           | string | Unique identifier for the feed                   |
| `language_id`       | string | Language code identifier                         |
| `language_name`     | string | Human-readable language name                     |
| `category_id`       | string | Category code identifier                         |
| `category_name`     | string | Human-readable category name                     |
| `feed_type`         | string | `rss` or `json`                                  |

## Raw Feed Record (Post-Fetch)

After `fetchfeedsdata` parses a feed, each article produces a raw record with the following fields. Field sources vary by feed type and publisher.

### Standard RSS/XML Field Mapping

| Output Field         | RSS Source Field                        | Notes                                 |
|----------------------|-----------------------------------------|---------------------------------------|
| `title`              | `entry.title`                           | Direct mapping                        |
| `url`                | `entry.link`                            | Appended with UTM params              |
| `sourcePublishDate`  | `entry.published_parsed` / `entry.published` | Converted to epoch seconds      |
| `sourceDescription`  | `entry.summary`                         | Article summary/description           |
| `thumbnail`          | 12-step extraction chain (see below)    | Source thumbnail URL                  |

### Standard JSON Field Mapping

| Output Field         | JSON Source Field          | Notes                                 |
|----------------------|----------------------------|---------------------------------------|
| `title`              | `item['title']`            | From `items` array elements           |
| `url`                | `item['link']`             | Appended with UTM params              |
| `sourcePublishDate`  | `item['published']`        | Converted to epoch seconds            |
| `sourceDescription`  | `item['summary']`          | Article summary/description           |
| `thumbnail`          | `item['thumbnail']`        | Direct URL if available               |

### Newspoint Publisher Field Mapping

Applies to publishers: `english-newspointapp`, `Indiatimes`, `Navbharat Times`, `Newspoint`.

| Output Field         | Newspoint Source Field | Notes                                 |
|----------------------|------------------------|---------------------------------------|
| `title`              | `hl`                   | Headline                              |
| `url`                | `mwu`                  | Mobile web URL                        |
| `sourcePublishDate`  | `dl`                   | Date line                             |
| `category`           | `sec`                  | Section/category                      |

### ESPNcricinfo Special Handling

| Output Field | Source Field     | Notes                                        |
|--------------|------------------|----------------------------------------------|
| `url`        | `record['href']` | Uses `href` instead of standard `link` field |
| UTM Param    | `ex_cid=jionews` | Uses `ex_cid` instead of standard UTM params |

## UTM Parameter Rules

### Standard Publishers

All article URLs are appended with the following UTM parameters:

```
utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews
```

If the URL already contains query parameters (`?`), UTM params are appended with `&`. Otherwise, they are appended with `?`.

### ESPNcricinfo Exception

ESPNcricinfo URLs use a custom tracking parameter instead of standard UTM:

```
ex_cid=jionews
```

## Thumbnail Extraction Priority Chain

The 12-step priority chain for extracting a thumbnail URL from feed entries. The first non-empty result is used:

| Priority | Source                                           | Description                                              |
|----------|--------------------------------------------------|----------------------------------------------------------|
| 1        | `media_content[0]['url']`                        | RSS media:content element                                |
| 2        | `media_thumbnail[0]['url']`                      | RSS media:thumbnail element                              |
| 3        | `enclosures[0]['href']`                          | RSS enclosure element                                    |
| 4        | `links` (type=image)                             | RSS link with image MIME type                            |
| 5        | `content[0]` image parsing                       | Parse image URL from content HTML                        |
| 6        | `summary` image parsing                          | Parse image URL from summary HTML                        |
| 7        | `description` image parsing                      | Parse image URL from description HTML                    |
| 8        | `image['href']`                                  | Direct image element                                     |
| 9        | `thumbimage`                                     | Custom tag (post `<image>` -> `<thumbimage>` replacement)|
| 10       | Feed-level `image`                               | Channel-level image                                      |
| 11       | JSON direct `thumbnail` field                    | For JSON feeds                                           |
| 12       | HTML `<img>` tag parsing in content              | Last resort: parse img tags from article content         |

**Rejection**: If all 12 steps return empty, the record is rejected with reason: `"No thumbnail image url found"`.

## Epoch / Date Handling

### Conversion Rules

1. If `published_parsed` is available (struct_time), convert via `calendar.timegm()`.
2. If `published` is a string, parse with `dateutil.parser.parse()` then convert to epoch.
3. If the resulting epoch is greater than current epoch, subtract `19800` seconds (IST UTC+5:30 offset correction).

### Epoch Adjustment Logic

```
if publisher_epoch > current_epoch:
    adjusted_epoch = publisher_epoch - 19800
```

This corrects for publishers that erroneously provide IST timestamps as if they were UTC.

## Processed Record Schema (Final)

After all processing stages, the record written to MongoDB has the following schema:

```json
{
  "title": "string",
  "sourceDescription": "string",
  "url": "string (original URL with UTM parameters appended)",
  "sourcePublishDate": "integer (Unix epoch seconds)",
  "sourceThumbnailURL": "string (original source thumbnail URL)",
  "thumbnailUrls": {
    "original": "https://icdn.jionews.com/original/{sourceId}.jpeg",
    "fhd": "https://icdn.jionews.com/fhd/{sourceId}.jpeg",
    "hd": "https://icdn.jionews.com/hd/{sourceId}.jpeg",
    "sd": "https://icdn.jionews.com/sd/{sourceId}.jpeg",
    "low": "https://icdn.jionews.com/low/{sourceId}.jpeg"
  },
  "sourceId": "string (bson.ObjectId as string)",
  "createdAt": "integer (Unix epoch seconds, time of processing)",
  "sourceLanguageId": "string",
  "sourceLanguageName": "string",
  "sourceCategoryId": "string",
  "sourceCategoryName": "string",
  "sourcePublisherId": "string",
  "sourcePublisherName": "string",
  "sourceFeedUrl": "string",
  "sourceFeedId": "string",
  "briefWordCount": "integer (word count of article body)",
  "publisherArticleBody": "string (raw scraped article body)",
  "articleBody": "string (cleaned article body text)",
  "articleHtml": "string (article body as HTML)"
}
```

### Field Descriptions

| Field                | Type    | Nullable | Description                                              |
|----------------------|---------|----------|----------------------------------------------------------|
| `title`              | string  | No       | Article headline/title from the feed                     |
| `sourceDescription`  | string  | Yes      | Article summary or description from the feed             |
| `url`                | string  | No       | Article URL with UTM parameters appended                 |
| `sourcePublishDate`  | int     | No       | Publisher's original publish date as Unix epoch           |
| `sourceThumbnailURL` | string  | No       | Original thumbnail URL from the publisher feed           |
| `thumbnailUrls`      | object  | No       | CDN URLs for all 5 image renditions                      |
| `sourceId`           | string  | No       | Unique identifier generated via `bson.ObjectId()`        |
| `createdAt`          | int     | No       | Pipeline processing timestamp as Unix epoch              |
| `sourceLanguageId`   | string  | No       | Language identifier from feed config                     |
| `sourceLanguageName` | string  | No       | Language name from feed config                           |
| `sourceCategoryId`   | string  | No       | Category identifier from feed config                     |
| `sourceCategoryName` | string  | No       | Category name from feed config                           |
| `sourcePublisherId`  | string  | No       | Publisher identifier from feed config                    |
| `sourcePublisherName`| string  | No       | Publisher name from feed config                          |
| `sourceFeedUrl`      | string  | No       | RSS/JSON feed endpoint URL                               |
| `sourceFeedId`       | string  | No       | Feed identifier from feed config                         |
| `briefWordCount`     | int     | Yes      | Word count of the article body (0 if scrape fails)       |
| `publisherArticleBody`| string | Yes      | Raw article body from scraper                            |
| `articleBody`        | string  | Yes      | Cleaned plain-text article body                          |
| `articleHtml`        | string  | Yes      | HTML-formatted article body                              |

## Image CDN URL Pattern

All CDN image URLs follow the pattern:

```
https://icdn.jionews.com/{rendition}/{sourceId}.jpeg
```

### Rendition Dimensions

| Rendition  | Width  | Height | Aspect Ratio | Use Case           |
|------------|--------|--------|--------------|---------------------|
| `original` | Source | Source | Source       | Full resolution     |
| `fhd`      | 1920   | 1080   | 16:9         | Full HD displays    |
| `hd`       | 1280   | 720    | 16:9         | HD displays         |
| `sd`       | 720    | 480    | 3:2          | Standard displays   |
| `low`      | 480    | 320    | 3:2          | Thumbnails/previews |

## Rejected Record Schema

Records routed to `rejected-pushtomongo` include the full processed record plus:

| Field             | Type   | Description                         |
|-------------------|--------|-------------------------------------|
| `rejectionReason` | string | Human-readable rejection reason     |
| `rejectedAt`      | int    | Epoch timestamp of rejection        |

## Default Image Pools

When a record requires a default thumbnail (fallback after all extraction attempts):

| Category       | Default Image Count | Selection Method |
|----------------|---------------------|------------------|
| `latest_news`  | 22 variants         | Random selection |
| All others     | 10 variants         | Random selection |

## Data Transformations Summary

| Stage              | Transformation                                         |
|--------------------|--------------------------------------------------------|
| Fetch              | `<image>` -> `<thumbimage>` tag replacement in XML     |
| Fetch              | Feed parsing (feedparser for RSS, json.loads for JSON) |
| Fetch              | Newspoint field remapping (hl, mwu, dl, sec)           |
| Process            | Redis dedup check (link + title)                       |
| Process            | UTM parameter appending                                |
| Process            | Epoch conversion and IST offset correction             |
| Process            | Article body scraping (primary + fallback)             |
| Process            | sourceId generation (bson.ObjectId)                    |
| ImageCDN           | EXIF orientation transpose                             |
| ImageCDN           | 5-rendition resize                                     |
| ImageCDN           | JPEG encoding at q90                                   |
| ImageCDN           | GCS upload + CDN URL generation                        |
| ImageCDN           | Thumbnail presence validation                          |
