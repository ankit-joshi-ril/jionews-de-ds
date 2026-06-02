# Auto Summarization - AS-IS State

## Current State Summary

The Auto Summarization pipeline is a synchronous HTTP API service deployed on Cloud Run. It serves the CMS editorial workflow: when an editor shortlists an article for publication, the CMS sends an HTTP POST with the article's source headline ID and optionally the article URL or content. The service generates a summary using Gemini 2.5 Flash and persists it to MongoDB via an idempotent upsert.

This is the only ingestion-adjacent pipeline that operates on-demand rather than on a schedule.

## Pipeline Flow (Current)

1. **CMS Editor** shortlists an article for publication.
2. **CMS Backend** sends HTTP POST to `/v1/jionews-summarization/summarize` with `source_headline_id` (required) and optionally `article_url` and/or `article_content`.
3. **FastAPI Service** determines the input source:
   - If `article_url` is provided: attempt URL-based summarization via Gemini.
   - If URL summarization fails: fetch content via proxy, then summarize.
   - If `article_content` is provided (no URL): summarize directly from content.
4. **Gemini 2.5 Flash** generates a summary of 350-360 characters.
5. **MongoDB Upsert**: Result is persisted via `find_one_and_update` with upsert by `sourceId`. The `updateCount` field is incremented on each call, allowing tracking of re-summarization attempts.
6. **HTTP Response**: Returns the summary, sourceId, updateCount, and timestamps.

## Known Issues and Technical Debt

### Moderate

| ID   | Issue                                           | Impact                                                     |
|------|-------------------------------------------------|------------------------------------------------------------|
| A-01 | URL failure detection is substring-based        | 7 hardcoded substrings; brittle if Gemini changes wording  |
| A-02 | Proxy timeout hardcoded at 45 seconds           | No configuration; long-running proxy fetches block request  |
| A-03 | No rate limiting on the API endpoint            | CMS could overwhelm the service with concurrent requests   |
| A-04 | LLM temperature 0 with no variation             | Deterministic but may produce repetitive summary styles    |

### Low

| ID   | Issue                                           | Impact                                                     |
|------|-------------------------------------------------|------------------------------------------------------------|
| A-05 | Summary length 350-360 chars is narrow range    | LLM may not consistently hit the 10-char window            |
| A-06 | No retry logic for Gemini API calls             | Differs from summaries-ingestion which has 3 retries       |
| A-07 | processingSource tracking is string-based       | No enum validation; potential for typos                    |

## URL Failure Detection

When Gemini attempts to access an article URL via the `url_context` tool, it may fail and describe the failure in natural language. The service detects these failures by checking for 7 substring patterns in the LLM response:

| Substring Pattern                  | Indicates                                    |
|------------------------------------|----------------------------------------------|
| `"unable to summarize"`            | General summarization failure                |
| `"unable to access"`              | URL access failure                           |
| `"unable to browse"`              | Browse/fetch failure                         |
| `"could not be fetched"`          | Fetch failure                                |
| `"could not be accessed"`         | Access failure                               |
| `"URL did not contain"`           | URL resolved but content was insufficient    |
| `"I am unable to"`               | General inability statement                  |

If any substring is found (case-insensitive) in the Gemini response, the service falls through to proxy-based content fetching.

## Processing Source Tracking

Each MongoDB record includes a `processingSource` field indicating how the summary was generated:

| Value                | Meaning                                                   |
|----------------------|-----------------------------------------------------------|
| `"publisher_url"`    | Gemini accessed the article URL directly via url_context  |
| `"publisher_content"`| Summary generated from article_content provided by CMS   |
| `"proxy_url"`        | Content fetched via proxy, then summarized by Gemini      |

## Comparison with Summaries Ingestion LLM Path

| Aspect                | Auto Summarization              | Summaries Ingestion (LLM async) |
|-----------------------|---------------------------------|----------------------------------|
| Trigger               | CMS HTTP POST (on-demand)       | Pub/Sub (batch, scheduled)       |
| Service type          | FastAPI on Cloud Run            | Cloud Run (event-driven)         |
| LLM Model             | gemini-2.5-flash                | gemini-2.5-flash                 |
| Temperature           | 0                               | 0                                |
| Tools                 | url_context                     | url_context                      |
| Retry on 503          | No                              | Yes (3 attempts, exponential)    |
| JSON parsing stages   | Not applicable (text output)    | 3-stage (direct, strip, extract) |
| Proxy                 | Same proxy service              | Same proxy service               |
| Proxy timeout         | 45 seconds                      | Default                          |
| MongoDB operation     | find_one_and_update (upsert)    | find_one_and_update (upsert)     |
| Update tracking       | $inc updateCount                | No                               |
| Processing source     | Tracked (3 values)              | Not tracked                      |
| Error field           | error_message in MongoDB        | Not persisted                    |
| Summary length target | 350-360 characters              | 200-360 characters (hygiene)     |

## External Service Dependencies

| Service                  | Protocol | Auth       | Timeout | Notes                                |
|--------------------------|----------|------------|---------|--------------------------------------|
| Gemini 2.5 Flash         | HTTPS    | API Key    | Default | LLM summarization                   |
| Article Render Proxy     | HTTPS    | IAM        | 45s     | Content extraction fallback          |
| MongoDB                  | TLS      | URI Secret | Default | Persistence layer                   |
| CMS (Inbound)           | HTTPS    | Service auth| N/A    | Caller, triggers summarization      |

## System Instruction

The Gemini model receives a system instruction defining its role and output constraints. The instruction specifies:
- Act as a news editor/writer.
- Output ONLY a single summary.
- Summary must be between 350 and 360 characters.
