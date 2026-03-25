# api/namaz_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import requests
from datetime import datetime, timedelta
import pytz
from urllib.parse import urlparse
import json

# -------------------------
# CONFIG
# -------------------------
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK not set!")

HADITH_API_KEY = os.getenv("HADITH_API_KEY")  # store your API key in env
HADITH_API_URL = f"https://hadithapi.com/api/hadiths?apiKey={HADITH_API_KEY}&book=sahih-bukhari"

CITY_LAT = 31.4313584
CITY_LON = 74.2782463
TZ = pytz.timezone("Asia/Karachi")

WINDOW_MINUTES = 5
LAST_SENT = {}
HADITH_TRACK_FILE = "last_hadith.json"

# Load persisted hadith tracking
if os.path.exists(HADITH_TRACK_FILE):
    with open(HADITH_TRACK_FILE, "r") as f:
        HADITH_TRACK = json.load(f)
else:
    HADITH_TRACK = {}

# -------------------------
# HELPERS
# -------------------------
def send_slack_message(message):
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": message})
        print(f"Sent: {message[:50]}..., Slack response: {r.status_code}")
        return True
    except Exception as e:
        print(f"Error sending Slack: {e}")
        return False


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
        return data["hadiths"]["data"]
    except Exception as e:
        print(f"Error fetching hadiths: {e}")
        return []


def get_next_hadith_index(hadith_list):
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    last_index = HADITH_TRACK.get(today_str, -1)
    index = (last_index + 1) % len(hadith_list)
    HADITH_TRACK[today_str] = index
    # Persist to file
    with open(HADITH_TRACK_FILE, "w") as f:
        json.dump(HADITH_TRACK, f)
    return index


def get_daily_hadith():
    hadith_list = fetch_hadiths()
    if not hadith_list:
        return None
    index = get_next_hadith_index(hadith_list)
    return hadith_list[index]


def send_hadith():
    hadith = get_daily_hadith()
    if not hadith:
        return "No Hadith available"

    message = (
        ":crescent_moon: *Daily Hadith Reminder* :crescent_moon:\n\n"
        f"*Arabic:* \n{hadith['hadithArabic']}\n\n"
        f"*English:* \n{hadith['hadithEnglish']}\n\n"
        f"*Urdu:* \n{hadith.get('hadithUrdu', 'N/A')}\n\n"
        f"— Narrated by: {hadith['englishNarrator']} \n {hadith.get('urduNarrator', 'N/A')}\n\n"
        f":book: Source: Sahih Bukhari, Chapter: {hadith['headingEnglish']}"
    )

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

        # Debug log incoming path
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Incoming request path: {self.path}")
        parsed_path = urlparse(self.path).path

        # -------------------------
        # Test Slack endpoint
        # -------------------------
        if parsed_path.endswith("/test-slack"):
            print("Test Slack endpoint called")
            send_slack_message(f"🕌 Test message from Vercel at {now.strftime('%I:%M %p')}")
            sent_messages.append("Test Slack message sent")

            # Send a hadith for testing every minute
            hadith_msg = send_hadith()
            sent_messages.append(hadith_msg)

        # -------------------------
        # Prayer times logic
        # -------------------------
        timings = get_prayer_times()
        if timings:
            zohar_time = now.replace(hour=13, minute=40)
            asar_api = datetime.strptime(timings.get("Asr", "17:00"), "%H:%M")
            asar_api = now.replace(hour=asar_api.hour, minute=asar_api.minute)
            asar_time = round_asar_time(asar_api) + timedelta(minutes=45)
            maghrib_api = datetime.strptime(timings.get("Maghrib", "18:30"), "%H:%M")
            maghrib_time = now.replace(hour=maghrib_api.hour, minute=maghrib_api.minute) + timedelta(minutes=5)

            prayers = {
                "Zohar": zohar_time,
                "Asar": asar_time,
                "Maghrib": maghrib_time
            }

            for name, prayer_time in prayers.items():
                reminder_time = prayer_time - timedelta(minutes=15)
                prayer_key = f"{name}-{today_str}-prayer"
                reminder_key = f"{name}-{today_str}-reminder"

                if is_within_range(now, reminder_time) and not LAST_SENT.get(reminder_key):
                    if send_slack_message(f"⏰ 15 min left for {name} prayer"):
                        LAST_SENT[reminder_key] = True
                        sent_messages.append(f"{name} reminder sent")

                if is_within_range(now, prayer_time) and not LAST_SENT.get(prayer_key):
                    if send_slack_message(f"🕌 Time for {name} prayer!"):
                        LAST_SENT[prayer_key] = True
                        sent_messages.append(f"{name} prayer sent")

        # -------------------------
        # Daily Hadith at 10 AM
        # -------------------------
        hadith_key = f"hadith-{today_str}"
        hadith_time = now.replace(hour=10, minute=0)
        if is_within_range(now, hadith_time) and not LAST_SENT.get(hadith_key):
            msg = send_hadith()
            LAST_SENT[hadith_key] = True
            sent_messages.append(msg)

        # -------------------------
        # Respond
        # -------------------------
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        if sent_messages:
            response_text = f"Sent: {', '.join(sent_messages)}"
        else:
            response_text = "No match"
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