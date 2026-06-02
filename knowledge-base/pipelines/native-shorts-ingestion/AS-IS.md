# Native Shorts Ingestion - AS-IS State

## Current Operational State

| Attribute | Value |
|---|---|
| **Status** | Production |
| **Environment** | GCP `jiox-328108` |
| **Execution Runtime** | Python (Cloud Functions Gen1) |
| **Data Store** | MongoDB `ingestion-data.raw_videos_rss` (shared with Native Videos) |
| **Dedup Mechanism** | Redis `de_mrss_shorts_cache` (48h TTL) |

## Current Behavior

### Source 1: JioNewsDENativeVideos (Shared Function)

This is a shared Cloud Function used by both the Native Videos and Native Shorts pipelines. Content is classified as Shorts based on editorial tagging at upload time.

1. Receives content upload events via Pub/Sub.
2. Editorial metadata tags the content with `contentType="shorts"`.
3. Processes the video metadata and inserts into `raw_videos_rss` with `contentType="shorts"`.
4. Portrait orientation is set: `sourceVideoOrientation="portrait"`.

### Source 2: yt-manual-upload (Shared Function)

This shared Cloud Function handles YouTube content that is manually uploaded and repackaged for the JioNews platform.

1. Receives upload events via Pub/Sub.
2. Sets `contentType="shorts"` for shorts content.
3. Uses `oar2.jpg` as the thumbnail source for these uploads.
4. Inserts records into `raw_videos_rss`.

### Source 3: MRSS Feeds (Dedicated Shorts Pipeline)

This is a three-stage dedicated pipeline for ingesting shorts from external MRSS feeds.

#### Stage 1: mrssshorts-fetchfeedsdata

1. Reads the MRSS feed configuration from `gs://de-raw-ingestion/shorts/mrss_shorts_feeds.csv`.
2. For each feed URL in the CSV, fetches the feed data using `ThreadPoolExecutor(100)` for concurrent retrieval.
3. Parses the JSON response:
   - **Feed IDs 49 and 50:** The data array is accessed via the key `'data'` (i.e., `response['data']`).
   - **All other feed IDs:** The data array is accessed via the key `'items'` (i.e., `response['items']`).
4. Publishes all raw feed records to Pub/Sub topic `MRSSShortsIngestion_RawFeedsData`.

#### Stage 2: mrssshorts-processvideos

1. Receives raw feed records from Pub/Sub `MRSSShortsIngestion_RawFeedsData`.
2. **Redis Deduplication:** Constructs a cache key from a combination of `title`, `link`, `category`, and `language` fields. Checks the Redis cache `de_mrss_shorts_cache` (TTL: 48 hours). Records already in cache are skipped.
3. **Publisher-Specific Processing:**
   - **Publisher 7777/7778:** Applies a `videotype` filter. Only records where the videotype field matches one of: `"shorts"`, `"short"`, `"short video"`, `"shortvideo"` are processed.
   - **Publisher 7782 (IANS):** Extracts the video URL from `record.get('video')` instead of the standard field.
4. Sets content metadata:
   - `contentType = "shorts"`
   - `sourceVideoOrientation = "portrait"`
5. **Default Image Handling:** When no thumbnail is available, a random default image is selected from range 1-5 (compared to 1-10 for the native videos pipeline).
6. Publishes thumbnail images to `NewRawHeadlinesIngestion_image_cdn` for CDN processing.
7. Inserts records into MongoDB `ingestion-data.raw_videos_rss` via `insert_many`.
8. Publishes each processed record individually to `MRSSShortsIngestion_ProcessedData`.

#### Stage 3: mrssshorts-downloadvideos

1. Receives processed records from Pub/Sub `MRSSShortsIngestion_ProcessedData`.
2. Downloads the video file from the source URL.
3. Uploads the raw MP4 file to GCS: `hls_video_transcoder_storage_output_files/raw_videos/{video_id}.mp4`.
4. **No transcoding is performed.** Unlike the Native Videos pipeline, shorts skip the HLS transcoding step entirely.
5. Updates the MongoDB record:
   - `processingStatus = "completed"`
   - `videoContentUrl = "https://vcdn.jionews.com/raw_videos/{video_id}.mp4"`

## Known Limitations and Considerations

### Shared Collection with Native Videos

- The `raw_videos_rss` collection is shared between the Native Shorts and Native Videos pipelines. The only differentiator is the `contentType` field (`"shorts"` vs. `"videos"`).
- Queries against this collection must always include a `contentType` filter to avoid mixing content types.
- Index design must account for both content types sharing the same collection.

### No Transcoding for Shorts

- Shorts are served as raw MP4 files directly from GCS via CDN (`vcdn.jionews.com`).
- This means there is no adaptive bitrate streaming (HLS) for shorts content.
- The raw MP4 URL pattern is: `https://vcdn.jionews.com/raw_videos/{video_id}.mp4`.

### Redis Cache Dependency

- The `de_mrss_shorts_cache` Redis instance is critical for deduplication. If Redis is unavailable, all records will be treated as new, leading to duplicate ingestion.
- The 48-hour TTL means records can be re-ingested after 48 hours if they still appear in the MRSS feed.

### Publisher-Specific Logic

- Feed IDs 49/50 use a different JSON key (`'data'` vs `'items'`), which is hardcoded.
- Publishers 7777/7778 require videotype filtering with specific string matches.
- Publisher 7782 (IANS) uses a non-standard field for video URLs.
- Adding new publishers with non-standard feed formats requires code changes.

### ThreadPoolExecutor Concurrency

- `ThreadPoolExecutor(100)` creates up to 100 concurrent threads for feed fetching.
- This can generate significant outbound network traffic and may trigger rate limiting on publisher feed endpoints.
- No per-publisher rate limiting is implemented.

### Default Image Range

- The default image random selection range is 1-5 for shorts (vs. 1-10 for videos).
- This is a hardcoded difference between the two pipelines.

## Error Handling

| Scenario | Current Behavior |
|---|---|
| MRSS feed CSV not found | Function fails with unhandled exception |
| Feed endpoint unreachable | Individual feed skipped; ThreadPoolExecutor handles exceptions |
| Redis unavailable | All records treated as new (no dedup) |
| Redis key collision | Record skipped (treated as duplicate) |
| Invalid videotype for 7777/7778 | Record excluded from processing |
| Video download failure | Record not updated; processingStatus remains incomplete |
| GCS upload failure | Record not updated; downstream serving affected |
| MongoDB insert failure | `insert_many` partial failure handling |
| Pub/Sub publish failure | Message lost; no application-level retry |

## Operational Notes

- The pipeline shares infrastructure with the Native Videos pipeline, including the MongoDB collection and the shared Cloud Functions (JioNewsDENativeVideos, yt-manual-upload).
- All MRSS-sourced shorts go through the three-stage pipeline: fetch, process, download.
- The CDN URL pattern for shorts is deterministic: `https://vcdn.jionews.com/raw_videos/{video_id}.mp4`.
