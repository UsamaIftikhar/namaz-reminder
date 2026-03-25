# api/send_prayer.py
import os
import requests
from datetime import datetime
import pytz

SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK")
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
    r = requests.post(SLACK_WEBHOOK, json={"text": message})
    return r.status_code, r.text

def handler(request):
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    sent_prayers = []

    for prayer, (h, m) in PRAYER_TIMES.items():
        key = f"{prayer}_{today}"
        if is_time_match(h, m) and not LAST_SENT.get(key):
            send_slack(f":mosque: {prayer} time! ({now.strftime('%I:%M %p')})")
            LAST_SENT[key] = True
            sent_prayers.append(prayer)

    return {
        "statusCode": 200,
        "body": f"Sent prayers: {', '.join(sent_prayers)}" if sent_prayers else "No match"
    }