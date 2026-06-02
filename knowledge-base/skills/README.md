# Skills Index

## Execution Model

Skills are micro-agents that automate specific operational tasks within the JioNews DE-DS knowledge base. Every skill follows a strict execution contract:

### Dry-Run by Default

All skills run in **DRY-RUN** mode unless the `--execute` flag is explicitly passed. In dry-run mode:

- Skills perform all validation, querying, and analysis steps.
- Skills produce a full structured JSON output report.
- Skills **NEVER** modify any data store (MongoDB, Redis, GCS, local config files).
- The output includes a `dry_run: true` field to confirm no mutations occurred.

With `--execute`:

- Skills may perform **write** operations (append config rows, update local copies).
- Skills still **NEVER** perform delete operations (per CONSTITUTION.md).
- All write operations require human approval before committing to production systems.

### Structured JSON Output

Every skill returns a JSON report containing:

| Field                | Type    | Description                                                |
|----------------------|---------|------------------------------------------------------------|
| `skill_name`         | string  | Identifier of the skill that produced the report           |
| `run_mode`           | string  | `"dry-run"` or `"execute"`                                 |
| `timestamp`          | string  | ISO 8601 execution timestamp                               |
| `inputs`             | object  | The input parameters that were provided                    |
| `validation_status`  | string  | `"passed"`, `"failed"`, or `"warning"`                     |
| `confidence_score`   | integer | 0-100 score indicating reliability of the result           |
| `output`             | object  | Skill-specific result data                                 |
| `issues`             | array   | List of problems detected during execution                 |
| `recommendations`    | array   | Suggested actions for the operator                         |
| `alerts`             | array   | Conditions that require immediate attention                |

### Confidence Score Calculation

The confidence score (0-100) reflects how trustworthy the skill's output is:

| Range  | Label    | Meaning                                                        |
|--------|----------|----------------------------------------------------------------|
| 90-100 | High     | All checks passed, data is fresh, no ambiguity                 |
| 70-89  | Medium   | Minor issues detected, some checks inconclusive                |
| 50-69  | Low      | Significant issues found, manual review recommended            |
| 0-49   | Critical | Major failures, data unreliable, human intervention required   |

### Validation Status

- **passed**: All required checks succeeded. The skill's output can be acted upon.
- **warning**: Some non-critical checks failed. Output is usable but review is recommended.
- **failed**: One or more critical checks failed. Do not act on the output without investigation.

---

## Skills Catalog

### 1. headlines-publisher-onboarding

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Validate and onboard new RSS/JSON feeds for the Headlines pipeline         |
| **Trigger**    | Manual (operator initiates when a new publisher feed is received)          |
| **Definition** | [SKILL.md](headlines-publisher-onboarding/SKILL.md)                       |
| **Inputs**     | `feed_url`, `publisher_name`, `language`, `category`                       |
| **Mutates**    | Only with `--execute`: appends row to local config CSV copy                |

### 2. native-videos-publisher-onboarding

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Validate MRSS feeds, check MP4 URL accessibility, verify 1080p resolution  |
| **Trigger**    | Manual (operator initiates when a new video publisher feed is received)    |
| **Definition** | [SKILL.md](native-videos-publisher-onboarding/SKILL.md)                   |
| **Inputs**     | `feed_url`, `publisher_name`, `language`, `category`                       |
| **Mutates**    | Only with `--execute`: appends row to local config CSV copy                |

### 3. feed-health-check

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Monitor all active feed URLs across all pipelines for availability         |
| **Trigger**    | Scheduled (recommended: every 30 minutes) or Manual                        |
| **Definition** | [SKILL.md](Archive/feed-health-check/SKILL.md)                                    |
| **Inputs**     | `pipeline` (optional), `timeout_seconds` (optional, default 10)            |
| **Mutates**    | Never (read-only monitoring skill)                                         |

### 4. summaries-hygiene-monitor

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Track hygiene pass/fail rates for the Summaries pipeline                   |
| **Trigger**    | Scheduled (recommended: every 1 hour) or Manual                            |
| **Definition** | [SKILL.md](Archive/summaries-hygiene-monitor/SKILL.md)                            |
| **Inputs**     | `hours_back` (optional, default 24)                                        |
| **Mutates**    | Never (read-only monitoring skill)                                         |

### 5. pipeline-execution-monitor

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Check pipeline run status and data flow across all pipelines               |
| **Trigger**    | Scheduled (recommended: every 15 minutes) or Manual                        |
| **Definition** | [SKILL.md](Archive/pipeline-execution-monitor/SKILL.md)                           |
| **Inputs**     | `hours_back` (optional, default 6)                                         |
| **Mutates**    | Never (read-only monitoring skill)                                         |

### 6. redis-cache-monitor

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Monitor Redis sorted set sizes, memory usage, and TTL compliance           |
| **Trigger**    | Scheduled (recommended: every 15 minutes) or Manual                        |
| **Definition** | [SKILL.md](Archive/redis-cache-monitor/SKILL.md)                                  |
| **Inputs**     | None required                                                              |
| **Mutates**    | Never (read-only monitoring skill)                                         |

### 7. transcoder-status-monitor

| Property       | Value                                                                      |
|----------------|----------------------------------------------------------------------------|
| **Purpose**    | Track transcoder queue depth, completion rates, and stuck jobs             |
| **Trigger**    | Scheduled (recommended: every 30 minutes) or Manual                        |
| **Definition** | [SKILL.md](Archive/transcoder-status-monitor/SKILL.md)                            |
| **Inputs**     | `hours_back` (optional, default 24)                                        |
| **Mutates**    | Never (read-only monitoring skill)                                         |

---

## Safety and Governance

All skills are governed by [CONSTITUTION.md](../CONSTITUTION.md):

- **No deletes**: Skills never delete documents, config rows, cache entries, or any persistent data.
- **Human approval for writes**: Even with `--execute`, production writes require operator confirmation.
- **Audit trail**: Every skill execution produces a timestamped JSON report that serves as an audit record.
- **Idempotent reads**: Monitoring skills can run repeatedly without side effects.
