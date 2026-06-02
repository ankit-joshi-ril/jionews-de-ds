# MongoDB Cleanup - Deploy & Run

## Files
- `cleanup.py` — the script, entry point: `process(request=None)`
- `requirements.txt` — just PyMongo

---

## Step 1: Deploy as Cloud Run Function

```bash
gcloud functions deploy cleanup \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point process \
  --timeout 60 \
  --memory 256MB
```

Grab the URL from the output (or run):
```bash
gcloud functions describe cleanup --format="value(httpsTrigger.url)"
```

---

## Step 2: Test One Batch Manually

```bash
curl https://YOUR_FUNCTION_URL
```

**Expected logs:**
```
✅ Connected
🆕 First run - initializing
Current IST : 2026-04-29 10:00:00
Cutoff (6mo): 2025-10-29 10:00:00
Progress    : batch #1 | total deleted so far: 0
Collection  : raw_headlines_ingestion_data
  Old docs   : 18,147,628
  Deleted    : 10,000
  Remaining  : 18,137,628
  → Staying on raw_headlines_ingestion_data
✅ Batch #1 complete | total deleted: 10,000
```

**Verify in MongoDB Compass:**
```javascript
use("ingestion-data")
db.cleanup_status.findOne()
// { _id: "progress", collection_idx: 0, batches: 1, total_deleted: 10000, complete: false }
```

---

## Step 3: Set Up Cloud Scheduler

```bash
gcloud scheduler jobs create http cleanup-scheduler \
  --location us-central1 \
  --schedule "*/5 * * * *" \
  --uri "https://YOUR_FUNCTION_URL" \
  --http-method GET

# Enable
gcloud scheduler jobs resume cleanup-scheduler
```

---

## Monitoring

Check progress anytime in MongoDB Compass:
```javascript
use("ingestion-data")
db.cleanup_status.findOne()
```

---

## Timeline (10K batch / 5 min)

| Time    | Batches | Deleted |
|---------|---------|---------|
| 1 day   | 288     | 2.88M   |
| 3 days  | 864     | 8.64M   |
| 8 days  | 2,304   | 23M     |
| 16 days | 4,608   | 46M ✅  |

Scale up `BATCH_SIZE` after first test if cluster handles it fine.

---

## Done

When `complete: true` shows in `cleanup_status`, all 46M docs are deleted.
Scheduler can stay running — script exits safely with no more work to do.
Pause anytime: `gcloud scheduler jobs pause cleanup-scheduler`
