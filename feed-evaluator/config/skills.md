# JioNews Dashboard -- Skill Definitions

This file contains all skill prompts loaded by the application at runtime.
Each skill is delimited by `## Skill: <skill-id>` headers.
Do NOT rename or remove these headers — they are parsed programmatically.

---

## Skill: headlines-publisher-onboarding

### Purpose
Validate and onboard new RSS/JSON feeds for the Headlines ingestion pipeline.

### Supported Languages
English, Hindi, Gujarati, Marathi, Telugu, Tamil, Bangla, Urdu, Kannada, Malayalam, Odia, Punjabi, Assamese

### Supported Categories
Agro, Astrology, Auto, Automobile, Business, Career, Education, Entertainment, Health, India, National, International, World, Latest News, Top News, Lifestyle, Fashion, Sci and Tech, Sports, Cricket

### Validation Steps
1. **Feed Accessibility** - HTTP GET with 10-second timeout, max 3 redirects; must return 2xx status
2. **Format Detection** - Determine XML vs JSON from Content-Type header or body content
3. **Parse Entries** - Extract items from feed; common JSON paths: `items`, `articles`, `data`, `feed.items`; XML uses feedparser
4. **Metadata Per Entry:**
   - Title: non-empty, >= 10 characters, no duplicates
   - URL/Link: valid HTTP/HTTPS URL
   - Thumbnail: 12-step extraction priority chain (media:content -> media:thumbnail -> custom tags -> image -> HTML parse)
   - Published Date: parseable to UTC timestamp
5. **Feed Freshness** - Newest entry must be <= 48 hours old; PASS if <= 24h, WARN if 24-48h
6. **Duplicate Titles Check** - Normalized title collision detection; WARN if > 10%

### Confidence Scoring (0-100)
| Condition | Points |
|-----------|--------|
| Feed accessible | +20 |
| Format detected | +10 |
| >= 10 entries | +10 |
| 100% titles present | +15 |
| 100% URLs present | +15 |
| >= 80% thumbnails | +10 |
| >= 80% dates parseable | +5 |
| Recent entries (24h) | +10 |
| No duplicate titles | +5 |

### Status Thresholds
- **passed**: score >= 70
- **warning**: score 50-69
- **failed**: score < 50

---

## Skill: native-videos-publisher-onboarding

### Purpose
Validate MRSS/RSS feeds for Native Videos ingestion with critical MP4 URL, accessibility, and 1080p resolution checks.

### Validation Steps
1-3. Same as Headlines (Fetch, Detect Format, Parse Entries)
4. **Metadata Per Entry:**
   - Title: same rules as Headlines
   - Thumbnail: 5-step extraction chain
   - Video URL: 6-step extraction priority (media_content[video] -> direct video -> custom fields -> enclosures -> links)
5. **Video-Specific Validations (Critical):**
   - **MP4 URL Format Check:** Must contain `.mp4` in path. Must NOT be YouTube, Dailymotion, or Vimeo. FAILS if >50% are YouTube URLs.
   - **MP4 Accessibility Check (first 3 URLs):** HTTP HEAD, must return 200/206, Content-Type must contain `video/`
   - **MP4 File Integrity Check:** GET first 1MB, bytes 4-7 must be `ftyp` (valid MP4 signature)
   - **Video Resolution Check:** MRSS width/height attributes. PASS: width >= 1920 OR height >= 1080
6. **Feed Freshness** - Same as Headlines
7. **YouTube URL Detection** - Lists problematic URLs with explanation

### Confidence Scoring (0-100)
| Condition | Points |
|-----------|--------|
| Feed accessible | +15 |
| Format detected | +5 |
| >= 5 entries | +5 |
| 100% titles | +10 |
| >= 80% thumbnails | +5 |
| >= 80% video URLs | +10 |
| 100% MP4 direct (no YouTube) | +15 |
| All MP4s accessible | +10 |
| Valid ftyp signature | +5 |
| 1080p resolution | +10 |
| Recent entries (24h) | +5 |
| No duplicate titles | +5 |

### Critical Failure Conditions
- >50% YouTube URLs -> automatic FAIL regardless of score
- Publishers must provide direct MP4 CDN URLs

---

## Skill: summaries-publisher-onboarding

### Purpose
Validate RSS/JSON feeds for the Summaries ingestion pipeline. Includes summary-specific hygiene pre-checks.

### Validation Steps
1-3. Same as Headlines (Fetch, Detect Format, Parse Entries)
4. **Metadata Per Entry:**
   - Title: non-empty, >= 10 characters
   - URL/Link: valid HTTP/HTTPS URL
   - Thumbnail: extraction chain (media:content -> media:thumbnail -> image tags -> HTML parse)
   - Summary/Description: extracted from summary, description, content, or brief fields
   - Published Date: parseable to UTC timestamp
5. **Summary-Specific Hygiene Checks:**
   - **Title Length:** 26-105 characters (flag too short or too long)
   - **Summary Length:** 200-360 characters (flag too short or too long)
   - **HTML Detection:** Check for HTML tags in title and summary text
   - **Special Characters:** Flag if >= 3 special characters (@#$%^&*()_+=[]{}\\|<>/?)
6. **Feed Freshness** - Same as Headlines
7. **Duplicate Titles Check** - Same as Headlines

### Confidence Scoring (0-100)
| Condition | Points |
|-----------|--------|
| Feed accessible | +20 |
| Format detected | +10 |
| >= 10 entries | +10 |
| 100% titles present | +10 |
| 100% URLs present | +10 |
| >= 80% summaries present | +10 |
| >= 80% summary length OK | +5 |
| No HTML contamination (>= 90%) | +5 |
| >= 80% thumbnails | +5 |
| Recent entries (24h) | +10 |
| No duplicate titles | +5 |

### Status Thresholds
- **passed**: score >= 70
- **warning**: score 50-69
- **failed**: score < 50

---

## Skill: feed-analytics

### Purpose
Answer analytical queries about the feed configuration files (headlines, videos, summaries CSVs).

### Capabilities
- Count feeds by publisher, language, category, or feed type
- Search for specific publishers or feed URLs
- Show distribution of feeds across languages
- Compare feed coverage between content types
- Identify publishers with feeds across multiple content types

### Response Format
Always present results in a clean markdown table. For counts > 100, suggest downloading the full dataset.
