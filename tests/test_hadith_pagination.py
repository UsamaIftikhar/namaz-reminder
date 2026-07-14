import os
import sys
import types
import unittest
from datetime import timezone
from unittest.mock import patch


os.environ.setdefault("SLACK_WEBHOOK", "https://hooks.slack.test/primary")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

# These unit tests exercise pure sequencing logic and do not need live clients.
# Lightweight stubs keep the test suite runnable before dependencies are installed.
requests_stub = types.ModuleType("requests")
pytz_stub = types.ModuleType("pytz")
pytz_stub.timezone = lambda _name: timezone.utc
supabase_stub = types.ModuleType("supabase")
supabase_stub.create_client = lambda _url, _key: object()
sys.modules["requests"] = requests_stub
sys.modules["pytz"] = pytz_stub
sys.modules["supabase"] = supabase_stub

from api import index as app


def make_hadith(number, english="Short Hadith"):
    return {
        "hadithNumber": str(number),
        "hadithArabic": "Arabic",
        "hadithEnglish": english,
        "hadithUrdu": "Urdu",
        "englishNarrator": "Narrator",
        "urduNarrator": "Narrator",
        "headingEnglish": "Chapter",
    }


def make_page(start, end, total=400, per_page=200, overrides=None):
    overrides = overrides or {}
    return {
        "current_page": ((start - 1) // per_page) + 1,
        "per_page": per_page,
        "total": total,
        "from": start,
        "to": end,
        "data": [overrides.get(number, make_hadith(number)) for number in range(start, end + 1)],
    }


class HadithPaginationTests(unittest.TestCase):
    def test_fresh_sequence_advances_normally(self):
        self.assertEqual(app.next_hadith_sequence(None), 0)
        self.assertEqual(app.next_hadith_sequence(0), 1)

    @patch.object(app, "fetch_hadith_page")
    def test_legacy_cycle_resumes_at_hadith_26(self, fetch_page):
        fetch_page.return_value = make_page(1, 200)

        sequence, hadith, _ = app.find_next_fitting_hadith(
            last_sequence=20,
            legacy_page_completed=True,
        )

        self.assertEqual(sequence, 25)
        self.assertEqual(hadith["hadithNumber"], "26")

    @patch.object(app, "fetch_hadith_page")
    def test_crosses_api_page_boundary_without_wrapping(self, fetch_page):
        pages = {1: make_page(1, 200), 2: make_page(201, 400)}
        fetch_page.side_effect = pages.__getitem__

        sequence, hadith, _ = app.find_next_fitting_hadith(last_sequence=199)

        self.assertEqual(sequence, 200)
        self.assertEqual(hadith["hadithNumber"], "201")
        self.assertEqual(fetch_page.call_count, 2)

    @patch.object(app, "fetch_hadith_page")
    def test_long_hadith_is_skipped_without_resetting_sequence(self, fetch_page):
        long_hadith = make_hadith(26, english="x" * 4000)
        fetch_page.return_value = make_page(1, 200, overrides={26: long_hadith})

        sequence, hadith, _ = app.find_next_fitting_hadith(last_sequence=24)

        self.assertEqual(sequence, 26)
        self.assertEqual(hadith["hadithNumber"], "27")


if __name__ == "__main__":
    unittest.main()
