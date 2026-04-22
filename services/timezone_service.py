# services/timezone_service.py

IANA_TO_WINDOWS = {
    "America/New_York":     "Eastern Standard Time",
    "America/Chicago":      "Central Standard Time",
    "America/Denver":       "Mountain Standard Time",
    "America/Los_Angeles":  "Pacific Standard Time",
    "America/Phoenix":      "US Mountain Standard Time",
    "America/Anchorage":    "Alaskan Standard Time",
    "Pacific/Honolulu":     "Hawaiian Standard Time",
    "Europe/London":        "GMT Standard Time",
    "Europe/Paris":         "W. Europe Standard Time",
    "Europe/Berlin":        "W. Europe Standard Time",
    "Europe/Amsterdam":     "W. Europe Standard Time",
    "Europe/Madrid":        "Romance Standard Time",
    "Europe/Rome":          "W. Europe Standard Time",
    "Europe/Athens":        "GTB Standard Time",
    "Europe/Moscow":        "Russian Standard Time",
    "Asia/Dubai":           "Arabian Standard Time",
    "Asia/Kolkata":         "India Standard Time",
    "Asia/Dhaka":           "Bangladesh Standard Time",
    "Asia/Bangkok":         "SE Asia Standard Time",
    "Asia/Singapore":       "Singapore Standard Time",
    "Asia/Tokyo":           "Tokyo Standard Time",
    "Asia/Seoul":           "Korea Standard Time",
    "Asia/Shanghai":        "China Standard Time",
    "Asia/Hong_Kong":       "China Standard Time",
    "Asia/Karachi":         "Pakistan Standard Time",
    "Asia/Riyadh":          "Arab Standard Time",
    "Africa/Cairo":         "Egypt Standard Time",
    "Africa/Johannesburg":  "South Africa Standard Time",
    "Africa/Lagos":         "W. Central Africa Standard Time",
    "Australia/Sydney":     "AUS Eastern Standard Time",
    "Australia/Melbourne":  "AUS Eastern Standard Time",
    "Australia/Perth":      "W. Australia Standard Time",
    "Pacific/Auckland":     "New Zealand Standard Time",
    "America/Toronto":      "Eastern Standard Time",
    "America/Vancouver":    "Pacific Standard Time",
    "America/Sao_Paulo":    "E. South America Standard Time",
    "America/Buenos_Aires": "Argentina Standard Time",
    "America/Mexico_City":  "Central Standard Time (Mexico)",
    "UTC":                  "UTC",
}


def get_timezone_command(iana_tz: str, os_type: str = "windows") -> dict:
    """
    Returns the OS-level command to set the timezone.
    os_type: 'windows', 'macos', or 'linux'
    """
    os_type = os_type.lower()

    if os_type == "windows":
        win_tz = IANA_TO_WINDOWS.get(iana_tz)
        if not win_tz:
            return {"error": f"No Windows timezone mapping found for `{iana_tz}`."}
        return {
            "command": f'tzutil /s "{win_tz}"',
            "label":   "Run in PowerShell or Command Prompt (as Administrator)",
            "note":    "Change takes effect immediately. No restart needed.",
            "iana":    iana_tz,
            "os":      os_type,
        }

    if os_type == "macos":
        return {
            "command": f'sudo systemsetup -settimezone "{iana_tz}"',
            "label":   "Run in Terminal",
            "note":    "You will be prompted for your password.",
            "iana":    iana_tz,
            "os":      os_type,
        }

    if os_type == "linux":
        return {
            "command": f'sudo timedatectl set-timezone "{iana_tz}"',
            "label":   "Run in Terminal",
            "note":    "Change takes effect immediately.",
            "iana":    iana_tz,
            "os":      os_type,
        }

    return {"error": f"Unknown OS type: {os_type}. Use windows, macos, or linux."}