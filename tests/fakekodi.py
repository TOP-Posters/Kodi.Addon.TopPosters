"""An in-memory Kodi: the JSON-RPC methods the add-on uses, with art handed
back in Kodi's `image://<encoded>/` form, plus stand-ins for the xbmc modules."""

import json
import sys
import types
from urllib.parse import quote

KODI_SAFE = "-_.!()~"


def wrap(url):
    # Kodi encodes everything but a few marks, with lowercase hex.
    out, i = [], 0
    encoded = quote(url, safe=KODI_SAFE)
    while i < len(encoded):
        if encoded[i] == "%":
            out.append(encoded[i:i + 3].lower())
            i += 3
        else:
            out.append(encoded[i])
            i += 1
    return "image://" + "".join(out) + "/"


class FakeKodi(object):
    def __init__(self):
        self.items = {"movie": {}, "tvshow": {}, "season": {}, "episode": {}}
        self.textures = {}
        self.calls = []
        self.notifications = []

    # -- fixtures ---------------------------------------------------------

    def add(self, kind, dbid, art=None, **fields):
        item = dict(fields)
        item["art"] = dict(art or {})
        self.items[kind][dbid] = item
        return item

    def art(self, kind, dbid):
        return self.items[kind][dbid]["art"]

    def cache(self, url):
        textureid = len(self.textures) + 1
        self.textures[textureid] = url
        return textureid

    # -- JSON-RPC ---------------------------------------------------------

    def _out(self, kind, dbid, props):
        item = self.items[kind][dbid]
        out = {kind + "id": dbid, "label": item.get("title", "")}
        for prop in props:
            if prop == "art":
                out["art"] = dict((k, wrap(v)) for k, v in item["art"].items())
            elif prop in item:
                out[prop] = item[prop]
        return out

    def call(self, method, params):
        self.calls.append((method, params))
        props = params.get("properties", [])
        lists = {
            "VideoLibrary.GetMovies": ("movie", "movies", None),
            "VideoLibrary.GetTVShows": ("tvshow", "tvshows", None),
            "VideoLibrary.GetSeasons": ("season", "seasons", "tvshowid"),
            "VideoLibrary.GetEpisodes": ("episode", "episodes", "tvshowid"),
        }
        if method in lists:
            kind, key, parent = lists[method]
            ids = sorted(i for i, it in self.items[kind].items()
                         if parent is None or it.get(parent) == params.get(parent))
            return {key: [self._out(kind, i, props) for i in ids], "limits": {"total": len(ids)}}
        for kind, key in (("movie", "moviedetails"), ("tvshow", "tvshowdetails"),
                          ("season", "seasondetails"), ("episode", "episodedetails")):
            prefix = {"movie": "Movie", "tvshow": "TVShow", "season": "Season", "episode": "Episode"}[kind]
            if method == "VideoLibrary.Get%sDetails" % prefix:
                dbid = params[kind + "id"]
                if dbid not in self.items[kind]:
                    raise KeyError(method)
                return {key: self._out(kind, dbid, props)}
            if method == "VideoLibrary.Set%sDetails" % prefix:
                art = self.items[kind][params[kind + "id"]]["art"]
                for art_type, url in params["art"].items():
                    if url is None:
                        art.pop(art_type, None)
                    else:
                        art[art_type] = url
                return "OK"
        if method == "Textures.GetTextures":
            value = params["filter"]["value"]
            assert params["filter"]["operator"] == "startswith"
            return {"textures": [{"textureid": t, "url": u} for t, u in sorted(self.textures.items())
                                 if u.startswith(value)]}
        if method == "Textures.RemoveTexture":
            del self.textures[params["textureid"]]
            return "OK"
        if method == "JSONRPC.NotifyAll":
            self.notifications.append(params)
            return "OK"
        raise NotImplementedError(method)

    def rpc(self, method, params=None):
        result = self.call(method, params or {})
        return result if isinstance(result, dict) else {}

    def execute_json(self, request_json):
        request = json.loads(request_json)
        try:
            result = self.call(request["method"], request.get("params") or {})
        except KeyError:
            return json.dumps({"id": 1, "jsonrpc": "2.0", "error": {"code": -32602, "message": "Invalid params."}})
        return json.dumps({"id": 1, "jsonrpc": "2.0", "result": result})


def install_xbmc_stubs(kodi, settings, profile):
    """Fake xbmc, xbmcaddon, xbmcgui and xbmcvfs modules bound to `kodi`."""
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
    xbmc.logged = []
    xbmc.log = lambda msg, level=1: xbmc.logged.append(msg)
    xbmc.executeJSONRPC = kodi.execute_json
    xbmc.getInfoLabel = lambda label: "21.1 (21.1.0) Git:20240901"
    xbmc.scanning = False
    xbmc.getCondVisibility = lambda cond: xbmc.scanning if cond == "Library.IsScanningVideo" else False

    class Monitor(object):
        def __init__(self):
            self.aborted = False

        def abortRequested(self):
            return self.aborted

        def waitForAbort(self, timeout=0):
            return self.aborted

    xbmc.Monitor = Monitor

    xbmcaddon = types.ModuleType("xbmcaddon")
    info = {"id": "service.topposters", "name": "TOP Posters", "icon": "icon.png",
            "profile": "special://profile/addon_data/service.topposters/", "version": "1.0.0"}

    class Addon(object):
        def getAddonInfo(self, key):
            return info[key]

        def getSetting(self, name):
            return settings.get(name, "")

        def setSetting(self, name, value):
            settings[name] = value

        def getLocalizedString(self, string_id):
            return "#%d %%s" % string_id

        def openSettings(self):
            pass

    xbmcaddon.Addon = Addon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.shown = []

    class Dialog(object):
        def notification(self, heading, message, icon=None, time=0):
            xbmcgui.shown.append(("notification", message))

        def ok(self, heading, message):
            xbmcgui.shown.append(("ok", message))

    class DialogProgressBG(object):
        def create(self, heading, message=""):
            xbmcgui.shown.append(("progress", message))

        def update(self, percent=0, heading=None, message=None):
            pass

        def close(self):
            pass

    xbmcgui.Dialog = Dialog
    xbmcgui.DialogProgressBG = DialogProgressBG

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda path: profile

    for name, module in (("xbmc", xbmc), ("xbmcaddon", xbmcaddon), ("xbmcgui", xbmcgui), ("xbmcvfs", xbmcvfs)):
        sys.modules[name] = module
    # Modules bound to a previous fake must be imported afresh; `from package
    # import module` looks at the package attribute before sys.modules.
    package = sys.modules.get("resources.lib")
    for name in ("kodi", "service"):
        sys.modules.pop("resources.lib." + name, None)
        if package is not None and hasattr(package, name):
            delattr(package, name)
    return xbmc, xbmcgui
