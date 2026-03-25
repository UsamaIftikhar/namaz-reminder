import os
import requests
from datetime import datetime, timedelta
import pytz
from flask import Flask
import threading
import time

# -------------------------
# CONFIG
# -------------------------
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK environment variable not set!")

TZ = pytz.timezone("Asia/Karachi")

# -------------------------
# HELPER
# -------------------------
def send_slack_message(message):
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message})
        print(f"{datetime.now(TZ)} - Sent: {message}")
    except Exception as e:
        print(f"{datetime.now(TZ)} - Error sending Slack message: {e}")

# -------------------------
# TEST NAMAZ LOGIC
# -------------------------
LAST_SENT = set()

def send_test_notifications():
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    prayers = ["Zohar", "Asar", "Maghrib"]

    for name in prayers:
        reminder_key = f"{name}-reminder-{now.minute}"  # minute added to allow repeated messages for testing
        prayer_key = f"{name}-prayer-{now.minute}"

        # REMINDER
        if reminder_key not in LAST_SENT:
            send_slack_message(f"⏰ 15 min left for {name} prayer (TEST)")
            LAST_SENT.add(reminder_key)

        # EXACT TIME
        if prayer_key not in LAST_SENT:
            send_slack_message(f"🕌 Time for {name} prayer! (TEST)")
            LAST_SENT.add(prayer_key)

    print(f"{datetime.now(TZ)} - Test notifications sent.")

# -------------------------
# BACKGROUND THREAD TO RUN EVERY 1 MINUTE FOR TESTING
# -------------------------
def background_test_checker():
    while True:
        send_test_notifications()
        time.sleep(300)  # check every 1 minute for testing

# -------------------------
# FLASK WEB SERVICE
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Namaz Reminder Test Service is alive!", 200

@app.route("/run-cron")
def run_cron():
    send_test_notifications()
    return "Test notifications sent!", 200

# -------------------------
# ENTRY POINT
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=background_test_checker, daemon=True).start()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)