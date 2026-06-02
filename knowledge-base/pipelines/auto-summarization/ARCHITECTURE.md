# Auto Summarization - Architecture

## Overview

The Auto Summarization pipeline is a single FastAPI service deployed on Cloud Run. Unlike the other ingestion pipelines (which are multi-function Pub/Sub chains), this is a synchronous request-response API triggered by the CMS editorial workflow. It uses Gemini 2.5 Flash for LLM-based summarization with a two-pass strategy (URL mode first, proxy content fallback).

## System Context Diagram

```mermaid
flowchart TB
    subgraph External["External Systems"]
        CMS[CMS Editorial System]
        Gemini[Gemini 2.5 Flash<br/>LLM API]
    end

    subgraph GCP["GCP - jiox-328108"]
        subgraph CloudRun["Cloud Run"]
            API["FastAPI Service<br/>POST /v1/jionews-summarization/summarize"]
            Proxy["jn-article-render-proxy"]
        end

        subgraph Storage["Storage"]
            MongoDB[(MongoDB<br/>ingestion-data<br/>.auto_summarization)]
        end

        subgraph Secrets["Secret Manager"]
            SK1[GEMINI_API_KEY]
            SK2[mongosh_de_uri]
        end
    end

    CMS -->|"HTTP POST<br/>source_headline_id<br/>article_url / content"| API
    API -->|"URL mode<br/>url_context tool"| Gemini
    API -->|"Content fetch<br/>45s timeout"| Proxy
    Proxy -->|"Rendered content"| API
    API -->|"Content mode"| Gemini
    Gemini -->|"Summary text"| API
    API -->|"find_one_and_update<br/>upsert by sourceId"| MongoDB
    API -->|"Summary response"| CMS
    API -.->|Read| SK1
    API -.->|Read| SK2
```

## Request Processing Sequence Diagram

```mermaid
sequenceDiagram
    participant CMS as CMS Editor
    participant API as FastAPI (Cloud Run)
    participant Gemini as Gemini 2.5 Flash
    participant Proxy as Article Render Proxy
    participant Mongo as MongoDB

    CMS->>API: POST /v1/jionews-summarization/summarize<br/>{source_headline_id, article_url?, article_content?}

    alt article_url provided
        Note over API: Strategy: URL Mode First

        API->>Gemini: Generate summary from URL<br/>(url_context tool enabled)
        Gemini-->>API: Summary response text

        API->>API: Check for failure substrings

        alt No failure substrings found
            Note over API: processingSource = "publisher_url"
        else Failure substring detected
            Note over API: URL mode failed, try proxy

            API->>Proxy: GET /proxy?url={article_url}<br/>(45s timeout)
            Proxy-->>API: Rendered article content

            API->>Gemini: Generate summary from content
            Gemini-->>API: Summary response text
            Note over API: processingSource = "proxy_url"
        end

    else article_content provided (no URL)
        Note over API: Strategy: Direct Content Mode

        API->>Gemini: Generate summary from content
        Gemini-->>API: Summary response text
        Note over API: processingSource = "publisher_content"

    else Neither provided
        API-->>CMS: Error: insufficient input
    end

    API->>Mongo: find_one_and_update<br/>filter: {sourceId}<br/>$set: {summary, processingSource, ...}<br/>$setOnInsert: {createdAt, sourceId}<br/>$inc: {updateCount: 1}
    Mongo-->>API: Updated document

    API-->>CMS: {sourceId, summary, updateCount, createdAt, updatedAt}
```

## URL Failure Detection Flow

```mermaid
flowchart TD
    RESP[Gemini URL Mode Response]
    CHECK{Contains any<br/>failure substring?}

    SUB1["'unable to summarize'"]
    SUB2["'unable to access'"]
    SUB3["'unable to browse'"]
    SUB4["'could not be fetched'"]
    SUB5["'could not be accessed'"]
    SUB6["'URL did not contain'"]
    SUB7["'I am unable to'"]

    SUCCESS[URL Mode Success<br/>processingSource = publisher_url]
    FALLBACK[Trigger Proxy Fallback<br/>processingSource = proxy_url]

    RESP --> CHECK
    CHECK -->|"Matches any of:"| FALLBACK
    CHECK -->|"No matches"| SUCCESS

    SUB1 -.-> CHECK
    SUB2 -.-> CHECK
    SUB3 -.-> CHECK
    SUB4 -.-> CHECK
    SUB5 -.-> CHECK
    SUB6 -.-> CHECK
    SUB7 -.-> CHECK
```

## Processing Source Decision Flow

```mermaid
flowchart TD
    INPUT[API Request]
    HAS_URL{article_url<br/>provided?}
    URL_MODE[Gemini URL Mode]
    URL_OK{URL mode<br/>succeeded?}
    HAS_CONTENT{article_content<br/>provided?}
    CONTENT_MODE[Gemini Content Mode<br/>from article_content]
    PROXY_FETCH[Proxy Content Fetch<br/>45s timeout]
    PROXY_MODE[Gemini Content Mode<br/>from proxy content]
    ERR[Error Response]

    PUB_URL["processingSource =<br/>'publisher_url'"]
    PUB_CONTENT["processingSource =<br/>'publisher_content'"]
    PROXY_SRC["processingSource =<br/>'proxy_url'"]

    INPUT --> HAS_URL
    HAS_URL -->|Yes| URL_MODE
    HAS_URL -->|No| HAS_CONTENT
    URL_MODE --> URL_OK
    URL_OK -->|Yes| PUB_URL
    URL_OK -->|No| PROXY_FETCH
    PROXY_FETCH --> PROXY_MODE
    PROXY_MODE --> PROXY_SRC
    HAS_CONTENT -->|Yes| CONTENT_MODE
    HAS_CONTENT -->|No| ERR
    CONTENT_MODE --> PUB_CONTENT
```

## MongoDB Upsert Flow

```mermaid
sequenceDiagram
    participant API as FastAPI Service
    participant Mongo as MongoDB

    API->>Mongo: find_one_and_update(filter, update, upsert=True)

    alt Document exists (sourceId found)
        Note over Mongo: $set: update summary, processingSource,<br/>model, error_message, updatedAt
        Note over Mongo: $setOnInsert: IGNORED (doc exists)
        Note over Mongo: $inc: updateCount += 1
        Mongo-->>API: Updated document
    else Document does not exist (new sourceId)
        Note over Mongo: $set: set summary, processingSource,<br/>model, error_message, updatedAt
        Note over Mongo: $setOnInsert: set createdAt, sourceId
        Note over Mongo: $inc: updateCount = 1
        Mongo-->>API: Newly inserted document
    end
```

## Infrastructure Summary

| Component              | GCP Service        | Configuration                        |
|------------------------|--------------------|--------------------------------------|
| FastAPI Service        | Cloud Run          | Single container, auto-scaling       |
| Article Render Proxy   | Cloud Run          | Internal service, 45s timeout        |
| Persistence            | MongoDB Atlas      | `ingestion-data.auto_summarization`  |
| LLM                    | Gemini API         | gemini-2.5-flash, temp 0             |
| Secrets                | Secret Manager     | GEMINI_API_KEY, mongosh_de_uri       |

## Comparison: Pipeline Architecture Patterns

```mermaid
flowchart LR
    subgraph Headlines["Headlines: Pub/Sub Chain"]
        direction LR
        H1[Fetch] --> H2[Process] --> H3[ImageCDN]
        H3 --> H4[MongoDB]
        H3 --> H5[Rejected]
    end

    subgraph Summaries["Summaries: Pub/Sub + Cloud Run"]
        direction LR
        S1[Fetch] --> S2[Process]
        S2 --> S3[ImageCDN] --> S4[MongoDB]
        S2 --> S5[LLM Cloud Run]
    end

    subgraph Webstories["Webstories: Minimal Chain"]
        direction LR
        W1[Fetch+Process] --> W2[MongoDB]
    end

    subgraph AutoSum["Auto Summarization: Single API"]
        direction LR
        A1["POST API<br/>→ LLM<br/>→ MongoDB"]
    end
```

## Network and Security

| Connection                | Protocol | Authentication                |
|---------------------------|----------|-------------------------------|
| CMS -> Cloud Run          | HTTPS    | Service auth (IAM / token)    |
| Cloud Run -> Gemini       | HTTPS    | API Key (Secret Manager)      |
| Cloud Run -> Proxy        | HTTPS    | IAM (Cloud Run to Cloud Run)  |
| Cloud Run -> MongoDB      | TLS      | URI with credentials (Secret) |
