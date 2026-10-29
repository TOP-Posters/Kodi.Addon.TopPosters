import base64
import io
import os
from urllib.error import HTTPError, URLError

import pytest

from fakekodi import FakeKodi
from resources.lib import local_artwork
from resources.lib.library import Library
from resources.lib.local_artwork import LocalArtworkCache, KEEP_SECONDS, RETRY_SECONDS
from resources.lib.store import Store
from resources.lib.sync import Config, Syncer

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
PNG2 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=")
URL = "https://api.top-posters.com/TP-private/tmdb/poster/movie-603.jpg"
ORIGINAL = "smb://nas/Movies/Matrix/poster.jpg"


class Response(io.BytesIO):
    def __init__(self, body=PNG, mime="image/png", etag='"image-v1"'):
        super().__init__(body)
        self.headers = {"Content-Type": mime, "ETag": etag}


@pytest.fixture
def env(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    now = [1000000000.0]
    calls = []
    replies = [lambda: Response()]

    def opener(request, timeout):
        calls.append(request)
        assert timeout == 15
        return replies[0]()

    def cache(**kwargs):
        return LocalArtworkCache(store, "Kodi/21 TOP Posters/1.1.0", opener=opener,
                                 clock=lambda: now[0], namespace="server|key", **kwargs)

    return store, now, calls, replies, cache


def raises(error):
    def fail():
        raise error
    return fail


def test_local_replacement_is_prepared_and_survives_restart(env):
    store, now, calls, replies, cache = env
    prepared = cache().select(URL, ORIGINAL)
    assert os.path.isfile(prepared) and open(prepared, "rb").read() == PNG
    assert "TP-private" not in prepared
    assert calls[0].get_header("User-agent").startswith("Kodi/")
    assert calls[0].get_header("Cache-control") == "no-cache"
    store.save()
    restarted = LocalArtworkCache(Store(store.path), "Kodi", opener=lambda *a, **k: pytest.fail("fresh image fetched twice"), clock=lambda: now[0])
    assert restarted.select(URL, ORIGINAL) == prepared
    assert "TP-private" not in open(store.path).read()


@pytest.mark.parametrize("error", [URLError("offline"), HTTPError(URL, 401, "invalid", {}, io.BytesIO()), HTTPError(URL, 429, "quota", {}, io.BytesIO()), HTTPError(URL, 503, "down", {}, io.BytesIO())], ids=["offline", "invalid-key", "quota", "server-error"])
def test_first_failure_keeps_original_and_limits_further_requests(env, error):
    store, now, calls, replies, cache = env
    replies[0] = raises(error)
    first = cache()
    assert first.select(URL, ORIGINAL) == ORIGINAL
    assert first.select(URL.replace("603", "604"), "/media/other.jpg") == "/media/other.jpg"
    assert len(calls) == 1
    assert not first.needs_refresh()
    now[0] += RETRY_SECONDS + 1
    assert first.needs_refresh()
    replies[0] = lambda: Response()
    assert os.path.isfile(first.select(URL, ORIGINAL))


def test_expired_image_stays_available_offline_then_recovers(env):
    store, now, calls, replies, cache = env
    prepared = cache().select(URL, ORIGINAL)
    now[0] += 8 * 24 * 3600
    replies[0] = raises(URLError("offline"))
    assert cache().select(URL, ORIGINAL) == prepared
    assert open(prepared, "rb").read() == PNG
    now[0] += RETRY_SECONDS + 1
    replies[0] = lambda: Response(PNG2, etag='"image-v2"')
    replacement = cache().select(URL, ORIGINAL)
    assert replacement != prepared and os.path.isfile(prepared) and os.path.isfile(replacement)


def test_missing_art_has_long_backoff_without_blocking_other_titles(env):
    store, now, calls, replies, cache = env
    replies[0] = raises(HTTPError(URL, 404, "missing", {}, io.BytesIO()))
    assert cache().select(URL, ORIGINAL) == ORIGINAL
    now[0] += RETRY_SECONDS + 1
    assert not cache().needs_refresh()
    replies[0] = lambda: Response()
    assert os.path.isfile(cache().select(URL.replace("603", "604"), ORIGINAL))
    assert len(calls) == 2


def test_etag_revalidation_does_not_rewrite_identical_art(env):
    store, now, calls, replies, cache = env
    prepared = cache().select(URL, ORIGINAL)
    stamp = os.stat(prepared).st_mtime_ns
    now[0] += 8 * 24 * 3600
    replies[0] = raises(HTTPError(URL, 304, "unchanged", {}, io.BytesIO()))
    assert cache().select(URL, ORIGINAL) == prepared
    assert calls[-1].get_header("If-none-match") == '"image-v1"'
    assert os.stat(prepared).st_mtime_ns == stamp
    assert not cache().needs_refresh()


def test_manual_refresh_bypasses_previous_failure_backoff(env):
    store, now, calls, replies, cache = env
    replies[0] = raises(URLError("offline"))
    assert cache().select(URL, ORIGINAL) == ORIGINAL
    now[0] += 1
    store.set("local_refresh_after", now[0])
    store.set("local_artwork_cooldown", {})
    replies[0] = lambda: Response()
    assert os.path.isfile(cache().select(URL, ORIGINAL))


def test_zero_day_schedule_keeps_cached_image_but_manual_refresh_still_works(env):
    store, now, calls, replies, cache = env
    prepared = cache(refresh_days=0).select(URL, ORIGINAL)
    now[0] += 60 * 24 * 3600
    assert cache(refresh_days=0).select(URL, ORIGINAL) == prepared
    assert len(calls) == 1
    store.set("local_refresh_after", now[0])
    assert cache(refresh_days=0).select(URL, ORIGINAL) == prepared
    assert len(calls) == 2


@pytest.mark.parametrize("body,mime", [(b'{"error":"quota"}', "application/json"), (b"html error", "image/png"), (b"not jpeg", "image/jpeg"), (PNG[:-12], "image/png")])
def test_invalid_payload_never_replaces_local_original(env, body, mime):
    store, now, calls, replies, cache = env
    replies[0] = lambda: Response(body, mime)
    assert cache().select(URL, ORIGINAL) == ORIGINAL


def test_oversized_response_and_failed_atomic_write_keep_original(env, monkeypatch):
    store, now, calls, replies, cache = env
    monkeypatch.setattr(local_artwork, "MAX_BYTES", 8)
    assert cache().select(URL, ORIGINAL) == ORIGINAL
    monkeypatch.setattr(local_artwork, "MAX_BYTES", 32 * 1024 * 1024)
    now[0] += RETRY_SECONDS + 1
    monkeypatch.setattr(local_artwork.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert cache().select(URL, ORIGINAL) == ORIGINAL
    assert not list(__import__("pathlib").Path(cache().root).glob(".download-*"))


def test_sync_migrates_old_http_urls_and_restores_exact_local_original(env):
    store, now, calls, replies, cache = env
    kodi = FakeKodi()
    kodi.add("movie", 1, {"poster": URL}, uniqueid={"tmdb": "603"})
    store.originals("movie", 1)["poster"] = ORIGINAL
    store.touch()
    config = Config(api_key="TP-private", toggles={"poster": True})
    sync = Syncer(Library(kodi.rpc), config, store, local_cache=cache())
    assert sync.run_all() == 1
    assert cache().is_ours(kodi.art("movie", 1)["poster"])
    assert store.originals("movie", 1)["poster"] == ORIGINAL
    assert "fallback_url" not in calls[0].full_url
    restored = Syncer(Library(kodi.rpc), Config(enabled=False), store, local_cache=cache())
    assert restored.run_all() == 1
    assert kodi.art("movie", 1)["poster"] == ORIGINAL


def test_failed_upgrade_from_old_http_art_puts_local_original_back(env):
    store, now, calls, replies, cache = env
    kodi = FakeKodi()
    kodi.add("movie", 1, {"poster": URL}, uniqueid={"tmdb": "603"})
    store.originals("movie", 1)["poster"] = ORIGINAL
    replies[0] = raises(URLError("offline"))
    sync = Syncer(Library(kodi.rpc), Config(api_key="TP-private", toggles={"poster": True}), store, local_cache=cache())
    assert sync.run_all() == 1
    assert kodi.art("movie", 1)["poster"] == ORIGINAL


def test_remote_originals_stay_lazy_and_specials_remain_untouched(env):
    store, now, calls, replies, cache = env
    kodi = FakeKodi()
    kodi.add("tvshow", 1, {"poster": "https://image.tmdb.org/show.jpg"}, uniqueid={"tmdb": "1"})
    kodi.add("season", 2, {"poster": "/local/specials.jpg"}, tvshowid=1, season=0)
    kodi.add("episode", 3, {"thumb": "/local/special.jpg"}, tvshowid=1, season=0, episode=1)
    sync = Syncer(Library(kodi.rpc), Config(api_key="TP-key", toggles={"poster": True, "season_poster": True, "thumb": True}), store, local_cache=cache())
    sync.run_all()
    assert calls == []
    assert kodi.art("tvshow", 1)["poster"].startswith("https://api.top-posters.com/")
    assert kodi.art("season", 2)["poster"] == "/local/specials.jpg"
    assert kodi.art("episode", 3)["thumb"] == "/local/special.jpg"


def test_cleanup_keeps_referenced_art_and_removes_only_old_unused_generated_files(env):
    store, now, calls, replies, cache = env
    first = cache()
    prepared = first.select(URL, ORIGINAL)
    unreferenced = os.path.join(first.root, "a" * 64 + "-" + "b" * 32 + ".png")
    with open(unreferenced, "wb") as stream:
        stream.write(PNG)
    unrelated = os.path.join(first.root, "user-image.png")
    with open(unrelated, "wb") as stream:
        stream.write(PNG)
    for path in [prepared, unreferenced, unrelated]:
        os.utime(path, (now[0] - KEEP_SECONDS - 1,) * 2)
    first.remember_current(prepared)
    first.complete()
    assert os.path.isfile(prepared) and os.path.isfile(unrelated)
    assert not os.path.exists(unreferenced)


def test_cancelled_library_pass_does_not_prune_unvisited_art(env):
    store, now, calls, replies, cache = env
    kodi = FakeKodi()
    kodi.add("movie", 1, {"poster": ORIGINAL}, uniqueid={"tmdb": "603"})
    local = cache()
    local.complete = lambda: pytest.fail("partial pass must not prune artwork")
    sync = Syncer(Library(kodi.rpc), Config(api_key="TP-key", toggles={"poster": True}), store, should_stop=lambda: True, local_cache=local)
    assert sync.run_all() == 0 and calls == []
