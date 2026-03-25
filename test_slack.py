import os
import requests

# Get the webhook URL from environment variable (set in Railway)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")

# Test message
message = "✅ Namaz Bot Test Message!"

# Send the message
response = requests.post(SLACK_WEBHOOK, json={"text": message})

# Print result
if response.status_code == 200:
    print("Test message sent successfully!")
else:
    print("Failed to send message:", response.text)