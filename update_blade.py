"""Blade / melee / pickaxe AOE helpers extracted from update_logic.

Both melee weapons (lightsabre + Energy Pickaxe) share the same swing
animation, the same ``MeleeBlade`` visual, and the same lazy-spawn /
despawn / per-tick AOE-damage lifecycle.  This module owns the shared
``_BladeKind`` config and the two pre-configured kinds
(``LIGHTSABRE_KIND`` + ``PICKAXE_KIND``), plus the per-frame update
hooks (``update_melee_blade`` / ``update_pickaxe_blade``) called by
``update_logic.update_weapons``.

Re-exported from update_logic so the existing
``from update_logic import update_melee_blade`` / etc. call sites keep
working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView


def _melee_blade_stats(gv: GameView) -> tuple[float, int]:
    """Return ``(hit_radius, damage)`` for the player's current
    ship type.  Bastion gets a longer reach + extra punch; every
    other ship type uses the base values."""
    from constants import (
        MELEE_DAMAGE, MELEE_HIT_RADIUS,
        MELEE_BASTION_DAMAGE_BONUS, MELEE_BASTION_HIT_RADIUS,
    )
    ship_type = (getattr(gv, "_ship_type", None)
                 or getattr(gv.player, "_ship_type", None))
    if ship_type == "Bastion":
        return (MELEE_BASTION_HIT_RADIUS,
                MELEE_DAMAGE + MELEE_BASTION_DAMAGE_BONUS)
    return (MELEE_HIT_RADIUS, MELEE_DAMAGE)


def _pickaxe_blade_stats(gv: GameView) -> tuple[float, int]:
    """Return ``(hit_radius, damage)`` for the Energy Pickaxe.
    Same hit radius as the lightsabre; damage is base + Debra bonus."""
    from constants import (
        MELEE_HIT_RADIUS, PICKAXE_DAMAGE, PICKAXE_DEBRA_DAMAGE_BONUS,
    )
    from settings import audio as _audio
    char_name = getattr(_audio, "character_name", None)
    damage = PICKAXE_DAMAGE
    if char_name == "Debra":
        damage += PICKAXE_DEBRA_DAMAGE_BONUS
    return (MELEE_HIT_RADIUS, damage)


# ── BladeKind: per-blade configuration ───────────────────────────────────
#
# Both melee weapons (lightsabre + Energy Pickaxe) share the same swing
# animation, the same MeleeBlade visual, and the same lazy-spawn /
# despawn / per-tick AOE-damage lifecycle.  They differ only in:
#   * which slot on gv stores the active blade
#   * the per-asset MeleeBlade kwargs (scale / rotation / handle / head)
#   * how stats (hit_radius, damage) are computed
#   * which target sprites the AOE pass scans (enemies vs asteroids)
#   * which point on the blade is the AOE centre (sprite centre vs head_pos)
#   * the kill-reward call (alien iron + bp vs asteroid iron + bp)
#
# A single ``BladeKind`` config + single ``_ensure_blade`` /
# ``_remove_blade`` / ``_update_blade_aoe`` collapses ~140 lines of
# nearly-identical code into ~80 lines of one shared implementation +
# two small kind objects.

class _BladeKind:
    """Configuration for one melee-style weapon (lightsabre or pickaxe)."""

    def __init__(
        self,
        slot_attr: str,
        stats_fn,
        sprite_kwargs_fn,
        target_lists_fn,
        use_head_pos: bool,
        kill_reward_fn,
    ) -> None:
        self.slot_attr = slot_attr
        self.stats_fn = stats_fn
        self.sprite_kwargs_fn = sprite_kwargs_fn
        self.target_lists_fn = target_lists_fn
        self.use_head_pos = use_head_pos
        self.kill_reward_fn = kill_reward_fn


def _enemies_for_lightsabre(gv: GameView) -> list:
    """Player's alien list + every zone-specific enemy list +
    both bosses.  Used by the lightsabre AOE pass."""
    enemies: list = list(gv.alien_list)
    zone = getattr(gv, "_zone", None)
    if zone is not None:
        for attr in ("_aliens", "_maze_aliens", "_stalkers"):
            zlist = getattr(zone, attr, None)
            if zlist is not None and zlist is not gv.alien_list:
                enemies.extend(zlist)
    if gv._boss is not None and gv._boss.hp > 0:
        enemies.append(gv._boss)
    nb = getattr(gv, "_nebula_boss", None)
    if nb is not None and nb.hp > 0:
        enemies.append(nb)
    return enemies


def _asteroids_for_pickaxe(gv: GameView) -> list:
    """Player's asteroid list + every zone-specific asteroid list.
    Used by the pickaxe AOE pass."""
    asteroids: list = list(gv.asteroid_list)
    zone = getattr(gv, "_zone", None)
    if zone is not None:
        for attr in ("_iron_asteroids", "_double_iron",
                     "_copper_asteroids", "_wanderers"):
            zlist = getattr(zone, attr, None)
            if zlist is not None and zlist is not gv.asteroid_list:
                asteroids.extend(zlist)
    return asteroids


def _reward_alien_kill(gv: GameView, target) -> None:
    """Spawn iron + chance-of-blueprint for a slain enemy and
    remove the sprite.  Skips bosses (they have their own death
    pipeline) and spawners (incompatible respawn flow)."""
    if (getattr(target, "_charging", False)
            or hasattr(target, "killed")):
        return
    from collisions import _apply_kill_rewards
    from character_data import bonus_iron_enemy
    from constants import ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN
    _apply_kill_rewards(
        gv, target.center_x, target.center_y,
        ALIEN_IRON_DROP, bonus_iron_enemy,
        BLUEPRINT_DROP_CHANCE_ALIEN)
    target.remove_from_sprite_lists()


def _reward_asteroid_kill(gv: GameView, target) -> None:
    """Spawn iron + chance-of-blueprint for a destroyed asteroid
    and remove the sprite.  Uses ``_base_x/_base_y`` (the
    asteroid's home position before shake) so pickups land at the
    canonical spot rather than mid-shake offset."""
    from collisions import _apply_kill_rewards
    from character_data import bonus_iron_asteroid
    from constants import (
        ASTEROID_IRON_YIELD, BLUEPRINT_DROP_CHANCE_ASTEROID,
    )
    ax = getattr(target, "_base_x", target.center_x)
    ay = getattr(target, "_base_y", target.center_y)
    target.remove_from_sprite_lists()
    _apply_kill_rewards(
        gv, ax, ay, ASTEROID_IRON_YIELD,
        bonus_iron_asteroid,
        BLUEPRINT_DROP_CHANCE_ASTEROID,
        asteroid=True)


def _pickaxe_sprite_kwargs() -> dict:
    """Per-asset MeleeBlade kwargs for the Energy Pickaxe."""
    from constants import (
        PICKAXE_SCALE, PICKAXE_TEX_ANGLE_OFFSET,
        PICKAXE_HANDLE_OFFSET_PX, PICKAXE_HEAD_OFFSET_PX,
    )
    return dict(
        tex_scale=PICKAXE_SCALE,
        tex_angle_offset=PICKAXE_TEX_ANGLE_OFFSET,
        handle_offset_px=PICKAXE_HANDLE_OFFSET_PX,
        head_offset_px=PICKAXE_HEAD_OFFSET_PX,
    )


LIGHTSABRE_KIND = _BladeKind(
    slot_attr="_active_blade",
    stats_fn=_melee_blade_stats,
    sprite_kwargs_fn=lambda: {},   # MeleeBlade defaults
    target_lists_fn=_enemies_for_lightsabre,
    use_head_pos=False,            # AOE centred on sprite centre
    kill_reward_fn=_reward_alien_kill,
)

PICKAXE_KIND = _BladeKind(
    slot_attr="_active_pickaxe",
    stats_fn=_pickaxe_blade_stats,
    sprite_kwargs_fn=_pickaxe_sprite_kwargs,
    target_lists_fn=_asteroids_for_pickaxe,
    use_head_pos=True,             # AOE follows the pickaxe head
    kill_reward_fn=_reward_asteroid_kill,
)


def _ensure_blade(gv: GameView, kind: _BladeKind, texture) -> None:
    """Lazy-spawn the blade for ``kind`` in front of the player.
    Idempotent — already-present blade stays put."""
    if getattr(gv, kind.slot_attr, None) is not None:
        return
    from sprites.melee import MeleeBlade
    hit_radius, damage = kind.stats_fn(gv)
    blade = MeleeBlade(
        texture, gv.player,
        offset=hit_radius,
        damage=damage,
        hit_radius=hit_radius,
        **kind.sprite_kwargs_fn(),
    )
    gv._melee_swings.append(blade)
    setattr(gv, kind.slot_attr, blade)


def _remove_blade(gv: GameView, kind: _BladeKind) -> None:
    """Despawn the blade for ``kind`` (called when the active
    weapon is no longer this kind)."""
    blade = getattr(gv, kind.slot_attr, None)
    if blade is None:
        return
    blade.remove_from_sprite_lists()
    setattr(gv, kind.slot_attr, None)


def _update_blade_aoe(gv: GameView, dt: float, kind: _BladeKind) -> None:
    """Tick the blade for ``kind`` and apply per-swing AOE damage
    to its target list.  One-hit-per-target-per-swing semantics
    handled by the blade's internal ``_enemies_hit`` set."""
    blade = getattr(gv, kind.slot_attr, None)
    if blade is None:
        return
    blade.update_blade(dt)
    if not blade.is_swinging:
        return
    targets = kind.target_lists_fn(gv)
    if not targets:
        return
    if kind.use_head_pos:
        cx, cy = blade.head_pos
    else:
        cx, cy = blade.center_x, blade.center_y
    r_sq = blade.hit_radius * blade.hit_radius
    for t in list(targets):
        if blade.already_hit(t):
            continue
        if getattr(t, "hp", 0) <= 0:
            continue
        dx = t.center_x - cx
        dy = t.center_y - cy
        if dx * dx + dy * dy > r_sq:
            continue
        t.take_damage(int(blade.damage))
        blade.mark_hit(t)
        if getattr(t, "hp", 1) <= 0:
            # 2026-05-13 boss-death-via-melee fix: bosses have their
            # own death pipeline (explosion, iron drop, XP, wormhole
            # spawn, ``gv._boss = None``, ``_boss_defeated = True``).
            # ``_reward_alien_kill`` only PARTIALLY skips bosses
            # (checks ``_charging`` which is False outside the dash
            # window), then calls ``remove_from_sprite_lists`` on the
            # boss -- so the sprite disappears but ``gv._boss`` still
            # references the corpse and the bot keeps engaging a
            # ghost.  Mirror the missile-vs-boss path
            # (update_logic_missiles.py) and call the death helper
            # directly when the lethal hit lands on either boss.
            if t is gv._boss:
                from collisions import _boss_death
                _boss_death(gv)
            elif t is getattr(gv, "_nebula_boss", None):
                from collisions import _nebula_boss_death
                _nebula_boss_death(gv)
            else:
                kind.kill_reward_fn(gv, t)


# ── Backwards-compat shims for existing call sites ───────────────────────

def _ensure_melee_blade(gv: GameView, sword_tex) -> None:
    _ensure_blade(gv, LIGHTSABRE_KIND, sword_tex)


def _remove_melee_blade(gv: GameView) -> None:
    _remove_blade(gv, LIGHTSABRE_KIND)


def _ensure_pickaxe_blade(gv: GameView, pickaxe_tex) -> None:
    _ensure_blade(gv, PICKAXE_KIND, pickaxe_tex)


def _remove_pickaxe_blade(gv: GameView) -> None:
    _remove_blade(gv, PICKAXE_KIND)


def update_melee_blade(gv: GameView, dt: float) -> None:
    _update_blade_aoe(gv, dt, LIGHTSABRE_KIND)


def update_pickaxe_blade(gv: GameView, dt: float) -> None:
    _update_blade_aoe(gv, dt, PICKAXE_KIND)
