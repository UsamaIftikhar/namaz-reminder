import os
import requests
import schedule
import time
from datetime import datetime

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")  # <-- will set this in Railway

CITY_LAT = 31.4313584
CITY_LON = 74.2782463
PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

def get_prayer_times():
    today = datetime.utcnow().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timings/{today}?latitude={CITY_LAT}&longitude={CITY_LON}&method=3&shafaq=general&timezonestring=UTC"
    data = requests.get(url).json()
    timings = data["data"]["timings"]
    return {p: timings[p] for p in PRAYERS}

def send_slack_message(message):
    requests.post(SLACK_WEBHOOK, json={"text": message})

def schedule_prayers():
    timings = get_prayer_times()
    for prayer, time_str in timings.items():
        hour, minute = map(int, time_str.split(":"))
        schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(
            lambda p=prayer: send_slack_message(f"Time for {p} prayer!")
        )

# Reschedule prayers every day at 00:01 UTC
schedule.every().day.at("00:01").do(schedule_prayers)

schedule_prayers()  # initial schedule

while True:
    schedule.run_pending()
    time.sleep(30)