# Skill: transcoder-status-monitor

## Metadata

| Field          | Value                                                              |
|----------------|--------------------------------------------------------------------|
| **Skill ID**   | `transcoder-status-monitor`                                        |
| **Version**    | 1.0.0                                                              |
| **Purpose**    | Track transcoder queue depth, completion rates, and stuck jobs     |
| **Trigger**    | Scheduled (every 30 minutes recommended) or Manual                 |
| **Run Mode**   | Always dry-run. This skill is read-only and never mutates data.    |
| **Mutates**    | Never                                                              |
| **Owner**      | DE-DS Platform Team                                                |

---

## Purpose

The Native Videos pipeline uses a transcoder workflow to process raw MP4 files into standardized formats. Videos flow through a state machine: initiated -> queued -> submitting -> submitted -> completed (or failed). This skill monitors the transcoder queue depth, identifies stuck or failed jobs, and tracks throughput to detect processing bottlenecks.

Stuck jobs (videos that remain in intermediate states for too long) are the most common operational issue. A video stuck in "submitted" for 6+ hours or "queued" for 2+ hours typically indicates a transcoder backend failure that requires manual intervention.

This is a read-only monitoring skill. It queries MongoDB and produces a report. It never writes to any data store.

---

## Inputs

```json
{
  "hours_back": {
    "type": "integer",
    "required": false,
    "description": "Number of hours to look back for transcoder job data.",
    "default": 24,
    "minimum": 1,
    "maximum": 168,
    "example": 24
  }
}
```

---

## Data Source

| Source                                                | Description                                         |
|-------------------------------------------------------|-----------------------------------------------------|
| MongoDB `ingestion-data.raw_videos_rss`               | Native video records with transcoder status fields  |
| Filter: `contentType == "videos"`                     | Excludes shorts which use a different workflow       |

### Key Fields in `raw_videos_rss`

| Field                           | Type    | Description                                              |
|---------------------------------|---------|----------------------------------------------------------|
| `transcoderProcessingStatus`    | string  | Current state: initiated, queued, submitting, submitted, completed, failed |
| `transcoderJobId`               | string  | External transcoder job identifier                       |
| `transcoderSubmittedAt`         | date    | Timestamp when job was submitted to transcoder           |
| `transcoderCompletedAt`         | date    | Timestamp when transcoder finished (success or failure)  |
| `transcoderError`               | string  | Error message if the job failed                          |
| `createdAt`                     | date    | Document creation timestamp                              |
| `updatedAt`                     | date    | Last update timestamp                                    |
| `pub_name`                      | string  | Publisher name                                           |
| `title`                         | string  | Video title                                              |
| `videoUrl`                      | string  | Source video URL                                         |

---

## Execution Steps

### Step 1: Query Status Distribution

- Connect to MongoDB database `ingestion-data`.
- Query collection `raw_videos_rss` with filter: `contentType == "videos"` and `createdAt >= (now - hours_back)`.
- Aggregate by `transcoderProcessingStatus` to get counts for each state.

Expected states and their meaning:

| Status        | Description                                              | Normal Dwell Time   |
|---------------|----------------------------------------------------------|---------------------|
| `initiated`   | Record created, not yet queued for transcoding           | < 15 minutes        |
| `queued`      | In the transcoder queue, waiting to be picked up         | < 2 hours           |
| `submitting`  | Being submitted to the transcoder backend                | < 30 minutes        |
| `submitted`   | Submitted to transcoder, awaiting completion callback    | < 6 hours           |
| `completed`   | Successfully transcoded                                  | Terminal state      |
| `failed`      | Transcoding failed with an error                         | Terminal state      |

Record `status_counts` as a dictionary mapping each status to its count.

### Step 2: Identify Stuck Jobs

A job is considered "stuck" if it has remained in a non-terminal state longer than the expected dwell time.

#### 2a. Stuck in "submitted" (> 6 hours)

```
Query: transcoderProcessingStatus == "submitted"
  AND contentType == "videos"
  AND transcoderSubmittedAt < (now - 6 hours)
```

For each stuck job, extract:
- `_id`, `transcoderJobId`, `title`, `pub_name`, `videoUrl`
- `transcoderSubmittedAt` (to calculate how long it has been stuck)
- `hours_stuck = (now - transcoderSubmittedAt) / 3600`

#### 2b. Stuck in "queued" (> 2 hours)

```
Query: transcoderProcessingStatus == "queued"
  AND contentType == "videos"
  AND createdAt < (now - 2 hours)
```

For each stuck job, extract the same fields plus `hours_stuck`.

#### 2c. Stuck in "initiated" (> 1 hour)

```
Query: transcoderProcessingStatus == "initiated"
  AND contentType == "videos"
  AND createdAt < (now - 1 hour)
```

#### 2d. Stuck in "submitting" (> 30 minutes)

```
Query: transcoderProcessingStatus == "submitting"
  AND contentType == "videos"
  AND updatedAt < (now - 30 minutes)
```

Aggregate all stuck jobs into `stuck_jobs` array, sorted by `hours_stuck` descending.
Record `total_stuck_jobs` count.

### Step 3: Analyze Recent Failures

Query all jobs with `transcoderProcessingStatus == "failed"` in the time window:

```
Query: transcoderProcessingStatus == "failed"
  AND contentType == "videos"
  AND updatedAt >= (now - hours_back)
```

For each failed job, extract:
- `_id`, `transcoderJobId`, `title`, `pub_name`, `videoUrl`
- `transcoderError` (the error message)
- `transcoderSubmittedAt`, `transcoderCompletedAt` (to calculate processing time before failure)

Group failures by error message to identify patterns:
- Aggregate `transcoderError` values (normalize by stripping unique IDs/timestamps).
- Count occurrences of each unique error pattern.
- Record `error_patterns` as an array of `{ pattern, count, example_job_id }`.

Record `total_failures` and `recent_failures` (list of individual failed jobs, limited to 20).

### Step 4: Calculate Throughput

#### 4a. Completions Per Hour

```
Query: transcoderProcessingStatus == "completed"
  AND contentType == "videos"
  AND transcoderCompletedAt >= (now - hours_back)
```

- Count total completions.
- Calculate `completions_per_hour = total_completions / hours_back`.

#### 4b. Average Completion Time

For completed jobs in the window that have both `transcoderSubmittedAt` and `transcoderCompletedAt`:
- Calculate `processing_time = transcoderCompletedAt - transcoderSubmittedAt` for each.
- Compute `avg_completion_time_minutes`, `min_completion_time_minutes`, `max_completion_time_minutes`, `p95_completion_time_minutes`.

#### 4c. Failure Rate

- `failure_rate_percent = (total_failures / (total_completions + total_failures)) * 100`
- Handle division by zero (if both are 0, set to 0 and note no transcoding activity).

### Step 5: Publisher-Level Breakdown

Group all transcoder jobs by `pub_name`:
- For each publisher, count: `total_jobs`, `completed`, `failed`, `stuck`, `in_progress` (queued + submitting + submitted).
- Calculate `publisher_failure_rate_percent`.
- Sort by failure rate descending.
- Flag publishers with failure rate > 20%.

### Step 6: Queue Depth Trend

Analyze the current queue depth (non-terminal jobs) versus the time window:

- `current_queue_depth = count of jobs where status in (initiated, queued, submitting, submitted)`.
- If possible, sample the queue depth at hourly intervals over the time window to detect trends.
- Classify trend: `growing` (queue getting larger), `stable`, `draining` (queue getting smaller).

---

## Confidence Score Calculation

| Condition                                              | Points |
|--------------------------------------------------------|--------|
| MongoDB connection successful                          | +20    |
| raw_videos_rss collection queryable                    | +10    |
| Status distribution data retrieved                     | +10    |
| Stuck job analysis completed                           | +10    |
| Failure analysis completed                             | +10    |
| Throughput calculation completed                       | +10    |
| No stuck jobs found                                    | +10    |
| Failure rate < 5%                                      | +10    |
| Queue depth is stable or draining                      | +10    |
| **Total possible**                                     | **100**|

Deductions:
- MongoDB connection failure: confidence = 0, status = failed
- Collection not found: -20 points
- > 10 stuck jobs: -10 points
- Failure rate > 20%: -15 points
- Queue depth growing: -10 points
- Zero completions in window: -10 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "transcoder-status-monitor",
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
    "status_counts": {
      "initiated": 5,
      "queued": 12,
      "submitting": 2,
      "submitted": 45,
      "completed": 380,
      "failed": 18
    },
    "total_jobs_in_window": 462,
    "current_queue_depth": 64,
    "queue_trend": "stable",
    "stuck_jobs": [
      {
        "status": "submitted",
        "document_id": "65f1a2b3c4d5e6f7a8b9c0d1",
        "transcoder_job_id": "txc-12345-abcde",
        "title": "Breaking News: Example Video",
        "pub_name": "Example Publisher",
        "video_url": "https://cdn.example.com/video.mp4",
        "submitted_at": "2026-03-09T22:00:00Z",
        "hours_stuck": 14.0,
        "expected_max_hours": 6
      },
      {
        "status": "queued",
        "document_id": "65f1a2b3c4d5e6f7a8b9c0d2",
        "transcoder_job_id": null,
        "title": "Another Stuck Video",
        "pub_name": "Another Publisher",
        "video_url": "https://cdn.another.com/vid.mp4",
        "created_at": "2026-03-10T08:30:00Z",
        "hours_stuck": 3.5,
        "expected_max_hours": 2
      }
    ],
    "total_stuck_jobs": 2,
    "recent_failures": [
      {
        "document_id": "65f1a2b3c4d5e6f7a8b9c0d3",
        "transcoder_job_id": "txc-67890-fghij",
        "title": "Failed Video Example",
        "pub_name": "Problem Publisher",
        "video_url": "https://cdn.problem.com/bad.mp4",
        "error": "TranscodingError: Input file is corrupted at timestamp 00:02:15",
        "submitted_at": "2026-03-10T06:00:00Z",
        "failed_at": "2026-03-10T06:45:00Z",
        "processing_time_minutes": 45
      }
    ],
    "total_failures": 18,
    "error_patterns": [
      {
        "pattern": "TranscodingError: Input file is corrupted",
        "count": 8,
        "example_job_id": "txc-67890-fghij"
      },
      {
        "pattern": "TimeoutError: Transcoding exceeded maximum duration",
        "count": 5,
        "example_job_id": "txc-11111-aaaaa"
      },
      {
        "pattern": "ResolutionError: Input resolution below minimum",
        "count": 3,
        "example_job_id": "txc-22222-bbbbb"
      },
      {
        "pattern": "NetworkError: Failed to fetch source video",
        "count": 2,
        "example_job_id": "txc-33333-ccccc"
      }
    ],
    "throughput": {
      "total_completions": 380,
      "completions_per_hour": 15.8,
      "avg_completion_time_minutes": 35,
      "min_completion_time_minutes": 8,
      "max_completion_time_minutes": 180,
      "p95_completion_time_minutes": 95
    },
    "failure_rate_percent": 4.5,
    "publisher_breakdown": [
      {
        "pub_name": "Problem Publisher",
        "total_jobs": 45,
        "completed": 30,
        "failed": 12,
        "stuck": 1,
        "in_progress": 2,
        "failure_rate_percent": 26.7
      },
      {
        "pub_name": "Good Publisher",
        "total_jobs": 120,
        "completed": 118,
        "failed": 1,
        "stuck": 0,
        "in_progress": 1,
        "failure_rate_percent": 0.8
      }
    ]
  },
  "validation_status": "warning",
  "confidence_score": 72,
  "issues": [
    "2 jobs are stuck beyond expected dwell times.",
    "1 job has been in 'submitted' state for 14 hours (threshold: 6 hours).",
    "Publisher 'Problem Publisher' has 26.7% failure rate, well above 20% threshold.",
    "8 failures due to corrupted input files - may indicate publisher feed quality issue."
  ],
  "recommendations": [
    "URGENT: Investigate stuck job txc-12345-abcde (submitted 14h ago). Check transcoder backend status and consider manual retry or cancellation.",
    "Contact 'Problem Publisher' regarding video file quality. 8 of their 12 failures are due to corrupted input files.",
    "Review transcoder timeout threshold. 5 jobs failed due to timeout - the max duration limit may need adjustment for longer videos.",
    "Monitor the 2 jobs stuck in 'queued' state. If they do not progress within 1 hour, escalate to infrastructure team."
  ],
  "alerts": [
    {
      "level": "CRITICAL",
      "message": "Job txc-12345-abcde has been stuck in 'submitted' state for 14.0 hours (threshold: 6h).",
      "document_id": "65f1a2b3c4d5e6f7a8b9c0d1"
    },
    {
      "level": "WARNING",
      "message": "Publisher 'Problem Publisher' has 26.7% transcoding failure rate.",
      "pub_name": "Problem Publisher"
    },
    {
      "level": "WARNING",
      "message": "8 transcoding failures due to corrupted input files in the last 24 hours.",
      "error_pattern": "TranscodingError: Input file is corrupted"
    }
  ]
}
```

---

## Dry-Run Behavior

This skill is **always read-only**. The `--execute` flag has no additional effect. The skill:

- Queries MongoDB collections (read-only).
- Performs count, aggregation, and find queries.
- Produces a JSON report.
- **Never** modifies transcoder job statuses, retries failed jobs, cancels stuck jobs, or performs any mutation.
- **Never** interacts with the transcoder backend directly.

To act on the findings (retry a stuck job, cancel a failed job, etc.), the operator must use the appropriate operational tool or interface manually.

---

## Error Handling

| Error Condition                               | Behavior                                                       |
|-----------------------------------------------|----------------------------------------------------------------|
| MongoDB connection failure                    | Set confidence=0, status=failed, record connection error       |
| raw_videos_rss collection not found           | Set confidence=0, status=failed, suggest checking DB name      |
| transcoderProcessingStatus field missing      | Count as "unknown" status, reduce confidence, note in issues   |
| Zero total jobs in time window                | Set all counts to 0, status=warning (no transcoding activity)  |
| transcoderSubmittedAt/CompletedAt missing     | Skip timing calculations for those jobs, note in issues        |
| Query timeout                                 | Record error, attempt with smaller time window                 |
| Aggregation pipeline error                    | Fall back to individual queries, note performance impact       |

---

## Alerting Thresholds

| Condition                                              | Alert Level |
|--------------------------------------------------------|-------------|
| Any job stuck in "submitted" > 6 hours                 | CRITICAL    |
| Any job stuck in "queued" > 2 hours                    | WARNING     |
| Any job stuck in "submitting" > 30 minutes             | WARNING     |
| Total stuck jobs > 10                                  | CRITICAL    |
| Total stuck jobs > 5                                   | WARNING     |
| Overall failure rate > 20%                             | CRITICAL    |
| Overall failure rate > 10%                             | WARNING     |
| Single publisher failure rate > 50%                    | CRITICAL    |
| Single publisher failure rate > 20%                    | WARNING     |
| Zero completions in monitoring window                  | CRITICAL    |
| Completions per hour < 5 (significantly below normal)  | WARNING     |
| Queue depth growing (trend = "growing")                | WARNING     |
| Average completion time > 120 minutes                  | WARNING     |
| P95 completion time > 240 minutes                      | WARNING     |
