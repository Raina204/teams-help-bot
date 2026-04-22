# services/graph_service.py

import os
import logging
import aiohttp

log      = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


async def _get_token(user_tenant_id: str = None) -> str:
    """
    Gets a Graph API access token.
    For multi-tenant: pass the user's tenant_id to get a token
    scoped to their tenant.
    Falls back to the bot's own tenant if none supplied.
    """
    tenant_id     = user_tenant_id or os.environ["MICROSOFT_APP_TENANT_ID"]
    client_id     = os.environ["MICROSOFT_APP_ID"]
    client_secret = os.environ["MICROSOFT_APP_PASSWORD"]


    url  = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            result = await resp.json()
            if "access_token" not in result:
                raise RuntimeError(
                    f"Token request failed for tenant {tenant_id}: "
                    f"{result.get('error_description', result)}"
                )
            return result["access_token"]


async def set_user_timezone(
    user_email:     str,
    windows_tz:     str,
    iana_tz:        str,
    user_tenant_id: str = None,
) -> dict:
    """
    Sets the timezone on a user's Microsoft 365 account via Graph API.
    Works across any tenant — pass user_tenant_id for multi-tenant support.

    user_email     : john.smith@clientcompany.com
    windows_tz     : Tokyo Standard Time
    iana_tz        : Asia/Tokyo
    user_tenant_id : the tenant ID of the user's organisation
    """
    try:
        token   = await _get_token(user_tenant_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"{GRAPH_BASE}/users/{user_email}/mailboxSettings",
                headers = headers,
                json    = {"timeZone": windows_tz},
            ) as resp:

                if resp.status in (200, 201, 204):
                    log.info(
                        "graph.timezone_set — user=%s tz=%s tenant=%s",
                        user_email, windows_tz, user_tenant_id,
                    )
                    return {
                        "success":  True,
                        "message": (
                            f"Your timezone has been updated to "
                            f"{iana_tz} on your Microsoft 365 account. "
                            f"This is now reflected in Outlook, Teams "
                            f"calendar, and all Microsoft 365 apps."
                        ),
                        "windows_tz": windows_tz,
                        "iana_tz":    iana_tz,
                        "user":       user_email,
                    }

                error_body = await resp.text()
                log.error(
                    "graph.timezone_error — status=%s user=%s body=%s",
                    resp.status, user_email, error_body,
                )
                return {
                    "success": False,
                    "error":   f"Could not update timezone (status {resp.status}).",
                }

    except Exception as exc:
        log.error("graph.set_timezone exception: %s", exc)
        return {"success": False, "error": str(exc)}