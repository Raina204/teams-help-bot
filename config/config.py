import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Azure Bot ──────────────────────────────────────────
    MICROSOFT_APP_ID        = os.environ.get("MICROSOFT_APP_ID", "")
    MICROSOFT_APP_PASSWORD  = os.environ.get("MICROSOFT_APP_PASSWORD", "")
    MICROSOFT_APP_TENANT_ID = os.environ.get("MICROSOFT_APP_TENANT_ID", "")
    MICROSOFT_APP_TYPE      = os.environ.get("MICROSOFT_APP_TYPE", "MultiTenant")
    PORT                    = int(os.environ.get("PORT", 3978))

    # ── ConnectWise Manage ─────────────────────────────────
    CW_SITE               = os.environ.get("CW_SITE", "")
    CW_COMPANY_ID         = os.environ.get("CW_COMPANY_ID", "")
    CW_PUBLIC_KEY         = os.environ.get("CW_PUBLIC_KEY", "")
    CW_PRIVATE_KEY        = os.environ.get("CW_PRIVATE_KEY", "")
    CW_CLIENT_ID          = os.environ.get("CW_CLIENT_ID", "")
    CW_DEFAULT_BOARD      = os.environ.get("CW_DEFAULT_BOARD", "Professional Services")
    CW_DEFAULT_COMPANY_ID = int(os.environ.get("CW_DEFAULT_COMPANY_ID", 133))
    CW_DEFAULT_PRIORITY   = os.environ.get("CW_DEFAULT_PRIORITY", "Priority 3 - Normal Response")

    # ── N-able N-central RMM ───────────────────────────────
    NABLE_BASE_URL    = os.environ.get("NABLE_BASE_URL", "")
    NABLE_JWT_TOKEN   = os.environ.get("NABLE_JWT_TOKEN", "")

    # Parse customer map from .env
    # Format: "itbd.net:1118,ntinetworks.com:1804"
    # Result: {"itbd.net": "1118", "ntinetworks.com": "1804"}
    _raw_map = os.environ.get("NABLE_CUSTOMER_MAP", "")
    NABLE_CUSTOMER_MAP = {}
    for _pair in _raw_map.split(","):
        if ":" in _pair:
            _domain, _cid = _pair.strip().split(":", 1)
            NABLE_CUSTOMER_MAP[_domain.strip().lower()] = _cid.strip()

    # Script IDs in N-central
    NABLE_SCRIPTS = {
        "memory":        int(os.environ.get("NABLE_SCRIPT_MEMORY", 0)),
        "cpu":           int(os.environ.get("NABLE_SCRIPT_CPU", 0)),
        "storage":       int(os.environ.get("NABLE_SCRIPT_STORAGE", 0)),
        "outlook_reset": int(os.environ.get("NABLE_SCRIPT_OUTLOOK_RESET", 0)),
    }


CONFIG = Config()