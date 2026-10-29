"""The background service: applies artwork at startup, after library scans and
item refreshes, when settings change, and refreshes cached images on schedule."""

import json
import os
import time
import uuid

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib.api import INVALID, UNREACHABLE, VALID, verify_key
from resources.lib.library import Library
from resources.lib.local_artwork import LocalArtworkCache
from resources.lib.store import Store
from resources.lib.sync import Config, Syncer

# Wait this long after the last library or settings event before acting, so a
# burst of notifications turns into one pass.
DEBOUNCE = 5
# Library notifications for items we wrote within this window are our own.
OWN_WRITE_WINDOW = 120
REFRESH_CHECK_EVERY = 3600
DAY = 24 * 3600

ART_LABELS = {"thumb": 32023, "landscape": 32024, "fanart": 32025}


def read_config(caps, device_id=None):
    return Config(
        enabled=kodi.setting_bool("enabled"),
        api_key=kodi.setting("api_key"),
        base_url=kodi.setting("base_url"),
        movies=kodi.setting_bool("movies"),
        tvshows=kodi.setting_bool("tvshows"),
        toggles={
            "poster": kodi.setting_bool("posters"),
            "season_poster": kodi.setting_bool("season_posters"),
            "thumb": kodi.setting_bool("episode_thumbs"),
            "landscape": kodi.setting_bool("banners"),
            "fanart": kodi.setting_bool("backgrounds"),
            "clearlogo": kodi.setting_bool("logos"),
        },
        caps=caps,
        device_id=device_id,
    )


class Monitor(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.full_pass_at = None
        self.items = {}
        self.actions = []

    def schedule_full_pass(self):
        self.full_pass_at = time.time() + DEBOUNCE

    def onSettingsChanged(self):
        self.schedule_full_pass()

    def onNotification(self, sender, method, data):
        if sender == kodi.ADDON_ID and method.startswith("Other."):
            self.actions.append(method[len("Other."):])
        elif method == "VideoLibrary.OnScanFinished":
            self.schedule_full_pass()
        elif method == "VideoLibrary.OnUpdate":
            try:
                payload = json.loads(data)
            except ValueError:
                return
            if "playcount" in payload or payload.get("transaction"):
                return
            item = payload.get("item") or payload
            if item.get("type") in ("movie", "tvshow", "season", "episode") and item.get("id"):
                self.items[(item["type"], item["id"])] = time.time()


class Service(object):
    def __init__(self):
        self.monitor = Monitor()
        self.store = Store(os.path.join(kodi.PROFILE, "state.json"))
        self.library = Library(kodi.rpc)
        self.recent_writes = {}
        self.next_refresh_check = 0

    def config(self):
        return read_config(self.store.get("caps"), self.installation_id())

    def installation_id(self, new=False):
        """This installation's ID, created on first use and kept in the state
        file. A copied data folder carries it along, hence the settings button
        that replaces it."""
        device_id = self.store.get("device_id")
        if new or not device_id:
            device_id = uuid.uuid4().hex
            self.store.set("device_id", device_id)
            self.store.save()
        return device_id

    def syncer(self, config):
        return Syncer(self.library, config, self.store, should_stop=self.monitor.abortRequested,
                      local_cache=self.local_cache(config))

    def local_cache(self, config):
        return LocalArtworkCache(self.store, kodi.user_agent(), kodi.setting_int("refresh_days", 7),
                                 namespace=config.base_url + "|" + config.api_key)

    def _remember_writes(self, syncer):
        now = time.time()
        for key in syncer.written:
            self.recent_writes[key] = now
        self.recent_writes = dict((k, t) for k, t in self.recent_writes.items() if now - t < OWN_WRITE_WINDOW)

    # -- actions ----------------------------------------------------------

    def verify(self, interactive):
        config = self.config()
        if not config.api_key:
            if interactive:
                kodi.ok_dialog(kodi.string(32103))
            return
        status = verify_key(config.base_url, config.api_key, kodi.user_agent())
        if status.state == VALID:
            self.store.set("caps", status.caps)
            self.store.save()
        if not interactive:
            if status.state == INVALID:
                kodi.notify(kodi.string(32101))
            return
        if status.state == INVALID:
            kodi.ok_dialog(kodi.string(32101))
        elif status.state == UNREACHABLE:
            kodi.ok_dialog(kodi.string(32102))
        else:
            lines = [kodi.string(32100) % status.plan]
            toggles = config.toggles
            off = [a for a in status.off_in_dashboard if toggles.get(a)]
            missing = [a for a, allowed in sorted(status.caps.items())
                       if not allowed and a not in off and toggles.get(a)]
            if missing:
                lines.append(kodi.string(32107) % ", ".join(kodi.string(ART_LABELS[a]) for a in missing))
            if off:
                lines.append(kodi.string(32108) % ", ".join(kodi.string(ART_LABELS[a]) for a in off))
            kodi.ok_dialog("[CR]".join(lines))

    def full_pass(self, interactive=False):
        config = self.config()
        if interactive and config.enabled and not config.api_key:
            kodi.ok_dialog(kodi.string(32103))
            return
        syncer = self.syncer(config)
        dialog = None
        if interactive:
            dialog = xbmcgui.DialogProgressBG()
            dialog.create(kodi.ADDON.getAddonInfo("name"), kodi.string(32104 if config.enabled else 32109))
        try:
            def progress(done, total):
                if dialog:
                    dialog.update(int(done * 100 / max(total, 1)))
            changed = syncer.run_all(progress)
        except kodi.RpcError as e:
            kodi.log("Library pass failed: %s" % e, xbmc.LOGERROR)
            return
        finally:
            if dialog:
                dialog.close()
            self._remember_writes(syncer)
        if not config.enabled and changed:
            # The originals are back: our cached images are just dead weight.
            self.library.remove_textures(config.base_url + "/")
        kodi.log("Library pass (%s): %d items changed" % ("on" if config.enabled else "off", changed))
        if interactive:
            kodi.notify(kodi.string(32105 if config.enabled else 32106) % changed)

    def restore(self):
        # Turning the add-on off is what keeps the originals in place across
        # later scans; the settings change itself would trigger the same pass,
        # this just runs it now with a progress bar.
        kodi.ADDON.setSetting("enabled", "false")
        self.monitor.full_pass_at = None
        self.full_pass(interactive=True)

    def refresh_textures(self, force=False):
        days = kodi.setting_int("refresh_days", 7)
        last = self.store.get("last_refresh", 0)
        if not force and (days <= 0 or time.time() - last < days * DAY):
            return
        removed = self.library.remove_textures(self.config().base_url + "/")
        self.store.set("last_refresh", time.time())
        self.store.set("local_refresh_after", time.time())
        if force:
            self.store.set("local_artwork_cooldown", {})
        self.store.save()
        self.monitor.schedule_full_pass()
        kodi.log("Ratings refresh: %d cached images dropped" % removed)

    def item_pass(self):
        now = time.time()
        due = [k for k, t in self.monitor.items.items() if now - t >= DEBOUNCE]
        if not due:
            return
        syncer = self.syncer(self.config())
        for key in due:
            del self.monitor.items[key]
            if now - self.recent_writes.get(key, 0) < OWN_WRITE_WINDOW:
                continue
            try:
                syncer.run_item(*key)
            except kodi.RpcError as e:
                kodi.log("Item update failed: %s" % e, xbmc.LOGWARNING)
        self._remember_writes(syncer)

    # -- loop -------------------------------------------------------------

    def start(self):
        if self.store.get("last_refresh") is None:
            # First run: start the clock instead of dropping images just fetched.
            self.store.set("last_refresh", time.time())
            self.store.save()
        config = self.config()
        if config.enabled and config.api_key:
            self.verify(interactive=False)
        self.monitor.schedule_full_pass()

    def tick(self):
        while self.monitor.actions:
            action = self.monitor.actions.pop(0)
            if action == "verify":
                self.verify(interactive=True)
            elif action == "apply":
                kodi.ADDON.setSetting("enabled", "true")
                self.verify(interactive=False)
                self.monitor.full_pass_at = None
                self.full_pass(interactive=True)
            elif action == "restore":
                self.restore()
            elif action == "refresh":
                self.refresh_textures(force=True)
                kodi.notify(kodi.string(32110))
            elif action == "new_installation_id":
                # New ID = new artwork URLs: the full pass writes them everywhere
                self.installation_id(new=True)
                self.monitor.schedule_full_pass()
                kodi.notify(kodi.string(32111))
        if kodi.is_scanning():
            return
        pending = self.monitor.full_pass_at
        if pending and time.time() >= pending:
            self.monitor.full_pass_at = None
            self.monitor.items.clear()
            self.full_pass()
        self.item_pass()
        if time.time() >= self.next_refresh_check:
            self.next_refresh_check = time.time() + REFRESH_CHECK_EVERY
            self.refresh_textures()
            config = self.config()
            if config.enabled and config.api_key and self.local_cache(config).needs_refresh():
                self.monitor.schedule_full_pass()

    def run(self):
        kodi.log("Service started")
        # Let Kodi finish starting up before reading the whole library.
        if self.monitor.waitForAbort(15):
            return
        self.start()
        while not self.monitor.waitForAbort(1):
            self.tick()
        kodi.log("Service stopped")
