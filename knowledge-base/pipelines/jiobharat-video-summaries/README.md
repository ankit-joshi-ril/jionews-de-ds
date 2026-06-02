# JioBharat Video Summaries Pipeline

## Pipeline Identity

| Field | Value |
|---|---|
| **Pipeline Name** | JioBharat Video Summaries |
| **Pipeline ID** | `jiobharat-video-summaries` |
| **GCP Project** | `jiox-328108` (Project Number: `266686822828`) |
| **Domain** | Data Engineering - Content Distribution |
| **Content Type** | Audio summaries with branded thumbnail images |
| **Output** | SFTP delivery to `mediaftp1.ril.com:33001` |

## Purpose

This pipeline aggregates audio news summaries from the production MongoDB, generates branded thumbnail images using a headless Chromium-based Image Attributor service, and delivers both the audio (MP3) and image (JPEG) files to an SFTP server for consumption by JioBharat devices. It processes summaries across 8 Indian languages, organizing deliveries into language-specific folders.

## Pipeline Overview

The pipeline consists of two Cloud Functions and one supporting FastAPI microservice:

1. **Stage 1 (JioBharat_AggregateSummariesPROD):** Reads today's audio summaries from the PROD MongoDB, deduplicates against previously processed records in the DE MongoDB, and publishes unprocessed summaries to Pub/Sub.
2. **Stage 2 (jiobharat-pushtosftpprod):** For each summary, requests a branded image from the Image Attributor service, downloads the audio from GCS, downloads the generated image from GCS, and uploads both files to the SFTP server.
3. **Image Attributor (FastAPI service):** Renders a Jinja2 HTML template with summary metadata, captures a screenshot using headless Chromium (pyppeteer), and stores the resulting JPEG in GCS.

## Supported Languages

| Language Code | Language | SFTP Folder Name |
|---|---|---|
| `HIN` | Hindi | `taaza_kabrein_hin` |
| `TAM` | Tamil | `ungal_Seithigal_tam` |
| `TEL` | Telugu | `itivali_varthalu_tel` |
| `KAN` | Kannada | `pramukha_Suddi_kan` |
| `MAR` | Marathi | `taajya_baatmya_mar` |
| `BAN` | Bangla | `tatka_sangbad_ban` |
| `MAL` | Malayalam | `puthiya_varthakal_mal` |
| `GUJ` | Gujarati | `taaza_samachar_guj` |

## Key Characteristics

- **Cross-Database Operation:** Reads from PROD MongoDB (`pie-production.summaries`), writes status to DE MongoDB (`ingestion-data.jio_bharat_summaries`)
- **Image Generation:** Headless Chromium renders branded HTML templates to JPEG images
- **Multi-Channel Delivery:** Audio (MP3) and images (JPEG) delivered via SFTP
- **Language-Partitioned:** Content organized into 8 language-specific SFTP folders
- **Daily Aggregation:** Processes today's summaries (full IST day), limited to 50 per language
- **Filters:** Only audio-generated, non-breaking summaries are included

## Infrastructure Components

| Component | Type | Name/Identifier |
|---|---|---|
| Cloud Function 1 | HTTP-triggered | JioBharat_AggregateSummariesPROD |
| Cloud Function 2 | Pub/Sub-triggered | jiobharat-pushtosftpprod |
| FastAPI Service | Microservice | Image Attributor (`service.jionews.com`) |
| Pub/Sub Topic | Message bus | `JioBharat_AggregateSummariesProd` |
| GCS Bucket | Audio storage | `audio-summaries-bucket` |
| GCS Bucket | Image storage | `img-cdn-bucket` |
| SFTP Server | File delivery | `mediaftp1.ril.com:33001` |
| PROD MongoDB | Source database | `pie-production.summaries` |
| DE MongoDB | Status tracking | `ingestion-data.jio_bharat_summaries` |
| Secret Manager | Credentials | `mongosh_de_uri` |

## Quick Links

| Document | Description |
|---|---|
| [AS-IS.md](./AS-IS.md) | Current operational state and known issues |
| [DATA-SPEC.md](./DATA-SPEC.md) | Input/output data specifications and schemas |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System architecture with Mermaid diagrams |
| [DATABASE-SCHEMA.md](./DATABASE-SCHEMA.md) | MongoDB collection schemas and indexes |
| [TECH-SPEC.md](./TECH-SPEC.md) | Technical implementation details |

## Upstream Dependencies

| Dependency | Type | Description |
|---|---|---|
| PROD MongoDB `pie-production.summaries` | Database | Source of audio summaries |
| GCS `audio-summaries-bucket/prd/` | Storage | Audio MP3 files |
| Image Attributor API | Internal service | Generates branded thumbnail images |
| GCS `img-cdn-bucket/jio_bharat/` | Storage | Generated thumbnail images |

## Downstream Consumers

| Consumer | Interface | Description |
|---|---|---|
| JioBharat devices | SFTP `mediaftp1.ril.com:33001` | Consumes audio + image files from language folders |
