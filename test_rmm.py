from services.rmm_service import (
    run_diagnostics,
    reset_outlook,
    find_device_by_user,
    _is_live_mode
)

print("=" * 55)
print("  RMM Service Test")
print("=" * 55)
mode = "LIVE — ConnectWise Automate" if _is_live_mode() else "MOCK — Simulated data"
print(f"  Mode: {mode}")
print("=" * 55)
print("")

# ── Test 1 — Find device ───────────────────────────────────
print("TEST 1 — Find device by username")
try:
    device = find_device_by_user("aarav.raina")
    print(f"  PASSED")
    print(f"  Device:  {device['ComputerName']}")
    print(f"  OS:      {device['OS']}")
    print(f"  User:    {device['UserName']}")
    if device.get("_mock"):
        print(f"  Mode:    Mock (simulated)")
except Exception as e:
    print(f"  FAILED — {str(e)}")
print("")

# ── Test 2 — Run diagnostics ───────────────────────────────
print("TEST 2 — Run diagnostics")
try:
    results = run_diagnostics("Aarav Raina", "aarav.raina@itbd.net")
    m = results["memory"]
    c = results["cpu"]
    s = results["storage"][0]

    mem_icon  = "🔴" if m["usedPercent"] > 85 else "🟡" if m["usedPercent"] > 60 else "🟢"
    cpu_icon  = "🔴" if c["loadPercent"] > 85 else "🟡" if c["loadPercent"] > 60 else "🟢"
    disk_icon = "🔴" if s["usedPercent"] > 90 else "🟡" if s["usedPercent"] > 75 else "🟢"

    print(f"  PASSED")
    print(f"  Device:    {results['device']['name']} ({results['device']['os']})")
    print(f"  {mem_icon} Memory:  {m['usedPercent']}% used ({m['usedGB']} GB / {m['totalGB']} GB)")
    print(f"  {cpu_icon} CPU:     {c['loadPercent']}% load")
    print(f"  {disk_icon} Drive C: {s['usedPercent']}% used ({s['freeGB']} GB free)")
    print("")
    print("  This is exactly what the user sees in Teams:")
    print(f"  ─────────────────────────────────────────")
    print(f"  📊 Diagnostic results for {results['device']['name']}")
    print(f"  {mem_icon} Memory: {m['usedPercent']}% used ({m['usedGB']} GB / {m['totalGB']} GB)")
    print(f"  {cpu_icon} CPU: {c['loadPercent']}% load")
    print(f"  {disk_icon} Drive C: {s['usedPercent']}% used ({s['freeGB']} GB free)")
    print(f"  🖥️  OS: {results['device']['os']}")
    print(f"  ─────────────────────────────────────────")
except Exception as e:
    print(f"  FAILED — {str(e)}")
print("")

# ── Test 3 — Outlook reset ─────────────────────────────────
print("TEST 3 — Outlook reset")
try:
    result = reset_outlook("Aarav Raina", "aarav.raina@itbd.net")
    print(f"  PASSED")
    print(f"  Device:  {result['device']}")
    print(f"  Message: {result['message']}")
    if result.get("_mock"):
        print(f"  Mode:    Mock (simulated)")
except Exception as e:
    print(f"  FAILED — {str(e)}")
print("")

# ── Summary ────────────────────────────────────────────────
print("=" * 55)
print("  ALL RMM TESTS COMPLETE")
print("")
if not _is_live_mode():
    print("  Running in MOCK mode.")
    print("  To switch to live ConnectWise Automate,")
    print("  add these 3 lines to your .env file:")
    print("")
    print("  RMM_BASE_URL=https://yourcompany.hostedrmm.com")
    print("  RMM_USERNAME=TeamsBotAPI")
    print("  RMM_PASSWORD=yourpassword")
    print("")
    print("  Then add the 4 script IDs:")
    print("  RMM_SCRIPT_MEMORY=100")
    print("  RMM_SCRIPT_CPU=101")
    print("  RMM_SCRIPT_STORAGE=102")
    print("  RMM_SCRIPT_OUTLOOK_RESET=103")
    print("")
    print("  Restart the bot — live mode activates instantly.")
else:
    print("  Running in LIVE mode against ConnectWise Automate.")
print("=" * 55)