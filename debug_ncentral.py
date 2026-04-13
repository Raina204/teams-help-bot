"""
Quick debug script — prints all devices returned from N-central for customer 1118.
Run: venv\Scripts\python.exe debug_ncentral.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.rmm_service import _get_headers
from config.config import CONFIG
import requests

customer_id = "1118"
url = f"{CONFIG.NABLE_BASE_URL}/api/devices"
params = {"customerId": customer_id, "pageSize": 100, "pageNumber": 1}

r = requests.get(url, headers=_get_headers(), params=params, timeout=15)
print(f"Status: {r.status_code}")

devices = r.json().get("data", [])
print(f"Total devices found: {len(devices)}\n")

for i, d in enumerate(devices):
    print(f"--- Device {i+1} ---")
    for key in ["deviceId", "longName", "lastLoggedInUser", "userName", "supportedOs"]:
        print(f"  {key}: {d.get(key)}")
    print()
