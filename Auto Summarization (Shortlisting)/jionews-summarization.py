import json
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google import genai
from google.cloud import secretmanager
from google.genai import types
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, constr,HttpUrl
from pymongo import MongoClient, errors, ReturnDocument
from urllib.parse import quote
import httpx


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load env variables
load_dotenv()

# Retrieve the JSON string from the environment variable
service_account_json_str = os.getenv('SERVICE_ACCOUNT')

# Convert the JSON string to a dictionary
service_account_creds = json.loads(service_account_json_str)


# ---------------- MongoDB Handler ---------------- #
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
        """Upserts a record based on sourceId. Tracks createdAt, updatedAt, and updateCount."""
        try:
            now = int(time.time())

            update_doc = {
                "$set": {
                    "articleContent": record.get("articleContent", ""),
                    "articleUrl": record.get("articleUrl", ""),
                    "summary": record.get("summary", ""),
                    "processingSource":record.get('processingSource',),
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

            result = self.collection.find_one_and_update(
                {"sourceId": source_id},
                update_doc,
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            return result
        except errors.PyMongoError as e:
            logging.error(f"Database operation failed: {e}")
            raise HTTPException(status_code=500, detail="Database operation failed.")


# ---------------- GCP ---------------- #
class GCPHandler:
    def __init__(self):
        try:
            self.secret_client = secretmanager.SecretManagerServiceClient().from_service_account_info(
                service_account_creds)
        except:
            self.secret_client = secretmanager.SecretManagerServiceClient()

    def get_secret(self, secret_name: str) -> str:
        response = self.secret_client.access_secret_version(request={"name": secret_name})
        payload = response.payload.data.decode("UTF-8")
        return payload


# ---------------- Summarizer ---------------- #
class Summarizer:
    def __init__(self):
        self.gcp_handler = GCPHandler()

        gemini_secret_name = "projects/266686822828/secrets/GEMINI_API_KEY/versions/latest"
        de_mongo_uri_key = "projects/266686822828/secrets/mongosh_de_uri/versions/latest"

        self.gemini_api_key = self.gcp_handler.get_secret(gemini_secret_name)
        self.mongo_uri = self.gcp_handler.get_secret(de_mongo_uri_key)
        self.mongo_handler = MongoDBHandler(self.mongo_uri, "ingestion-data", "auto_summarization")

        self.genai_client = genai.Client(api_key=self.gemini_api_key)
        self.default_model = "gemini-2.5-flash"
        self.tools = [
            {"url_context": {}},
            # {"google_search": {}}
        ]
        # self.default_prompt = "You are a news editor. Summarize the following paragraph in 360 characters or less, focusing on factual information, direct quotes, when and where details, and making the outcome complete and meaningful. Avoid any introductory text, additional explanations, or formatting elements like 'Summary:'. Provide only the summary, without speculation or assumptions"
        # self.old_default_prompt = "Act as a news editor/writer and summarize the following news article. The summary should be between 350 and 360 characters, focusing on factual information, direct quotes, 5Ws and 1 H and making the outcome complete and meaningful. Avoid any introductory text, additional explanations, or formatting elements like 'Summary:'. Provide only the summary, without speculation or assumptions"
        # self.default_prompt = "The summary should be between 350 and 360 characters, focusing on factual information, direct quotes, 5Ws and 1 H and making the outcome complete and meaningful. Avoid any introductory text, additional explanations, or formatting elements like 'Summary:'. Provide only the summary, without speculation or assumptions"
        # self.default_prompt = "The summary should be between 350 and 360 characters, focusing on factual information, direct quotes, 5Ws and 1 H and making the outcome complete and meaningful. Do NOT show your reasoning, steps, drafting process, planning, or analysis.Do NOT rewrite the instructions.Output ONLY the final summary. No explanations, no chain-of-thought."

        self.system_instruction = (
            "You act as a news editor/writer and summarize news articles accurately and concisely."
            "Your output must be ONLY a single summary between 350 and 360 characters. "
            "Do NOT include: reasoning, planning, steps, drafts, explanations, "
            "notes, meta comments, chain-of-thought, or analysis. "
            "Output ONLY the final summary text, nothing else."
        )

    def generate_summary(self, article_content: str | None, article_url: str | None, model=None) -> dict:

        if not article_url and not article_content:
            return {'summary': "", 'error_message': "Either article URL or article content must be provided."}

        # prompt = prompt or self.default_prompt

        model = model or self.default_model
        # if article_content:
        #     full_input = f"Act as a news editor/writer and summarize the following news article.{prompt}\n\nArticle Content:\n{article_content.strip()}"
        # else:
        #     full_input = f"Act as a news editor/writer and summarize the following news article available at Article URL:\n{article_url}.{prompt}"
        #
        user_message = "Summarize this news article in 350–360 characters, focusing on factual information, direct quotes, 5Ws and 1 H and making the outcome complete and meaningful\n\n"

        if article_url:
            user_message += f"URL: {article_url}\n\n"
        if article_content:
            user_message += f"CONTENT:\n{article_content.strip()}"
            # full_input = f"{prompt}\n\nArticle URL: {article_url}"

        try:

            response = self.genai_client.models.generate_content(
                model=model,
                contents=[
                    self.system_instruction,
                    user_message
                ],
                config=GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=False
                    ),
                    temperature=0,
                    tools=self.tools
                )
            )

            summary = response.text.strip() if response and response.text else ""
            return {'summary': summary, 'error_message': ""}

        except Exception as e:
            summary = ""
            logging.error(f"Error during Gemini API call: {e}")
            return {'summary': summary, 'error_message': f"Error generating summary. Error: {e}"}


class SummarizeRequest(BaseModel):
    article_content: constr(strip_whitespace=True, min_length=1) | None = None
    article_url: str | None = None
    source_headline_id: constr(strip_whitespace=True, min_length=1)
    prompt: str | None = None
    model: str | None = None


# ---------------- FastAPI ---------------- #
BASE_ROUTE = "/v1/jionews-summarization"
app = FastAPI(root_path=BASE_ROUTE)

summarizer = Summarizer()

PROXY_SERVICE_BASE_URL = "https://jn-article-render-proxy-266686822828.asia-south1.run.app/proxy"

URL_FAILURE_SUBSTRINGS = ["unable to summarize","unable to access","unable to browse","could not be fetched","could not be accessed","URL did not contain","I am unable to"]


@app.get("/")
async def health():
    return {"message": "Summarization API is healthy!"}


@app.post("/summarize")
async def summarize(input_data: SummarizeRequest):
    start = time.time()
    try:
        article_content = input_data.article_content or ""
        article_url = input_data.article_url or ""
        source_id = input_data.source_headline_id
        # prompt = input_data.prompt or summarizer.default_prompt
        model = input_data.model or summarizer.default_model

        if article_url:
            processing_source = "publisher_url"
        else:
            processing_source = "publisher_content"

        t1 = time.time()
        summary_result = summarizer.generate_summary(article_content, article_url, model)
        t2 = time.time()

        summary_lower = summary_result.get('summary','').lower()
        if any(substr in summary_lower for substr in URL_FAILURE_SUBSTRINGS):
            logging.info("Gemini failed to fetch URL")

            async with httpx.AsyncClient(timeout=45) as client:
                proxy_url = f"{PROXY_SERVICE_BASE_URL}?url={quote(article_url)}"
                proxy_response = await client.get(proxy_url)
                proxy_response.raise_for_status()
                html_content = proxy_response.text

            t3 = time.time()
            summary_result = summarizer.generate_summary(
                article_content=html_content,
                article_url=None,
                model=model
            )
            t4 = time.time()

            processing_source = "proxy_url"


        # Upsert record into Mongo
        record = {
            "articleContent": article_content,
            "articleUrl": article_url,
            "summary": summary_result['summary'],
            "model": model,
            "error_message": summary_result['error_message'],
            "processingSource": processing_source
        }

        db_record = summarizer.mongo_handler.upsert_record(source_id, record)
        t5 = time.time()

        logging.info(f"Timing -> Gemini call: {t2 - t1:.2f}s | Mongo upsert: {t5 - t2:.2f}s | Total: {t5 - start:.2f}s")

        return {
            "sourceId": db_record["sourceId"],
            "summary": db_record["summary"],
            "updateCount": db_record["updateCount"],
            "createdAt": db_record["createdAt"],
            "updatedAt": db_record["updatedAt"],
        }

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error. Error message: {e}")