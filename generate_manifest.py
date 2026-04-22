import json
import zipfile
import os
from PIL import Image, ImageDraw

# -------------------------
# CONFIGURATION — Fill these in
# -------------------------
APP_ID        = "7178286e-0d7c-4485-ae7e-bc8d488dc94b"   # Replace with your Entra App ID
NGROK_URL     = "https://calvin-unpeeling-latrice.ngrok-free.dev"
APP_NAME_SHORT = "IT Help Bot"
APP_NAME_FULL  = "ITBD IT Help Bot"
COMPANY_NAME   = "ITBD"
PACKAGE_NAME   = "net.itbd.helpbot"
# -------------------------


def generate_color_icon(path: str):
    img = Image.new("RGB", (192, 192), color=(0, 120, 212))
    draw = ImageDraw.Draw(img)
    draw.ellipse([40, 40, 152, 152], fill=(255, 255, 255))
    draw.text((75, 80), "IT", fill=(0, 120, 212))
    img.save(path, "PNG")
    print("DONE  color icon: " + path)


def generate_outline_icon(path: str):
    img = Image.new("RGBA", (32, 32), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 30, 30], outline=(255, 255, 255), width=2)
    draw.text((10, 9), "I", fill=(255, 255, 255))
    img.save(path, "PNG")
    print("DONE  outline icon: " + path)


def generate_manifest() -> dict:
    ngrok_domain = NGROK_URL.replace("https://", "").replace("http://", "").rstrip("/")

    return {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
        "manifestVersion": "1.16",
        "version": "1.0.0",
        "id": APP_ID,
        "packageName": PACKAGE_NAME,
        "developer": {
            "name": COMPANY_NAME,
            "websiteUrl": "https://itbd.net",
            "privacyUrl": "https://itbd.net/privacy",
            "termsOfUseUrl": "https://itbd.net/terms"
        },
        "name": {
            "short": APP_NAME_SHORT,
            "full": APP_NAME_FULL
        },
        "description": {
            "short": "Raise tickets and run diagnostics via ConnectWise and N-able",
            "full": "Create ConnectWise support tickets and run N-able RMM diagnostics directly from Microsoft Teams chat."
        },
        "icons": {
            "color": "color.png",
            "outline": "outline.png"
        },
        "accentColor": "#0078D4",
        "bots": [
            {
                "botId": APP_ID,
                "scopes": ["personal", "team", "groupchat"],
                "supportsFiles": False,
                "isNotificationOnly": False,
                "commandLists": [
                    {
                        "scopes": ["personal", "team", "groupchat"],
                        "commands": [
                            {"title": "help",          "description": "Show the main menu"},
                            {"title": "new ticket",    "description": "Create a ConnectWise support ticket"},
                            {"title": "diagnose",      "description": "Run diagnostics on your PC via N-able"},
                            {"title": "reset outlook", "description": "Reset Outlook profile via N-able"},
                            {"title": "check ticket",  "description": "Check the status of a ticket"}
                        ]
                    }
                ]
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [
            ngrok_domain,
            "itbd.net"
        ]
    }


def create_manifest_zip(output_path: str = "teams-app-manifest.zip"):
    color_icon    = "color.png"
    outline_icon  = "outline.png"
    manifest_file = "manifest.json"

    if APP_ID == "YOUR_AZURE_APP_ID_HERE":
        print("ERROR: Replace YOUR_AZURE_APP_ID_HERE with your actual App ID before running.")
        return

    generate_color_icon(color_icon)
    generate_outline_icon(outline_icon)

    manifest = generate_manifest()
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)
    print("DONE  manifest.json")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_file)
        zf.write(color_icon)
        zf.write(outline_icon)

    os.remove(color_icon)
    os.remove(outline_icon)
    os.remove(manifest_file)

    print("")
    print("DONE  Package ready: " + output_path)
    print("")
    print("  Contents:")
    print("    manifest.json")
    print("    color.png   (192x192)")
    print("    outline.png (32x32)")
    print("")
    print("  Next: Teams -> Apps -> Manage your apps -> Upload an app -> select " + output_path)


if __name__ == "__main__":
    create_manifest_zip()
