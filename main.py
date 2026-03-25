import os
import requests
from datetime import datetime
import pytz

# Get Slack webhook from environment
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")

TZ = pytz.timezone("Asia/Karachi")
now = datetime.now(TZ)

def send_slack_message(message):
    """Send message to Slack webhook"""
    response = requests.post(SLACK_WEBHOOK, json={"text": message})
    if response.status_code == 200:
        print(f"✅ Sent: {message}")
    else:
        print(f"❌ Failed ({response.status_code}): {message}")

def main():
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    send_slack_message(f"🕒 Test Slack notification at {now_str}")

if __name__ == "__main__":
    main()