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


# ── Main-thread work queue ────────────────────────────────────────────────
#
# arcade / pyglet OpenGL operations only work from the main thread that
# owns the GL context.  Sprite / texture creation is GL-backed, so HTTP
# handlers that need to spawn buildings or place sprites can't call
# building_manager.place_building directly — that triggers
# ``GL_INVALID_OPERATION (0x1282)`` from a worker thread.
#
# Submit_to_main_thread queues a callable to run on the next
# ``pump_main_thread_queue`` call, which the game loop fires from
# ``GameView.on_update``.  The HTTP handler waits on a per-call Event
# for the callable to finish, then reads the result / error.
_main_thread_queue: list = []
_main_thread_queue_lock = threading.Lock()


def submit_to_main_thread(fn):
    """Queue ``fn`` to run on the main thread the next time the
    game loop pumps the queue.  Returns ``(done_event, result_box)``;
    ``result_box`` is a dict with ``"value"`` (return value) and
    ``"error"`` (exception or None) populated once the main thread
    runs the callable."""
    done = threading.Event()
    result: dict = {"value": None, "error": None}

    def wrapper(gv):
        try:
            result["value"] = fn(gv)
        except Exception as e:
            result["error"] = e
        finally:
            done.set()

    with _main_thread_queue_lock:
        _main_thread_queue.append(wrapper)
    return done, result


def pump_main_thread_queue(gv) -> None:
    """Drain queued main-thread callables.  Called once per frame
    from ``GameView.on_update`` so HTTP handlers that need GL-
    backed mutation (sprite spawn, building placement) can run
    on the right thread.  Cheap no-op when the queue is empty."""
    with _main_thread_queue_lock:
        if not _main_thread_queue:
            return
        callables = _main_thread_queue[:]
        _main_thread_queue.clear()
    for c in callables:
        try:
            c(gv)
        except Exception as e:
            print(f"[bot_api] main-thread callable failed: {e}")


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
        # Death state -- True during the 1.5 s death-animation window
        # before respawn fires.  Bot observes the alive->dead and
        # dead->alive transitions to drive loot-recovery + boss
        # telemetry (PR 2026-05-10).
        "is_dead": _safe(lambda: bool(gv._player_dead), False),
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
        # ``building_type`` is the human-readable name set by
        # building_manager (e.g. "Home Station", "Service Module");
        # empty string for non-building sprites.  Lets the bot find
        # specific buildings (the Home Station, in particular)
        # without having to know arcade Sprite class names.
        "building_type": _safe(
            lambda: str(getattr(sprite, "building_type", "")), ""),
        # ``crafting`` + ``craft_target`` are populated by
        # ``BasicCrafter`` instances; both default to safe values
        # for non-crafter sprites.  The bot reads ``crafting`` to
        # decide whether to start a new craft cycle (only when
        # every crafter is idle) and ``craft_target`` to know which
        # module is currently in the queue.
        "crafting": _safe(
            lambda: bool(getattr(sprite, "crafting", False)), False),
        "craft_target": _safe(
            lambda: str(getattr(sprite, "craft_target", "")), ""),
        "disabled": _safe(
            lambda: bool(getattr(sprite, "disabled", False)), False),
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
    # Charge telegraph fields are only meaningful in Phase 2+ — the
    # boss class always exposes the attributes (set in __init__) so
    # the ``getattr`` defaults are belt-and-braces, not a real path.
    return {
        "x": _safe(lambda: float(boss.center_x), 0.0),
        "y": _safe(lambda: float(boss.center_y), 0.0),
        "hp": _safe(lambda: int(boss.hp), 0),
        "max_hp": _safe(lambda: int(boss.max_hp), 0),
        "phase": _safe(lambda: int(getattr(boss, "_phase", 1)), 1),
        "charging":      _safe(lambda: bool(getattr(boss, "_charging", False)), False),
        "charge_windup": _safe(lambda: float(getattr(boss, "_charge_windup", 0.0)), 0.0),
        "charge_timer":  _safe(lambda: float(getattr(boss, "_charge_timer", 0.0)), 0.0),
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


def _station_inventory_state(gv) -> dict:
    """Aggregate the home-station inventory by item name.  Mirrors
    ``_inventory_state`` for the ship side.  Empty dict if the
    station inventory hasn't been initialised yet (no Home
    Station built)."""
    inv = getattr(gv, "_station_inv", None)
    if inv is None:
        return {}
    by_name: dict[str, int] = {}
    items = getattr(inv, "_items", {}) or {}
    try:
        for _cell, (name, count) in items.items():
            by_name[name] = by_name.get(name, 0) + int(count)
    except Exception:
        pass
    return {"items": by_name}


def _module_slots_state(gv) -> list[str | None]:
    """Snapshot of ``gv._module_slots`` (None for empty slots).
    Lets the bot detect which modules are currently installed so it
    can drive the install queue without re-installing duplicates."""
    try:
        return [
            (None if s is None else str(s))
            for s in (gv._module_slots or [])
        ]
    except Exception:
        return []


def _quick_use_slots_state(gv) -> list[dict]:
    """Snapshot of the ship's quick-use bar.

    Returned as a parallel list of ``{"item_type": str | None,
    "count": int}`` entries — one per slot.  Empty slots have
    ``item_type`` = None / ``count`` = 0.  The bot reads this to
    decide whether to fire ``/use_quick_use`` for a repair pack /
    shield recharge when HP / shields drop below the use threshold.
    """
    try:
        slots = list(getattr(gv._hud, "_qu_slots", []) or [])
        counts = list(getattr(gv._hud, "_qu_counts", []) or [])
    except Exception:
        return []
    out: list[dict] = []
    for i, item in enumerate(slots):
        cnt = counts[i] if i < len(counts) else 0
        out.append({
            "item_type": (None if item is None else str(item)),
            "count": int(cnt),
        })
    return out


def _wormholes_state(gv) -> list[dict]:
    """Snapshot of the MAIN-zone wormholes (4 corner spawns).

    Each entry carries ``x``, ``y``, and ``zone_target`` (the
    stringified ZoneID the wormhole warps to).  Empty list when
    the bot is in a non-MAIN zone (wormholes are MAIN-only).

    The bot uses this to navigate to the nearest wormhole after a
    post-boss recovery is complete -- the FSM
    ``S_WARP_TO_WORMHOLE`` state reads it directly.
    """
    try:
        whs = getattr(gv, "_wormholes", None) or []
    except Exception:
        return []
    out: list[dict] = []
    for wh in whs:
        try:
            zt = getattr(wh, "zone_target", None)
            out.append({
                "x": float(wh.center_x),
                "y": float(wh.center_y),
                "zone_target": "" if zt is None else str(zt),
            })
        except Exception:
            continue
    return out


def _gas_areas_state(gv) -> list[dict]:
    """Snapshot of toxic gas clouds in the active zone, if any.

    Sourced from the active zone's ``_clouds`` SpriteList when it
    exists (the gas warp zone + its Nebula / Star-Maze variants
    expose this).  Other zones return an empty list.  Each entry
    has ``x``, ``y``, and ``radius`` -- the bot's navigation layer
    treats gas areas as a soft potential-field obstacle.
    """
    try:
        z = getattr(gv, "_zone", None)
        if z is None:
            return []
        clouds = getattr(z, "_clouds", None)
        if clouds is None:
            return []
    except Exception:
        return []
    out: list[dict] = []
    for c in clouds:
        try:
            out.append({
                "x": float(c.center_x),
                "y": float(c.center_y),
                "radius": float(getattr(c, "radius", 80.0)),
            })
        except Exception:
            continue
    return out


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


def _zone_aware_aliens(gv):
    """Same source the minimap reads — picks the right alien list
    for the current zone (gv.alien_list in MAIN, zone._aliens in
    Zone 2 / Star Maze, zone.get_minimap_objects() in warp zones).
    Without this the bot was blind in non-MAIN zones: /state.aliens
    returned an empty list while the minimap clearly showed
    enemies, so the FSM kept dropping into SEARCH and the bot
    appeared to pause."""
    try:
        from draw_logic import _minimap_enemies
        return _minimap_enemies(gv)
    except Exception:
        return getattr(gv, "alien_list", [])


def _zone_aware_asteroids(gv):
    """Zone-aware asteroid source (mirrors _minimap_obstacles) —
    same fix as _zone_aware_aliens but for the asteroid list."""
    try:
        from draw_logic import _minimap_obstacles
        return _minimap_obstacles(gv)
    except Exception:
        return getattr(gv, "asteroid_list", [])


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
        "station_inventory": _station_inventory_state(gv),
        "module_slots": _module_slots_state(gv),
        "quick_use_slots": _quick_use_slots_state(gv),
        # Zone-aware lists — pull from the same aggregators the
        # minimap uses so the bot sees what the player sees.
        "asteroids": _list_summary(_safe(lambda: _zone_aware_asteroids(gv))),
        "aliens": _list_summary(_safe(lambda: _zone_aware_aliens(gv))),
        "buildings": _list_summary(_safe(lambda: gv.building_list)),
        "iron_pickups": _pickup_list(_safe(lambda: gv.iron_pickup_list)),
        "blueprint_pickups": _pickup_list(_safe(lambda: gv.blueprint_pickup_list)),
        "wormholes": _safe(lambda: _wormholes_state(gv)) or [],
        "gas_areas": _safe(lambda: _gas_areas_state(gv)) or [],
        # ``boss_defeated`` is the GAME's persisted "main boss has
        # died in this save" flag (set in collisions_boss.py, saved
        # via game_save.py).  Survives save/load so the bot can
        # trigger its post-boss warp behaviour even on a loaded
        # game where ``boss_engage_end outcome=boss_killed`` never
        # fired this session.  Default False if the attribute is
        # missing (older game build).
        "boss_defeated": _safe(
            lambda: bool(getattr(gv, "_boss_defeated", False)),
            False),
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
            bt = body.get("type", "Home Station")
            offset = float(body.get("offset", 200.0))

            def _do_build(gv):
                """Run on the main thread — sprite + texture
                creation goes through arcade / pyglet which only
                tolerate GL ops on the GL-context thread."""
                import building_manager as bm
                wx = gv.player.center_x + offset
                wy = gv.player.center_y
                bm.enter_placement_mode(gv, bt)
                bm.place_building(gv, wx, wy)
                return {
                    "type": bt,
                    "placed_at": {"x": wx, "y": wy},
                    "buildings_now": len(gv.building_list),
                }

            done, result = submit_to_main_thread(_do_build)
            if not done.wait(timeout=10.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"build failed: {result['error']}"})
                return
            self._send_json(200, {"ok": True, **result["value"]})
            return
        if self.path == "/build_starter_base":
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                bot_builder.build_starter_base)
            if not done.wait(timeout=10.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error":
                          f"starter base build failed: {result['error']}"})
                return
            self._send_json(200, {"ok": True, **result["value"]})
            return
        if self.path == "/deposit_to_station":
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                bot_builder.deposit_ship_resources_to_station)
            if not done.wait(timeout=5.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error":
                          f"deposit failed: {result['error']}"})
                return
            self._send_json(200, {"ok": True, **result["value"]})
            return
        if self.path == "/craft":
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
            target = body.get("target", "repair_pack")
            if not isinstance(target, str) or not target:
                self._send_json(
                    400, {"error": "missing or invalid 'target'"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                lambda gv: bot_builder.start_craft(gv, target))
            if not done.wait(timeout=5.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"craft failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
            return
        if self.path == "/install_module":
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
            mod_key = body.get("mod_key", "")
            if not isinstance(mod_key, str) or not mod_key:
                self._send_json(
                    400, {"error": "missing or invalid 'mod_key'"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                lambda gv: bot_builder.install_module(gv, mod_key))
            if not done.wait(timeout=5.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"install failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
            return
        if self.path == "/equip_consumables":
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
            repair_slot = int(body.get("repair_slot", 0))
            shield_slot = int(body.get("shield_slot", 1))
            max_each = int(body.get("max_each", 25))
            import bot_builder
            done, result = submit_to_main_thread(
                lambda gv: bot_builder.equip_consumables_to_quick_use(
                    gv, repair_slot=repair_slot,
                    shield_slot=shield_slot,
                    max_each=max_each))
            if not done.wait(timeout=5.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"equip failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
            return
        if self.path == "/use_quick_use":
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
            slot = int(body.get("slot", 0))
            import bot_builder
            done, result = submit_to_main_thread(
                lambda gv: bot_builder.use_quick_use_slot(gv, slot))
            if not done.wait(timeout=5.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"use failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
            return
        if self.path == "/fortify":
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                bot_builder.fortify_base_defenses)
            if not done.wait(timeout=10.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"fortify failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
            return
        if self.path == "/place_qwi":
            if _gv_ref is None:
                self._send_json(503, {"error": "game not ready"})
                return
            import bot_builder
            done, result = submit_to_main_thread(
                bot_builder.place_quantum_wave_integrator)
            if not done.wait(timeout=10.0):
                self._send_json(
                    504, {"error": "timeout waiting for main thread"})
                return
            if result["error"] is not None:
                self._send_json(
                    500, {"error": f"qwi placement failed: {result['error']}"})
                return
            self._send_json(200, result["value"])
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
