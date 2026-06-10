"""
backfill_sample.py
Backfills isHygienic, videoWidth, videoHeight for a sample of 1000 records
per content type using partial CDN range requests + hachoir.

Usage: python backfill_sample.py <content_type>  (videos or shorts)
"""
import sys, os, time, tempfile, warnings, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import gcd
warnings.filterwarnings('ignore')
from pymongo import MongoClient, UpdateOne
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata

MONGO_URI = "mongodb+srv://de-user:asjdhuewnbhvbv_234@jionews-de-mongo.jionews.com/?tls=true&authSource=admin"
ALLOWED = {
    'videos': {(1920, 1080), (1280, 720)},
    'shorts': {(1080, 1920), (720, 1280)}
}
SAMPLE_SIZE   = 1000
RANGE_BYTES   = 2 * 1024 * 1024   # 2MB
THREADS       = 12
BATCH_SIZE    = 50

# Deploy timestamps — only backfill records before this
DEPLOY_TS = {
    'videos': 1780402200,   # 2026-06-02 15:20 IST
    'shorts': 1780402800,   # 2026-06-02 15:30 IST
}


def safe_int(val, default=0):
    try:
        return int(val) if val is not None else default
    except:
        return default


def aspect_ratio(w, h):
    try:
        if not w or not h:
            return ""
        g = gcd(int(w), int(h))
        return f"{w // g}:{h // g}"
    except:
        return ""


def get_dims_from_bytes(data):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(data)
            tmp = f.name
        parser = createParser(tmp)
        if not parser:
            return 0, 0
        with parser:
            meta = extractMetadata(parser)
        if not meta:
            return 0, 0
        w = safe_int(meta.get('width'))  if meta.has('width')  else 0
        h = safe_int(meta.get('height')) if meta.has('height') else 0
        return w, h
    except:
        return 0, 0
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except:
                pass


def fetch_bytes(url, start=0, size=RANGE_BYTES):
    try:
        headers = {'Range': f'bytes={start}-{start + size - 1}'}
        r = requests.get(url, headers=headers, timeout=20, stream=False)
        if r.status_code in (200, 206):
            return r.content
    except:
        pass
    return None


def fetch_last_bytes(url, size=RANGE_BYTES):
    try:
        headers = {'Range': f'bytes=-{size}'}
        r = requests.get(url, headers=headers, timeout=20, stream=False)
        if r.status_code in (200, 206):
            return r.content
    except:
        pass
    return None


def get_resolution(url):
    if not url or not url.startswith('http'):
        return 0, 0
    # Try first 2MB (faststart MP4 — moov at front)
    data = fetch_bytes(url)
    if data:
        w, h = get_dims_from_bytes(data)
        if w > 0:
            return w, h
    # Fallback: last 2MB (moov at end)
    data = fetch_last_bytes(url)
    if data:
        w, h = get_dims_from_bytes(data)
        if w > 0:
            return w, h
    return 0, 0


def process_record(rec, allowed):
    video_id = rec.get('sourceVideoId', '')
    url      = rec.get('videoContentUrl', '')
    now      = int(time.time())

    w, h = get_resolution(url)

    update = {'updatedAt': now}

    if w > 0 and h > 0:
        update['videoWidth']        = w
        update['videoHeight']       = h
        update['videoAspectRatio']  = aspect_ratio(w, h)
        if (w, h) in allowed:
            update['isHygienic'] = True
        else:
            update['isHygienic']           = False
            update['hygieneFailureReason'] = (
                f"Unsupported resolution {w}x{h}. "
                f"Supported: {', '.join(f'{rw}x{rh}' for rw, rh in sorted(allowed))}"
            )
    else:
        # Could not read dimensions from partial download
        update['videoWidth']  = 0
        update['videoHeight'] = 0
        # Do not set isHygienic — leave unset so we can track unknowns

    return video_id, update, w, h


def run(content_type):
    client  = MongoClient(MONGO_URI)
    col     = client['ingestion-data']['raw_videos_rss']
    allowed = ALLOWED[content_type]
    deploy  = DEPLOY_TS[content_type]

    query = {
        'contentType':      content_type,
        'createdAt':        {'$lt': deploy},
        'isHygienic':       {'$exists': False},
        'processingStatus': 'completed',
        'videoContentUrl':  {'$exists': True, '$ne': ''}
    }

    # Take most recent 1000 records
    records = list(
        col.find(query, {'sourceVideoId': 1, 'videoContentUrl': 1, 'transcoderProcessingStatus': 1})
           .sort('createdAt', -1)
           .limit(SAMPLE_SIZE)
    )

    total = len(records)
    print(f"[{content_type}] Fetched {total} records to backfill")

    passed  = 0
    failed  = 0
    unknown = 0
    done    = 0
    bulk    = []

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(process_record, r, allowed): r for r in records}
        for fut in as_completed(futures):
            video_id, update, w, h = fut.result()
            bulk.append(UpdateOne({'sourceVideoId': video_id}, {'$set': update}))

            if w > 0:
                if update.get('isHygienic') is True:
                    passed += 1
                else:
                    failed += 1
            else:
                unknown += 1

            done += 1
            if len(bulk) >= BATCH_SIZE:
                col.bulk_write(bulk, ordered=False)
                bulk = []
                print(f"[{content_type}] {done}/{total} | passed={passed} failed={failed} unknown={unknown}")

    if bulk:
        col.bulk_write(bulk, ordered=False)

    print(f"\n[{content_type}] COMPLETE")
    print(f"  Total    : {total}")
    print(f"  Passed   : {passed}  ({passed/total*100:.1f}%)")
    print(f"  Failed   : {failed}  ({failed/total*100:.1f}%)")
    print(f"  Unknown  : {unknown}  ({unknown/total*100:.1f}%)")
    return total, passed, failed, unknown


if __name__ == '__main__':
    content_type = sys.argv[1] if len(sys.argv) > 1 else 'videos'
    run(content_type)
