import httpx
import pytest
import asyncio

BASE_URL = "http://localhost:3978"

# ── Test 1: Health check ──────────────────────────────────────────
def test_bot_server_is_running():
    response = httpx.get(f"{BASE_URL}/")
    assert response.status_code == 200, "Bot server is not running"
    print("\n  Bot server is UP on localhost:3978")

# ── Test 2: Messaging endpoint accepts POST ───────────────────────
def test_messaging_endpoint_exists():
    payload = {
        "type": "message",
        "id": "test-activity-001",
        "channelId": "emulator",
        "from": {"id": "user1", "name": "Test User"},
        "conversation": {"id": "conv1"},
        "recipient": {"id": "bot1"},
        "text": "hello",
        "serviceUrl": "http://localhost:50765"
    }
    response = httpx.post(
        f"{BASE_URL}/api/messages",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15.0
    )
    # 200, 201, or 202 = endpoint is alive and accepted the message
    assert response.status_code in [200, 201, 202], \
        f"Messaging endpoint failed: {response.status_code} - {response.text}"
    print(f"\n  Messaging endpoint OK — status {response.status_code}")

# ── Test 3: MCP endpoint is reachable ────────────────────────────
def test_mcp_endpoint_exists():
    response = httpx.get(f"{BASE_URL}/mcp")
    assert response.status_code in [200, 405], \
        "MCP endpoint not found"
    print("\n  MCP endpoint is reachable")