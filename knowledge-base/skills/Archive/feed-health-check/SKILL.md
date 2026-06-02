# Skill: feed-health-check

## Metadata

| Field          | Value                                                              |
|----------------|--------------------------------------------------------------------|
| **Skill ID**   | `feed-health-check`                                                |
| **Version**    | 1.0.0                                                              |
| **Purpose**    | Monitor all active feeds across all pipelines for availability     |
| **Trigger**    | Scheduled (every 30 minutes recommended) or Manual                 |
| **Run Mode**   | Always dry-run. This skill is read-only and never mutates data.    |
| **Mutates**    | Never                                                              |
| **Owner**      | DE-DS Platform Team                                                |

---

## Purpose

This skill monitors the health of all active feed URLs across every ingestion pipeline. It checks feed availability, response time, content validity, and entry freshness. The output enables operators to quickly identify feeds that are down, degraded, or stale before they impact pipeline throughput.

This is a read-only monitoring skill. It performs only HTTP GET requests against feed URLs and reads config CSVs. It never writes to any data store.

---

## Inputs

```json
{
  "pipeline": {
    "type": "string",
    "required": false,
    "description": "Filter to a specific pipeline. If omitted, all pipelines are checked.",
    "enum": ["headlines", "summaries", "native_videos", "native_shorts", "all"],
    "default": "all",
    "example": "headlines"
  },
  "timeout_seconds": {
    "type": "integer",
    "required": false,
    "description": "HTTP timeout in seconds for each feed check.",
    "default": 10,
    "minimum": 3,
    "maximum": 30,
    "example": 10
  }
}
```

---

## Config CSV Sources

The skill reads publisher feed configurations from the following GCS paths (or their local copies):

| Pipeline       | GCS Path                                                          | Key Columns                         |
|----------------|-------------------------------------------------------------------|-------------------------------------|
| Headlines      | `de-raw-ingestion/headlines/headlines_publishers_feeds.csv`       | feed_url, is_active, pub_name       |
| Summaries      | `de-raw-ingestion/summaries/summaries_publishers_feeds.csv`       | feed_url, is_active, pub_name       |
| Native Videos  | `de-raw-ingestion/videos/mrss_videos_feeds.csv`                  | feed_url, is_active, pub_name       |
| Native Shorts  | `de-raw-ingestion/shorts/mrss_shorts_feeds.csv`                  | feed_url, is_active, pub_name       |

---

## Execution Steps

### Step 1: Load Feed Configurations

- Read all config CSVs for the selected pipeline(s).
- If `pipeline` is `"all"` or omitted, read all four CSVs.
- If a specific pipeline is selected, read only that CSV.
- For each CSV:
  - Parse as CSV with headers.
  - Filter rows where `is_active` equals `true` (case-insensitive, also accept `1`, `yes`, `TRUE`).
  - Extract `feed_url`, `pub_name`, `language_name`, `category_name`.
- Record `total_feeds` per pipeline and overall.
- **WARN** if a config CSV cannot be read (GCS access issue or file not found).
- **Skip** rows where `feed_url` is empty or malformed.

### Step 2: Deduplicate Feed URLs

- Some feeds may appear in multiple pipelines. Deduplicate by URL.
- Track which pipelines each URL belongs to.
- Record `unique_feed_urls` count.

### Step 3: Check Each Feed (Parallel Execution)

Execute feed checks in parallel using a thread pool with a maximum of **50 concurrent threads**.

For each unique feed URL:

#### 3a. HTTP GET Request

- Perform HTTP GET with the specified timeout.
- Follow redirects (up to 3 hops).
- Record:
  - `status_code`: HTTP response status.
  - `response_time_ms`: Time from request initiation to full response.
  - `content_length`: From header or measured from body.
  - `content_type`: Response Content-Type header.
  - `redirect_count`: Number of redirects followed.
  - `final_url`: The URL after all redirects.
  - `error`: If the request failed, the error message (timeout, DNS failure, connection refused, SSL error).

#### 3b. Parse Response

If the request succeeded (HTTP 2xx):
- Detect format (XML or JSON) using the same logic as onboarding skills.
- Parse the feed and count entries.
- Record `entry_count`.

#### 3c. Check Freshness

If entries were parsed:
- Extract the published date from each entry.
- Find the most recent entry.
- Calculate `newest_entry_age_hours` (hours since the newest entry was published).

### Step 4: Categorize Feed Health

Classify each feed into one of three states:

| State       | Criteria                                                                              |
|-------------|---------------------------------------------------------------------------------------|
| `healthy`   | HTTP 200 AND entry_count > 0 AND newest_entry_age_hours <= 24 AND response_time_ms < 5000 |
| `degraded`  | HTTP 200 BUT (entry_count == 0 OR newest_entry_age_hours > 24 OR response_time_ms >= 5000) |
| `failed`    | HTTP non-200 OR timeout OR DNS failure OR connection error                             |

Additional sub-classifications for degraded feeds:
- `degraded_slow`: HTTP 200 but response_time_ms >= 5000.
- `degraded_stale`: HTTP 200 and entries present but newest_entry_age_hours > 24.
- `degraded_empty`: HTTP 200 but entry_count == 0.

### Step 5: Aggregate Results

Per pipeline:
- Count: `total_feeds`, `healthy`, `degraded`, `failed`.
- Calculate: `health_rate_percent` = (healthy / total_feeds) * 100.
- Calculate: `avg_response_time_ms` across all feeds in the pipeline.
- Calculate: `p95_response_time_ms` (95th percentile response time).

Overall:
- Same aggregations across all pipelines combined.
- Identify the top 10 slowest feeds.
- Identify all failed feeds (sorted by publisher name).

---

## Confidence Score Calculation

| Condition                                         | Points |
|---------------------------------------------------|--------|
| All config CSVs loaded successfully               | +20    |
| >= 95% of feeds responded with HTTP 200           | +20    |
| >= 90% of feeds have entries                      | +15    |
| >= 80% of feeds have entries within last 24 hours | +15    |
| Average response time < 3 seconds                 | +10    |
| P95 response time < 10 seconds                    | +10    |
| No DNS failures or connection errors              | +10    |
| **Total possible**                                | **100**|

Deductions:
- Each config CSV that fails to load: -10 points
- Each percentage point of feeds below 95% HTTP 200 rate: -1 point
- Each failed feed: -2 points (capped at -20)
- Average response time > 5 seconds: -10 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "feed-health-check",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {
    "pipeline": "all",
    "timeout_seconds": 10
  },
  "output": {
    "overall": {
      "total_feeds": 320,
      "unique_feed_urls": 285,
      "healthy": 260,
      "degraded": 15,
      "failed": 10,
      "health_rate_percent": 91.2,
      "avg_response_time_ms": 1250,
      "p95_response_time_ms": 4800
    },
    "pipelines": {
      "headlines": {
        "total_feeds": 180,
        "healthy": 165,
        "degraded": 10,
        "failed": 5,
        "health_rate_percent": 91.7,
        "avg_response_time_ms": 980,
        "feeds": [
          {
            "feed_url": "https://example.com/rss/news.xml",
            "pub_name": "Example Publisher",
            "status": "healthy",
            "status_code": 200,
            "response_time_ms": 450,
            "entry_count": 25,
            "newest_entry_age_hours": 1.2
          },
          {
            "feed_url": "https://broken.com/feed.xml",
            "pub_name": "Broken Publisher",
            "status": "failed",
            "status_code": null,
            "response_time_ms": null,
            "entry_count": null,
            "newest_entry_age_hours": null,
            "error": "ConnectionTimeout: 10s exceeded"
          }
        ]
      },
      "summaries": { "...": "same structure" },
      "native_videos": { "...": "same structure" },
      "native_shorts": { "...": "same structure" }
    },
    "top_10_slowest_feeds": [
      {
        "feed_url": "https://slow.example.com/rss",
        "pub_name": "Slow Publisher",
        "pipeline": "headlines",
        "response_time_ms": 9200
      }
    ],
    "all_failed_feeds": [
      {
        "feed_url": "https://broken.com/feed.xml",
        "pub_name": "Broken Publisher",
        "pipeline": "headlines",
        "error": "ConnectionTimeout: 10s exceeded"
      }
    ]
  },
  "validation_status": "warning",
  "confidence_score": 78,
  "issues": [
    "10 feeds are completely unreachable.",
    "5 feeds returned HTTP 200 but contain no entries.",
    "10 feeds have not published new content in over 24 hours."
  ],
  "recommendations": [
    "Contact Broken Publisher regarding feed URL https://broken.com/feed.xml - connection timeout.",
    "Investigate Slow Publisher feed - 9.2s response time may indicate server issues.",
    "Review 10 stale feeds for possible publisher discontinuation."
  ],
  "alerts": [
    {
      "level": "CRITICAL",
      "message": "3 feeds have been failing for consecutive checks. Consider marking as inactive.",
      "feeds": ["https://dead1.com/rss", "https://dead2.com/rss", "https://dead3.com/rss"]
    }
  ]
}
```

---

## Dry-Run Behavior

This skill is **always read-only**. The `--execute` flag has no additional effect. The skill:

- Reads config CSVs (read-only).
- Performs HTTP GET requests to feed URLs (read-only).
- Parses feed responses (in-memory only).
- Produces a JSON report.
- **Never** modifies config CSVs, feed URLs, database records, or any other persistent state.

---

## Error Handling

| Error Condition                           | Behavior                                                      |
|-------------------------------------------|---------------------------------------------------------------|
| Config CSV not found or unreadable        | Skip that pipeline, add to issues, reduce confidence          |
| Individual feed timeout                   | Mark as failed, record error, continue with other feeds       |
| Individual feed DNS failure               | Mark as failed, record error, continue with other feeds       |
| Individual feed SSL error                 | Mark as failed, record error, continue with other feeds       |
| Feed returns non-feed content (HTML)      | Mark as degraded_empty, note content_type mismatch            |
| Feed parsing fails (malformed XML/JSON)   | Mark as degraded_empty, record parse error                    |
| Thread pool exhaustion                    | Queue remaining feeds, extend execution time                  |

---

## Alerting Thresholds

| Condition                                          | Alert Level |
|----------------------------------------------------|-------------|
| Any feed fails that was healthy in the prior check | WARNING     |
| > 5% of feeds are in failed state                  | WARNING     |
| > 10% of feeds are in failed state                 | CRITICAL    |
| > 20% of feeds are stale (> 24h)                   | WARNING     |
| Average response time > 5 seconds                  | WARNING     |
| A config CSV cannot be loaded                      | CRITICAL    |
| Total feeds found is 0 (config issue)              | CRITICAL    |
