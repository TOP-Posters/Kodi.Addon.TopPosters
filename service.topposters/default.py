"""Buttons in the settings dialog: each one hands its action to the service."""

import sys

from resources.lib import kodi

ACTIONS = ("verify", "apply", "restore", "refresh")

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action in ACTIONS:
        kodi.notify_service(action)
    else:
        kodi.ADDON.openSettings()
