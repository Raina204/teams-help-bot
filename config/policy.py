"""
config/policy.py
----------------
RBAC (Role-Based Access Control) policy gate.

Call check_allowed() before every service invocation in your orchestrator.
It reads the allowed_actions list from the tenant_ctx and raises
PermissionError if the requested action is not permitted for that tenant.

Usage:
    from config.policy import check_allowed

    check_allowed("RESTART_PRINTER", tenant_ctx)
    await printer_service.restart_spooler(user_email, tenant_ctx)
"""

import logging

logger = logging.getLogger(__name__)


class ActionNotAllowedError(PermissionError):
    """
    Raised when a tenant attempts an action not in their allowed_actions list.
    Catch this in your orchestrator and send the user a friendly message.
    """
    def __init__(self, action: str, tenant_id: str, allowed: list[str]):
        self.action = action
        self.tenant_id = tenant_id
        self.allowed = allowed
        super().__init__(
            f"Action '{action}' is not enabled for tenant '{tenant_id}'. "
            f"Allowed actions: {allowed}"
        )


def check_allowed(action: str, tenant_ctx: dict) -> None:
    """
    Assert that the given action is permitted for this tenant.
    Raises ActionNotAllowedError if not.

    Args:
        action:     Action name e.g. "RESTART_PRINTER". Must match
                    an entry in tenant_ctx["allowed_actions"].
        tenant_ctx: The resolved tenant config dict.

    Raises:
        ActionNotAllowedError: if action is not in allowed_actions.
        ValueError: if tenant_ctx is missing required fields.
    """
    tenant_id = tenant_ctx.get("tenant_id", "<unknown>")
    allowed: list[str] = tenant_ctx.get("allowed_actions", [])

    if not isinstance(allowed, list):
        raise ValueError(
            f"tenant_ctx['allowed_actions'] must be a list, "
            f"got {type(allowed)} for tenant '{tenant_id}'"
        )

    if action not in allowed:
        logger.warning(
            f"POLICY DENIED — tenant='{tenant_id}' action='{action}' "
            f"allowed={allowed}"
        )
        raise ActionNotAllowedError(action, tenant_id, allowed)

    logger.debug(f"POLICY ALLOWED — tenant='{tenant_id}' action='{action}'")


def is_allowed(action: str, tenant_ctx: dict) -> bool:
    """
    Non-raising version of check_allowed. Returns True/False.
    Use this when you need to conditionally show UI options.

    Args:
        action:     Action name to check.
        tenant_ctx: The resolved tenant config dict.

    Returns:
        True if action is in allowed_actions, False otherwise.
    """
    try:
        check_allowed(action, tenant_ctx)
        return True
    except ActionNotAllowedError:
        return False


def get_allowed_actions(tenant_ctx: dict) -> list[str]:
    """
    Return the full list of allowed actions for a tenant.
    Use this to build dynamic menus that only show what the tenant can do.

    Args:
        tenant_ctx: The resolved tenant config dict.

    Returns:
        List of allowed action name strings.
    """
    return tenant_ctx.get("allowed_actions", [])