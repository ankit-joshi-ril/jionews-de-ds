import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

URI = "mongodb+srv://de-user:asjdhuewnbhvbv_234@jionews-de-mongo.jionews.com/?tls=true&authSource=admin"
IST = timezone(timedelta(hours=5, minutes=30))

client = MongoClient(URI, serverSelectionTimeoutMS=10000)
db = client["ingestion-data"]
db.command("ping")
print("Connected OK")

now_ist = datetime.now(IST)
cutoff = int((now_ist - timedelta(days=180)).timestamp())
print(f"Current IST : {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Cutoff (6mo): {(now_ist - timedelta(days=180)).strftime('%Y-%m-%d %H:%M:%S')}")

baseline = {
    "raw_headlines_ingestion_data":      {"old": 18147628, "keep": 3746234},
    "raw_headlines_stg":                 {"old": 4065890,  "keep": 3746488},
    "headlines_scraper_data":            {"old": 9573992,  "keep": 0},
    "embeddings":                        {"old": 7648245,  "keep": 10},
    "summaries_hygiene_failure":         {"old": 0,        "keep": 726998},
    "raw_summaries_insgestion_data":     {"old": 725699,   "keep": 545416},
    "summaries_hygiene_failure_stg":     {"old": 0,        "keep": 27077},
    "raw_videos_ingestion_data":         {"old": 3425349,  "keep": 1063274},
    "raw_short_videos_ingestion_data":   {"old": 1053368,  "keep": 432786},
    "raw_summaries_insgestion_data_stg": {"old": 664674,   "keep": 350435},
    "headlines_hygiene_failures":        {"old": 0,        "keep": 159573},
    "raw_videos_rss":                    {"old": 612040,   "keep": 126678},
    "raw_web_stories_ingestion_data":    {"old": 248247,   "keep": 1613},
    "raw_videos_native":                 {"old": 811,      "keep": 58124},
    "auto_summarization":                {"old": 1340,     "keep": 6607},
}

skipped = ["jio_bharat_summaries", "summaries_av_gen_logs", "awards_form_data_prod", "ians_videos"]

print()
print("=" * 100)
print("COLLECTION AUDIT")
print("=" * 100)
print(f"{'Collection':<44} {'Exp.Keep':>10} {'Actual':>10} {'OldLeft':>10}  Status")
print("-" * 100)

total_old_remaining = 0
issues = []

for coll, b in baseline.items():
    actual = db[coll].estimated_document_count()
    old_remaining = db[coll].count_documents({"createdAt": {"$lt": cutoff}})
    total_old_remaining += old_remaining
    flag = "CLEAN" if old_remaining == 0 else "!! HAS OLD DOCS"
    if old_remaining > 0:
        issues.append((coll, old_remaining))
    print(f"{coll:<44} {b['keep']:>10,} {actual:>10,} {old_remaining:>10,}  {flag}")

print()
print(f"Total old docs still remaining : {total_old_remaining:,}")
print(f"Collections with issues        : {len(issues)}")
for c, r in issues:
    print(f"  >> {c}: {r:,} old docs remain")

print()
print("=" * 100)
print("SKIPPED COLLECTIONS (no createdAt in Phase 0)")
print("=" * 100)
for coll in skipped:
    count = db[coll].estimated_document_count()
    print(f"{coll:<44} {count:>10,} docs (not touched)")

print()
print("=" * 100)
print("CLEANUP STATUS DOCUMENT")
print("=" * 100)
status = db["cleanup_status"].find_one({"_id": "progress"})
if status:
    for k, v in status.items():
        print(f"  {k}: {v}")
else:
    print("  No cleanup_status document found")

print()
print("=" * 100)
print("DB SIZE (before was 501 GB data / 179 GB storage)")
print("=" * 100)
s = db.command("dbStats")
print(f"  dataSize   : {s['dataSize'] / (1024**3):.2f} GB")
print(f"  storageSize: {s['storageSize'] / (1024**3):.2f} GB")
print(f"  objects    : {s['objects']:,}")
print(f"  collections: {s['collections']}")

client.close()
