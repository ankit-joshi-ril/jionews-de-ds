import base64
import io
import json
import random
import time
import warnings

import requests
from PIL import Image, ImageOps
from google.cloud import pubsub_v1
from google.cloud import storage
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ALERT_WEBHOOK_URL = "https://rilcloud.webhook.office.com/webhookb2/50d9b364-0092-40a4-a5c4-95d82953ae66@fe1d95a9-4ce1-41a5-8eab-6dd43aa26d9f/IncomingWebhook/bcbbb2121e7649deae43fca4539a50af/6c18cadb-8d47-4378-bbd9-016fd8e3b86b/V2DRdo9Nv42MRg2nadbCJqxhMxzCmddmv_vBzooEDKb-E1"

MIN_SHORT_EDGE = 480
MIN_LONG_EDGE = 720

RENDITION_SIZES = [
    ((1920, 1080), "fhd"),
    ((1280, 720), "hd"),
    ((720, 480), "sd"),
    ((480, 320), "low")
]

# Category mapping for default images (from old script)
CATEGORY_MAP = {
    "Agro": "agro",
    "Astrology": "astrology",
    "Auto": "automobile",
    "Business": "business",
    "Money": "business",
    "Career": "education",
    "Entertainment": "entertainment",
    "Movie Reviews": "entertainment",
    "Health": "health",
    "Corona": "health",
    "National": "india",
    "Regional": "india",
    "World": "international",
    "Top News": "latest_news",
    "Top Stories": "latest_news",
    "news": "latest_news",
    "News": "latest_news",
    "Lifestyle": "lifestyle",
    "Fashion": "lifestyle",
    "Sci & Tech": "sci_and_tech",
    "Sports": "sports",
    "cricket": "cricket"
}


class Alert:
    @staticmethod
    def send_alert(error_message, publisher, content_type="Other"):
        custom_message = {
            "title": "Error Processing Publisher Image to CDN",
            "text": f"Content Type: {content_type}",
            "sections": [
                {
                    "facts": [
                        {"name": "Severity", "value": "SEV-3"},
                        {"name": "Cloud Function name", "value": "NewRawHeadlinesIngestion_ImageCDN"},
                        {"name": "Publisher Name", "value": publisher},
                        {"name": "Error Message", "value": str(error_message)},
                    ],
                    "markdown": True
                }
            ]
        }
        try:
            response = requests.post(ALERT_WEBHOOK_URL, json=custom_message, verify=False, timeout=10)
            if response.status_code == 200:
                print("Alert message sent successfully!")
            else:
                print(f"Failed to send alert message. Status code: {response.status_code}")
        except Exception as e:
            print(f"Failed to send alert message. Exception: {e}")


class PubSub:
    @staticmethod
    def publish_message_to_topic(topic_name, data):
        project_id = "jiox-328108"
        pubsub = pubsub_v1.PublisherClient()
        topic_path = pubsub.topic_path(project_id, topic_name)
        pubsub.publish(topic_path, data=json.dumps(data).encode("utf-8"))


class CDN:
    def __init__(self):
        self.bucket_name = "img-cdn-bucket"
        self.processed_headlines = []
        self.rejected_headlines = []
        self.processed_videos = []
        self.rejected_videos = []
        self.processed_summaries = []
        # Cache GCS client at class level for efficiency
        self._storage_client = None

    @property
    def storage_client(self):
        """Lazy-loaded cached GCS client."""
        if self._storage_client is None:
            self._storage_client = storage.Client()
        return self._storage_client

    # ---------- helpers ----------
    def download(self, url):
        r = requests.get(url, timeout=10, verify=False)
        r.raise_for_status()
        return r.content

    def get_size(self, b):
        with Image.open(io.BytesIO(b)) as img:
            transposed = ImageOps.exif_transpose(img)
            size = transposed.size
            if transposed is not img:
                transposed.close()
            return size

    def resize(self, b, size):
        with Image.open(io.BytesIO(b)) as img:
            transposed = ImageOps.exif_transpose(img)
            try:
                if transposed.mode in ("RGBA", "P"):
                    transposed = transposed.convert("RGB")
                transposed.thumbnail(size, Image.Resampling.LANCZOS)
                w, h = transposed.size
                out = io.BytesIO()
                transposed.save(out, format="JPEG", quality=90)
                return out.getvalue(), w, h
            finally:
                if transposed is not img:
                    transposed.close()

    def upload(self, folder, name, data):
        bucket = self.storage_client.bucket(self.bucket_name)
        bucket.blob(f"{folder}/{name}.jpeg").upload_from_string(data)

    def _get_mapped_category(self, category):
        """Map category to default image folder name using CATEGORY_MAP."""
        if not category:
            return "latest_news"
        stripped = category.strip()
        return CATEGORY_MAP.get(stripped, stripped.lower().replace(" ", "_")) or "latest_news"

    def set_default_category_images(self, category, name):
        """Copy default category images for all sizes. Returns True on success, False on failure."""
        sizes = ["original", "fhd", "hd", "sd", "low"]
        mapped = self._get_mapped_category(category)
        bucket = self.storage_client.bucket(self.bucket_name)

        try:
            for s in sizes:
                # latest_news has more default images (1-22), others have 1-10
                max_num = 22 if mapped == "latest_news" else 10
                rnd = random.randint(1, max_num)
                src = f"default/{mapped}/{s}/{mapped}_{rnd}.png"
                dst = f"{s}/{name}.jpeg"
                bucket.copy_blob(bucket.blob(src), bucket, dst)
            return True
        except Exception as e:
            print(
                f"Error setting default category images. Category: {category}, Mapped: {mapped}, Name: {name}. Exception: {e}")
            return False

    # ---------- headline processing ----------
    def process_headline(self, filename, url, headline_rec):
        """
        Process headline images.
        - Download and validate image dimensions
        - If approved: upload to CDN and add to processed_headlines
        - If rejected (download fails): add to rejected_headlines (no default images)
        """
        orig_w = orig_h = 0
        rejected = False
        original = None

        try:
            original = self.download(url)
            orig_w, orig_h = self.get_size(original)

            # if min(orig_w, orig_h) < MIN_SHORT_EDGE or max(orig_w, orig_h) < MIN_LONG_EDGE:
            #     rejected = True
            #     print(f"Headline image rejected due to size. Filename: {filename}, Size: {orig_w}x{orig_h}")
        except Exception as e:
            rejected = True
            print(f"Headline image download failed. Filename: {filename}, URL: {url}, Exception: {e}")

        headline_rec["originalImageWidth"] = orig_w
        headline_rec["originalImageHeight"] = orig_h
        # headline_rec["isOriginalImageRejected"] = rejected

        if rejected:
            # Headlines with rejected images go to rejected_headlines (no default images per new logic)
            # self.set_default_category_images(category, filename)
            self.rejected_headlines.append(headline_rec)
            print(f"Headline rejected. Filename: {filename}")
        else:
            self.upload("original", filename, original)
            for size, folder in RENDITION_SIZES:
                data, w, h = self.resize(original, size)
                self.upload(folder, filename, data)
            self.processed_headlines.append(headline_rec)
            print(f"Headline image processed successfully. Filename: {filename}")

    # ---------- video processing ----------
    def process_video(self, filename, url, category, video_rec):
        """
        Process video thumbnail images.
        - Download and validate image dimensions
        - If rejected (download fails OR dimensions too small): use default images, update metadata, still pass to processed
        - All videos go to processed_videos (with metadata indicating rejection status)
        """
        base = "https://icdn.jionews.com"
        orig_w = orig_h = 0
        rejected = False
        original = None

        try:
            original = self.download(url)
            orig_w, orig_h = self.get_size(original)
            if min(orig_w, orig_h) < MIN_SHORT_EDGE or max(orig_w, orig_h) < MIN_LONG_EDGE:
                rejected = True
                print(f"Video thumbnail rejected due to size. Filename: {filename}, Size: {orig_w}x{orig_h}")
        except Exception as e:
            rejected = True
            print(f"Video thumbnail download failed. Filename: {filename}, URL: {url}, Exception: {e}")

        video_rec["originalThumbnailWidth"] = orig_w
        video_rec["originalThumbnailHeight"] = orig_h
        video_rec["isOriginalThumbnailRejected"] = rejected

        if rejected:
            self.set_default_category_images(category, filename)
            video_rec["thumbnailUrls"] = {
                "default": {"url": f"{base}/original/{filename}.jpeg", "width": 1920, "height": 1080},
                "medium": {"url": f"{base}/low/{filename}.jpeg", "width": 480, "height": 320},
                "standard": {"url": f"{base}/sd/{filename}.jpeg", "width": 720, "height": 480},
                "high": {"url": f"{base}/hd/{filename}.jpeg", "width": 1280, "height": 720},
                "maxres": {"url": f"{base}/fhd/{filename}.jpeg", "width": 1920, "height": 1080},
            }
            # Videos with rejected images still go to processed (with default images)
            # self.rejected_videos.append(video_rec)
            self.processed_videos.append(video_rec)
            print(f"Video thumbnail defaulted successfully. Filename: {filename}")
        else:
            self.upload("original", filename, original)
            meta = {}
            for size, folder in RENDITION_SIZES:
                data, w, h = self.resize(original, size)
                self.upload(folder, filename, data)
                meta[folder] = (w, h)

            video_rec["thumbnailUrls"] = {
                "default": {"url": f"{base}/original/{filename}.jpeg", "width": orig_w, "height": orig_h},
                "medium": {"url": f"{base}/low/{filename}.jpeg", "width": meta["low"][0], "height": meta["low"][1]},
                "standard": {"url": f"{base}/sd/{filename}.jpeg", "width": meta["sd"][0], "height": meta["sd"][1]},
                "high": {"url": f"{base}/hd/{filename}.jpeg", "width": meta["hd"][0], "height": meta["hd"][1]},
                "maxres": {"url": f"{base}/fhd/{filename}.jpeg", "width": meta["fhd"][0], "height": meta["fhd"][1]},
            }
            self.processed_videos.append(video_rec)
            print(f"Video thumbnail processed successfully. Filename: {filename}")

    # ---------- summary processing ----------
    def process_summary(self, filename, url, category, summary_rec):
        """
        Process summary images.
        - Download and validate image dimensions
        - If successful: upload to CDN and add to processed_summaries
        - If unsuccessful (download fails): rename publisher to Inside media and tag  default image
        """
        orig_w = orig_h = 0
        missing_thumbnail = False
        original = None

        try:
            original = self.download(url)
            orig_w, orig_h = self.get_size(original)

            # if min(orig_w, orig_h) < MIN_SHORT_EDGE or max(orig_w, orig_h) < MIN_LONG_EDGE:
            #     rejected = True
            #     print(f"Headline image rejected due to size. Filename: {filename}, Size: {orig_w}x{orig_h}")
        except Exception as e:
            # Set default category image and update metadata
            print("Setting default category image")
            self.set_default_category_images(category, filename)
            # Rename publisher to inside media for records with missing thumbnail (STORY 51524)
            summary_rec['thumbnailError'] = str(e)
            summary_rec['isDefaultThumbnail'] = True
            summary_rec['sourcePublisherName'] = "Inside Media"
            summary_rec['sourcePublisherId'] = "000"
            missing_thumbnail = True

        # summary_rec["originalImageWidth"] = orig_w
        # summary_rec["originalImageHeight"] = orig_h
        # headline_rec["isOriginalImageRejected"] = rejected

        if not missing_thumbnail:
            self.upload("original", filename, original)
            for size, folder in RENDITION_SIZES:
                data, w, h = self.resize(original, size)
                self.upload(folder, filename, data)
            print(f"Summary image processed successfully. Filename: {filename}")

        self.processed_summaries.append(summary_rec)

    # ---------- other content processing ----------
    def process_other_content(self, filename, url, category, publisher, content_type):
        """
        Process images for content types other than headlines and videos.
        This is async processing - no Pub/Sub publishing, just image CDN upload.
        On failure, sets default category images and sends an alert.
        """
        try:
            original = self.download(url)
            self.upload("original", filename, original)

            for size, folder in RENDITION_SIZES:
                resized_data, w, h = self.resize(original, size)
                self.upload(folder, filename, resized_data)

            print(f"Other content image processed successfully. Filename: {filename}, ContentType: {content_type}")

        except Exception as e:
            print(
                f"Error processing other content image. Setting default category image. Category: {category}, URL: {url}, Exception: {e}")
            self.set_default_category_images(category, filename)
            message = f"Couldn't process image. Default category images have been set. Publisher: {publisher}. Image URL: {url}. Exception: {e}"
            Alert.send_alert(message, publisher, content_type=content_type or "Other")

    # ---------- generic dispatcher ----------
    def process(self, rec):
        filename = rec.get("filename", "")
        url = rec.get("url", "")
        category = rec.get("category", "")
        publisher = rec.get("publisher", "")
        content_type = rec.get("content_type", "")
        data = rec.get("data", {})

        if not filename or not url:
            print(f"Skipping record with missing filename or url. Record: {rec}")
            return

        if content_type == "headlines":
            self.process_headline(filename, url, data)
        elif content_type == "videos":
            self.process_video(filename, url, category, data)
        elif content_type == "summaries":
            self.process_summary(filename, url, category, data)
        else:
            self.process_other_content(filename, url, category, publisher, content_type)


class Execute:
    def __init__(self):
        self.cdn = CDN()

    def run(self, message):
        parsed = json.loads(base64.b64decode(message["data"]).decode())

        for rec in parsed:
            self.cdn.process(rec)

        print(f"Total {len(parsed)} records received")

        # Headline topics - only approved go to processed, rejected go to rejected topic
        total_headlines = len(self.cdn.processed_headlines) + len(self.cdn.rejected_headlines)
        if self.cdn.processed_headlines:
            print(f"Total {len(self.cdn.processed_headlines)} of {total_headlines} headlines processed successfully")
            PubSub.publish_message_to_topic(
                "NewRawHeadlinesIngestion_processed_data",
                self.cdn.processed_headlines
            )

        if self.cdn.rejected_headlines:
            print(f"Total {len(self.cdn.rejected_headlines)} of {total_headlines} headlines rejected")
            PubSub.publish_message_to_topic(
                "NewRawHeadlinesIngestion_rejected_data",
                self.cdn.rejected_headlines
            )

        # Publish videos individually - both processed and rejected go through (rejected have default images)
        total_videos = len(self.cdn.processed_videos) + len(self.cdn.rejected_videos)
        if self.cdn.processed_videos:
            print(f"Total {len(self.cdn.processed_videos)} of {total_videos} video thumbnails processed successfully")
            for rec in self.cdn.processed_videos:
                PubSub.publish_message_to_topic(
                    "MRSSVideosIngestion_ProcessedData",
                    [rec]
                )

        # Activate this when we wanna deactivate image defaulting logic just like headlines
        # if self.cdn.rejected_videos:
        #     print(f"Total {len(self.cdn.rejected_videos)} of {total_videos} video thumbnails defaulted")
        #     for rec in self.cdn.rejected_videos:
        #         PubSub.publish_message_to_topic(
        #             "MRSSVideosIngestion_ProcessedData",
        #             [rec]
        #         )

        # Publish all updated summaries
        if self.cdn.processed_summaries:
            print(f"Total {len(self.cdn.processed_summaries)} summaries processed (with or without defaulting)")
            PubSub.publish_message_to_topic(
                "RawSummariesIngestion_ProcessedData",
                self.cdn.processed_summaries
            )


def main(req):
    start = time.time()
    try:
        message = req.get_json()["message"]
        Execute().run(message)
        print(f"Completed in {(time.time() - start) / 60:.2f} mins")
        return {"result": "success"}
    except Exception as e:
        print(f"Error in main execution. Exception: {e}")
        print(f"Failed after {(time.time() - start) / 60:.2f} mins")
        return {"result": "error", "message": str(e)}