"""Null fields, slipspaces, force walls — per-zone special effects.

Extracted from ``update_logic.py``.  These three subsystems share a
common pattern: each operates on a per-zone list (Zone 1 fields on
``gv``, Zone 2 fields on ``zone``), with helpers that walk both lists
when an action might affect either side.

Public functions are re-exported from ``update_logic`` so existing
``from update_logic import active_null_fields`` call sites in
draw_logic / collisions / combat_helpers / input_handlers continue
to work without churn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

if TYPE_CHECKING:
    from game_view import GameView


# ── Null fields ─────────────────────────────────────────────────────────

def active_null_fields(gv: "GameView") -> list:
    """Return the null-field list for the zone the player is currently
    in.  Used by the cloaking gate + the fire-disable hook + drawing.

    Warp zones (meteor / lightning / gas / enemy) never host null
    fields, so when the player is in one we return ``[]`` rather than
    falling through to ``gv._null_fields`` (which belongs to Zone 1)."""
    from zones import ZoneID
    zone = getattr(gv, "_zone", None)
    zone_fields = getattr(zone, "_null_fields", None)
    if zone_fields:
        return zone_fields
    if getattr(zone, "zone_id", None) is ZoneID.MAIN:
        return getattr(gv, "_null_fields", None) or []
    return []


def find_null_field_at(gv: "GameView", x: float, y: float):
    """Return the first null field (in the active zone's list) that
    contains ``(x, y)``, or ``None``.  Used by the fire-disable hook."""
    for nf in active_null_fields(gv):
        if nf.contains_point(x, y):
            return nf
    return None


def disable_null_field_around_player(gv: "GameView") -> None:
    """Disable every null field containing the player's current
    position for ``NULL_FIELD_DISABLE_S`` seconds.  Called whenever the
    player fires a weapon or triggers an ability from inside one."""
    px, py = gv.player.center_x, gv.player.center_y
    for nf in active_null_fields(gv):
        if nf.contains_point(px, py):
            nf.trigger_disable()


def player_is_cloaked(gv: "GameView") -> bool:
    """True when the player is inside an ACTIVE null field (not one
    currently serving a 30-second disable penalty)."""
    if getattr(gv, "_player_dead", False):
        return False
    px, py = gv.player.center_x, gv.player.center_y
    for nf in active_null_fields(gv):
        if nf.active and nf.contains_point(px, py):
            return True
    return False


def update_null_fields(gv: "GameView", dt: float) -> None:
    """Tick disabled-timer animation on every null field in the
    active zone (and the Zone 1 fields too, so Zone 2 -> Zone 1
    transitions don't leave a stale disable on a Zone 1 field)."""
    seen: set = set()
    z1 = getattr(gv, "_null_fields", None) or []
    for nf in z1:
        if id(nf) not in seen:
            nf.update_null_field(dt)
            seen.add(id(nf))
    zone = getattr(gv, "_zone", None)
    z2 = getattr(zone, "_null_fields", None) or []
    for nf in z2:
        if id(nf) not in seen:
            nf.update_null_field(dt)
            seen.add(id(nf))


# ── Slipspaces ──────────────────────────────────────────────────────────

def active_slipspaces(gv: "GameView"):
    """Return the slipspace SpriteList for the player's current zone.

    Zone 2 stores its own list on ``zone._slipspaces``; Zone 1 stores
    them on ``gv._slipspaces``.  Warp zones return ``[]`` because they
    deliberately don't host slipspaces — same rule as null fields."""
    from zones import ZoneID
    zone = getattr(gv, "_zone", None)
    zone_ss = getattr(zone, "_slipspaces", None)
    if zone_ss:
        return zone_ss
    if getattr(zone, "zone_id", None) is ZoneID.MAIN:
        return getattr(gv, "_slipspaces", None) or []
    return []


def update_slipspaces(gv: "GameView", dt: float) -> None:
    """Rotate every slipspace in the active zone (plus Zone 1's even
    when the player is elsewhere, to keep the texture animation stable
    on zone return — same dual-walk pattern as ``update_null_fields``).
    Then run the teleport collision check against the active list."""
    seen: set = set()
    z1 = getattr(gv, "_slipspaces", None) or []
    for ss in z1:
        if id(ss) not in seen:
            ss.update_slipspace(dt)
            seen.add(id(ss))
    zone = getattr(gv, "_zone", None)
    z2 = getattr(zone, "_slipspaces", None) or []
    for ss in z2:
        if id(ss) not in seen:
            ss.update_slipspace(dt)
            seen.add(id(ss))
    _check_slipspace_teleport(gv)


def _check_slipspace_teleport(gv: "GameView") -> None:
    """Teleport the player to a random other slipspace if they're
    inside one and weren't inside it last frame.  Velocity + heading
    are preserved.  ``gv._inside_slipspace`` blocks re-trigger while
    the player is still overlapping the destination, so the jump
    fires exactly once per entry."""
    if getattr(gv, "_player_dead", False):
        return
    # Look up active_slipspaces via ``update_logic`` so test
    # monkey-patches against ``update_logic.active_slipspaces`` take
    # effect (the function was moved here from update_logic — the
    # public name lives on update_logic for back-compat).
    try:
        import update_logic
        get_active = update_logic.active_slipspaces
    except (ImportError, AttributeError):
        get_active = active_slipspaces
    active = get_active(gv)
    if not active or len(active) < 2:
        gv._inside_slipspace = None
        return
    px, py = gv.player.center_x, gv.player.center_y

    inside = gv._inside_slipspace
    if inside is not None and inside in active and inside.contains_point(px, py):
        return

    hit = None
    for ss in active:
        if ss.contains_point(px, py):
            hit = ss
            break
    if hit is None:
        gv._inside_slipspace = None
        return

    import random as _r
    candidates = [ss for ss in active if ss is not hit]
    dest = _r.choice(candidates)

    src_x = gv.player.center_x
    src_y = gv.player.center_y
    gv.player.center_x = dest.center_x
    gv.player.center_y = dest.center_y
    gv._inside_slipspace = dest
    if hasattr(gv, "shield_sprite") and gv.shield_sprite is not None:
        gv.shield_sprite.center_x = dest.center_x
        gv.shield_sprite.center_y = dest.center_y
    drone = getattr(gv, "_active_drone", None)
    if drone is not None:
        offx = drone.center_x - src_x
        offy = drone.center_y - src_y
        drone.center_x = dest.center_x + offx
        drone.center_y = dest.center_y + offy
        drone._nudge_anchor_x = drone.center_x
        drone._nudge_anchor_y = drone.center_y
        drone._nudge_timer = 0.0

    snd = getattr(gv, "_slipspace_snd", None)
    if snd is not None:
        try:
            from settings import audio as _audio
            arcade.play_sound(snd, volume=_audio.sfx_volume)
        except Exception:
            pass


# ── Force walls ─────────────────────────────────────────────────────────

def update_force_walls(gv: "GameView", dt: float) -> None:
    """Update force wall lifetimes and absorb enemy projectiles they
    block.  Also clips nebula-boss gas clouds."""
    for wall in gv._force_walls:
        wall.update(dt)
    gv._force_walls = [w for w in gv._force_walls if not w.dead]
    if not gv._force_walls:
        return
    from sprites.explosion import HitSpark
    walls = gv._force_walls
    plists = [gv.alien_projectile_list, gv._boss_projectile_list]
    zone = getattr(gv, '_zone', None)
    z2_alien_projs = getattr(zone, '_alien_projectiles', None)
    if z2_alien_projs is not None and z2_alien_projs is not gv.alien_projectile_list:
        plists.append(z2_alien_projs)
    for plist in plists:
        for proj in list(plist):
            for wall in walls:
                if wall.blocks_point(proj.center_x, proj.center_y, radius=14.0):
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    break

    # Nebula-boss gas clouds also stop at force walls.  These live in
    # ``gv._nebula_gas_clouds`` (a plain list of ``GasCloudProjectile``
    # instances, not an arcade.SpriteList), so filter in place.
    gas_clouds = getattr(gv, "_nebula_gas_clouds", None)
    if gas_clouds:
        survivors = []
        for c in gas_clouds:
            hit_wall = False
            for wall in walls:
                if wall.blocks_point(c.center_x, c.center_y, radius=c.radius):
                    gv.hit_sparks.append(HitSpark(c.center_x, c.center_y))
                    hit_wall = True
                    break
            if not hit_wall:
                survivors.append(c)
        gv._nebula_gas_clouds = survivors
