"""
services/timezone_service.py
-----------------------------
Timezone command generator — multi-tenant aware.

This service has no external API calls, credentials, or network requests.
tenant_ctx is used solely to enforce each tenant's allowed_timezones policy
before generating commands.

Per-tenant values used from tenant_ctx:
  - allowed_timezones  → list of permitted IANA timezone strings.
                         Empty list [] means all timezones are permitted.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# IANA → Windows timezone name mapping
# ---------------------------------------------------------------------------

IANA_TO_WINDOWS: dict[str, str] = {
    "America/New_York":    "Eastern Standard Time",
    "America/Chicago":     "Central Standard Time",
    "America/Denver":      "Mountain Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "America/Phoenix":     "US Mountain Standard Time",
    "America/Anchorage":   "Alaskan Standard Time",
    "America/Honolulu":    "Hawaiian Standard Time",
    "Europe/London":       "GMT Standard Time",
    "Europe/Paris":        "W. Europe Standard Time",
    "Europe/Berlin":       "W. Europe Standard Time",
    "Europe/Istanbul":     "Turkey Standard Time",
    "Asia/Tokyo":          "Tokyo Standard Time",
    "Asia/Kolkata":        "India Standard Time",
    "Asia/Dubai":          "Arabian Standard Time",
    "Asia/Singapore":      "Singapore Standard Time",
    "Asia/Karachi":        "Pakistan Standard Time",
    "Asia/Shanghai":       "China Standard Time",
    "Asia/Seoul":          "Korea Standard Time",
    "Australia/Sydney":    "AUS Eastern Standard Time",
    "Australia/Perth":     "W. Australia Standard Time",
    "Pacific/Auckland":    "New Zealand Standard Time",
    "UTC":                 "UTC",
    "GMT":                 "GMT Standard Time",
}


# ---------------------------------------------------------------------------
# Policy check
# ---------------------------------------------------------------------------

def is_timezone_allowed(iana_timezone: str, tenant_ctx: dict) -> bool:
    """
    Check whether this IANA timezone is permitted for the given tenant.

    If the tenant's allowed_timezones list is empty, all timezones are
    permitted. If the list has entries, the requested timezone must be
    in it.

    Args:
        iana_timezone: IANA timezone string (e.g. "America/New_York").
        tenant_ctx:    Resolved tenant config dict.

    Returns:
        True if the timezone is allowed, False if blocked by policy.
    """
    allowed = tenant_ctx.get("allowed_timezones", [])
    # Empty list = no restriction = all timezones permitted
    if not allowed:
        return True
    return iana_timezone in allowed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_timezone_command(
    iana_timezone: str,
    os_type: str,
    tenant_ctx: dict | None = None,
) -> dict:
    """
    Return the shell command to set a timezone for the given OS.
    Validates the timezone against the tenant's allowed_timezones policy
    before generating the command.

    Args:
        iana_timezone: IANA timezone string (e.g. "America/New_York").
        os_type:       Target OS — "windows", "macos", or "linux".
        tenant_ctx:    Resolved tenant config dict. Optional — if None,
                       no policy check is performed (used in main_dialog.py
                       to preview commands before RBAC is applied).

    Returns:
        Dict with 'command', 'label', 'note', 'iana', 'os' on success.
        Dict with 'error' key on failure (policy block or unknown OS).
    """
    # ── Tenant policy check ───────────────────────────────────────────────
    # If tenant_ctx is provided, validate the requested timezone against
    # this tenant's allowed_timezones list before generating any command.
    if tenant_ctx is not None:
        if not is_timezone_allowed(iana_timezone, tenant_ctx):
            allowed = tenant_ctx.get("allowed_timezones", [])
            return {
                "error": (
                    f"Timezone '{iana_timezone}' is not permitted for "
                    f"tenant '{tenant_ctx.get('tenant_id', 'unknown')}'. "
                    f"Permitted timezones: {', '.join(allowed) if allowed else 'none configured'}."
                ),
                "policy_blocked": True,
            }

    os_lower = os_type.lower()

    # ── Windows ───────────────────────────────────────────────────────────
    if os_lower == "windows":
        windows_tz = IANA_TO_WINDOWS.get(iana_timezone)
        if not windows_tz:
            return {
                "error": (
                    f"No Windows timezone mapping found for '{iana_timezone}'. "
                    f"Supported IANA timezones: {', '.join(IANA_TO_WINDOWS.keys())}."
                )
            }
        return {
            "command": f'tzutil /s "{windows_tz}"',
            "label":   windows_tz,
            "note":    "Run as Administrator in PowerShell or Command Prompt.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    # ── macOS ─────────────────────────────────────────────────────────────
    if os_lower == "macos":
        return {
            "command": f'sudo systemsetup -settimezone "{iana_timezone}"',
            "label":   iana_timezone,
            "note":    "Run in Terminal.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    # ── Linux ─────────────────────────────────────────────────────────────
    if os_lower == "linux":
        return {
            "command": f'sudo timedatectl set-timezone "{iana_timezone}"',
            "label":   iana_timezone,
            "note":    "Run in Terminal.",
            "iana":    iana_timezone,
            "os":      os_lower,
        }

    return {
        "error": (
            f"Unknown OS type '{os_type}'. "
            "Expected: windows, macos, or linux."
        )
    }


def get_windows_timezone_name(iana_timezone: str) -> str | None:
    """
    Convenience function — return the Windows timezone name for an IANA
    string, or None if no mapping exists.

    Used by rmm_service.change_timezone() to get the Windows-compatible
    name before passing it to the ConnectWise Automate script.

    Args:
        iana_timezone: IANA timezone string.

    Returns:
        Windows timezone name string, or None.
    """
    return IANA_TO_WINDOWS.get(iana_timezone)