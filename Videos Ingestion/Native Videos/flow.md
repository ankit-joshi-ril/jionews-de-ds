```
========================
VIDEO INGESTION PIPELINE
========================

----------------------------------
SOURCE 1 — API Upload (Partner API)
----------------------------------

JioNewsDENativeVideos
        ↓
Process Meta
        ↓
newrawheadlinesingestion-imagecdn
        ↓
Push Meta → MongoDB


----------------------------------
SOURCE 2 — Manual Upload (Editorial)
----------------------------------

yt-manual-upload
        ↓
Process Meta
        ↓
newrawheadlinesingestion-imagecdn
        ↓
Push Meta → MongoDB


----------------------------------
SOURCE 3 — MRSS Feeds / Partner APIs
----------------------------------

mrssvideos-fetchfeedsdata
        ↓
mrssvideos-processvideos
        ↓
newrawheadlinesingestion-imagecdn (generic)
        ↓
mrssvideos-downloadvideos
        ↓
mrssvideos-pushtomongodb


=================================================
POST-INGESTION PROCESSING (AFTER RAW SAVED TO GCS)
=================================================

(transcoder cron workflow)

transcoder-push-to-sftp-batching
        ↓
transcoder-push-to-sftp
        ↓
External Transcoder Workflow
        ↓
transcoder-update-content-status
        (poll CPP API, update status,
         fetch HLS URLs, update MongoDB meta)


===========================================
RSS FEED GENERATION (FOR JioHotstar / JHS)
===========================================

RawVideosHLSContentPrepareRss_AggregateDataLanguageSplit
        ↓
RawVideosHLSContentPrepareRss_ProcessRssFeedLanguageSplit
        ↓
Generate Language-wise RSS XML
        ↓
Push RSS to GCS (Consumed by JHS)
```