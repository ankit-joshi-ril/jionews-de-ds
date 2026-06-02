# Cloud Run Service Analyzer

Analyze a Cloud Run / Cloud Function service for resource utilization, latency issues, and scaling efficiency. Produces a full diagnostic report with concrete tuning recommendations.

## Usage

```
/cloudrun-analyzer <service-name> [--project <id>] [--region <region>] [--days <n>]
```

**Examples:**
```
/cloudrun-analyzer transcoder-push-to-sftp
/cloudrun-analyzer transcoder-push-to-sftp --days 14
/cloudrun-analyzer my-service --project my-project-id --region us-central1
```

**Defaults:** project=`jiox-328108`, region=`asia-south1`, days=`30`

---

## Instructions

When this skill is invoked with `$ARGUMENTS`, do the following:

### 1. Parse arguments

Extract from `$ARGUMENTS`:
- `service` — first positional arg or `--service`
- `project` — `--project` flag, default `jiox-328108`
- `region` — `--region` flag, default `asia-south1`
- `days` — `--days` flag as integer, default `30`

If no service name is given, ask the user for it before proceeding.

---

### 2. Fetch current service configuration

Run this command and capture JSON output:

```bash
gcloud run services describe <service> --region <region> --project <project> --format json
```

Extract and display:
- CPU (vCPU)
- Memory (MiB and GiB)
- Min instances
- Max instances
- Concurrency (`containerConcurrency`)
- Request timeout (`timeoutSeconds`)
- Runtime / base image

---

### 3. Pull observability metrics via Cloud Monitoring

Use the `gcloud` CLI to query Cloud Monitoring metrics for the last `<days>` days. Use 1-hour alignment periods.

Run the following queries (one at a time, capture output):

**Request count** — total invocations:
```bash
gcloud monitoring metrics list --filter="metric.type=\"run.googleapis.com/request_count\""
```

Use the Monitoring API or `gcloud` to fetch time series for each metric below, filtered by:
- `resource.labels.service_name = "<service>"`
- `resource.labels.location = "<region>"`

Metrics to fetch:
| Metric | Aligner | What it tells you |
|--------|---------|-------------------|
| `run.googleapis.com/request_count` | SUM | Total requests |
| `run.googleapis.com/request_latencies` | PERCENTILE_50 + PERCENTILE_99 | Response time |
| `run.googleapis.com/container/cpu/utilizations` | PERCENTILE_50 + PERCENTILE_99 | CPU pressure |
| `run.googleapis.com/container/memory/utilizations` | PERCENTILE_50 + PERCENTILE_99 | Memory pressure |
| `run.googleapis.com/container/instance_count` | MAX + MEAN | Scaling behavior |

If `gcloud` CLI doesn't support the query format needed, write and execute a short Python snippet using `google-cloud-monitoring` (already installed) to fetch the time series data.

---

### 4. Analyze and diagnose

For each dimension, apply these thresholds (relative to the service's configured timeout/limits):

**Latency:**
- p50 avg > 30% of timeout → WARNING
- p50 avg > 60% of timeout → CRITICAL
- p99 peak > 80% of timeout → CRITICAL (close to request drop)
- If latency is elevated AND concurrency > 1: root cause is request queuing

**CPU utilization:**
- p99 peak > 90% → CRITICAL (CPU throttling)
- p99 peak > 70% → WARNING
- p99 peak < 20% and CPU > 1 vCPU → over-provisioned

**Memory utilization:**
- p99 peak > 90% of limit → CRITICAL (OOM risk)
- p99 peak > 70% → WARNING
- p99 peak < 40% → potentially over-provisioned
- Note: `/tmp` in Cloud Run is RAM-backed — simultaneous file downloads at high concurrency multiply memory usage linearly

**Instance count:**
- If peak instances > 70% of max_instances → WARNING (near cap)
- If avg active << min_instances → wasting money on idle warm instances

**Concurrency root cause detection:**
- If `containerConcurrency > 1` AND latency is elevated: flag that all batch messages pile onto shared instances, creating a queue. Recommend `concurrency=1` for I/O-heavy workloads (SFTP uploads, GCS downloads, video processing).

---

### 5. Generate recommendations

For every issue found, output a concrete recommendation in this format:

```
[DIMENSION]
  Current  →  Recommended
  Reason: <one line explaining why, with specific numbers>
```

Standard recommendation logic:

- **Concurrency**: If latency-elevated and concurrency > 1 → set to `1` for I/O-bound workloads
- **Memory**: If peak > 85% of limit → increase to `peak × 1.4` rounded up to nearest 128 MiB. If fixing concurrency will reduce peak, estimate per-instance usage first.
- **CPU**: If peak > 85% → increase. If peak < 30% and CPU > 1 → halve it.
- **Min instances**: If avg active < min_instances by more than 2 → reduce min; set to 0 if workload is async/PubSub.
- **Max instances**: If peak ever < 30% of max → cap at `peak × 2` to prevent runaway scaling costs.

---

### 6. Output format

Present the full report in this structure:

```
================================================================
  Cloud Run Analyzer  |  <service-name>
================================================================
  Project : <project>
  Region  : <region>
  Period  : last <days> days

── CURRENT CONFIGURATION ──────────────────────────────────────
  CPU          : X vCPU
  Memory       : X MiB (X GiB)
  Min instances: X
  Max instances: X
  Concurrency  : X
  Timeout      : Xs

── REQUEST COUNT ───────────────────────────────────────────────
  Total (Xd)   : X,XXX
  Avg / hour   : X.X
  Peak hour    : X

── LATENCY ─────────────────────────────────────────────────────
  [OK/WARNING/CRITICAL]  p50 avg : Xs   peak=Xs   (timeout=Xs)
  [OK/WARNING/CRITICAL]  p99 avg : Xs   peak=Xs
  ROOT CAUSE (if any)

── CPU ─────────────────────────────────────────────────────────
  [status]  p50 avg : X%  = X.XXX vCPU
  [status]  p99 peak: X%  = X.XXX vCPU

── MEMORY ──────────────────────────────────────────────────────
  [status]  p50 avg : X%  = X MiB  (limit=X MiB)
  [status]  p99 peak: X%  = X MiB

── INSTANCE COUNT ──────────────────────────────────────────────
  [status]  Peak ever  : X  (max_instances=X)
  [status]  Avg active : X.X   median=X.X  (min_instances=X)

── RECOMMENDATIONS ─────────────────────────────────────────────

  Concurrency
    80  →  1
    Request queuing at concurrency=80 is the primary driver of ...

  Memory
    8192 MiB  →  1024 MiB
    After fixing concurrency=1, ...
  
  (or: "No major issues — configuration looks healthy.")

================================================================
```

Use markdown bold/emphasis in your output where it aids readability. If metric data is unavailable for a section, note "No data" and skip that section's recommendations.
