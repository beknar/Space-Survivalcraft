"""Combat, spawning, and progression helpers extracted from GameView."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Optional

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, SHAKE_DURATION, SHAKE_AMPLITUDE,
    ASTEROID_IRON_YIELD, ASTEROID_COUNT, ASTEROID_MIN_DIST,
    ALIEN_COUNT, ALIEN_MIN_DIST,
    RESPAWN_EXCLUSION_RADIUS, SHIELD_RECHARGE_HEAL,
    REPAIR_PACK_HEAL, WORLD_ITEM_LIFETIME,
    MODULE_TYPES,
)
from settings import audio
from sprites.explosion import Explosion, HitSpark, FireSpark
from sprites.pickup import IronPickup, BlueprintPickup
from sprites.boss import BossAlienShip

if TYPE_CHECKING:
    from game_view import GameView


def trigger_shake(gv: GameView) -> None:
    """Start a brief camera shake."""
    gv._shake_timer = SHAKE_DURATION


def apply_damage_to_player(gv: GameView, amount: int) -> None:
    """Apply damage to the player's shields first, then HP."""
    if gv._player_dead:
        return
    if gv.player.shield_absorb > 0 and gv.player.shields > 0:
        amount = max(1, amount - gv.player.shield_absorb)
    if gv.player.shields > 0:
        absorbed = min(gv.player.shields, amount)
        gv.player.shields -= absorbed
        amount -= absorbed
        gv.shield_sprite.hit_flash()
    if amount > 0:
        gv.player.hp = max(0, gv.player.hp - amount)
        gv.fire_sparks.append(
            FireSpark(gv.player.center_x, gv.player.center_y)
        )
        if gv.player.hp <= 0:
            trigger_player_death(gv)
    gv._shake_amp = SHAKE_AMPLITUDE


def flash_game_msg(gv: GameView, msg: str, duration: float = 1.5) -> None:
    """Show a temporary message centered on the play area."""
    gv._flash_msg = msg
    gv._flash_timer = duration


def use_repair_pack(gv: GameView, slot: int) -> None:
    """Try to use a repair pack from the given quick-use slot."""
    if gv.player.hp >= gv.player.max_hp:
        flash_game_msg(gv, "Already at full HP!")
        return
    if gv.inventory.count_item("repair_pack") <= 0:
        return
    heal = int(gv.player.max_hp * REPAIR_PACK_HEAL)
    gv.player.hp = min(gv.player.max_hp, gv.player.hp + heal)
    gv.inventory.remove_item("repair_pack", 1)
    remaining = gv.inventory.count_item("repair_pack")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "repair_pack", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    # Brief red glow
    gv._use_glow = (255, 80, 80, 160)
    gv._use_glow_timer = 0.4
    # Consuming an item inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def use_shield_recharge(gv: GameView, slot: int) -> None:
    """Try to use a shield recharge from the given quick-use slot."""
    if gv.player.shields >= gv.player.max_shields:
        flash_game_msg(gv, "Shields already full!")
        return
    if gv.inventory.count_item("shield_recharge") <= 0:
        return
    recharge = int(gv.player.max_shields * SHIELD_RECHARGE_HEAL)
    gv.player.shields = min(gv.player.max_shields, gv.player.shields + recharge)
    gv.inventory.remove_item("shield_recharge", 1)
    remaining = gv.inventory.count_item("shield_recharge")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "shield_recharge", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    # Brief blue glow
    gv._use_glow = (80, 160, 255, 160)
    gv._use_glow_timer = 0.4
    # Consuming an item inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def fire_missile(gv: GameView, slot: int) -> None:
    """Fire a homing missile from the given quick-use slot."""
    from constants import MISSILE_FIRE_RATE
    from sprites.missile import HomingMissile
    if gv.inventory.count_item("missile") <= 0:
        return
    if hasattr(gv, '_missile_fire_cd') and gv._missile_fire_cd > 0:
        return
    gv._missile_fire_cd = MISSILE_FIRE_RATE
    gv.inventory.remove_item("missile", 1)
    remaining = gv.inventory.count_item("missile")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "missile", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    m = HomingMissile(gv._missile_tex,
                      gv.player.center_x, gv.player.center_y,
                      gv.player.heading)
    gv._missile_list.append(m)
    arcade.play_sound(gv._missile_launch_snd, volume=0.4)
    # Firing a homing missile from inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def trigger_player_death(gv: GameView) -> None:
    """Handle player ship destruction."""
    gv._player_dead = True
    exp = Explosion(
        gv._explosion_frames,
        gv.player.center_x,
        gv.player.center_y,
        scale=2.5,
    )
    exp.color = (255, 180, 100, 255)
    gv.explosion_list.append(exp)
    for _ in range(5):
        gv.fire_sparks.append(
            FireSpark(gv.player.center_x, gv.player.center_y)
        )
    arcade.play_sound(gv._explosion_snd, volume=audio.sfx_volume)
    gv.player.visible = False
    gv.shield_sprite.visible = False
    if gv._thruster_player is not None:
        arcade.stop_sound(gv._thruster_player)
        gv._thruster_player = None
    gv._death_delay = 1.5


def spawn_explosion(gv: GameView, x: float, y: float) -> None:
    """Spawn a one-shot explosion animation at world position (x, y)."""
    exp = Explosion(gv._explosion_frames, x, y, scale=1.0)
    gv.explosion_list.append(exp)


def spawn_iron_pickup(
    gv: GameView,
    x: float,
    y: float,
    amount: int = ASTEROID_IRON_YIELD,
    lifetime: Optional[float] = None,
) -> None:
    """Spawn an iron token at world position (x, y)."""
    pickup = IronPickup(gv._iron_tex, x, y, amount=amount, lifetime=lifetime)
    gv.iron_pickup_list.append(pickup)


def spawn_blueprint_pickup(gv: GameView, x: float, y: float) -> None:
    """Spawn a random blueprint pickup at world position (x, y)."""
    mod_type = random.choice(list(MODULE_TYPES.keys()))
    tex = gv._blueprint_tinted.get(mod_type, gv._blueprint_tex)
    bp = BlueprintPickup(tex, x, y, mod_type,
                         lifetime=WORLD_ITEM_LIFETIME)
    gv.blueprint_pickup_list.append(bp)


def add_xp(gv: GameView, amount: int) -> None:
    """Add XP and check for level-up; reapply bonuses if leveled."""
    from character_data import level_for_xp
    from world_setup import load_weapons
    from character_data import MAX_XP
    if gv._char_xp >= MAX_XP:
        return
    old_level = gv._char_level
    gv._char_xp = min(gv._char_xp + amount, MAX_XP)
    gv._char_level = level_for_xp(gv._char_xp)
    if gv._char_level > old_level:
        flash_game_msg(gv, f"Level {gv._char_level}!", 2.0)
        gv._weapons = load_weapons(gv.player.guns)
        gv._apply_character_weapon_bonuses()


def try_respawn_asteroids(gv: GameView) -> None:
    """Respawn one asteroid if count < ASTEROID_COUNT, avoiding buildings."""
    if len(gv.asteroid_list) >= ASTEROID_COUNT:
        return
    from sprites.asteroid import IronAsteroid
    margin = 100
    for _ in range(200):
        ax = random.uniform(margin, WORLD_WIDTH - margin)
        ay = random.uniform(margin, WORLD_HEIGHT - margin)
        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
            continue
        too_close = any(
            math.hypot(ax - b.center_x, ay - b.center_y)
            < RESPAWN_EXCLUSION_RADIUS
            for b in gv.building_list
        )
        if too_close:
            continue
        gv.asteroid_list.append(IronAsteroid(gv._asteroid_tex, ax, ay))
        gv.hit_sparks.append(HitSpark(ax, ay))
        arcade.play_sound(gv._bump_snd, volume=0.3)
        return


def try_respawn_aliens(gv: GameView) -> None:
    """Respawn one alien if count < ALIEN_COUNT, avoiding buildings."""
    if len(gv.alien_list) >= ALIEN_COUNT:
        return
    from sprites.alien import SmallAlienShip
    margin = 100
    for _ in range(200):
        ax = random.uniform(margin, WORLD_WIDTH - margin)
        ay = random.uniform(margin, WORLD_HEIGHT - margin)
        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        if math.hypot(ax - cx_world, ay - cy_world) < ALIEN_MIN_DIST:
            continue
        too_close = any(
            math.hypot(ax - b.center_x, ay - b.center_y)
            < RESPAWN_EXCLUSION_RADIUS
            for b in gv.building_list
        )
        if too_close:
            continue
        gv.alien_list.append(
            SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex, ax, ay)
        )
        gv.hit_sparks.append(HitSpark(ax, ay))
        arcade.play_sound(gv._bump_snd, volume=0.3)
        return


def check_boss_spawn(gv: GameView) -> None:
    """Check if boss spawn conditions are met and spawn if so."""
    from sprites.building import HomeStation
    if gv._boss_spawned or gv._boss_defeated or gv._boss is not None:
        return
    if gv._char_level < 5:
        return
    if any(m is None for m in gv._module_slots):
        return
    rp_count = gv.inventory.count_item("repair_pack")
    rp_count += gv._station_inv.count_item("repair_pack")
    if rp_count < 5:
        return
    home = None
    for b in gv.building_list:
        if isinstance(b, HomeStation) and not b.disabled:
            home = b
            break
    if home is None:
        return
    spawn_boss(gv, home.center_x, home.center_y)


def spawn_boss(gv: GameView, station_x: float, station_y: float) -> None:
    """Spawn the boss as far as possible from the station."""
    corners = [
        (100.0, 100.0),
        (WORLD_WIDTH - 100.0, 100.0),
        (100.0, WORLD_HEIGHT - 100.0),
        (WORLD_WIDTH - 100.0, WORLD_HEIGHT - 100.0),
    ]
    best_corner = max(
        corners,
        key=lambda c: math.hypot(c[0] - station_x, c[1] - station_y),
    )
    gv._boss = BossAlienShip(
        gv._boss_tex, gv._boss_laser_tex,
        best_corner[0], best_corner[1],
        station_x, station_y,
    )
    gv._boss_list.clear()
    gv._boss_list.append(gv._boss)
    gv._boss_spawned = True
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "WARNING: BOSS INCOMING"
    gv._t_boss_subtitle.text = "A massive enemy approaches your station!"
