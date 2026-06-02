# Summaries Ingestion - Technical Specification

## Overview

This document provides implementation-level technical details for the Summaries Ingestion pipeline, including Cloud Function specifications, the LLM async summarization Cloud Run service, retry logic, JSON parsing resilience, and hygiene validation implementation.

## Runtime Environment

| Attribute        | Value                          |
|------------------|--------------------------------|
| Runtime          | Python 3.x                     |
| GCP Project      | `jiox-328108` (266686822828)   |
| Region           | `asia-south1`                  |
| Functions Gen    | Cloud Functions Gen 2          |

## Function Specifications

### 1. FetchFeedsData

| Attribute          | Value                                      |
|--------------------|--------------------------------------------|
| Trigger            | HTTP (Cloud Scheduler cron)                |
| Entry Point        | `main(req)`                                |
| Pub/Sub Output     | `RawSummariesIngestion_FeedsData`          |

#### Execution Flow

1. Read publisher feed configurations (format similar to Headlines pipeline).
2. For each feed, HTTP GET the feed URL.
3. Parse RSS/XML feeds with `feedparser` or JSON feeds with `json.loads()`.
4. Map publisher-specific fields to standard schema.
5. Batch-publish raw records to Pub/Sub.

### 2. ProcessSummaries

| Attribute          | Value                                      |
|--------------------|--------------------------------------------|
| Trigger            | HTTP (Pub/Sub push subscription)           |
| Entry Point        | `main(req)`                                |
| Pub/Sub Input      | `RawSummariesIngestion_FeedsData`          |
| Pub/Sub Output (Hygienic) | `NewRawHeadlinesIngestion_image_cdn` (shared) |
| Pub/Sub Output (Unhygienic) | `RawSummariesIngestion_HygineFailure` |

#### Deduplication

```python
# Single-layer title-based dedup
title = record["title"]
if redis_cache.get("de_summaries_cache", title):
    return  # Silently drop duplicate

redis_cache.set("de_summaries_cache", title, "1", ttl=172800)
```

#### Hygiene Validation (English Only)

```python
import re

def validate_hygiene(record):
    """Returns True if record passes all hygiene checks."""
    if record["sourceLanguageName"].lower() != "english":
        return True  # Non-English bypasses hygiene

    title = record.get("title", "")
    summary = record.get("sourceDescription", "")

    # Title length: 26-105 characters
    if not (26 <= len(title) <= 105):
        return False

    # Summary length: 200-360 characters
    if not (200 <= len(summary) <= 360):
        return False

    # No HTML tags allowed
    if re.search(r"<[^>]+>", summary):
        return False

    # Fewer than 3 special characters
    special_count = len(re.findall(r"[^a-zA-Z0-9\s.,!?'\"-]", summary))
    if special_count >= 3:
        return False

    return True
```

#### Default Thumbnail Re-attribution

```python
if record.get("isDefaultThumbnail") == True:
    record["sourcePublisherName"] = "InsideMedia"
    record["sourcePublisherId"] = "000"
```

#### Routing Logic

```python
if validate_hygiene(record):
    publish_to("NewRawHeadlinesIngestion_image_cdn", record)  # Shared topic
else:
    publish_to("RawSummariesIngestion_HygineFailure", record)
```

### 3. imagecdn (Shared)

This function is shared with the Headlines Ingestion pipeline. See [Headlines Ingestion TECH-SPEC](../headlines-ingestion/TECH-SPEC.md) for full implementation details.

The summaries pipeline publishes to the same `NewRawHeadlinesIngestion_image_cdn` topic and receives processed results on `RawSummariesIngestion_ProcessedData`.

### 4. PushToMongoDB

| Attribute          | Value                                          |
|--------------------|-------------------------------------------------|
| Trigger            | CloudEvent (Pub/Sub)                            |
| Entry Point        | `write_to_mongodb(cloud_event)`                 |
| Pub/Sub Input      | `RawSummariesIngestion_ProcessedData`           |
| MongoDB Collection | `ingestion-data.raw_summaries_insgestion_data`  |

```python
client = MongoClient(secret("mongosh_de_uri"))
db = client["ingestion-data"]
collection = db["raw_summaries_insgestion_data"]  # Note: production typo preserved

collection.insert_one(record)
```

### 5. summarization-async (Cloud Run)

| Attribute          | Value                                          |
|--------------------|-------------------------------------------------|
| Type               | Cloud Run service                               |
| Trigger            | Pub/Sub push from `RawSummariesIngestion_HygineFailure` |
| Secrets            | `GEMINI_API_KEY`, `mongosh_de_uri`              |
| Model              | `gemini-2.5-flash`                              |
| Temperature        | `0`                                             |
| Tools              | `[{"url_context": {}}]`                         |

#### Two-Pass Summarization Implementation

```python
import google.generativeai as genai
import time
import json
import re

def summarize(record):
    """Two-pass summarization: URL mode first, content fallback."""

    genai.configure(api_key=secret("GEMINI_API_KEY"))
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"temperature": 0},
        tools=[{"url_context": {}}]
    )

    article_url = record["url"]

    # Pass 1: URL Mode
    try:
        response = call_gemini_with_retry(model, article_url, mode="url")
        result = parse_json_response(response.text)
        if result:
            return result
    except Exception:
        pass

    # Pass 2: Content Fallback via Proxy
    proxy_url = (
        "https://jn-article-render-proxy-266686822828"
        ".asia-south1.run.app/proxy"
    )
    content = requests.get(f"{proxy_url}?url={article_url}").text

    response = call_gemini_with_retry(model, content, mode="content")
    result = parse_json_response(response.text)
    return result
```

#### Retry Implementation

```python
def call_gemini_with_retry(model, input_data, mode, max_attempts=3):
    """Retry on HTTP 503 with exponential backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            if mode == "url":
                response = model.generate_content(
                    f"Summarize the article at: {input_data}"
                )
            else:
                response = model.generate_content(
                    f"Summarize the following article:\n{input_data}"
                )
            return response

        except Exception as e:
            if "503" in str(e) and attempt < max_attempts:
                wait_time = 2 ** attempt  # 2s, 4s, 8s
                time.sleep(wait_time)
                continue
            raise
```

#### 3-Stage JSON Parsing

```python
def parse_json_response(response_text):
    """3-stage JSON parsing for LLM responses."""

    # Stage 1: Direct parse
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Stage 2: Strip markdown fences
    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]  # Remove ```json prefix
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]  # Remove ``` prefix
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]  # Remove ``` suffix
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        pass

    # Stage 3: Extract first JSON object
    try:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass

    return None  # All stages failed
```

#### MongoDB Upsert (LLM Path)

```python
def upsert_summary(record, summary_result):
    """Upsert LLM-generated summary to MongoDB."""
    client = MongoClient(secret("mongosh_de_uri"))
    db = client["ingestion-data"]
    collection = db["raw_summaries_insgestion_data"]

    now = int(time.time())

    collection.find_one_and_update(
        filter={"sourceId": record["sourceId"]},
        update={
            "$set": {
                "summary": summary_result["summary"],
                "title": summary_result.get("title", record["title"]),
                "updatedAt": now
            },
            "$setOnInsert": {
                "createdAt": now,
                "sourceId": record["sourceId"]
            }
        },
        upsert=True
    )
```

## Key Libraries

| Library                | Purpose                                       |
|------------------------|-----------------------------------------------|
| `feedparser`           | RSS/XML feed parsing                          |
| `pymongo`              | MongoDB client                                |
| `redis`                | Redis deduplication cache client              |
| `google-generativeai`  | Gemini API client (LLM summarization)         |
| `google-cloud-pubsub`  | Pub/Sub publish                               |
| `google-cloud-storage` | GCS image upload (via shared imagecdn)        |
| `requests`             | HTTP client for feeds and proxy               |
| `Pillow`               | Image processing (via shared imagecdn)        |

## Error Handling

| Stage              | Error Type                | Handling                                     |
|--------------------|---------------------------|----------------------------------------------|
| Feed Fetch         | HTTP error / timeout      | Log, skip feed                               |
| Redis              | Connection error          | Fail-open (allow record through)             |
| Hygiene Validation | Validation failure        | Route to LLM path (not an error)             |
| LLM - Pass 1      | URL mode failure          | Fall through to Pass 2 (content mode)        |
| LLM - Pass 2      | Content mode failure      | Log error, record not persisted              |
| LLM - 503         | Rate limit / overload     | Exponential backoff, up to 3 attempts        |
| JSON Parsing       | Malformed LLM output      | 3-stage fallback; log if all fail            |
| MongoDB Insert     | Write error               | Log error, message remains in Pub/Sub        |
| MongoDB Upsert     | Write error               | Log error                                    |

## Secrets Management

| Secret Name      | Storage                   | Accessed By                                |
|------------------|---------------------------|--------------------------------------------|
| `mongosh_de_uri` | GCP Secret Manager        | `PushToMongoDB`, `summarization-async`     |
| `GEMINI_API_KEY` | GCP Secret Manager        | `summarization-async`                      |

## Configuration Constants

| Constant                    | Value          | Location              |
|-----------------------------|----------------|-----------------------|
| Redis title cache TTL       | 172800s (48h)  | ProcessSummaries      |
| Title min length (English)  | 26 chars       | ProcessSummaries      |
| Title max length (English)  | 105 chars      | ProcessSummaries      |
| Summary min length (English)| 200 chars      | ProcessSummaries      |
| Summary max length (English)| 360 chars      | ProcessSummaries      |
| Max special characters      | 2 (< 3)       | ProcessSummaries      |
| LLM temperature             | 0              | summarization-async   |
| LLM max retry attempts      | 3              | summarization-async   |
| LLM retry backoff base      | 2 (seconds)    | summarization-async   |
| LLM retry trigger           | HTTP 503       | summarization-async   |
| Default publisher name      | `InsideMedia`  | ProcessSummaries      |
| Default publisher ID        | `000`          | ProcessSummaries      |

## Proxy Service

| Attribute    | Value                                                             |
|--------------|-------------------------------------------------------------------|
| Service Name | `jn-article-render-proxy`                                         |
| Full URL     | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` |
| Project      | `266686822828`                                                    |
| Region       | `asia-south1`                                                     |
| Purpose      | Render and extract article content for LLM consumption            |
| Input        | Query parameter `url` with article URL                            |
| Output       | Rendered article text content                                     |
