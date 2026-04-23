from __future__ import annotations

IANA_TO_WINDOWS: dict[str, str] = {
    "America/New_York":    "Eastern Standard Time",
    "America/Chicago":     "Central Standard Time",
    "America/Denver":      "Mountain Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "Europe/London":       "GMT Standard Time",
    "Europe/Paris":        "W. Europe Standard Time",
    "Asia/Tokyo":          "Tokyo Standard Time",
    "Asia/Kolkata":        "India Standard Time",
    "Asia/Dubai":          "Arabian Standard Time",
    "Asia/Singapore":      "Singapore Standard Time",
    "Asia/Karachi":        "Pakistan Standard Time",
    "Australia/Sydney":    "AUS Eastern Standard Time",
    "UTC":                 "UTC",
}


def get_timezone_command(iana_timezone: str, os_type: str) -> dict:
    """Return the shell command to set a timezone for the given OS."""
    os_lower = os_type.lower()

    if os_lower == "windows":
        windows_tz = IANA_TO_WINDOWS.get(iana_timezone)
        if not windows_tz:
            return {"error": f"No Windows timezone mapping found for '{iana_timezone}'."}
        return {
            "command": f'tzutil /s "{windows_tz}"',
            "label":   windows_tz,
            "note":    "Run as Administrator in PowerShell or Command Prompt.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    if os_lower == "macos":
        return {
            "command": f'sudo systemsetup -settimezone "{iana_timezone}"',
            "label":   iana_timezone,
            "note":    "Run in Terminal.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    if os_lower == "linux":
        return {
            "command": f'sudo timedatectl set-timezone "{iana_timezone}"',
            "label":   iana_timezone,
            "note":    "Run in Terminal.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    return {"error": f"Unknown OS type '{os_type}'. Expected: windows, macos, or linux."}
