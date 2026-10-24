"""Thin layer over Kodi's JSON-RPC video library and texture cache."""

_PROPS = {
    "movie": ["title", "art", "uniqueid"],
    "tvshow": ["title", "art", "uniqueid"],
    "season": ["season", "tvshowid", "art"],
    "episode": ["season", "episode", "tvshowid", "art"],
}

_DETAILS = {
    "movie": ("VideoLibrary.GetMovieDetails", "movieid", "moviedetails"),
    "tvshow": ("VideoLibrary.GetTVShowDetails", "tvshowid", "tvshowdetails"),
    "season": ("VideoLibrary.GetSeasonDetails", "seasonid", "seasondetails"),
    "episode": ("VideoLibrary.GetEpisodeDetails", "episodeid", "episodedetails"),
}

_SETTERS = {
    "movie": ("VideoLibrary.SetMovieDetails", "movieid"),
    "tvshow": ("VideoLibrary.SetTVShowDetails", "tvshowid"),
    "season": ("VideoLibrary.SetSeasonDetails", "seasonid"),
    "episode": ("VideoLibrary.SetEpisodeDetails", "episodeid"),
}


class Library(object):
    def __init__(self, rpc):
        # rpc(method, params) -> the JSON-RPC "result" object
        self.rpc = rpc

    def movies(self):
        return self.rpc("VideoLibrary.GetMovies", {"properties": _PROPS["movie"]}).get("movies") or []

    def tvshows(self):
        return self.rpc("VideoLibrary.GetTVShows", {"properties": _PROPS["tvshow"]}).get("tvshows") or []

    def seasons(self, tvshowid):
        params = {"tvshowid": tvshowid, "properties": _PROPS["season"]}
        return self.rpc("VideoLibrary.GetSeasons", params).get("seasons") or []

    def episodes(self, tvshowid):
        params = {"tvshowid": tvshowid, "properties": _PROPS["episode"]}
        return self.rpc("VideoLibrary.GetEpisodes", params).get("episodes") or []

    def details(self, kind, dbid):
        method, id_field, key = _DETAILS[kind]
        return self.rpc(method, {id_field: dbid, "properties": _PROPS[kind]}).get(key)

    def set_art(self, kind, dbid, art):
        method, id_field = _SETTERS[kind]
        self.rpc(method, {id_field: dbid, "art": art})

    def remove_textures(self, url_prefix):
        """Drop cached copies of our images, so Kodi fetches fresh ratings the
        next time each one is shown (and only then)."""
        params = {
            "properties": ["url"],
            "filter": {"field": "url", "operator": "startswith", "value": url_prefix},
        }
        textures = self.rpc("Textures.GetTextures", params).get("textures") or []
        for texture in textures:
            self.rpc("Textures.RemoveTexture", {"textureid": texture["textureid"]})
        return len(textures)
