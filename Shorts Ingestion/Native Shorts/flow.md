```
========================
NATIVE SHORTS INGESTION
========================

----------------------------------
SOURCE 1 — API Upload (Partner API)
----------------------------------

JioNewsDENativeVideos (tagged as Shorts)
        ↓
Process Meta
        ↓
newrawheadlinesingestion-imagecdn
        ↓
Push Meta → MongoDB


----------------------------------
SOURCE 2 — Manual Upload (Editorial)
----------------------------------

yt-manual-upload (Shorts)
        ↓
Process Meta
        ↓
newrawheadlinesingestion-imagecdn
        ↓
Push Meta → MongoDB


----------------------------------
SOURCE 3 — MRSS Feeds / Partner APIs
----------------------------------

mrssshorts-fetchfeedsdata
        ↓
mrssshorts-processvideos
        ↓
mrssshorts-downloadvideos
        ↓
Push Raw MP4 + Meta → MongoDB / GCS


===========================================
RSS FEED GENERATION (FOR JioHotstar / JHS)
===========================================

(Note: Shorts skip transcoding — JHS consumes raw MP4 files)

RawShortsContentPrepareRss_AggregateDataLanguageSplit
        ↓
RawShortsContentPrepareRss_ProcessRssFeedLanguageSplit
        ↓
Generate Language-wise RSS XML
        ↓
Push RSS to GCS (Consumed by JHS)
```