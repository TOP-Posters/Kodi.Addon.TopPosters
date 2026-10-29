"""Everything that touches the xbmc modules."""

import json

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ICON = ADDON.getAddonInfo("icon")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, message), level)


def string(string_id):
    return ADDON.getLocalizedString(string_id)


def setting(name):
    # A fresh Addon() reads the settings as they are now, not as they were
    # when this module was imported.
    return xbmcaddon.Addon().getSetting(name)


def setting_bool(name):
    return setting(name) == "true"


def setting_int(name, default=0):
    try:
        return int(setting(name))
    except ValueError:
        return default


def notify(message, time_ms=5000):
    xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"), message, ICON, time_ms)


def ok_dialog(message):
    xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), message)


class RpcError(Exception):
    pass


def rpc(method, params=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if "error" in response:
        raise RpcError("%s: %s" % (method, response["error"]))
    return response.get("result") or {}


def notify_service(action):
    """Hand an action to the running service, which does all library work so
    two writers never touch the saved originals at once."""
    rpc("JSONRPC.NotifyAll", {"sender": ADDON_ID, "message": action})


def user_agent():
    # Kodi's own user agent names the platform (Android TV, Windows,
    # LibreELEC...), which TOP Posters shows for this device in the dashboard.
    return "%s TOP Posters add-on/%s" % (xbmc.getUserAgent(), ADDON.getAddonInfo("version"))


def is_scanning():
    return xbmc.getCondVisibility("Library.IsScanningVideo")
