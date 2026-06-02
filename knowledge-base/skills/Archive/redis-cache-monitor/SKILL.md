# Skill: redis-cache-monitor

## Metadata

| Field          | Value                                                              |
|----------------|--------------------------------------------------------------------|
| **Skill ID**   | `redis-cache-monitor`                                              |
| **Version**    | 1.0.0                                                              |
| **Purpose**    | Monitor Redis sorted set sizes, memory usage, and TTL compliance   |
| **Trigger**    | Scheduled (every 15 minutes recommended) or Manual                 |
| **Run Mode**   | Always dry-run. This skill is read-only and never mutates data.    |
| **Mutates**    | Never                                                              |
| **Owner**      | DE-DS Platform Team                                                |

---

## Purpose

The DE-DS pipelines use Redis sorted sets as deduplication caches. Each pipeline stores document IDs or title hashes with timestamps as scores, enabling time-based expiry. This skill monitors the health of these caches by checking set sizes, identifying expired entries, measuring memory usage, and verifying TTL compliance.

Unhealthy Redis caches can cause either duplicate content (if the cache is down or empty) or memory exhaustion (if expired entries are not being cleaned up).

This is a read-only monitoring skill. It executes only Redis read commands (ZCARD, ZRANGEBYSCORE, INFO, DBSIZE, DEBUG OBJECT). It never writes to or modifies Redis state.

---

## Inputs

```json
{}
```

No required inputs. This skill monitors all known sorted sets and the overall Redis instance.

---

## Redis Connection

| Parameter  | Value                                                                |
|------------|----------------------------------------------------------------------|
| Host       | `34.93.131.211`                                                      |
| Port       | `6379`                                                               |
| Database   | `0` (default)                                                        |
| Auth       | Use credentials from environment variable `REDIS_PASSWORD` or config |

---

## Monitored Sorted Sets

| Sorted Set Name            | Pipeline         | Description                                    |
|----------------------------|------------------|------------------------------------------------|
| `de_headlines_id_cache`    | Headlines        | Dedup cache keyed by article ID/URL            |
| `de_headlines_title_cache` | Headlines        | Dedup cache keyed by normalized title hash     |
| `de_summaries_cache`       | Summaries        | Dedup cache for summaries pipeline             |
| `de_videos_id_cache`       | YouTube Videos   | Dedup cache for YouTube video IDs              |
| `de_mrss_videos_cache`     | Native Videos    | Dedup cache for MRSS native video entries      |
| `de_mrss_shorts_cache`     | Native Shorts    | Dedup cache for MRSS native shorts entries     |

---

## Execution Steps

### Step 1: Connect to Redis

- Establish connection to Redis at `34.93.131.211:6379`.
- Authenticate if `REDIS_PASSWORD` is set.
- Execute `PING` to verify connectivity.
- Record `connection_successful: bool` and `ping_latency_ms`.
- **FAIL** if connection cannot be established within 5 seconds.

### Step 2: Check Each Sorted Set

For each sorted set in the monitored list:

#### 2a. Get Total Entry Count

```
ZCARD <set_name>
```
Record `total_entries`.

#### 2b. Count Expired Entries

Entries use Unix timestamp (seconds) as the score. Entries with score < current time are considered expired (their TTL has passed but they have not yet been cleaned up by the application).

```
ZCOUNT <set_name> -inf <current_unix_timestamp>
```
Record `expired_entries`.

#### 2c. Count Active (Non-Expired) Entries

```
ZCOUNT <set_name> <current_unix_timestamp> +inf
```
Record `active_entries`.

Validate: `active_entries + expired_entries == total_entries`.

#### 2d. Sample TTL Distribution

Retrieve a sample of 10 entries from the set to analyze TTL distribution:

```
ZRANGEBYSCORE <set_name> <current_unix_timestamp> +inf WITHSCORES LIMIT 0 10
```

For each sampled entry:
- Calculate `remaining_ttl_hours = (score - current_unix_timestamp) / 3600`.
- Record the `min_ttl_hours`, `max_ttl_hours`, and `avg_ttl_hours` across the sample.

Expected TTL ranges:
- Headlines caches: entries should have 24-48 hour TTLs.
- Summaries cache: entries should have 24-48 hour TTLs.
- Video caches: entries should have 48-72 hour TTLs.

**WARN** if average TTL for any set deviates significantly from expected range.

#### 2e. Estimate Memory Usage for Set

Use `DEBUG OBJECT` (if available) or `MEMORY USAGE` command on a sample key to estimate per-entry memory, then multiply by total_entries:

```
MEMORY USAGE <set_name>
```

If `MEMORY USAGE` is not available, estimate based on:
- Average entry size: ~200 bytes (key + score overhead).
- Set memory estimate: `total_entries * 200 bytes`.

Record `memory_estimate_bytes`.

#### 2f. Check for Empty Sets

- If `total_entries == 0` for a set that should have entries (all caches should be non-empty during normal operation):
  - **CRITICAL**: The dedup cache is empty. This means all incoming content will be treated as new, potentially causing duplicates in the output.

#### 2g. Check for Excessive Size

- If `total_entries > 10,000,000` (10 million):
  - **WARNING**: Cache is very large. Check if cleanup jobs are running.
- If `expired_entries > (total_entries * 0.5)`:
  - **WARNING**: More than 50% of entries are expired. Cleanup may be stalled.

### Step 3: Get Redis Server Info

Execute Redis `INFO` command and extract key metrics:

```
INFO memory
INFO stats
INFO server
```

Extract and record:

| Metric                          | Redis Field                    | Description                           |
|---------------------------------|--------------------------------|---------------------------------------|
| `redis_version`                 | `server.redis_version`         | Server version                        |
| `used_memory_bytes`             | `memory.used_memory`           | Total memory used by Redis            |
| `used_memory_human`             | `memory.used_memory_human`     | Human-readable memory (e.g., "2.5G")  |
| `used_memory_peak_bytes`        | `memory.used_memory_peak`      | Peak memory usage                     |
| `used_memory_peak_human`        | `memory.used_memory_peak_human`| Human-readable peak memory            |
| `maxmemory_bytes`               | `memory.maxmemory`             | Configured memory limit (0=unlimited) |
| `maxmemory_policy`              | `memory.maxmemory_policy`      | Eviction policy                       |
| `mem_fragmentation_ratio`       | `memory.mem_fragmentation_ratio`| Memory fragmentation ratio           |
| `connected_clients`             | `stats.connected_clients`      | Number of connected clients           |
| `total_commands_processed`      | `stats.total_commands_processed`| Total commands since start           |
| `evicted_keys`                  | `stats.evicted_keys`           | Keys evicted due to memory pressure   |

### Step 4: Get Total Key Count

```
DBSIZE
```

Record `total_keys`. This includes all keys, not just sorted sets.

### Step 5: Memory Health Assessment

Evaluate Redis memory health:

| Condition                                                       | Status       |
|-----------------------------------------------------------------|--------------|
| `used_memory < maxmemory * 0.7` (or no limit set)              | `healthy`    |
| `used_memory >= maxmemory * 0.7` and `< maxmemory * 0.9`       | `warning`    |
| `used_memory >= maxmemory * 0.9`                                | `critical`   |
| `evicted_keys > 0` (keys being evicted due to memory pressure) | `critical`   |
| `mem_fragmentation_ratio > 1.5`                                 | `warning`    |
| `mem_fragmentation_ratio > 2.0`                                 | `critical`   |

---

## Confidence Score Calculation

| Condition                                              | Points |
|--------------------------------------------------------|--------|
| Redis connection successful                            | +25    |
| All 6 sorted sets exist and are queryable              | +15    |
| No sorted set is empty (all have entries)              | +15    |
| Expired entries < 50% of total in all sets             | +10    |
| TTL distribution within expected ranges                | +10    |
| Memory usage < 70% of max (or no max set)              | +10    |
| No evicted keys                                        | +10    |
| Fragmentation ratio < 1.5                              | +5     |
| **Total possible**                                     | **100**|

Deductions:
- Redis connection failure: confidence = 0, status = failed
- Each empty sorted set: -15 points
- Each set with > 50% expired entries: -5 points
- Memory > 90% of max: -15 points
- Evicted keys > 0: -10 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "redis-cache-monitor",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {},
  "output": {
    "connection": {
      "host": "34.93.131.211",
      "port": 6379,
      "connected": true,
      "ping_latency_ms": 3
    },
    "sorted_sets": [
      {
        "name": "de_headlines_id_cache",
        "pipeline": "headlines",
        "total_entries": 245000,
        "active_entries": 180000,
        "expired_entries": 65000,
        "expired_percent": 26.5,
        "ttl_sample": {
          "min_ttl_hours": 2.3,
          "max_ttl_hours": 47.8,
          "avg_ttl_hours": 24.1
        },
        "memory_estimate_bytes": 49000000,
        "memory_estimate_human": "46.7 MB",
        "status": "healthy"
      },
      {
        "name": "de_headlines_title_cache",
        "pipeline": "headlines",
        "total_entries": 245000,
        "active_entries": 178000,
        "expired_entries": 67000,
        "expired_percent": 27.3,
        "ttl_sample": {
          "min_ttl_hours": 1.8,
          "max_ttl_hours": 47.5,
          "avg_ttl_hours": 23.8
        },
        "memory_estimate_bytes": 49000000,
        "memory_estimate_human": "46.7 MB",
        "status": "healthy"
      },
      {
        "name": "de_summaries_cache",
        "pipeline": "summaries",
        "total_entries": 120000,
        "active_entries": 95000,
        "expired_entries": 25000,
        "expired_percent": 20.8,
        "ttl_sample": {
          "min_ttl_hours": 3.5,
          "max_ttl_hours": 46.2,
          "avg_ttl_hours": 25.0
        },
        "memory_estimate_bytes": 24000000,
        "memory_estimate_human": "22.9 MB",
        "status": "healthy"
      },
      {
        "name": "de_videos_id_cache",
        "pipeline": "youtube_videos",
        "total_entries": 35000,
        "active_entries": 28000,
        "expired_entries": 7000,
        "expired_percent": 20.0,
        "ttl_sample": {
          "min_ttl_hours": 12.0,
          "max_ttl_hours": 71.5,
          "avg_ttl_hours": 48.2
        },
        "memory_estimate_bytes": 7000000,
        "memory_estimate_human": "6.7 MB",
        "status": "healthy"
      },
      {
        "name": "de_mrss_videos_cache",
        "pipeline": "native_videos",
        "total_entries": 8000,
        "active_entries": 6500,
        "expired_entries": 1500,
        "expired_percent": 18.8,
        "ttl_sample": {
          "min_ttl_hours": 15.0,
          "max_ttl_hours": 70.3,
          "avg_ttl_hours": 50.1
        },
        "memory_estimate_bytes": 1600000,
        "memory_estimate_human": "1.5 MB",
        "status": "healthy"
      },
      {
        "name": "de_mrss_shorts_cache",
        "pipeline": "native_shorts",
        "total_entries": 6000,
        "active_entries": 5000,
        "expired_entries": 1000,
        "expired_percent": 16.7,
        "ttl_sample": {
          "min_ttl_hours": 18.0,
          "max_ttl_hours": 69.8,
          "avg_ttl_hours": 49.5
        },
        "memory_estimate_bytes": 1200000,
        "memory_estimate_human": "1.1 MB",
        "status": "healthy"
      }
    ],
    "redis_server": {
      "redis_version": "7.0.12",
      "used_memory_bytes": 536870912,
      "used_memory_human": "512.0 MB",
      "used_memory_peak_bytes": 644245094,
      "used_memory_peak_human": "614.5 MB",
      "maxmemory_bytes": 2147483648,
      "maxmemory_human": "2.0 GB",
      "maxmemory_policy": "noeviction",
      "mem_fragmentation_ratio": 1.12,
      "connected_clients": 15,
      "evicted_keys": 0,
      "memory_usage_percent": 25.0,
      "memory_status": "healthy"
    },
    "total_keys": 18,
    "summary": {
      "total_sorted_sets_monitored": 6,
      "healthy_sets": 6,
      "warning_sets": 0,
      "critical_sets": 0,
      "total_cache_entries": 659000,
      "total_active_entries": 492500,
      "total_expired_entries": 166500,
      "overall_expired_percent": 25.3
    }
  },
  "validation_status": "passed",
  "confidence_score": 95,
  "issues": [],
  "recommendations": [
    "Expired entries comprise 25.3% of total cache entries. While within acceptable range, a cleanup job could reclaim ~125 MB of memory.",
    "Consider running ZREMRANGEBYSCORE periodically to remove expired entries from sorted sets."
  ],
  "alerts": []
}
```

---

## Dry-Run Behavior

This skill is **always read-only**. The `--execute` flag has no additional effect. The skill:

- Executes only read commands against Redis: `PING`, `ZCARD`, `ZCOUNT`, `ZRANGEBYSCORE` (with LIMIT), `INFO`, `DBSIZE`, `MEMORY USAGE`.
- **Never** executes write commands: no `SET`, `ZADD`, `ZREM`, `ZREMRANGEBYSCORE`, `DEL`, `FLUSHDB`, or any mutation.
- Produces a JSON report.
- **Never** modifies Redis data, configuration, or any other persistent state.

---

## Error Handling

| Error Condition                              | Behavior                                                      |
|----------------------------------------------|---------------------------------------------------------------|
| Redis connection failure                     | Set confidence=0, status=failed, record connection error      |
| Redis authentication failure                 | Set confidence=0, status=failed, note auth issue              |
| Individual sorted set does not exist         | Record as total_entries=0, status=critical (cache missing)    |
| MEMORY USAGE command not available           | Fall back to estimation (200 bytes/entry), note in output     |
| INFO command restricted                      | Skip server metrics, reduce confidence, note in issues        |
| Redis latency > 100ms per command            | Record as degraded performance, add to issues                 |

---

## Alerting Thresholds

| Condition                                              | Alert Level |
|--------------------------------------------------------|-------------|
| Redis connection failure                               | CRITICAL    |
| Any sorted set is empty (0 entries)                    | CRITICAL    |
| Any sorted set has > 80% expired entries               | CRITICAL    |
| Memory usage > 90% of maxmemory                        | CRITICAL    |
| Evicted keys > 0                                       | CRITICAL    |
| Any sorted set has > 50% expired entries               | WARNING     |
| Memory usage 70-90% of maxmemory                       | WARNING     |
| Memory fragmentation ratio > 1.5                       | WARNING     |
| Any sorted set has > 5 million entries                 | WARNING     |
| Redis latency > 50ms                                   | WARNING     |
