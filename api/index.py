from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import requests
from datetime import datetime, timedelta, date
import pytz
from urllib.parse import urlparse
from supabase import create_client

# -------------------------
# CONFIG
# -------------------------
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK not set!")

SLACK_WEBHOOK_2 = os.getenv("SLACK_WEBHOOK_2")

HADITH_API_KEY = os.getenv("HADITH_API_KEY")
HADITH_API_URL = "https://hadithapi.com/api/hadiths"
HADITH_BOOK = "sahih-bukhari"
HADITH_PAGE_SIZE = 200  # API maximum; reduces requests while covering the full book.
LEGACY_HADITH_PAGE_SIZE = 25  # Old code only ever loaded the API's default first page.

CITY_LAT = float(os.getenv("CITY_LAT", "31.4313584"))
CITY_LON = float(os.getenv("CITY_LON", "74.2782463"))
TZ = pytz.timezone("Asia/Karachi")

HADITH_TRACK_TABLE = os.getenv("HADITH_TRACK_TABLE", "daily_hadith_track")
NOTIFICATION_LOCK_TABLE = os.getenv("NOTIFICATION_LOCK_TABLE", "daily_notification_lock")
NOTIFICATION_LOCK_RETENTION_DAYS = int(os.getenv("NOTIFICATION_LOCK_RETENTION_DAYS", "30"))


def _build_channels():
    """Channel 1 (boys) + optional channel 2 (girls)."""
    channels = [
        {"id": "1", "label": "boys", "webhook": SLACK_WEBHOOK},
    ]
    if SLACK_WEBHOOK_2:
        channels.append(
            {
                "id": "2",
                "label": "girls",
                "webhook": SLACK_WEBHOOK_2,
            }
        )
    return channels


CHANNELS = _build_channels()

WINDOW_MINUTES = 5
LAST_SENT = {}

SLACK_MAX_LENGTH = 3800  # single message limit

# -------------------------
# SUPABASE CLIENT
# -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not set!")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# HELPERS
# -------------------------
def send_slack_message(message, webhook_url=None):
    """Send message to a Slack incoming webhook (defaults to primary)."""
    url = webhook_url or SLACK_WEBHOOK
    try:
        r = requests.post(url, json={"text": message})
        print(f"Sent Slack message ({len(message)} chars), response: {r.status_code}")
        return True
    except Exception as e:
        print(f"Error sending Slack: {e}")
        return False


def all_hadith_webhooks():
    """Same hadith goes to every configured channel."""
    return [c["webhook"] for c in CHANNELS]

def is_within_range(now, target):
    return target <= now < (target + timedelta(minutes=WINDOW_MINUTES))


def notification_already_sent(notification_key):
    """Check DB lock table first; fallback to in-memory state."""
    if LAST_SENT.get(notification_key):
        return True
    try:
        res = (
            supabase.table(NOTIFICATION_LOCK_TABLE)
            .select("notify_key")
            .eq("notify_key", notification_key)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        # If table isn't available yet, continue with in-memory dedupe.
        print(f"Notification lock read failed, using memory dedupe: {e}")
        return bool(LAST_SENT.get(notification_key))


def lock_notification(notification_key):
    """Create DB lock for this notification key."""
    try:
        supabase.table(NOTIFICATION_LOCK_TABLE).insert(
            {"notify_key": notification_key, "track_date": date.today().isoformat()}
        ).execute()
        return True
    except Exception as e:
        print(f"Notification lock insert failed: {e}")
        return False


def unlock_notification(notification_key):
    """Release DB lock if send fails, allowing a later retry."""
    try:
        supabase.table(NOTIFICATION_LOCK_TABLE).delete().eq("notify_key", notification_key).execute()
    except Exception as e:
        print(f"Notification unlock failed: {e}")


def send_once(notification_key, message, webhook_url):
    """
    Cross-instance dedupe:
    1) check existing lock
    2) acquire lock
    3) send
    4) release lock on failure
    """
    if notification_already_sent(notification_key):
        return False

    if not lock_notification(notification_key):
        # Fallback behavior if lock table missing/unavailable.
        if LAST_SENT.get(notification_key):
            return False
        if send_slack_message(message, webhook_url=webhook_url):
            LAST_SENT[notification_key] = True
            return True
        return False

    if send_slack_message(message, webhook_url=webhook_url):
        LAST_SENT[notification_key] = True
        return True

    unlock_notification(notification_key)
    return False


def cleanup_old_notification_locks(now):
    """Delete old lock rows once per day."""
    cleanup_key = f"lock-cleanup-{now.strftime('%Y-%m-%d')}"
    if LAST_SENT.get(cleanup_key):
        return

    cutoff_date = (now.date() - timedelta(days=NOTIFICATION_LOCK_RETENTION_DAYS)).isoformat()
    try:
        supabase.table(NOTIFICATION_LOCK_TABLE).delete().lt("track_date", cutoff_date).execute()
        LAST_SENT[cleanup_key] = True
        print(f"Notification lock cleanup done. Removed rows older than {cutoff_date}")
    except Exception as e:
        print(f"Notification lock cleanup failed: {e}")

def round_asar_time(dt):
    minute = dt.minute
    if minute <= 30:
        return dt.replace(minute=30, second=0, microsecond=0)
    else:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

def get_prayer_times(lat, lon):
    today = datetime.utcnow().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timings/{today}?latitude={lat}&longitude={lon}&method=3"
    try:
        data = requests.get(url).json()
        return data["data"]["timings"]
    except Exception as e:
        print(f"Error fetching prayer times: {e}")
        return {}

# -------------------------
# HADITH LOGIC
# -------------------------
def fetch_hadith_page(page):
    try:
        response = requests.get(
            HADITH_API_URL,
            params={
                "apiKey": HADITH_API_KEY,
                "book": HADITH_BOOK,
                "paginate": HADITH_PAGE_SIZE,
                "page": page,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("hadiths", {})
    except Exception as e:
        print(f"Error fetching Hadith page {page}: {e}")
        return {}

def format_hadith_message(hadith):
    """Format Hadith for Slack message."""
    arabic = hadith.get("hadithArabic", "N/A")
    english = hadith.get("hadithEnglish", "N/A")
    urdu = hadith.get("hadithUrdu", "N/A")
    eng_narrator = hadith.get("englishNarrator", "Unknown")
    urdu_narrator = hadith.get("urduNarrator", "N/A")
    hadith_number = hadith.get("hadithNumber", "N/A")
    chapter = hadith.get("headingEnglish", "N/A")

    message = (
        f":crescent_moon: *Daily Hadith Reminder* :crescent_moon:\n\n"
        f"*Arabic:*\n{arabic}\n\n"
        f"*English:*\n{english}\n\n"
        f"*Urdu:*\n{urdu}\n\n"
        f"— Narrated by: {eng_narrator} / {urdu_narrator}\n\n"
        f":book: Source: Sahih Bukhari, Hadith Number: {hadith_number}, Chapter: {chapter}"
    )
    return message

def next_hadith_sequence(last_sequence, legacy_page_completed=False):
    """Return the next monotonic sequence value, migrating the old 25-item cycle."""
    if last_sequence is None:
        return 0
    if legacy_page_completed and last_sequence < LEGACY_HADITH_PAGE_SIZE:
        # Legacy values 0-24 only identify an item on API page 1. That page has
        # already cycled in production, so continue from Hadith 26.
        return LEGACY_HADITH_PAGE_SIZE
    return last_sequence + 1


def find_next_fitting_hadith(last_sequence, legacy_page_completed=False):
    """Find the next Slack-sized Hadith across every API page."""
    first_page = fetch_hadith_page(1)
    hadiths = first_page.get("data", [])
    total_hadith = int(first_page.get("total") or len(hadiths))
    per_page = int(first_page.get("per_page") or HADITH_PAGE_SIZE)
    if not hadiths or total_hadith <= 0:
        return None

    page_cache = {1: first_page}
    sequence = next_hadith_sequence(last_sequence, legacy_page_completed)

    # A monotonic sequence is persisted. Modulo is used only to start over after
    # the complete book has been exhausted, never after a single API page.
    for _ in range(total_hadith):
        position = sequence % total_hadith
        page_number = (position // per_page) + 1
        page_data = page_cache.get(page_number)
        if page_data is None:
            page_data = fetch_hadith_page(page_number)
            if not page_data.get("data"):
                return None
            page_cache[page_number] = page_data

        page_start = int(page_data.get("from") or ((page_number - 1) * per_page + 1)) - 1
        page_offset = position - page_start
        page_hadiths = page_data.get("data", [])
        if page_offset < 0 or page_offset >= len(page_hadiths):
            print(f"Hadith position {position} missing from API page {page_number}")
            return None

        hadith = page_hadiths[page_offset]
        message = format_hadith_message(hadith)
        if len(message) <= SLACK_MAX_LENGTH:
            return sequence, hadith, message

        print(
            f"Skipped Hadith {hadith.get('hadithNumber', position + 1)}, "
            f"too long ({len(message)} chars)"
        )
        sequence += 1

    return None


def send_hadith_single_message():
    """Send at most one new Hadith per Karachi calendar day."""
    today = datetime.now(TZ).date().isoformat()

    today_result = (
        supabase.table(HADITH_TRACK_TABLE)
        .select("hadith_index")
        .eq("track_date", today)
        .limit(1)
        .execute()
    )
    if today_result.data:
        return "Hadith already sent today"

    previous_result = (
        supabase.table(HADITH_TRACK_TABLE)
        .select("hadith_index")
        .order("track_date", desc=True)
        .limit(LEGACY_HADITH_PAGE_SIZE + 1)
        .execute()
    )
    last_sequence = previous_result.data[0]["hadith_index"] if previous_result.data else None
    legacy_page_completed = any(
        row["hadith_index"] == LEGACY_HADITH_PAGE_SIZE - 1
        for row in (previous_result.data or [])
    )
    selected = find_next_fitting_hadith(last_sequence, legacy_page_completed)
    if selected is None:
        return "No Hadith fits in a single message today"

    sequence, hadith, message = selected
    supabase.table(HADITH_TRACK_TABLE).insert(
        {"track_date": today, "hadith_index": sequence}
    ).execute()

    webhooks = all_hadith_webhooks()
    for webhook in webhooks:
        send_slack_message(message, webhook_url=webhook)

    hadith_number = hadith.get("hadithNumber", sequence + 1)
    return f"Hadith {hadith_number} sent to {len(webhooks)} channel(s)"

# -------------------------
# HTTP HANDLER
# -------------------------
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now = datetime.now(TZ).replace(second=0, microsecond=0)
        if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            response_text = "Weekend skip: no notifications"
            print(f"Response: {response_text}")
            self.wfile.write(response_text.encode("utf-8"))
            return

        today_str = now.strftime("%Y-%m-%d")
        sent_messages = []
        cleanup_old_notification_locks(now)

        parsed_path = urlparse(self.path).path
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Incoming request path: {self.path}")

        # Test Slack
        if parsed_path.endswith("/test-slack"):
            for ch in CHANNELS:
                send_slack_message(
                    f"🕌 Test message ({ch['label']}) at {now.strftime('%I:%M %p')}",
                    webhook_url=ch["webhook"],
                )
            sent_messages.append("Test Slack message sent (all channels)")
            msg = send_hadith_single_message()
            sent_messages.append(msg)

        # Prayer times: same location for both channels, but custom per-channel business rules.
        base_timings = get_prayer_times(CITY_LAT, CITY_LON)
        if base_timings:
            asr_api = datetime.strptime(base_timings.get("Asr", "17:00"), "%H:%M")
            boys_asar = now.replace(hour=asr_api.hour, minute=asr_api.minute)
            boys_asar = round_asar_time(boys_asar) + timedelta(minutes=45)

            maghrib_api = datetime.strptime(base_timings.get("Maghrib", "18:30"), "%H:%M")
            maghrib_base = now.replace(hour=maghrib_api.hour, minute=maghrib_api.minute)

            channel_prayers = {
                "1": {  # Boys
                    "Zohar": now.replace(hour=13, minute=40),
                    "Asar": boys_asar,
                    # Boys: reminder should occur at api-5 with "15 min left",
                    # so prayer time is api+10.
                    "Maghrib": maghrib_base + timedelta(minutes=10),
                }
            }
            if SLACK_WEBHOOK_2:
                channel_prayers["2"] = {  # Girls
                    "Zohar": now.replace(hour=14, minute=5),
                    "Asar": boys_asar + timedelta(minutes=30),
                    # Girls: maghrib on API time.
                    "Maghrib": maghrib_base,
                }

            for ch in CHANNELS:
                cid = ch["id"]
                prayers = channel_prayers.get(cid, channel_prayers["1"])
                for name, prayer_time in prayers.items():
                    reminder_time = prayer_time - timedelta(minutes=15)
                    prayer_key = f"{cid}-{name}-{today_str}-prayer"
                    reminder_key = f"{cid}-{name}-{today_str}-reminder"

                    if is_within_range(now, reminder_time):
                        if send_once(
                            reminder_key,
                            f"⏰ 15 min left for {name} prayer",
                            webhook_url=ch["webhook"],
                        ):
                            sent_messages.append(f"ch{cid} {name} reminder sent")

                    if is_within_range(now, prayer_time):
                        if send_once(
                            prayer_key,
                            f"🕌 Time for {name} prayer!",
                            webhook_url=ch["webhook"],
                        ):
                            sent_messages.append(f"ch{cid} {name} prayer sent")

        # Daily Hadith at 10 AM
        hadith_key = f"hadith-{today_str}"
        hadith_time = now.replace(hour=10, minute=0)
        if is_within_range(now, hadith_time) and not LAST_SENT.get(hadith_key):
            msg = send_hadith_single_message()
            LAST_SENT[hadith_key] = True
            sent_messages.append(msg)

        # Response
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        response_text = f"Sent: {', '.join(sent_messages)}" if sent_messages else "No match"
        print(f"Response: {response_text}")
        self.wfile.write(response_text.encode("utf-8"))

# -------------------------
# SERVER ENTRY
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Server running on port {port}...")
    server = HTTPServer(("", port), handler)
    server.serve_forever()
