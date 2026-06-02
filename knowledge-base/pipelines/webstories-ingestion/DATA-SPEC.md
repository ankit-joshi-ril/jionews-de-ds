# Webstories Ingestion - Data Specification

## Overview

This document defines all data schemas, field definitions, transformations, and validation rules for the Webstories Ingestion pipeline. The pipeline is notable for its configurable per-publisher field mapping system and its simplicity compared to Headlines and Summaries pipelines.

## Publisher Configuration Schema

**Source**: Local CSV file bundled with the `RawWebStoriesIngestion` Cloud Function deployment package.

| Column           | Type   | Required | Description                                              |
|------------------|--------|----------|----------------------------------------------------------|
| `sys_pub_name`   | string | Yes      | System publisher name (unique identifier)                |
| `endpoint`       | string | Yes      | Publisher API or RSS feed endpoint URL                   |
| `data_list_path` | string | Yes      | JSON path to story array in API response (API type only) |
| `type`           | string | Yes      | Source type: `api` or `feed`                             |
| `mapping`        | string | Yes      | JSON string defining field extraction mapping            |
| `category`       | string | Yes      | Content category name                                    |
| `language`       | string | Yes      | Content language name                                    |

### Mapping JSON Structure

The `mapping` column contains a JSON string that maps standard output fields to publisher-specific source fields. Example:

```json
{
  "title": "headline",
  "url": "story_url",
  "thumbnail": "cover_image",
  "published_date": "created_at"
}
```

Each key is the standard output field name, and each value is the publisher's proprietary field name for that data.

## Source Type Processing

### API Sources

| Step | Action                                                |
|------|-------------------------------------------------------|
| 1    | HTTP GET to `endpoint`                                |
| 2    | Parse response as JSON                                |
| 3    | Navigate to array using `data_list_path`              |
| 4    | For each item, apply `mapping` to extract fields      |
| 5    | Apply URL transformations (HTTPS, UTM)                |
| 6    | Validate thumbnail URL via HTTP GET                   |

**data_list_path** usage:
```python
# If data_list_path = "data.stories"
response_json = json.loads(response.text)
items = response_json["data"]["stories"]
```

### Feed Sources

| Step | Action                                                |
|------|-------------------------------------------------------|
| 1    | HTTP GET to `endpoint`                                |
| 2    | Parse response with `feedparser`                      |
| 3    | For each entry, apply `mapping` to extract fields     |
| 4    | Apply URL transformations (HTTPS, UTM)                |
| 5    | Validate thumbnail URL via HTTP GET                   |

## URL Transformation Rules

### HTTPS Enforcement

All URLs (both article and thumbnail) undergo protocol replacement:

```
http://example.com/story → https://example.com/story
```

Applied unconditionally to all URLs.

### UTM Parameters

All article URLs (not thumbnail URLs) are appended with:

```
utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories
```

**Note**: The UTM campaign is `JioNewsStories`, which differs from Headlines (`JioNews`).

URL construction:
```
If URL contains "?":
    url = url + "&utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories"
Else:
    url = url + "?utm_source=JioNews&utm_medium=referral&utm_campaign=JioNewsStories"
```

## Thumbnail Validation

Thumbnail URLs are validated via HTTP GET request:

```python
try:
    response = requests.get(thumbnail_url)
    if response.status_code == 200:
        # URL is valid
        validated_thumbnail = thumbnail_url
    else:
        # URL is invalid
        validated_thumbnail = None
except Exception:
    validated_thumbnail = None
```

This is a simpler approach compared to Headlines (12-step priority chain) and Summaries (default thumbnail fallback).

## Processed Record Schema

The final record written to MongoDB:

```json
{
  "sourceId": "string (unique identifier)",
  "title": "string",
  "sourcePublishedDate": "string (date string from publisher)",
  "sourceCategoryName": "string",
  "sourceLanguageName": "string",
  "sourcePublisherName": "string",
  "sourceURL": "string (HTTPS enforced, UTM appended)",
  "sourceThumbnailUrl": "string (validated via HTTP GET)",
  "createdAt": "integer (Unix epoch seconds)"
}
```

### Field Details

| Field                  | Type   | Nullable | Description                                              |
|------------------------|--------|----------|----------------------------------------------------------|
| `sourceId`             | string | No       | Unique identifier for the web story                      |
| `title`                | string | No       | Web story title from publisher                           |
| `sourcePublishedDate`  | string | Yes      | Published date as string (format varies by publisher)    |
| `sourceCategoryName`   | string | No       | Category from publisher CSV config                       |
| `sourceLanguageName`   | string | No       | Language from publisher CSV config                       |
| `sourcePublisherName`  | string | No       | Publisher name from CSV config                           |
| `sourceURL`            | string | No       | Full web story URL (HTTPS + UTM params)                  |
| `sourceThumbnailUrl`   | string | Yes      | Validated thumbnail URL (HTTPS enforced)                 |
| `createdAt`            | int    | No       | Pipeline processing timestamp as Unix epoch              |

### Schema Differences from Headlines/Summaries

| Field                  | Headlines/Summaries       | Webstories               |
|------------------------|---------------------------|--------------------------|
| URL field name         | `url`                     | `sourceURL`              |
| Date field name        | `sourcePublishDate` (int) | `sourcePublishedDate` (string) |
| Date format            | Unix epoch integer        | String (publisher format)|
| Thumbnail field name   | `sourceThumbnailURL`      | `sourceThumbnailUrl` (lowercase 'l') |
| CDN URLs               | `thumbnailUrls` object    | Not present (no CDN)     |
| Article body           | `articleBody`, etc.       | Not present (no scraping)|
| Feed/publisher IDs     | `sourceFeedId`, etc.      | Not present              |

## Data Transformations Summary

| Stage              | Transformation                                         |
|--------------------|--------------------------------------------------------|
| Fetch              | HTTP GET to publisher endpoint                         |
| Parse (API)        | JSON parse, navigate `data_list_path`, apply `mapping` |
| Parse (Feed)       | feedparser parse, apply `mapping`                      |
| URL Transform      | `http://` -> `https://` replacement                    |
| URL Transform      | Append UTM params (campaign=JioNewsStories)            |
| Thumbnail          | HTTP GET validation                                    |
| Metadata           | Add `createdAt` epoch, `sourceCategoryName`, `sourceLanguageName`, `sourcePublisherName` from CSV config |
| Persistence        | Insert to MongoDB                                      |
