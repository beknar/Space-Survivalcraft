"""Integration tests for ``bot_api`` -- spins up a real HTTP
server backed by a stub ``gv``, hits ``/state`` / ``/intent`` /
``/assist`` over localhost, and asserts the wire contract holds.

Skipped automatically on CI / non-Windows boxes that don't have
a free port; uses port 18765 to avoid clashing with a live game.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest


API_PORT = 18765    # different from prod (8765) so a live game doesn't conflict
API_BASE = f"http://127.0.0.1:{API_PORT}"


def _stub_gv():
    weapons = [
        SimpleNamespace(name="Basic Laser"),
        SimpleNamespace(name="Mining Beam"),
        SimpleNamespace(name="Melee"),
    ]
    gv = SimpleNamespace(
        player=SimpleNamespace(
            center_x=3200.0, center_y=3200.0, heading=0.0,
            vel_x=0.0, vel_y=0.0,
            hp=100, max_hp=100, shields=150, max_shields=150,
        ),
        _weapons=weapons,
        _weapon_idx=0,
        _ability_meter=100,
        _ability_meter_max=100,
        _faction="Earth",
        _ship_type="Aegis",
        _ship_level=1,
        _zone=SimpleNamespace(
            zone_id="ZoneID.MAIN", world_width=6400, world_height=6400),
        _boss=None,
        _nebula_boss=None,
        alien_list=[],
        asteroid_list=[],
        building_list=[],
        iron_pickup_list=[],
        blueprint_pickup_list=[],
        inventory=SimpleNamespace(_items={}, _open=False),
        _build_menu_open=False,
        _escape_menu_open=False,
        _player_dead=False,
        _dialogue_open=False,
    )
    gv._active_weapon = weapons[0]
    return gv


@pytest.fixture(scope="module")
def api_server():
    """Start the API on a non-default port for the duration of
    the module, then shut it down."""
    import bot_api
    gv = _stub_gv()
    bot_api.start_api(gv, host="127.0.0.1", port=API_PORT)
    # Wait for the socket to actually bind.
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            with urlopen(f"{API_BASE}/health", timeout=0.5) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)
    yield gv
    bot_api.stop_api()


def _get_json(path: str) -> dict:
    with urlopen(f"{API_BASE}{path}", timeout=2.0) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(path: str, body: dict) -> dict:
    req = Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=2.0) as r:
        return json.loads(r.read().decode("utf-8"))


# ── Endpoint contracts ────────────────────────────────────────────────────


class TestHealth:
    def test_health_responds(self, api_server):
        s = _get_json("/health")
        assert s["ok"] is True
        assert "version" in s


class TestState:
    def test_state_returns_full_payload(self, api_server):
        s = _get_json("/state")
        for k in ("player", "weapon", "ability", "zone", "menu",
                  "intent", "asteroids", "aliens", "buildings",
                  "iron_pickups", "blueprint_pickups", "assist"):
            assert k in s

    def test_state_reflects_player_position(self, api_server):
        s = _get_json("/state")
        assert s["player"]["x"] == 3200.0
        assert s["player"]["faction"] == "Earth"


class TestIntent:
    def test_get_intent_default(self, api_server):
        s = _get_json("/intent")
        assert "type" in s

    def test_post_intent_round_trip(self, api_server):
        r = _post_json("/intent", {"type": "mine_nearest"})
        assert r["ok"] is True
        s = _get_json("/intent")
        assert s["type"] == "mine_nearest"

    def test_state_carries_current_intent(self, api_server):
        _post_json("/intent", {"type": "engage_boss"})
        s = _get_json("/state")
        assert s["intent"]["type"] == "engage_boss"

    def test_post_intent_rejects_missing_type(self, api_server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post_json("/intent", {"foo": "bar"})
        assert exc.value.code == 400


class TestAssistToggle:
    def test_post_assist_round_trip(self, api_server):
        r = _post_json("/assist", {"enabled": False})
        assert r["ok"] is True
        assert r["assist"]["enabled"] is False
        # Re-enable so other tests don't see a side effect.
        _post_json("/assist", {"enabled": True})


class TestUnknownPath:
    def test_get_unknown_path_404(self, api_server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get_json("/no-such-endpoint")
        assert exc.value.code == 404
