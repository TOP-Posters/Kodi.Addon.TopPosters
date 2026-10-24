import io
import json
from urllib.error import HTTPError, URLError

from resources.lib import api


def payload(**over):
    data = {
        "valid": True, "is_active": True, "tier_name": "Pro",
        "tier_info": {"features": {"episode_thumbnails": False}},
        "banners": {"allowed": True, "enabled": False},
        "backgrounds": {"allowed": False, "enabled": False},
    }
    data.update(over)
    return data


class FakeResponse(io.BytesIO):
    pass


def test_parse_verify_caps_and_dashboard_hints():
    status = api.parse_verify(payload())
    assert status.state == api.VALID and status.plan == "Pro"
    assert status.caps == {"thumb": False, "landscape": False, "fanart": False}
    assert status.off_in_dashboard == ["landscape"]


def test_verify_key_states(monkeypatch):
    def respond(result):
        def fake_urlopen(request, timeout=0):
            assert request.full_url == "https://api.example/auth/verify/TP-a%2Fb"
            if isinstance(result, Exception):
                raise result
            return FakeResponse(json.dumps(result).encode())
        monkeypatch.setattr(api, "urlopen", fake_urlopen)
        return api.verify_key("https://api.example/", "TP-a/b", "Kodi").state

    assert respond(payload()) == api.VALID
    assert respond(payload(is_active=False)) == api.INVALID
    assert respond(HTTPError("u", 404, "nf", {}, None)) == api.INVALID
    assert respond(HTTPError("u", 502, "bad", {}, None)) == api.UNREACHABLE
    assert respond(URLError("down")) == api.UNREACHABLE
