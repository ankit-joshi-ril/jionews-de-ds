# JioNews DE-DS (Data Engineering & Data Science)

A FastAPI-based dashboard for validating, onboarding, and analyzing RSS/JSON/MRSS feeds for the JioNews platform. Combines Claude AI-powered chat interfaces with MongoDB analytics for feed management and data insights.

---

## Features

### Publisher Onboarding
- Chat-based feed validation for **Headlines**, **Videos**, and **Summaries**
- Multi-step validation: accessibility, format, metadata, thumbnails, media quality
- Confidence scoring (0-100) with PASSED / WARNING / FAILED verdicts
- Auto-append validated feeds to CSV configuration

### Smart Analytics
- Natural language queries against MongoDB ingestion data
- Read-only access with whitelisted operations (`find`, `aggregate`, `count_documents`, `distinct`)
- Claude tool-use loop for multi-step analytical workflows
- Real-time date/epoch context injection

### Feed Management
- Browse feeds with filters (language, publisher, category, feed type)
- Export as CSV, Excel, or JSON
- Aggregate statistics and distribution views

### Web Dashboard
- Interactive chat UI for onboarding and analytics
- Markdown-rendered responses with syntax highlighting
- Session-based conversation history
- Feed browser with search and filtering

---

## Project Structure

```
JioNews DE-DS/
├── feed-evaluator/              # Main application
│   ├── app.py                   # FastAPI entry point
│   ├── requirements.txt         # Python dependencies
│   ├── .env.example             # Environment template
│   ├── feed_validator.py        # Core validation engine
│   ├── config/                  # Feed CSVs & skill/guardrail prompts
│   ├── managers/                # MongoDB & publisher config managers
│   ├── routers/                 # API route handlers
│   ├── services/                # Claude client, prompt builder, loaders
│   ├── tools/                   # Claude tool definitions
│   ├── validators/              # Feed-type-specific validators
│   ├── static/                  # Frontend CSS & JS
│   └── templates/               # HTML templates
├── Headlines Ingestion/         # Headlines pipeline scripts
├── Summaries Ingestion/         # Summaries pipeline scripts
├── Videos Ingestion/            # Video ingestion scripts
├── Shorts Ingestion/            # Shorts pipeline scripts
├── Webstories Ingestion/        # Webstories pipeline scripts
├── JioBharat Video Summaries/   # Video summary pipelines
├── Auto Summarization/          # Auto summarization scripts
├── architecture/                # Architecture documentation
├── knowledge-base/              # Specs & reference docs
└── Projects/                    # Sub-projects (ads-revenue-dashboard)
```

---

## Prerequisites

- **Python 3.10+**
- **MongoDB** (Atlas or local instance with ingestion data)
- **Anthropic API Key** (for Claude integration)

---

## Setup

### 1. Clone & Navigate

```bash
cd "JioNews DE-DS/feed-evaluator"
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example and fill in your values:

```bash
cp .env.example .env          # Linux/Mac
copy .env.example .env        # Windows CMD
```

Edit `.env`:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
MONGODB_URI=mongodb+srv://username:password@host/

# Optional (defaults shown)
CLAUDE_MODEL=claude-sonnet-4-20250514
PORT=8000
MONGODB_DATABASE=ingestion-data
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | - | Anthropic API key |
| `MONGODB_URI` | Yes | - | MongoDB connection string |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-20250514` | Claude model to use |
| `PORT` | No | `8000` | Server port |
| `MONGODB_DATABASE` | No | `ingestion-data` | MongoDB database name |

### 5. Start the Server

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Open the Dashboard

Navigate to **http://localhost:8000** in your browser.

---

## API Endpoints

### Health
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check (API key, MongoDB, modules) |

### Feed Management
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/feeds/list` | List feeds (filters: `feed_type`, `language`, `publisher`, `category`, `limit`) |
| `GET` | `/api/feeds/download` | Export feeds as CSV / Excel / JSON |
| `GET` | `/api/feeds/stats` | Aggregate feed statistics |
| `GET` | `/api/feeds/query` | Predefined analytics queries |

### Publisher Onboarding
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/onboarding/chat` | Chat-based feed validation & onboarding |
| `POST` | `/api/onboarding/reset` | Clear onboarding conversation history |

### Analytics
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/analytics/chat` | Natural language MongoDB queries |
| `POST` | `/api/analytics/reset` | Clear analytics conversation history |

---

## Feed Types & Validation

### Headlines (RSS/JSON)
- Feed accessibility and format validation
- 12-step thumbnail extraction and verification
- Entry freshness check (< 48 hours)
- Required fields: title, link, published date, thumbnail

### Videos (MRSS/RSS)
- MP4 URL extraction and accessibility
- File integrity validation (magic bytes)
- 1080p resolution verification
- YouTube/Vimeo URL detection and flagging

### Summaries (RSS/JSON)
- Summary content length hygiene
- HTML contamination detection
- Required fields: title, link, summary, published date

### Confidence Scoring
| Score | Verdict | Meaning |
|---|---|---|
| 70-100 | PASSED | Feed meets all requirements |
| 50-69 | WARNING | Feed has minor issues |
| 0-49 | FAILED | Feed has critical issues |

---

## Supported Languages

English, Hindi, Gujarati, Marathi, Telugu, Tamil, Bangla, Urdu, Kannada, Malayalam, Odia, Punjabi, Assamese

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Uvicorn |
| AI | Claude (Anthropic API) with tool-use |
| Database | MongoDB (read-only analytics) |
| Feed Parsing | feedparser, BeautifulSoup4 |
| Data | pandas, openpyxl |
| HTTP Client | httpx |
| Frontend | Vanilla JS, marked.js, DOMPurify |
| Templates | Jinja2 |

---

## Architecture Notes

- **Modular design** - routers, managers, services, tools, and validators are cleanly separated
- **Read-only MongoDB** - no write operations; hard limit of 100 docs per query; `$out`/`$merge` blocked
- **CSV-based feed config** - atomic row append only (no deletion/modification), auto-incrementing IDs
- **Session state** - per-session conversation history stored in memory (single-user / small team use)
- **Non-destructive validation** - all feed checks are dry-run; no side effects on source feeds
