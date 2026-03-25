import os
import requests
from datetime import datetime
import pytz
from flask import Flask

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
# MAIN LOGIC
# -------------------------
def send_test_notifications():
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    
    prayers = ["Zohar", "Asar", "Maghrib"]

    for name in prayers:
        # REMINDER
        send_slack_message(f"⏰ 15 min left for {name} prayer (TEST CONTINUOUS)")

        # EXACT
        send_slack_message(f"🕌 Time for {name} prayer! (TEST CONTINUOUS)")

    print(f"{datetime.now(TZ)} - Cron ran successfully.")

# -------------------------
# FLASK APP TO KEEP SERVICE ALIVE
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Namaz Reminder Service is alive!", 200

@app.route("/run-cron")
def run_cron():
    send_test_notifications()
    return "Test notifications sent!", 200

# -------------------------
# ENTRY POINT
# -------------------------
if __name__ == "__main__":
    # Run Flask web server to keep service alive
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))