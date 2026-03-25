import os
import requests
from datetime import datetime
import pytz

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
def main():
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    
    # For testing: trigger all prayers immediately
    prayers = ["Zohar", "Asar", "Maghrib"]

    for name in prayers:
        # REMINDER
        send_slack_message(f"⏰ 15 min left for {name} prayer (TEST CONTINUOUS)")
        
        # EXACT
        send_slack_message(f"🕌 Time for {name} prayer! (TEST CONTINUOUS)")

    # Log cron run
    print(f"{datetime.now(TZ)} - Cron ran successfully.")

# -------------------------
# ENTRY POINT
# -------------------------
if __name__ == "__main__":
    main()