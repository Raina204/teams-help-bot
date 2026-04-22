import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

class ConnectWiseClient:
    def __init__(self):
        self.site = os.getenv("CW_SITE")
        self.company = os.getenv("CW_COMPANY")
        self.public_key = os.getenv("CW_PUBLIC_KEY")
        self.private_key = os.getenv("CW_PRIVATE_KEY")
        self.client_id = os.getenv("CW_CLIENT_ID")
        self.base_url = f"https://{self.site}/v4_6_release/apis/3.0"

        credentials = f"{self.company}+{self.public_key}:{self.private_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "clientId": self.client_id,
            "Content-Type": "application/json"
        }

    def get(self, endpoint, params=None):
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, payload):
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def patch(self, endpoint, operations):
        url = f"{self.base_url}{endpoint}"
        response = requests.patch(url, headers=self.headers, json=operations)
        response.raise_for_status()
        return response.json()