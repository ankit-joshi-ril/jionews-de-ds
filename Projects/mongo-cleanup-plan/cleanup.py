"""
MongoDB Batch Cleanup via Cloud Scheduler
Batch: 50K
Recommended schedule: every 2–3 minutes
"""

import logging
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGODB_URI = "mongodb+srv://de-user:asjdhuewnbhvbv_234@jionews-de-mongo.jionews.com/?tls=true&authSource=admin"
DATABASE = "ingestion-data"
BATCH_SIZE = 50000

COLLECTIONS = [
    "raw_headlines_ingestion_data", "raw_headlines_stg", "headlines_scraper_data",
    "embeddings", "raw_videos_ingestion_data", "raw_short_videos_ingestion_data",
    "raw_summaries_insgestion_data", "raw_summaries_insgestion_data_stg",
    "raw_videos_rss", "raw_web_stories_ingestion_data",
    "summaries_hygiene_failure", "summaries_hygiene_failure_stg",
    "headlines_hygiene_failures", "raw_videos_native", "auto_summarization",
]

IST = timezone(timedelta(hours=5, minutes=30))


def get_six_months_ago_epoch():
    now = datetime.now(IST)
    cutoff = now - timedelta(days=180)
    return int(cutoff.timestamp())


def process(request=None):
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[DATABASE]
    db.command("ping")
    logger.info("✅ Connected")

    status_coll = db["cleanup_status"]
    status = status_coll.find_one({"_id": "progress"})

    if not status:
        logger.info("🆕 First run - initializing")
        status = {
            "_id": "progress",
            "collection_idx": 0,
            "total_deleted": 0,
            "batches": 0,
            "complete": False
        }
        status_coll.insert_one(status)

    if status["complete"]:
        logger.info("✅ Cleanup already complete.")
        client.close()
        return "complete"

    cutoff = get_six_months_ago_epoch()
    now_ist = datetime.now(IST)
    logger.info(f"Current IST : {now_ist.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Cutoff      : {(now_ist - timedelta(days=180)).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Progress    : batch #{status['batches'] + 1} | total deleted: {status['total_deleted']:,}")

    idx = status["collection_idx"]

    if idx >= len(COLLECTIONS):
        logger.info("🎉 ALL COLLECTIONS DONE")
        status_coll.update_one({"_id": "progress"}, {"$set": {"complete": True}})
        client.close()
        return "complete"

    coll_name = COLLECTIONS[idx]
    coll = db[coll_name]
    logger.info(f"Collection  : {coll_name}")

    # safer sampling
    sample = coll.find_one({"createdAt": {"$exists": True}})
    if not sample:
        logger.info("  → No createdAt field, skipping")
        status_coll.update_one({"_id": "progress"}, {"$set": {"collection_idx": idx + 1}})
        client.close()
        return "skipped"

    # fetch batch
    old_ids = [
        doc["_id"] for doc in
        coll.find(
            {"createdAt": {"$lt": cutoff}},
            {"_id": 1}
        ).sort("createdAt", 1).limit(BATCH_SIZE)
    ]

    if not old_ids:
        logger.info("  → No old docs, moving to next collection")
        status_coll.update_one({"_id": "progress"}, {"$set": {"collection_idx": idx + 1}})
        client.close()
        return "no_old_docs"

    # delete safely
    result = coll.delete_many({
        "_id": {"$in": old_ids},
        "createdAt": {"$lt": cutoff}
    })

    deleted = result.deleted_count

    logger.info(f"  Deleted    : {deleted:,}")

    new_total = status["total_deleted"] + deleted
    new_batches = status["batches"] + 1

    if deleted < BATCH_SIZE:
        # collection done
        status_coll.update_one(
            {"_id": "progress"},
            {
                "$set": {
                    "total_deleted": new_total,
                    "batches": new_batches,
                    "collection_idx": idx + 1
                }
            }
        )
        logger.info(f"  → Collection done, moving next")

    else:
        # continue same collection
        status_coll.update_one(
            {"_id": "progress"},
            {
                "$set": {
                    "total_deleted": new_total,
                    "batches": new_batches
                }
            }
        )
        logger.info(f"  → Continuing same collection")

    logger.info(f"✅ Batch #{new_batches} done | total deleted: {new_total:,}")

    client.close()
    return "success"
