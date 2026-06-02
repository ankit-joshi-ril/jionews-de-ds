# Source Code: thenewj-com/de-headlines-airflow
> Auto-synced from GitHub on 2026-04-14 11:54 UTC
> Branch: `master` | Role: Headlines ingestion Airflow DAGs and Cloud Functions

## Repository Structure
```
.gitignore
DEPLOYMENT.md
README.md
airflow/cleanup_logs.sh
airflow/dags/headlines_pipeline_v2_dag.py
airflow/dags/headlines_poc/__init__.py
airflow/dags/headlines_poc/feeds.csv
airflow/dags/headlines_poc/feeds_healthy.csv
airflow/dags/headlines_poc/pipeline_v2.py
airflow/dags/headlines_poc/requirements.txt
airflow/dags/utils/teams_alert.py
airflow/webserver_config.py
analysis/analyze_feeds.py
analysis/feeds_error_report.csv
analysis/feeds_full_health_report.csv
analysis/feeds_healthy.csv
docs/ANALYSIS.md
docs/ARCHITECTURE.md
docs/ARCHITECTURE_COMPARISON.md
docs/AS-IS.md
docs/ROADMAP.md
```

## `README.md`
```markdown
# Headlines Airflow Pipeline

Near-realtime headlines ingestion pipeline running on a single Airflow VM, replacing the production Cloud Functions + Pub/Sub architecture for cost optimization.

## Quick Reference

| Parameter | Value |
|-----------|-------|
| **DAG ID** | `headlines_pipeline_v2` |
| **Schedule** | Every 5 minutes (`*/5 * * * *`) |
| **VM** | `de-airflow` (e2-standard-2, 2 vCPU, 8 GB, asia-south1-b) |
| **GCP Project** | `jiox-328108` |
| **Feeds** | 3,089 healthy feeds (from 4,856 total) |
| **Target E2E Latency** | 3-5 minutes |
| **MongoDB (success)** | `ingestion-data.raw_headlines_ingestion_data` |
| **MongoDB (rejected)** | `ingestion-data.headlines_hygiene_failures` |
| **Image CDN** | `gs://img-cdn-bucket` → `https://icdn.jionews.com/` |

## Architecture

```
Airflow Scheduler (*/5 min)
    ↓
┌── Task 1: fetch_and_process ──────────────────────┐
│   64 threads → fetch 3,089 RSS/JSON feeds          │
│   24h filter → file-based dedup (48h TTL)          │
│   field mapping → 16 threads article scraping      │
└───────────────────────┬───────────────────────────┘
                        ↓ temp JSON file + XCom
┌── Task 2: cdn_and_store ─────────────────────────┐
│   10 threads → download, resize (5 renditions),   │
│                upload to GCS                       │
│   MongoDB bulk insert: success + rejected          │
└───────────────────────────────────────────────────┘
```

**Zero Pub/Sub.** Data flows via local temp files between tasks.

## Project Structure

```
headlines-airflow/
├── README.md                    ← You are here
├── docs/
│   ├── AS-IS.md                 ← Current production pipeline documentation
│   ├── ARCHITECTURE.md          ← New Airflow pipeline architecture
│   ├── ANALYSIS.md              ← GCP audit findings and feed health analysis
│   └── ROADMAP.md               ← Rollout plan and future improvements
├── analysis/
│   ├── analyze_feeds.py         ← Feed health analysis script
│   ├── feeds_healthy.csv        ← 3,089 clean feeds (pipeline input)
│   ├── feeds_error_report.csv   ← 1,767 broken feeds (for product team)
│   └── feeds_full_health_report.csv  ← Full report on all 4,856 feeds
└── airflow/                     ← Airflow home directory (deploy to /opt/airflow/)
    ├── cleanup_logs.sh
    ├── webserver_config.py
    └── dags/
        ├── headlines_pipeline_v2_dag.py   ← DAG definition
        ├── headlines_poc/
        │   ├── pipeline_v2.py             ← Core pipeline logic (~500 lines)
        │   ├── feeds_healthy.csv          ← Feed config (3,089 feeds)
        │   ├── feeds.csv                  ← Original feed config (4,856 feeds, backup)
        │   └── requirements.txt
        └── utils/
            └── teams_alert.py             ← MS Teams failure alerting
```

## Deployment

```bash
# 1. Copy to VM
scp -r airflow/* de-airflow:/opt/airflow/

# 2. Create working directories
ssh de-airflow "mkdir -p /opt/airflow/tmp/headlines /opt/airflow/cache"

# 3. Install dependencies
ssh de-airflow "pip install -r /opt/airflow/dags/headlines_poc/requirements.txt"

# 4. Ensure Airflow Variables are set:
#    GCP_SERVICE_ACCOUNT_FILE  → /path/to/sa-key.json
#    DE_MONGO_URL              → mongodb+srv://...
#    TEAMS_WEBHOOK_URL         → https://...webhook...

# 5. Enable DAG in Airflow UI → headlines_pipeline_v2
# 6. Trigger manually first, check logs, then let scheduler take over
```

## Key Airflow Variables

| Variable | Description |
|----------|-------------|
| `GCP_SERVICE_ACCOUNT_FILE` | Path to GCP service account JSON key on the VM |
| `DE_MONGO_URL` | MongoDB Atlas connection URI |
| `TEAMS_WEBHOOK_URL` | MS Teams incoming webhook for failure alerts |

## Monitoring

- **Airflow UI**: Check task durations, success/failure rates
- **Logs**: `/opt/airflow/logs/dag_id=headlines_pipeline_v2/`
- **Teams Alerts**: Automatic on any task failure (via `on_failure_callback`)
- **Cache**: `/opt/airflow/cache/headlines_dedup_cache.json` (auto-managed, 48h TTL)
```

## `airflow/dags/headlines_pipeline_v2_dag.py`
```python
"""
Headlines Pipeline v2 — Near-Realtime DAG
==========================================
Schedule: Every 5 minutes
Architecture: 2 chained tasks, zero Pub/Sub, single VM

  fetch_and_process  →  cdn_and_store
       ~3 min              ~1-2 min

Data flows via local temp files + XCom (file path only).
max_active_runs=1 prevents overlap — if a cycle exceeds 5 min,
the next trigger is skipped rather than creating a backlog.
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

from headlines_poc.pipeline_v2 import fetch_and_process, cdn_and_store
from utils.teams_alert import send_teams_alert

default_args = {
    'owner': 'de-team',
    'start_date': datetime(2026, 4, 13),
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
    'on_failure_callback': send_teams_alert,
}

with DAG(
    dag_id='headlines_pipeline_v2',
    default_args=default_args,
    description='Headlines near-realtime ingestion (5-min cycle, no Pub/Sub)',
    schedule_interval='*/5 * * * *',
    catchup=False,
    max_active_runs=1,
    tags=['headlines', 'ingestion', 'v2', 'production'],
) as dag:

    task_fetch = PythonOperator(
        task_id='fetch_and_process',
        python_callable=fetch_and_process,
        execution_timeout=timedelta(minutes=8),  # hard kill if stuck
    )

    task_cdn = PythonOperator(
        task_id='cdn_and_store',
        python_callable=cdn_and_store,
        execution_timeout=timedelta(minutes=5),
    )

    task_fetch >> task_cdn
```

## `airflow/dags/headlines_poc/pipeline_v2.py`
```python
"""
Headlines Pipeline v2 — Near-Realtime, Single-VM, Zero Pub/Sub
===============================================================
Designed for: e2-standard-2 (2 vCPU, 8 GB RAM)
Target cycle: 5 minutes end-to-end
Feed count: ~3,089 healthy feeds

Architecture:
  Task 1: fetch_and_process()
    Phase A — Fetch 3089 RSS/JSON feeds (ThreadPool 64, I/O bound)  ~3 min
    Phase B — 24h filter + dedup + mapping + article scrape          ~1-2 min
    Output  → /opt/airflow/tmp/headlines/batch_{timestamp}.json

  Task 2: cdn_and_store()
    Phase A — Image CDN: download, resize 5 renditions, upload GCS  ~1-2 min
    Phase B — MongoDB bulk insert (processed + rejected)            ~10 sec
    Cleanup → remove temp file

All business logic preserved from production Cloud Functions.
"""

import hashlib
import io
import json
import logging
import os
import re
import random
import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
import pytz
import requests
from bson import ObjectId
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from PIL import Image, ImageOps
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from google.cloud import storage
from google.oauth2 import service_account
from airflow.models import Variable
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("headlines_pipeline_v2")
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")
TEMP_DIR = "/opt/airflow/tmp/headlines"
FEEDS_CSV = "/opt/airflow/dags/headlines_poc/feeds_healthy.csv"
CACHE_FILE = "/opt/airflow/cache/headlines_dedup_cache.json"

FETCH_WORKERS = 64       # I/O-bound: HTTP requests to publisher feeds
SCRAPE_WORKERS = 16      # I/O-bound: article body scraping
CDN_WORKERS = 10         # mixed I/O + CPU: image download/resize/upload

FEED_TIMEOUT = (3, 8)    # (connect, read) seconds for feed HTTP requests
SCRAPE_TIMEOUT = 10      # seconds for article scrape API
CDN_DOWNLOAD_TIMEOUT = 10

DEDUP_TTL = 48 * 3600    # 48 hours

RENDITION_SIZES = [
    ((1920, 1080), "fhd"),
    ((1280, 720),  "hd"),
    ((720, 480),   "sd"),
    ((480, 320),   "low"),
]

CDN_BUCKET = "img-cdn-bucket"
CDN_BASE = "https://icdn.jionews.com"

CATEGORY_MAP = {
    "Agro": "agro", "Astrology": "astrology", "Auto": "automobile",
    "Business": "business", "Money": "business", "Career": "education",
    "Entertainment": "entertainment", "Movie Reviews": "entertainment",
    "Health": "health", "Corona": "health", "National": "india",
    "Regional": "india", "World": "international", "Top News": "latest_news",
    "Top Stories": "latest_news", "news": "latest_news", "News": "latest_news",
    "Lifestyle": "lifestyle", "Fashion": "lifestyle",
    "Sci & Tech": "sci_and_tech", "Sports": "sports", "cricket": "cricket",
}

NP_TARGET_PUBLISHERS = ['english-newspointapp', 'Indiatimes', 'Navbharat Times', 'Newspoint']

NP_CATEGORIES_MAP = {
    "business": {"name": "Business", "id": 5},
    "entertainment": {"name": "Entertainment", "id": 11},
    "lifestyle": {"name": "Lifestyle", "id": 4},
    "city": {"name": "Latest news", "id": 173},
    "top-news": {"name": "Latest news", "id": 173},
    "education": {"name": "Education", "id": 156},
    "regional": {"name": "Latest news", "id": 191},
    "astrology": {"name": "Astrology", "id": 161},
    "auto": {"name": "Automobile", "id": 44},
    "india": {"name": "India", "id": 58},
    "world": {"name": "International", "id": 9},
}


# ──────────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────────
def epoch_now():
    return int(datetime.now(tz=IST).timestamp())


def clean_html(text):
    if not isinstance(text, str):
        return text
    text = re.sub(r'<!\[CDATA\[(.*?)(\]\]>|\]\])', r'\1', text, flags=re.DOTALL)
    import html
    text = html.unescape(text)
    return text


def generic_parse_date(date_string):
    try:
        return dateparser.parse(date_string)
    except (ValueError, TypeError):
        return None


def is_within_last_24_hours(date_string):
    parsed = generic_parse_date(date_string)
    if parsed is None:
        return False
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ist)
    diff = now - parsed.astimezone(ist)
    return diff <= timedelta(days=1)


def safe_publisher_epoch(pub_date_str):
    now = epoch_now()
    try:
        if pub_date_str and "IST" in str(pub_date_str):
            pub_date_str = pub_date_str.replace("IST", "+0530")
        parsed = generic_parse_date(pub_date_str)
        if not parsed:
            return now
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        ep = int(parsed.timestamp())
        return ep if ep <= now else now
    except Exception:
        return now


def handle_custom_image_tags(raw_response):
    if raw_response:
        return re.sub(
            r"(?<!<thumbimage>)(</?image>)(?!</thumbimage>)",
            lambda m: "<thumbimage>" if m.group(0) == "<image>" else "</thumbimage>",
            raw_response,
        )
    return ""


# ──────────────────────────────────────────────────────────────────
# PHASE A: FEED FETCHING
# ──────────────────────────────────────────────────────────────────
def fetch_single_feed(row):
    """Fetch a single RSS/JSON feed. Returns dict with feed_id + feed_data or None."""
    feed_url = row["feed_url"]
    feed_id = row["id"]
    try:
        feedparser.SANITIZE_HTML = 0
        response = requests.get(feed_url, timeout=FEED_TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        raw = response.text

        if 'application/json' in content_type:
            feed_list = json.loads(raw).get('items', [])
        else:
            raw = handle_custom_image_tags(raw)
            feed = feedparser.parse(raw)
            feed_list = feed.entries

        if not feed_list:
            # Fallback: let feedparser try the URL directly
            feed = feedparser.parse(feed_url)
            feed_list = feed.entries

        if feed_list:
            # Convert feedparser entries to plain dicts
            serializable = []
            for entry in feed_list:
                serializable.append(dict(entry) if hasattr(entry, 'keys') else entry)
            return {"feed_id": feed_id, "feed_data": serializable}
        return None

    except Exception:
        return None


def fetch_all_feeds(feeds_df):
    """Fetch all feeds in parallel. Returns list of {feed_id, feed_data}."""
    active = feeds_df[feeds_df["is_active"] == True]
    rows = [row for _, row in active.iterrows()]

    results = []
    success = fail = 0

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_single_feed, r): r["id"] for r in rows}
        for future in as_completed(futures):
            result = future.result()
            if result and result["feed_data"]:
                results.append(result)
                success += 1
            else:
                fail += 1

    logger.info(f"[FETCH] Done | success={success} | fail={fail} | total_feeds_with_data={len(results)}")
    return results


# ──────────────────────────────────────────────────────────────────
# PHASE B: DEDUP + PROCESSING
# ──────────────────────────────────────────────────────────────────
class DedupCache:
    """File-based dedup cache with TTL. Safe for single-process use (max_active_runs=1)."""

    def __init__(self, cache_path=CACHE_FILE):
        self.cache_path = cache_path
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        self.cache = self._load()

    def _load(self):
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Cache load error (starting fresh): {e}")
        return {}

    def save(self):
        # Atomic write: write to temp, then rename
        tmp_path = self.cache_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(self.cache, f)
            os.replace(tmp_path, self.cache_path)
        except Exception as e:
            logger.error(f"Cache save error: {e}")

    def deduplicate(self, records, category_id, language_id):
        now = int(time.time())

        # Evict expired entries
        self.cache = {k: v for k, v in self.cache.items() if v >= now}

        unique = []
        for rec in records:
            title = rec.get('title', rec.get('hl', ""))
            link = rec.get('link', rec.get('mwu', ""))
            title_clean = re.sub(r'\s+', ' ', title.strip().lower())
            raw_key = f"{title_clean}_{link}_{category_id}_{language_id}"
            key = hashlib.md5(raw_key.encode()).hexdigest()

            if key not in self.cache:
                unique.append(rec)
                self.cache[key] = now + DEDUP_TTL

        return unique


def get_image_thumbnail_url(record):
    """Extract thumbnail URL from feed record using priority chain."""
    keys = [
        ('media_content', 0, 'url'), ('media_thumbnail', 0, 'url'),
        ('media_thumbnail',), ('thumbimage', 'url'), ('thumbimage',),
        ('fullimage',), ('fullimageimage',), ('image', 'url'),
        ('image', 'link'), ('image',), ('links', 1, 'href'), ('images', 0),
    ]
    for key_path in keys:
        value = record
        try:
            for k in key_path:
                value = value[k]
            if value:
                return value
        except (KeyError, IndexError, TypeError):
            continue

    # Fallback: extract from HTML content
    for html_key in [('content_html',), ('description_html',), ('summary_html',),
                     ('content',), ('summary',), ('summary_detail', 'value')]:
        value = record
        try:
            for k in html_key:
                value = value[k]
            if value and isinstance(value, str):
                soup = BeautifulSoup(value, 'html.parser')
                img = soup.find('img')
                if img and 'src' in img.attrs:
                    return img['src']
        except (KeyError, IndexError, TypeError):
            continue
    return ""


def append_utm_params(url, pub_name):
    utm_keys = {'utm_source', 'utm_medium', 'utm_campaign'}
    utm = "utm_source=JioNews&utm_medium=referral&utm_campaign=JioNews"
    if any(re.search(f'{k}=', url) for k in utm_keys):
        return url
    if pub_name.lower() == "espncricinfo":
        if 'ex_cid=' in url:
            url = re.sub(r'ex_cid=[^&]+', 'ex_cid=jionews', url)
        else:
            utm += "&ex_cid=jionews"
    sep = "" if url.endswith('?') or url.endswith('&') else ("&" if '?' in url else "?")
    return url + sep + utm


def scrape_article(url, language):
    """Scrape article body. Primary: jionews API. Fallback: crawl service (English only)."""
    # Primary scraper
    try:
        r = requests.get(
            "https://service.jionews.com/v1/scrape/scrape/",
            params={"url": url},
            headers={"Content-Type": "application/json"},
            timeout=SCRAPE_TIMEOUT, verify=False
        )
        if r.status_code == 200:
            data = r.json()
            text = data.get('article_text', '')
            html = data.get('article_html', '')
            if text:
                return text, html
    except Exception:
        pass

    # Fallback: old crawler (English only)
    if language == "English":
        try:
            r = requests.post(
                "http://34.36.231.72/crawl",
                headers={'accept': 'application/json', 'Content-Type': 'text/plain'},
                data=url, timeout=15
            )
            body = r.json()
            text = body.get('article_body', '') or body.get('Result', {}).get('article_body', '')
            return text, ""
        except Exception:
            pass
    return "", ""


def process_single_record(record, defaults, now_epoch):
    """Map a single feed record to the final headline document."""
    pub_name = str(defaults["pub_name"])
    pub_id = str(defaults["publication_id"])
    cat_id = str(defaults["category_id"])
    cat_name = str(defaults["category_name"])
    lang_id = str(defaults["language_id"])
    lang_name = str(defaults["language_name"])
    feed_url = str(defaults["feed_url"])
    feed_id = str(defaults["id"])

    # Newspoint publishers have different field mapping
    if pub_name in NP_TARGET_PUBLISHERS:
        pub_name = "Newspoint"
        title = record.get('hl', '')
        description = ""
        url = record.get('mwu', '')
        pub_date_str = record.get('dl', '')
        np_cat = NP_CATEGORIES_MAP.get(record.get('sec', '').lower(), {"name": "Latest news", "id": 173})
        cat_id = str(np_cat["id"])
        cat_name = str(np_cat["name"])
    else:
        title = record.get('title', '')
        description = record.get('summary', '')
        url = record.get('href', record.get('link', '')) if pub_name == "ESPNcricinfo" else record.get('link', '')
        pub_date_str = record.get('published', '')

    # Publisher article body from content field
    publisher_article_body = ""
    try:
        publisher_article_body = record.get('content', '')[0].get('value', '')
    except Exception:
        pass

    thumbnail_url = get_image_thumbnail_url(record)
    source_id = str(ObjectId())
    pub_epoch = safe_publisher_epoch(pub_date_str)

    # UTM params
    try:
        url = append_utm_params(url, pub_name)
    except Exception:
        pass

    doc = {
        "title": re.sub(r'\s+', ' ', title.strip()),
        "sourceDescription": description,
        "url": url,
        "sourcePublishDate": pub_epoch,
        "sourceThumbnailURL": thumbnail_url,
        "thumbnailUrls": {
            "original": f"{CDN_BASE}/original/{source_id}.jpeg",
            "fhd": f"{CDN_BASE}/fhd/{source_id}.jpeg",
            "hd": f"{CDN_BASE}/hd/{source_id}.jpeg",
            "low": f"{CDN_BASE}/low/{source_id}.jpeg",
            "sd": f"{CDN_BASE}/sd/{source_id}.jpeg",
        },
        "sourceId": source_id,
        "createdAt": now_epoch,
        "sourceLanguageId": lang_id,
        "sourceLanguageName": lang_name,
        "sourceCategoryId": cat_id,
        "sourceCategoryName": cat_name,
        "sourcePublisherId": pub_id,
        "sourcePublisherName": pub_name,
        "sourceFeedUrl": feed_url,
        "sourceFeedId": feed_id,
        "briefWordCount": len(re.findall(r'\b\w+\b', title)),
        "publisherArticleBody": publisher_article_body,
    }

    # Mark rejected if no thumbnail
    if not thumbnail_url:
        doc["processing_status"] = "rejected"
        doc["error_message"] = "No thumbnail image url found"

    return {
        "filename": source_id,
        "url": thumbnail_url,
        "category": cat_name,
        "publisher": pub_name,
        "content_type": "headlines",
        "data": doc,
    }


def scrape_articles_batch(records):
    """Scrape article bodies for a batch of processed records in parallel."""
    def _scrape_one(rec):
        doc = rec["data"]
        try:
            text, html = scrape_article(doc["url"], doc["sourceLanguageName"])
            doc["articleBody"] = text
            doc["articleHtml"] = html
        except Exception:
            doc["articleBody"] = ""
            doc["articleHtml"] = ""
        return rec

    with ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as pool:
        return list(pool.map(_scrape_one, records))


def process_feeds(raw_feeds, feeds_df, dedup_cache):
    """Process all fetched feeds: filter, dedup, map, scrape articles."""
    now = epoch_now()
    all_processed = []
    total_input = 0
    total_after_24h = 0
    total_after_dedup = 0

    for feed_msg in raw_feeds:
        feed_id = feed_msg["feed_id"]
        records = feed_msg["feed_data"]
        total_input += len(records)

        # Get feed config
        config = feeds_df.query(f"id == {feed_id}")
        if config.empty:
            continue
        defaults = config.iloc[0]

        cat_id = str(defaults["category_id"])
        lang_id = str(defaults["language_id"])

        # 24h filter
        filtered = [
            r for r in records
            if is_within_last_24_hours(r.get('published') or r.get('dl') or "")
        ]
        total_after_24h += len(filtered)

        if not filtered:
            continue

        # Dedup
        unique = dedup_cache.deduplicate(filtered, cat_id, lang_id)
        total_after_dedup += len(unique)

        if not unique:
            continue

        # Map
        for rec in unique:
            try:
                processed = process_single_record(rec, defaults, now)
                if processed:
                    all_processed.append(processed)
            except Exception as e:
                logger.error(f"Mapping error | feed_id={feed_id} | {e}")

    # Save dedup cache after processing all feeds
    dedup_cache.save()

    logger.info(
        f"[PROCESS] input={total_input} | after_24h={total_after_24h} | "
        f"after_dedup={total_after_dedup} | mapped={len(all_processed)}"
    )

    # Article scraping (parallel)
    if all_processed:
        logger.info(f"[SCRAPE] Scraping {len(all_processed)} articles...")
        all_processed = scrape_articles_batch(all_processed)

    return all_processed


# ──────────────────────────────────────────────────────────────────
# PHASE C: CDN IMAGE PROCESSING
# ──────────────────────────────────────────────────────────────────
class ImageCDN:
    """Handles image download, resize, and upload to GCS."""

    def __init__(self):
        sa_path = Variable.get("GCP_SERVICE_ACCOUNT_FILE")
        credentials = service_account.Credentials.from_service_account_file(sa_path)
        self._client = storage.Client(credentials=credentials)
        self._bucket = self._client.bucket(CDN_BUCKET)

    def download(self, url):
        r = requests.get(url, timeout=CDN_DOWNLOAD_TIMEOUT, verify=False)
        r.raise_for_status()
        return r.content

    def get_size(self, img_bytes):
        with Image.open(io.BytesIO(img_bytes)) as img:
            transposed = ImageOps.exif_transpose(img)
            size = transposed.size
            if transposed is not img:
                transposed.close()
            return size

    def resize(self, img_bytes, target_size):
        with Image.open(io.BytesIO(img_bytes)) as img:
            transposed = ImageOps.exif_transpose(img)
            try:
                if transposed.mode in ("RGBA", "P"):
                    transposed = transposed.convert("RGB")
                transposed.thumbnail(target_size, Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                transposed.save(buf, format="JPEG", quality=90)
                return buf.getvalue()
            finally:
                if transposed is not img:
                    transposed.close()

    def upload(self, folder, name, data):
        self._bucket.blob(f"{folder}/{name}.jpeg").upload_from_string(data)

    def process_one(self, rec):
        """Process a single headline's image. Returns (rec, is_rejected)."""
        filename = rec["filename"]
        url = rec["url"]
        doc = rec["data"]

        # No thumbnail URL → already marked rejected in processing phase
        if not url:
            doc["originalImageWidth"] = 0
            doc["originalImageHeight"] = 0
            return rec, True

        try:
            original = self.download(url)
            w, h = self.get_size(original)
            doc["originalImageWidth"] = w
            doc["originalImageHeight"] = h

            # Upload original + 4 renditions
            self.upload("original", filename, original)
            for size, folder in RENDITION_SIZES:
                resized = self.resize(original, size)
                self.upload(folder, filename, resized)

            return rec, False

        except Exception as e:
            doc["originalImageWidth"] = 0
            doc["originalImageHeight"] = 0
            logger.debug(f"CDN failed | {filename} | {e}")
            return rec, True


def process_cdn(records, cdn):
    """Process all images in parallel. Returns (processed, rejected) lists."""
    processed = []
    rejected = []

    with ThreadPoolExecutor(max_workers=CDN_WORKERS) as pool:
        futures = {pool.submit(cdn.process_one, r): r for r in records}
        for future in as_completed(futures):
            try:
                rec, is_rejected = future.result()
                if is_rejected:
                    rejected.append(rec["data"])
                else:
                    processed.append(rec["data"])
            except Exception as e:
                logger.error(f"CDN error: {e}")

    logger.info(f"[CDN] processed={len(processed)} | rejected={len(rejected)}")
    return processed, rejected


# ──────────────────────────────────────────────────────────────────
# PHASE D: MONGODB STORAGE
# ──────────────────────────────────────────────────────────────────
def write_to_mongo(records, collection_name):
    """Bulk insert records to MongoDB. Skips duplicates."""
    if not records:
        return 0
    uri = Variable.get("DE_MONGO_URL")
    client = MongoClient(uri)
    try:
        col = client["ingestion-data"][collection_name]
        try:
            result = col.insert_many(records, ordered=False)
            count = len(result.inserted_ids)
        except BulkWriteError as bwe:
            count = bwe.details.get("nInserted", 0)
        except Exception as e:
            logger.error(f"MongoDB error ({collection_name}): {e}")
            count = 0
        logger.info(f"[MONGO] {count} inserted to {collection_name}")
        return count
    finally:
        client.close()


# ──────────────────────────────────────────────────────────────────
# AIRFLOW TASK ENTRYPOINTS
# ──────────────────────────────────────────────────────────────────
def fetch_and_process(**kwargs):
    """
    Airflow Task 1: Fetch all feeds → 24h filter → dedup → map → scrape articles.
    Writes processed records to temp JSON file.
    """
    start = time.time()
    logger.info(f"[TASK 1] Started at {datetime.now(tz=IST)}")

    os.makedirs(TEMP_DIR, exist_ok=True)

    # Load feeds config
    feeds_df = pd.read_csv(FEEDS_CSV)
    logger.info(f"[TASK 1] Loaded {len(feeds_df)} feeds from config")

    # Phase A: Fetch
    raw_feeds = fetch_all_feeds(feeds_df)

    if not raw_feeds:
        logger.info("[TASK 1] No feeds returned data — nothing to process")
        return {"records": 0, "elapsed_min": round((time.time() - start) / 60, 2)}

    # Phase B: Process
    dedup = DedupCache()
    processed = process_feeds(raw_feeds, feeds_df, dedup)

    if not processed:
        logger.info("[TASK 1] No new records after processing")
        return {"records": 0, "elapsed_min": round((time.time() - start) / 60, 2)}

    # Write output
    batch_ts = int(time.time())
    output_path = os.path.join(TEMP_DIR, f"batch_{batch_ts}.json")
    with open(output_path, "w") as f:
        json.dump(processed, f, default=str)

    elapsed = round((time.time() - start) / 60, 2)
    logger.info(f"[TASK 1] Complete | records={len(processed)} | file={output_path} | time={elapsed}min")

    # Pass file path to next task via XCom
    return {"file": output_path, "records": len(processed), "elapsed_min": elapsed}


def cdn_and_store(**kwargs):
    """
    Airflow Task 2: CDN image processing → MongoDB bulk insert.
    Reads from temp file written by Task 1.
    """
    start = time.time()
    logger.info(f"[TASK 2] Started at {datetime.now(tz=IST)}")

    # Get file path from Task 1 via XCom
    ti = kwargs["ti"]
    task1_result = ti.xcom_pull(task_ids="fetch_and_process")

    if not task1_result or not task1_result.get("file"):
        logger.info("[TASK 2] No file from Task 1 — nothing to do")
        return {"processed": 0, "rejected": 0}

    file_path = task1_result["file"]
    if not os.path.exists(file_path):
        logger.warning(f"[TASK 2] File not found: {file_path}")
        return {"processed": 0, "rejected": 0}

    with open(file_path, "r") as f:
        records = json.load(f)

    logger.info(f"[TASK 2] Loaded {len(records)} records from {file_path}")

    # Separate: records with thumbnail → CDN, records without → already rejected
    cdn_records = [r for r in records if r.get("url")]
    pre_rejected = [r["data"] for r in records if not r.get("url")]

    logger.info(f"[TASK 2] CDN candidates={len(cdn_records)} | pre-rejected (no thumbnail)={len(pre_rejected)}")

    # Phase A: CDN processing
    processed_docs = []
    rejected_docs = list(pre_rejected)

    if cdn_records:
        cdn = ImageCDN()
        processed_docs, cdn_rejected = process_cdn(cdn_records, cdn)
        rejected_docs.extend(cdn_rejected)

    # Phase B: MongoDB writes
    inserted_ok = write_to_mongo(processed_docs, "raw_headlines_ingestion_data")

    # Add rejection metadata
    rejection_ts = epoch_now()
    for doc in rejected_docs:
        doc["rejectedAt"] = rejection_ts
        if "rejectionReason" not in doc:
            doc["rejectionReason"] = doc.get("error_message", "Image processing failed")

    inserted_rej = write_to_mongo(rejected_docs, "headlines_hygiene_failures")

    # Cleanup temp file
    try:
        os.remove(file_path)
    except Exception:
        pass

    elapsed = round((time.time() - start) / 60, 2)
    logger.info(
        f"[TASK 2] Complete | processed={inserted_ok} | rejected={inserted_rej} | time={elapsed}min"
    )
    return {"processed": inserted_ok, "rejected": inserted_rej, "elapsed_min": elapsed}
```

## `airflow/dags/utils/teams_alert.py`
```python
import json
import logging
import requests
from airflow.models import Variable


def send_teams_alert(context):
    log = logging.getLogger("airflow.task")

    webhook_url = Variable.get("TEAMS_WEBHOOK_URL")

    dag_id = context["dag"].dag_id
    task_id = context["task_instance"].task_id
    execution_date = context.get("execution_date")
    log_url = context["task_instance"].log_url
    exception = context.get("exception")
    message = {
    "type": "message",
    "attachments": [
             {   
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "body": [
                        {"type": "TextBlock", "text": "🚨 Airflow Failure", "weight": "Bolder", "size": "Large"},
                        {"type": "TextBlock", "text": f"DAG: {dag_id}"},
                        {"type": "TextBlock", "text": f"Task: {task_id}"},
                        {"type": "TextBlock", "text": f"Execution: {execution_date}"},
                        {"type": "TextBlock", "text": f"[View Logs]({log_url})"}
                    ],
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.2"
                }
            }   
        ]
    }

    log.info("Sending Teams alert")
    log.info("Teams payload: %s", json.dumps(message))

    response = requests.post(webhook_url, json=message, timeout=15)

    log.info("Teams response status: %s", response.status_code)
    log.info("Teams response body: %s", response.text)

    response.raise_for_status()
```

## `airflow/webserver_config.py`
```python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Default configuration for the Airflow webserver."""

from __future__ import annotations

import os

from flask_appbuilder.const import AUTH_DB

# from airflow.www.fab_security.manager import AUTH_LDAP
# from airflow.www.fab_security.manager import AUTH_OAUTH
# from airflow.www.fab_security.manager import AUTH_OID
# from airflow.www.fab_security.manager import AUTH_REMOTE_USER


basedir = os.path.abspath(os.path.dirname(__file__))

# Flask-WTF flag for CSRF
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# ----------------------------------------------------
# AUTHENTICATION CONFIG
# ----------------------------------------------------
# For details on how to set up each of the following authentication, see
# http://flask-appbuilder.readthedocs.io/en/latest/security.html# authentication-methods
# for details.

# The authentication type
# AUTH_OID : Is for OpenID
# AUTH_DB : Is for database
# AUTH_LDAP : Is for LDAP
# AUTH_REMOTE_USER : Is for using REMOTE_USER from web server
# AUTH_OAUTH : Is for OAuth
AUTH_TYPE = AUTH_DB

# Uncomment to setup Full admin role name
# AUTH_ROLE_ADMIN = 'Admin'

# Uncomment and set to desired role to enable access without authentication
# AUTH_ROLE_PUBLIC = 'Viewer'

# Will allow user self registration
# AUTH_USER_REGISTRATION = True

# The recaptcha it's automatically enabled for user self registration is active and the keys are necessary
# RECAPTCHA_PRIVATE_KEY = PRIVATE_KEY
# RECAPTCHA_PUBLIC_KEY = PUBLIC_KEY

# Config for Flask-Mail necessary for user self registration
# MAIL_SERVER = 'smtp.gmail.com'
# MAIL_USE_TLS = True
# MAIL_USERNAME = 'yourappemail@gmail.com'
# MAIL_PASSWORD = 'passwordformail'
# MAIL_DEFAULT_SENDER = 'sender@gmail.com'

# The default user self registration role
# AUTH_USER_REGISTRATION_ROLE = "Public"

# When using OAuth Auth, uncomment to setup provider(s) info
# Google OAuth example:
# OAUTH_PROVIDERS = [{
#   'name':'google',
#     'token_key':'access_token',
#     'icon':'fa-google',
#         'remote_app': {
#             'api_base_url':'https://www.googleapis.com/oauth2/v2/',
#             'client_kwargs':{
#                 'scope': 'email profile'
#             },
#             'access_token_url':'https://accounts.google.com/o/oauth2/token',
#             'authorize_url':'https://accounts.google.com/o/oauth2/auth',
#             'request_token_url': None,
#             'client_id': GOOGLE_KEY,
#             'client_secret': GOOGLE_SECRET_KEY,
#         }
# }]

# When using LDAP Auth, setup the ldap server
# AUTH_LDAP_SERVER = "ldap://ldapserver.new"

# When using OpenID Auth, uncomment to setup OpenID providers.
# example for OpenID authentication
# OPENID_PROVIDERS = [
#    { 'name': 'Yahoo', 'url': 'https://me.yahoo.com' },
#    { 'name': 'AOL', 'url': 'http://openid.aol.com/<username>' },
#    { 'name': 'Flickr', 'url': 'http://www.flickr.com/<username>' },
#    { 'name': 'MyOpenID', 'url': 'https://www.myopenid.com' }]

# ----------------------------------------------------
# Theme CONFIG
# ----------------------------------------------------
# Flask App Builder comes up with a number of predefined themes
# that you can use for Apache Airflow.
# http://flask-appbuilder.readthedocs.io/en/latest/customizing.html#changing-themes
# Please make sure to remove "navbar_color" configuration from airflow.cfg
# in order to fully utilize the theme. (or use that property in conjunction with theme)
# APP_THEME = "bootstrap-theme.css"  # default bootstrap
# APP_THEME = "amelia.css"
# APP_THEME = "cerulean.css"
# APP_THEME = "cosmo.css"
# APP_THEME = "cyborg.css"
# APP_THEME = "darkly.css"
# APP_THEME = "flatly.css"
# APP_THEME = "journal.css"
# APP_THEME = "lumen.css"
# APP_THEME = "paper.css"
# APP_THEME = "readable.css"
# APP_THEME = "sandstone.css"
# APP_THEME = "simplex.css"
# APP_THEME = "slate.css"
# APP_THEME = "solar.css"
# APP_THEME = "spacelab.css"
# APP_THEME = "superhero.css"
# APP_THEME = "united.css"
# APP_THEME = "yeti.css"
```

## `analysis/analyze_feeds.py`
```python
"""
Feed Health Analyzer
Analyzes 24h of FetchFeedsData logs to classify all 4856 feeds.
Produces:
  - feeds_healthy.csv  (feeds that successfully returned data)
  - feeds_error.csv    (feeds that consistently failed, with reasons)
"""

import csv
import re
import json
import collections
import pandas as pd
from pathlib import Path

FEEDS_CSV = r"C:\Users\Ankit10.Joshi\Downloads\headlines_airflow\headlines_airflow\dags\headlines_poc\feeds.csv"
import tempfile, os
_tmp = tempfile.gettempdir()
ERROR_LOG = os.path.join(_tmp, "feed_errors_24h.csv")
EMPTY_LOG = os.path.join(_tmp, "feed_empty_24h.csv")
OUTPUT_DIR = r"C:\Users\Ankit10.Joshi\Downloads\headlines_airflow"

# ---- Step 1: Parse all feeds config ----
feeds_df = pd.read_csv(FEEDS_CSV)
all_feed_ids = set(feeds_df["id"].astype(str).tolist())
print(f"Total feeds in config: {len(all_feed_ids)}")

# ---- Step 2: Parse error logs ----
error_feeds = collections.defaultdict(lambda: {
    "error_count": 0,
    "error_types": collections.Counter(),
    "urls": set(),
    "status_codes": collections.Counter(),
    "sample_error": ""
})

with open(ERROR_LOG, "r", encoding="utf-8", errors="replace") as f:
    reader = csv.reader(f)
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 2:
            continue
        text = row[-1]  # text_payload is last field

        m = re.search(r'LogId(\d+)', text)
        if not m:
            continue
        feed_id = m.group(1)

        # Extract URL
        url_match = re.search(r'Error fetching feed from (\S+)', text)
        url = url_match.group(1).rstrip("||").strip() if url_match else ""

        # Classify error type
        if "403" in text and ("Forbidden" in text or "Client Error" in text):
            err_type = "403_Forbidden"
        elif "404" in text and "Not Found" in text:
            err_type = "404_NotFound"
        elif "500" in text and "Server Error" in text:
            err_type = "500_ServerError"
        elif "502" in text:
            err_type = "502_BadGateway"
        elif "503" in text:
            err_type = "503_Unavailable"
        elif "504" in text or "Gateway Time-out" in text:
            err_type = "504_GatewayTimeout"
        elif "ConnectTimeout" in text:
            err_type = "ConnectTimeout"
        elif "ReadTimeout" in text or "Read timed out" in text:
            err_type = "ReadTimeout"
        elif "Connection refused" in text:
            err_type = "ConnectionRefused"
        elif "Max retries" in text and "ConnectTimeout" in text:
            err_type = "ConnectTimeout"
        elif "Max retries" in text:
            err_type = "MaxRetries_ConnectionFailed"
        elif "SSLError" in text or "CERTIFICATE" in text or "SSL" in text:
            err_type = "SSLError"
        elif "Name or service not known" in text or "NameResolution" in text:
            err_type = "DNS_Failure"
        elif "NewConnectionError" in text:
            err_type = "ConnectionFailed"
        elif "RemoteDisconnected" in text:
            err_type = "RemoteDisconnected"
        elif "TooManyRedirects" in text:
            err_type = "TooManyRedirects"
        elif "ChunkedEncodingError" in text:
            err_type = "ChunkedEncodingError"
        elif "ConnectionReset" in text or "Connection reset" in text:
            err_type = "ConnectionReset"
        else:
            err_type = "Other"

        sc_match = re.search(r'status_code:(\S+)', text)
        status_code = sc_match.group(1) if sc_match else "None"

        error_feeds[feed_id]["error_count"] += 1
        error_feeds[feed_id]["error_types"][err_type] += 1
        error_feeds[feed_id]["urls"].add(url)
        error_feeds[feed_id]["status_codes"][status_code] += 1
        if not error_feeds[feed_id]["sample_error"]:
            # Extract just the exception part
            exc_match = re.search(r'Exception: (.+?)(\|\||$)', text)
            error_feeds[feed_id]["sample_error"] = exc_match.group(1).strip() if exc_match else text[:200]

print(f"\nTotal unique feed_ids with errors: {len(error_feeds)}")

# ---- Step 3: Parse empty feed logs ----
empty_feeds = collections.Counter()

with open(EMPTY_LOG, "r", encoding="utf-8", errors="replace") as f:
    reader = csv.reader(f)
    next(reader, None)
    for row in reader:
        if len(row) < 2:
            continue
        text = row[-1]
        m = re.search(r'Feed Error no data feed_id-(\d+)', text)
        if not m:
            continue
        feed_id = m.group(1)
        empty_feeds[feed_id] += 1

print(f"Total unique feed_ids returning empty: {len(empty_feeds)}")

# ---- Step 4: Calculate success logs from remaining feed_ids ----
# Success logs contain "Final JSON String: {\"feed_id\": XXXX"
success_feeds = collections.Counter()

SUCCESS_LOG = os.path.join(_tmp, "feed_success_24h.csv")
try:
    with open(SUCCESS_LOG, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            text = row[-1]
            m = re.search(r'"feed_id":\s*(\d+)', text)
            if not m:
                continue
            feed_id = m.group(1)
            success_feeds[feed_id] += 1
    print(f"Total unique feed_ids with success: {len(success_feeds)}")
except FileNotFoundError:
    print("Success log not ready yet, using deduction method")

# ---- Step 5: Classify each feed ----
# 24h at 10-min intervals = ~144 cycles
TOTAL_CYCLES_APPROX = 144

results = []

for _, row in feeds_df.iterrows():
    fid = str(row["id"])

    err_count = error_feeds[fid]["error_count"] if fid in error_feeds else 0
    empty_count = empty_feeds.get(fid, 0)
    success_count = success_feeds.get(fid, 0)

    total_observed = err_count + empty_count + success_count

    # Determine primary error type
    if fid in error_feeds:
        primary_error = error_feeds[fid]["error_types"].most_common(1)[0][0]
        sample_error = error_feeds[fid]["sample_error"]
    else:
        primary_error = ""
        sample_error = ""

    # Classify feed health
    if success_count > 0 and err_count == 0 and empty_count == 0:
        status = "HEALTHY"
        reason = "Always returns data"
    elif success_count > 0 and (err_count > 0 or empty_count > 0):
        success_rate = success_count / max(total_observed, 1) * 100
        if success_rate >= 50:
            status = "HEALTHY_INTERMITTENT"
            reason = f"Returns data {success_rate:.0f}% of time, intermittent issues"
        else:
            status = "DEGRADED"
            reason = f"Returns data only {success_rate:.0f}% of time"
    elif success_count == 0 and err_count > 0 and empty_count == 0:
        status = "ERROR_ALWAYS"
        if "403" in primary_error:
            reason = "ACCESS_DENIED: Feed URL returns 403 Forbidden (IP blocked or auth required)"
        elif "404" in primary_error:
            reason = "FEED_REMOVED: Feed URL returns 404 Not Found (URL changed or removed)"
        elif "500" in primary_error:
            reason = "PUBLISHER_ERROR: Publisher server returns 500 Internal Server Error"
        elif "502" in primary_error:
            reason = "PUBLISHER_ERROR: Publisher server returns 502 Bad Gateway"
        elif "503" in primary_error:
            reason = "PUBLISHER_DOWN: Publisher server returns 503 Service Unavailable"
        elif "504" in primary_error or "Timeout" in primary_error:
            reason = "TIMEOUT: Feed URL consistently times out (publisher too slow or unreachable)"
        elif "DNS" in primary_error:
            reason = "DNS_DEAD: Domain no longer resolves (publisher domain expired or changed)"
        elif "SSL" in primary_error:
            reason = "SSL_ERROR: Certificate issue (expired, invalid, or misconfigured)"
        elif "Connection" in primary_error:
            reason = "CONNECTION_FAILED: Cannot connect to publisher server"
        else:
            reason = f"ERROR: {primary_error}"
    elif success_count == 0 and empty_count > 0 and err_count == 0:
        status = "EMPTY_ALWAYS"
        reason = "STALE_FEED: Feed URL is accessible but returns zero articles (publisher stopped publishing or feed misconfigured)"
    elif success_count == 0 and err_count > 0 and empty_count > 0:
        status = "ERROR_AND_EMPTY"
        reason = f"Mixed failures: errors ({primary_error}) and empty responses"
    elif total_observed == 0:
        status = "UNOBSERVED"
        reason = "No log data found in 24h (possible new feed or logging gap)"
    else:
        status = "UNKNOWN"
        reason = f"err={err_count}, empty={empty_count}, success={success_count}"

    results.append({
        "id": row["id"],
        "feed_url": row["feed_url"],
        "pub_name": row["pub_name"],
        "category_name": row["category_name"],
        "language_name": row["language_name"],
        "category_id": row["category_id"],
        "language_id": row["language_id"],
        "publication_id": row["publication_id"],
        "is_active": row["is_active"],
        "status": status,
        "reason": reason,
        "success_count_24h": success_count,
        "error_count_24h": err_count,
        "empty_count_24h": empty_count,
        "primary_error_type": primary_error,
        "sample_error": sample_error,
    })

results_df = pd.DataFrame(results)

# ---- Step 6: Summary ----
print("\n" + "=" * 70)
print("FEED HEALTH REPORT (24h analysis)")
print("=" * 70)

status_counts = results_df["status"].value_counts()
for status, count in status_counts.items():
    print(f"  {status}: {count}")

print(f"\n  TOTAL: {len(results_df)}")

# Healthy = HEALTHY + HEALTHY_INTERMITTENT
healthy_mask = results_df["status"].isin(["HEALTHY", "HEALTHY_INTERMITTENT"])
degraded_mask = results_df["status"] == "DEGRADED"
error_mask = results_df["status"].isin(["ERROR_ALWAYS", "ERROR_AND_EMPTY", "EMPTY_ALWAYS", "UNOBSERVED"])

print(f"\n  -> Ready for pipeline: {healthy_mask.sum()}")
print(f"  -> Degraded (include with monitoring): {degraded_mask.sum()}")
print(f"  -> Broken (remove from pipeline): {error_mask.sum()}")

# ---- Step 7: Write output files ----
# Healthy feeds config (for pipeline)
healthy_df = results_df[healthy_mask | degraded_mask][
    ["id", "category_id", "language_id", "publication_id", "feed_url",
     "category_name", "pub_name", "language_name", "is_active", "status"]
]
healthy_path = Path(OUTPUT_DIR) / "feeds_healthy.csv"
healthy_df.to_csv(healthy_path, index=False)
print(f"\n  Written: {healthy_path} ({len(healthy_df)} feeds)")

# Error feeds report (for product/content team)
error_df = results_df[error_mask].sort_values(["status", "primary_error_type", "pub_name"])
error_path = Path(OUTPUT_DIR) / "feeds_error_report.csv"
error_df.to_csv(error_path, index=False)
print(f"  Written: {error_path} ({len(error_df)} feeds)")

# Full report
full_path = Path(OUTPUT_DIR) / "feeds_full_health_report.csv"
results_df.sort_values(["status", "pub_name"]).to_csv(full_path, index=False)
print(f"  Written: {full_path} ({len(results_df)} feeds)")

# ---- Step 8: Error breakdown for product team ----
print("\n" + "=" * 70)
print("ERROR BREAKDOWN (for product/content onboarding team)")
print("=" * 70)

error_only = results_df[error_mask]
if len(error_only) > 0:
    reason_counts = error_only["reason"].apply(lambda x: x.split(":")[0]).value_counts()
    for reason, count in reason_counts.items():
        print(f"  {reason}: {count} feeds")

    print(f"\nTop publishers with broken feeds:")
    pub_errors = error_only.groupby("pub_name").size().sort_values(ascending=False).head(20)
    for pub, cnt in pub_errors.items():
        print(f"  {pub}: {cnt} broken feeds")

# ---- Step 9: Language breakdown of healthy vs broken ----
print("\n" + "=" * 70)
print("LANGUAGE BREAKDOWN")
print("=" * 70)
for lang in results_df["language_name"].unique():
    lang_df = results_df[results_df["language_name"] == lang]
    lang_healthy = lang_df[lang_df["status"].isin(["HEALTHY", "HEALTHY_INTERMITTENT", "DEGRADED"])]
    lang_broken = lang_df[lang_df["status"].isin(["ERROR_ALWAYS", "ERROR_AND_EMPTY", "EMPTY_ALWAYS", "UNOBSERVED"])]
    print(f"  {lang}: {len(lang_healthy)} healthy / {len(lang_broken)} broken (total {len(lang_df)})")
```
