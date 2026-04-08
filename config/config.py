
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Azure Bot credentials
    MICROSOFT_APP_ID        = os.environ.get("MICROSOFT_APP_ID", "")
    MICROSOFT_APP_PASSWORD  = os.environ.get("MICROSOFT_APP_PASSWORD", "")
    MICROSOFT_APP_TENANT_ID = os.environ.get("MICROSOFT_APP_TENANT_ID", "")
    MICROSOFT_APP_TYPE      = os.environ.get("MICROSOFT_APP_TYPE", "MultiTenant")
    PORT                    = int(os.environ.get("PORT", 3978))

    # ConnectWise Manage
    CW_SITE               = os.environ.get("CW_SITE", "")
    CW_COMPANY_ID         = os.environ.get("CW_COMPANY_ID", "")
    CW_PUBLIC_KEY         = os.environ.get("CW_PUBLIC_KEY", "")
    CW_PRIVATE_KEY        = os.environ.get("CW_PRIVATE_KEY", "")
    CW_CLIENT_ID          = os.environ.get("CW_CLIENT_ID", "")
    CW_DEFAULT_BOARD      = os.environ.get("CW_DEFAULT_BOARD", "Professional Services")
    CW_DEFAULT_COMPANY_ID = int(os.environ.get("CW_DEFAULT_COMPANY_ID", 133))
    CW_DEFAULT_PRIORITY   = os.environ.get("CW_DEFAULT_PRIORITY", "Priority 3 - Normal Response")

    # ConnectWise Automate RMM
    RMM_BASE_URL  = os.environ.get("RMM_BASE_URL", "")
    RMM_USERNAME  = os.environ.get("RMM_USERNAME", "")
    RMM_PASSWORD  = os.environ.get("RMM_PASSWORD", "")
    RMM_SCRIPTS   = {
        "memory":        int(os.environ.get("RMM_SCRIPT_MEMORY", 100)),
        "cpu":           int(os.environ.get("RMM_SCRIPT_CPU", 101)),
        "storage":       int(os.environ.get("RMM_SCRIPT_STORAGE", 102)),
        "outlook_reset": int(os.environ.get("RMM_SCRIPT_OUTLOOK_RESET", 103)),
    }

CONFIG = Config()