# JioBharat Video Summaries - AS-IS State

## Current Operational State

| Attribute | Value |
|---|---|
| **Status** | Production |
| **Environment** | GCP `jiox-328108` |
| **Execution Runtime** | Python (Cloud Functions Gen1) + FastAPI microservice |
| **Source Database** | PROD MongoDB `pie-production.summaries` |
| **Status Database** | DE MongoDB `ingestion-data.jio_bharat_summaries` |
| **Delivery Target** | SFTP `mediaftp1.ril.com:33001` |

## Current Behavior

### Stage 1: JioBharat_AggregateSummariesPROD

1. Triggered via HTTP request (Cloud Scheduler or manual invocation).
2. Connects to the PROD MongoDB using a base64-encoded hardcoded connection URI in the source code.
3. Executes an aggregation pipeline against `pie-production.summaries`:
   - **$match:** Filters for documents where:
     - `createdAt` falls within today (full IST day, midnight to midnight)
     - `language.code` is one of: `HIN`, `TAM`, `TEL`, `KAN`, `MAR`, `BAN`, `MAL`, `GUJ`
     - `isAudioSummaryGenerated` is `true`
     - `isBreaking` is `false`
   - **$sort:** Orders by `createdAt` descending (newest first)
   - **$group:** Groups documents by language, collecting up to all documents per group
   - **$slice:** Limits to 50 documents per language using `$slice` on the grouped array
   - **$unwind + $replaceRoot:** Flattens the grouped arrays back to individual documents
4. Connects to the DE MongoDB (via `mongosh_de_uri` from Secret Manager).
5. Queries `ingestion-data.jio_bharat_summaries` to find already-processed summaries (where `isSuccess=true`).
6. Computes the set difference: summaries from PROD that have not yet been successfully processed.
7. Publishes each unprocessed summary to Pub/Sub topic `JioBharat_AggregateSummariesProd`.

### Stage 2: jiobharat-pushtosftpprod

For each summary received from Pub/Sub:

1. **Image Generation Request:**
   - Sends a POST request to `https://service.jionews.com/v1/image-attributor/generate-image`
   - Request body: `{ title, publisher, image_url, summary_id }`
   - The Image Attributor service renders a branded HTML template, takes a headless Chromium screenshot, and uploads the JPEG to GCS.

2. **Audio Download:**
   - Downloads the audio file from GCS: `audio-summaries-bucket/prd/{summary_id}.mp3`

3. **Image Download:**
   - Downloads the generated image from GCS: `img-cdn-bucket/jio_bharat/prod/{summary_id}.jpeg`

4. **SFTP Upload:**
   - Connects to `mediaftp1.ril.com:33001` using SFTP credentials (user: `FT_jionews_livenews`)
   - Determines the language folder based on the language code mapping
   - Uploads both files with the naming pattern:
     - Image: `/media/prod/{language_folder}/{summary_id}_{lang}_{dd_mm_yyyy}.jpeg`
     - Audio: `/media/prod/{language_folder}/{summary_id}_{lang}_{dd_mm_yyyy}.mp3`

5. **Status Recording:**
   - Inserts a status document into DE MongoDB `ingestion-data.jio_bharat_summaries`
   - Records `isSuccess=true` on successful upload, or `isSuccess=false` with `errorMessage` on failure

### Image Attributor Service (FastAPI)

1. Receives POST request at `/v1/image-attributor/generate-image`.
2. Populates a Jinja2 HTML template with the summary's `title`, `publisher`, and `image_url`.
3. Launches a headless Chromium browser via `pyppeteer` with the following configuration:
   - Viewport: 1920x1080
   - Args: `--no-sandbox`, `--disable-setuid-sandbox`
4. Renders the HTML template and captures a JPEG screenshot.
5. Uploads the screenshot to GCS: `img-cdn-bucket/jio_bharat/{summary_id}.jpeg`
6. Returns the GCS path in the API response.

## Language Folder Mapping

| Language Code | SFTP Folder Name | Language |
|---|---|---|
| `HIN` | `taaza_kabrein_hin` | Hindi |
| `KAN` | `pramukha_Suddi_kan` | Kannada |
| `TAM` | `ungal_Seithigal_tam` | Tamil |
| `TEL` | `itivali_varthalu_tel` | Telugu |
| `MAR` | `taajya_baatmya_mar` | Marathi |
| `BAN` | `tatka_sangbad_ban` | Bangla |
| `GUJ` | `taaza_samachar_guj` | Gujarati |
| `MAL` | `puthiya_varthakal_mal` | Malayalam |

## Known Limitations and Considerations

### Hardcoded PROD MongoDB URI

- The PROD MongoDB connection URI is base64-encoded and hardcoded directly in the source code of `JioBharat_AggregateSummariesPROD`.
- This is a security concern and deviates from the standard practice of using GCP Secret Manager.
- Any changes to the PROD MongoDB credentials require a code deployment.

### Dual Database Access

- Stage 1 connects to two separate MongoDB instances:
  1. PROD MongoDB (`pie-production`) for reading source summaries
  2. DE MongoDB (`ingestion-data`) for deduplication status checks
- Network issues with either database will cause the function to fail.

### IST Day Boundary

- The aggregation uses IST (Indian Standard Time, UTC+5:30) day boundaries for the `createdAt` filter.
- Summaries created near midnight IST may be missed or included depending on the exact execution time.

### 50 Per Language Limit

- The `$slice` operation limits output to 50 summaries per language per execution.
- If more than 50 summaries are generated for a language in a day, only the 50 most recent are processed.

### Image Attributor Dependency

- The Image Attributor FastAPI service must be running and accessible at `service.jionews.com`.
- It uses headless Chromium (`pyppeteer`), which has specific system dependencies and can be resource-intensive.
- Chromium is launched with `--no-sandbox` for container compatibility, which has security implications.

### SFTP Reliability

- SFTP uploads to `mediaftp1.ril.com:33001` depend on network connectivity and server availability.
- Failed uploads result in `isSuccess=false` status records, but there is no automatic retry mechanism.
- The SFTP connection uses user `FT_jionews_livenews`.

### Sequential Processing

- Each summary in Stage 2 involves multiple sequential operations: image generation API call, audio download, image download, SFTP upload.
- Any step failure for a summary results in a failed status record for that summary.

## Error Handling

| Scenario | Current Behavior |
|---|---|
| PROD MongoDB unreachable | Function fails with connection error |
| DE MongoDB unreachable | Function fails; cannot perform dedup |
| No summaries match aggregation | No messages published; function exits cleanly |
| Image Attributor API failure | Summary marked `isSuccess=false` with error message |
| Audio file not found in GCS | Summary marked `isSuccess=false` with error message |
| Image file not found in GCS | Summary marked `isSuccess=false` with error message |
| SFTP connection failure | Summary marked `isSuccess=false` with error message |
| SFTP upload failure | Summary marked `isSuccess=false` with error message |
| Pub/Sub publish failure | Message lost; summary not processed |

## Operational Notes

- The pipeline runs daily and processes only today's summaries (IST day boundary).
- SFTP file naming includes the date (`dd_mm_yyyy`) to prevent filename collisions across days.
- The Image Attributor service is shared infrastructure, also used by other pipelines.
- GCS buckets used: `audio-summaries-bucket` (audio source) and `img-cdn-bucket` (image generation target and source).
