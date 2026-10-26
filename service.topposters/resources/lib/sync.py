"""Walks the video library and brings every item's artwork in line with the
settings: our URLs where they are wanted, the originals everywhere else."""

from resources.lib.artwork import DEFAULT_BASE_URL, MANAGED_ART, UrlBuilder, is_remote, media_ref, reconcile, unwrap


class Config(object):
    def __init__(self, enabled=True, api_key="", base_url=DEFAULT_BASE_URL, movies=True, tvshows=True,
                 toggles=None, caps=None):
        # Off means "put every original back": the same pass, wanting nothing.
        self.enabled = enabled
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.movies = movies
        self.tvshows = tvshows
        # Keys: poster, season_poster, thumb, landscape, fanart, clearlogo
        self.toggles = toggles or {}
        # What the plan allows, from the last key check (None = unknown)
        self.caps = caps

    def wants(self, kind, art_type):
        if not self.enabled or not self.api_key:
            return False
        if not (self.movies if kind == "movie" else self.tvshows):
            return False
        if not self.toggles.get("season_poster" if kind == "season" else art_type):
            return False
        return (self.caps or {}).get(art_type) is not False


class Syncer(object):
    def __init__(self, library, config, store, should_stop=None, local_cache=None):
        self.library = library
        self.config = config
        self.store = store
        self.should_stop = should_stop or (lambda: False)
        self.local_cache = local_cache
        self.urls = UrlBuilder(config.base_url, config.api_key)
        # URLs from the default server count as ours even when a custom one is
        # set, so switching servers never mistakes them for originals.
        self.prefixes = tuple(set([DEFAULT_BASE_URL + "/", config.base_url + "/"]))
        # (kind, dbid) of every item written, so the service can ignore the
        # library notifications our own writes cause.
        self.written = []

    def is_ours(self, url):
        return url.startswith(self.prefixes) or bool(self.local_cache and self.local_cache.is_ours(url))

    def _apply(self, kind, item, make_url):
        dbid = item[kind + "id"]
        art = item.get("art") or {}
        current = dict((t, unwrap(art.get(t))) for t in MANAGED_ART[kind])
        if self.local_cache:
            for url in current.values():
                self.local_cache.remember_current(url)
        saved = self.store.originals(kind, dbid)
        before = dict(saved)
        def safe_url(art_type, original):
            target = make_url(art_type, original)
            if target and original and not is_remote(original):
                return self.local_cache.select(target, original) if self.local_cache else original
            return target
        changes = reconcile(MANAGED_ART[kind], current, saved, safe_url, self.is_ours)
        if saved != before:
            self.store.touch()
        if changes:
            self.library.set_art(kind, dbid, changes)
            self.written.append((kind, dbid))
        return bool(changes)

    def _title_maker(self, kind, ref):
        def make(art_type, original):
            if ref is None or not self.config.wants(kind, art_type):
                return None
            return self.urls.art(art_type, ref, original)
        return make

    def _season_maker(self, ref, season):
        def make(art_type, original):
            if ref is None or season < 1 or not self.config.wants("season", art_type):
                return None
            return self.urls.art(art_type, ref, original, season=season)
        return make

    def _episode_maker(self, ref, season, episode):
        def make(art_type, original):
            if ref is None or season < 1 or episode < 1 or not self.config.wants("episode", art_type):
                return None
            return self.urls.episode_thumb(ref, season, episode, original)
        return make

    def movie(self, item):
        return self._apply("movie", item, self._title_maker("movie", media_ref("movie", item.get("uniqueid"))))

    def tvshow(self, show, with_children=True):
        ref = media_ref("tvshow", show.get("uniqueid"))
        changed = int(self._apply("tvshow", show, self._title_maker("tvshow", ref)))
        if with_children:
            for season in self.library.seasons(show["tvshowid"]):
                if self.should_stop():
                    return changed
                changed += self.season(season, ref)
            for episode in self.library.episodes(show["tvshowid"]):
                if self.should_stop():
                    break
                changed += self.episode(episode, ref)
        return changed

    def season(self, item, ref):
        return int(self._apply("season", item, self._season_maker(ref, item.get("season", -1))))

    def episode(self, item, ref):
        maker = self._episode_maker(ref, item.get("season", -1), item.get("episode", -1))
        return int(self._apply("episode", item, maker))

    def run_all(self, progress=None):
        """Whole library. Returns how many items were changed."""
        movies = self.library.movies()
        shows = self.library.tvshows()
        total = len(movies) + len(shows)
        changed = done = 0
        try:
            for item in movies:
                if self.should_stop():
                    return changed
                changed += self.movie(item)
                done += 1
                if progress:
                    progress(done, total)
            for show in shows:
                if self.should_stop():
                    return changed
                changed += self.tvshow(show)
                done += 1
                if progress:
                    progress(done, total)
            if self.local_cache and not self.should_stop():
                self.local_cache.complete()
            return changed
        finally:
            self.store.save()

    def run_item(self, kind, dbid):
        """One item, after Kodi reports it changed (a refresh rewrites its art)."""
        try:
            item = self.library.details(kind, dbid)
            if not item:
                return 0
            if kind == "movie":
                return int(self.movie(item))
            if kind == "tvshow":
                return self.tvshow(item)
            show = self.library.details("tvshow", item["tvshowid"])
            ref = media_ref("tvshow", (show or {}).get("uniqueid"))
            if kind == "season":
                return self.season(item, ref)
            if kind == "episode":
                return self.episode(item, ref)
            return 0
        finally:
            self.store.save()
