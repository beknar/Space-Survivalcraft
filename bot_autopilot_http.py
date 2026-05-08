"""HTTP client + window-focus helpers split from ``bot_autopilot``.

All POSTs to the in-game ``COO_BOT_API`` endpoint live here, plus
the ``_ensure_game_focused`` helper that activates the Call of
Orion window between polls.  The module references constants
(``API_BASE``, ``EQUIP_QUICK_USE_*``) on ``bot_autopilot`` via
the ``_ap`` alias so the autopilot keeps owning the canonical
config values.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen, Request

import bot_autopilot as _ap

try:
    import pygetwindow as gw
except ImportError:
    gw = None


def fetch_state(timeout_s: float = 0.5) -> dict | None:
    try:
        with urlopen(f"{_ap.API_BASE}/state", timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError):
        return None
    except Exception as e:
        print(f"[autopilot] fetch_state error: {e}")
        return None


def _post_build_starter_base(timeout_s: float = 5.0) -> dict | None:
    """POST /build_starter_base on the in-game HTTP API.  Returns
    the parsed JSON response, or ``None`` on transport failure.
    The endpoint is synchronous — the entire build sequence runs
    in the HTTP-handler thread before the response is sent."""
    try:
        req = Request(
            f"{_ap.API_BASE}/build_starter_base",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] build POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] build POST unexpected error: {e}")
        return None


def _post_craft(target: str, timeout_s: float = 5.0) -> dict | None:
    """POST /craft to start a Basic Crafter cycle for ``target``
    (a MODULE_TYPES key, ``"repair_pack"``, or ``"shield_recharge"``).
    Returns the parsed response dict (with ``ok`` flag) or ``None``
    on transport failure."""
    try:
        import json
        req = Request(
            f"{_ap.API_BASE}/craft",
            data=json.dumps({"target": target}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] craft POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] craft POST unexpected error: {e}")
        return None


def _post_install_module(mod_key: str,
                          timeout_s: float = 5.0) -> dict | None:
    """POST /install_module to install one ``mod_<mod_key>`` from
    station inventory into the next free ship slot.  Returns the
    parsed response dict or ``None`` on transport failure."""
    try:
        import json
        req = Request(
            f"{_ap.API_BASE}/install_module",
            data=json.dumps({"mod_key": mod_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] install POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] install POST unexpected error: {e}")
        return None


def _post_deposit_to_station(timeout_s: float = 5.0) -> dict | None:
    """POST /deposit_to_station on the in-game HTTP API.  Returns
    the parsed JSON response, or ``None`` on transport failure.
    The endpoint is synchronous — the in-process deposit runs on
    the main thread and returns the moved-items dict."""
    try:
        req = Request(
            f"{_ap.API_BASE}/deposit_to_station",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] deposit POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] deposit POST unexpected error: {e}")
        return None


def _post_use_quick_use(slot: int, timeout_s: float = 5.0) -> dict | None:
    """POST /use_quick_use — consume the item in ship quick-use
    slot ``slot``.  Returns the parsed JSON response or None on
    transport failure."""
    try:
        import json
        req = Request(
            f"{_ap.API_BASE}/use_quick_use",
            data=json.dumps({"slot": int(slot)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] use_quick_use POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] use_quick_use POST unexpected error: {e}")
        return None


def _post_equip_consumables(timeout_s: float = 5.0) -> dict | None:
    """POST /equip_consumables — withdraw repair packs + shield
    recharges from station into ship inv + bind to quick-use
    slots."""
    try:
        import json
        body = {
            "repair_slot": _ap.EQUIP_QUICK_USE_REPAIR_SLOT,
            "shield_slot": _ap.EQUIP_QUICK_USE_SHIELD_SLOT,
        }
        req = Request(
            f"{_ap.API_BASE}/equip_consumables",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] equip POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] equip POST unexpected error: {e}")
        return None


def _post_place_qwi(timeout_s: float = 10.0) -> dict | None:
    """POST /place_qwi — place a Quantum Wave Integrator near the
    Home Station.  Auto-spawns the Double Star boss on success."""
    try:
        import json
        req = Request(
            f"{_ap.API_BASE}/place_qwi",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] place_qwi POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] place_qwi POST unexpected error: {e}")
        return None


def _ensure_game_focused() -> None:
    """Activate the game window so pyautogui keystrokes reach
    it.  No-op on non-Windows or if pygetwindow isn't installed.
    Called periodically from main()."""
    if gw is None:
        return
    try:
        for w in gw.getAllWindows():
            if "Call of Orion" in (w.title or ""):
                # Skip if already active to avoid focus thrash.
                try:
                    if hasattr(w, "isActive") and w.isActive:
                        return
                except Exception:
                    pass
                try:
                    w.activate()
                except Exception:
                    pass
                return
    except Exception:
        pass
