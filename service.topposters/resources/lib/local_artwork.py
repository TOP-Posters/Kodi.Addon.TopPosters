"""Keep local originals usable when the API cannot supply their replacement.

HTTP redirects cannot point at a file on a Kodi device or its SMB shares.
Prepare a local replacement first, retaining the last good image on failures.
"""

import hashlib
import os
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BYTES = 32 * 1024 * 1024
RETRY_SECONDS = 5 * 60
MISSING_RETRY_SECONDS = 24 * 3600
KEEP_SECONDS = 30 * 24 * 3600
_IMAGE_NAME = re.compile(r"^[a-f0-9]{64}-[a-f0-9]{32}\.(jpg|png)$")


class LocalArtworkCache(object):
    def __init__(self, store, user_agent, refresh_days=7, namespace="", opener=None, clock=None):
        self.store = store
        self.root = os.path.join(os.path.dirname(os.path.abspath(store.path)), "artwork")
        self.user_agent = user_agent
        self.refresh_days = refresh_days
        self.namespace = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        self.opener = opener or urlopen
        self.clock = clock or time.time
        self.records = store.get("local_artwork", {})
        self.seen = set()
        self.keep = set()

    def is_ours(self, path):
        if not path:
            return False
        path = os.path.abspath(path)
        return (os.path.dirname(path) == self.root
                and bool(_IMAGE_NAME.match(os.path.basename(path))))

    def remember_current(self, path):
        if self.is_ours(path):
            self.keep.add(os.path.abspath(path))

    def _path(self, record):
        name = record.get("file", "")
        path = os.path.join(self.root, name)
        return path if _IMAGE_NAME.match(name) and os.path.isfile(path) else None

    def _blocked(self, now):
        block = self.store.get("local_artwork_cooldown", {})
        return block.get("namespace") == self.namespace and block.get("until", 0) > now

    def _due(self, record, now):
        updated = record.get("updated_at", 0)
        return (not self._path(record)
                or updated < self.store.get("local_refresh_after", 0)
                or self.refresh_days > 0 and now - updated >= self.refresh_days * 24 * 3600)

    def _retry_allowed(self, record, now):
        forced = self.store.get("local_refresh_after", 0)
        return record.get("retry_after", 0) <= now or record.get("attempted_at", 0) < forced

    def needs_refresh(self):
        now = self.clock()
        return not self._blocked(now) and any(
            rec.get("active") and self._due(rec, now) and self._retry_allowed(rec, now)
            for rec in self.records.values())

    def _touch(self):
        self.store.set("local_artwork", self.records)

    def select(self, url, original):
        now = self.clock()
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        self.seen.add(key)
        record = self.records.setdefault(key, {})
        record["last_used"] = now
        record["active"] = True
        self._touch()
        cached = self._path(record)
        if cached:
            self.keep.add(cached)
        if not self._due(record, now) or not self._retry_allowed(record, now) or self._blocked(now):
            return cached or original

        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "image/jpeg,image/png",
                                        "Cache-Control": "no-cache"})
        if cached and record.get("etag"):
            request.add_header("If-None-Match", record["etag"])
        record["attempted_at"] = now
        try:
            response = self.opener(request, timeout=15)
            try:
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Image too large")
                if (mime == "image/png" and body.startswith(b"\x89PNG\r\n\x1a\n")
                        and body.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")):
                    ext = "png"
                elif mime == "image/jpeg" and body.startswith(b"\xff\xd8\xff") and body.endswith(b"\xff\xd9"):
                    ext = "jpg"
                else:
                    raise ValueError("Invalid image")
                name = "%s-%s.%s" % (key, hashlib.md5(body).hexdigest(), ext)
                path = os.path.join(self.root, name)
                self._write(path, body)
                record.update(file=name, etag=response.headers.get("ETag"), updated_at=now, retry_after=0)
                self.keep.add(path)
                return path
            finally:
                response.close()
        except HTTPError as error:
            try:
                if error.code == 304 and cached:
                    record.update(updated_at=now, retry_after=0)
                    return cached
                delay = MISSING_RETRY_SECONDS if error.code in (403, 404) else RETRY_SECONDS
                self._failed(record, now, error.code in (401, 429) or error.code >= 500, delay)
            finally:
                error.close()
        except (URLError, OSError, ValueError) as error:
            self._failed(record, now, isinstance(error, (URLError, TimeoutError)))
        return cached or original

    def _failed(self, record, now, block_all, delay=RETRY_SECONDS):
        record["retry_after"] = now + delay
        if block_all:
            self.store.set("local_artwork_cooldown", {"namespace": self.namespace, "until": now + RETRY_SECONDS})

    def _write(self, target, body):
        if os.path.isfile(target):
            return
        os.makedirs(self.root, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".download-", delete=False) as stream:
                temp = stream.name
                stream.write(body)
            os.replace(temp, target)
        finally:
            if temp and os.path.exists(temp):
                os.remove(temp)

    def complete(self):
        """Called only after a complete library pass; never delete referenced art."""
        now = self.clock()
        for key, record in list(self.records.items()):
            record["active"] = key in self.seen
            if key not in self.seen and now - record.get("last_used", now) > KEEP_SECONDS:
                del self.records[key]
            else:
                path = self._path(record)
                if path:
                    self.keep.add(path)
        self._touch()
        if not os.path.isdir(self.root):
            return
        try:
            names = os.listdir(self.root)
        except OSError:
            return
        for name in names:
            path = os.path.join(self.root, name)
            if not self.is_ours(path) or path in self.keep:
                continue
            try:
                if now - os.path.getmtime(path) > KEEP_SECONDS:
                    os.remove(path)
            except OSError:
                pass
