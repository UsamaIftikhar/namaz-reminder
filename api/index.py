# api/namaz_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import requests
from datetime import datetime, timedelta
import pytz
from urllib.parse import urlparse

# -------------------------
# CONFIG
# -------------------------
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK not set!")

CITY_LAT = 31.4313584
CITY_LON = 74.2782463
TZ = pytz.timezone("Asia/Karachi")

# Tolerance window for reminder/exact time
WINDOW_MINUTES = 5

# Keep track of sent reminders/prayers in memory (reset if function instance restarts)
LAST_SENT = {}

# -------------------------
# HELPERS
# -------------------------
def send_slack_message(message):
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": message})
        print(f"Sent: {message}, Slack response: {r.status_code}")
        return True
    except Exception as e:
        print(f"Error sending Slack: {e}")
        return False


def is_within_range(now, target):
    """Check if `now` is within WINDOW_MINUTES of target time"""
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

        # -------------------------
        # Prayer times logic
        # -------------------------
        timings = get_prayer_times()
        if timings:
            # --- ZOHAR (fixed) ---
            zohar_time = now.replace(hour=13, minute=40)

            # --- ASAR ---
            asar_api = datetime.strptime(timings.get("Asr", "17:00"), "%H:%M")
            asar_api = now.replace(hour=asar_api.hour, minute=asar_api.minute)
            asar_time = round_asar_time(asar_api) + timedelta(minutes=45)

            # --- MAGHRIB ---
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

                # REMINDER
                if is_within_range(now, reminder_time) and not LAST_SENT.get(reminder_key):
                    if send_slack_message(f"⏰ 15 min left for {name} prayer"):
                        LAST_SENT[reminder_key] = True
                        sent_messages.append(f"{name} reminder sent")

                # EXACT PRAYER
                if is_within_range(now, prayer_time) and not LAST_SENT.get(prayer_key):
                    if send_slack_message(f"🕌 Time for {name} prayer!"):
                        LAST_SENT[prayer_key] = True
                        sent_messages.append(f"{name} prayer sent")

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