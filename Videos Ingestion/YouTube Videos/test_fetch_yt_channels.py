"""
Unit tests for NewRawVideosIngestion_FetchYTChannelsData.py

Covers:
  - convert_relative_to_timestamp: all time units + edge cases
  - get_channel_videos_data:
      * Layout A — legacy videoRenderer
      * Layout B — new lockupViewModel (2024+)
      * Empty HTML / no ytInitialData (bot/consent page)
      * Missing responseContext marker
      * Malformed JSON
      * Mixed malformed + valid records (should skip bad, keep good)
      * Live fetch smoke test against real known-new-layout channel
"""

import io
import json
import pathlib
import sys
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

# Force UTF-8 on stdout so test descriptions with special chars don't crash
# on Windows consoles that default to cp1252.
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Import the module under test with GCP dependencies stubbed out.
# The production file does NOT call main() at module level (it's commented out)
# so a plain sys.path import works cleanly once google.cloud is mocked.
# Using a real import (not spec_from_file_location) avoids the jsonpath_ng
# yacc KeyError that occurs when the module is loaded under a non-standard name.
# ---------------------------------------------------------------------------
_src_dir = str(pathlib.Path(__file__).parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

_gcp_mock = mock.MagicMock()
with mock.patch.dict('sys.modules', {
    'google': _gcp_mock,
    'google.cloud': _gcp_mock,
    'google.cloud.pubsub_v1': _gcp_mock,
    'google.cloud.storage': _gcp_mock,
}):
    import NewRawVideosIngestion_FetchYTChannelsData as _mod

Utils = _mod.Utils
Processor = _mod.Processor


# ---------------------------------------------------------------------------
# Helpers to build minimal HTML fixtures
# ---------------------------------------------------------------------------

def _make_html(yt_initial_data: dict) -> str:
    """Wrap a ytInitialData dict in the minimal HTML structure YouTube uses.

    The production extractor first looks for '}};' as an end marker, and falls
    back to len(script_content) when not found.  Omitting the suffix here
    exercises the fallback path, which produces clean JSON.
    """
    payload = json.dumps(yt_initial_data)
    script = 'var ytInitialData = ' + payload
    return '<html><body>\n<script>' + script + '</script>\n</body></html>'


def _wrap_video_renderer(video_id, title_text, published, duration, width, height):
    return {
        "videoId": video_id,
        "title": {"runs": [{"text": title_text}]},
        "publishedTimeText": {"simpleText": published},
        "lengthText": {"simpleText": duration},
        "thumbnail": {"thumbnails": [{"url": f"https://i.ytimg.com/vi/{video_id}/hq.jpg",
                                       "width": width, "height": height}]}
    }


def _wrap_lockup_vm(video_id, title, published_ago, duration_str, width, height):
    return {
        "contentId": video_id,
        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
        "metadata": {
            "lockupMetadataViewModel": {
                "title": {"content": title},
                "metadata": {
                    "contentMetadataViewModel": {
                        "metadataRows": [
                            {"metadataParts": [
                                {"text": {"content": "1k views"}},
                                {"text": {"content": published_ago}},
                            ]}
                        ]
                    }
                }
            }
        },
        "contentImage": {
            "thumbnailViewModel": {
                "image": {"sources": [
                    {"url": f"https://i.ytimg.com/vi/{video_id}/hq.jpg", "width": width, "height": height}
                ]},
                "overlays": [
                    {"thumbnailBottomOverlayViewModel": {"badges": [
                        {"thumbnailBadgeViewModel": {"text": duration_str}}
                    ]}}
                ]
            }
        },
        "rendererContext": {}
    }


def _make_yt_data_with_video_renderer(*vr_dicts):
    return {
        "responseContext": {},
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [{"tabRenderer": {"content": {
                    "sectionListRenderer": {"contents": [
                        {"itemSectionRenderer": {"contents": [
                            {"gridRenderer": {"items": [
                                {"gridVideoRenderer": {}} ,   # noise
                                *[{"videoRenderer": vr} for vr in vr_dicts]
                            ]}}
                        ]}}
                    ]}
                }}}]
            }
        }
    }


def _make_yt_data_with_lockup(*lvm_dicts):
    return {
        "responseContext": {},
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [{"tabRenderer": {"content": {
                    "richGridRenderer": {"contents": [
                        {"richItemRenderer": {"content": {"lockupViewModel": lvm}}}
                        for lvm in lvm_dicts
                    ]}
                }}}]
            }
        }
    }


# Minimal processor instance (no GCS/PubSub needed for unit tests)
def _make_processor():
    debug_fn = MagicMock()
    ps = MagicMock()
    proc = Processor.__new__(Processor)
    proc.debug = debug_fn
    proc.ps = ps
    proc.total_failures = 0
    proc.total_successes = 0
    proc.max_threads = 1
    proc.all_channels_data = []
    proc.publishers_config = None
    return proc


# ---------------------------------------------------------------------------
# Tests: convert_relative_to_timestamp
# ---------------------------------------------------------------------------

class TestConvertRelativeToTimestamp(unittest.TestCase):

    def _approx(self, result_str, expected_dt, tolerance_seconds=5):
        """Assert result_str parses to a datetime within tolerance of expected_dt."""
        self.assertIsNotNone(result_str, "Expected a timestamp string, got None")
        # The function returns str(datetime_with_tz); parse it back
        from datetime import datetime
        result_dt = datetime.fromisoformat(result_str)
        delta = abs((result_dt - expected_dt).total_seconds())
        self.assertLessEqual(delta, tolerance_seconds,
                             f"Timestamp {result_str!r} too far from expected {expected_dt}: delta={delta}s")

    def _now(self):
        return datetime.now(tz=ZoneInfo("Asia/Kolkata"))

    def test_seconds(self):
        result = Utils.convert_relative_to_timestamp("30 seconds ago")
        self._approx(result, self._now() - timedelta(seconds=30))

    def test_minutes(self):
        result = Utils.convert_relative_to_timestamp("17 minutes ago")
        self._approx(result, self._now() - timedelta(minutes=17))

    def test_hours(self):
        result = Utils.convert_relative_to_timestamp("3 hours ago")
        self._approx(result, self._now() - timedelta(hours=3))

    def test_days(self):
        result = Utils.convert_relative_to_timestamp("2 days ago")
        self._approx(result, self._now() - timedelta(days=2))

    def test_weeks(self):
        result = Utils.convert_relative_to_timestamp("2 weeks ago")
        self._approx(result, self._now() - timedelta(weeks=2))

    def test_months(self):
        result = Utils.convert_relative_to_timestamp("3 months ago")
        self._approx(result, self._now() - timedelta(days=90))

    def test_years(self):
        result = Utils.convert_relative_to_timestamp("1 year ago")
        self._approx(result, self._now() - timedelta(days=365))

    def test_singular_minute(self):
        # "1 minute ago" — singular
        result = Utils.convert_relative_to_timestamp("1 minute ago")
        self._approx(result, self._now() - timedelta(minutes=1))

    def test_singular_hour(self):
        result = Utils.convert_relative_to_timestamp("1 hour ago")
        self._approx(result, self._now() - timedelta(hours=1))

    def test_none_input(self):
        self.assertIsNone(Utils.convert_relative_to_timestamp(None))

    def test_empty_string(self):
        self.assertIsNone(Utils.convert_relative_to_timestamp(""))

    def test_unknown_unit(self):
        self.assertIsNone(Utils.convert_relative_to_timestamp("recently"))

    def test_non_numeric_first_token(self):
        # Should not raise, should return None
        self.assertIsNone(Utils.convert_relative_to_timestamp("a few minutes ago"))

    def test_streamed_prefix(self):
        # YouTube sometimes shows "Streamed 2 hours ago" — first token is "streamed", not numeric
        # Should return None gracefully (not crash)
        result = Utils.convert_relative_to_timestamp("Streamed 2 hours ago")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests: get_channel_videos_data — Layout A (videoRenderer)
# ---------------------------------------------------------------------------

class TestGetChannelVideosData_VideoRenderer(unittest.TestCase):

    def setUp(self):
        self.proc = _make_processor()

    def test_single_landscape_video(self):
        data = _make_yt_data_with_video_renderer(
            _wrap_video_renderer("abc123", "Test Video Title", "2 days ago", "5:30", 320, 180)
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)

        self.assertEqual(len(result), 1)
        v = result[0]
        self.assertEqual(v['video_id'], 'abc123')
        self.assertEqual(v['title'], 'Test Video Title')
        self.assertEqual(v['duration'], '5:30')
        self.assertEqual(v['width'], 320)
        self.assertEqual(v['height'], 180)
        self.assertEqual(v['orientation'], 'landscape')
        self.assertIsNotNone(v['published_time'])

    def test_multiple_videos(self):
        data = _make_yt_data_with_video_renderer(
            _wrap_video_renderer("vid1", "Title 1", "1 hour ago", "2:00", 320, 180),
            _wrap_video_renderer("vid2", "Title 2", "3 days ago", "10:00", 320, 180),
            _wrap_video_renderer("vid3", "Title 3", "1 week ago", "7:45", 320, 180),
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 3)
        ids = [v['video_id'] for v in result]
        self.assertIn('vid1', ids)
        self.assertIn('vid3', ids)

    def test_portrait_orientation(self):
        data = _make_yt_data_with_video_renderer(
            _wrap_video_renderer("port1", "Portrait Vid", "5 hours ago", "1:00", 180, 320)
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result[0]['orientation'], 'portrait')

    def test_missing_published_time(self):
        """publishedTimeText absent ->published_time should be None, not crash."""
        vr = {
            "videoId": "novid1",
            "title": {"runs": [{"text": "No Published Time"}]},
            "lengthText": {"simpleText": "3:00"},
            "thumbnail": {"thumbnails": [{"url": "x", "width": 320, "height": 180}]}
            # publishedTimeText intentionally omitted
        }
        data = _make_yt_data_with_video_renderer(vr)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['published_time'])

    def test_missing_duration(self):
        """lengthText absent ->duration should be empty string, not crash."""
        vr = {
            "videoId": "nodur1",
            "title": {"runs": [{"text": "No Duration"}]},
            "publishedTimeText": {"simpleText": "1 day ago"},
            "thumbnail": {"thumbnails": [{"url": "x", "width": 320, "height": 180}]}
        }
        data = _make_yt_data_with_video_renderer(vr)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['duration'], '')

    def test_malformed_record_skipped_others_kept(self):
        """A videoRenderer with no videoId should be skipped; valid ones retained."""
        good = _wrap_video_renderer("good1", "Good Video", "1 day ago", "4:00", 320, 180)
        bad = {"title": {"runs": [{"text": "No ID"}]}}  # missing videoId
        data = _make_yt_data_with_video_renderer(good, bad)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['video_id'], 'good1')

    def test_simpletext_title_fallback(self):
        """Title via simpleText (no runs) should work."""
        vr = {
            "videoId": "stxt1",
            "title": {"simpleText": "SimpleText Title"},
            "publishedTimeText": {"simpleText": "2 hours ago"},
            "lengthText": {"simpleText": "6:00"},
            "thumbnail": {"thumbnails": [{"url": "x", "width": 320, "height": 180}]}
        }
        data = _make_yt_data_with_video_renderer(vr)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result[0]['title'], 'SimpleText Title')


# ---------------------------------------------------------------------------
# Tests: get_channel_videos_data — Layout B (lockupViewModel)
# ---------------------------------------------------------------------------

class TestGetChannelVideosData_LockupViewModel(unittest.TestCase):

    def setUp(self):
        self.proc = _make_processor()

    def test_single_video(self):
        data = _make_yt_data_with_lockup(
            _wrap_lockup_vm("lv_abc", "Lockup Title", "17 minutes ago", "3:30", 336, 188)
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)

        self.assertEqual(len(result), 1)
        v = result[0]
        self.assertEqual(v['video_id'], 'lv_abc')
        self.assertEqual(v['title'], 'Lockup Title')
        self.assertEqual(v['duration'], '3:30')
        self.assertEqual(v['width'], 336)
        self.assertEqual(v['height'], 188)
        self.assertEqual(v['orientation'], 'landscape')
        self.assertIsNotNone(v['published_time'])

    def test_multiple_videos(self):
        data = _make_yt_data_with_lockup(
            _wrap_lockup_vm("lv1", "Title A", "1 hour ago", "5:00", 336, 188),
            _wrap_lockup_vm("lv2", "Title B", "3 days ago", "2:30", 336, 188),
            _wrap_lockup_vm("lv3", "Title C", "2 weeks ago", "8:15", 336, 188),
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 3)

    def test_non_video_content_type_skipped(self):
        """LOCKUP_CONTENT_TYPE_PLAYLIST should be ignored."""
        playlist = {
            "contentId": "PLabc",
            "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST",
            "metadata": {"lockupMetadataViewModel": {"title": {"content": "A Playlist"}}},
            "contentImage": {"thumbnailViewModel": {"image": {"sources": []}, "overlays": []}},
            "rendererContext": {}
        }
        video = _wrap_lockup_vm("lv_vid", "Real Video", "5 hours ago", "4:00", 336, 188)
        data = _make_yt_data_with_lockup(playlist, video)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['video_id'], 'lv_vid')

    def test_missing_published_time_graceful(self):
        """No 'ago' in metadataParts ->published_time=None, no crash."""
        lvm = {
            "contentId": "nopub",
            "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": "No Pub Time"},
                    "metadata": {
                        "contentMetadataViewModel": {
                            "metadataRows": [{"metadataParts": [
                                {"text": {"content": "50k views"}}
                                # no 'ago' part
                            ]}]
                        }
                    }
                }
            },
            "contentImage": {
                "thumbnailViewModel": {
                    "image": {"sources": [{"url": "x", "width": 336, "height": 188}]},
                    "overlays": [{"thumbnailBottomOverlayViewModel": {"badges": [
                        {"thumbnailBadgeViewModel": {"text": "2:00"}}
                    ]}}]
                }
            },
            "rendererContext": {}
        }
        data = _make_yt_data_with_lockup(lvm)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['published_time'])

    def test_missing_duration_graceful(self):
        """No overlay badges ->duration='', no crash."""
        lvm = _wrap_lockup_vm("nodur", "No Duration", "2 hours ago", "3:00", 336, 188)
        lvm['contentImage']['thumbnailViewModel']['overlays'] = []  # strip overlays
        data = _make_yt_data_with_lockup(lvm)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['duration'], '')

    def test_weeks_published_time_parsed(self):
        data = _make_yt_data_with_lockup(
            _wrap_lockup_vm("wk1", "Old Video", "3 weeks ago", "6:00", 336, 188)
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0]['published_time'])


# ---------------------------------------------------------------------------
# Tests: failure / edge cases
# ---------------------------------------------------------------------------

class TestGetChannelVideosData_FailureCases(unittest.TestCase):

    def setUp(self):
        self.proc = _make_processor()

    def test_empty_html(self):
        result = self.proc.get_channel_videos_data("")
        self.assertEqual(result, [])

    def test_consent_page_no_ytInitialData(self):
        html = """<html><body>
        <h1>Before you continue to YouTube</h1>
        <p>We use cookies...</p>
        </body></html>"""
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result, [])

    def test_no_response_context_marker(self):
        """ytInitialData present but no responseContext key."""
        html = '<html><body><script>var ytInitialData = {"someOtherKey": {}};</script></body></html>'
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result, [])

    def test_malformed_json(self):
        html = '<html><body><script>var ytInitialData = {"responseContext": INVALID_JSON};</script></body></html>'
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result, [])

    def test_empty_contents(self):
        """ytInitialData with responseContext but no video data ->empty list, no crash."""
        data = {"responseContext": {}, "contents": {}}
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result, [])

    def test_videorenderer_with_no_videos_falls_through_to_lockup(self):
        """If videoRenderer matches 0 results, lockupViewModel branch should be tried."""
        # Build data with ONLY lockupViewModel (no videoRenderer at all)
        data = _make_yt_data_with_lockup(
            _wrap_lockup_vm("fallback1", "Fallback Video", "1 day ago", "4:00", 336, 188)
        )
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['video_id'], 'fallback1')

    def test_no_crash_on_completely_broken_record_in_lockup(self):
        """A fully broken lockupViewModel entry shouldn't prevent others from being parsed."""
        good = _wrap_lockup_vm("good_lv", "Good", "2 hours ago", "3:00", 336, 188)
        broken = {"contentType": "LOCKUP_CONTENT_TYPE_VIDEO", "contentId": "brk1"}  # missing metadata/contentImage
        data = _make_yt_data_with_lockup(broken, good)
        html = _make_html(data)
        result = self.proc.get_channel_videos_data(html)
        # good should still be present
        self.assertTrue(any(v['video_id'] == 'good_lv' for v in result))

    def test_bot_check_page(self):
        """Unusual traffic / sorry page returns no data."""
        html = """<html><body>
        <p>Our systems have detected unusual traffic from your computer network.</p>
        </body></html>"""
        result = self.proc.get_channel_videos_data(html)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Live smoke test — hits actual YouTube (skipped in CI if network unavailable)
# ---------------------------------------------------------------------------

class TestLiveSmokeTest(unittest.TestCase):
    """
    Hits real YouTube pages to validate the fix works end-to-end.
    Skipped automatically if network is unavailable.
    """

    def setUp(self):
        import socket
        try:
            socket.setdefaulttimeout(5)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        except socket.error:
            self.skipTest("No network — skipping live tests")
        self.proc = _make_processor()

    def _fetch(self, channel_id):
        import requests
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        r = requests.get(url, timeout=10, headers=headers)
        return r.text

    def test_network18_lockup_layout(self):
        """Network18/FirstPost — confirmed lockupViewModel layout."""
        html = self._fetch("UCz8QaiQxApLq8sLNcszYyJw")
        result = self.proc.get_channel_videos_data(html)
        self.assertGreater(len(result), 0,
                           "Expected >0 videos for Network18 with lockupViewModel layout")
        for v in result:
            self.assertNotEqual(v['video_id'], '', "video_id must not be empty")
            self.assertNotEqual(v['title'], '', "title must not be empty")
        print(f"\n[LIVE] Network18: {len(result)} videos extracted")
        print(f"  Sample: {result[0]}")

    def test_all_records_have_required_fields(self):
        """Every record must contain all required keys with correct types."""
        html = self._fetch("UCz8QaiQxApLq8sLNcszYyJw")
        result = self.proc.get_channel_videos_data(html)
        required_keys = {'video_id', 'title', 'published_time', 'duration', 'width', 'height', 'orientation'}
        for v in result:
            for key in required_keys:
                self.assertIn(key, v, f"Key '{key}' missing from record: {v}")
            self.assertIn(v['orientation'], ('landscape', 'portrait'))

    def test_etv_bharat_channel(self):
        """ETV Bharat — another known new-layout channel."""
        html = self._fetch("UCXE-a27-EBapw1foqm2CQnQ")
        result = self.proc.get_channel_videos_data(html)
        self.assertGreater(len(result), 0,
                           "Expected >0 videos for ETV Bharat with lockupViewModel layout")
        print(f"\n[LIVE] ETV Bharat: {len(result)} videos extracted")


if __name__ == '__main__':
    # Run with verbosity so individual test names show in output
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Ordering: unit tests first, live last
    for cls in [
        TestConvertRelativeToTimestamp,
        TestGetChannelVideosData_VideoRenderer,
        TestGetChannelVideosData_LockupViewModel,
        TestGetChannelVideosData_FailureCases,
        TestLiveSmokeTest,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
