# Skill: pipeline-execution-monitor

## Metadata

| Field          | Value                                                              |
|----------------|--------------------------------------------------------------------|
| **Skill ID**   | `pipeline-execution-monitor`                                       |
| **Version**    | 1.0.0                                                              |
| **Purpose**    | Check pipeline run status and data flow across all pipelines       |
| **Trigger**    | Scheduled (every 15 minutes recommended) or Manual                 |
| **Run Mode**   | Always dry-run. This skill is read-only and never mutates data.    |
| **Mutates**    | Never                                                              |
| **Owner**      | DE-DS Platform Team                                                |

---

## Purpose

This skill provides a unified view of all pipeline execution health by examining recent data flow in MongoDB. It detects zero-ingest periods, throughput anomalies, and error patterns that indicate pipeline failures or degradation. It serves as the first-line health check for the entire DE-DS ingestion system.

This is a read-only monitoring skill. It queries MongoDB collections and produces a report. It never writes to any data store.

---

## Inputs

```json
{
  "hours_back": {
    "type": "integer",
    "required": false,
    "description": "Number of hours to look back for pipeline activity.",
    "default": 6,
    "minimum": 1,
    "maximum": 72,
    "example": 6
  }
}
```

---

## Pipeline-to-Collection Mapping

| Pipeline         | MongoDB Collection                        | Filter Criteria                         |
|------------------|-------------------------------------------|-----------------------------------------|
| Headlines        | `raw_headlines_ingestion_data`            | None (all documents)                    |
| Summaries        | `raw_summaries_insgestion_data`           | None (all documents)                    |
| YouTube Videos   | `raw_videos_ingestion_data`               | None (all documents)                    |
| Native Videos    | `raw_videos_rss`                          | `contentType == "videos"`               |
| Native Shorts    | `raw_videos_rss`                          | `contentType == "shorts"`               |
| YouTube Shorts   | `raw_short_videos_ingestion_data`         | None (all documents)                    |
| Web Stories      | `raw_web_stories_ingestion_data`          | None (all documents)                    |

All collections are in the `ingestion-data` database.

---

## Execution Steps

### Step 1: Query Document Counts Per Pipeline

For each pipeline in the mapping above:

- Connect to MongoDB database `ingestion-data`.
- Query the corresponding collection.
- Apply filter criteria (if any, e.g., `contentType` for native videos/shorts).
- Filter by time: `createdAt >= (now - hours_back)`.
- Count total documents inserted in the time window.
- Record `documents_last_Nh` (where N is `hours_back`).
- Also query for the **most recent document** (sort by `createdAt` descending, limit 1).
- Record `last_ingest_time` as the `createdAt` value of the most recent document.
- Calculate `minutes_since_last_ingest`.

### Step 2: Detect Zero-Ingest Periods

For each pipeline, determine if there are gaps in data flow:

- Divide the `hours_back` window into 1-hour buckets.
- For each bucket, count documents with `createdAt` in that hour.
- Identify any bucket with 0 documents as a **zero-ingest period**.
- Record the list of zero-ingest periods per pipeline.

Classification:
- **Healthy**: No zero-ingest periods, `minutes_since_last_ingest < 30`.
- **Warning**: 1-2 zero-ingest periods, or `minutes_since_last_ingest` between 30-60 minutes.
- **Critical**: 3+ zero-ingest periods, or `minutes_since_last_ingest > 60` minutes.

Exception handling:
- Some pipelines (e.g., Web Stories) may have naturally lower throughput. Apply pipeline-specific thresholds (defined below in Pipeline Thresholds).

### Step 3: Check Error Patterns in Rejection Collections

For each pipeline, check for associated rejection or error collections:

| Pipeline         | Rejection Source                                                   |
|------------------|--------------------------------------------------------------------|
| Headlines        | Documents with `status == "rejected"` or separate rejection topic  |
| Summaries        | Hygiene failures (cross-reference `summaries-hygiene-monitor`)     |
| YouTube Videos   | Documents with processing errors                                   |
| Native Videos    | `raw_videos_rss` where `transcoderProcessingStatus == "failed"`    |
| Native Shorts    | `raw_videos_rss` where `transcoderProcessingStatus == "failed"` and `contentType == "shorts"` |
| YouTube Shorts   | Documents with processing errors                                   |
| Web Stories      | Documents with `status == "rejected"` or processing errors         |

For each pipeline:
- Count rejection/error documents in the time window.
- Calculate `error_rate_percent = (errors / total_documents) * 100`.
- Extract the top 5 most common error messages/reasons.

### Step 4: Compare Current Throughput with Historical Averages

For each pipeline:
- Calculate `current_throughput_per_hour = documents_last_Nh / hours_back`.
- If historical data is available (from previous skill runs or a metrics store):
  - Compare with the 7-day average throughput for the same time-of-day window.
  - Calculate `throughput_delta_percent = ((current - historical) / historical) * 100`.
  - **WARN** if throughput is down by more than 30%.
  - **CRITICAL** if throughput is down by more than 60%.
- If historical data is not available:
  - Record `historical_comparison: "unavailable"`.

### Step 5: Determine Overall Pipeline Status

For each pipeline, assign a status based on all checks:

| Status     | Criteria                                                                              |
|------------|---------------------------------------------------------------------------------------|
| `healthy`  | Documents flowing, no zero-ingest periods, error rate < 5%, throughput within norms   |
| `warning`  | Minor issues: 1-2 zero-ingest periods, error rate 5-15%, throughput down 30-60%       |
| `critical` | Pipeline likely down: 3+ zero-ingest periods, error rate > 15%, throughput down > 60%, or no data at all |

---

## Pipeline Thresholds

Different pipelines have different expected throughput levels. These thresholds govern alerting sensitivity:

| Pipeline         | Expected Docs/Hour (minimum) | Max Acceptable Gap (minutes) |
|------------------|------------------------------|------------------------------|
| Headlines        | 500                          | 30                           |
| Summaries        | 200                          | 30                           |
| YouTube Videos   | 50                           | 60                           |
| Native Videos    | 20                           | 120                          |
| Native Shorts    | 20                           | 120                          |
| YouTube Shorts   | 30                           | 60                           |
| Web Stories      | 10                           | 180                          |

These thresholds are configurable. If the actual throughput or gap exceeds these values, the corresponding alert is triggered.

---

## Confidence Score Calculation

| Condition                                              | Points |
|--------------------------------------------------------|--------|
| MongoDB connection successful                          | +20    |
| All 7 pipeline collections are queryable               | +15    |
| All pipelines have documents in the time window        | +15    |
| No pipeline has zero-ingest period > 2 hours           | +15    |
| All error rates < 5%                                   | +10    |
| Historical comparison data available                   | +10    |
| All pipelines have throughput within 30% of average    | +15    |
| **Total possible**                                     | **100**|

Deductions:
- MongoDB connection failure: confidence = 0, status = failed
- Each pipeline with 0 documents: -10 points
- Each pipeline with error rate > 15%: -5 points
- Any pipeline with status = critical: -10 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "pipeline-execution-monitor",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {
    "hours_back": 6
  },
  "output": {
    "time_window": {
      "from": "2026-03-10T06:00:00Z",
      "to": "2026-03-10T12:00:00Z",
      "hours": 6
    },
    "pipelines": [
      {
        "name": "headlines",
        "collection": "raw_headlines_ingestion_data",
        "documents_last_6h": 4500,
        "last_ingest_time": "2026-03-10T11:58:23Z",
        "minutes_since_last_ingest": 2,
        "throughput_per_hour": 750,
        "zero_ingest_periods": [],
        "error_count": 45,
        "error_rate_percent": 1.0,
        "top_errors": [
          {"reason": "duplicate_url", "count": 30},
          {"reason": "invalid_thumbnail", "count": 15}
        ],
        "historical_comparison": {
          "seven_day_avg_throughput_per_hour": 720,
          "throughput_delta_percent": 4.2,
          "trend": "stable"
        },
        "status": "healthy"
      },
      {
        "name": "summaries",
        "collection": "raw_summaries_insgestion_data",
        "documents_last_6h": 1800,
        "last_ingest_time": "2026-03-10T11:55:10Z",
        "minutes_since_last_ingest": 5,
        "throughput_per_hour": 300,
        "zero_ingest_periods": [],
        "error_count": 120,
        "error_rate_percent": 6.7,
        "top_errors": [
          {"reason": "hygiene_failed_html", "count": 80},
          {"reason": "hygiene_failed_title_short", "count": 40}
        ],
        "historical_comparison": {
          "seven_day_avg_throughput_per_hour": 310,
          "throughput_delta_percent": -3.2,
          "trend": "stable"
        },
        "status": "warning"
      },
      {
        "name": "youtube_videos",
        "collection": "raw_videos_ingestion_data",
        "documents_last_6h": 420,
        "last_ingest_time": "2026-03-10T11:50:00Z",
        "minutes_since_last_ingest": 10,
        "throughput_per_hour": 70,
        "zero_ingest_periods": [],
        "error_count": 5,
        "error_rate_percent": 1.2,
        "top_errors": [],
        "historical_comparison": {
          "seven_day_avg_throughput_per_hour": 65,
          "throughput_delta_percent": 7.7,
          "trend": "stable"
        },
        "status": "healthy"
      },
      {
        "name": "native_videos",
        "collection": "raw_videos_rss",
        "filter": "contentType=videos",
        "documents_last_6h": 0,
        "last_ingest_time": "2026-03-10T04:30:00Z",
        "minutes_since_last_ingest": 450,
        "throughput_per_hour": 0,
        "zero_ingest_periods": ["06:00-07:00", "07:00-08:00", "08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00"],
        "error_count": 0,
        "error_rate_percent": 0,
        "top_errors": [],
        "historical_comparison": {
          "seven_day_avg_throughput_per_hour": 25,
          "throughput_delta_percent": -100,
          "trend": "stopped"
        },
        "status": "critical"
      },
      {
        "name": "native_shorts",
        "collection": "raw_videos_rss",
        "filter": "contentType=shorts",
        "documents_last_6h": 150,
        "last_ingest_time": "2026-03-10T11:45:00Z",
        "minutes_since_last_ingest": 15,
        "throughput_per_hour": 25,
        "zero_ingest_periods": [],
        "error_count": 3,
        "error_rate_percent": 2.0,
        "top_errors": [],
        "historical_comparison": "unavailable",
        "status": "healthy"
      },
      {
        "name": "youtube_shorts",
        "collection": "raw_short_videos_ingestion_data",
        "documents_last_6h": 240,
        "last_ingest_time": "2026-03-10T11:52:00Z",
        "minutes_since_last_ingest": 8,
        "throughput_per_hour": 40,
        "zero_ingest_periods": [],
        "error_count": 8,
        "error_rate_percent": 3.3,
        "top_errors": [
          {"reason": "video_unavailable", "count": 8}
        ],
        "historical_comparison": "unavailable",
        "status": "healthy"
      },
      {
        "name": "webstories",
        "collection": "raw_web_stories_ingestion_data",
        "documents_last_6h": 80,
        "last_ingest_time": "2026-03-10T11:20:00Z",
        "minutes_since_last_ingest": 40,
        "throughput_per_hour": 13,
        "zero_ingest_periods": ["08:00-09:00"],
        "error_count": 2,
        "error_rate_percent": 2.5,
        "top_errors": [],
        "historical_comparison": "unavailable",
        "status": "healthy"
      }
    ],
    "summary": {
      "total_pipelines": 7,
      "healthy": 5,
      "warning": 1,
      "critical": 1,
      "total_documents_all_pipelines": 7190,
      "total_errors_all_pipelines": 183
    }
  },
  "validation_status": "warning",
  "confidence_score": 65,
  "issues": [
    "Native Videos pipeline has ingested 0 documents in the last 6 hours. Last ingest was 7.5 hours ago.",
    "Summaries pipeline has 6.7% error rate, above the 5% warning threshold.",
    "Historical comparison data is unavailable for 3 pipelines."
  ],
  "recommendations": [
    "URGENT: Investigate Native Videos pipeline immediately. Check Cloud Function logs, Pub/Sub subscription, and MRSS feed availability.",
    "Review Summaries hygiene failures - 80 HTML contamination errors suggest a publisher feed quality issue. Run summaries-hygiene-monitor for detailed breakdown.",
    "Establish historical throughput baselines by running this skill on a scheduled basis."
  ],
  "alerts": [
    {
      "level": "CRITICAL",
      "message": "Native Videos pipeline has been inactive for 7.5 hours. Zero documents ingested in the monitoring window.",
      "pipeline": "native_videos"
    },
    {
      "level": "WARNING",
      "message": "Summaries pipeline error rate is 6.7%, above the 5% threshold.",
      "pipeline": "summaries"
    }
  ]
}
```

---

## Dry-Run Behavior

This skill is **always read-only**. The `--execute` flag has no additional effect. The skill:

- Queries MongoDB collections (read-only).
- Performs count and aggregation queries.
- Produces a JSON report.
- **Never** modifies documents, collections, pipeline configurations, or any other persistent state.

---

## Error Handling

| Error Condition                               | Behavior                                                      |
|-----------------------------------------------|---------------------------------------------------------------|
| MongoDB connection failure                    | Set confidence=0, status=failed, record connection error      |
| Individual collection not found               | Mark that pipeline as status=critical with note, continue     |
| Query timeout on a collection                 | Record timeout, mark pipeline as status=warning, continue     |
| createdAt field missing on documents          | Attempt fallback fields (_id ObjectId timestamp), note issue  |
| contentType field missing on raw_videos_rss   | Cannot distinguish native_videos from native_shorts, note     |
| All pipelines return 0 documents              | Set status=critical for all, raise CRITICAL alert             |

---

## Alerting Thresholds

| Condition                                              | Alert Level |
|--------------------------------------------------------|-------------|
| Any pipeline has 0 documents in monitoring window      | CRITICAL    |
| Any pipeline has minutes_since_last_ingest > threshold | CRITICAL    |
| Any pipeline has throughput down > 60% from average    | CRITICAL    |
| Any pipeline has error rate > 15%                      | CRITICAL    |
| Any pipeline has 1-2 zero-ingest hour gaps             | WARNING     |
| Any pipeline has error rate 5-15%                      | WARNING     |
| Any pipeline has throughput down 30-60% from average   | WARNING     |
| MongoDB connection failure                             | CRITICAL    |
