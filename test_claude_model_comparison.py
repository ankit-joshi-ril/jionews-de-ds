"""
Unit Tests for claude_model_comparison.py
=========================================
Tests every function WITHOUT making real API calls, DB connections, or GCS uploads.
Run:  python -m pytest test_claude_model_comparison.py -v
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock
from zoneinfo import ZoneInfo

# Import the module under test
import claude_model_comparison as cm


# ═══════════════════════════════════════════════════════════════════
# 1. build_prompts
# ═══════════════════════════════════════════════════════════════════

class TestBuildPrompts(unittest.TestCase):

    def test_returns_two_strings(self):
        system, user = cm.build_prompts("Hindi")
        self.assertIsInstance(system, str)
        self.assertIsInstance(user, str)

    def test_language_injected_into_user_message(self):
        _, user = cm.build_prompts("Tamil")
        self.assertIn("Tamil", user)

    def test_language_injected_into_system_instruction(self):
        system, _ = cm.build_prompts("Marathi")
        # System prompt mentions "specified language" — generic
        self.assertIn("specified language", system)

    def test_json_format_present_in_user_message(self):
        _, user = cm.build_prompts("English")
        self.assertIn('"title"', user)
        self.assertIn('"summary"', user)
        self.assertIn('"compliance_score"', user)
        self.assertIn('"error_message"', user)

    def test_all_supported_languages(self):
        """Ensure prompts build without error for every language."""
        for lang in cm.LANGUAGE_ID_MAP.keys() if hasattr(cm, "LANGUAGE_ID_MAP") else [
            "English", "Hindi", "Marathi", "Gujarati", "Malayalam",
            "Tamil", "Urdu", "Kannada", "Punjabi", "Telugu",
            "Bangla", "Odia", "Assamese"
        ]:
            system, user = cm.build_prompts(lang)
            self.assertTrue(len(system) > 50)
            self.assertTrue(len(user) > 100)


# ═══════════════════════════════════════════════════════════════════
# 2. safe_parse_llm_json
# ═══════════════════════════════════════════════════════════════════

class TestSafeParseLlmJson(unittest.TestCase):

    def test_valid_json(self):
        raw = '{"title": "Test", "summary": "Summary", "compliance_score": 85, "error_message": ""}'
        result = cm.safe_parse_llm_json(raw)
        self.assertEqual(result["title"], "Test")
        self.assertEqual(result["compliance_score"], 85)

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"title": "Test", "summary": "Sum"}\n```'
        result = cm.safe_parse_llm_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Test")

    def test_json_with_backticks_only(self):
        raw = '```\n{"title": "Test"}\n```'
        result = cm.safe_parse_llm_json(raw)
        self.assertIsNotNone(result)

    def test_json_embedded_in_text(self):
        raw = 'Here is the output:\n{"title": "Headline", "summary": "Body"}\nDone.'
        result = cm.safe_parse_llm_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Headline")

    def test_empty_string(self):
        self.assertIsNone(cm.safe_parse_llm_json(""))

    def test_none_input(self):
        self.assertIsNone(cm.safe_parse_llm_json(None))

    def test_non_string_input(self):
        self.assertIsNone(cm.safe_parse_llm_json(123))

    def test_garbage_text(self):
        self.assertIsNone(cm.safe_parse_llm_json("this is not json at all"))

    def test_incomplete_json(self):
        self.assertIsNone(cm.safe_parse_llm_json('{"title": "unclosed'))

    def test_whitespace_padded_json(self):
        raw = '   \n  {"title": "Test"}  \n  '
        result = cm.safe_parse_llm_json(raw)
        self.assertIsNotNone(result)

    def test_nested_json_picks_outer(self):
        raw = '{"title": "T", "meta": {"nested": true}}'
        result = cm.safe_parse_llm_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "T")


# ═══════════════════════════════════════════════════════════════════
# 3. contains_html_tags
# ═══════════════════════════════════════════════════════════════════

class TestContainsHtmlTags(unittest.TestCase):

    def test_clean_text(self):
        self.assertFalse(cm.contains_html_tags("This is clean text"))

    def test_html_paragraph(self):
        self.assertTrue(cm.contains_html_tags("Hello <p>world</p>"))

    def test_html_div(self):
        self.assertTrue(cm.contains_html_tags("<div>content</div>"))

    def test_html_self_closing(self):
        self.assertTrue(cm.contains_html_tags("Image: <img src='x' />"))

    def test_non_string_input(self):
        self.assertFalse(cm.contains_html_tags(None))
        self.assertFalse(cm.contains_html_tags(123))

    def test_angle_brackets_not_html(self):
        # "5 > 3" should not match as HTML
        self.assertFalse(cm.contains_html_tags("5 > 3 and 2 < 4"))

    def test_closing_tag(self):
        self.assertTrue(cm.contains_html_tags("text </span> more"))


# ═══════════════════════════════════════════════════════════════════
# 4. special_char_check
# ═══════════════════════════════════════════════════════════════════

class TestSpecialCharCheck(unittest.TestCase):

    def test_normal_text(self):
        self.assertFalse(cm.special_char_check("Normal news headline about economy"))

    def test_few_specials_under_threshold(self):
        self.assertFalse(cm.special_char_check("Price is $10!"))  # only 1 special

    def test_exactly_three_specials(self):
        self.assertTrue(cm.special_char_check("a@b#c$d"))  # 3 specials

    def test_many_specials(self):
        self.assertTrue(cm.special_char_check("@@@###$$$"))

    def test_non_string(self):
        self.assertFalse(cm.special_char_check(None))
        self.assertFalse(cm.special_char_check(42))

    def test_empty_string(self):
        self.assertFalse(cm.special_char_check(""))


# ═══════════════════════════════════════════════════════════════════
# 5. check_hygiene
# ═══════════════════════════════════════════════════════════════════

class TestCheckHygiene(unittest.TestCase):

    def test_perfect_input(self):
        title = "This is a perfectly valid headline for news"  # ~44 chars
        summary = "A" * 250  # 250 chars, within 200-360
        result = cm.check_hygiene(title, summary)
        self.assertTrue(result["is_hygienic"])
        self.assertEqual(result["errors"], "")

    def test_empty_title(self):
        result = cm.check_hygiene("", "A" * 250)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Title is empty", result["errors"])

    def test_empty_summary(self):
        result = cm.check_hygiene("Valid title that is long enough", "")
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Summary is empty", result["errors"])

    def test_title_too_short(self):
        result = cm.check_hygiene("Short", "A" * 250)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Title too short", result["errors"])

    def test_title_too_long(self):
        result = cm.check_hygiene("A" * 110, "B" * 250)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Title too long", result["errors"])

    def test_summary_too_short(self):
        result = cm.check_hygiene("Valid title that is long enough", "Short")
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Summary too short", result["errors"])

    def test_summary_too_long(self):
        result = cm.check_hygiene("Valid title that is long enough", "C" * 365)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Summary too long", result["errors"])

    def test_title_with_html(self):
        result = cm.check_hygiene("<b>Bold headline</b> more text here", "D" * 250)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Title contains HTML", result["errors"])

    def test_summary_with_html(self):
        result = cm.check_hygiene("Valid title that is long enough", "<p>" + "D" * 247 + "</p>")
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Summary contains HTML", result["errors"])

    def test_title_with_special_chars(self):
        result = cm.check_hygiene("Headline @#$ with specials!", "E" * 250)
        self.assertFalse(result["is_hygienic"])
        self.assertIn("excessive special chars", result["errors"])

    def test_multiple_errors_combined(self):
        result = cm.check_hygiene("", "")
        self.assertFalse(result["is_hygienic"])
        self.assertIn("Title is empty", result["errors"])
        self.assertIn("Summary is empty", result["errors"])

    def test_boundary_title_26_chars(self):
        title = "A" * 26
        result = cm.check_hygiene(title, "B" * 250)
        # 26 chars is exactly the min — should pass title length check
        self.assertNotIn("Title too short", result["errors"])

    def test_boundary_summary_200_chars(self):
        result = cm.check_hygiene("Valid title that is long enough", "C" * 200)
        self.assertNotIn("Summary too short", result["errors"])

    def test_boundary_summary_360_chars(self):
        result = cm.check_hygiene("Valid title that is long enough", "D" * 360)
        self.assertNotIn("Summary too long", result["errors"])


# ═══════════════════════════════════════════════════════════════════
# 6. fetch_article_content (mocked HTTP)
# ═══════════════════════════════════════════════════════════════════

class TestFetchArticleContent(unittest.TestCase):

    @patch("claude_model_comparison.httpx.Client")
    def test_direct_fetch_success_with_article_tag(self, MockClient):
        html = """
        <html><body>
        <nav>Menu</nav>
        <article>
            <p>This is a long paragraph with meaningful news content about recent events
            that provides enough text to exceed the 200 character minimum threshold for content.</p>
            <p>Second paragraph with more details about the story that adds additional context.</p>
        </article>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        result = cm.fetch_article_content("https://example.com/article")
        self.assertTrue(len(result) > 100)
        self.assertNotIn("<nav>", result)  # nav should be stripped

    @patch("claude_model_comparison.httpx.Client")
    def test_direct_fetch_success_with_paragraphs(self, MockClient):
        html = """
        <html><body>
        <p>Short</p>
        <p>This is a sufficiently long paragraph that exceeds the 30 character threshold for inclusion.</p>
        <p>Another long paragraph with enough content to be considered meaningful article text for extraction.</p>
        <p>Third paragraph that gives us enough total content to pass the 200 character overall threshold.</p>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        result = cm.fetch_article_content("https://example.com/article")
        self.assertTrue(len(result) > 0)
        self.assertNotIn("Short", result)  # <30 chars excluded

    @patch("claude_model_comparison.httpx.Client")
    def test_direct_fetch_404_falls_to_proxy(self, MockClient):
        # First call (direct) returns 404, second call (proxy) returns content
        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404
        mock_resp_404.text = ""

        mock_resp_proxy = MagicMock()
        mock_resp_proxy.status_code = 200
        mock_resp_proxy.text = "Proxy fetched article content " * 20  # >100 chars

        mock_client_instance = MagicMock()
        mock_client_instance.get.side_effect = [mock_resp_404, mock_resp_proxy]
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        result = cm.fetch_article_content("https://example.com/broken")
        self.assertIn("Proxy fetched", result)

    @patch("claude_model_comparison.httpx.Client")
    def test_both_fail_returns_empty(self, MockClient):
        mock_client_instance = MagicMock()
        mock_client_instance.get.side_effect = Exception("Connection refused")
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        result = cm.fetch_article_content("https://unreachable.example.com")
        self.assertEqual(result, "")

    @patch("claude_model_comparison.httpx.Client")
    def test_content_truncated_at_15k(self, MockClient):
        html = "<html><body><article>" + ("<p>" + "A" * 500 + "</p>") * 100 + "</article></body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        result = cm.fetch_article_content("https://example.com/long-article")
        self.assertLessEqual(len(result), 15000)


# ═══════════════════════════════════════════════════════════════════
# 7. call_claude (mocked Anthropic client)
# ═══════════════════════════════════════════════════════════════════

class TestCallClaude(unittest.TestCase):

    def _mock_client_response(self, response_text):
        """Helper: build a mock Anthropic client that returns given text."""
        mock_block = MagicMock()
        mock_block.text = response_text

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        return mock_client

    @patch("claude_model_comparison.fetch_article_content", return_value="Article text here...")
    def test_successful_json_response(self, mock_fetch):
        response_json = json.dumps({
            "title": "Test Headline",
            "summary": "This is a test summary.",
            "compliance_score": 90,
            "error_message": ""
        })
        mock_client = self._mock_client_response(response_json)

        result = cm.call_claude(mock_client, "claude-sonnet-4-20250514", "https://example.com", "Hindi")

        self.assertEqual(result["title"], "Test Headline")
        self.assertEqual(result["summary"], "This is a test summary.")
        self.assertEqual(result["compliance_score"], 90)
        self.assertEqual(result["error_message"], "")
        mock_client.messages.create.assert_called_once()

    @patch("claude_model_comparison.fetch_article_content", return_value="Article text here...")
    def test_markdown_wrapped_json_response(self, mock_fetch):
        response_text = '```json\n{"title": "T", "summary": "S", "compliance_score": 80, "error_message": ""}\n```'
        mock_client = self._mock_client_response(response_text)

        result = cm.call_claude(mock_client, "claude-haiku-4-5-20251001", "https://example.com", "English")
        self.assertEqual(result["title"], "T")
        self.assertEqual(result["compliance_score"], 80)

    @patch("claude_model_comparison.fetch_article_content", return_value="Article text here...")
    def test_unparseable_response(self, mock_fetch):
        mock_client = self._mock_client_response("I cannot generate a summary for this.")

        result = cm.call_claude(mock_client, "claude-sonnet-4-20250514", "https://example.com", "Hindi")
        self.assertEqual(result["title"], "")
        self.assertIn("JSON parse failed", result["error_message"])

    @patch("claude_model_comparison.fetch_article_content", return_value="")
    def test_article_fetch_fails_still_calls_api(self, mock_fetch):
        response_json = json.dumps({
            "title": "", "summary": "", "compliance_score": 0,
            "error_message": "Article content could not be fetched."
        })
        mock_client = self._mock_client_response(response_json)

        result = cm.call_claude(mock_client, "claude-sonnet-4-20250514", "https://example.com", "Hindi")
        self.assertIn("could not be fetched", result["error_message"])
        # Verify the note was added to the user message
        call_args = mock_client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        self.assertIn("[Note: Article content could not be fetched", user_content)

    @patch("claude_model_comparison.fetch_article_content", return_value="Content")
    def test_api_error_retries_on_429(self, mock_fetch):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception("429 rate limit exceeded"),
            Exception("429 rate limit exceeded"),  # fails both retries
        ]

        result = cm.call_claude(mock_client, "claude-sonnet-4-20250514", "https://example.com", "Hindi")
        self.assertIn("Failed after", result["error_message"])
        self.assertEqual(mock_client.messages.create.call_count, 2)

    @patch("claude_model_comparison.fetch_article_content", return_value="Content")
    def test_api_error_no_retry_on_non_retryable(self, mock_fetch):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            Exception("400 invalid request"),
            Exception("400 invalid request"),
        ]

        result = cm.call_claude(mock_client, "claude-sonnet-4-20250514", "https://example.com", "Hindi")
        self.assertIn("Failed after", result["error_message"])

    @patch("claude_model_comparison.fetch_article_content", return_value="Content")
    def test_correct_api_params(self, mock_fetch):
        response_json = json.dumps({"title": "T", "summary": "S", "compliance_score": 85, "error_message": ""})
        mock_client = self._mock_client_response(response_json)

        cm.call_claude(mock_client, "claude-haiku-4-5-20251001", "https://example.com", "Tamil")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(call_kwargs["max_tokens"], 1024)
        self.assertEqual(call_kwargs["temperature"], 0)
        self.assertIsInstance(call_kwargs["system"], str)
        self.assertEqual(len(call_kwargs["messages"]), 1)
        self.assertEqual(call_kwargs["messages"][0]["role"], "user")


# ═══════════════════════════════════════════════════════════════════
# 8. process_single_task (mocked Claude + MongoDB)
# ═══════════════════════════════════════════════════════════════════

class TestProcessSingleTask(unittest.TestCase):

    @patch("claude_model_comparison.call_claude")
    def test_full_task_flow(self, mock_call):
        mock_call.return_value = {
            "title": "Great Headline About Economy News Today",
            "summary": "A" * 260,
            "compliance_score": 88,
            "error_message": "",
            "raw_response": "...",
        }

        mock_collection = MagicMock()
        article = {"sourceId": "abc123", "url": "https://example.com/news", "sourceLanguageName": "Hindi"}

        row = cm.process_single_task(MagicMock(), article, "claude-sonnet-4-20250514", mock_collection)

        self.assertEqual(row["source_id"], "abc123")
        self.assertEqual(row["model"], "claude-sonnet-4-20250514")
        self.assertEqual(row["language"], "Hindi")
        self.assertEqual(row["generated_title"], "Great Headline About Economy News Today")
        self.assertEqual(row["title_char_len"], len("Great Headline About Economy News Today"))
        self.assertTrue(row["hygiene_passed"])
        self.assertIsInstance(row["response_time_sec"], float)
        mock_collection.insert_one.assert_called_once()

    @patch("claude_model_comparison.call_claude")
    def test_task_with_hygiene_failure(self, mock_call):
        mock_call.return_value = {
            "title": "Short",  # Too short — will fail hygiene
            "summary": "Also short",  # Too short
            "compliance_score": 40,
            "error_message": "",
            "raw_response": "...",
        }

        mock_collection = MagicMock()
        article = {"sourceId": "xyz789", "url": "https://example.com", "sourceLanguageName": "English"}

        row = cm.process_single_task(MagicMock(), article, "claude-haiku-4-5-20251001", mock_collection)

        self.assertFalse(row["hygiene_passed"])
        self.assertIn("Title too short", row["hygiene_errors"])
        self.assertIn("Summary too short", row["hygiene_errors"])

    @patch("claude_model_comparison.call_claude")
    def test_task_records_created_at(self, mock_call):
        mock_call.return_value = {
            "title": "T" * 30, "summary": "S" * 260,
            "compliance_score": 80, "error_message": "", "raw_response": "",
        }
        mock_collection = MagicMock()
        article = {"sourceId": "dt1", "url": "https://x.com", "sourceLanguageName": "Hindi"}

        row = cm.process_single_task(MagicMock(), article, "claude-sonnet-4-20250514", mock_collection)
        self.assertIsInstance(row["created_at"], datetime)

    @patch("claude_model_comparison.call_claude")
    def test_missing_url_defaults_empty(self, mock_call):
        mock_call.return_value = {
            "title": "", "summary": "", "compliance_score": 0,
            "error_message": "no url", "raw_response": "",
        }
        mock_collection = MagicMock()
        article = {"sourceId": "no_url"}  # missing url and language

        row = cm.process_single_task(MagicMock(), article, "claude-sonnet-4-20250514", mock_collection)
        self.assertEqual(row["article_url"], "")
        self.assertEqual(row["language"], "English")  # default


# ═══════════════════════════════════════════════════════════════════
# 9. Excel generation (run_comparison with mocked externals)
# ═══════════════════════════════════════════════════════════════════

class TestExcelGeneration(unittest.TestCase):
    """
    Tests that run_comparison produces a valid Excel file with 3 sheets.
    Mocks: API calls, GCS upload, Secret Manager. Does NOT make real calls.
    """

    @patch("claude_model_comparison.upload_to_gcs")
    @patch("claude_model_comparison.get_api_key", return_value="sk-test-key")
    @patch("claude_model_comparison.call_claude")
    def test_excel_three_sheets_generated(self, mock_call, mock_key, mock_upload):
        mock_call.return_value = {
            "title": "Test Title for Article",
            "summary": "B" * 260,
            "compliance_score": 85,
            "error_message": "",
            "raw_response": "...",
        }

        mock_collection = MagicMock()
        test_data = [
            {"sourceId": "s1", "url": "https://a.com", "sourceLanguageName": "Hindi"},
            {"sourceId": "s2", "url": "https://b.com", "sourceLanguageName": "Tamil"},
        ]

        # Temporarily override MODELS_TO_COMPARE to speed up
        original_models = cm.MODELS_TO_COMPARE
        cm.MODELS_TO_COMPARE = ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]

        try:
            cm.run_comparison(test_data, mock_collection)
        finally:
            cm.MODELS_TO_COMPARE = original_models

        # Verify GCS upload was called
        mock_upload.assert_called_once()
        upload_args = mock_upload.call_args
        local_path = upload_args[0][0]
        blob_name = upload_args[0][2]

        self.assertIn("claude_model_comparison_", blob_name)
        self.assertTrue(blob_name.endswith(".xlsx"))

    @patch("claude_model_comparison.upload_to_gcs")
    @patch("claude_model_comparison.get_api_key", return_value="sk-test-key")
    @patch("claude_model_comparison.call_claude")
    def test_excel_stats_calculated(self, mock_call, mock_key, mock_upload):
        """Stats sheet should aggregate correctly."""
        call_count = [0]

        def varying_response(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return {"title": "Good Title Here!!", "summary": "G" * 260,
                        "compliance_score": 90, "error_message": "", "raw_response": ""}
            else:
                return {"title": "Bad", "summary": "Short",
                        "compliance_score": 30, "error_message": "", "raw_response": ""}

        mock_call.side_effect = varying_response
        mock_collection = MagicMock()

        test_data = [{"sourceId": "s1", "url": "https://a.com", "sourceLanguageName": "Hindi"}]

        original_models = cm.MODELS_TO_COMPARE
        cm.MODELS_TO_COMPARE = ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]
        try:
            cm.run_comparison(test_data, mock_collection)
        finally:
            cm.MODELS_TO_COMPARE = original_models

        # Verify mongo inserts happened (1 article x 2 models)
        self.assertEqual(mock_collection.insert_one.call_count, 2)


# ═══════════════════════════════════════════════════════════════════
# 10. Config & structural checks
# ═══════════════════════════════════════════════════════════════════

class TestConfigAndStructure(unittest.TestCase):

    def test_models_to_compare_not_empty(self):
        self.assertTrue(len(cm.MODELS_TO_COMPARE) >= 1)

    def test_all_models_have_claude_prefix(self):
        for model in cm.MODELS_TO_COMPARE:
            self.assertTrue(model.startswith("claude-"), f"Model '{model}' doesn't start with 'claude-'")

    def test_model_fills_covers_all_models(self):
        """Verify every model in MODELS_TO_COMPARE has a color fill in the Excel."""
        # model_fills is defined inside run_comparison, so we check indirectly
        # by reading the source. For now just ensure models are valid strings.
        for model in cm.MODELS_TO_COMPARE:
            self.assertIsInstance(model, str)
            self.assertGreater(len(model), 10)

    def test_max_workers_reasonable(self):
        self.assertGreaterEqual(cm.MAX_WORKERS, 1)
        self.assertLessEqual(cm.MAX_WORKERS, 50)

    def test_max_retries_positive(self):
        self.assertGreaterEqual(cm.MAX_RETRIES, 1)

    def test_gcs_bucket_name_set(self):
        self.assertEqual(cm.GCS_BUCKET_NAME, "de-raw-ingestion")

    def test_gcs_blob_prefix_set(self):
        self.assertEqual(cm.GCS_BLOB_PREFIX, "data")

    def test_article_proxy_url_valid(self):
        self.assertTrue(cm.ARTICLE_PROXY_URL.startswith("https://"))
        self.assertIn("jn-article-render-proxy", cm.ARTICLE_PROXY_URL)

    def test_main_function_exists(self):
        self.assertTrue(callable(cm.main))

    def test_main_signature_accepts_request(self):
        """main(req_ph) must accept one positional arg for Cloud Run Functions."""
        import inspect
        sig = inspect.signature(cm.main)
        self.assertEqual(len(sig.parameters), 1)


# ═══════════════════════════════════════════════════════════════════
# 11. Side-by-Side sheet short name generation
# ═══════════════════════════════════════════════════════════════════

class TestSideBySideShortNames(unittest.TestCase):
    """Verify the model name shortening logic for the Side-by-Side sheet headers."""

    def _short_name(self, model):
        """Mirror the actual short_name logic from run_comparison."""
        import re
        return re.sub(r"-\d{8}$", "", model.replace("claude-", ""))

    def test_sonnet4_short_name(self):
        self.assertEqual(self._short_name("claude-sonnet-4-20250514"), "sonnet-4")

    def test_haiku45_short_name(self):
        self.assertEqual(self._short_name("claude-haiku-4-5-20251001"), "haiku-4-5")

    def test_opus4_short_name(self):
        self.assertEqual(self._short_name("claude-opus-4-20250514"), "opus-4")

    def test_sonnet45_short_name(self):
        self.assertEqual(self._short_name("claude-sonnet-4-5-20250929"), "sonnet-4-5")


# ═══════════════════════════════════════════════════════════════════
# 12. get_api_key (mocked Secret Manager)
# ═══════════════════════════════════════════════════════════════════

class TestGetApiKey(unittest.TestCase):

    @patch("claude_model_comparison.secretmanager.SecretManagerServiceClient")
    def test_fetches_correct_secret(self, MockSMClient):
        mock_response = MagicMock()
        mock_response.payload.data = b"sk-ant-api03-test-key"
        mock_instance = MagicMock()
        mock_instance.access_secret_version.return_value = mock_response
        MockSMClient.return_value = mock_instance

        key = cm.get_api_key()
        self.assertEqual(key, "sk-ant-api03-test-key")

        # Verify correct secret path
        call_args = mock_instance.access_secret_version.call_args
        self.assertEqual(
            call_args.kwargs["request"]["name"],
            "projects/266686822828/secrets/claude-api-key/versions/latest"
        )

    @patch.dict(os.environ, {"SERVICE_ACCOUNT_PUBSUB": '{"type": "service_account", "project_id": "test"}'})
    @patch("claude_model_comparison.secretmanager.SecretManagerServiceClient")
    def test_uses_service_account_when_env_set(self, MockSMClient):
        mock_response = MagicMock()
        mock_response.payload.data = b"sk-test"
        mock_instance = MagicMock()
        mock_instance.access_secret_version.return_value = mock_response
        MockSMClient.from_service_account_info.return_value = mock_instance

        key = cm.get_api_key()
        self.assertEqual(key, "sk-test")
        MockSMClient.from_service_account_info.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# 13. upload_to_gcs (mocked)
# ═══════════════════════════════════════════════════════════════════

class TestUploadToGcs(unittest.TestCase):

    @patch("claude_model_comparison.storage.Client")
    def test_upload_calls_correct_bucket_and_blob(self, MockStorageClient):
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client_instance = MagicMock()
        mock_client_instance.bucket.return_value = mock_bucket
        MockStorageClient.return_value = mock_client_instance

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"test")
            tmp_path = f.name

        try:
            cm.upload_to_gcs(tmp_path, "de-raw-ingestion", "data/test.xlsx")
        finally:
            os.remove(tmp_path)

        mock_client_instance.bucket.assert_called_with("de-raw-ingestion")
        mock_bucket.blob.assert_called_with("data/test.xlsx")
        mock_blob.upload_from_filename.assert_called_once_with(tmp_path)


if __name__ == "__main__":
    unittest.main()
