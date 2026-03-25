# api/namaz_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import requests
from datetime import datetime
import pytz

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK not set!")

TZ = pytz.timezone("Asia/Karachi")

PRAYER_TIMES = {
    "Zohar": (13, 15),
    "Asar": (17, 0),
    "Maghrib": (18, 30),
}

TOLERANCE = 2  # minutes
LAST_SENT = {}

def is_time_match(hour, minute):
    now = datetime.now(TZ)
    current_minutes = now.hour * 60 + now.minute
    target_minutes = hour * 60 + minute
    return abs(current_minutes - target_minutes) <= TOLERANCE

def send_slack(message):
    print(f"Sending Slack message: {message}")
    r = requests.post(SLACK_WEBHOOK, json={"text": message})
    print(f"Slack response: {r.status_code}, {r.text}")
    return r.status_code, r.text

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        now = datetime.now(TZ)
        today = now.strftime("%Y-%m-%d")
        sent_prayers = []

        # Regular prayer check
        for prayer, (h, m) in PRAYER_TIMES.items():
            key = f"{prayer}_{today}"
            if is_time_match(h, m) and not LAST_SENT.get(key):
                send_slack(f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})")
                LAST_SENT[key] = True
                sent_prayers.append(prayer)

        # Test endpoint: /test-slack
        if path == "/test-slack":
            print(f"test slack calling")
            status, text = send_slack(f"🕌 Test message from Vercel at {now.strftime('%I:%M %p')}")
            sent_prayers.append("Test Slack message sent")

        # Respond
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        if sent_prayers:
            self.wfile.write(f"Sent: {', '.join(sent_prayers)}".encode('utf-8'))
        else:
            self.wfile.write(b"No match")
        return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("", port), handler)
    print(f"Server running on port {port}...")
    server.serve_forever()