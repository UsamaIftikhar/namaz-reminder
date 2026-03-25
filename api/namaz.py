# api/namaz.py

import os
import requests
from datetime import datetime
import pytz

from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Hello"

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

# Memory to prevent duplicates during cold starts
LAST_SENT = {}

def is_time_match(target_hour, target_minute):
    now = datetime.now(TZ)
    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_hour * 60 + target_minute
    return abs(current_minutes - target_minutes) <= TOLERANCE

def send_slack(message):
    response = requests.post(SLACK_WEBHOOK, json={"text": message})
    if response.status_code == 200:
        print(f"✅ Sent: {message}")
    else:
        print(f"❌ Failed ({response.status_code}): {response.text}")

# This is the Vercel entrypoint
def handler(request):
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    sent_prayers = []

    for prayer, (h, m) in PRAYER_TIMES.items():
        key = f"{prayer}_{today}"
        if is_time_match(h, m) and not LAST_SENT.get(key):
            msg = f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})"
            send_slack(msg)
            LAST_SENT[key] = True
            sent_prayers.append(prayer)

    if sent_prayers:
        return {"status": "sent", "prayers": sent_prayers}
    return {"status": "no match"}