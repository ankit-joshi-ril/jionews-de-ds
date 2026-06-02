# Auto Summarization Pipeline

## Overview

The Auto Summarization pipeline is an on-demand LLM-based summarization service triggered by the CMS editorial workflow. When an editor shortlists an article in the CMS, the system sends an HTTP POST request to this service, which generates a summary using Gemini 2.5 Flash and persists the result to MongoDB. It operates as a single FastAPI service deployed on Cloud Run.

## Pipeline Identity

| Attribute             | Value                                                    |
|-----------------------|----------------------------------------------------------|
| Pipeline Name         | Auto Summarization                                       |
| GCP Project           | `jiox-328108`                                            |
| GCP Project Number    | `266686822828`                                           |
| Region                | `asia-south1`                                            |
| Trigger               | HTTP POST (CMS editorial shortlist action)               |
| Pipeline Type         | Single-service synchronous API                           |
| Service Type          | FastAPI on Cloud Run                                     |
| API Route             | `POST /v1/jionews-summarization/summarize`               |
| Primary Database      | MongoDB (`ingestion-data.auto_summarization`)            |
| LLM Model             | Gemini 2.5 Flash                                         |

## Service Architecture

```
CMS Editorial Shortlist
    |
    v (HTTP POST)
FastAPI Service (Cloud Run)
    |
    ├── Gemini 2.5 Flash (URL mode with url_context tool)
    |       |
    |       └── Fallback: Proxy → Gemini (content mode)
    |
    └── MongoDB upsert (by sourceId)
```

## External Dependencies

| Dependency         | Type        | Endpoint                                                     |
|--------------------|-------------|--------------------------------------------------------------|
| Gemini 2.5 Flash   | HTTPS       | Google Generative AI API                                     |
| Article Proxy      | HTTPS       | `https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy` |
| CMS (Caller)      | HTTP POST   | Inbound from CMS                                             |

## Secrets

| Secret Name        | Purpose                   |
|--------------------|---------------------------|
| `GEMINI_API_KEY`   | Gemini LLM API key        |
| `mongosh_de_uri`   | MongoDB connection string |

## Key Business Rules

1. **On-Demand**: Not scheduled; triggered by CMS editorial action.
2. **Two-Pass LLM**: URL mode first (Gemini accesses article URL directly), content fallback via proxy.
3. **URL Failure Detection**: 7 substring patterns to detect when Gemini cannot access a URL.
4. **Summary Length**: System instruction requests 350-360 characters.
5. **Idempotent Upsert**: MongoDB `find_one_and_update` with upsert by `sourceId`; `updateCount` increments on each call.
6. **Processing Source Tracking**: Records whether summary was generated from `publisher_url`, `publisher_content`, or `proxy_url`.
7. **Proxy Timeout**: 45-second timeout for content fetching via proxy.

## Related Documentation

- [AS-IS.md](./AS-IS.md) - Current state analysis and known issues
- [DATA-SPEC.md](./DATA-SPEC.md) - Data schemas, field definitions, transformations
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture with Mermaid diagrams
- [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) - MongoDB collection schema
- [TECH-SPEC.md](./TECH-SPEC.md) - Technical implementation details
