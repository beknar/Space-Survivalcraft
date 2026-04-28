"""In-process state-broadcast API for Call of Orion.

Runs an HTTP server on a background daemon thread.  The server
exposes the live game state as JSON so an external autopilot
(``bot_autopilot.py``) and a high-level strategist (Claude in
Claude Code, via ``bot_strategy_helper.py``) can act on
structured data instead of parsing screenshots — about three
orders of magnitude cheaper per query.

Activation:

    set COO_BOT_API=1
    python main.py

The server binds to ``127.0.0.1:8765``.  Endpoints:

    GET  /             ->  health check + version
    GET  /state        ->  full game-state JSON
    GET  /intent       ->  current high-level intent
    POST /intent       ->  set the current intent (JSON body)

Intent schema (the autopilot interprets this each tick):

    {"type": "idle"}
    {"type": "goto", "x": 3200, "y": 4000}
    {"type": "mine_nearest"}
    {"type": "attack_nearest"}
    {"type": "engage_boss"}
    {"type": "retreat_to_station"}
    {"type": "build", "building": "Home Station"}
    {"type": "cycle_weapon", "to": "Mining Beam"}

Unknown intent types are kept verbatim — the autopilot logs
them and falls back to ``idle`` until a known type arrives.

Threading note: the HTTP handler reads ``_gv_ref`` without a
lock; arcade's main loop also writes to GameView attributes on
the main thread.  This is racy in principle but the reads are
all read-only attribute access on simple types (floats, ints),
so a torn read at worst gives a stale value for one frame.
That's acceptable for an advisory channel — never make a
gameplay decision atomically against this state.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Set by ``start_api`` from main / GameView.  Kept module-global
# so the handler can reach it without per-request injection.
_gv_ref: Any | None = None
_intent: dict = {"type": "auto"}
_intent_lock = threading.Lock()
_started_at: float = 0.0
API_VERSION = "1.0"


# ── State extraction ──────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _player_state(gv) -> dict:
    p = gv.player
    return {
        "x": _safe(lambda: float(p.center_x), 0.0),
        "y": _safe(lambda: float(p.center_y), 0.0),
        "heading": _safe(lambda: float(p.heading), 0.0),
        "vel_x": _safe(lambda: float(p.vel_x), 0.0),
        "vel_y": _safe(lambda: float(p.vel_y), 0.0),
        "hp": _safe(lambda: int(p.hp), 0),
        "max_hp": _safe(lambda: int(p.max_hp), 0),
        "shields": _safe(lambda: int(p.shields), 0),
        "max_shields": _safe(lambda: int(p.max_shields), 0),
        "faction": _safe(lambda: gv._faction),
        "ship_type": _safe(lambda: gv._ship_type),
        "ship_level": _safe(lambda: int(gv._ship_level), 1),
    }


def _weapon_state(gv) -> dict:
    return {
        "name": _safe(lambda: gv._active_weapon.name, "Unknown"),
        "idx": _safe(lambda: int(gv._weapon_idx), 0),
    }


def _ability_state(gv) -> dict:
    return {
        "value": _safe(lambda: int(gv._ability_meter), 0),
        "max": _safe(lambda: int(gv._ability_meter_max), 100),
    }


def _zone_state(gv) -> dict:
    z = getattr(gv, "_zone", None)
    if z is None:
        return {}
    return {
        "id": _safe(lambda: str(z.zone_id), "?"),
        "world_w": _safe(lambda: int(getattr(z, "world_width", 0)), 0),
        "world_h": _safe(lambda: int(getattr(z, "world_height", 0)), 0),
    }


def _sprite_summary(sprite) -> dict:
    return {
        "x": _safe(lambda: float(sprite.center_x), 0.0),
        "y": _safe(lambda: float(sprite.center_y), 0.0),
        "hp": _safe(lambda: int(getattr(sprite, "hp", 0)), 0),
        "type": type(sprite).__name__,
    }


def _list_summary(lst, max_items: int = 100) -> list[dict]:
    if lst is None:
        return []
    out = []
    for i, sp in enumerate(lst):
        if i >= max_items:
            break
        out.append(_sprite_summary(sp))
    return out


def _pickup_summary(sprite) -> dict:
    """Like _sprite_summary but also captures the pickup's
    ``amount`` and ``item_type`` so the bot can prioritise."""
    return {
        "x": _safe(lambda: float(sprite.center_x), 0.0),
        "y": _safe(lambda: float(sprite.center_y), 0.0),
        "amount": _safe(lambda: int(getattr(sprite, "amount", 1)), 1),
        "item_type": _safe(lambda: str(getattr(sprite, "item_type", "")), ""),
        "type": type(sprite).__name__,
    }


def _pickup_list(lst, max_items: int = 200) -> list[dict]:
    if lst is None:
        return []
    out = []
    for i, sp in enumerate(lst):
        if i >= max_items:
            break
        out.append(_pickup_summary(sp))
    return out


def _boss_state(gv) -> dict | None:
    boss = getattr(gv, "_boss", None)
    if boss is None or not getattr(boss, "alive", True):
        return None
    return {
        "x": _safe(lambda: float(boss.center_x), 0.0),
        "y": _safe(lambda: float(boss.center_y), 0.0),
        "hp": _safe(lambda: int(boss.hp), 0),
        "max_hp": _safe(lambda: int(boss.max_hp), 0),
        "phase": _safe(lambda: int(getattr(boss, "_phase", 1)), 1),
    }


def _inventory_state(gv) -> dict:
    inv = getattr(gv, "inventory", None)
    if inv is None:
        return {}
    by_name: dict[str, int] = {}
    items = getattr(inv, "_items", {})
    try:
        for _cell, (name, count) in items.items():
            by_name[name] = by_name.get(name, 0) + int(count)
    except Exception:
        pass
    return {"items": by_name}


def _menu_state(gv) -> dict:
    """Best-effort: which modal (if any) is open, so the
    autopilot doesn't fight the player by spamming WASD while a
    menu is up."""
    flags = {
        "build": _safe(lambda: bool(getattr(gv, "_build_menu_open", False))),
        "inventory": _safe(lambda: bool(getattr(gv.inventory, "_open", False))),
        "escape": _safe(lambda: bool(getattr(gv, "_escape_menu_open", False))),
        "death": _safe(lambda: bool(getattr(gv, "_death_screen_open", False))),
        "dialogue": _safe(lambda: bool(getattr(gv, "_dialogue_open", False))),
    }
    return flags


def get_state(gv) -> dict:
    """Build the full state snapshot.  Errors in any single
    extractor are caught + replaced with empty defaults so a
    transient missing-attr never breaks the API."""
    assist_state = {}
    try:
        import bot_combat_assist
        assist_state = bot_combat_assist.get_state()
    except Exception:
        pass
    return {
        "ts": time.time(),
        "uptime_s": time.time() - _started_at,
        "player": _player_state(gv),
        "weapon": _weapon_state(gv),
        "ability": _ability_state(gv),
        "zone": _zone_state(gv),
        "boss": _boss_state(gv),
        "menu": _menu_state(gv),
        "inventory": _inventory_state(gv),
        "asteroids": _list_summary(_safe(lambda: gv.asteroid_list)),
        "aliens": _list_summary(_safe(lambda: gv.alien_list)),
        "buildings": _list_summary(_safe(lambda: gv.building_list)),
        "iron_pickups": _pickup_list(_safe(lambda: gv.iron_pickup_list)),
        "blueprint_pickups": _pickup_list(_safe(lambda: gv.blueprint_pickup_list)),
        "intent": dict(_intent),
        "assist": assist_state,
    }


# ── HTTP handler ──────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Silence access logging — keeps the game terminal readable.
        return

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            self._send_json(200, {
                "ok": True,
                "version": API_VERSION,
                "uptime_s": time.time() - _started_at,
            })
            return
        if self.path == "/state":
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            self._send_json(200, get_state(_gv_ref))
            return
        if self.path == "/intent":
            with _intent_lock:
                self._send_json(200, dict(_intent))
            return
        self._send_json(404, {"error": "unknown path"})

    def do_POST(self):
        if self.path == "/intent":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                self._send_json(400, {"error": f"bad JSON: {e}"})
                return
            if not isinstance(body, dict) or "type" not in body:
                self._send_json(400, {"error": "intent must be a dict with 'type'"})
                return
            global _intent
            with _intent_lock:
                _intent = body
            self._send_json(200, {"ok": True, "intent": body})
            return
        if self.path == "/build":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                self._send_json(400, {"error": f"bad JSON: {e}"})
                return
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            try:
                import building_manager as bm
                bt = body.get("type", "Home Station")
                # Place near the player.  ``offset`` is the px in
                # the +X direction relative to the player; default
                # 200 px is outside the ship's collision radius
                # but still close enough that it counts as adjacent.
                offset = float(body.get("offset", 200.0))
                gv = _gv_ref
                wx = gv.player.center_x + offset
                wy = gv.player.center_y
                bm.enter_placement_mode(gv, bt)
                bm.place_building(gv, wx, wy)
                self._send_json(200, {
                    "ok": True, "type": bt,
                    "placed_at": {"x": wx, "y": wy},
                    "buildings_now": len(gv.building_list),
                })
            except Exception as e:
                self._send_json(500, {"error": f"build failed: {e}"})
            return
        if self.path == "/assist":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                self._send_json(400, {"error": f"bad JSON: {e}"})
                return
            try:
                import bot_combat_assist
                state = bot_combat_assist.set_enabled(
                    bool(body.get("enabled", True)))
                self._send_json(200, {"ok": True, "assist": state})
            except Exception as e:
                self._send_json(500, {"error": f"assist toggle failed: {e}"})
            return
        self._send_json(404, {"error": "unknown path"})


# ── Server lifecycle ──────────────────────────────────────────────────────

_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None


def start_api(gv, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start the API in a background daemon thread.  Idempotent —
    a second call just refreshes the gv reference."""
    global _gv_ref, _server, _server_thread, _started_at
    _gv_ref = gv
    if _server is not None:
        return
    _started_at = time.time()
    _server = ThreadingHTTPServer((host, port), _Handler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, daemon=True,
        name="bot_api",
    )
    _server_thread.start()
    print(f"[bot_api] listening on http://{host}:{port}/  "
          f"(GET /state, POST /intent)")


def stop_api() -> None:
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None


def maybe_start_from_env(gv) -> None:
    """Convenience hook — start the API iff ``COO_BOT_API`` is
    truthy in the environment.  Lets the same main.py work
    with and without the bot.  Also installs the in-process
    combat-assist hook so the player ship auto-aims + fires
    on the nearest threat each frame."""
    if os.environ.get("COO_BOT_API", "").strip() not in ("", "0", "false"):
        start_api(gv)
        try:
            import bot_combat_assist
            bot_combat_assist.install(gv)
        except Exception as e:
            print(f"[bot_api] combat assist install failed: {e}")
