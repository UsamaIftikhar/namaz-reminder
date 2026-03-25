# api/namaz.py

import os
import requests
from datetime import datetime
import pytz

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK secret is not set!")

TZ = pytz.timezone("Asia/Karachi")

PRAYER_TIMES = {
    "Zohar": (13, 15),
    "Asar": (17, 0),
    "Maghrib": (18, 30),
}

TOLERANCE = 2  # minutes

# Store last sent in memory (resets per function cold start)
LAST_SENT = {}

def is_time_match(target_hour, target_minute):
    now = datetime.now(TZ)
    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_hour * 60 + target_minute
    return abs(current_minutes - target_minutes) <= TOLERANCE

def send_slack_message(message: str):
    response = requests.post(SLACK_WEBHOOK, json={"text": message})
    if response.status_code == 200:
        print(f"✅ Sent: {message}")
    else:
        print(f"❌ Failed ({response.status_code}): {response.text}")

def handler(request):
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    messages_sent = []

    for prayer, (hour, minute) in PRAYER_TIMES.items():
        key = f"{prayer}_{today}"
        if is_time_match(hour, minute) and not LAST_SENT.get(key):
            msg = f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})"
            send_slack_message(msg)
            LAST_SENT[key] = True
            messages_sent.append(prayer)

    if messages_sent:
        return {"status": "sent", "prayers": messages_sent}
    return {"status": "no match"}