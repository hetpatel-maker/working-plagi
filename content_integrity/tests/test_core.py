"""
Unit tests for the content_integrity plugin.

These tests cover the local, non-network-dependent logic:
- Hashing (whitespace normalization, change detection)
- HTML extraction (tag stripping, edge cases)
- SRT transcript parsing (video extraction)
- OLX problem text parsing
- Task logic (hash-skip, force_recheck, report aggregation)
- Receiver routing (container vs. leaf blocks)
"""
import unittest
from unittest.mock import patch, MagicMock

from content_integrity.hashing import hash_text, normalize_text
from content_integrity.extraction import (
    _extract_html, _extract_video, _parse_srt_to_text, _parse_problem_olx,
)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class HashingTests(unittest.TestCase):
    def test_whitespace_changes_dont_change_hash(self):
        a = hash_text("Hello   world")
        b = hash_text("Hello\nworld  ")
        self.assertEqual(a, b)

    def test_wording_changes_do_change_hash(self):
        a = hash_text("Hello world")
        b = hash_text("Hello there world")
        self.assertNotEqual(a, b)

    def test_normalize_handles_empty(self):
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text(""), "")

    def test_normalize_collapses_tabs_and_newlines(self):
        self.assertEqual(normalize_text("a\t\tb\n\nc"), "a b c")

    def test_identical_text_produces_same_hash(self):
        a = hash_text("The quick brown fox")
        b = hash_text("The quick brown fox")
        self.assertEqual(a, b)

    def test_hash_is_64_char_hex(self):
        """SHA-256 hex digest should be exactly 64 characters."""
        h = hash_text("test")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


# ---------------------------------------------------------------------------
# HTML Extraction
# ---------------------------------------------------------------------------

class HtmlExtractionTests(unittest.TestCase):
    def test_strips_tags(self):
        block = {"student_view_data": {"html": "<p>Hello <b>world</b></p>"}}
        text = _extract_html(block)
        self.assertIn("Hello", text)
        self.assertIn("world", text)
        self.assertNotIn("<p>", text)

    def test_handles_missing_data(self):
        self.assertEqual(_extract_html({}), "")

    def test_handles_nested_dict_structure(self):
        """student_view_data can be a dict with an 'html' key."""
        block = {"student_view_data": {"html": "<div>Content here</div>"}}
        text = _extract_html(block)
        self.assertEqual(text.strip(), "Content here")

    def test_handles_string_student_view_data(self):
        """In some cases student_view_data might be a raw string."""
        block = {"student_view_data": "<p>Direct HTML</p>"}
        text = _extract_html(block)
        self.assertIn("Direct HTML", text)

    def test_handles_none_student_view_data(self):
        block = {"student_view_data": None}
        self.assertEqual(_extract_html(block), "")

    def test_preserves_text_from_multiple_elements(self):
        block = {"student_view_data": {"html": "<h1>Title</h1><p>Body text</p><ul><li>Item 1</li></ul>"}}
        text = _extract_html(block)
        self.assertIn("Title", text)
        self.assertIn("Body text", text)
        self.assertIn("Item 1", text)


# ---------------------------------------------------------------------------
# SRT Transcript Parsing
# ---------------------------------------------------------------------------

class SrtParsingTests(unittest.TestCase):
    def test_parses_standard_srt(self):
        srt = """1
00:00:01,000 --> 00:00:05,000
This is the first subtitle.

2
00:00:06,000 --> 00:00:10,000
This is the second subtitle.
"""
        text = _parse_srt_to_text(srt)
        self.assertIn("first subtitle", text)
        self.assertIn("second subtitle", text)
        # Should not contain timestamps or sequence numbers.
        self.assertNotIn("00:00:01", text)
        self.assertNotIn("-->", text)

    def test_strips_html_tags_from_srt(self):
        """Some SRT files contain HTML formatting like <i> and <b>."""
        srt = """1
00:00:01,000 --> 00:00:03,000
<i>Italic text</i> and <b>bold text</b>
"""
        text = _parse_srt_to_text(srt)
        self.assertIn("Italic text", text)
        self.assertIn("bold text", text)
        self.assertNotIn("<i>", text)
        self.assertNotIn("<b>", text)

    def test_empty_srt(self):
        self.assertEqual(_parse_srt_to_text(""), "")

    def test_srt_with_only_timestamps(self):
        srt = """1
00:00:01,000 --> 00:00:03,000

2
00:00:04,000 --> 00:00:06,000
"""
        text = _parse_srt_to_text(srt)
        self.assertEqual(text.strip(), "")


# ---------------------------------------------------------------------------
# Video Extraction (block-level)
# ---------------------------------------------------------------------------

class VideoExtractionTests(unittest.TestCase):
    def test_returns_empty_for_missing_student_view_data(self):
        self.assertEqual(_extract_video({}), "")
        self.assertEqual(_extract_video({"student_view_data": None}), "")

    def test_returns_empty_for_no_transcripts(self):
        block = {"student_view_data": {"transcripts": {}}}
        self.assertEqual(_extract_video(block), "")

    @patch("content_integrity.extraction._get_lms_access_token", return_value="fake-token")
    @patch("content_integrity.extraction.requests.get")
    def test_downloads_and_parses_transcript(self, mock_get, mock_token):
        srt_content = """1
00:00:01,000 --> 00:00:05,000
Hello from the video.
"""
        mock_resp = MagicMock()
        mock_resp.text = srt_content
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        block = {
            "student_view_data": {
                "transcripts": {"en": "https://lms.example.com/transcript_en.srt"}
            }
        }
        text = _extract_video(block)
        self.assertIn("Hello from the video", text)
        mock_get.assert_called_once()

    @patch("content_integrity.extraction._get_lms_access_token", return_value="fake-token")
    @patch("content_integrity.extraction.requests.get")
    def test_falls_back_to_non_english_transcript(self, mock_get, mock_token):
        srt_content = """1
00:00:01,000 --> 00:00:03,000
Hola del video.
"""
        mock_resp = MagicMock()
        mock_resp.text = srt_content
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        block = {
            "student_view_data": {
                "transcripts": {"es": "https://lms.example.com/transcript_es.srt"}
            }
        }
        text = _extract_video(block)
        self.assertIn("Hola del video", text)

    @patch("content_integrity.extraction._get_lms_access_token", return_value="fake-token")
    @patch("content_integrity.extraction.requests.get", side_effect=Exception("Network error"))
    def test_returns_empty_on_download_failure(self, mock_get, mock_token):
        block = {
            "student_view_data": {
                "transcripts": {"en": "https://lms.example.com/transcript_en.srt"}
            }
        }
        text = _extract_video(block)
        self.assertEqual(text, "")


# ---------------------------------------------------------------------------
# Problem OLX Parsing
# ---------------------------------------------------------------------------

class ProblemOlxParsingTests(unittest.TestCase):
    def test_extracts_question_text(self):
        olx = """
        <problem>
          <multiplechoiceresponse>
            <label>What is 2 + 2?</label>
            <choicegroup>
              <choice correct="true">4</choice>
              <choice correct="false">3</choice>
              <choice correct="false">5</choice>
            </choicegroup>
          </multiplechoiceresponse>
        </problem>
        """
        text = _parse_problem_olx(olx)
        self.assertIn("What is 2 + 2?", text)
        self.assertIn("4", text)
        self.assertIn("3", text)
        self.assertIn("5", text)

    def test_extracts_hints_and_solutions(self):
        olx = """
        <problem>
          <multiplechoiceresponse>
            <label>Sample question</label>
          </multiplechoiceresponse>
          <demandhint>
            <hint>Think about basic math.</hint>
          </demandhint>
          <solution>
            <p>The answer is obvious.</p>
          </solution>
        </problem>
        """
        text = _parse_problem_olx(olx)
        self.assertIn("Think about basic math", text)
        self.assertIn("The answer is obvious", text)

    def test_strips_script_tags(self):
        olx = """
        <problem>
          <script>var x = 1;</script>
          <label>Real question</label>
        </problem>
        """
        text = _parse_problem_olx(olx)
        self.assertIn("Real question", text)
        self.assertNotIn("var x", text)

    def test_handles_empty_olx(self):
        self.assertEqual(_parse_problem_olx(""), "")

    def test_handles_malformed_olx(self):
        """Should not crash on malformed XML, just extract what it can."""
        olx = "<problem><label>Unclosed tag<label>"
        text = _parse_problem_olx(olx)
        self.assertIn("Unclosed tag", text)


# ---------------------------------------------------------------------------
# Receiver Routing
# ---------------------------------------------------------------------------

class ReceiverRoutingTests(unittest.TestCase):
    """
    Test that the signal handler routes container vs. leaf blocks correctly.

    These tests mock openedx_events at the sys.modules level so they can
    run outside the Open edX platform environment. All mocking is done
    inside each test method to avoid timing issues with @patch decorators.
    """

    def _setup_mocks_and_import(self):
        """
        Inject mock openedx_events, celery, and other platform deps into
        sys.modules, force-reimport receivers, and return
        (receivers_module, original_modules_snapshot).
        """
        import sys
        import importlib

        originals = {}

        # Mock openedx_events hierarchy
        mock_signals = MagicMock()
        mock_signals.XBLOCK_PUBLISHED = MagicMock()
        mock_signals.XBLOCK_DELETED = MagicMock()

        # Mock celery (shared_task should be a simple pass-through decorator)
        mock_celery = MagicMock()
        mock_celery.shared_task = lambda *a, **kw: (lambda f: f) if not a else a[0]

        # Mock opaque_keys (used by permissions.py which models.py might trigger)
        mock_opaque = MagicMock()

        modules_to_mock = [
            ("openedx_events", MagicMock()),
            ("openedx_events.content_authoring", MagicMock()),
            ("openedx_events.content_authoring.signals", mock_signals),
            ("celery", mock_celery),
            ("opaque_keys", mock_opaque),
            ("opaque_keys.edx", MagicMock()),
            ("opaque_keys.edx.keys", MagicMock()),
            ("common", MagicMock()),
            ("common.djangoapps", MagicMock()),
            ("common.djangoapps.student", MagicMock()),
            ("common.djangoapps.student.roles", MagicMock()),
        ]
        for mod_name, mock_mod in modules_to_mock:
            originals[mod_name] = sys.modules.get(mod_name)
            sys.modules[mod_name] = mock_mod

        # Clear any cached imports so they reimport with mocks
        for mod in [
            "content_integrity.receivers",
            "content_integrity.tasks",
            "content_integrity.providers",
            "content_integrity.providers.base",
            "content_integrity.providers.copyleaks",
            "content_integrity.providers.plagiarismcheck",
            "content_integrity.api",
            "content_integrity.api.permissions",
        ]:
            if mod in sys.modules:
                originals[mod] = sys.modules.pop(mod)

        # Now import receivers — it will see the mocked deps
        from content_integrity import receivers as recv_mod

        return recv_mod, originals

    def _teardown_mocks(self, originals):
        import sys
        for mod_name, original in originals.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original

    def test_container_block_triggers_children_enumeration(self):
        recv_mod, originals = self._setup_mocks_and_import()
        try:
            mock_enum = MagicMock()
            mock_publish = MagicMock()
            recv_mod.enqueue_children_checks = mock_enum
            recv_mod.process_block_publish = mock_publish

            for block_type in recv_mod.CONTAINER_BLOCK_TYPES:
                mock_info = MagicMock()
                mock_info.usage_key = MagicMock()
                mock_info.usage_key.__str__ = lambda s: "block-v1:test+course+run+type@vertical+block@1"
                mock_info.usage_key.course_key = MagicMock()
                mock_info.usage_key.course_key.__str__ = lambda s: "course-v1:test+course+run"
                mock_info.block_type = block_type

                recv_mod.on_xblock_published(sender=None, signal=None, xblock_info=mock_info)

            self.assertEqual(mock_enum.delay.call_count, len(recv_mod.CONTAINER_BLOCK_TYPES))
            mock_publish.delay.assert_not_called()
        finally:
            self._teardown_mocks(originals)

    def test_leaf_block_triggers_direct_publish(self):
        recv_mod, originals = self._setup_mocks_and_import()
        try:
            mock_enum = MagicMock()
            mock_publish = MagicMock()
            recv_mod.enqueue_children_checks = mock_enum
            recv_mod.process_block_publish = mock_publish

            for block_type in recv_mod.CHECKABLE_BLOCK_TYPES:
                mock_info = MagicMock()
                mock_info.usage_key = MagicMock()
                mock_info.usage_key.__str__ = lambda s: "block-v1:test+course+run+type@html+block@1"
                mock_info.usage_key.course_key = MagicMock()
                mock_info.usage_key.course_key.__str__ = lambda s: "course-v1:test+course+run"
                mock_info.block_type = block_type

                recv_mod.on_xblock_published(sender=None, signal=None, xblock_info=mock_info)

            self.assertEqual(mock_publish.delay.call_count, len(recv_mod.CHECKABLE_BLOCK_TYPES))
            mock_enum.delay.assert_not_called()
        finally:
            self._teardown_mocks(originals)

    def test_ignores_missing_xblock_info(self):
        recv_mod, originals = self._setup_mocks_and_import()
        try:
            mock_enum = MagicMock()
            mock_publish = MagicMock()
            recv_mod.enqueue_children_checks = mock_enum
            recv_mod.process_block_publish = mock_publish

            recv_mod.on_xblock_published(sender=None, signal=None)

            mock_publish.delay.assert_not_called()
            mock_enum.delay.assert_not_called()
        finally:
            self._teardown_mocks(originals)


if __name__ == "__main__":
    unittest.main()
