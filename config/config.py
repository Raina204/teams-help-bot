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

    # ── ConnectWise Automate RMM ───────────────────────────
    CWA_BASE_URL = os.environ.get("CWA_BASE_URL", "")

    # Script IDs pre-created in ConnectWise Automate.
    # Set these in .env after uploading each script to CWA.
    CWA_SCRIPTS = {
        "memory":          int(os.environ.get("CWA_SCRIPT_MEMORY", 0)),
        "cpu":             int(os.environ.get("CWA_SCRIPT_CPU", 0)),
        "storage":         int(os.environ.get("CWA_SCRIPT_STORAGE", 0)),
        "outlook_reset":   int(os.environ.get("CWA_SCRIPT_OUTLOOK_RESET", 0)),
        "timezone_change": int(os.environ.get("CWA_SCRIPT_TIMEZONE_CHANGE", 0)),
        "printer_restart": int(os.environ.get("CWA_SCRIPT_PRINTER_RESTART", 0)),
        "printer_status":  int(os.environ.get("CWA_SCRIPT_PRINTER_STATUS", 0)),
        "printer_clear":   int(os.environ.get("CWA_SCRIPT_PRINTER_CLEAR_QUEUE", 0)),
        "printer_list":    int(os.environ.get("CWA_SCRIPT_PRINTER_LIST", 0)),
    }


CONFIG = Config()
