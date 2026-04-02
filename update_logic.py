"""Game update logic extracted from GameView.on_update."""
from __future__ import annotations

import gc
import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    DEAD_ZONE, SHIP_RADIUS,
    CONTRAIL_MAX_PARTICLES, CONTRAIL_SPAWN_RATE, CONTRAIL_LIFETIME,
    CONTRAIL_START_SIZE, CONTRAIL_END_SIZE, CONTRAIL_OFFSET,
    REPAIR_RANGE, REPAIR_RATE, REPAIR_SHIELD_BOOST,
    CRAFT_TIME, CRAFT_IRON_COST, CRAFT_RESULT_COUNT,
    MODULE_TYPES,
    BROADSIDE_COOLDOWN, BROADSIDE_DAMAGE, BROADSIDE_SPEED, BROADSIDE_RANGE,
    RESPAWN_INTERVAL,
)
from settings import audio
from sprites.contrail import ContrailParticle
from sprites.building import (
    HomeStation, RepairModule, BasicCrafter, Turret,
)
from collisions import (
    handle_projectile_hits,
    handle_ship_asteroid_collision,
    handle_alien_player_collision,
    handle_alien_asteroid_collision,
    handle_alien_alien_collision,
    handle_alien_laser_hits,
    handle_alien_laser_building_hits,
    handle_alien_building_collision,
    handle_turret_projectile_hits,
    handle_ship_building_collision,
    handle_boss_projectile_hits,
    handle_boss_player_collision,
    handle_boss_laser_hits,
    handle_boss_building_hits,
    handle_boss_charge_hit,
)

if TYPE_CHECKING:
    from game_view import GameView


def update_preamble(gv: GameView, dt: float) -> None:
    """GC, FPS, video/music sync, and escape menu tick."""
    # Manual GC
    if gv._escape_menu.open and not gv._gc_ran:
        gc.collect()
        gv._gc_ran = True
    elif not gv._escape_menu.open:
        gv._gc_ran = False
    # FPS
    gv._hud.update_fps(dt)
    gv._hud._show_fps = audio.show_fps
    # Character video
    if gv._char_video_player.active:
        gv._char_video_player.update_volume(0.0)
    # Video / music
    if gv._video_player.active:
        gv._video_player.update(audio.music_volume)
    else:
        if gv._music_player is not None:
            gv._music_player.volume = audio.music_volume
            if not gv._music_player.playing:
                gv._play_next_track()
    # Escape menu
    gv._escape_menu.update(dt)


def update_death_state(gv: GameView, dt: float) -> None:
    """Update explosions/sparks during death delay."""
    for exp in list(gv.explosion_list):
        exp.update_explosion(dt)
    for fs in gv.fire_sparks:
        fs.update(dt)
    gv.fire_sparks = [fs for fs in gv.fire_sparks if not fs.dead]
    if hasattr(gv, '_death_delay') and gv._death_delay > 0:
        gv._death_delay -= dt
        if gv._death_delay <= 0:
            gv._death_screen.show()


def update_timers(gv: GameView, dt: float) -> None:
    """Tick shake, flash, and boss announce timers."""
    if gv._shake_timer > 0.0:
        gv._shake_timer = max(0.0, gv._shake_timer - dt)
    if gv._flash_timer > 0.0:
        gv._flash_timer = max(0.0, gv._flash_timer - dt)
        if gv._flash_timer <= 0.0:
            gv._flash_msg = ""
    if gv._boss_announce_timer > 0.0:
        gv._boss_announce_timer = max(0.0, gv._boss_announce_timer - dt)


def update_repair_and_shields(gv: GameView, dt: float) -> None:
    """Repair module proximity check, shield regen, HP/building healing."""
    has_repair = any(
        isinstance(b, RepairModule) and not b.disabled
        for b in gv.building_list
    )
    repair_near_home = False
    if has_repair:
        home = None
        for b in gv.building_list:
            if isinstance(b, HomeStation) and not b.disabled:
                home = b
                break
        if home is not None:
            dist = math.hypot(
                gv.player.center_x - home.center_x,
                gv.player.center_y - home.center_y,
            )
            if dist <= REPAIR_RANGE:
                repair_near_home = True

    # Shield regen
    if gv.player.shields < gv.player.max_shields:
        regen = gv.player._shield_regen
        if repair_near_home:
            regen += REPAIR_SHIELD_BOOST
        gv.player._shield_acc += regen * dt
        pts = int(gv.player._shield_acc)
        if pts > 0:
            gv.player._shield_acc -= pts
            gv.player.shields = min(gv.player.max_shields,
                                    gv.player.shields + pts)

    # Player HP repair
    if repair_near_home and gv.player.hp < gv.player.max_hp:
        gv._repair_acc += REPAIR_RATE * dt
        pts = int(gv._repair_acc)
        if pts > 0:
            gv._repair_acc -= pts
            gv.player.hp = min(gv.player.max_hp, gv.player.hp + pts)

    # Building repair
    if has_repair:
        any_damaged = any(
            not b.disabled and b.hp < b.max_hp
            for b in gv.building_list
        )
        if any_damaged:
            gv._building_repair_acc += REPAIR_RATE * dt
            pts = int(gv._building_repair_acc)
            if pts > 0:
                gv._building_repair_acc -= pts
                for b in gv.building_list:
                    if not b.disabled and b.hp < b.max_hp:
                        b.heal(pts)


def update_crafting(gv: GameView, dt: float) -> None:
    """Tick active crafters and update craft menu progress."""
    for b in gv.building_list:
        if isinstance(b, BasicCrafter) and b.crafting and not b.disabled:
            b.craft_timer += dt
            if b.craft_timer >= b.craft_total:
                b.crafting = False
                b.craft_timer = 0.0
                target = gv._craft_menu._craft_target
                if target and target in MODULE_TYPES:
                    gv._station_inv.add_item(f"mod_{target}", 1)
                else:
                    gv._station_inv.add_item("repair_pack", CRAFT_RESULT_COUNT)

    if gv._craft_menu.open and gv._active_crafter is not None:
        gv._craft_menu.update(
            gv._active_crafter.craft_progress,
            gv._active_crafter.crafting,
        )


def update_movement(gv: GameView, dt: float) -> bool:
    """Process movement input and update ship. Returns whether fire is held."""
    if gv._escape_menu.open:
        rl = rr = tf = tb = sl = sr = fire = False
    else:
        rl = arcade.key.LEFT in gv._keys or arcade.key.A in gv._keys
        rr = arcade.key.RIGHT in gv._keys or arcade.key.D in gv._keys
        tf = arcade.key.UP in gv._keys or arcade.key.W in gv._keys
        tb = arcade.key.DOWN in gv._keys or arcade.key.S in gv._keys
        sl = arcade.key.Q in gv._keys
        sr = arcade.key.E in gv._keys
        fire = arcade.key.SPACE in gv._keys

    if gv.joystick and not gv._escape_menu.open:
        lx = gv.joystick.leftx
        ly = gv.joystick.lefty
        rl |= lx < -DEAD_ZONE
        rr |= lx > DEAD_ZONE
        tf |= ly > DEAD_ZONE
        tb |= ly < -DEAD_ZONE
        fire |= bool(getattr(gv.joystick, "a", False))
        rb = bool(getattr(gv.joystick, "rightshoulder", False))
        if rb and not gv._prev_rb:
            gv._cycle_weapon()
        gv._prev_rb = rb
        y_btn = bool(getattr(gv.joystick, "y", False))
        if y_btn and not gv._prev_y:
            gv.inventory.toggle()
        gv._prev_y = y_btn

    gv.player.apply_input(dt, rl, rr, tf, tb, sl, sr)

    # Shield sprite + animation
    gv.shield_sprite.update_shield(
        dt,
        gv.player.center_x, gv.player.center_y,
        gv.player.shields,
    )
    from constants import SHIELD_ROT_SPEED
    gv._enhancer_angle = (gv._enhancer_angle + SHIELD_ROT_SPEED * dt) % 360.0

    # Thruster sound
    thrusting_now = tf or tb
    if thrusting_now and not gv._thrusting_last:
        gv._thruster_player = arcade.play_sound(
            gv._thruster_snd, volume=0.25, loop=True
        )
    elif not thrusting_now and gv._thrusting_last:
        if gv._thruster_player is not None:
            arcade.stop_sound(gv._thruster_player)
            gv._thruster_player = None
    gv._thrusting_last = thrusting_now

    return fire


def update_contrail(gv: GameView, dt: float) -> None:
    """Spawn and advance contrail particles."""
    intensity = gv.player.thrust_intensity
    if intensity > 0.01:
        gv._contrail_timer += dt
        interval = 1.0 / CONTRAIL_SPAWN_RATE
        while gv._contrail_timer >= interval:
            gv._contrail_timer -= interval
            if len(gv._contrail) < CONTRAIL_MAX_PARTICLES:
                rad = math.radians(gv.player.heading)
                ex = gv.player.center_x - math.sin(rad) * abs(CONTRAIL_OFFSET)
                ey = gv.player.center_y - math.cos(rad) * abs(CONTRAIL_OFFSET)
                ex += random.uniform(-3, 3)
                ey += random.uniform(-3, 3)
                start_sz = CONTRAIL_START_SIZE * intensity
                gv._contrail.append(ContrailParticle(
                    ex, ey,
                    gv._contrail_start_colour,
                    gv._contrail_end_colour,
                    CONTRAIL_LIFETIME,
                    start_sz, CONTRAIL_END_SIZE,
                ))
    else:
        gv._contrail_timer = 0.0

    for cp in gv._contrail:
        cp.update(dt)
    gv._contrail = [p for p in gv._contrail if not p.dead]


def update_weapons(gv: GameView, dt: float, fire: bool) -> None:
    """Tick weapon cooldowns and fire if held."""
    for w in gv._weapons:
        w.update(dt)

    if fire:
        spawn_pts = gv.player.gun_spawn_points()
        gun_count = gv.player.guns
        base_idx = (gv._weapon_idx // gun_count) * gun_count
        for gi in range(gun_count):
            wpn = gv._weapons[base_idx + gi]
            pt = spawn_pts[gi] if gi < len(spawn_pts) else spawn_pts[0]
            proj = wpn.fire(pt[0], pt[1], gv.player.heading)
            if proj is not None:
                gv.projectile_list.append(proj)

    # Broadside auto-fire
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


def update_entities(gv: GameView, dt: float) -> None:
    """Advance projectiles, pickups, asteroids, and aliens."""
    # Player projectiles
    for proj in list(gv.projectile_list):
        proj.update_projectile(dt)

    # Collisions
    handle_projectile_hits(gv)
    handle_ship_asteroid_collision(gv)

    # Asteroids
    for asteroid in gv.asteroid_list:
        asteroid.update_asteroid(dt)

    # Iron pickups
    sx, sy = gv.player.center_x, gv.player.center_y
    for pickup in list(gv.iron_pickup_list):
        collected = pickup.update_pickup(dt, sx, sy, SHIP_RADIUS)
        if collected:
            gv.inventory.add_item("iron", pickup.amount)

    # Blueprint pickups
    for bp in list(gv.blueprint_pickup_list):
        collected = bp.update_pickup(dt, sx, sy, SHIP_RADIUS)
        if collected:
            gv.inventory.add_item(bp.item_type, 1)

    # Alien AI
    px, py = gv.player.center_x, gv.player.center_y
    for alien in list(gv.alien_list):
        proj = alien.update_alien(
            dt, px, py,
            gv.asteroid_list, gv.alien_list,
        )
        if proj is not None:
            gv.alien_projectile_list.append(proj)

    # Alien collisions
    handle_alien_player_collision(gv)
    handle_alien_asteroid_collision(gv)
    handle_alien_alien_collision(gv)

    # Alien projectiles
    for proj in list(gv.alien_projectile_list):
        proj.update_projectile(dt)
    handle_alien_laser_hits(gv)


def update_buildings(gv: GameView, dt: float) -> None:
    """Update buildings, turrets, and station info."""
    for b in list(gv.building_list):
        b.update_building(dt)
        if isinstance(b, Turret):
            b.update_turret(dt, gv.alien_list,
                            gv.turret_projectile_list)

    for proj in list(gv.turret_projectile_list):
        proj.update_projectile(dt)

    handle_turret_projectile_hits(gv)
    handle_alien_laser_building_hits(gv)
    handle_alien_building_collision(gv)
    handle_ship_building_collision(gv)

    # Station info live update
    if gv._station_info.open:
        gv._station_info.update_stats(
            gv.inventory.total_iron,
            len(gv.asteroid_list),
            len(gv.alien_list),
        )
    if gv._station_info.open:
        near = any(
            math.hypot(gv.player.center_x - b.center_x,
                       gv.player.center_y - b.center_y) < 400.0
            for b in gv.building_list
        )
        if not near:
            gv._station_info.open = False


def update_respawns(gv: GameView, dt: float) -> None:
    """Tick respawn timers for asteroids and aliens."""
    gv._asteroid_respawn_timer += dt
    if gv._asteroid_respawn_timer >= RESPAWN_INTERVAL:
        gv._asteroid_respawn_timer = 0.0
        gv._try_respawn_asteroids()

    gv._alien_respawn_timer += dt
    if gv._alien_respawn_timer >= RESPAWN_INTERVAL:
        gv._alien_respawn_timer = 0.0
        gv._try_respawn_aliens()


def update_boss(gv: GameView, dt: float) -> None:
    """Boss spawn check and update."""
    gv._check_boss_spawn()
    if gv._boss is not None and gv._boss.hp > 0:
        station_x, station_y = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        for b in gv.building_list:
            if isinstance(b, HomeStation) and not b.disabled:
                station_x, station_y = b.center_x, b.center_y
                break
        projs = gv._boss.update_boss(
            dt,
            gv.player.center_x, gv.player.center_y,
            station_x, station_y,
            gv.asteroid_list,
        )
        for p in projs:
            gv._boss_projectile_list.append(p)
        for proj in list(gv._boss_projectile_list):
            proj.update_projectile(dt)
        handle_boss_projectile_hits(gv)
        handle_boss_laser_hits(gv)
        handle_boss_player_collision(gv)
        handle_boss_building_hits(gv)
        if gv._boss._charging and gv._boss._charge_windup <= 0.0:
            handle_boss_charge_hit(gv)


def update_effects(gv: GameView, dt: float) -> None:
    """Advance explosions, hit sparks, and fire sparks."""
    for exp in list(gv.explosion_list):
        exp.update_explosion(dt)

    for spark in gv.hit_sparks:
        spark.update(dt)
    gv.hit_sparks = [s for s in gv.hit_sparks if not s.dead]

    for fs in gv.fire_sparks:
        fs.update(dt)
    gv.fire_sparks = [fs for fs in gv.fire_sparks if not fs.dead]
