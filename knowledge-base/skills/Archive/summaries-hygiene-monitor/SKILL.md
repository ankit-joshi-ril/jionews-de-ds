# Skill: summaries-hygiene-monitor

## Metadata

| Field          | Value                                                              |
|----------------|--------------------------------------------------------------------|
| **Skill ID**   | `summaries-hygiene-monitor`                                        |
| **Version**    | 1.0.0                                                              |
| **Purpose**    | Track hygiene pass/fail rates for the Summaries pipeline           |
| **Trigger**    | Scheduled (every 1 hour recommended) or Manual                     |
| **Run Mode**   | Always dry-run. This skill is read-only and never mutates data.    |
| **Mutates**    | Never                                                              |
| **Owner**      | DE-DS Platform Team                                                |

---

## Purpose

The Summaries pipeline applies hygiene checks to every ingested document before it progresses through the pipeline. This skill monitors the pass/fail rates of those hygiene checks to detect quality degradation early. It breaks down failures by error type and publisher, enabling targeted investigation.

This is a read-only monitoring skill. It queries MongoDB collections and produces a report. It never writes to any data store.

---

## Inputs

```json
{
  "hours_back": {
    "type": "integer",
    "required": false,
    "description": "Number of hours to look back for hygiene data.",
    "default": 24,
    "minimum": 1,
    "maximum": 168,
    "example": 24
  }
}
```

---

## Data Sources

| Source                                        | Description                                          |
|-----------------------------------------------|------------------------------------------------------|
| MongoDB `ingestion-data.raw_summaries_insgestion_data` | Primary collection for summaries ingestion records   |
| Hygiene failure records (via rejection tracking or Pub/Sub monitoring) | Records of documents that failed hygiene checks      |

---

## Execution Steps

### Step 1: Query Total Documents Processed

- Connect to MongoDB database `ingestion-data`.
- Query collection `raw_summaries_insgestion_data`.
- Filter: `createdAt >= (now - hours_back)`.
- Count total documents. This is `total_processed`.
- Also retrieve a sample of 100 recent documents to inspect their hygiene-related fields.
- **WARN** if `total_processed` is 0 (may indicate pipeline is down; recommend running `pipeline-execution-monitor`).

### Step 2: Query Hygiene Pass/Fail Counts

Hygiene results may be tracked in one of the following ways (check in order):

1. **Field-level tracking**: Documents in `raw_summaries_insgestion_data` may have a `hygiene_status` or `isHygienePassed` field.
   - Count documents where `hygiene_status == "passed"` or `isHygienePassed == true`.
   - Count documents where `hygiene_status == "failed"` or `isHygienePassed == false`.

2. **Separate rejection collection**: A collection like `raw_summaries_rejections` or `summaries_hygiene_failures` may store failed documents.
   - Count documents in the rejection collection created in the time window.

3. **Pub/Sub dead-letter tracking**: Hygiene failures may be routed to a dead-letter topic with metadata stored in a tracking collection.

Record: `passed_hygiene`, `failed_hygiene`.
Calculate: `pass_rate_percent = (passed_hygiene / total_processed) * 100` (handle division by zero).

### Step 3: Break Down Failures by Error Type

For documents that failed hygiene, categorize by the specific failure reason. Check the `hygiene_error`, `rejectionReason`, or `failureType` field. Common failure types:

| Error Type            | Description                                                | Detection Logic                                          |
|-----------------------|------------------------------------------------------------|----------------------------------------------------------|
| `title_too_short`     | Title is shorter than minimum allowed length               | `len(title) < 20` characters                             |
| `title_too_long`      | Title exceeds maximum allowed length                       | `len(title) > 200` characters                            |
| `summary_too_short`   | Summary/description is shorter than minimum                | `len(summary) < 50` characters                           |
| `summary_too_long`    | Summary/description exceeds maximum                        | `len(summary) > 5000` characters                         |
| `html_in_content`     | Raw HTML tags found in title or summary                    | Regex: `<[^>]+>` found in text fields                    |
| `special_chars`       | Excessive special characters or encoding issues            | Non-printable characters, mojibake, or encoding artifacts |
| `missing_title`       | Title field is null or empty                               | `title is None or title.strip() == ""`                   |
| `missing_summary`     | Summary field is null or empty                             | `summary is None or summary.strip() == ""`               |
| `duplicate_content`   | Content is a duplicate of an already-ingested document     | Dedup check flagged the content                          |
| `invalid_url`         | Source URL is malformed or unreachable                     | URL validation failed                                    |
| `language_mismatch`   | Detected language does not match declared language         | Language detection disagrees with metadata                |

Record counts per error type in `failure_breakdown`.

If the failure reason field is not available or is unstructured, attempt to classify failures by inspecting the document content directly using the rules above.

### Step 4: Break Down Failures by Publisher

- Group failed documents by `pub_name` or `publication_id`.
- For each publisher, calculate:
  - `total_documents`: Documents from this publisher in the time window.
  - `failed_documents`: Documents that failed hygiene.
  - `failure_rate_percent`: `(failed / total) * 100`.
  - `primary_failure_type`: The most common failure type for this publisher.
- Sort publishers by `failure_rate_percent` descending.
- Record the top 20 publishers with the highest failure rates.
- **WARN** if any publisher has a failure rate > 30%.
- **CRITICAL** if any publisher has a failure rate > 60%.

### Step 5: Compare with Historical Averages

If historical data is available (e.g., from previous skill runs or a metrics collection):

- Compare current `pass_rate_percent` with the rolling 7-day average.
- Calculate `pass_rate_delta`: difference between current and historical average.
- **WARN** if pass rate has dropped by more than 5 percentage points.
- **CRITICAL** if pass rate has dropped by more than 15 percentage points.

If historical data is not available:
- Set `historical_comparison: "unavailable"`.
- Recommend establishing a baseline by running this skill regularly.

### Step 6: Generate Alerts

Based on the analysis, generate actionable alerts:

| Condition                                                  | Alert Level | Message Template                                                |
|------------------------------------------------------------|-------------|-----------------------------------------------------------------|
| Overall pass rate < 80%                                    | WARNING     | "Summaries hygiene pass rate is {rate}%, below 80% threshold."  |
| Overall pass rate < 60%                                    | CRITICAL    | "Summaries hygiene pass rate is critically low at {rate}%."     |
| Single publisher failure rate > 60%                        | CRITICAL    | "Publisher {name} has {rate}% failure rate. Investigate feed."  |
| `html_in_content` failures > 10% of total failures        | WARNING     | "HTML contamination detected in {count} documents."             |
| `total_processed` is 0                                     | CRITICAL    | "No summaries processed in last {hours} hours. Pipeline down?"  |
| Pass rate dropped > 5pp from historical average            | WARNING     | "Pass rate dropped {delta}pp from 7-day average."               |
| Pass rate dropped > 15pp from historical average           | CRITICAL    | "Severe pass rate drop of {delta}pp. Immediate investigation."  |

---

## Confidence Score Calculation

| Condition                                              | Points |
|--------------------------------------------------------|--------|
| MongoDB connection successful                          | +20    |
| total_processed > 0 (pipeline is running)              | +15    |
| Hygiene status field is available and queryable         | +15    |
| Failure breakdown by error type is complete            | +10    |
| Publisher breakdown is complete                        | +10    |
| Historical comparison data available                   | +10    |
| Overall pass rate >= 80%                               | +10    |
| No publisher has failure rate > 30%                    | +10    |
| **Total possible**                                     | **100**|

Deductions:
- MongoDB connection failure: confidence = 0, status = failed
- total_processed is 0: -20 points
- Hygiene status field not found (must infer from content): -15 points
- Historical data unavailable: -10 points
- Overall pass rate < 60%: -15 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "summaries-hygiene-monitor",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {
    "hours_back": 24
  },
  "output": {
    "time_window": {
      "from": "2026-03-09T12:00:00Z",
      "to": "2026-03-10T12:00:00Z",
      "hours": 24
    },
    "total_processed": 12500,
    "passed_hygiene": 11250,
    "failed_hygiene": 1250,
    "pass_rate_percent": 90.0,
    "failure_breakdown": {
      "title_too_short": 180,
      "title_too_long": 45,
      "summary_too_short": 320,
      "summary_too_long": 90,
      "html_in_content": 250,
      "special_chars": 115,
      "missing_title": 30,
      "missing_summary": 60,
      "duplicate_content": 100,
      "invalid_url": 25,
      "language_mismatch": 35
    },
    "publisher_breakdown": [
      {
        "pub_name": "Low Quality Publisher",
        "publication_id": "pub_042",
        "total_documents": 500,
        "failed_documents": 200,
        "failure_rate_percent": 40.0,
        "primary_failure_type": "html_in_content"
      },
      {
        "pub_name": "Another Publisher",
        "publication_id": "pub_089",
        "total_documents": 300,
        "failed_documents": 75,
        "failure_rate_percent": 25.0,
        "primary_failure_type": "summary_too_short"
      }
    ],
    "historical_comparison": {
      "seven_day_avg_pass_rate": 92.5,
      "current_pass_rate": 90.0,
      "delta_percentage_points": -2.5,
      "trend": "declining"
    }
  },
  "validation_status": "warning",
  "confidence_score": 82,
  "issues": [
    "Overall pass rate (90.0%) is within acceptable range but showing declining trend.",
    "Publisher 'Low Quality Publisher' has 40.0% failure rate, primarily due to HTML in content.",
    "250 documents contained HTML tags in title or summary fields."
  ],
  "recommendations": [
    "Investigate 'Low Quality Publisher' feed for HTML contamination. Their RSS feed may include raw HTML in description fields. Consider adding HTML stripping as a pre-processing step.",
    "Review summary length thresholds - 320 documents failed for summary_too_short. Some publishers may send brief summaries that are legitimate.",
    "Monitor pass rate trend over next 24 hours. If decline continues below 85%, escalate to on-call."
  ],
  "alerts": [
    {
      "level": "WARNING",
      "message": "Publisher 'Low Quality Publisher' has 40.0% failure rate. Investigate feed quality."
    }
  ]
}
```

---

## Dry-Run Behavior

This skill is **always read-only**. The `--execute` flag has no additional effect. The skill:

- Queries MongoDB collections (read-only).
- Aggregates and computes statistics in-memory.
- Produces a JSON report.
- **Never** modifies documents, collections, hygiene rules, or any other persistent state.

---

## Error Handling

| Error Condition                               | Behavior                                                      |
|-----------------------------------------------|---------------------------------------------------------------|
| MongoDB connection failure                    | Set confidence=0, status=failed, record connection error      |
| Collection not found                          | Set confidence=0, status=failed, suggest checking DB name     |
| Zero documents in time window                 | Set total_processed=0, status=warning, suggest pipeline check |
| Hygiene status field not found on documents   | Attempt inference from content fields, reduce confidence      |
| Query timeout                                 | Record timeout error, attempt with smaller time window        |
| Publisher field missing on some documents     | Group those as "unknown_publisher", note in issues            |

---

## Alerting Thresholds Summary

| Metric                          | WARNING Threshold | CRITICAL Threshold |
|---------------------------------|-------------------|--------------------|
| Overall pass rate               | < 80%             | < 60%              |
| Single publisher failure rate   | > 30%             | > 60%              |
| Pass rate delta from 7-day avg  | > 5pp drop        | > 15pp drop        |
| HTML contamination rate         | > 10% of failures | > 25% of failures  |
| Total processed = 0             | -                 | Always CRITICAL    |
