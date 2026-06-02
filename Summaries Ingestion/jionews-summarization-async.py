import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import redis
import requests
from anthropic import AnthropicVertex
from google import genai
from google.auth import default
from google.cloud import pubsub_v1, secretmanager
from google.genai import types
from google.genai.types import GenerateContentConfig
from google.oauth2 import service_account
from pymongo import MongoClient, ReturnDocument, UpdateOne, errors

logging.basicConfig(
    level=logging.INFO,  # Explicitly set INFO level
    # format="%(levelname)s:%(name)s:%(message)s",
    format="%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # Direct logs to stdout
    ]
)

logger = logging.getLogger(__name__)

try:
    service_account_json_str = os.getenv("GCP_SERVICE_ACCOUNT")
    mongodb_collection_name = os.getenv("MONGO_COLLECTION_NAME")
    pubsub_subscription_name = os.getenv("SUB_NAME")
    pubsub_publish_topic_name = os.getenv("PUB_TOPIC_NAME")
    instance = os.getenv("ENV")
    service_account_creds = json.loads(service_account_json_str)
except Exception as e:
    logging.error(f"Error loading service account credentials: {e}")
    service_account_creds = None


class Utils:
    @staticmethod
    def epoch_now():
        zone = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=zone)
        return int(now.timestamp())


class PubSub:
    def __init__(self):
        self.project_id = "jiox-328108"

        self.subscription_name = pubsub_subscription_name  # Topic: RawSummariesIngestion_HygineFailure_STG
        # self.subscription_name = "SummarizationHygieneRepocessTest_Sub"  # Topic: SummarizationHygieneRepocessTest
        # self.subscription_name = "youtube_scrapper_test_sub"
        self.subscriber_client, self.publisher_client = self.get_pubsub_clients()
        self.subscription_path = self.subscriber_client.subscription_path(self.project_id, self.subscription_name)

    def get_pubsub_clients(self):
        # Configure Pub/Sub Clients
        if service_account_creds:
            # Use the service account credentials from the environment variable
            subscriber_client = pubsub_v1.SubscriberClient.from_service_account_info(service_account_creds)
            publisher_client = pubsub_v1.PublisherClient.from_service_account_info(service_account_creds)
        else:
            # Use the default credentials for local development
            credentials, project = default()
            subscriber_client = pubsub_v1.SubscriberClient(credentials=credentials)
            publisher_client = pubsub_v1.PublisherClient(credentials=credentials)

        return subscriber_client, publisher_client

    def publish_message_to_topic(self, topic_name, data):
        pubsub = self.publisher_client
        topic_path = pubsub.topic_path(self.project_id, topic_name)

        json_string = json.dumps(data)
        logger.info(f"Final JSON String for pubsub: {json_string}")
        message_bytes = json_string.encode("utf-8")
        try:
            pubsub.publish(topic_path, data=message_bytes)
        except Exception as err:
            logger.info(f"Message Publishing Error: {err}")


class GCPHandler:
    def __init__(self):
        try:
            self.secret_client = secretmanager.SecretManagerServiceClient().from_service_account_info(
                service_account_creds)
        except Exception:
            self.secret_client = secretmanager.SecretManagerServiceClient()

    def get_secret(self, secret_name: str) -> str:
        response = self.secret_client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8")


class RedisDedup:
    """Redis-based deduplication layer with 24-hour TTL."""

    REDIS_URL = "redis://:u4YIVWZBcNiYCPFj!@35.200.220.40:6379"
    TTL_SECONDS = 86400  # 24 hours
    KEY_PREFIX = "summarization_hygiene_reprocess_dedup:"

    def __init__(self):
        try:
            self.client = redis.from_url(self.REDIS_URL, decode_responses=True, socket_timeout=5,
                                         socket_connect_timeout=5)
            self.client.ping()
            self.connected = True
            logger.info("Connected to Redis successfully.")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Dedup will be skipped.")
            self.client = None
            self.connected = False

    def _key(self, source_id: str) -> str:
        return f"{self.KEY_PREFIX}{source_id}"

    def is_duplicate(self, source_id: str) -> bool:
        """Return True if the record was already processed (exists in Redis)."""
        if not self.connected:
            return False
        try:
            return self.client.exists(self._key(source_id)) == 1
        except Exception as e:
            logger.warning(f"Redis lookup failed for {source_id}: {e}")
            return False

    def mark_processed(self, source_id: str):
        """Mark a record as processed with 24-hour TTL."""
        if not self.connected:
            return
        try:
            self.client.set(self._key(source_id), "1", ex=self.TTL_SECONDS)
        except Exception as e:
            logger.warning(f"Redis set failed for {source_id}: {e}")


class MongoDBHandler:
    def __init__(self, uri: str, db_name: str, collection_name: str):
        try:
            self.client = MongoClient(uri)
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            self.client.server_info()
            logging.info("Connected to MongoDB successfully.")
        except Exception as e:
            logging.error(f"MongoDB connection failed: {e}")
            raise RuntimeError("Error connecting to MongoDB.")

    def upsert_record(self, source_id: str, record: dict):
        try:
            now = int(time.time())

            update_doc = {
                "$set": {
                    "articleContent": record.get("articleContent", ""),
                    "articleUrl": record.get("articleUrl", ""),
                    "title": record.get("title", ""),
                    "summary": record.get("summary", ""),
                    "compliance_score": record.get("compliance_score"),
                    "generate": record.get("generate", []),
                    "processingSource": record.get("processingSource", ""),
                    "model": record.get("model", ""),
                    "error_message": record.get("error_message", ""),
                    "updatedAt": now,
                },
                "$setOnInsert": {
                    "createdAt": now,
                    "sourceId": source_id
                },
                "$inc": {"updateCount": 1}
            }

            return self.collection.find_one_and_update(
                {"sourceId": source_id},
                update_doc,
                upsert=True,
                return_document=ReturnDocument.AFTER
            )

        except errors.PyMongoError as e:
            logging.error(f"Database operation failed: {e}")

    def upsert_records_bulk(self, records: list[dict]):
        """
        Bulk upsert based on sourceId.
        Upserts the entire record (no hardcoded fields).
        Adds updatedAt on every update and createdAt only on insert.
        """
        try:
            if not records:
                return {"matched": 0, "modified": 0, "upserted": 0, "skipped": 0}

            now = int(time.time())
            ops = []
            skipped = 0

            for record in records:
                source_id = record.get("sourceId")
                if not source_id:
                    skipped += 1
                    continue

                # Make a copy so we don't mutate the original input
                doc = dict(record)

                # Always update updatedAt
                doc["updatedAt"] = now

                # Never allow overriding createdAt from incoming record
                doc.pop("createdAt", None)

                ops.append(
                    UpdateOne(
                        {"sourceId": source_id},
                        {
                            "$set": doc,
                            "$setOnInsert": {"createdAt": now},
                        },
                        upsert=True,
                    )
                )

            if not ops:
                return {"matched": 0, "modified": 0, "upserted": 0, "skipped": skipped}

            result = self.collection.bulk_write(ops, ordered=False)

            return {
                "matched": result.matched_count,
                "modified": result.modified_count,
                "upserted": len(result.upserted_ids) if result.upserted_ids else 0,
                "skipped": skipped,
            }

        except errors.PyMongoError as e:
            logging.error(f"Bulk upsert failed: {e}")
            return None


class Processor:
    def __init__(self):
        self.gcp_handler = GCPHandler()
        self.ps = PubSub()

        gemini_secret_name = "projects/266686822828/secrets/GEMINI_API_KEY/versions/latest"
        mongo_uri_key = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"

        self.gemini_api_key = self.gcp_handler.get_secret(gemini_secret_name)
        self.mongo_uri = self.gcp_handler.get_secret(mongo_uri_key)
        self.mongo_handler = MongoDBHandler(self.mongo_uri, "ingestion-data", mongodb_collection_name)

        self.genai_client = genai.Client(api_key=self.gemini_api_key)
        self.gemini_primary_model = "gemini-2.5-flash"
        self.gemini_fallback_model = "gemini-2.5-flash-lite"

        # Claude via Vertex AI (for bangla, tamil, gujarati)
        if service_account_creds:
            claude_credentials = service_account.Credentials.from_service_account_info(
                service_account_creds,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.claude_client = AnthropicVertex(region="global", project_id="jiox-328108",
                                                 credentials=claude_credentials)
        else:
            self.claude_client = AnthropicVertex(region="global", project_id="jiox-328108")
        self.claude_primary_model = "claude-haiku-4-5@20251001"
        self.claude_fallback_model = "claude-sonnet-4-6@default"

        # Language routing: Gemini vs Claude
        # Gujarati is not listed here — not yet integrated. Falls through to Gemini.
        self.gemini_languages = {"english", "hindi", "marathi", "kannada"}
        self.claude_languages = {"bangla", "bengali", "tamil"}

        # Per-language config for the XML-structured Claude prompt (tickets 55043, 55949, 55951)
        # Keys: language name (lowercase) | Values: (system_display_name, grammar_rule, include_factual_self_check)
        self.claude_language_config = {
            "tamil": (
                "Tamil",
                "Correct agglutinative verb forms, postpositions, SOV order, case markers (\u0bb5\u0bc7\u0bb1\u0bc1\u0bae\u0bc8 \u0b89\u0bb0\u0bc1\u0baa\u0bc1\u0b95\u0bb3\u0bcd).",
                True   # Include factual accuracy self-check
            ),
            "bangla": (
                "Bengali/Bangla",
                "Correct verb conjugations for person/tense, classifiers (\u09aa\u09a6\u09be\u09b6\u09cd\u09b0\u09bf\u09a4 \u09a8\u09bf\u09b0\u09cd\u09a6\u09c7\u09b6\u0995), proper sandhi rules.",
                True   # Include factual accuracy self-check per ticket 55949
            ),
            "bengali": (
                "Bengali/Bangla",
                "Correct verb conjugations for person/tense, classifiers (\u09aa\u09a6\u09be\u09b6\u09cd\u09b0\u09bf\u09a4 \u09a8\u09bf\u09b0\u09cd\u09a6\u09c7\u09b6\u0995), proper sandhi rules.",
                True
            ),
            "gujarati": (
                "Gujarati",
                "Gender agreement for nouns/adjectives, correct postpositions and verb conjugations.",
                True   # Include factual accuracy self-check per ticket 55951
            ),
            "gujrati": (
                "Gujarati",
                "Gender agreement for nouns/adjectives, correct postpositions and verb conjugations.",
                True
            ),
        }

        # Redis dedup layer
        self.redis_dedup = RedisDedup()

        #

        # UPDATED SYSTEM INSTRUCTION (EDITORIAL + HYGIENE BASELINE)
        # self.system_instruction = (
        #     "You are a senior news editor for a reputable, high-traffic digital news outlet.\n"
        #     "Your responsibility is to generate publishable news content that is highly engaging, "
        #     "editorially responsible, accurate, and ethical.\n"
        #     "You must balance urgency with credibility. You may use intelligent sentence framing "
        #     "to increase curiosity and engagement, but you must NOT be misleading, dishonest, or speculative.\n\n"
        #     "EDITORIAL HYGIENE RULES (STRICT AND NON-NEGOTIABLE):\n"
        #     "- Title length MUST be between 26 and 105 characters\n"
        #     "- Summary length MUST be between 200 and 360 characters\n"
        #     "- If you cannot fit within the limits, rewrite and compress/expand while keeping meaning\n"
        #     "- Never exceed 105 characters for title or 360 characters for summary under any condition\n"
        #     "- Do NOT include HTML tags, markup, or formatting\n"
        #     "- Do NOT include emojis\n"
        #     "- Do NOT include excessive special characters\n"
        #     "- Use clean, professional language suitable for a news outlet\n"
        #     "- No meta text, headings, labels, or explanations\n"
        #     "- No reasoning, planning, drafts, analysis, or commentary\n\n"
        #     "Output ONLY the requested content in the specified format."
        # )

        # self.system_instruction = system_instruction = (
        #     "You are a senior news editor for a reputable, high-traffic digital news outlet.\n"
        #     "Your responsibility is to generate publishable news content that is highly engaging, "
        #     "editorially responsible, accurate, and ethical.\n"
        #     "You act as a news editor/writer and summarize news articles accurately and concisely."
        #     "Your output must be ONLY a single summary between 350 and 360 characters. "
        #     "Do NOT include: reasoning, planning, steps, drafts, explanations, "
        #     "notes, meta comments, chain-of-thought, or analysis. "
        #     "\nNever exceed 15 words (must stay under 105 characters) for title and 45 words (must stay under 105 characters)characters) summary under any condition\n"
        #     "\nIf you cannot fit within the limits, rewrite and compress/expand while keeping meaning"
        # )

        # self.user_message = (
        #     "Generate the following from the article below:\n\n"
        #     "1) Engaging / Social Media Headline\n"
        #     "   - Length between 26 and 105 characters\n"
        #     "   - Must spark curiosity and sharing without being misleading\n"
        #     "   - Must be accurate, ethical, and context-rich\n\n"
        #     "2) News Summary\n"
        #     "   - Length between 350 and 360 characters\n"
        #     "   - Focus on factual information, key developments, and outcomes\n"
        #     "   - Include 5W1H where applicable\n\n"
        #     "3) Compliance Score\n"
        #     "   - Integer from 0 to 100\n"
        #     "   - Reflects how strictly you followed ALL instructions\n\n"
        #     "4) error_message\n"
        #     "   - Must be an empty string \"\" if generation succeeded\n"
        #     "   - If the article cannot be accessed, is unavailable, or content is insufficient, "
        #     "return empty title and summary, compliance_score = 0, and set error_message with the reason.\n\n"
        #     "Return STRICTLY valid, parsable JSON in the following format WITHOUT any additional text.\n"
        #     "Return ONLY a single JSON object.\n"
        #     "Do NOT include markdown, backticks, code fences, comments, or any text before or after the JSON.\n\n"
        #     '{ "title": "", "summary": "", "compliance_score": 0, "error_message": "" }'
        # )

        # self.user_message = (
        #     "Generate the following from the article below:\n\n"
        #     "1) Engaging / Social Media Headline Title\n"
        #     "   - Title length MUST be strictly under 15 words (must stay under 105 characters)\n"
        #     "   - Must spark curiosity and sharing without being misleading\n"
        #     "   - Must be accurate, ethical, and context-rich\n\n"
        #     "2) News Summary\n"
        #     "   - Summary length MUST be strictly between 35 and 50 words (must stay between 200 and 360 characters)\n"
        #     "   - Focus on factual information, key developments, and outcomes\n"
        #     "3) Compliance Score\n"
        #     "   - Integer from 0 to 100\n"
        #     "   - Reflects how strictly you followed ALL instructions\n\n"
        #     "4) error_message\n"
        #     "   - Must be an empty string \"\" if generation succeeded\n"
        #     "   - If the article cannot be accessed, is unavailable, or content is insufficient, "
        #     "return empty title and summary, compliance_score = 0, and set error_message with the reason.\n\n"
        #     "Return STRICTLY valid, parsable JSON in the following format WITHOUT any additional text.\n"
        #     "Return ONLY a single JSON object.\n"
        #     "Do NOT include markdown, backticks, code fences, comments, or any text before or after the JSON.\n\n"
        #     '{ "title": "", "summary": "", "compliance_score": 0, "error_message": "" }\n\n'
        #     "\nNever exceed 105 characters for title or 360 characters for summary under any condition\n"
        #     "\nIf you cannot fit within the limits, rewrite and compress/expand while keeping meaning"
        # )

        # Compiled regex patterns for access failure detection.
        # Each pattern covers a family of phrasings (contractions, passive voice, split words).
        self.ACCESS_FAILURE_PATTERNS = [
            # Pattern 1: [negation] + [action verb]
            # Catches: unable to access, couldn't access, can not browse, could not be fetched, etc.
            re.compile(
                r"(?:unable|(?:could|can)\s*(?:n[o']t|not)|couldn't|can't)\s+(?:to\s+)?(?:be\s+)?"
                r"(?:access|browse|fetch|retrieve|summarize|reach|read|load|open)",
                re.IGNORECASE
            ),
            # Pattern 2: not + [adjective form]
            # Catches: not accessible, not retrievable, not available, not reachable, inaccessible
            re.compile(
                r"(?:not\s+(?:accessible|retrievable|available|reachable)|inaccessible|unreachable)",
                re.IGNORECASE
            ),
            # Pattern 3: article/content/url/page + unavailable/not found
            # Catches: article unavailable, content not found, url is unavailable, page not found
            re.compile(
                r"(?:article|content|url|page|link|resource)\s+(?:is\s+)?(?:unavailable|not\s+found|not\s+available|empty|missing)",
                re.IGNORECASE
            ),
            # Pattern 4: URL did not contain / insufficient content
            # Catches: url did not contain, did not have sufficient content, no content found
            re.compile(
                r"(?:(?:url|link|page)\s+did\s+not\s+contain|insufficient\s+content|no\s+(?:article\s+)?content)",
                re.IGNORECASE
            ),
            # Pattern 5: please ensure/check/verify the URL
            # Catches: please ensure the url, please check the url, verify the link
            re.compile(
                r"(?:please|kindly)\s+(?:ensure|check|verify)\s+(?:the\s+)?(?:url|link)",
                re.IGNORECASE
            ),
            # Pattern 6: I am unable / I cannot / I could not / I'm unable
            # Catches: i am unable to, i'm unable to, i cannot, i could not, i couldn't
            re.compile(
                r"i\s*(?:'m|am)\s+unable|i\s+(?:cannot|could\s*n[o']t|couldn't|can't)",
                re.IGNORECASE
            ),
        ]

        self.MAX_RETRIES = 3
        self.BACKOFF_BASE = 2  # seconds
        self.success_recs = []

    def print_current_timestamp_ist(self):
        ist_time = datetime.now(tz=ZoneInfo('Asia/Kolkata'))
        return str(ist_time)

    def get_article_content_via_proxy(self, article_url: str) -> str:
        base_url = "https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy"
        proxy_url = f"{base_url}?url={quote(article_url)}"

        try:
            resp = requests.get(proxy_url, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logging.error(f"Error fetching article via proxy: {e}")
            return ""

    def safe_parse_llm_json(self, text: str):
        """
        Safely parses JSON from LLM output.

        Strategy:
        1. Try direct json.loads
        2. Strip markdown fences and retry
        3. Extract first {...} block and retry
        4. Return None if all fail
        """

        if not text or not isinstance(text, str):
            return None

        text = text.strip()

        # ---------- Attempt 1: direct parse ----------
        try:
            return json.loads(text)
        except Exception:
            pass

        # ---------- Attempt 2: remove markdown fences ----------
        cleaned = text

        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

            try:
                return json.loads(cleaned)
            except Exception:
                pass

        # ---------- Attempt 3: extract first valid JSON object ----------
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = cleaned[first_brace:last_brace + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass

        # ---------- All attempts failed ----------
        return None

    def is_access_failure_text(self, text: str) -> bool:
        if not text:
            return True
        return any(pattern.search(text) for pattern in self.ACCESS_FAILURE_PATTERNS)

    def contains_html_tags(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        return bool(re.search(r"</?[a-z][\s\S]*>", text, re.IGNORECASE))

    def special_char_check(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        special_chars = "@#$%^&*()_+=[]{}\\|<>/?"
        count = sum(1 for ch in text if ch in special_chars)
        return count >= 3

    def check_publisher_summary_hygiene(self, record) -> dict:
        title = record.get('title', "")
        summary = record.get('summary', "")
        errors = []

        try:
            # ---- TITLE CHECKS ----
            if not title:
                errors.append({"key": "title", "value": "Title is empty"})
            else:
                if len(title) < 26:
                    errors.append({"key": "title", "value": "Title is less than 26 characters"})
                if len(title) > 105:
                    errors.append({"key": "title", "value": "Title is more than 105 characters"})
                if self.contains_html_tags(title):
                    errors.append({"key": "title", "value": "Title contains HTML characters"})
                if self.special_char_check(title):
                    errors.append({"key": "title", "value": "Title contains special characters"})

            # ---- SUMMARY CHECKS ----
            if not summary:
                errors.append({"key": "summary", "value": "Summary is empty"})
            else:
                if len(summary) < 200:
                    errors.append({"key": "summary", "value": "Summary is less than 200 characters"})
                if len(summary) > 360:
                    errors.append({"key": "summary", "value": "Summary is more than 360 characters"})
                if self.contains_html_tags(summary):
                    errors.append({"key": "summary", "value": "Summary contains HTML characters"})
                if self.special_char_check(summary):
                    errors.append({"key": "summary", "value": "Summary contains special characters"})

            return {
                "isHygienic": len(errors) == 0,
                "errors": errors
            }

        except Exception as e:
            return {
                "isHygienic": False,
                "errors": [{"key": "", "value": str(e)}]
            }

    def determine_generate_fields(self, record) -> str:
        """
        Inspect the record's hygieneErrors to decide which fields
        need regeneration.
        Returns: "title_only", "summary_only", or "both"
        """
        hygiene_errors = record.get("hygieneErrors", [])

        if not hygiene_errors:
            return "both"

        failed_keys = set()
        for err in hygiene_errors:
            key = err.get("key", "").strip().lower()
            if key in ("title", "summary"):
                failed_keys.add(key)

        if failed_keys == {"title", "summary"}:
            return "both"
        elif failed_keys == {"title"}:
            return "title_only"
        elif failed_keys == {"summary"}:
            return "summary_only"
        else:
            return "both"

    def gemini_call(self, article_url="", article_content="", language_name="", generate_fields="both"):
        # Build system instruction based on which fields need regeneration
        system_instruction_base = (
            "You are a senior news editor for a reputable, high-traffic digital news outlet.\n"
            "Your responsibility is to generate publishable news content that is highly engaging, "
            "editorially responsible, accurate, and ethical.\n"
            "You act as a news editor/writer and summarize news articles accurately and concisely."
            "Do NOT include: reasoning, planning, steps, drafts, explanations, "
            "notes, meta comments, chain-of-thought, or analysis."
        )

        if generate_fields == "title_only":
            system_instruction_constraints = (
                "\nNever exceed 18 words (must stay under 90 characters) for the title under any condition.\n"
                "\nIf you cannot fit within the limits, rewrite and compress while keeping meaning.\n"
            )
        elif generate_fields == "summary_only":
            system_instruction_constraints = (
                "\nNever exceed 60 words (must stay under 310 characters) for the summary under any condition.\n"
                "\nIf you cannot fit within the limits, rewrite and compress/expand while keeping meaning.\n"
            )
        else:
            system_instruction_constraints = (
                "\nNever exceed 18 words (must stay under 90 characters) for title and 60 words (must stay under 310 characters) for summary under any condition\n"
                "\nIf you cannot fit within the limits, rewrite and compress/expand while keeping meaning.\n"
            )

        system_instruction = (
                system_instruction_base
                + system_instruction_constraints
                + f"Make sure to generate the output in {language_name} language."
        )

        # Build user_message dynamically based on generate_fields mode
        user_message_header = f"Generate the following from the article below strictly in {language_name} language:\n\n"

        # Title section (only if title needs regeneration)
        title_section = ""
        if generate_fields in ("title_only", "both"):
            title_section = (
                "1) Engaging / Social Media Headline Title\n"
                f"   - Title length MUST be strictly between 6 to 18 words (must stay between 40 to 90 characters) and in {language_name} language\n"
                "   - Must spark curiosity and sharing without being misleading\n"
                "   - Must be accurate, ethical, and context-rich\n\n"
                "   - Do not start the title with a city name\n"
            )

        # Summary section (only if summary needs regeneration)
        summary_section = ""
        if generate_fields in ("summary_only", "both"):
            summary_num = 2 if generate_fields == "both" else 1
            summary_section = (
                f"{summary_num}) News Summary in {language_name} language\n"
                "   - Summary length MUST be strictly between 45 to 60 words (must stay between 225 to 310 characters)\n"
                "   - Focus on factual information, key developments, and outcomes\n"
            )

        # Compliance and error sections (numbering adjusts per mode)
        if generate_fields == "both":
            compliance_num, error_num = 3, 4
        else:
            compliance_num, error_num = 2, 3

        compliance_section = (
            f"{compliance_num}) Compliance Score\n"
            "   - Integer from 0 to 100\n"
            "   - Reflects how strictly you followed ALL instructions\n\n"
        )

        # Mode-specific error fallback text and JSON template
        if generate_fields == "title_only":
            error_fallback = "return empty title, compliance_score = 0, and set error_message with the reason.\n\n"
            json_template = '{ "title": "", "compliance_score": 0, "error_message": "" }'
            constraint_reminder = "\nNever exceed 90 characters for title under any condition\n"
        elif generate_fields == "summary_only":
            error_fallback = "return empty summary, compliance_score = 0, and set error_message with the reason.\n\n"
            json_template = '{ "summary": "", "compliance_score": 0, "error_message": "" }'
            constraint_reminder = "\nNever exceed 310 characters for summary under any condition\n"
        else:
            error_fallback = "return empty title and summary, compliance_score = 0, and set error_message with the reason.\n\n"
            json_template = '{ "title": "", "summary": "", "compliance_score": 0, "error_message": "" }'
            constraint_reminder = "\nNever exceed 90 characters for title or 310 characters for summary under any condition\n"

        error_section = (
                f"{error_num}) error_message\n"
                "   - Must be an empty string \"\" if generation succeeded\n"
                "   - If the article cannot be accessed, is unavailable, or content is insufficient, "
                + error_fallback
        )

        json_instruction = (
            "Return STRICTLY valid, parsable JSON in the following format WITHOUT any additional text.\n"
            "Return ONLY a single JSON object.\n"
            "Do NOT include markdown, backticks, code fences, comments, or any text before or after the JSON.\n\n"
            f"{json_template}\n\n"
            f"{constraint_reminder}"
            "\nIf you cannot fit within the limits, rewrite and compress/expand while keeping meaning"
        )

        user_message = (
                user_message_header
                + title_section
                + summary_section
                + compliance_section
                + error_section
                + json_instruction
        )

        error_message = ""
        reprocessing_status = ""
        raw_gemini_response = None

        if article_url:
            user_message += f"\n\nArticle URL:\n{article_url}"
        if article_content:
            user_message += f"\n\nArticle Content:\n{article_content.strip()}"

        logger.info(f"User Message to Gemini: {user_message}")

        models_to_try = [self.gemini_primary_model, self.gemini_fallback_model]

        for model in models_to_try:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    tools_to_use = [{"url_context": {}}] if article_url and not article_content else []
                    raw_gemini_response = self.genai_client.models.generate_content(
                        model=model,
                        contents=user_message,
                        config=GenerateContentConfig(
                            system_instruction=system_instruction,
                            thinking_config=types.ThinkingConfig(
                                include_thoughts=False
                            ),
                            temperature=0,
                            tools=tools_to_use
                        )
                    )

                    response_text = raw_gemini_response.text.strip() if raw_gemini_response and raw_gemini_response.text else ""
                    try:
                        parsed_response = self.safe_parse_llm_json(response_text)
                        if not parsed_response:
                            error_message = "Failed to parse JSON from model response"
                            reprocessing_status = "rejected"

                            return {"title": "", "summary": "", "compliance_score": 0, "error_message": error_message,
                                    "reprocessing_status": reprocessing_status,
                                    "raw_gemini_response": raw_gemini_response,
                                    "input_prompt": user_message}
                        else:
                            parsed_response['input_prompt'] = user_message
                            parsed_response['raw_gemini_response'] = raw_gemini_response

                            return parsed_response

                    except Exception as e:
                        error_message = f"Failed to parse JSON from model response:: {e}"
                        reprocessing_status = "rejected"
                        return {"title": "", "summary": "", "compliance_score": 0, "error_message": error_message,
                                "reprocessing_status": reprocessing_status, "raw_gemini_response": raw_gemini_response,
                                "input_prompt": user_message}

                except Exception as e:
                    msg = str(e).lower()
                    error_message += f"Gemini {model} attempt {attempt} failure_msg: {msg}. "

                    if "503" in msg or "overloaded" in msg:
                        wait = self.BACKOFF_BASE ** attempt
                        logging.warning(
                            f"Gemini overloaded (attempt {attempt}/{self.MAX_RETRIES}), retrying in {wait}s"
                        )
                        time.sleep(wait)

                    if attempt == self.MAX_RETRIES:
                        logger.warning(f"Gemini model {model} failed after {self.MAX_RETRIES} retries. "
                                       f"{'Falling back to Flash Lite.' if model == self.gemini_primary_model else 'All models exhausted.'}")
                        break  # Break inner retry loop; try next model

        # All models and retries exhausted
        error_message = f"Gemini failed after all retries with both models: {error_message}"
        return {"title": "", "summary": "", "compliance_score": 0, "error_message": error_message,
                "reprocessing_status": "rejected", "raw_gemini_response": raw_gemini_response,
                "input_prompt": user_message}

    def build_claude_xml_prompt(self, language_name, generate_fields, article_url="", article_content=""):
        """
        Build XML-structured prompt for Claude languages (Tamil, Bangla, Gujarati).
        Uses per-language config from self.claude_language_config.
        Tickets: 55043 (Tamil), 55949 (Bangla), 55951 (Gujarati)
        """
        lang_lower = language_name.strip().lower() if language_name else ""
        lang_config = self.claude_language_config.get(lang_lower)

        if lang_config:
            system_display_name, grammar_rule, include_factual_check = lang_config
        else:
            # Fallback for any unmapped language
            system_display_name = language_name
            grammar_rule = f"Correct grammar rules specific to {language_name}."
            include_factual_check = True

        # ---- System instruction ----
        system_instruction = (
            f"You are a senior multilingual news editor for a high-traffic digital news outlet, "
            f"with expert fluency in {system_display_name}. "
            f"You produce publishable, accurate, ethical, and grammatically flawless content in each language."
        )

        # ---- Rules section (varies by generate_fields mode) ----
        if generate_fields == "title_only":
            rules = (
                f"1. Generate output strictly in {language_name}.\n"
                f"2. Title: 6\u201318 words, 40\u201390 characters. Must spark curiosity without being misleading. "
                f"Must be accurate and context-rich. Do not start with a city name.\n"
                f"3. If you cannot fit within limits, rewrite and compress while keeping meaning. "
                f"Never truncate a sentence \u2014 simplify the idea instead.\n"
                f"4. Character limits are hard boundaries. Word limits are secondary if they conflict with character limits."
            )
            self_check_limits = (
                f"- Title is within 40\u201390 characters AND 6\u201318 words"
            )
            json_template = '{ "title": "", "compliance_score": 0, "error_message": "" }'
            error_fallback = "return empty title, compliance_score = 0, and set error_message with the reason."

        elif generate_fields == "summary_only":
            rules = (
                f"1. Generate output strictly in {language_name}.\n"
                f"2. Summary: 45\u201360 words, 225\u2013310 characters. Focus on factual information, key developments, and outcomes.\n"
                f"3. If you cannot fit within limits, rewrite and compress while keeping meaning. "
                f"Never truncate a sentence \u2014 simplify the idea instead.\n"
                f"4. Character limits are hard boundaries. Word limits are secondary if they conflict with character limits."
            )
            self_check_limits = (
                f"- Summary is within 225\u2013310 characters AND 45\u201360 words"
            )
            json_template = '{ "summary": "", "compliance_score": 0, "error_message": "" }'
            error_fallback = "return empty summary, compliance_score = 0, and set error_message with the reason."

        else:  # both
            rules = (
                f"1. Generate output strictly in {language_name}.\n"
                f"2. Title: 6\u201318 words, 40\u201390 characters. Must spark curiosity without being misleading. "
                f"Must be accurate and context-rich. Do not start with a city name.\n"
                f"3. Summary: 45\u201360 words, 225\u2013310 characters. Focus on factual information, key developments, and outcomes.\n"
                f"4. If you cannot fit within limits, rewrite and compress while keeping meaning. "
                f"Never truncate a sentence \u2014 simplify the idea instead.\n"
                f"5. Character limits are hard boundaries. Word limits are secondary if they conflict with character limits."
            )
            self_check_limits = (
                f"- Title is within 40\u201390 characters AND 6\u201318 words\n"
                f"- Summary is within 225\u2013310 characters AND 45\u201360 words"
            )
            json_template = '{ "title": "", "summary": "", "compliance_score": 0, "error_message": "" }'
            error_fallback = "return empty title and summary, compliance_score = 0, and set error_message with the reason."

        # ---- Self-check section ----
        factual_check_line = "\n- Factual accuracy is maintained in accordance with the original article" if include_factual_check else ""
        self_check = (
            f"- Every sentence is grammatically correct for {language_name}\n"
            f"{self_check_limits}\n"
            f"- No truncated thoughts or incomplete sentences\n"
            f"- A native speaker would find this natural"
            f"{factual_check_line}"
        )

        # ---- Article input ----
        article_input = ""
        if article_url:
            article_input += f"Article URL:\n{article_url}"
        if article_content:
            if article_input:
                article_input += "\n\n"
            article_input += f"Article Content:\n{article_content.strip()}"

        # ---- Assemble full user message ----
        user_message = (
            f"<task>\n"
            f"Summarize the article in <input> following <rules>, <language_quality>, and <output_spec> strictly.\n"
            f"Do NOT include: reasoning, planning, drafts, explanations, notes, meta comments, chain-of-thought, or analysis.\n"
            f"</task>\n\n"
            f"<rules>\n{rules}\n</rules>\n\n"
            f"<language_quality>\n"
            f"1. Follow grammar rules specific to {language_name}: {grammar_rule}\n"
            f"2. Use natural phrasing a native speaker would find fluent. Avoid machine-translated or stilted constructions.\n"
            f"3. Do not mix in English words when a native term exists and is widely understood.\n"
            f"4. Use correct punctuation for the target language, including purna viram (\u0964).\n"
            f"5. Every sentence must be grammatically complete and logically connected.\n"
            f"6. Do NOT copy-paste sentences directly from the article. Always paraphrase and summarize in your own words.\n"
            f"</language_quality>\n\n"
            f"<self_check>\n"
            f"Before producing output, verify:\n"
            f"{self_check}\n"
            f"If any check fails, revise before responding.\n"
            f"</self_check>\n\n"
            f"<input>\n{article_input}\n</input>\n\n"
            f"<output_spec>\n"
            f"Return ONLY valid parsable JSON. No markdown, backticks, code fences, or text before/after the JSON.\n"
            f"{json_template}\n"
            f"- compliance_score: integer 0\u2013100 reflecting adherence to ALL instructions\n"
            f"- error_message: empty string \"\" if successful; {error_fallback}\n"
            f"</output_spec>"
        )

        return system_instruction, user_message

    def claude_call(self, article_url="", article_content="", language_name="", generate_fields="both"):
        """Call Claude models via Vertex AI. Uses Haiku as primary, Sonnet as fallback.
        Uses XML-structured prompt per tickets 55043 (Tamil), 55949 (Bangla), 55951 (Gujarati)."""

        # Build XML-structured prompt (language-specific grammar rules + self-check injected)
        system_instruction, user_message = self.build_claude_xml_prompt(
            language_name=language_name,
            generate_fields=generate_fields,
            article_url=article_url,
            article_content=article_content
        )

        logger.info(f"User Message to Claude: {user_message}")

        error_message = ""
        raw_claude_response = None
        # Tamil uses Sonnet as primary (editorial preference), others use Haiku
        lang_lower = language_name.strip().lower() if language_name else ""
        if lang_lower == "tamil":
            models_to_try = [self.claude_fallback_model, self.claude_primary_model]
        else:
            models_to_try = [self.claude_primary_model, self.claude_fallback_model]

        for model in models_to_try:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    raw_claude_response = self.claude_client.messages.create(
                        model=model,
                        max_tokens=1024,
                        system=system_instruction,
                        messages=[{"role": "user", "content": user_message}],
                        temperature=0,
                    )

                    response_text = raw_claude_response.content[0].text.strip() if raw_claude_response.content else ""
                    parsed_response = self.safe_parse_llm_json(response_text)

                    if not parsed_response:
                        error_message = f"Failed to parse JSON from Claude ({model}) response"
                        return {"title": "", "summary": "", "compliance_score": 0,
                                "error_message": error_message, "reprocessing_status": "rejected",
                                "raw_gemini_response": str(raw_claude_response), "input_prompt": user_message}

                    parsed_response['input_prompt'] = user_message
                    parsed_response['raw_gemini_response'] = str(raw_claude_response)
                    return parsed_response

                except Exception as e:
                    msg = str(e).lower()
                    error_message += f"Claude {model} attempt {attempt} failure_msg: {msg}. "

                    if "529" in msg or "overloaded" in msg:
                        wait = self.BACKOFF_BASE ** attempt
                        logger.warning(f"Claude overloaded (attempt {attempt}/{self.MAX_RETRIES}), retrying in {wait}s")
                        time.sleep(wait)

                    if attempt == self.MAX_RETRIES:
                        logger.warning(f"Claude model {model} failed after {self.MAX_RETRIES} retries. "
                                       f"{'Falling back to Sonnet.' if model == self.claude_primary_model else 'All models exhausted.'}")
                        break  # Break inner retry loop; try next model

        # All models and retries exhausted
        error_message = f"Claude failed after all retries with both models: {error_message}"
        return {"title": "", "summary": "", "compliance_score": 0, "error_message": error_message,
                "reprocessing_status": "rejected", "raw_gemini_response": str(raw_claude_response),
                "input_prompt": user_message}

    def generate_summary_content(self, record):
        error_message = ""
        reprocessing_status = ""
        generated_title = ""
        generated_summary = ""
        input_prompt = ""
        compliance_score = 0

        source_id = record.get('sourceId')
        article_url = record.get('url', '')
        language_name = record.get('sourceLanguageName', '')
        article_content = ""  # Will be set for Claude languages (proxy pre-fetch) or in proxy fallback

        # --- Redis Dedup Check ---
        if self.redis_dedup.is_duplicate(source_id):
            logger.info(f"[{source_id}] SKIPPED - duplicate record (already processed, found in Redis)")
            record['reprocessingStatus'] = 'skipped_duplicate'
            record['error_message'] = 'Record already processed (Redis dedup)'
            return record

        # Determine which fields need regeneration from incoming hygieneErrors
        generate_fields = self.determine_generate_fields(record)
        logger.info(
            f"[{source_id}] Generation mode: {generate_fields}, hygieneErrors: {record.get('hygieneErrors', [])}")

        # Route to appropriate model based on language
        lang_lower = language_name.strip().lower() if language_name else ""
        if lang_lower in self.claude_languages:
            logger.info(f"[{source_id}] Using Claude for language: {language_name}")
            model_provider = "claude"
            # Claude (via Vertex AI) cannot browse URLs — always pre-fetch article content via proxy
            article_content = self.get_article_content_via_proxy(article_url) if article_url else ""
            if not article_content:
                logger.warning(f"[{source_id}] Proxy returned empty content for Claude call.")
            generated_response = self.claude_call(article_url=article_url, article_content=article_content,
                                                  language_name=language_name, generate_fields=generate_fields)
        else:
            logger.info(f"[{source_id}] Using Gemini for language: {language_name}")
            model_provider = "gemini"
            generated_response = self.gemini_call(article_url=article_url, language_name=language_name,
                                                  generate_fields=generate_fields)

        generated_title = generated_response.get('title', '') or ""
        generated_summary = generated_response.get('summary', '') or ""
        compliance_score = generated_response.get('compliance_score', 0)
        error_message = generated_response.get('error_message', '') or ""
        reprocessing_status = generated_response.get('reprocessing_status', '') or ""
        raw_gemini_response = generated_response.get('raw_gemini_response', "") or ""
        generation_source = "article_content" if (model_provider == "claude" and article_content) else "article_url"
        input_prompt = generated_response.get("input_prompt", "") or ""

        combined_text = f"{error_message} {generated_title} {generated_summary}"
        if self.is_access_failure_text(combined_text):
            # try fetching the article through the proxy headless browser service
            article_content = self.get_article_content_via_proxy(article_url)
            if article_content:
                if lang_lower in self.claude_languages:
                    generated_response = self.claude_call(article_content=article_content, language_name=language_name,
                                                          generate_fields=generate_fields)
                else:
                    generated_response = self.gemini_call(article_content=article_content, language_name=language_name,
                                                          generate_fields=generate_fields)

                generated_title = generated_response.get('title', '') or ""
                generated_summary = generated_response.get('summary', '') or ""
                compliance_score = generated_response.get('compliance_score', 0)
                error_message = generated_response.get('error_message', '') or ""
                reprocessing_status = generated_response.get('reprocessing_status', '') or ""
                raw_gemini_response = generated_response.get('raw_gemini_response', "") or ""
                generation_source = "article_content"
                input_prompt = generated_response.get("input_prompt", "") or ""

            else:
                error_message = "Failed to retrieve article content via proxy."
                generated_title = ""
                generated_summary = ""
                compliance_score = 0
                reprocessing_status = "rejected"

        # ---- Preserve original publisher data ----
        # Remove special characters from title to avoid hygiene issues
        original_title = re.sub(r'[^\w\s]', '', record.get("title", ""), flags=re.UNICODE).strip()
        original_summary = record.get("summary", "")
        original_publisher_name = record.get("sourcePublisherName", "")
        record["originalPublisherTitle"] = original_title
        record["originalPublisherSummary"] = original_summary
        record["originalPublisherName"] = original_publisher_name

        # ---- Apply generated content selectively based on generate_fields mode ----
        if generate_fields in ("title_only", "both"):
            record["title"] = generated_title
        else:
            # Keep existing title (it passed hygiene); update local var for success check
            generated_title = record.get("title", "")

        if generate_fields in ("summary_only", "both"):
            record["summary"] = generated_summary
        else:
            # Keep existing summary (it passed hygiene); update local var for success check
            generated_summary = record.get("summary", "")

        record["compliance_score"] = compliance_score
        record["sourcePublisherName"] = "InsideMedia"
        record["source"] = "hygiene_reprocess"
        record["generateFields"] = generate_fields
        record["modelProvider"] = model_provider

        record["error_message"] = error_message
        record["reprocessingStatus"] = reprocessing_status
        record["generationSource"] = generation_source
        record["rawGeminiResponse"] = str(raw_gemini_response)
        record["input_prompt"] = str(input_prompt)

        record["summaryLen"] = len(record["summary"])
        record["titleLen"] = len(record["title"])

        record["originalSummaryLen"] = len(original_summary)
        record["originalTitleLen"] = len(original_title)

        # Re-check hygiene of generated content
        hygiene_check = self.check_publisher_summary_hygiene(record)

        record["hygieneCheck"] = hygiene_check
        if not hygiene_check.get("isHygienic", False):
            error_message = f"Hygiene failed after generation. prev hyg msg--{error_message}."
            record["reprocessingStatus"] = "rejected"
            hygiene_errors = hygiene_check.get("errors", [])
            hygiene_error_msgs = [f"{err['key']}: {err['value']}" for err in hygiene_errors]
            record["error_message"] += " | Hygiene Errors: " + "; ".join(hygiene_error_msgs)

        if generated_summary and generated_title and not error_message:
            record['reprocessingStatus'] = "success"
            # Mark as processed in Redis for dedup
            self.redis_dedup.mark_processed(source_id)
            if instance == 'prod':
                processed_rec = {"filename": source_id, "url": record.get("sourceThumbnailURL", ""),
                                 "category": record.get("sourceCategoryName", ""),
                                 "publisher": record.get("sourcePublisherName", ""), "content_type": "summaries",
                                 "data": record}
            else:
                processed_rec = record
            self.success_recs.append(processed_rec)

        return record

    def process_data(self, data_list, max_workers=1):
        """Process multiple videos concurrently using ThreadPoolExecutor."""
        # with ThreadPoolExecutor(max_workers=max_workers) as executor:
        #     future_to_rec = {executor.submit(self.process_video, rec): rec for rec in data_list}
        #
        #     for future in as_completed(future_to_rec):
        #         rec = future_to_rec[future]
        #         try:
        #             future.result()
        #         except Exception as e:
        #             logger.info(f"Exception Caught process_videos: {e}")
        processed_data = []

        for rec in data_list:
            try:
                processed_rec = self.generate_summary_content(rec)
                processed_data.append(processed_rec)
            except Exception as e:
                logger.info(f"Exception Caught process_summary: {e}")
                rec['reprocessingStatus'] = 'failed'
                rec['errorMessage'] = f'Error in processing summary. Exception:: {e}'
                processed_data.append(rec)

        return processed_data


class Execute:

    def __init__(self):
        logger.info("execution started")
        self.ps = PubSub()
        self.processor = Processor()

    def append_fields(self, data_list, additional_fields):
        for rec in data_list:
            for field, value in additional_fields.items():
                rec[field] = value

        return data_list

    def process(self, message):
        # Parse message
        data = json.loads(message.data.decode("utf-8"))
        if len(data) == 0:
            logger.info("Blank message received.")
            return ""

        self.processor.success_recs = []

        logger.info(f"Processing {len(data)} records")
        # Process merge
        processed_data = self.processor.process_data(data)

        logger.info(
            f"Processing completed for {len(data)}/{len(processed_data)} records. Success records: {len(self.processor.success_recs)}")
        print(
            f"Processing completed for {len(data)}/{len(processed_data)} records. Success records: {len(self.processor.success_recs)}")

        logger.info(f"Updating processing status to db")
        # Update all the processed records (success and failures) to the hygiene collection
        self.processor.mongo_handler.upsert_records_bulk(processed_data)

        # Publish to pubsub (DE and Backend Summaries collections)
        self.ps.publish_message_to_topic(pubsub_publish_topic_name, self.processor.success_recs)

    def callback(self, message):
        try:
            logger.info(f"Received message: {message.data}")

            self.process(message)

            # Acknowledge the message
            message.ack()
            logger.info("Message processed successfully.")
        except Exception as e:
            logger.info(f"Error processing message: {e}", exc_info=True)
            message.ack()

    def run(self):
        logger.info(f"Listening for messages on {self.ps.subscription_path}")
        future = self.ps.subscriber_client.subscribe(self.ps.subscription_path, callback=self.callback)
        try:
            future.result()
        except Exception as e:
            logger.info(f"Subscriber encountered an error: {e}")


def run_main():
    execution_start_time = time.time()
    logger.info(f"Execution started at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    exe = Execute()
    exe.run()
    logger.info(f"execution obj run")
    execution_end_time = time.time()
    logger.info(f"timer end")
    execution_processing_time = (execution_end_time - execution_start_time) / 60
    logger.info(f"execution_processing_time: {execution_processing_time}")
    logger.info(f"Execution processing time: {execution_processing_time} minutes")
    logger.info(f"Execution Ended at: {datetime.now(tz=ZoneInfo('Asia/Kolkata'))}")
    return {'result': 'success'}


run_main()