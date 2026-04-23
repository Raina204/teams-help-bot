import requests
import os
from dotenv import load_dotenv

load_dotenv()

NABLE_BASE_URL = os.getenv("NABLE_BASE_URL")
NABLE_API_KEY  = os.getenv("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJTb2xhcndpbmRzIE1TUCBOLWNlbnRyYWwiLCJ1c2VyaWQiOjE4NTM0MjUyMTIsImlhdCI6MTc2NzYyNTcyOH0.pOAvvrKYShWxDGw6IiFJj-OS51Z4RMEAoCwWuVW3l9k")

headers = {
    "Authorization": f"Bearer {NABLE_API_KEY}",
    "Accept":        "application/json"
}

response = requests.get(
    f"{NABLE_BASE_URL}/api/scheduled-tasks/script-items",
    headers=headers
)

print(f"Status: {response.status_code}")

if response.ok:
    scripts = response.json()
    for script in scripts.get("data", scripts):
        print(f"ID: {script.get('id')} | Name: {script.get('name')}")
else:
    print(response.text)