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

HADITH_API_KEY = os.getenv("HADITH_API_KEY")
if not HADITH_API_KEY:
    raise ValueError("HADITH_API_KEY not set!")

HADITH_API_URL = f"https://hadithapi.com/api/hadiths?apiKey={HADITH_API_KEY}&book=sahih-bukhari"

CITY_LAT = 31.4313584
CITY_LON = 74.2782463
TZ = pytz.timezone("Asia/Karachi")

WINDOW_MINUTES = 5
LAST_SENT = {}

# Slack chunk size (safe)
SLACK_CHUNK_SIZE = 3500

# -------------------------
# SUPABASE CLIENT
# -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not set!")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# SLACK MESSAGE SPLITTER
# -------------------------
def split_message_safely(message, max_length):
    """Split message without breaking words or paragraphs"""
    chunks = []

    while len(message) > max_length:
        # Prefer paragraph split
        split_index = message.rfind("\n", 0, max_length)

        # If no newline, split by space
        if split_index == -1:
            split_index = message.rfind(" ", 0, max_length)

        # If still nothing, force split
        if split_index == -1:
            split_index = max_length

        chunks.append(message[:split_index])
        message = message[split_index:].lstrip()

    if message:
        chunks.append(message)

    return chunks


def send_slack_message(message):
    """Send message safely to Slack"""
    try:
        chunks = split_message_safely(message, SLACK_CHUNK_SIZE)

        for i, chunk in enumerate(chunks):
            r = requests.post(SLACK_WEBHOOK, json={"text": chunk})
            print(f"Sent chunk {i+1}/{len(chunks)} | Status: {r.status_code}")

    except Exception as e:
        print(f"Error sending Slack: {e}")

# -------------------------
# HELPERS
# -------------------------
def is_within_range(now, target):
    return target <= now < (target + timedelta(minutes=WINDOW_MINUTES))


def round_asar_time(dt):
    minute = dt.minute
    if minute <= 30:
        return dt.replace(minute=30, second=0, microsecond=0)
    else:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def get_prayer_times():
    today = datetime.utcnow().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timings/{today}?latitude={CITY_LAT}&longitude={CITY_LON}&method=3"
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


def get_next_hadith_index(hadith_list):
    today = date.today().isoformat()

    res = supabase.table("daily_hadith_track").select("*").eq("track_date", today).execute()

    if res.data:
        row = res.data[0]
        index = row["hadith_index"]
        new_index = (index + 1) % len(hadith_list)

        supabase.table("daily_hadith_track") \
            .update({"hadith_index": new_index}) \
            .eq("track_date", today) \
            .execute()
    else:
        res_last = supabase.table("daily_hadith_track") \
            .select("hadith_index") \
            .order("track_date", desc=True) \
            .limit(1) \
            .execute()

        last_index = res_last.data[0]["hadith_index"] if res_last.data else -1
        index = (last_index + 1) % len(hadith_list)

        supabase.table("daily_hadith_track") \
            .insert({"track_date": today, "hadith_index": index}) \
            .execute()

    return index


def get_daily_hadith():
    hadith_list = fetch_hadiths()
    if not hadith_list:
        return None
    index = get_next_hadith_index(hadith_list)
    return hadith_list[index]


def format_hadith_message(hadith):
    arabic = hadith.get("hadithArabic", "N/A")
    english = hadith.get("hadithEnglish", "N/A")
    urdu = hadith.get("hadithUrdu", "N/A")
    eng_narrator = hadith.get("englishNarrator", "Unknown")
    urdu_narrator = hadith.get("urduNarrator", "N/A")
    hadith_number = hadith.get("hadithNumber", "N/A")
    chapter = hadith.get("headingEnglish") or hadith.get("chapter", {}).get("chapterEnglish", "N/A")

    return (
        f":crescent_moon: *Daily Hadith Reminder* :crescent_moon:\n\n"
        f"*Arabic:*\n{arabic}\n\n"
        f"*English:*\n{english}\n\n"
        f"*Urdu:*\n{urdu}\n\n"
        f"— Narrated by: {eng_narrator} / {urdu_narrator}\n\n"
        f":book: Source: Sahih Bukhari, Hadith Number: {hadith_number}, Chapter: {chapter}"
    )

def send_hadith():
    hadith = get_daily_hadith()
    if not hadith:
        return "No Hadith available"

    message = format_hadith_message(hadith)
    send_slack_message(message)
    return "Hadith sent"

# -------------------------
# HANDLER
# -------------------------
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now = datetime.now(TZ).replace(second=0, microsecond=0)
        today_str = now.strftime("%Y-%m-%d")
        sent_messages = []

        parsed_path = urlparse(self.path).path

        # Test endpoint
        if parsed_path.endswith("/test-slack"):
            send_slack_message(f"🕌 Test message at {now.strftime('%I:%M %p')}")
            sent_messages.append("Test message")
            sent_messages.append(send_hadith())

        # Prayer times
        timings = get_prayer_times()
        if timings:
            zohar_time = now.replace(hour=13, minute=40)

            asr_api = datetime.strptime(timings.get("Asr", "17:00"), "%H:%M")
            asar_time = round_asar_time(now.replace(hour=asr_api.hour, minute=asr_api.minute)) + timedelta(minutes=45)

            maghrib_api = datetime.strptime(timings.get("Maghrib", "18:30"), "%H:%M")
            maghrib_time = now.replace(hour=maghrib_api.hour, minute=maghrib_api.minute) + timedelta(minutes=5)

            prayers = {"Zohar": zohar_time, "Asar": asar_time, "Maghrib": maghrib_time}

            for name, prayer_time in prayers.items():
                reminder_time = prayer_time - timedelta(minutes=15)

                if is_within_range(now, reminder_time):
                    send_slack_message(f"⏰ 15 min left for {name} prayer")

                if is_within_range(now, prayer_time):
                    send_slack_message(f"🕌 Time for {name} prayer!")

        # Daily Hadith at 10 AM
        hadith_time = now.replace(hour=10, minute=0)
        if is_within_range(now, hadith_time):
            sent_messages.append(send_hadith())

        # Response
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

# -------------------------
# SERVER ENTRY
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    HTTPServer(("", port), handler).serve_forever()