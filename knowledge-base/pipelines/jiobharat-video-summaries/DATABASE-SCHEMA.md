# JioBharat Video Summaries - Database Schema

## Database Overview

This pipeline interacts with two separate MongoDB instances:

| Database | Instance | Purpose | Connection Method |
|---|---|---|---|
| `pie-production.summaries` | PROD MongoDB | Source of audio summaries | Base64-encoded hardcoded URI |
| `ingestion-data.jio_bharat_summaries` | DE MongoDB | Processing status tracking | `mongosh_de_uri` (Secret Manager) |

## Source Collection: `pie-production.summaries`

### Purpose

This is the production summaries collection maintained by the upstream summarization pipeline. The JioBharat pipeline reads from this collection but never writes to it.

### Aggregation Pipeline Used

```javascript
db.summaries.aggregate([
  {
    $match: {
      createdAt: {
        $gte: ISODate("today_start_IST"),
        $lt: ISODate("today_end_IST")
      },
      "language.code": {
        $in: ["HIN", "TAM", "TEL", "KAN", "MAR", "BAN", "MAL", "GUJ"]
      },
      isAudioSummaryGenerated: true,
      isBreaking: false
    }
  },
  { $sort: { createdAt: -1 } },
  {
    $group: {
      _id: "$language.code",
      docs: { $push: "$$ROOT" }
    }
  },
  {
    $project: {
      docs: { $slice: ["$docs", 50] }
    }
  },
  { $unwind: "$docs" },
  { $replaceRoot: { newRoot: "$docs" } }
])
```

### Relevant Document Fields (Read-Only)

| Field | BSON Type | Description |
|---|---|---|
| `_id` | ObjectId | Summary identifier (used as `summary_id`) |
| `title` | String | Summary headline text |
| `language` | Object | Language information object |
| `language.code` | String | Language code: HIN, TAM, TEL, KAN, MAR, BAN, MAL, GUJ |
| `language.name` | String | Full language name |
| `publisher` | String | Source publisher name |
| `thumbnailUrl` | String | Original image URL for the summary |
| `createdAt` | Date | Summary creation timestamp (IST day boundary used for filtering) |
| `isAudioSummaryGenerated` | Boolean | `true` if audio version exists |
| `isBreaking` | Boolean | `true` for breaking news (excluded by this pipeline) |

### Aggregation Filter Details

#### Date Range (IST Day Boundary)

The `createdAt` filter uses IST (UTC+5:30) day boundaries:

| Boundary | Value |
|---|---|
| **Start** | Today 00:00:00 IST (previous day 18:30:00 UTC) |
| **End** | Today 23:59:59 IST (today 18:29:59 UTC) |

#### Language Codes

| Code | Language |
|---|---|
| `HIN` | Hindi |
| `TAM` | Tamil |
| `TEL` | Telugu |
| `KAN` | Kannada |
| `MAR` | Marathi |
| `BAN` | Bangla |
| `MAL` | Malayalam |
| `GUJ` | Gujarati |

#### Per-Language Limit

The `$group` + `$slice` combination ensures a maximum of 50 summaries per language. With 8 languages, the maximum output is 400 documents per execution.

## Status Collection: `ingestion-data.jio_bharat_summaries`

### Purpose

Tracks the processing status of each summary delivered to the SFTP server. Used for deduplication (checking `isSuccess=true` to avoid reprocessing) and for operational monitoring.

### Document Schema

| Field | BSON Type | Required | Description |
|---|---|---|---|
| `_id` | ObjectId | Yes | Auto-generated MongoDB document identifier |
| `summary_id` | String | Yes | PROD summary ObjectId as string (links to `pie-production.summaries._id`) |
| `title` | String | Yes | Summary headline text |
| `language` | String | Yes | Language code (HIN, TAM, TEL, KAN, MAR, BAN, MAL, GUJ) |
| `thumbnailUrl` | String | Yes | Original thumbnail URL from PROD |
| `publisher` | String | Yes | Source publisher name |
| `createdAt` | Number (Epoch) | Yes | Unix epoch timestamp of summary creation |
| `isSuccess` | Boolean | Yes | `true` if SFTP delivery succeeded; `false` on any failure |
| `errorMessage` | String | Yes | Error description (empty string on success) |
| `uploadedPaths` | Array | Yes | Array of `[image_path, audio_path]` string pairs |
| `env` | String | Yes | Environment identifier (always `"prod"`) |

### Example Document (Successful Delivery)

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

### Example Document (Failed Delivery)

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

### Field Details

#### `uploadedPaths`

This field is an array of arrays. Each inner array is a pair of strings: `[image_sftp_path, audio_sftp_path]`.

```json
"uploadedPaths": [
  ["<image_path>", "<audio_path>"]
]
```

On success, it contains one pair with the SFTP paths. On failure, it is an empty array.

#### `isSuccess`

This field is the primary deduplication key used by Stage 1. The aggregation function queries for records where `isSuccess=true` to determine which summaries have already been successfully processed and should be skipped.

#### `env`

Always set to `"prod"` in the production pipeline. This field may be used for environment-based filtering if the collection ever stores records from multiple environments.

## Write Operations

### Stage 2: jiobharat-pushtosftpprod

```python
collection.insert_one({
    "summary_id": summary_id,
    "title": title,
    "language": language_code,
    "thumbnailUrl": thumbnail_url,
    "publisher": publisher,
    "createdAt": epoch_timestamp,
    "isSuccess": True,  # or False on failure
    "errorMessage": "",  # or error string
    "uploadedPaths": [[image_path, audio_path]],  # or [] on failure
    "env": "prod"
})
```

| Attribute | Value |
|---|---|
| **Method** | `insert_one` |
| **Collection** | `jio_bharat_summaries` |
| **Timing** | After SFTP upload (success) or after any failure step |
| **Idempotency** | Not enforced; duplicate runs may create duplicate status records |

## Read Operations

### Stage 1: Deduplication Query

```python
processed_ids = collection.find(
    {"isSuccess": True},
    {"summary_id": 1}
)
```

| Attribute | Value |
|---|---|
| **Method** | `find` with projection |
| **Filter** | `{ isSuccess: true }` |
| **Projection** | `{ summary_id: 1 }` |
| **Purpose** | Retrieve all successfully processed summary IDs for set-difference dedup |

## Recommended Indexes

### Source Collection: `pie-production.summaries`

| Index | Fields | Rationale |
|---|---|---|
| Date + language | `{ createdAt: -1, "language.code": 1 }` | Optimize the primary aggregation match stage |
| Audio + breaking | `{ isAudioSummaryGenerated: 1, isBreaking: 1 }` | Support boolean filter conditions |

### Status Collection: `ingestion-data.jio_bharat_summaries`

| Index | Fields | Type | Rationale |
|---|---|---|---|
| Success dedup | `{ isSuccess: 1, summary_id: 1 }` | Compound | Optimize dedup query in Stage 1 |
| Summary lookup | `{ summary_id: 1 }` | Regular | Direct lookup by summary ID |
| Language + date | `{ language: 1, createdAt: -1 }` | Compound | Operational monitoring by language |
| Environment | `{ env: 1 }` | Regular | Environment-based filtering |

## Data Lifecycle

| Aspect | PROD Collection | Status Collection |
|---|---|---|
| **Access** | Read-only | Write (insert) |
| **Ownership** | Upstream summarization pipeline | This pipeline |
| **Retention** | Managed upstream | No TTL; records persist indefinitely |
| **Volume per day** | Up to 400 records read (50 x 8 languages) | Up to 400 records inserted |
| **Immutability** | N/A (read-only) | Insert-only; no updates after creation |
