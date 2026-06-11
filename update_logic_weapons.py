"""Per-frame weapons update.

Extracted from ``update_logic`` in the 2026-05-10 split.  Holds the
weapon cooldown / fire / melee-blade / broadside / rear-turret tick.

The blade lifecycle (lazy-spawn / despawn / per-tick AOE damage)
itself lives in ``update_blade``; this module just calls into the
blade helpers re-exported through ``update_logic``.

``update_logic.update_weapons`` is monkey-patched at runtime by
``bot_combat_assist`` to add reflex aim-and-fire.  The patch
replaces the ``update_logic.update_weapons`` attribute and the
call site (``game_view.on_update``) does
``_ul.update_weapons(...)`` (qualified lookup), so re-exporting
this function from the shim preserves the patch contract.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import (
    BROADSIDE_COOLDOWN, BROADSIDE_DAMAGE, BROADSIDE_SPEED, BROADSIDE_RANGE,
)

if TYPE_CHECKING:
    from game_view import GameView


def update_weapons(gv: GameView, dt: float, fire: bool) -> None:
    """Tick weapon cooldowns and fire if held."""
    # Late imports through ``update_logic`` so blade-helper monkey
    # patches and existing re-export contracts keep working.
    from update_logic import (
        _ensure_melee_blade, _remove_melee_blade,
        _ensure_pickaxe_blade, _remove_pickaxe_blade,
        update_melee_blade, update_pickaxe_blade,
        disable_null_field_around_player,
    )

    for w in gv._weapons:
        w.update(dt)

    gun_count = gv.player.guns
    base_idx = (gv._weapon_idx // gun_count) * gun_count
    head_wpn = gv._weapons[base_idx]
    if head_wpn.name == "Melee":
        _ensure_melee_blade(gv, head_wpn._texture)
        _remove_pickaxe_blade(gv)
    elif head_wpn.name == "Energy Pickaxe":
        _ensure_pickaxe_blade(gv, head_wpn._texture)
        _remove_melee_blade(gv)
    else:
        _remove_melee_blade(gv)
        _remove_pickaxe_blade(gv)

    fired_any = False
    if fire:
        from sprites.explosion import HitSpark
        spawn_pts = gv.player.gun_spawn_points()
        if head_wpn.name == "Melee":
            if head_wpn._timer <= 0.0:
                head_wpn._timer = head_wpn.cooldown
                if head_wpn._snd_cd <= 0.0:
                    arcade.play_sound(head_wpn._sound, volume=0.5)
                    head_wpn._snd_cd = head_wpn._snd_min_interval
                blade = getattr(gv, "_active_blade", None)
                if blade is not None:
                    blade.start_swing()
                    fired_any = True
        elif head_wpn.name == "Energy Pickaxe":
            if head_wpn._timer <= 0.0:
                head_wpn._timer = head_wpn.cooldown
                if head_wpn._snd_cd <= 0.0:
                    arcade.play_sound(head_wpn._sound, volume=0.5)
                    head_wpn._snd_cd = head_wpn._snd_min_interval
                blade = getattr(gv, "_active_pickaxe", None)
                if blade is not None:
                    blade.start_swing()
                    fired_any = True
        elif getattr(head_wpn, "_on_foot_melee", False):
            # On-foot Electron Sword / Pick Axe — the surface zone reads
            # the held-fire + active-weapon state and applies the swing
            # (AOE damage / node mining / deflect).  No projectile here.
            pass
        else:
            for gi in range(gun_count):
                wpn = gv._weapons[base_idx + gi]
                pt = spawn_pts[gi] if gi < len(spawn_pts) else spawn_pts[0]
                proj = wpn.fire(pt[0], pt[1], gv.player.heading)
                if proj is not None:
                    gv.projectile_list.append(proj)
                    fired_any = True
                    gv.hit_sparks.append(HitSpark(pt[0], pt[1]))
    if fired_any:
        disable_null_field_around_player(gv)
    update_melee_blade(gv, dt)
    update_pickaxe_blade(gv, dt)

    if "broadside" in gv._module_slots and not gv._player_dead:
        gv._broadside_cd -= dt
        if gv._broadside_cd <= 0.0 and fire:
            gv._broadside_cd = BROADSIDE_COOLDOWN
            from sprites.projectile import Projectile
            heading = gv.player.heading
            cx, cy = gv.player.center_x, gv.player.center_y
            for angle_offset in (90.0, -90.0):
                proj = Projectile(
                    gv._broadside_tex, cx, cy,
                    heading + angle_offset,
                    BROADSIDE_SPEED, BROADSIDE_RANGE,
                    scale=1.0, mines_rock=False,
                    damage=BROADSIDE_DAMAGE,
                )
                gv.projectile_list.append(proj)

    if "rear_turret" in gv._module_slots and not gv._player_dead:
        gv._rear_turret_cd -= dt
        if gv._rear_turret_cd <= 0.0 and fire:
            gv._rear_turret_cd = BROADSIDE_COOLDOWN
            from sprites.projectile import Projectile
            heading = gv.player.heading
            cx, cy = gv.player.center_x, gv.player.center_y
            proj = Projectile(
                gv._broadside_tex, cx, cy,
                heading + 180.0,
                BROADSIDE_SPEED, BROADSIDE_RANGE,
                scale=1.0, mines_rock=False,
                damage=BROADSIDE_DAMAGE,
            )
            gv.projectile_list.append(proj)
