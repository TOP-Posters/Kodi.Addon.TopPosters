"""Builds the installable add-on zip: dist/service.topposters-<version>.zip"""

import os
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = "service.topposters"
SOURCE = os.path.join(ROOT, ADDON_ID)


def main():
    version = ET.parse(os.path.join(SOURCE, "addon.xml")).getroot().get("version")
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    target = os.path.join(dist, "%s-%s.zip" % (ADDON_ID, version))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, dirs, files in os.walk(SOURCE):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
            for name in sorted(files):
                if name.endswith(".pyc") or name.startswith("."):
                    continue
                path = os.path.join(folder, name)
                # Kodi expects the add-on folder at the top of the zip.
                zf.write(path, os.path.relpath(path, ROOT))
    print(target)


if __name__ == "__main__":
    main()
