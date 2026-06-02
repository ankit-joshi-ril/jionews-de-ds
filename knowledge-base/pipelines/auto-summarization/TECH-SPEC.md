# Auto Summarization - Technical Specification

## Overview

This document provides implementation-level technical details for the Auto Summarization pipeline, including the FastAPI service implementation, Gemini LLM integration, URL failure detection, proxy fallback, and MongoDB upsert logic.

## Runtime Environment

| Attribute        | Value                          |
|------------------|--------------------------------|
| Runtime          | Python 3.x                     |
| Framework        | FastAPI                        |
| GCP Project      | `jiox-328108` (266686822828)   |
| Region           | `asia-south1`                  |
| Deployment       | Cloud Run (container)          |

## API Specification

### Route Definition

| Attribute    | Value                                        |
|--------------|----------------------------------------------|
| Method       | POST                                         |
| Path         | `/v1/jionews-summarization/summarize`        |
| Content-Type | `application/json`                           |
| Response     | `application/json`                           |

### Request Model

```python
from pydantic import BaseModel
from typing import Optional

class SummarizationRequest(BaseModel):
    article_content: Optional[str] = None
    article_url: Optional[str] = None
    source_headline_id: str  # Required
    prompt: Optional[str] = None
    model: Optional[str] = "gemini-2.5-flash"
```

### Response Model

```python
class SummarizationResponse(BaseModel):
    sourceId: str
    summary: str
    updateCount: int
    createdAt: int
    updatedAt: int
```

## LLM Integration

### Gemini Configuration

```python
import google.generativeai as genai

genai.configure(api_key=secret("GEMINI_API_KEY"))

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={"temperature": 0},
    tools=[{"url_context": {}}],
    system_instruction=(
        "You act as a news editor/writer. "
        "Your task is to output ONLY a single summary "
        "between 350 and 360 characters."
    )
)
```

### URL Mode Summarization

```python
def summarize_from_url(article_url: str, model) -> tuple[str, bool]:
    """
    Attempt to summarize an article by URL using url_context tool.
    Returns (summary_text, success_flag).
    """
    response = model.generate_content(
        f"Summarize the article at: {article_url}"
    )

    summary = response.text

    # Check for failure substrings
    if is_url_failure(summary):
        return summary, False

    return summary, True
```

### URL Failure Detection

```python
FAILURE_SUBSTRINGS = [
    "unable to summarize",
    "unable to access",
    "unable to browse",
    "could not be fetched",
    "could not be accessed",
    "URL did not contain",
    "I am unable to",
]

def is_url_failure(response_text: str) -> bool:
    """
    Check if the LLM response indicates a URL access failure.
    Case-insensitive substring matching.
    """
    lower_text = response_text.lower()
    return any(
        substring.lower() in lower_text
        for substring in FAILURE_SUBSTRINGS
    )
```

### Proxy Content Fetching

```python
import requests

PROXY_URL = (
    "https://jn-article-render-proxy-266686822828"
    ".asia-south1.run.app/proxy"
)
PROXY_TIMEOUT = 45  # seconds

def fetch_content_via_proxy(article_url: str) -> str:
    """Fetch rendered article content via the proxy service."""
    response = requests.get(
        PROXY_URL,
        params={"url": article_url},
        timeout=PROXY_TIMEOUT
    )
    response.raise_for_status()
    return response.text
```

### Content Mode Summarization

```python
def summarize_from_content(content: str, model) -> str:
    """Summarize article from pre-fetched content."""
    response = model.generate_content(
        f"Summarize the following article:\n\n{content}"
    )
    return response.text
```

## Main Service Logic

```python
from fastapi import FastAPI, HTTPException
from pymongo import MongoClient, ReturnDocument
import time

app = FastAPI()

@app.post("/v1/jionews-summarization/summarize")
def summarize(request: SummarizationRequest):
    """Main summarization endpoint."""

    source_id = request.source_headline_id
    summary = None
    processing_source = None
    error_message = None

    # Configure model (use request model or default)
    model_name = request.model or "gemini-2.5-flash"
    model = configure_model(model_name, request.prompt)

    try:
        if request.article_url:
            # Strategy 1: URL mode first
            summary, url_success = summarize_from_url(
                request.article_url, model
            )

            if url_success:
                processing_source = "publisher_url"
            else:
                # Fallback: fetch content via proxy
                try:
                    content = fetch_content_via_proxy(request.article_url)
                    summary = summarize_from_content(content, model)
                    processing_source = "proxy_url"
                except Exception as proxy_error:
                    error_message = str(proxy_error)
                    processing_source = "proxy_url"

        elif request.article_content:
            # Strategy 2: Direct content mode
            summary = summarize_from_content(
                request.article_content, model
            )
            processing_source = "publisher_content"

        else:
            raise HTTPException(
                status_code=400,
                detail="Either article_url or article_content is required"
            )

    except Exception as e:
        error_message = str(e)

    # MongoDB upsert
    result = upsert_summary(
        source_id=source_id,
        article_content=request.article_content,
        article_url=request.article_url,
        summary=summary,
        processing_source=processing_source,
        model=model_name,
        error_message=error_message
    )

    return SummarizationResponse(
        sourceId=result["sourceId"],
        summary=result.get("summary", ""),
        updateCount=result.get("updateCount", 1),
        createdAt=result.get("createdAt", 0),
        updatedAt=result.get("updatedAt", 0)
    )
```

## MongoDB Upsert Implementation

```python
def upsert_summary(
    source_id: str,
    article_content: str,
    article_url: str,
    summary: str,
    processing_source: str,
    model: str,
    error_message: str
):
    """
    Upsert summarization result to MongoDB.
    Uses find_one_and_update with upsert=True.
    Increments updateCount on each call.
    """
    client = MongoClient(secret("mongosh_de_uri"))
    db = client["ingestion-data"]
    collection = db["auto_summarization"]

    now = int(time.time())

    result = collection.find_one_and_update(
        filter={"sourceId": source_id},
        update={
            "$set": {
                "articleContent": article_content,
                "articleUrl": article_url,
                "summary": summary,
                "processingSource": processing_source,
                "model": model,
                "error_message": error_message,
                "updatedAt": now
            },
            "$setOnInsert": {
                "createdAt": now,
                "sourceId": source_id
            },
            "$inc": {
                "updateCount": 1
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    return result
```

## Key Libraries

| Library                | Purpose                                       |
|------------------------|-----------------------------------------------|
| `fastapi`              | HTTP API framework                            |
| `pydantic`             | Request/response model validation             |
| `uvicorn`              | ASGI server for FastAPI                       |
| `google-generativeai`  | Gemini API client (LLM summarization)         |
| `pymongo`              | MongoDB client                                |
| `requests`             | HTTP client for proxy calls                   |

## Error Handling

| Stage                | Error Type              | Handling                                      |
|----------------------|-------------------------|-----------------------------------------------|
| Request Validation   | Missing required field  | HTTP 422 (FastAPI automatic validation)       |
| Request Validation   | No URL or content       | HTTP 400 (explicit check)                     |
| Gemini URL Mode      | url_context failure     | Detected via substring matching; fall to proxy|
| Gemini URL Mode      | API error               | Caught; error_message set in MongoDB          |
| Proxy Fetch          | Timeout (45s)           | Caught; error_message set in MongoDB          |
| Proxy Fetch          | HTTP error              | Caught; error_message set in MongoDB          |
| Gemini Content Mode  | API error               | Caught; error_message set in MongoDB          |
| MongoDB Upsert       | Connection error        | Uncaught; HTTP 500                            |

## Secrets Management

| Secret Name      | Storage                   | Accessed By          |
|------------------|---------------------------|----------------------|
| `GEMINI_API_KEY` | GCP Secret Manager        | FastAPI service      |
| `mongosh_de_uri` | GCP Secret Manager        | FastAPI service      |

## Configuration Constants

| Constant                        | Value                  | Description                                  |
|---------------------------------|------------------------|----------------------------------------------|
| API route                       | `/v1/jionews-summarization/summarize` | POST endpoint path            |
| Default LLM model               | `gemini-2.5-flash`    | Overridable via request `model` field        |
| LLM temperature                 | `0`                   | Deterministic output                         |
| LLM tools                       | `url_context`         | Enables URL access for Gemini                |
| Summary target length            | 350-360 characters   | Specified in system instruction              |
| Proxy timeout                    | 45 seconds           | Timeout for proxy content fetch              |
| Proxy URL                        | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` | Content proxy |
| Failure substring count          | 7                    | Number of URL failure detection patterns     |

## Deployment Configuration

| Attribute         | Value                     |
|-------------------|---------------------------|
| Container runtime | Python 3.x + FastAPI      |
| ASGI server       | Uvicorn                   |
| Cloud Run scaling | Auto (min 0, configurable)|
| Region            | `asia-south1`             |
| Ingress           | Internal + Cloud Load Balancing (CMS access) |
| Secrets           | Mounted via Secret Manager|
