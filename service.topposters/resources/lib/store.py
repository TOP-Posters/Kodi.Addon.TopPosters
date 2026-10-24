"""Add-on state in the profile folder: the original artwork we replaced (so it
can always be put back), when textures were last refreshed and what the
API key's plan allows."""

import json
import os


class Store(object):
    def __init__(self, path):
        self.path = path
        self.data = {}
        self.dirty = False
        try:
            with open(path, "r") as f:
                self.data = json.load(f)
        except (IOError, OSError, ValueError):
            self.data = {}
        self.data.setdefault("originals", {})

    def originals(self, kind, dbid):
        """This item's saved originals, created on demand; empty records are
        dropped again on save."""
        return self.data["originals"].setdefault("%s:%d" % (kind, dbid), {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.dirty = True

    def touch(self):
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        self.data["originals"] = dict((k, v) for k, v in self.data["originals"].items() if v)
        folder = os.path.dirname(self.path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)
        self.dirty = False
