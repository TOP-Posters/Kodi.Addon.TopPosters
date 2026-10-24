"""API key check against /auth/verify/{key}."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

VALID = "valid"
INVALID = "invalid"
UNREACHABLE = "unreachable"


class KeyStatus(object):
    def __init__(self, state, plan=None, caps=None):
        self.state = state
        self.plan = plan
        # Art features the plan and the dashboard allow: {"thumb": bool,
        # "landscape": bool, "fanart": bool}. None when unknown.
        self.caps = caps
        # Features the plan includes but the user has not switched on in the
        # dashboard, worth telling them about.
        self.off_in_dashboard = []


def parse_verify(payload):
    features = (payload.get("tier_info") or {}).get("features") or {}
    banners = payload.get("banners") or {}
    backgrounds = payload.get("backgrounds") or {}
    status = KeyStatus(
        VALID,
        plan=payload.get("tier_name"),
        caps={
            "thumb": bool(features.get("episode_thumbnails")),
            "landscape": bool(banners.get("allowed") and banners.get("enabled")),
            "fanart": bool(backgrounds.get("allowed") and backgrounds.get("enabled")),
        },
    )
    if banners.get("allowed") and not banners.get("enabled"):
        status.off_in_dashboard.append("landscape")
    if backgrounds.get("allowed") and not backgrounds.get("enabled"):
        status.off_in_dashboard.append("fanart")
    return status


def verify_key(base_url, api_key, user_agent, timeout=15):
    url = "%s/auth/verify/%s" % (base_url.rstrip("/"), quote(api_key, safe=""))
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        response = urlopen(request, timeout=timeout)
        try:
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
    except HTTPError as e:
        if e.code in (401, 403, 404):
            return KeyStatus(INVALID)
        return KeyStatus(UNREACHABLE)
    except (URLError, OSError, ValueError):
        return KeyStatus(UNREACHABLE)
    if not payload.get("valid") or not payload.get("is_active", True):
        return KeyStatus(INVALID)
    return parse_verify(payload)
