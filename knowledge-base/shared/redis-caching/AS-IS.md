# Redis Caching -- AS-IS State

> **Document Classification:** SHARED COMPONENT -- Current State Specification
> **Component:** Redis Deduplication Cache
> **GCP Project:** `jiox-328108` (Project Number: `266686822828`)
> **Last Updated:** 2026-03-10
> **Version:** 1.0.0

---

## Overview

Redis serves as the centralized deduplication layer for the JioNews DE platform. All ingestion pipelines that require real-time deduplication use a shared Redis instance with **Sorted Sets (ZSets)** and time-based expiration scores. This provides a fast, TTL-aware dedup mechanism that automatically expires stale entries without explicit cleanup jobs.

---

## Architecture

```mermaid
flowchart TD
    subgraph Pipelines["Ingestion Pipelines"]
        HL["Headlines\nIngestion"]
        SM["Summaries\nIngestion"]
        YV["YouTube Videos\nIngestion"]
        MV["MRSS Videos\nIngestion"]
        MS["MRSS Shorts\nIngestion"]
    end

    subgraph Redis["Redis Instance\n34.93.131.211:6379"]
        HL_ID["de_headlines_id_cache\n(ZSet)"]
        HL_TITLE["de_headlines_title_cache\n(ZSet)"]
        SM_CACHE["de_summaries_cache\n(ZSet)"]
        YV_CACHE["de_videos_id_cache\n(ZSet)"]
        MV_CACHE["de_mrss_videos_cache\n(ZSet)"]
        MS_CACHE["de_mrss_shorts_cache\n(ZSet)"]
    end

    HL -->|"ZSCORE/ZADD"| HL_ID
    HL -->|"ZSCORE/ZADD"| HL_TITLE
    SM -->|"ZSCORE/ZADD"| SM_CACHE
    YV -->|"ZSCORE/ZADD"| YV_CACHE
    MV -->|"ZSCORE/ZADD"| MV_CACHE
    MS -->|"ZSCORE/ZADD"| MS_CACHE
```

---

## Connection Details

| Attribute | Value |
|---|---|
| **Host** | `34.93.131.211` |
| **Port** | `6379` |
| **Username** | `default` |
| **Password** | `developpd` |
| **Connection URI** | `redis://default:developpd@34.93.131.211:6379` |
| **Protocol** | Redis wire protocol (RESP) |
| **TLS** | Not configured |
| **Database** | `0` (default) |

---

## Data Structure: Sorted Sets (ZSets)

All deduplication caches use Redis **Sorted Sets** where:
- **Member** = the deduplication key (composite string)
- **Score** = expiration timestamp (Unix epoch in seconds, `now + TTL`)

This design allows:
1. O(log N) lookup via `ZSCORE`
2. O(log N) insertion via `ZADD`
3. Efficient bulk expiration via `ZREMRANGEBYSCORE`

---

## Cache Registry

| Set Name | Pipeline | Key Format | TTL | Score Formula |
|---|---|---|---|---|
| `de_headlines_id_cache` | Headlines Ingestion | `{link}_{category_id}_{language_id}` | 48 hours | `now + 172800` |
| `de_headlines_title_cache` | Headlines Ingestion | `normalized_title` | 48 hours | `now + 172800` |
| `de_summaries_cache` | Summaries Ingestion | `title` | 48 hours | `now + 172800` |
| `de_videos_id_cache` | YouTube Videos Ingestion | `{video_id}_{category_id}_{language_id}` | 48 hours | `now + 172800` |
| `de_mrss_videos_cache` | MRSS Videos Ingestion | `{title}_{link}_{category_id}_{language_id}` | 48 hours | `now + 172800` |
| `de_mrss_shorts_cache` | MRSS Shorts Ingestion | `{title}_{link}_{category_id}_{language_id}` | 48 hours | `now + 172800` |

**TTL Note:** 48 hours = 172,800 seconds. All caches use the same TTL value.

---

## Deduplication Pattern

### Lookup and Insert Flow

```mermaid
flowchart TD
    RECORD["Incoming Record"] --> KEY["Construct dedup key\n(pipeline-specific format)"]
    KEY --> ZSCORE["ZSCORE(set_name, key)"]
    ZSCORE --> CHECK{"Result\nis None?"}
    CHECK -->|"Yes (new record)"| ZADD["ZADD(set_name,\nscore=now+172800,\nkey)"]
    ZADD --> PASS["Record PASSES\n(continues pipeline)"]
    CHECK -->|"No (duplicate)"| FILTER["Record FILTERED OUT\n(silently dropped)"]
```

### Redis Command Sequence

**Check for duplicate:**
```
ZSCORE <set_name> <key>
```
- Returns `None` if the key does not exist (record is new)
- Returns the score (expiration timestamp) if the key exists (record is a duplicate)

**Insert new record:**
```
ZADD <set_name> <now + 172800> <key>
```
- Adds the key with a score equal to the current time plus 48 hours

### Cleanup (Expiration)

```
ZREMRANGEBYSCORE <set_name> -inf <now>
```

This command removes all entries whose score (expiration timestamp) is less than or equal to the current time. It is called periodically within the pipeline execution to clean up expired entries.

```mermaid
flowchart LR
    BEFORE["Sorted Set\n(with expired entries)"] --> CLEANUP["ZREMRANGEBYSCORE\n(set, -inf, now)"]
    CLEANUP --> AFTER["Sorted Set\n(only valid entries)"]
```

---

## Pipeline-Specific Key Formats

### Headlines Ingestion (Dual Dedup)

Headlines use **two independent** dedup checks. Both must pass for a record to proceed:

```mermaid
flowchart TD
    RECORD["Headline Record"] --> ID_CHECK["Check 1: ID-based\nde_headlines_id_cache"]
    ID_CHECK -->|"Duplicate"| DROP["Record dropped"]
    ID_CHECK -->|"New"| TITLE_CHECK["Check 2: Title-based\nde_headlines_title_cache"]
    TITLE_CHECK -->|"Duplicate"| DROP
    TITLE_CHECK -->|"New"| PASS["Record passes\n(add to both caches)"]
```

**ID Cache Key:** `{link}_{category_id}_{language_id}`
- Composite of the article URL, category identifier, and language identifier
- Prevents the same article URL from being ingested twice for the same category/language combination

**Title Cache Key:** `normalized_title`
- The article title after normalization (lowercase, stripped of whitespace)
- Prevents near-duplicate articles with identical titles from different publishers

### Summaries Ingestion

**Key:** `title`
- The summary title string
- Single-field key; no composite with category or language

### YouTube Videos Ingestion

**Key:** `{video_id}_{category_id}_{language_id}`
- YouTube video identifier combined with category and language
- Allows the same video to exist in different category/language combinations

### MRSS Videos Ingestion

**Key:** `{title}_{link}_{category_id}_{language_id}`
- Four-field composite key
- Includes both title and link to differentiate videos with the same title from different sources

### MRSS Shorts Ingestion

**Key:** `{title}_{link}_{category_id}_{language_id}`
- Same format as MRSS Videos
- Separate cache set to allow independent TTL management

---

## Operational Characteristics

| Metric | Value |
|---|---|
| **Total cache sets** | 6 |
| **Uniform TTL** | 48 hours (172,800 seconds) |
| **Data structure** | Sorted Set (ZSet) |
| **Lookup complexity** | O(log N) per check |
| **Insert complexity** | O(log N) per insert |
| **Cleanup complexity** | O(log N + M) where M = expired entries |
| **Persistence** | Not configured (in-memory only) |

---

## Known Issues and Technical Debt

| ID | Issue | Severity | Impact |
|---|---|---|---|
| RD-01 | No TLS encryption on Redis connection | High | Credentials and data transmitted in plaintext |
| RD-02 | Password stored in application code / env vars | Medium | Credential management not centralized via Secret Manager |
| RD-03 | Single Redis instance (no replication or sentinel) | Medium | Single point of failure for all dedup operations |
| RD-04 | No Redis persistence configured | Medium | Full cache loss on instance restart; temporary re-ingestion of duplicates |
| RD-05 | Cleanup runs inline during pipeline execution | Low | Adds latency to pipeline; could be offloaded to a scheduled job |
| RD-06 | Title normalization for headlines is basic (lowercase + strip) | Low | Slight title variations bypass dedup (e.g., punctuation differences) |
| RD-07 | All pipelines share one Redis instance with no namespace isolation | Low | Risk of key collisions if set names are not carefully managed |

---

## Integration Points

| System | Direction | Protocol | Purpose |
|---|---|---|---|
| Headlines Ingestion (`processheadlines`) | Bidirectional | Redis | Dual dedup (ID + title) |
| Summaries Ingestion | Bidirectional | Redis | Title dedup |
| YouTube Videos (`ProcessYTChannelsData`) | Bidirectional | Redis | Video ID dedup |
| MRSS Videos Ingestion | Bidirectional | Redis | Composite key dedup |
| MRSS Shorts Ingestion | Bidirectional | Redis | Composite key dedup |
