"""Parked-ship collision handlers.

Extracted from ``collisions`` in the 2026-05-10 split.  Covers
both the per-frame projectile-vs-parked-ship loop (alien lasers,
player lasers w/ AI-pilot friendly-fire immunity, boss lasers) and
the death routine that scatters cargo + module pickups on a ring
around the destroyed hull.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from sprites.explosion import HitSpark

from collisions_common import _drop_scatter

if TYPE_CHECKING:
    from game_view import GameView


def _destroy_parked_ship(gv: GameView, ship) -> None:
    """Destroy a parked ship, dropping cargo + modules as pickups.

    Cargo dumps used to spawn every pickup at the exact ship centre,
    which stacked them into a single hard-to-distinguish blob.  Now
    every item is placed on an evenly-spaced ring around the death
    point via ``_drop_scatter`` so the player can tell what dropped
    at a glance and the auto-attraction code picks them up cleanly.
    """
    gv._spawn_explosion(ship.center_x, ship.center_y)
    from update_logic import play_sfx_at
    play_sfx_at(gv, gv._explosion_snd,
                ship.center_x, ship.center_y, base_volume=0.7)
    cargo_drops: list[tuple[str, int]] = []
    for (_r, _c), (item_type, count) in ship.cargo_items.items():
        if item_type in ("iron", "copper") and count > 0:
            cargo_drops.append((item_type, count))
    module_drops: list[str] = [m for m in ship.module_slots if m is not None]
    total = len(cargo_drops) + len(module_drops)
    positions = _drop_scatter(ship.center_x, ship.center_y, total)
    pos_i = 0
    for item_type, count in cargo_drops:
        x, y = positions[pos_i]
        pos_i += 1
        gv._spawn_iron_pickup(x, y, amount=count)
    _bp_icons = getattr(gv, "_blueprint_drop_tex", {}) or {}
    for mod in module_drops:
        x, y = positions[pos_i]
        pos_i += 1
        from sprites.pickup import BlueprintPickup
        tex = _bp_icons.get(mod, gv._blueprint_tex)
        bp = BlueprintPickup(tex, x, y, module_type=mod)
        bp.item_type = f"mod_{mod}"
        gv.blueprint_pickup_list.append(bp)
    ship.remove_from_sprite_lists()


def handle_parked_ship_damage(gv: GameView) -> None:
    """All projectiles (alien, player, boss, turret) vs parked ships."""
    if len(gv._parked_ships) == 0:
        return
    for proj in list(gv.alien_projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
        if hits:
            ship = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            ship.take_damage(int(proj.damage))
            if ship.hp <= 0:
                _destroy_parked_ship(gv, ship)
    for proj in list(gv.projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
        if not hits:
            continue
        ship = hits[0]
        if getattr(ship, "has_ai_pilot", False):
            continue
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        ship.take_damage(int(proj.damage))
        if ship.hp <= 0:
            _destroy_parked_ship(gv, ship)
    if gv._boss is not None:
        for proj in list(gv._boss_projectile_list):
            hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
            if hits:
                ship = hits[0]
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                proj.remove_from_sprite_lists()
                ship.take_damage(int(proj.damage))
                if ship.hp <= 0:
                    _destroy_parked_ship(gv, ship)
