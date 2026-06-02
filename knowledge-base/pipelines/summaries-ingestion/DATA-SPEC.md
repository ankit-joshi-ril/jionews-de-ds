# Summaries Ingestion - Data Specification

## Overview

This document defines all data schemas, field definitions, validation rules, and transformations for the Summaries Ingestion pipeline, including the LLM async summarization path for unhygienic records.

## Deduplication

### Redis Cache

| Attribute    | Value                          |
|--------------|--------------------------------|
| Cache Name   | `de_summaries_cache`           |
| Key          | Article title (string)         |
| Value        | Presence flag                  |
| TTL          | 48 hours (172800 seconds)      |

Records with a title already present in the cache are silently dropped.

## Hygiene Validation Rules

Hygiene validation is applied to **English-language records only**. Non-English records bypass all hygiene checks and proceed directly to the image CDN stage.

### Title Validation

| Rule               | Min | Max | Failure Type        |
|--------------------|-----|-----|---------------------|
| Character count    | 26  | 105 | Unhygienic (title)  |

### Summary Validation

| Rule               | Min | Max | Failure Type          |
|--------------------|-----|-----|----------------------|
| Character count    | 200 | 360 | Unhygienic (summary) |

### Content Validation

| Rule                    | Threshold | Failure Type              |
|-------------------------|-----------|---------------------------|
| HTML tags present       | 0 allowed | Unhygienic (HTML content) |
| Special characters count| < 3       | Unhygienic (special chars)|

### Validation Decision Matrix

| Title Valid | Summary Valid | No HTML | < 3 Special | Result     | Route                  |
|-------------|---------------|---------|-------------|------------|------------------------|
| Yes         | Yes           | Yes     | Yes         | Hygienic   | imagecdn -> MongoDB    |
| No          | Any           | Any     | Any         | Unhygienic | summarization-async    |
| Any         | No            | Any     | Any         | Unhygienic | summarization-async    |
| Any         | Any           | No      | Any         | Unhygienic | summarization-async    |
| Any         | Any           | Any     | No          | Unhygienic | summarization-async    |

## Default Thumbnail Handling

When a record has a default (placeholder) thumbnail image, the following transformations are applied:

| Field                  | Before                | After           |
|------------------------|-----------------------|-----------------|
| `isDefaultThumbnail`   | `true`                | `true` (kept)   |
| `sourcePublisherName`  | (actual publisher)    | `"InsideMedia"`  |
| `sourcePublisherId`    | (actual publisher ID) | `"000"`          |

This re-attribution ensures default-image records are not attributed to their original publisher in downstream systems.

## LLM Summarization Request

### Gemini API Configuration

| Parameter        | Value                   |
|------------------|-------------------------|
| Model            | `gemini-2.5-flash`      |
| Temperature      | `0`                     |
| Tools            | `[{"url_context": {}}]` |

### Two-Pass Strategy

**Pass 1 - URL Mode**:
- Input: Article URL with `url_context` tool enabled.
- The model uses the `url_context` tool to access and read the article content directly.
- If the model can summarize the content successfully, the result is used.

**Pass 2 - Content Fallback**:
- Triggered when URL mode fails (model cannot access the URL).
- Article content is fetched via the proxy service:
  ```
  GET https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy?url={article_url}
  ```
- The rendered article content is sent to Gemini as direct input text.

### LLM Response Format

The LLM is expected to return a JSON object. Parsing uses a 3-stage fallback:

1. **Direct parse**: `json.loads(response_text)`
2. **Strip markdown fences**: Remove `` ```json\n `` prefix and `` \n``` `` suffix, then parse.
3. **Extract JSON object**: Regex match first `\{.*\}` (dotall) from response text, then parse.

### Retry Configuration

| Parameter         | Value                                |
|-------------------|--------------------------------------|
| Max Attempts      | 3                                    |
| Retry Condition   | HTTP 503 from Gemini API             |
| Backoff Formula   | `2^attempt` seconds (2s, 4s, 8s)    |

### MongoDB Upsert (LLM Path)

The `summarization-async` service upserts results directly to MongoDB by `sourceId`:

```json
{
  "filter": { "sourceId": "<sourceId>" },
  "update": {
    "$set": {
      "summary": "<generated summary>",
      "title": "<generated or original title>",
      "updatedAt": "<epoch>"
    },
    "$setOnInsert": {
      "createdAt": "<epoch>",
      "sourceId": "<sourceId>"
    }
  },
  "upsert": true
}
```

## Processed Record Schema (Hygienic Path)

Records that pass hygiene validation and image CDN processing are written to MongoDB with the following schema. This mirrors the Headlines Ingestion schema with summary-specific additions:

```json
{
  "title": "string (26-105 chars for English)",
  "sourceDescription": "string (200-360 chars for English)",
  "url": "string (with UTM parameters)",
  "sourcePublishDate": "integer (Unix epoch)",
  "sourceThumbnailURL": "string",
  "thumbnailUrls": {
    "original": "string (CDN URL)",
    "fhd": "string (CDN URL)",
    "hd": "string (CDN URL)",
    "sd": "string (CDN URL)",
    "low": "string (CDN URL)"
  },
  "sourceId": "string",
  "createdAt": "integer (epoch)",
  "sourceLanguageId": "string",
  "sourceLanguageName": "string",
  "sourceCategoryId": "string",
  "sourceCategoryName": "string",
  "sourcePublisherId": "string (may be '000' for default thumbnails)",
  "sourcePublisherName": "string (may be 'InsideMedia' for default thumbnails)",
  "isDefaultThumbnail": "boolean"
}
```

### Field Details

| Field                  | Type    | Nullable | Description                                              |
|------------------------|---------|----------|----------------------------------------------------------|
| `title`                | string  | No       | Article title (26-105 chars if English)                  |
| `sourceDescription`    | string  | No       | Article summary (200-360 chars if English)               |
| `url`                  | string  | No       | Article URL with UTM parameters                          |
| `sourcePublishDate`    | int     | No       | Publisher's publish date as Unix epoch                    |
| `sourceThumbnailURL`   | string  | Yes      | Original thumbnail URL from publisher                    |
| `thumbnailUrls`        | object  | No       | CDN URLs for 5 image renditions                          |
| `sourceId`             | string  | No       | Unique article identifier                                |
| `createdAt`            | int     | No       | Pipeline processing timestamp                            |
| `sourceLanguageId`     | string  | No       | Language code from feed config                           |
| `sourceLanguageName`   | string  | No       | Language name from feed config                           |
| `sourceCategoryId`     | string  | No       | Category code from feed config                           |
| `sourceCategoryName`   | string  | No       | Category name from feed config                           |
| `sourcePublisherId`    | string  | No       | Publisher ID (or `"000"` for default thumbnails)         |
| `sourcePublisherName`  | string  | No       | Publisher name (or `"InsideMedia"` for default thumbnails)|
| `isDefaultThumbnail`   | boolean | No       | `true` if using a default/placeholder thumbnail          |

## Data Transformations Summary

| Stage              | Transformation                                              |
|--------------------|-------------------------------------------------------------|
| Fetch              | Feed parsing (RSS/JSON)                                     |
| Process            | Redis title-based deduplication                             |
| Process            | English hygiene validation (title, summary, HTML, specials) |
| Process            | Default thumbnail publisher re-attribution                  |
| Process            | Routing: hygienic -> imagecdn, unhygienic -> LLM           |
| ImageCDN           | Image download, EXIF, resize, JPEG q90, GCS upload          |
| LLM Async          | Two-pass summarization (URL mode, content fallback)         |
| LLM Async          | 3-stage JSON response parsing                               |
| LLM Async          | MongoDB upsert by sourceId                                  |
| PushToMongoDB      | Direct insert to MongoDB                                    |
