"""Zone 2 entity population and collision handling (extracted from Zone2)."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    ASTEROID_COUNT, ASTEROID_IRON_YIELD,
    DOUBLE_IRON_COUNT, DOUBLE_IRON_HP, DOUBLE_IRON_YIELD, DOUBLE_IRON_SCALE,
    DOUBLE_IRON_XP, COPPER_ASTEROID_COUNT,
    COPPER_YIELD, COPPER_XP,
    GAS_AREA_COUNT,
    WANDERING_COUNT, Z2_SHIELDED_COUNT, Z2_SHIELDED_XP,
    Z2_FAST_COUNT, Z2_FAST_XP,
    Z2_GUNNER_COUNT, Z2_GUNNER_XP,
    Z2_RAMMER_COUNT, Z2_RAMMER_XP,
    BLUEPRINT_DROP_CHANCE_ALIEN, BLUEPRINT_DROP_CHANCE_ASTEROID,
    RESPAWN_EXCLUSION_RADIUS,
)
from sprites.asteroid import IronAsteroid
from sprites.explosion import HitSpark
from sprites.pickup import IronPickup
from sprites.zone2_aliens import (
    ShieldedAlien, FastAlien, GunnerAlien, RammerAlien,
)
from character_data import (
    bonus_copper_asteroid, bonus_copper_enemy, blueprint_drop_bonus,
)
from settings import audio as _audio

if TYPE_CHECKING:
    from game_view import GameView
    from zones.zone2 import Zone2

# Module-level XP table (avoids rebuilding dict per call)
_ALIEN_XP: dict[type, int] = {}  # populated lazily after imports resolve


def _get_alien_xp() -> dict[type, int]:
    global _ALIEN_XP
    if not _ALIEN_XP:
        _ALIEN_XP = {
            ShieldedAlien: Z2_SHIELDED_XP, FastAlien: Z2_FAST_XP,
            GunnerAlien: Z2_GUNNER_XP, RammerAlien: Z2_RAMMER_XP,
        }
    return _ALIEN_XP


# ── Population ─────────────────────────────────────────────────────────────

def populate_iron_asteroids(z: Zone2, reject_fn=None) -> None:
    for _ in range(ASTEROID_COUNT):
        x, y = _rand_pos(z, reject_fn=reject_fn)
        z._iron_asteroids.append(IronAsteroid(z._iron_tex, x, y))


def populate_double_iron(z: Zone2, reject_fn=None) -> None:
    for _ in range(DOUBLE_IRON_COUNT):
        x, y = _rand_pos(z, reject_fn=reject_fn)
        a = IronAsteroid(z._iron_tex, x, y)
        a.hp = DOUBLE_IRON_HP
        a.scale = DOUBLE_IRON_SCALE
        z._double_iron.append(a)


def populate_copper_asteroids(z: Zone2, reject_fn=None) -> None:
    from sprites.copper_asteroid import CopperAsteroid
    for _ in range(COPPER_ASTEROID_COUNT):
        x, y = _rand_pos(z, reject_fn=reject_fn)
        z._copper_asteroids.append(CopperAsteroid(z._copper_tex, x, y))


def populate_gas_areas(z: Zone2, reject_fn=None) -> None:
    from sprites.gas_area import GasArea, generate_gas_texture
    from zones.zone2 import _gas_texture_cache
    sizes = [64, 128, 192, 256, 384]
    for _ in range(GAS_AREA_COUNT):
        size = random.choice(sizes)
        if size not in _gas_texture_cache:
            _gas_texture_cache[size] = generate_gas_texture(size)
        x, y = _rand_pos(z, 200, reject_fn=reject_fn)
        z._gas_areas.append(GasArea(_gas_texture_cache[size], x, y, size,
                                    world_w=z.world_width, world_h=z.world_height))


def populate_wanderers(z: Zone2, reject_fn=None) -> None:
    from sprites.wandering_asteroid import WanderingAsteroid
    for _ in range(WANDERING_COUNT):
        x, y = _rand_pos(z, reject_fn=reject_fn)
        z._wanderers.append(WanderingAsteroid(
            z._wanderer_tex, x, y, z.world_width, z.world_height))


def populate_aliens(z: Zone2, reject_fn=None) -> None:
    kw = dict(world_w=z.world_width, world_h=z.world_height)
    specs = [
        (Z2_SHIELDED_COUNT, "shielded", ShieldedAlien),
        (Z2_FAST_COUNT, "fast", FastAlien),
        (Z2_GUNNER_COUNT, "gunner", GunnerAlien),
        (Z2_RAMMER_COUNT, "rammer", RammerAlien),
    ]
    for count, tex_name, cls in specs:
        tex = z._alien_textures[tex_name]
        for _ in range(count):
            x, y = _rand_pos(z, 200, reject_fn=reject_fn)
            z._aliens.append(cls(tex, z._alien_laser_tex, x, y, **kw))
    z._alien_counts = {
        "shielded": Z2_SHIELDED_COUNT, "fast": Z2_FAST_COUNT,
        "gunner": Z2_GUNNER_COUNT, "rammer": Z2_RAMMER_COUNT,
    }


def _rand_pos(z: Zone2, margin: float = 100.0,
              reject_fn=None, max_tries: int = 40
              ) -> tuple[float, float]:
    """Pick a random world-space position inside ``z``'s bounds.

    ``reject_fn(x, y) -> bool`` is an optional filter; when provided,
    we re-roll up to ``max_tries`` times to find a position it doesn't
    reject.  If every attempt is rejected (unlikely — even tight
    filters clear on a handful of rolls), the last candidate is
    returned.  Used by the Star Maze to keep population out of
    maze-room interiors without duplicating the placement code.
    """
    x = y = 0.0
    for _ in range(max_tries):
        x = random.uniform(margin, z.world_width - margin)
        y = random.uniform(margin, z.world_height - margin)
        if reject_fn is None or not reject_fn(x, y):
            return x, y
    return x, y


# ── Collision handling ─────────────────────────────────────────────────────

def handle_projectile_hits(z: Zone2, gv: GameView) -> None:
    """Player projectile hits on asteroids and aliens using spatial hash.

    Previously invalidated ``z._minimap_cache`` here on every kill,
    forcing a fresh arcade.SpriteList allocation + 150-sprite refill
    on the next minimap draw — that GL-buffer churn was the source
    of the sub-40-FPS spike on each mining-beam asteroid kill.  The
    minimap obstacles iterator now lazily chains the source lists
    (see ``draw_logic._minimap_obstacles``) so no cache + no
    invalidation is needed.
    """
    for proj in gv.projectile_list:
        if proj.mines_rock:
            _check_mining_hits(z, gv, proj)
        else:
            _check_laser_vs_aliens(z, gv, proj)


def _check_mining_hits(z: Zone2, gv: GameView, proj) -> None:
    """Check mining beam projectile against all asteroid types."""
    # Iron
    for a in arcade.check_for_collision_with_list(proj, z._iron_asteroids):
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        a.take_damage(int(proj.damage))
        if a.hp <= 0:
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            gv._spawn_iron_pickup(a.center_x, a.center_y, amount=ASTEROID_IRON_YIELD)
            gv._add_xp(10)
            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
            a.remove_from_sprite_lists()
        return

    # Double iron
    for a in arcade.check_for_collision_with_list(proj, z._double_iron):
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        a.take_damage(int(proj.damage))
        if a.hp <= 0:
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            gv._spawn_iron_pickup(a.center_x, a.center_y, amount=DOUBLE_IRON_YIELD)
            gv._add_xp(DOUBLE_IRON_XP)
            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
            a.remove_from_sprite_lists()
        return

    # Copper
    for a in arcade.check_for_collision_with_list(proj, z._copper_asteroids):
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        a.take_damage(int(proj.damage))
        if a.hp <= 0:
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            # Drop copper
            base = COPPER_YIELD
            extra = bonus_copper_asteroid(_audio.character_name, gv._char_level)
            pickup = IronPickup(z._copper_pickup_tex,
                                a.center_x, a.center_y + 20,
                                amount=base + extra)
            pickup.item_type = "copper"
            gv.iron_pickup_list.append(pickup)
            # Also drop iron below the copper
            from constants import COPPER_IRON_YIELD
            gv._spawn_iron_pickup(a.center_x, a.center_y - 20,
                                  amount=COPPER_IRON_YIELD)
            gv._add_xp(COPPER_XP)
            a.remove_from_sprite_lists()
        return

    # Wanderers
    for w in arcade.check_for_collision_with_list(proj, z._wanderers):
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        w.take_damage(int(proj.damage))
        if w.hp <= 0:
            gv._spawn_asteroid_explosion(w.center_x, w.center_y)
            from constants import WANDERING_IRON_YIELD
            gv._spawn_iron_pickup(w.center_x, w.center_y,
                                  amount=WANDERING_IRON_YIELD)
            w.remove_from_sprite_lists()
        return


def drop_zone2_alien_loot(z: Zone2, gv: GameView, alien) -> None:
    """Spawn explosion + iron/copper/blueprint drops + award XP for a Zone 2 alien kill."""
    gv._spawn_explosion(alien.center_x, alien.center_y)
    gv._spawn_iron_pickup(alien.center_x - 20, alien.center_y, amount=5)
    copper_extra = bonus_copper_enemy(_audio.character_name, gv._char_level)
    if copper_extra > 0:
        cp = IronPickup(z._copper_pickup_tex,
                        alien.center_x + 20, alien.center_y,
                        amount=copper_extra)
        cp.item_type = "copper"
        gv.iron_pickup_list.append(cp)
    xp = _get_alien_xp().get(type(alien), 25)
    gv._add_xp(xp)
    bp_chance = BLUEPRINT_DROP_CHANCE_ALIEN + blueprint_drop_bonus(
        _audio.character_name, gv._char_level)
    if random.random() < bp_chance:
        gv._spawn_blueprint_pickup(alien.center_x, alien.center_y + 25)
    alien.remove_from_sprite_lists()


def nebula_boss_destroy_asteroids(z: Zone2, gv: GameView, boss) -> None:
    """Destroy any Zone-2 asteroid the Nebula boss has rammed into
    and spawn its normal drops.

    Called once per frame from ``update_logic.update_nebula_boss``
    AFTER the boss's movement step.  Uses ``boss.radius`` (derived
    from the rendered sprite size) so the crush radius tracks any
    future ``BOSS_SCALE`` change.  Each asteroid type keeps its
    usual yield — iron from iron, iron+XP from double-iron, copper
    + bonus iron + XP from copper, base iron from wanderers — plus
    the same blueprint drop chance as a mining-beam kill.  No
    damage is applied to the boss; it's a steamroller, not a wall.
    """
    from constants import (
        ASTEROID_IRON_YIELD, DOUBLE_IRON_YIELD, DOUBLE_IRON_XP,
        COPPER_YIELD, COPPER_XP, COPPER_IRON_YIELD,
        WANDERING_IRON_YIELD,
        BLUEPRINT_DROP_CHANCE_ASTEROID,
    )
    # Boss hull radius plus a generous crush buffer — the boss arc
    # can glance asteroids at 10..40 px from its hull edge and the
    # player expects those "close pass" rocks to go up with the
    # rest.  40 px buffer lines up with the visual sprite's glow /
    # antenna silhouette on the 230-px-wide monster textures.
    crush_r = boss.radius + 40.0
    # Use the boss's path segment (pre-frame → post-frame) so
    # obstacles between sample points still count.  ``_prev_frame_x``
    # / ``_y`` are set at the top of ``BossAlienShip.update_boss``.
    x0 = getattr(boss, "_prev_frame_x", boss.center_x)
    y0 = getattr(boss, "_prev_frame_y", boss.center_y)
    x1 = boss.center_x
    y1 = boss.center_y

    def _hit(ax: float, ay: float) -> bool:
        return _segment_hit_asteroid(x0, y0, x1, y1, ax, ay, crush_r)

    # Iron asteroids
    for a in list(z._iron_asteroids):
        if _hit(a.center_x, a.center_y):
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            gv._spawn_iron_pickup(a.center_x, a.center_y,
                                  amount=ASTEROID_IRON_YIELD)
            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
            gv._add_xp(10)
            a.remove_from_sprite_lists()

    # Double-iron
    for a in list(z._double_iron):
        if _hit(a.center_x, a.center_y):
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            gv._spawn_iron_pickup(a.center_x, a.center_y,
                                  amount=DOUBLE_IRON_YIELD)
            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
            gv._add_xp(DOUBLE_IRON_XP)
            a.remove_from_sprite_lists()

    # Copper
    for a in list(z._copper_asteroids):
        if _hit(a.center_x, a.center_y):
            gv._spawn_asteroid_explosion(a.center_x, a.center_y)
            base = COPPER_YIELD
            extra = 0  # character bonuses apply on mining-beam kill only
            pickup = IronPickup(z._copper_pickup_tex,
                                a.center_x, a.center_y + 20,
                                amount=base + extra)
            pickup.item_type = "copper"
            gv.iron_pickup_list.append(pickup)
            gv._spawn_iron_pickup(a.center_x, a.center_y - 20,
                                  amount=COPPER_IRON_YIELD)
            gv._add_xp(COPPER_XP)
            a.remove_from_sprite_lists()

    # Wanderers
    for w in list(z._wanderers):
        if _hit(w.center_x, w.center_y):
            gv._spawn_asteroid_explosion(w.center_x, w.center_y)
            gv._spawn_iron_pickup(w.center_x, w.center_y,
                                  amount=WANDERING_IRON_YIELD)
            w.remove_from_sprite_lists()


def _segment_hit_asteroid(
    x0: float, y0: float, x1: float, y1: float,
    ax: float, ay: float, r: float,
) -> bool:
    """True if the segment (x0,y0)->(x1,y1) passes within ``r + ASTEROID_RADIUS``
    of the asteroid centre ``(ax, ay)``.  Uses standard point-to-segment
    distance (squared, to avoid ``math.sqrt`` on the hot path)."""
    from constants import ASTEROID_RADIUS
    thr = r + ASTEROID_RADIUS
    thr_sq = thr * thr
    dx = x1 - x0
    dy = y1 - y0
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-6:
        # Zero-length segment — degenerate into a point check.
        ddx = ax - x0
        ddy = ay - y0
        return ddx * ddx + ddy * ddy <= thr_sq
    # Project asteroid onto segment, clamped to [0, 1].
    t = ((ax - x0) * dx + (ay - y0) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    cx = x0 + t * dx
    cy = y0 + t * dy
    ddx = ax - cx
    ddy = ay - cy
    return ddx * ddx + ddy * ddy <= thr_sq


def _check_laser_vs_aliens(z: Zone2, gv: GameView, proj) -> None:
    """Check laser projectile against Zone 2 aliens."""
    for alien in arcade.check_for_collision_with_list(proj, z._aliens):
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        gv._trigger_shake()
        proj.remove_from_sprite_lists()
        alien.take_damage(int(proj.damage))
        if alien.hp <= 0:
            drop_zone2_alien_loot(z, gv, alien)
        break


def _find_respawn_pos(z: Zone2, gv: GameView, margin: float = 100.0,
                      attempts: int = 200,
                      reject_radius: float = 26.0) -> tuple[float, float] | None:
    """Pick a random Nebula position that isn't inside
    RESPAWN_EXCLUSION_RADIUS of any Zone 2 building, AND that passes
    the optional ``z._respawn_reject(x, y, radius)`` hook (Star Maze
    uses this to keep respawned content out of the maze AABBs).
    Returns None if no clear spot is found after ``attempts`` tries
    so the caller can skip this tick rather than spawning on top of
    the station."""
    import math as _math
    buildings = list(getattr(gv, "building_list", []) or [])
    reject = getattr(z, "_respawn_reject", None)
    for _ in range(attempts):
        x, y = _rand_pos(z, margin)
        too_close = any(
            _math.hypot(x - b.center_x, y - b.center_y)
            < RESPAWN_EXCLUSION_RADIUS
            for b in buildings
        )
        if too_close:
            continue
        if reject is not None and reject(x, y, reject_radius):
            continue
        return x, y
    return None


def try_respawn(z: Zone2, gv: GameView) -> None:
    """Respawn one alien + one asteroid of each type if below max.

    Runs on the same ``RESPAWN_INTERVAL`` cadence as Zone 1 so every
    Nebula resource (iron, double-iron, copper, wandering) regenerates
    at the same rate as Zone 1 iron: one sprite per type per minute.

    Honours an optional ``z._respawn_reject(x, y, radius)`` hook —
    Star Maze uses it to keep respawned Nebula entities outside the
    maze AABBs.  Without the hook, every minute one Z2 alien of each
    type was bypassing the original populate-time reject filter and
    dropping anywhere on the map (including inside a maze).
    """
    reject = getattr(z, "_respawn_reject", None)

    def _pick(margin: float, radius: float) -> tuple[float, float] | None:
        for _ in range(30):
            x, y = _rand_pos(z, margin)
            if reject is None or not reject(x, y, radius):
                return x, y
        return None

    # Aliens — one per subclass up to cap.
    _CLASS_MAP = {ShieldedAlien: "shielded", FastAlien: "fast",
                  GunnerAlien: "gunner", RammerAlien: "rammer"}
    counts = {"shielded": 0, "fast": 0, "gunner": 0, "rammer": 0}
    for a in z._aliens:
        name = _CLASS_MAP.get(type(a))
        if name:
            counts[name] += 1
    maxes = {"shielded": Z2_SHIELDED_COUNT, "fast": Z2_FAST_COUNT,
             "gunner": Z2_GUNNER_COUNT, "rammer": Z2_RAMMER_COUNT}
    classes = {"shielded": ShieldedAlien, "fast": FastAlien,
               "gunner": GunnerAlien, "rammer": RammerAlien}
    kw = dict(world_w=z.world_width, world_h=z.world_height)
    for name, max_count in maxes.items():
        if counts[name] < max_count:
            pos = _pick(200, 24.0)
            if pos is None:
                continue
            x, y = pos
            cls = classes[name]
            tex = z._alien_textures[name]
            z._aliens.append(cls(tex, z._alien_laser_tex, x, y, **kw))

    # Asteroids — mirrors combat_helpers.try_respawn_asteroids for
    # Zone 1.  One per type per tick, avoiding Zone 2 buildings.
    if len(z._iron_asteroids) < ASTEROID_COUNT:
        pos = _find_respawn_pos(z, gv)
        if pos is not None:
            z._iron_asteroids.append(IronAsteroid(z._iron_tex, *pos))
            _minimap_dirty(z)

    if len(z._double_iron) < DOUBLE_IRON_COUNT:
        pos = _find_respawn_pos(z, gv)
        if pos is not None:
            a = IronAsteroid(z._iron_tex, *pos)
            a.hp = DOUBLE_IRON_HP
            a.scale = DOUBLE_IRON_SCALE
            z._double_iron.append(a)
            _minimap_dirty(z)

    if len(z._copper_asteroids) < COPPER_ASTEROID_COUNT:
        pos = _find_respawn_pos(z, gv)
        if pos is not None:
            from sprites.copper_asteroid import CopperAsteroid
            z._copper_asteroids.append(
                CopperAsteroid(z._copper_tex, *pos))
            _minimap_dirty(z)

    if len(z._wanderers) < WANDERING_COUNT:
        pos = _find_respawn_pos(z, gv)
        if pos is not None:
            from sprites.wandering_asteroid import WanderingAsteroid
            z._wanderers.append(WanderingAsteroid(
                z._wanderer_tex, *pos, z.world_width, z.world_height))
            _minimap_dirty(z)


def _minimap_dirty(z: Zone2) -> None:
    """Invalidate the Nebula minimap cache after a respawn so the new
    dot shows up on next draw."""
    z._minimap_cache = None
