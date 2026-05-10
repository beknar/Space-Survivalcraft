"""Input-handler re-export shim.

The actual handlers were extracted into three topical modules in
the 2026-05-10 split:

* ``input_handlers_keys``     -- ``handle_key_press`` + the three
                                 ability triggers (force wall,
                                 death blossom, misty step).
* ``input_handlers_mouse``    -- ``handle_mouse_press`` /
                                 ``handle_mouse_motion`` /
                                 ``handle_mouse_scroll`` plus the
                                 craft-action / world-click /
                                 trade-action / death-action
                                 helpers they invoke.
* ``input_handlers_dragdrop`` -- ``handle_mouse_drag`` /
                                 ``handle_mouse_release`` plus the
                                 long-press building-move state
                                 machine and the four ``_eject_to_*``
                                 routers.

This shim re-exports every public + private name so existing
``from input_handlers import handle_*`` and
``import input_handlers as _ih; _ih.handle_*`` style imports keep
working.
"""
from __future__ import annotations

from input_handlers_keys import (
    handle_key_press,
    _try_force_wall,
    _try_death_blossom,
    _try_misty_step,
)
from input_handlers_mouse import (
    handle_mouse_press,
    handle_mouse_motion,
    handle_mouse_scroll,
    _apply_craft_action,
    _screen_to_world,
    _handle_world_click,
    apply_trade_action,
    _handle_death_action,
)
from input_handlers_dragdrop import (
    handle_mouse_drag,
    handle_mouse_release,
    _try_start_building_move,
    _update_pending_building_move,
    _clamp_turret_position,
    _finish_building_move,
    _is_valid_move_target,
    _handle_station_drop,
    _eject_to_module_slot,
    _eject_to_quick_use,
    _eject_to_station_inv,
    _eject_iron_to_world,
    _handle_inventory_eject,
)

__all__ = [
    # keys
    "handle_key_press",
    "_try_force_wall", "_try_death_blossom", "_try_misty_step",
    # mouse
    "handle_mouse_press", "handle_mouse_motion", "handle_mouse_scroll",
    "_apply_craft_action", "_screen_to_world", "_handle_world_click",
    "apply_trade_action", "_handle_death_action",
    # drag/drop
    "handle_mouse_drag", "handle_mouse_release",
    "_try_start_building_move", "_update_pending_building_move",
    "_clamp_turret_position", "_finish_building_move",
    "_is_valid_move_target",
    "_handle_station_drop",
    "_eject_to_module_slot", "_eject_to_quick_use",
    "_eject_to_station_inv", "_eject_iron_to_world",
    "_handle_inventory_eject",
]
