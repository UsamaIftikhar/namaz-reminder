# api/namaz_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import requests
from datetime import datetime
import pytz
from urllib.parse import urlparse

# Slack webhook
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK not set!")

# Timezone
TZ = pytz.timezone("Asia/Karachi")

# Prayer times (hour, minute)
PRAYER_TIMES = {
    "Zohar": (13, 15),
    "Asar": (17, 0),
    "Maghrib": (18, 30),
}

TOLERANCE = 2  # minutes tolerance
LAST_SENT = {}  # keeps track of sent prayers

# Check if current time is within tolerance
def is_time_match(hour, minute):
    now = datetime.now(TZ)
    current_minutes = now.hour * 60 + now.minute
    target_minutes = hour * 60 + minute
    return abs(current_minutes - target_minutes) <= TOLERANCE

# Send message to Slack
def send_slack(message):
    print(f"Sending Slack message: {message}")
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": message})
        print(f"Slack response: {r.status_code}, {r.text}")
        return r.status_code, r.text
    except Exception as e:
        print(f"Error sending Slack: {e}")
        return None, str(e)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now = datetime.now(TZ)
        today = now.strftime("%Y-%m-%d")
        sent_prayers = []

        # Debug: log incoming path
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Incoming request path: {self.path}")

        # Parse path (ignores query string)
        parsed_path = urlparse(self.path).path

        # Test Slack endpoint
        if parsed_path.endswith("/test-slack"):
            print("Test Slack endpoint called")
            status, text = send_slack(f"🕌 Test message from Vercel at {now.strftime('%I:%M %p')}")
            sent_prayers.append("Test Slack message sent")

        # Regular prayer check
        for prayer, (h, m) in PRAYER_TIMES.items():
            key = f"{prayer}_{today}"
            if is_time_match(h, m) and not LAST_SENT.get(key):
                send_slack(f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})")
                LAST_SENT[key] = True
                sent_prayers.append(prayer)

        # Respond
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        if sent_prayers:
            response_text = f"Sent: {', '.join(sent_prayers)}"
        else:
            response_text = "No match"
        print(f"Response: {response_text}")
        self.wfile.write(response_text.encode('utf-8'))
        return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Server running on port {port}...")
    server = HTTPServer(("", port), handler)
    server.serve_forever()