# JioNews DE-DS — AI-Native Knowledge Base

> **Purpose:** Canonical source of truth for all Data Engineering and Data Science systems at JioNews
> **Audience:** AI agents, human engineers, automated workflows
> **GCP Project:** `jiox-328108` (Project Number: `266686822828`)

---

## What Is This?

This knowledge base is the central documentation layer for the JioNews DE-DS platform. It is designed to be consumed by AI agents operating in an AI-native SDLC workflow. Every document is structured for machine readability while maintaining human clarity.

**This is NOT a wiki. This is an operational specification.**

---

## Folder Structure

```
knowledge-base/
├── CONSTITUTION.md                      # MANDATORY — Governing rules for all AI agents
├── README.md                            # This file — Knowledge base guide
├── MASTER-AS-IS-ARCHITECTURE.md         # Complete system architecture (Mermaid diagrams)
│
├── pipelines/                           # Per-pipeline documentation
│   ├── headlines-ingestion/
│   │   ├── README.md                    # Pipeline overview and quick reference
│   │   ├── AS-IS.md                     # Current-state pipeline specification
│   │   ├── DATA-SPEC.md                 # Input/output data schemas
│   │   ├── ARCHITECTURE.md              # Mermaid diagrams and component topology
│   │   ├── DATABASE-SCHEMA.md           # MongoDB collection schemas
│   │   └── TECH-SPEC.md                 # Technical implementation details
│   ├── summaries-ingestion/             # (same structure)
│   ├── youtube-videos-ingestion/        # (same structure)
│   ├── native-videos-ingestion/         # (same structure)
│   ├── video-transcoder-workflow/       # (same structure)
│   ├── youtube-shorts-ingestion/        # (same structure)
│   ├── native-shorts-ingestion/         # (same structure)
│   ├── webstories-ingestion/            # (same structure)
│   ├── jiobharat-video-summaries/       # (same structure)
│   ├── auto-summarization/              # (same structure)
│   └── rss-feed-generation/             # (same structure)
│
├── shared/                              # Cross-pipeline shared components
│   ├── image-cdn/
│   │   ├── AS-IS.md                     # Image CDN processing pipeline
│   │   └── TECH-SPEC.md                 # Rendition sizes, formats, defaults
│   ├── llm-integration/
│   │   ├── AS-IS.md                     # Gemini integration architecture
│   │   └── TECH-SPEC.md                 # Prompts, models, retry logic
│   ├── redis-caching/
│   │   └── AS-IS.md                     # Deduplication cache architecture
│   └── infrastructure/
│       ├── MONGODB-REGISTRY.md          # All collections, schemas, operations
│       ├── PUBSUB-REGISTRY.md           # All topics, publishers, consumers
│       ├── GCS-REGISTRY.md              # All buckets, paths, access patterns
│       ├── SECRETS-REGISTRY.md          # All Secret Manager entries
│       └── EXTERNAL-DEPENDENCIES.md     # All external APIs, SFTP, CDNs
│
└── skills/                              # Automated micro-agent skills
    ├── README.md                        # Skills index and usage guide
    ├── headlines-publisher-onboarding/
    │   └── SKILL.md                     # Feed validation + config onboarding
    ├── native-videos-publisher-onboarding/
    │   └── SKILL.md                     # MRSS validation + MP4 checks + 1080p
    ├── feed-health-check/
    │   └── SKILL.md                     # Cross-pipeline feed monitoring
    ├── summaries-hygiene-monitor/
    │   └── SKILL.md                     # Hygiene pass rate tracking
    ├── pipeline-execution-monitor/
    │   └── SKILL.md                     # Pipeline run status + alerts
    ├── redis-cache-monitor/
    │   └── SKILL.md                     # Cache size, TTL, hit rates
    └── transcoder-status-monitor/
        └── SKILL.md                     # Transcoder queue + completion tracking
```

---

## How AI Agents Should Use This Knowledge Base

### Step 1: Read the Constitution FIRST

Before any task execution, read `CONSTITUTION.md`. It contains inviolable rules that govern all agent behavior. Non-compliance is a terminal offense.

### Step 2: Consult the Master Architecture

For understanding the full system: read `MASTER-AS-IS-ARCHITECTURE.md`. It provides the complete picture with Mermaid flow diagrams, cross-pipeline data flows, and infrastructure maps.

### Step 3: Drill Into Pipeline Docs

For pipeline-specific work, navigate to `pipelines/<pipeline-name>/`:

| File | Use When |
|---|---|
| `README.md` | Quick orientation — what this pipeline does |
| `AS-IS.md` | Understanding current implementation in detail |
| `DATA-SPEC.md` | Working with data schemas, field mappings, validations |
| `ARCHITECTURE.md` | Understanding component topology and data flow |
| `DATABASE-SCHEMA.md` | Working with MongoDB collections and documents |
| `TECH-SPEC.md` | Understanding technical implementation, libraries, configs |

### Step 4: Check Shared Components

For cross-cutting concerns (image processing, LLM, Redis, infrastructure registries), consult `shared/`.

### Step 5: Execute Skills

For automated tasks, consult `skills/<skill-name>/SKILL.md` for the skill definition, inputs, outputs, and execution rules.

---

## Document Conventions

### Mermaid Diagrams

All architecture and flow diagrams use **Mermaid** syntax. Render them in any Mermaid-compatible viewer.

### Data Schemas

All schemas use **JSON** representation with field-level type annotations and constraints.

### Tables

All registries use **Markdown tables** with consistent column ordering.

### Cross-References

Documents reference each other using relative paths: `../shared/infrastructure/PUBSUB-REGISTRY.md`

### Versioning

Each document includes a metadata header with version and last-updated date.

---

## Pipeline Index

| # | Pipeline | Directory | Content Type | Sources |
|---|---|---|---|---|
| 1 | Headlines Ingestion | `pipelines/headlines-ingestion/` | News headlines | RSS/JSON feeds |
| 2 | Summaries Ingestion | `pipelines/summaries-ingestion/` | Article summaries | RSS/JSON feeds + LLM |
| 3 | YouTube Videos | `pipelines/youtube-videos-ingestion/` | Full-length videos | YouTube scraping + API |
| 4 | Native Videos | `pipelines/native-videos-ingestion/` | Full-length videos | Partner API, Manual, MRSS |
| 5 | Video Transcoder | `pipelines/video-transcoder-workflow/` | HLS transcoding | SFTP + CPP/SAAS API |
| 6 | YouTube Shorts | `pipelines/youtube-shorts-ingestion/` | Short-form videos | YouTube scraping + API |
| 7 | Native Shorts | `pipelines/native-shorts-ingestion/` | Short-form videos | Partner API, Manual, MRSS |
| 8 | Webstories | `pipelines/webstories-ingestion/` | Web stories | Publisher APIs + RSS |
| 9 | JioBharat Summaries | `pipelines/jiobharat-video-summaries/` | Video summaries | PROD MongoDB + TTS + SFTP |
| 10 | Auto Summarization | `pipelines/auto-summarization/` | CMS summaries | HTTP API + Gemini LLM |
| 11 | RSS Feed Generation | `pipelines/rss-feed-generation/` | RSS XML feeds | MongoDB aggregation + GCS |

---

## Skills Index

| Skill | Directory | Purpose | Trigger |
|---|---|---|---|
| Headlines Publisher Onboarding | `skills/headlines-publisher-onboarding/` | Validate and onboard new RSS/JSON feeds | Manual |
| Native Videos Publisher Onboarding | `skills/native-videos-publisher-onboarding/` | Validate MRSS feeds, MP4 URLs, resolution | Manual |
| Feed Health Check | `skills/feed-health-check/` | Monitor all active feed URLs for availability | Scheduled / Manual |
| Summaries Hygiene Monitor | `skills/summaries-hygiene-monitor/` | Track hygiene pass/fail rates | Scheduled / Manual |
| Pipeline Execution Monitor | `skills/pipeline-execution-monitor/` | Check pipeline run status and detect failures | Scheduled / Manual |
| Redis Cache Monitor | `skills/redis-cache-monitor/` | Monitor cache sizes, memory, TTL compliance | Scheduled / Manual |
| Transcoder Status Monitor | `skills/transcoder-status-monitor/` | Track transcoder queue depth and completion rates | Scheduled / Manual |

---

## Maintenance Rules

1. **Code changes MUST trigger documentation updates** — If you modify a pipeline, update its docs
2. **Documentation MUST NOT drift from code** — Flag any drift you discover
3. **New pipelines MUST have full documentation** — All 5 standard files + README
4. **New skills MUST have a SKILL.md** — No undocumented skills
5. **The Constitution is immutable** — Only the repository owner may amend it
