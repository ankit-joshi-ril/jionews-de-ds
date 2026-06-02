# Skill: native-videos-publisher-onboarding

## Metadata

| Field          | Value                                                                          |
|----------------|--------------------------------------------------------------------------------|
| **Skill ID**   | `native-videos-publisher-onboarding`                                           |
| **Version**    | 1.0.0                                                                          |
| **Purpose**    | Validate MRSS feeds, check MP4 URL accessibility, verify 1080p resolution      |
| **Trigger**    | Manual                                                                         |
| **Run Mode**   | Dry-run by default. Use `--execute` to append config.                          |
| **Mutates**    | Only with `--execute`: appends row to local config CSV copy                    |
| **Owner**      | DE-DS Platform Team                                                            |

---

## Purpose

When a new publisher provides an MRSS/RSS feed for Native Videos ingestion, this skill performs comprehensive validation including feed structure, metadata completeness, MP4 URL accessibility, video file integrity, and resolution verification. It is specifically designed to catch common integration failures such as publishers providing YouTube URLs instead of direct MP4 CDN links.

This skill does NOT upload to GCS or modify any production config. Even with `--execute`, it only appends to a local copy.

---

## Inputs

```json
{
  "feed_url": {
    "type": "string",
    "required": true,
    "description": "The full HTTP/HTTPS URL of the MRSS or RSS feed to validate.",
    "example": "https://publisher.example.com/mrss/videos.xml"
  },
  "publisher_name": {
    "type": "string",
    "required": true,
    "description": "Human-readable name of the publisher.",
    "example": "Example Video Network"
  },
  "language": {
    "type": "string",
    "required": true,
    "description": "Language of the feed content.",
    "enum": ["English", "Hindi", "Marathi", "Gujarati", "Malayalam", "Tamil", "Urdu", "Kannada", "Punjabi", "Telugu", "Bangla", "Odia", "Assamese"],
    "example": "English"
  },
  "category": {
    "type": "string",
    "required": true,
    "description": "Content category for the feed.",
    "enum": ["Agro", "Astrology", "Auto/Automobile", "Business", "Career/Education", "Entertainment", "Health", "India/National", "International/World", "Latest News/Top News", "Lifestyle/Fashion", "Sci and Tech", "Sports", "Cricket"],
    "example": "Entertainment"
  }
}
```

---

## Reference Mappings

### Language ID Mapping

| Language  | ID |
|-----------|----|
| English   | 1  |
| Hindi     | 2  |
| Marathi   | 3  |
| Gujarati  | 4  |
| Malayalam  | 6  |
| Tamil     | 7  |
| Urdu      | 8  |
| Kannada   | 9  |
| Punjabi   | 10 |
| Telugu    | 11 |
| Bangla    | 13 |
| Odia      | 18 |
| Assamese  | 19 |

### Category Mapping

Categories are matched case-insensitively against the known set: `Agro`, `Astrology`, `Auto/Automobile`, `Business`, `Career/Education`, `Entertainment`, `Health`, `India/National`, `International/World`, `Latest News/Top News`, `Lifestyle/Fashion`, `Sci and Tech`, `Sports`, `Cricket`.

---

## Execution Steps

### Step 1: Fetch the Feed URL

- Perform an HTTP GET request to `feed_url`.
- Timeout: 10 seconds.
- Follow redirects (up to 3 hops).
- Record: HTTP status code, response time in milliseconds, Content-Type header, Content-Length header.
- **FAIL** if status code is not 2xx.
- **FAIL** if timeout is exceeded.

### Step 2: Detect and Parse Feed Format

- Inspect the `Content-Type` response header:
  - If `application/json` or `text/json` or body starts with `[` or `{`: treat as **JSON feed**.
  - If `application/xml`, `text/xml`, `application/rss+xml`, or body starts with `<?xml` or `<rss`: treat as **XML/MRSS feed**.
- **JSON feeds**: Extract entries from `response['items']`, `response['data']`, or root list.
- **XML/MRSS feeds**: Parse with `feedparser.parse()` and extract `feed.entries`.
- Record `total_entries` count and `feed_format`.
- **FAIL** if zero entries are found.

### Step 3: Validate Metadata Per Entry

For each parsed entry, check the following fields:

#### 3a. Title Validation

- Extract: `entry.title` or `entry.get('title')` or `entry.get('headline')`.
- Must be a non-empty string after stripping whitespace.
- Must be at least 10 characters long.

#### 3b. Thumbnail/Image URL Extraction

Attempt extraction using the video thumbnail chain:

1. `entry.media_thumbnail[0]['url']`
2. `entry.media_content` items where `medium="image"` or `type` starts with `image/`
3. `entry.get('thumbnail')` or `entry.get('thumbUrl')`
4. `entry.image` (dict with `url` key, or direct string)
5. Parse entry `description`/`summary` HTML for `<img>` tags.

Record whether a thumbnail was found.

#### 3c. Video URL Extraction

Attempt extraction in this order:

1. `entry.media_content[0]['url']` where `medium="video"` or `type` starts with `video/`
2. `entry.media_content[0]['url']` (fallback if no medium attribute, check if URL ends in `.mp4`)
3. `entry.get('video')` (IANS-type feeds use this field)
4. `entry.get('videoUrl')` or `entry.get('video_url')`
5. `entry.enclosures[0]['href']` where `type` starts with `video/`
6. `entry.links` where `type` starts with `video/`

Record: the extracted video URL and the extraction method used.

### Step 4: Video-Specific Validations

This is the critical differentiation from headlines onboarding. Each sub-step targets a specific failure mode.

#### 4a. MP4 URL Format Check

For each entry with a video URL:
- Check that the URL contains `.mp4` (case-insensitive) in the path.
- Check that the URL does **NOT** contain `youtube.com` or `youtu.be`.
- Check that the URL does **NOT** contain `dailymotion.com` or `vimeo.com`.
- Classify each video URL as:
  - `"mp4_direct"`: Contains `.mp4`, no streaming platform domain.
  - `"youtube"`: Contains `youtube.com` or `youtu.be`.
  - `"other_platform"`: Contains other streaming platform domains.
  - `"unknown"`: No `.mp4` extension and no recognized platform.

Count: `entries_with_mp4_url`, `entries_with_youtube_url`.

**FAIL the entire validation** if > 50% of video URLs are YouTube links. Publishers must provide direct MP4 CDN URLs.

#### 4b. MP4 URL Accessibility Check

For the **first 3 entries** that have MP4 direct URLs:
- Perform an HTTP HEAD request to the video URL.
- Timeout: 15 seconds (video CDNs can be slower).
- Validate:
  - HTTP status code is 200 or 206 (partial content).
  - `Content-Type` header contains `video/` (e.g., `video/mp4`).
  - `Content-Length` header is present and represents a reasonable file size (> 100KB, < 5GB).
- Record per URL: `{ url, status_code, content_type, content_length_bytes, accessible: bool }`.
- Count `mp4_urls_accessible` out of `mp4_urls_tested`.

#### 4c. MP4 File Integrity Check

For the **first video URL** that passed the HEAD check:
- Perform an HTTP GET request with `Range: bytes=0-1048575` header (first 1MB).
- Timeout: 30 seconds.
- Validate:
  - Response body starts with valid MP4 file signature: bytes 4-7 should be `ftyp` (hex: `66 74 79 70`).
  - Common ftyp brands: `isom`, `iso2`, `avc1`, `mp41`, `mp42`, `M4V`.
- Record: `mp4_signature_valid: bool`, `ftyp_brand: string or null`.
- **WARN** if the signature is invalid (file may not be a valid MP4).

#### 4d. Video Resolution Check

For the first video URL, attempt to determine resolution:
- **Method 1 (preferred)**: If `ffprobe` is available on the system:
  ```
  ffprobe -v quiet -print_format json -show_streams <video_url>
  ```
  Extract `width` and `height` from the first video stream.
- **Method 2 (fallback)**: Check MRSS feed metadata for `media:content` attributes:
  - `width` and `height` attributes on `media:content` tag.
- **Method 3 (fallback)**: Check if publisher provides resolution metadata in custom tags.

Evaluate resolution:
- **PASS**: width >= 1920 or height >= 1080 (covers both landscape 1920x1080 and portrait 1080x1920).
- **WARN**: width >= 1280 or height >= 720 (HD but below 1080p target).
- **FAIL**: width < 1280 and height < 720 (below acceptable quality).
- **UNKNOWN**: If resolution cannot be determined, record `"unknown"` and note in recommendations.

Record: `video_resolution: "<width>x<height>" or "unknown"`, `is_1080p: bool or null`.

### Step 5: Validate Feed Freshness

- From all parsed published dates, find the most recent entry.
- Calculate the age of the newest entry in hours.
- **PASS** if at least 1 entry was published within the last 24 hours.
- **WARN** if the newest entry is between 24-48 hours old.
- **FAIL** if the newest entry is older than 48 hours.

### Step 6: YouTube URL Detection and Reporting

- Aggregate all entries where the video URL was classified as `"youtube"`.
- If any YouTube URLs are found:
  - Add to `issues`: `"Found <N> entries with YouTube URLs instead of direct MP4 links."`
  - Add to `recommendations`: `"Publisher must provide direct MP4 CDN URLs, not YouTube links. YouTube URLs cannot be ingested by the native videos pipeline because: (1) YouTube does not allow direct video download, (2) YouTube URLs require separate YouTube Data API processing, (3) transcoder cannot process YouTube URLs."`
- List the first 5 YouTube URLs found for reference.

### Step 7: Generate Proposed Config Row

Assemble the proposed CSV row for `mrss_videos_feeds.csv`:

```json
{
  "id": "<NEXT_AVAILABLE - to be assigned by operator>",
  "feed_url": "<validated feed_url>",
  "is_active": "true",
  "pub_name": "<publisher_name from input>",
  "publication_id": "<TO_BE_ASSIGNED>",
  "category_id": "<looked up from category mapping>",
  "category_name": "<category from input>",
  "language_id": "<looked up from language mapping>",
  "language_name": "<language from input>",
  "content_type": "videos",
  "mapping_schema": "<inferred from feed format>"
}
```

---

## Confidence Score Calculation

| Condition                                              | Points |
|--------------------------------------------------------|--------|
| Feed is accessible (HTTP 200)                          | +15    |
| Feed format detected unambiguously                     | +5     |
| At least 5 entries parsed                              | +5     |
| 100% of entries have titles                            | +10    |
| >= 80% of entries have thumbnails                      | +5     |
| >= 80% of entries have video URLs                      | +10    |
| 100% of video URLs are MP4 direct (0% YouTube)        | +15    |
| All tested MP4 URLs accessible (HEAD 200)              | +10    |
| MP4 file signature valid                               | +5     |
| Video resolution is 1080p or higher                    | +10    |
| At least 1 entry within last 24 hours                  | +5     |
| No duplicate titles                                    | +5     |
| **Total possible**                                     | **100**|

Deductions:
- Any YouTube URLs found: -15 points minimum, -25 if > 50%
- MP4 URLs inaccessible: -5 per inaccessible URL tested
- No MP4 signature validation possible: -5 points
- Resolution below 1080p: -10 points
- Resolution unknown: -5 points
- No entries within 24 hours: -5 points
- Feed response time > 5 seconds: -3 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "native-videos-publisher-onboarding",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {
    "feed_url": "https://publisher.example.com/mrss/videos.xml",
    "publisher_name": "Example Video Network",
    "language": "English",
    "category": "Entertainment"
  },
  "output": {
    "feed_accessible": true,
    "http_status_code": 200,
    "response_time_ms": 580,
    "feed_format": "xml",
    "total_entries": 15,
    "entries_with_title": 15,
    "entries_with_thumbnail": 14,
    "entries_with_video_url": 15,
    "entries_with_mp4_url": 13,
    "entries_with_youtube_url": 2,
    "youtube_urls_found": [
      "https://www.youtube.com/watch?v=abc123",
      "https://youtu.be/def456"
    ],
    "mp4_url_checks": [
      {
        "url": "https://cdn.publisher.com/video1.mp4",
        "status_code": 200,
        "content_type": "video/mp4",
        "content_length_bytes": 52428800,
        "accessible": true
      },
      {
        "url": "https://cdn.publisher.com/video2.mp4",
        "status_code": 200,
        "content_type": "video/mp4",
        "content_length_bytes": 41943040,
        "accessible": true
      },
      {
        "url": "https://cdn.publisher.com/video3.mp4",
        "status_code": 403,
        "content_type": null,
        "content_length_bytes": null,
        "accessible": false
      }
    ],
    "mp4_urls_accessible": 2,
    "mp4_urls_tested": 3,
    "mp4_signature_valid": true,
    "ftyp_brand": "isom",
    "video_resolution": "1920x1080",
    "is_1080p": true,
    "entries_with_date": 15,
    "entries_within_24h": 8,
    "newest_entry_age_hours": 2.3,
    "duplicate_titles": 0,
    "proposed_config": {
      "id": "<TO_BE_ASSIGNED>",
      "feed_url": "https://publisher.example.com/mrss/videos.xml",
      "is_active": "true",
      "pub_name": "Example Video Network",
      "publication_id": "<TO_BE_ASSIGNED>",
      "category_id": "6",
      "category_name": "Entertainment",
      "language_id": "1",
      "language_name": "English",
      "content_type": "videos",
      "mapping_schema": "mrss_media"
    }
  },
  "validation_status": "warning",
  "confidence_score": 68,
  "issues": [
    "Found 2 entries with YouTube URLs instead of direct MP4 links.",
    "1 of 3 tested MP4 URLs returned HTTP 403 Forbidden."
  ],
  "recommendations": [
    "Publisher must provide direct MP4 CDN URLs, not YouTube links. YouTube URLs cannot be ingested by the native videos pipeline.",
    "Investigate HTTP 403 on https://cdn.publisher.com/video3.mp4 - publisher CDN may require referrer or auth headers.",
    "Request publisher to ensure all video CDN URLs are publicly accessible without authentication."
  ]
}
```

---

## Dry-Run vs Execute Behavior

### Dry-Run (default)

- Fetches and parses the feed (read-only HTTP GET).
- Performs HEAD/partial-GET requests to video URLs (read-only).
- Validates all metadata and video-specific checks.
- Generates the proposed config row.
- Produces the full JSON report.
- **Does NOT** write to any file, database, or storage system.

### Execute (`--execute`)

- Performs all dry-run steps first.
- **ONLY if `validation_status` is `"passed"`** (not warning, not failed):
  - Video feeds have a higher bar than headlines because bad video configs cause transcoder failures.
  - Reads the local copy of `mrss_videos_feeds.csv`.
  - Appends the proposed config row.
  - Writes the updated CSV to the local file system only.
  - Sets output field `config_row_appended: true`.
- **Does NOT** upload to GCS. Operator must manually review and upload.
- **Does NOT** delete or modify existing rows (per CONSTITUTION.md).

If `validation_status` is `"warning"` or `"failed"`, execute mode refuses to append and sets `config_row_appended: false` with an explanation. For warnings, the operator can override by fixing the issues and re-running.

---

## Error Handling

| Error Condition                        | Behavior                                                           |
|----------------------------------------|--------------------------------------------------------------------|
| Feed URL unreachable (timeout/DNS)     | Set `feed_accessible: false`, confidence=0, status=failed          |
| HTTP 4xx/5xx on feed                   | Record status code, set feed_accessible=false, status=failed       |
| Zero entries found                     | Set total_entries=0, status=failed, confidence=0                   |
| All video URLs are YouTube             | Set status=failed, add critical issue                              |
| No MP4 URLs found at all               | Set status=failed, confidence < 20                                 |
| HEAD request to MP4 fails              | Record failure per URL, continue checking others                   |
| Partial GET for MP4 signature fails    | Set mp4_signature_valid=null, note in recommendations              |
| ffprobe not available                  | Set video_resolution="unknown", is_1080p=null, note in output      |
| Invalid language/category input        | Reject with input validation error before execution                |

---

## Alerting Thresholds

| Condition                                          | Alert Level |
|----------------------------------------------------|-------------|
| Feed completely inaccessible                       | CRITICAL    |
| > 50% of video URLs are YouTube links              | CRITICAL    |
| 0 MP4 URLs found                                   | CRITICAL    |
| All tested MP4 URLs inaccessible                   | CRITICAL    |
| Video resolution below 720p                        | WARNING     |
| Video resolution unknown (cannot verify)           | WARNING     |
| MP4 file signature invalid                         | WARNING     |
| 0 entries within last 24 hours                     | WARNING     |
| Confidence score < 50                              | CRITICAL    |
| Confidence score 50-69                             | WARNING     |
