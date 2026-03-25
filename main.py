import os
import requests
from datetime import datetime, timedelta
import pytz

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")

CITY_LAT = 31.4313584
CITY_LON = 74.2782463

TZ = pytz.timezone("Asia/Karachi")

LAST_SENT_FILE = "last_sent.txt"


# -------------------------
# HELPERS
# -------------------------
def send_slack_message(message):
    requests.post(SLACK_WEBHOOK, json={"text": message})
    print("Sent:", message)


def already_sent(key):
    if not os.path.exists(LAST_SENT_FILE):
        return False
    with open(LAST_SENT_FILE, "r") as f:
        lines = f.read().splitlines()
    return key in lines


def mark_sent(key):
    with open(LAST_SENT_FILE, "a") as f:
        f.write(key + "\n")


def is_within_range(now, target):
    return target <= now < (target + timedelta(minutes=5))


def round_asar_time(dt):
    minute = dt.minute

    if minute <= 30:
        return dt.replace(minute=30, second=0)
    else:
        return dt.replace(minute=0, second=0) + timedelta(hours=1)


# -------------------------
# FETCH PRAYER TIMES
# -------------------------
def get_prayer_times():
    today = datetime.utcnow().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timings/{today}?latitude={CITY_LAT}&longitude={CITY_LON}&method=3"
    data = requests.get(url).json()
    return data["data"]["timings"]


# -------------------------
# MAIN LOGIC
# -------------------------
def main():
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    today_str = now.strftime("%Y-%m-%d")

    timings = get_prayer_times()

    # --- ZOHAR (FIXED) ---
    zohar_time = now.replace(hour=13, minute=40)

    # --- ASAR ---
    asar_api = datetime.strptime(timings["Asr"], "%H:%M")
    asar_api = now.replace(hour=asar_api.hour, minute=asar_api.minute)

    asar_rounded = round_asar_time(asar_api)
    asar_time = asar_rounded + timedelta(minutes=45)

    # --- MAGHRIB ---
    maghrib_api = datetime.strptime(timings["Maghrib"], "%H:%M")
    maghrib_api = now.replace(hour=maghrib_api.hour, minute=maghrib_api.minute)

    maghrib_time = maghrib_api + timedelta(minutes=5)

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
        if is_within_range(now, reminder_time) and not already_sent(reminder_key):
            send_slack_message(f"⏰ 15 min left for {name} prayer")
            mark_sent(reminder_key)

        # EXACT
        if is_within_range(now, prayer_time) and not already_sent(prayer_key):
            send_slack_message(f"🕌 Time for {name} prayer!")
            mark_sent(prayer_key)


if __name__ == "__main__":
    main()