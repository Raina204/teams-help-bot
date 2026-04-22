# check_nable_scripts.py
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("NABLE_BASE_URL", "ncod494.n-able.com")
API_KEY  = os.environ.get("NABLE_API_KEY", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJTb2xhcndpbmRzIE1TUCBOLWNlbnRyYWwiLCJ1c2VyaWQiOjE4NTM0MjUyMTIsImlhdCI6MTc2NzYyNTcyOH0.pOAvvrKYShWxDGw6IiFJj-OS51Z4RMEAoCwWuVW3l9k")


def try_auth_methods() -> tuple[dict, str]:
    """
    Tries all known N-able authentication methods.
    Returns (headers, method_name) for the one that works.
    """
    auth_attempts = [
        # Method 1 — Bearer token (newer N-able versions)
        {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
        # Method 2 — API key in custom header
        {
            "X-API-Key":    API_KEY,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        # Method 3 — API key as token
        {
            "Authorization": f"Token {API_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
        # Method 4 — Basic auth with API key as password
        {
            "Authorization": f"Basic {API_KEY}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    ]

    method_names = [
        "Bearer token",
        "X-API-Key header",
        "Token auth",
        "Basic auth",
    ]

    # Test each auth method against the scheduled-tasks endpoint
    # since we know it exists (returned 401 not 404)
    test_url = f"{BASE_URL}/api/scheduled-tasks"

    for headers, name in zip(auth_attempts, method_names):
        try:
            print(f"  Trying auth method: {name}")
            resp = requests.get(test_url, headers=headers, timeout=10)
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                print(f"  SUCCESS — {name} works")
                return headers, name
            elif resp.status_code == 401:
                print(f"  FAILED — unauthorized")
            elif resp.status_code == 403:
                print(f"  FAILED — forbidden")
        except Exception as exc:
            print(f"  ERROR: {exc}")

    return {}, ""


def get_jwt_token() -> str:
    """
    Some N-able versions require a JWT login first.
    Tries the N-able token endpoint using the API key.
    """
    token_endpoints = [
        f"{BASE_URL}/api/auth/token",
        f"{BASE_URL}/api/authenticate",
        f"{BASE_URL}/api/login",
        f"{BASE_URL}/api/v1/auth",
        f"{BASE_URL}/api/auth",
    ]

    for endpoint in token_endpoints:
        try:
            print(f"\n  Trying token endpoint: {endpoint}")

            # Try POST with API key in body
            resp = requests.post(
                endpoint,
                json    = {"apiKey": API_KEY},
                headers = {"Content-Type": "application/json"},
                timeout = 10,
            )
            print(f"  Status: {resp.status_code}")

            if resp.status_code == 200:
                data  = resp.json()
                token = (
                    data.get("token")
                    or data.get("access_token")
                    or data.get("jwt")
                    or data.get("accessToken")
                )
                if token:
                    print(f"  JWT token obtained successfully")
                    return token

            # Try GET with API key as query param
            resp2 = requests.get(
                endpoint,
                params  = {"apiKey": API_KEY},
                headers = {"Content-Type": "application/json"},
                timeout = 10,
            )
            if resp2.status_code == 200:
                data  = resp2.json()
                token = (
                    data.get("token")
                    or data.get("access_token")
                    or data.get("jwt")
                )
                if token:
                    print(f"  JWT token obtained via GET")
                    return token

        except Exception as exc:
            print(f"  ERROR: {exc}")

    return ""


def fetch_scripts_with_headers(headers: dict) -> list:
    """
    Fetches scripts using confirmed working headers.
    """
    endpoints = [
        f"{BASE_URL}/api/scheduled-tasks",
        f"{BASE_URL}/api/scheduled-tasks?pageSize=100",
        f"{BASE_URL}/api/scheduled-tasks/direct",
        f"{BASE_URL}/api/automation-policies",
        f"{BASE_URL}/api/scripts",
    ]

    for endpoint in endpoints:
        try:
            print(f"\n  Fetching scripts from: {endpoint}")
            resp = requests.get(endpoint, headers=headers, timeout=15)
            print(f"  Status: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                print(f"  Raw response type: {type(data).__name__}")

                if isinstance(data, list) and data:
                    print(f"  Found {len(data)} items")
                    return data

                if isinstance(data, dict):
                    print(f"  Response keys: {list(data.keys())}")
                    for key in ("data", "scripts", "items", "results",
                                "tasks", "policies", "automationPolicies"):
                        if key in data and isinstance(data[key], list):
                            print(f"  Found {len(data[key])} items under '{key}'")
                            return data[key]

                    # Save raw response for inspection
                    with open("raw_response.json", "w") as f:
                        json.dump(data, f, indent=2)
                    print("  Raw response saved to raw_response.json")

        except Exception as exc:
            print(f"  ERROR: {exc}")

    return []


def display_scripts(scripts: list) -> None:
    """Prints all found scripts with their IDs."""
    print(f"\n{'=' * 60}")
    print(f"ALL SCRIPTS ({len(scripts)} found)")
    print(f"{'=' * 60}")

    for i, script in enumerate(scripts, 1):
        script_id = (
            script.get("id")
            or script.get("scriptId")
            or script.get("taskItemId")
            or script.get("automationPolicyId")
            or script.get("taskId")
            or "N/A"
        )
        name = (
            script.get("name")
            or script.get("scriptName")
            or script.get("taskName")
            or script.get("policyName")
            or "Unnamed"
        )
        print(f"\n  [{i:>2}]  ID   : {script_id}")
        print(f"         Name : {name}")

    # Generate .env suggestions
    print(f"\n{'=' * 60}")
    print("COPY THESE INTO YOUR .env FILE")
    print(f"{'=' * 60}\n")

    keyword_map = {
        "NABLE_SCRIPT_MEMORY":          ["memory", "mem", "ram"],
        "NABLE_SCRIPT_CPU":             ["cpu", "processor"],
        "NABLE_SCRIPT_STORAGE":         ["storage", "disk", "drive"],
        "NABLE_SCRIPT_OUTLOOK_RESET":   ["outlook", "reset", "refresh"],
        "NABLE_SCRIPT_TIMEZONE_CHANGE": ["timezone", "time zone", "tz"],
    }

    found_any = False
    for env_var, keywords in keyword_map.items():
        for script in scripts:
            name = (
                script.get("name")
                or script.get("taskName")
                or ""
            ).lower()
            if any(kw in name for kw in keywords):
                script_id = (
                    script.get("id")
                    or script.get("scriptId")
                    or script.get("taskItemId")
                    or script.get("taskId")
                )
                print(f"{env_var}={script_id}")
                found_any = True
                break

    if not found_any:
        print("Could not auto-match scripts by name.")
        print("Look at the list above and add the IDs manually.")


def main():
    print("=" * 60)
    print("N-ABLE SCRIPT CHECKER")
    print("=" * 60)
    print(f"\nBase URL : {BASE_URL}")
    print(f"API Key  : {API_KEY[:8]}{'*' * max(0, len(API_KEY) - 8)}")

    if not BASE_URL or not API_KEY:
        print("\nERROR: NABLE_BASE_URL or NABLE_API_KEY missing from .env")
        return

    # Step 1 — Try all auth methods
    print(f"\n{'-' * 60}")
    print("STEP 1: Testing authentication methods")
    print(f"{'-' * 60}")

    working_headers, method = try_auth_methods()

    # Step 2 — If no auth method worked, try JWT login
    if not working_headers:
        print(f"\n{'-' * 60}")
        print("STEP 2: Trying JWT token authentication")
        print(f"{'-' * 60}")

        jwt_token = get_jwt_token()
        if jwt_token:
            working_headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            }
            method = "JWT token"
        else:
            print("\nAll authentication methods failed.")
            print("\nNext steps:")
            print("  1. Check your NABLE_API_KEY is correct in .env")
            print("  2. In N-able go to:")
            print("     Administration → User Management → your user → API Access")
            print("     Generate a new API key and update your .env")
            print("  3. Make sure your user has 'Automation Policy' read permissions")
            return

    # Step 3 — Fetch scripts with working auth
    print(f"\n{'-' * 60}")
    print(f"STEP 3: Fetching scripts using {method}")
    print(f"{'-' * 60}")

    scripts = fetch_scripts_with_headers(working_headers)

    if not scripts:
        print("\nNo scripts returned.")
        print("Check raw_response.json if it was created.")
        print("\nShare the raw_response.json contents and")
        print("I will identify the correct field names for your N-able version.")
        return

    # Step 4 — Display and save results
    display_scripts(scripts)

    with open("nable_scripts_dump.json", "w") as f:
        json.dump(scripts, f, indent=2)
    print(f"\nFull list saved to: nable_scripts_dump.json")


if __name__ == "__main__":
    main()