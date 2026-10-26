"""The service end to end, against the fake Kodi and fake xbmc modules."""

import json
import os
import re
import time
import xml.etree.ElementTree as ET

import pytest

from fakekodi import FakeKodi, install_xbmc_stubs

TMDB = "https://image.tmdb.org/t/p/original/"
ADDON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service.topposters")


@pytest.fixture
def env(tmp_path, monkeypatch):
    kodi = FakeKodi()
    kodi.add("movie", 1, {"poster": TMDB + "matrix.jpg"}, title="The Matrix", uniqueid={"tmdb": "603"})
    settings = {"enabled": "true", "api_key": "TP-key", "base_url": "https://api.top-posters.com",
                "movies": "true", "tvshows": "true", "posters": "true", "season_posters": "true",
                "episode_thumbs": "false", "banners": "false", "backgrounds": "false", "logos": "false",
                "refresh_days": "7"}
    xbmc, xbmcgui = install_xbmc_stubs(kodi, settings, str(tmp_path) + "/")
    from resources.lib import service as service_module
    from resources.lib import api

    verified = api.parse_verify({"valid": True, "tier_name": "Free", "tier_info": {"features": {}},
                                 "banners": {}, "backgrounds": {}})
    monkeypatch.setattr(service_module, "verify_key", lambda *a: verified)
    monkeypatch.setattr(service_module, "DEBOUNCE", 0)
    svc = service_module.Service()
    return kodi, settings, svc, xbmc, xbmcgui, service_module


def started(svc):
    svc.start()
    svc.tick()
    return svc


def test_run_stops_on_abort(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    svc.monitor.aborted = True
    svc.run()
    assert kodi.calls == []


def test_startup_applies_posters(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    started(svc)
    assert kodi.art("movie", 1)["poster"].startswith("https://api.top-posters.com/TP-key/tmdb/poster/movie-603.jpg")
    assert svc.store.get("caps") == {"thumb": False, "landscape": False, "fanart": False}


def test_own_writes_do_not_echo(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    started(svc)
    sets = len([c for c in kodi.calls if c[0].startswith("VideoLibrary.Set")])
    gets = len([c for c in kodi.calls if c[0] == "VideoLibrary.GetMovieDetails"])
    # Kodi reports the write we just made
    svc.monitor.onNotification("xbmc", "VideoLibrary.OnUpdate", json.dumps({"item": {"type": "movie", "id": 1}}))
    svc.item_pass()
    assert len([c for c in kodi.calls if c[0] == "VideoLibrary.GetMovieDetails"]) == gets
    assert len([c for c in kodi.calls if c[0].startswith("VideoLibrary.Set")]) == sets


def test_refreshed_item_gets_our_poster_back(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    started(svc)
    svc.recent_writes.clear()
    kodi.art("movie", 1)["poster"] = TMDB + "matrix-2.jpg"
    svc.monitor.onNotification("xbmc", "VideoLibrary.OnUpdate", json.dumps({"item": {"type": "movie", "id": 1}}))
    svc.monitor.onNotification("xbmc", "VideoLibrary.OnUpdate",
                               json.dumps({"item": {"type": "movie", "id": 1}, "playcount": 1}))
    svc.item_pass()
    assert "matrix-2.jpg" in kodi.art("movie", 1)["poster"]
    assert kodi.art("movie", 1)["poster"].startswith("https://api.top-posters.com/")


def test_restore_button_turns_off_and_puts_originals_back(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    started(svc)
    kodi.cache(kodi.art("movie", 1)["poster"])
    svc.monitor.onNotification("service.topposters", "Other.restore", "null")
    svc.tick()
    assert settings["enabled"] == "false"
    assert kodi.art("movie", 1)["poster"] == TMDB + "matrix.jpg"
    assert kodi.textures == {}
    # A later scan does not bring our posters back
    svc.monitor.onNotification("xbmc", "VideoLibrary.OnScanFinished", "null")
    svc.tick()
    assert kodi.art("movie", 1)["poster"] == TMDB + "matrix.jpg"
    # Apply turns it on again
    svc.monitor.onNotification("service.topposters", "Other.apply", "null")
    svc.tick()
    assert settings["enabled"] == "true"
    assert kodi.art("movie", 1)["poster"].startswith("https://api.top-posters.com/")


def test_scheduled_refresh_drops_only_our_textures(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    started(svc)
    ours = kodi.cache(kodi.art("movie", 1)["poster"])
    theirs = kodi.cache(TMDB + "matrix.jpg")
    svc.refresh_textures()
    assert ours in kodi.textures  # just started: not due yet
    svc.store.set("last_refresh", time.time() - 8 * 24 * 3600)
    svc.refresh_textures()
    assert ours not in kodi.textures and theirs in kodi.textures


def test_waits_for_scan_to_finish(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    xbmc.scanning = True
    started(svc)
    assert kodi.art("movie", 1)["poster"] == TMDB + "matrix.jpg"
    xbmc.scanning = False
    svc.tick()
    assert kodi.art("movie", 1)["poster"].startswith("https://api.top-posters.com/")


def test_settings_buttons_notify_the_service(env):
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    import runpy
    import sys
    for action in ("verify", "apply", "restore", "refresh"):
        sys.argv = ["default.py", action]
        runpy.run_path(os.path.join(ADDON_DIR, "default.py"), run_name="__main__")
    assert [n["message"] for n in kodi.notifications] == ["verify", "apply", "restore", "refresh"]


def _po_ids(lang):
    path = os.path.join(ADDON_DIR, "resources", "language", "resource.language.%s" % lang, "strings.po")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    entries = re.findall(r'msgctxt "#(\d+)"\nmsgid "(.*)"\nmsgstr "(.*)"', text)
    return dict((int(i), (msgid, msgstr)) for i, msgid, msgstr in entries)


def test_every_string_id_exists_and_is_translated():
    used = set()
    root = ET.parse(os.path.join(ADDON_DIR, "resources", "settings.xml")).getroot()
    for el in root.iter():
        for attr in ("label", "help"):
            if el.get(attr):
                used.add(int(el.get(attr)))
        if el.tag == "heading":
            used.add(int(el.text))
    lib = os.path.join(ADDON_DIR, "resources", "lib")
    for name in os.listdir(lib):
        if name.endswith(".py"):
            with open(os.path.join(lib, name)) as f:
                used |= set(int(i) for i in re.findall(r"\b(32\d{3})\b", f.read()))
    en, it = _po_ids("en_gb"), _po_ids("it_it")
    assert used - set(en) == set()
    assert set(en) == set(it)
    assert all(msgstr for msgid, msgstr in it.values())
    assert all(msgid.count("%") == it[i][1].count("%") for i, (msgid, _) in en.items())


def test_addon_xml_points_at_real_files():
    root = ET.parse(os.path.join(ADDON_DIR, "addon.xml")).getroot()
    assert root.get("id") == "service.topposters"
    for ext in root.findall("extension"):
        if ext.get("library"):
            assert os.path.isfile(os.path.join(ADDON_DIR, ext.get("library")))
    icon = root.find("extension/assets/icon").text
    assert os.path.isfile(os.path.join(ADDON_DIR, icon))


def test_local_artwork_refresh_and_restore_through_service(env, monkeypatch):
    from test_local_artwork import PNG, PNG2, Response
    from resources.lib import local_artwork
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    original = "smb://nas/Movies/Matrix/poster.jpg"
    kodi.art("movie", 1)["poster"] = original
    calls = []
    content = [PNG]

    def download(request, timeout):
        calls.append(request.full_url)
        return Response(content[0])

    monkeypatch.setattr(local_artwork, "urlopen", download)
    started(svc)
    prepared = kodi.art("movie", 1)["poster"]
    assert os.path.isfile(prepared) and len(calls) == 1
    assert svc.store.originals("movie", 1)["poster"] == original
    assert "fallback_url" not in calls[0]
    svc.full_pass()
    assert len(calls) == 1  # No additional download while the local copy is fresh.

    content[0] = PNG2
    svc.monitor.onNotification("service.topposters", "Other.refresh", "null")
    svc.tick()
    updated = kodi.art("movie", 1)["poster"]
    assert updated != prepared and os.path.isfile(updated) and len(calls) == 2
    svc.restore()
    assert kodi.art("movie", 1)["poster"] == original and settings["enabled"] == "false"


def test_offline_refresh_keeps_last_good_local_artwork(env, monkeypatch):
    from urllib.error import URLError
    from test_local_artwork import Response
    from resources.lib import local_artwork
    kodi, settings, svc, xbmc, xbmcgui, _ = env
    kodi.art("movie", 1)["poster"] = "/media/matrix/poster.jpg"
    monkeypatch.setattr(local_artwork, "urlopen", lambda *a, **k: Response())
    started(svc)
    prepared = kodi.art("movie", 1)["poster"]

    def offline(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(local_artwork, "urlopen", offline)
    svc.refresh_textures(force=True)
    svc.tick()
    assert kodi.art("movie", 1)["poster"] == prepared and os.path.isfile(prepared)
    assert svc.store.originals("movie", 1)["poster"] == "/media/matrix/poster.jpg"
