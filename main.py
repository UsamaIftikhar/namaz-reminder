import os
import requests
from datetime import datetime
import pytz

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK secret is not set in GitHub Actions!")

TZ = pytz.timezone("Asia/Karachi")

def send_slack_message(message: str):
    response = requests.post(SLACK_WEBHOOK, json={"text": message})
    if response.status_code == 200:
        print(f"✅ Sent: {message}")
    else:
        print(f"❌ Failed ({response.status_code}): {response.text}")

def main():
    now = datetime.now(TZ)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    send_slack_message(f"🕒 Test Slack notification at {now_str}")

if __name__ == "__main__":
    main()