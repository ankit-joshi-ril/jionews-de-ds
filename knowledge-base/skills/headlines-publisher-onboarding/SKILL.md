# Skill: headlines-publisher-onboarding

## Metadata

| Field          | Value                                                          |
|----------------|----------------------------------------------------------------|
| **Skill ID**   | `headlines-publisher-onboarding`                               |
| **Version**    | 1.0.0                                                          |
| **Purpose**    | Validate and onboard new RSS/JSON feeds for Headlines pipeline |
| **Trigger**    | Manual                                                         |
| **Run Mode**   | Dry-run by default. Use `--execute` to append config.          |
| **Mutates**    | Only with `--execute`: appends row to local config CSV copy    |
| **Owner**      | DE-DS Platform Team                                            |

---

## Purpose

When a new publisher provides an RSS or JSON feed for Headlines ingestion, this skill validates the feed structure, content quality, and metadata completeness. It produces a detailed validation report and, optionally, a proposed configuration row for the headlines publisher feeds CSV.

This skill does NOT upload to GCS or modify any production config. Even with `--execute`, it only appends to a local copy.

---

## Inputs

```json
{
  "feed_url": {
    "type": "string",
    "required": true,
    "description": "The full HTTP/HTTPS URL of the RSS or JSON feed to validate.",
    "example": "https://publisher.example.com/rss/news.xml"
  },
  "publisher_name": {
    "type": "string",
    "required": true,
    "description": "Human-readable name of the publisher.",
    "example": "Example News Network"
  },
  "language": {
    "type": "string",
    "required": true,
    "description": "Language of the feed content. Must match a known language.",
    "enum": ["English", "Hindi", "Marathi", "Gujarati", "Malayalam", "Tamil", "Urdu", "Kannada", "Punjabi", "Telugu", "Bangla", "Odia", "Assamese"],
    "example": "Hindi"
  },
  "category": {
    "type": "string",
    "required": true,
    "description": "Content category for the feed. Must match a known category.",
    "enum": ["Agro", "Astrology", "Auto/Automobile", "Business", "Career/Education", "Entertainment", "Health", "India/National", "International/World", "Latest News/Top News", "Lifestyle/Fashion", "Sci and Tech", "Sports", "Cricket"],
    "example": "Sports"
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

Categories are matched case-insensitively against the following known values:

`Agro`, `Astrology`, `Auto/Automobile`, `Business`, `Career/Education`, `Entertainment`, `Health`, `India/National`, `International/World`, `Latest News/Top News`, `Lifestyle/Fashion`, `Sci and Tech`, `Sports`, `Cricket`

Category IDs are resolved by looking up the existing config CSV for the numeric ID associated with the category name.

---

## Execution Steps

### Step 1: Fetch the Feed URL

- Perform an HTTP GET request to `feed_url`.
- Timeout: 10 seconds.
- Follow redirects (up to 3 hops).
- Record: HTTP status code, response time in milliseconds, Content-Type header, Content-Length header.
- **FAIL** if status code is not 2xx.
- **FAIL** if timeout is exceeded.

### Step 2: Detect Feed Format

- Inspect the `Content-Type` response header:
  - If `application/json` or `text/json` or body starts with `[` or `{`: treat as **JSON feed**.
  - If `application/xml`, `text/xml`, `application/rss+xml`, `application/atom+xml`, or body starts with `<?xml` or `<rss` or `<feed`: treat as **XML feed**.
- If format cannot be determined, attempt both parsers and use whichever succeeds.
- Record the detected format in output as `"xml"` or `"json"`.

### Step 3: Parse Feed Entries

- **JSON feeds**: Extract the entries array. Common paths to check in order:
  1. `response['items']`
  2. `response['articles']`
  3. `response['data']`
  4. `response['feed']['items']`
  5. If the root is a list, use it directly.
- **XML feeds**: Parse with `feedparser.parse()` and extract `feed.entries`.
- Record `total_entries` count.
- **FAIL** if zero entries are found.

### Step 4: Validate Metadata Per Entry

For each parsed entry, check the following fields:

#### 4a. Title Validation

- Extract: `entry.title` or `entry.get('title')` or `entry.get('headline')`.
- Must be a non-empty string after stripping whitespace.
- Must be at least 10 characters long (to filter placeholder titles).
- Must not be a duplicate of another entry's title (tracked separately in Step 6).

#### 4b. URL/Link Validation

- Extract: `entry.link` or `entry.get('url')` or `entry.get('link')` or `entry.get('sourceUrl')`.
- Must be a valid HTTP or HTTPS URL.
- Must not be empty or contain only whitespace.

#### 4c. Thumbnail/Image Extraction (12-Step Priority Chain)

Attempt extraction in this exact order, as implemented in processheadlines:

1. `entry.media_content[0]['url']` (media:content tag)
2. `entry.media_thumbnail[0]['url']` (media:thumbnail tag, list form)
3. `entry.media_thumbnail` (media:thumbnail tag, direct string)
4. `entry.thumbimage['url']` (custom thumbimage tag, dict form)
5. `entry.thumbimage` (custom thumbimage tag, direct string)
6. `entry.fullimage` (custom fullimage tag)
7. `entry.fullimageimage` (custom fullimageimage tag)
8. `entry.image['url']` (image tag, dict form)
9. `entry.image['link']` (image tag, link key)
10. `entry.image` (image tag, direct string)
11. `entry.links[1]['href']` (second link element, often used for enclosure)
12. `entry.images[0]` (images array, first element)
13. **Fallback**: Parse entry `summary` or `description` HTML for `<img>` tags and extract the `src` attribute.

Record whether a thumbnail was found and via which method.

#### 4d. Published Date Validation

- Extract: `entry.published` or `entry.get('pubDate')` or `entry.get('publishedAt')` or `entry.get('created_at')` or `entry.get('date')`.
- Must be parseable as a date (try ISO 8601, RFC 2822, and common formats).
- Record the parsed datetime in UTC.

### Step 5: Validate Feed Freshness

- From all parsed published dates, find the most recent entry.
- Calculate the age of the newest entry in hours.
- **PASS** if at least 1 entry was published within the last 24 hours.
- **WARN** if the newest entry is between 24-48 hours old.
- **FAIL** if the newest entry is older than 48 hours.

### Step 6: Check for Duplicate Titles

- Normalize all titles: lowercase, strip leading/trailing whitespace, collapse multiple spaces.
- Count the number of title collisions (identical normalized titles).
- **WARN** if more than 10% of entries share a title with another entry.
- Record `duplicate_titles` count.

### Step 7: Generate Proposed Config Row (Dry-Run Output)

Assemble the proposed CSV row for `headlines_publishers_feeds.csv`:

```json
{
  "id": "<NEXT_AVAILABLE - to be assigned by operator>",
  "feed_url": "<validated feed_url>",
  "is_active": "true",
  "pub_name": "<publisher_name from input>",
  "publication_id": "<TO_BE_ASSIGNED - requires publication registry lookup>",
  "category_id": "<looked up from category mapping>",
  "category_name": "<category from input>",
  "language_id": "<looked up from language mapping>",
  "language_name": "<language from input>",
  "mapping_schema": "<inferred from feed format, or 'default'>"
}
```

The `mapping_schema` field is inferred:
- If XML/RSS with standard RSS 2.0 structure: `"rss_standard"`
- If XML/RSS with custom tags (media:content, etc.): `"rss_media"`
- If JSON with `items` array: `"json_items"`
- If none match: `"default"`

---

## Confidence Score Calculation

The confidence score is computed as follows:

| Condition                                         | Points |
|---------------------------------------------------|--------|
| Feed is accessible (HTTP 200)                     | +20    |
| Feed format detected unambiguously                | +10    |
| At least 10 entries parsed                        | +10    |
| 100% of entries have titles                       | +15    |
| 100% of entries have URLs                         | +15    |
| >= 80% of entries have thumbnails                 | +10    |
| >= 80% of entries have parseable dates            | +5     |
| At least 1 entry within last 24 hours             | +10    |
| No duplicate titles (0%)                          | +5     |
| **Total possible**                                | **100**|

Deductions:
- Each 10% of entries missing titles: -3 points
- Each 10% of entries missing URLs: -3 points
- Each 10% of entries missing thumbnails: -2 points
- Duplicate titles > 10%: -5 points
- No entries within 24 hours: -10 points
- Feed response time > 5 seconds: -5 points

Score is clamped to [0, 100].

---

## Output Schema

```json
{
  "skill_name": "headlines-publisher-onboarding",
  "run_mode": "dry-run",
  "timestamp": "2026-03-10T12:00:00Z",
  "inputs": {
    "feed_url": "https://publisher.example.com/rss/news.xml",
    "publisher_name": "Example News Network",
    "language": "Hindi",
    "category": "Sports"
  },
  "output": {
    "feed_accessible": true,
    "http_status_code": 200,
    "response_time_ms": 342,
    "feed_format": "xml",
    "total_entries": 25,
    "entries_with_title": 25,
    "entries_with_url": 25,
    "entries_with_thumbnail": 20,
    "thumbnail_extraction_methods": {
      "media_content_url": 15,
      "media_thumbnail_url": 3,
      "html_img_parse": 2
    },
    "entries_with_date": 24,
    "entries_within_24h": 12,
    "newest_entry_age_hours": 1.5,
    "duplicate_titles": 0,
    "proposed_config": {
      "id": "<TO_BE_ASSIGNED>",
      "feed_url": "https://publisher.example.com/rss/news.xml",
      "is_active": "true",
      "pub_name": "Example News Network",
      "publication_id": "<TO_BE_ASSIGNED>",
      "category_id": "14",
      "category_name": "Sports",
      "language_id": "2",
      "language_name": "Hindi",
      "mapping_schema": "rss_media"
    }
  },
  "validation_status": "passed",
  "confidence_score": 92,
  "issues": [],
  "recommendations": [
    "5 entries are missing thumbnails. Verify publisher supports media:content or media:thumbnail tags.",
    "1 entry has no parseable published date. Consider adding date parsing fallback for this publisher's format."
  ]
}
```

---

## Dry-Run vs Execute Behavior

### Dry-Run (default)

- Fetches and parses the feed (read-only HTTP GET).
- Validates all metadata fields.
- Generates the proposed config row.
- Produces the full JSON report.
- **Does NOT** write to any file, database, or storage system.

### Execute (`--execute`)

- Performs all dry-run steps first.
- **ONLY if `validation_status` is `"passed"` or `"warning"`**:
  - Reads the local copy of `headlines_publishers_feeds.csv`.
  - Appends the proposed config row with placeholder values for `id` and `publication_id`.
  - Writes the updated CSV to the local file system only.
  - Sets output field `config_row_appended: true`.
- **Does NOT** upload to GCS. Operator must manually review and upload.
- **Does NOT** delete or modify existing rows (per CONSTITUTION.md).

If `validation_status` is `"failed"`, execute mode refuses to append and sets `config_row_appended: false` with an explanation in `issues`.

---

## Error Handling

| Error Condition                        | Behavior                                                      |
|----------------------------------------|---------------------------------------------------------------|
| Feed URL unreachable (timeout/DNS)     | Set `feed_accessible: false`, confidence=0, status=failed     |
| HTTP 4xx/5xx response                  | Record status code, set feed_accessible=false, status=failed  |
| Unparseable feed body                  | Try both XML and JSON parsers, report which failed            |
| Zero entries found                     | Set total_entries=0, status=failed, confidence=0              |
| Invalid language input                 | Reject with input validation error before execution           |
| Invalid category input                 | Reject with input validation error before execution           |
| Network error during fetch             | Record error message, set feed_accessible=false               |

---

## Alerting Thresholds

| Condition                              | Alert Level |
|----------------------------------------|-------------|
| Feed completely inaccessible           | CRITICAL    |
| 0 entries within last 24 hours         | WARNING     |
| < 50% entries have thumbnails          | WARNING     |
| > 20% duplicate titles                 | WARNING     |
| Confidence score < 50                  | CRITICAL    |
| Confidence score 50-69                 | WARNING     |
