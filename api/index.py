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
HADITH_API_URL = f"https://hadithapi.com/api/hadiths?apiKey={HADITH_API_KEY}&book=sahih-bukhari"

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
def fetch_hadiths():
    try:
        data = requests.get(HADITH_API_URL).json()
        return data.get("hadiths", {}).get("data", [])
    except Exception as e:
        print(f"Error fetching hadiths: {e}")
        return []

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

def send_hadith_single_message():
    """Send a Hadith only if it fits in one Slack message and update index."""
    hadith_list = fetch_hadiths()
    if not hadith_list:
        return "No Hadith available"

    total_hadith = len(hadith_list)
    today = date.today().isoformat()

    # Get today's last index
    res = supabase.table(HADITH_TRACK_TABLE).select("*").eq("track_date", today).execute()
    if res.data and len(res.data) > 0:
        last_index = res.data[0]["hadith_index"]
    else:
        # Get last index from previous days
        res_last = supabase.table(HADITH_TRACK_TABLE).select("hadith_index").order("track_date", desc=True).limit(1).execute()
        last_index = res_last.data[0]["hadith_index"] if res_last.data else -1

    # Try each Hadith in circular order
    for i in range(total_hadith):
        index = (last_index + 1 + i) % total_hadith
        hadith = hadith_list[index]
        message = format_hadith_message(hadith)

        if len(message) <= SLACK_MAX_LENGTH:
            # Update index for today
            if res.data and len(res.data) > 0:
                supabase.table(HADITH_TRACK_TABLE).update({"hadith_index": index}).eq("track_date", today).execute()
            else:
                supabase.table(HADITH_TRACK_TABLE).insert({"track_date": today, "hadith_index": index}).execute()

            webhooks = all_hadith_webhooks()
            for wh in webhooks:
                send_slack_message(message, webhook_url=wh)
            return f"Hadith {index} sent to {len(webhooks)} channel(s)"

        print(f"Skipped Hadith {index}, too long ({len(message)} chars)")

    # If none fit, move index forward to avoid sending same ones repeatedly
    next_index = (last_index + 1) % total_hadith
    if res.data and len(res.data) > 0:
        supabase.table(HADITH_TRACK_TABLE).update({"hadith_index": next_index}).eq("track_date", today).execute()
    else:
        supabase.table(HADITH_TRACK_TABLE).insert({"track_date": today, "hadith_index": next_index}).execute()

    return "No Hadith fits in a single message today"

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