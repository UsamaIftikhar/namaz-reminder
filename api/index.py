# api/namaz.py
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

LAST_SENT = {}  # memory to prevent duplicate sends

def is_time_match(hour, minute):
    now = datetime.now(TZ)
    current_minutes = now.hour * 60 + now.minute
    target_minutes = hour * 60 + minute
    return abs(current_minutes - target_minutes) <= TOLERANCE

def send_slack(message):
    r = requests.post(SLACK_WEBHOOK, json={"text": message})
    if r.status_code == 200:
        print(f"✅ Sent: {message}")
    else:
        print(f"❌ Failed ({r.status_code}): {r.text}")

def handler(request):
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    sent = []

    for prayer, (h, m) in PRAYER_TIMES.items():
        key = f"{prayer}_{today}"
        if is_time_match(h, m) and not LAST_SENT.get(key):
            msg = f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})"
            send_slack(msg)
            LAST_SENT[key] = True
            sent.append(prayer)

    if sent:
        return {"status": "sent", "prayers": sent}
    return {"status": "no match"}