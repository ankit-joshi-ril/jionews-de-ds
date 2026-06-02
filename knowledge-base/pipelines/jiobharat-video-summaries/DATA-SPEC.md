# JioBharat Video Summaries - Data Specification

## Data Flow Summary

```
PROD MongoDB (summaries) -> Aggregation + Dedup -> Pub/Sub ->
  -> Image Attributor (generates JPEG) -> GCS
  -> GCS (audio MP3) download
  -> GCS (image JPEG) download
  -> SFTP upload (audio + image)
  -> DE MongoDB (status tracking)
```

## Input Data

### PROD MongoDB: `pie-production.summaries`

| Attribute | Value |
|---|---|
| **Database** | `pie-production` |
| **Collection** | `summaries` |
| **Connection** | Base64-encoded hardcoded URI in source code |
| **Access Pattern** | Aggregation pipeline with date, language, and status filters |

#### Aggregation Pipeline

```
$match -> $sort -> $group -> $slice -> $unwind -> $replaceRoot
```

**$match Criteria:**

| Field | Condition | Description |
|---|---|---|
| `createdAt` | Today (full IST day, midnight-midnight) | Only today's summaries |
| `language.code` | `$in: [HIN, TAM, TEL, KAN, MAR, BAN, MAL, GUJ]` | 8 supported languages |
| `isAudioSummaryGenerated` | `true` | Only summaries with audio |
| `isBreaking` | `false` | Exclude breaking news summaries |

**$sort:** `{ createdAt: -1 }` (newest first)

**$group:** Group by `language`, collect all matching documents per language

**$slice:** Limit to 50 documents per language group

**$unwind + $replaceRoot:** Flatten groups back to individual documents

#### Relevant Source Document Fields

| Field | Type | Description |
|---|---|---|
| `_id` | ObjectId | Summary identifier (used as `summary_id`) |
| `title` | String | Summary headline text |
| `language.code` | String | Language code (HIN, TAM, TEL, etc.) |
| `publisher` | String | Source publisher name |
| `thumbnailUrl` | String | Original image URL for the summary |
| `createdAt` | Date | Summary creation timestamp |
| `isAudioSummaryGenerated` | Boolean | Whether audio has been generated |
| `isBreaking` | Boolean | Whether this is a breaking news summary |

### GCS Audio Files

| Attribute | Value |
|---|---|
| **Bucket** | `audio-summaries-bucket` |
| **Path Pattern** | `prd/{summary_id}.mp3` |
| **Format** | MP3 |

### GCS Image Files (Generated)

| Attribute | Value |
|---|---|
| **Bucket** | `img-cdn-bucket` |
| **Path Pattern (generation)** | `jio_bharat/{summary_id}.jpeg` |
| **Path Pattern (prod download)** | `jio_bharat/prod/{summary_id}.jpeg` |
| **Format** | JPEG |

## Intermediate Data

### Pub/Sub Message: `JioBharat_AggregateSummariesProd`

| Attribute | Value |
|---|---|
| **Direction** | JioBharat_AggregateSummariesPROD -> jiobharat-pushtosftpprod |
| **Content** | Individual summary record from PROD aggregation |
| **Format** | JSON (base64-encoded in Pub/Sub envelope) |

#### Message Payload Fields

| Field | Type | Description |
|---|---|---|
| `summary_id` | String | Summary ObjectId as string |
| `title` | String | Summary headline |
| `language` | String | Language code |
| `publisher` | String | Publisher name |
| `thumbnailUrl` | String | Original image URL |
| `createdAt` | String/Number | Creation timestamp |

### Image Attributor API Request

| Attribute | Value |
|---|---|
| **Endpoint** | `POST https://service.jionews.com/v1/image-attributor/generate-image` |
| **Content-Type** | `application/json` |

#### Request Body

```json
{
  "title": "Summary headline text",
  "publisher": "Publisher name",
  "image_url": "https://original-image-url.com/image.jpg",
  "summary_id": "65a1b2c3d4e5f6a7b8c9d0e1"
}
```

#### Response

The Image Attributor generates a JPEG image and uploads it to GCS. The response includes the GCS path for the generated image.

### Image Attributor Internal Processing

| Step | Description |
|---|---|
| 1 | Receive POST request with title, publisher, image_url, summary_id |
| 2 | Render Jinja2 HTML template with the provided data |
| 3 | Launch headless Chromium via pyppeteer (1920x1080 viewport) |
| 4 | Navigate to rendered HTML template |
| 5 | Capture JPEG screenshot |
| 6 | Upload to GCS: `img-cdn-bucket/jio_bharat/{summary_id}.jpeg` |
| 7 | Return GCS path |

## Output Data

### SFTP File Delivery

| Attribute | Value |
|---|---|
| **Server** | `mediaftp1.ril.com:33001` |
| **User** | `FT_jionews_livenews` |
| **Base Path** | `/media/prod/` |

#### SFTP Path Pattern

```
/media/prod/{language_folder}/{summary_id}_{lang}_{dd_mm_yyyy}.{ext}
```

**Example paths:**

```
/media/prod/taaza_kabrein_hin/65a1b2c3d4e5f6a7_HIN_15_01_2025.mp3
/media/prod/taaza_kabrein_hin/65a1b2c3d4e5f6a7_HIN_15_01_2025.jpeg
/media/prod/ungal_Seithigal_tam/65b2c3d4e5f6a7b8_TAM_15_01_2025.mp3
/media/prod/ungal_Seithigal_tam/65b2c3d4e5f6a7b8_TAM_15_01_2025.jpeg
```

#### Language Folder Mapping

| Language Code | Folder Name |
|---|---|
| `HIN` | `taaza_kabrein_hin` |
| `KAN` | `pramukha_Suddi_kan` |
| `TAM` | `ungal_Seithigal_tam` |
| `TEL` | `itivali_varthalu_tel` |
| `MAR` | `taajya_baatmya_mar` |
| `BAN` | `tatka_sangbad_ban` |
| `GUJ` | `taaza_samachar_guj` |
| `MAL` | `puthiya_varthakal_mal` |

#### Files Per Summary

Each summary produces two SFTP files:

| File | Extension | Source |
|---|---|---|
| Audio | `.mp3` | GCS `audio-summaries-bucket/prd/{summary_id}.mp3` |
| Image | `.jpeg` | GCS `img-cdn-bucket/jio_bharat/prod/{summary_id}.jpeg` |

### DE MongoDB Status Record: `jio_bharat_summaries`

| Attribute | Value |
|---|---|
| **Database** | `ingestion-data` |
| **Collection** | `jio_bharat_summaries` |
| **Purpose** | Track processing status for deduplication |

#### Status Document Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `summary_id` | String | Yes | PROD summary ObjectId as string |
| `title` | String | Yes | Summary headline |
| `language` | String | Yes | Language code (HIN, TAM, etc.) |
| `thumbnailUrl` | String | Yes | Original thumbnail URL |
| `publisher` | String | Yes | Publisher name |
| `createdAt` | Number | Yes | Epoch timestamp |
| `isSuccess` | Boolean | Yes | `true` if SFTP upload succeeded |
| `errorMessage` | String | No | Error details (only when `isSuccess=false`) |
| `uploadedPaths` | Array | Yes | Array of `[image_path, audio_path]` pairs |
| `env` | String | Yes | Always `"prod"` |

#### Example Status Document (Success)

```json
{
  "_id": "ObjectId('65c3d4e5f6a7b8c9d0e1f2a3')",
  "summary_id": "65a1b2c3d4e5f6a7b8c9d0e1",
  "title": "Top Headlines in Hindi",
  "language": "HIN",
  "thumbnailUrl": "https://cdn.example.com/images/headline.jpg",
  "publisher": "News Publisher",
  "createdAt": 1736935800,
  "isSuccess": true,
  "errorMessage": "",
  "uploadedPaths": [
    [
      "/media/prod/taaza_kabrein_hin/65a1b2c3d4e5f6a7_HIN_15_01_2025.jpeg",
      "/media/prod/taaza_kabrein_hin/65a1b2c3d4e5f6a7_HIN_15_01_2025.mp3"
    ]
  ],
  "env": "prod"
}
```

#### Example Status Document (Failure)

```json
{
  "_id": "ObjectId('65c3d4e5f6a7b8c9d0e1f2a4')",
  "summary_id": "65b2c3d4e5f6a7b8c9d0e1f2",
  "title": "Tamil News Update",
  "language": "TAM",
  "thumbnailUrl": "https://cdn.example.com/images/tamil-news.jpg",
  "publisher": "Tamil Publisher",
  "createdAt": 1736935900,
  "isSuccess": false,
  "errorMessage": "SFTP connection timeout: mediaftp1.ril.com:33001",
  "uploadedPaths": [],
  "env": "prod"
}
```

## Data Volume Estimates

| Metric | Typical Value |
|---|---|
| Languages processed | 8 |
| Max summaries per language | 50 |
| Max total summaries per run | 400 (8 x 50) |
| Files per summary | 2 (audio + image) |
| Max SFTP uploads per run | 800 (400 x 2) |

## GCS Bucket Summary

| Bucket | Path | Content | Direction |
|---|---|---|---|
| `audio-summaries-bucket` | `prd/{summary_id}.mp3` | Audio files | Read (download) |
| `img-cdn-bucket` | `jio_bharat/{summary_id}.jpeg` | Generated images (by Image Attributor) | Write (by Image Attributor) |
| `img-cdn-bucket` | `jio_bharat/prod/{summary_id}.jpeg` | Production images | Read (download for SFTP) |
