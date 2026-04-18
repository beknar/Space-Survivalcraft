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

def populate_iron_asteroids(z: Zone2) -> None:
    for _ in range(ASTEROID_COUNT):
        x, y = _rand_pos(z)
        z._iron_asteroids.append(IronAsteroid(z._iron_tex, x, y))


def populate_double_iron(z: Zone2) -> None:
    for _ in range(DOUBLE_IRON_COUNT):
        x, y = _rand_pos(z)
        a = IronAsteroid(z._iron_tex, x, y)
        a.hp = DOUBLE_IRON_HP
        a.scale = DOUBLE_IRON_SCALE
        z._double_iron.append(a)


def populate_copper_asteroids(z: Zone2) -> None:
    from sprites.copper_asteroid import CopperAsteroid
    for _ in range(COPPER_ASTEROID_COUNT):
        x, y = _rand_pos(z)
        z._copper_asteroids.append(CopperAsteroid(z._copper_tex, x, y))


def populate_gas_areas(z: Zone2) -> None:
    from sprites.gas_area import GasArea, generate_gas_texture
    from zones.zone2 import _gas_texture_cache
    sizes = [64, 128, 192, 256, 384]
    for _ in range(GAS_AREA_COUNT):
        size = random.choice(sizes)
        if size not in _gas_texture_cache:
            _gas_texture_cache[size] = generate_gas_texture(size)
        x, y = _rand_pos(z, 200)
        z._gas_areas.append(GasArea(_gas_texture_cache[size], x, y, size,
                                    world_w=z.world_width, world_h=z.world_height))


def populate_wanderers(z: Zone2) -> None:
    from sprites.wandering_asteroid import WanderingAsteroid
    for _ in range(WANDERING_COUNT):
        x, y = _rand_pos(z)
        z._wanderers.append(WanderingAsteroid(
            z._wanderer_tex, x, y, z.world_width, z.world_height))


def populate_aliens(z: Zone2) -> None:
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
            x, y = _rand_pos(z, 200)
            z._aliens.append(cls(tex, z._alien_laser_tex, x, y, **kw))
    z._alien_counts = {
        "shielded": Z2_SHIELDED_COUNT, "fast": Z2_FAST_COUNT,
        "gunner": Z2_GUNNER_COUNT, "rammer": Z2_RAMMER_COUNT,
    }


def _rand_pos(z: Zone2, margin: float = 100.0) -> tuple[float, float]:
    return (random.uniform(margin, z.world_width - margin),
            random.uniform(margin, z.world_height - margin))


# ── Collision handling ─────────────────────────────────────────────────────

def handle_projectile_hits(z: Zone2, gv: GameView) -> None:
    """Player projectile hits on asteroids and aliens using spatial hash."""
    _pre_count = (len(z._iron_asteroids) + len(z._copper_asteroids)
                  + len(z._double_iron) + len(z._wanderers))

    for proj in gv.projectile_list:
        if proj.mines_rock:
            _check_mining_hits(z, gv, proj)
        else:
            _check_laser_vs_aliens(z, gv, proj)

    _post_count = (len(z._iron_asteroids) + len(z._copper_asteroids)
                   + len(z._double_iron) + len(z._wanderers))
    if _post_count != _pre_count:
        z._minimap_cache = None


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


def try_respawn(z: Zone2, gv: GameView) -> None:
    """Respawn one alien of each type if below max."""
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
            x, y = _rand_pos(z, 200)
            cls = classes[name]
            tex = z._alien_textures[name]
            z._aliens.append(cls(tex, z._alien_laser_tex, x, y, **kw))
