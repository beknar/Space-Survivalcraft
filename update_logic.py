"""Game update logic extracted from GameView.on_update."""
from __future__ import annotations

import gc
import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    DEAD_ZONE, CONTRAIL_MAX_PARTICLES, CONTRAIL_SPAWN_RATE, CONTRAIL_LIFETIME,
    CONTRAIL_START_SIZE, CONTRAIL_END_SIZE, CONTRAIL_OFFSET,
    REPAIR_RANGE, REPAIR_RATE, REPAIR_SHIELD_BOOST,
    CRAFT_RESULT_COUNT,
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
    handle_parked_ship_damage,
)

if TYPE_CHECKING:
    from game_view import GameView


# ── Sound player cleanup ──────────────────────────────────────────────────
# arcade.play_sound() returns a pyglet.media.Player. Pyglet's internal
# event system holds a strong reference to every Player, and Player.playing
# stays True even AFTER the source is exhausted. So finished players are
# never freed — even by gc.collect(). Over minutes of continuous combat,
# hundreds of dead Players accumulate and degrade FPS.
#
# Fix: track each player with a creation timestamp, then .delete() any
# player older than _SOUND_MAX_AGE seconds. All game SFX are < 2 s long,
# so 3 s is a safe upper bound.
import time as _time

_SOUND_MAX_AGE = 3.0  # seconds — all game SFX finish within this
_sound_players: list[tuple[float, object]] = []  # (creation_time, Player)
_sound_cleanup_timer: float = 0.0

_real_play_sound = arcade.play_sound


def _tracked_play_sound(*args, **kwargs):
    """Wrapper around arcade.play_sound that tracks the returned Player
    with a creation timestamp."""
    player = _real_play_sound(*args, **kwargs)
    if player is not None:
        _sound_players.append((_time.perf_counter(), player))
    return player


# Monkey-patch arcade.play_sound at module load time
arcade.play_sound = _tracked_play_sound


def _cleanup_finished_sounds() -> None:
    """Delete pyglet Players older than _SOUND_MAX_AGE seconds."""
    now = _time.perf_counter()
    alive = []
    for created_at, p in _sound_players:
        if now - created_at < _SOUND_MAX_AGE:
            alive.append((created_at, p))
        else:
            try:
                p.delete()
            except Exception:
                pass
    _sound_players.clear()
    _sound_players.extend(alive)


def update_preamble(gv: GameView, dt: float) -> None:
    """GC, FPS, video/music sync, sound cleanup, and escape menu tick."""
    global _sound_cleanup_timer
    # Full GC when ESC menu opens (existing behaviour)
    if gv._escape_menu.open and not gv._gc_ran:
        gc.collect()
        gv._gc_ran = True
    elif not gv._escape_menu.open:
        gv._gc_ran = False
    # Periodic sound player cleanup + full GC (every 5 seconds).
    # Sound cleanup: .delete()s finished pyglet Players that hold native
    # audio resources (prevents FPS degradation over minutes of combat).
    # Full GC: frees arcade.Sprite objects with cross-generational circular
    # references from inventory render-cache rebuilds. Cost is ~0.5–1 ms
    # which is acceptable within a 16.7 ms frame budget at 60 FPS.
    _sound_cleanup_timer += dt
    if _sound_cleanup_timer >= 5.0:
        _sound_cleanup_timer = 0.0
        _cleanup_finished_sounds()
        gc.collect()
    # FPS
    gv._hud.update_fps(dt)
    gv._hud._show_fps = audio.show_fps
    # Module-slot cooldown flash: track which ability modules are
    # currently in cooldown so the HUD can tint their slot red.
    cooling: set[str] = set()
    if getattr(gv, "_misty_step_cd", 0.0) > 0.0:
        cooling.add("misty_step")
    if getattr(gv, "_force_wall_cd", 0.0) > 0.0:
        cooling.add("force_wall")
    if getattr(gv, "_death_blossom_active", False):
        cooling.add("death_blossom")
    gv._hud._mod_cooldowns = cooling
    gv._hud._mod_flash_t += dt
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
    if gv._use_glow_timer > 0.0:
        gv._use_glow_timer = max(0.0, gv._use_glow_timer - dt)
    # Hold-to-sell loop: consume timer and drain inventory if held.
    if gv._trade_menu.open:
        action = gv._trade_menu.on_update(
            dt, inventory=gv.inventory, station_inv=gv._station_inv,
        )
        if action is not None:
            from input_handlers import apply_trade_action
            apply_trade_action(gv, action)


def update_repair_and_shields(gv: GameView, dt: float) -> None:
    """Repair module proximity check, shield regen, HP/building healing."""
    # Cache home station and repair module references to avoid per-frame isinstance scans
    home = getattr(gv, '_cached_home', None)
    has_repair = getattr(gv, '_cached_has_repair', False)
    if home is not None and (home not in gv.building_list or home.disabled):
        home = None
        gv._cached_home = None
    if home is None or not has_repair:
        # Rebuild cache (runs once after station changes, not every frame)
        home = None
        has_repair = False
        for b in gv.building_list:
            if isinstance(b, HomeStation) and not b.disabled:
                home = b
            elif isinstance(b, RepairModule) and not b.disabled:
                has_repair = True
        gv._cached_home = home
        gv._cached_has_repair = has_repair

    repair_near_home = False
    if has_repair and home is not None:
        dx = gv.player.center_x - home.center_x
        dy = gv.player.center_y - home.center_y
        if dx * dx + dy * dy <= REPAIR_RANGE * REPAIR_RANGE:
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
                    info = MODULE_TYPES[target]
                    if info.get("consumable"):
                        item_key = info.get("item_key", target)
                        gv._station_inv.add_item(
                            item_key, info.get("craft_count", 1))
                    else:
                        gv._station_inv.add_item(f"mod_{target}", 1)
                elif target == "shield_recharge":
                    gv._station_inv.add_item("shield_recharge", CRAFT_RESULT_COUNT)
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

    # Rear turret auto-fire (fires backward, same stats as broadside)
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


def update_entities(gv: GameView, dt: float) -> None:
    """Advance pickups, asteroids, aliens, and handle collisions.

    Note: player projectiles are advanced in game_view.on_update (shared).
    """
    # Collisions
    handle_projectile_hits(gv)
    handle_ship_asteroid_collision(gv)

    # Asteroids
    for asteroid in gv.asteroid_list:
        asteroid.update_asteroid(dt)

    # Note: pickup collection moved to game_view.on_update (shared across all zones)

    # Alien AI
    px, py = gv.player.center_x, gv.player.center_y
    for alien in list(gv.alien_list):
        proj = alien.update_alien(
            dt, px, py,
            gv.asteroid_list, gv.alien_list,
            force_walls=gv._force_walls,
        )
        if proj is not None:
            gv.alien_projectile_list.append(proj)

    # Alien collisions (aliens pass through each other but collide with asteroids)
    handle_alien_player_collision(gv)
    handle_alien_asteroid_collision(gv)

    # Alien projectiles
    for proj in list(gv.alien_projectile_list):
        proj.update_projectile(dt)
    handle_alien_laser_hits(gv)

    # Parked ship damage + animation update
    handle_parked_ship_damage(gv)
    _update_parked_ships(gv, dt)


def update_refugee_npc(gv: GameView, dt: float) -> None:
    """Spawn + approach the Double Star Refugee.

    Spawns once per save as soon as a ``Shield Generator`` is present in
    the station while the player is inside Zone 2. After spawn, the NPC
    flies in from the right edge and holds at ``NPC_REFUGEE_HOLD_DIST``
    of the Home Station. Does nothing in other zones.
    """
    from zones import ZoneID
    from sprites.building import HomeStation
    from constants import (
        WORLD_WIDTH, WORLD_HEIGHT, NPC_REFUGEE_HOLD_DIST,
    )
    from sprites.npc_ship import RefugeeNPCShip

    if getattr(gv, "_zone", None) is None:
        return
    if gv._zone.zone_id != ZoneID.ZONE2:
        return

    home = next((b for b in gv.building_list
                 if isinstance(b, HomeStation) and not b.disabled), None)

    if gv._refugee_npc is None:
        if gv._refugee_spawned or home is None:
            return
        has_shield_gen = any(b.building_type == "Shield Generator"
                             for b in gv.building_list)
        if not has_shield_gen:
            return
        zone = gv._zone
        zw = getattr(zone, "world_width", WORLD_WIDTH)
        zh = getattr(zone, "world_height", WORLD_HEIGHT)
        spawn_x = zw - 80.0
        spawn_y = max(80.0, min(zh - 80.0, home.center_y))
        gv._refugee_npc = RefugeeNPCShip(
            spawn_x, spawn_y, (home.center_x, home.center_y))
        gv._refugee_spawned = True
        return

    # Already spawned — advance approach while a home still exists.
    if home is not None:
        gv._refugee_npc._target = (home.center_x, home.center_y)
    gv._refugee_npc.update_npc(dt)


def _update_parked_ships(gv: GameView, dt: float) -> None:
    """Tick parked-ship hit flash + AI pilot (when `ai_pilot` is installed).

    AI-piloted parked ships patrol around the Home Station and fire into
    ``gv.turret_projectile_list`` so existing turret projectile
    collisions deliver the damage (no new collision handler needed).
    """
    from sprites.building import HomeStation
    home = next((b for b in gv.building_list
                 if isinstance(b, HomeStation) and not b.disabled), None)
    home_pos = (home.center_x, home.center_y) if home is not None else None
    # Pick the target list matching the active zone so AI ships don't
    # shoot ghosts from the stashed zone.
    targets = list(gv.alien_list)
    zone = getattr(gv, "_zone", None)
    z2_aliens = getattr(zone, "_aliens", None)
    if z2_aliens is not None and z2_aliens is not gv.alien_list:
        targets.extend(z2_aliens)
    if gv._boss is not None and gv._boss.hp > 0:
        targets.append(gv._boss)
    laser_tex = getattr(gv, "_turret_laser_tex", None)
    for ps in gv._parked_ships:
        ps.update_parked(dt)
        if ps.has_ai_pilot:
            ps.update_ai(dt, home_pos, targets,
                         gv.turret_projectile_list, laser_tex)


def update_buildings(gv: GameView, dt: float) -> None:
    """Update buildings, turrets, and station info."""
    from sprites.building import MissileArray
    for b in list(gv.building_list):
        b.update_building(dt)
        if isinstance(b, Turret):
            b.update_turret(dt, gv.alien_list,
                            gv.turret_projectile_list,
                            boss=gv._boss)
        elif isinstance(b, MissileArray):
            b.update_missile_array(
                dt, gv.alien_list, gv._missile_list,
                gv._missile_tex, boss=gv._boss,
            )

    for proj in list(gv.turret_projectile_list):
        proj.update_projectile(dt)

    handle_turret_projectile_hits(gv)
    handle_alien_laser_building_hits(gv)
    handle_alien_building_collision(gv)
    handle_ship_building_collision(gv)

    # Station info live update (throttled to 2x/sec to avoid GC stalls)
    if gv._station_info.open:
        gv._station_info._update_cd = getattr(
            gv._station_info, '_update_cd', 0.0) - dt
        if gv._station_info._update_cd <= 0.0:
            gv._station_info._update_cd = 0.5
            from draw_logic import compute_world_stats, compute_inactive_zone_stats
            gv._station_info.update_stats(
                compute_world_stats(gv),
                inactive_zone_stats=compute_inactive_zone_stats(gv),
            )
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
        if gv._boss is not None and gv._boss._charging and gv._boss._charge_windup <= 0.0:
            handle_boss_charge_hit(gv)


def update_wormholes(gv: GameView, dt: float) -> None:
    """Update wormhole spiral animations and check player collision."""
    import arcade
    for wh in gv._wormholes:
        wh.update_wormhole(dt)
    # Check player entering a wormhole (100px detection = visual overlap)
    px, py = gv.player.center_x, gv.player.center_y
    for wh in gv._wormholes:
        dist = math.hypot(px - wh.center_x, py - wh.center_y)
        if dist < 100:
            # Visual effect: bright flash glow
            gv._use_glow = (100, 180, 255, 200)
            gv._use_glow_timer = 0.5
            # Play victory sound as warp sound
            arcade.play_sound(gv._victory_snd, volume=0.6)
            # Determine destination
            if wh.zone_target is not None:
                target = wh.zone_target
            else:
                # Random warp zone
                from zones import ZoneID
                target = random.choice([
                    ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                    ZoneID.WARP_GAS, ZoneID.WARP_ENEMY,
                ])
            gv._flash_game_msg("Entering wormhole...", 1.5)
            gv._transition_zone(target, entry_side="bottom")
            return


def update_ability_meter(gv: GameView, dt: float) -> None:
    """Regen the special ability meter and update module cooldowns."""
    from constants import ABILITY_REGEN_RATE
    if gv._ability_meter < gv._ability_meter_max:
        gv._ability_meter = min(gv._ability_meter_max,
                                gv._ability_meter + ABILITY_REGEN_RATE * dt)
    if gv._misty_step_cd > 0:
        gv._misty_step_cd = max(0.0, gv._misty_step_cd - dt)
    if getattr(gv, '_force_wall_cd', 0.0) > 0:
        gv._force_wall_cd = max(0.0, gv._force_wall_cd - dt)
    if gv._rear_turret_cd > 0:
        gv._rear_turret_cd = max(0.0, gv._rear_turret_cd - dt)
    if hasattr(gv, '_missile_fire_cd') and gv._missile_fire_cd > 0:
        gv._missile_fire_cd = max(0.0, gv._missile_fire_cd - dt)
    # Promote a held-LMB long press into an active move even if the mouse
    # never moves. The drag handler also promotes, so position stays fresh
    # once the cursor does move.
    if gv._move_candidate is not None and gv._moving_building is None:
        import time as _time
        from constants import MOVE_LONG_PRESS_TIME
        if (_time.monotonic() - gv._move_press_time) >= MOVE_LONG_PRESS_TIME:
            gv._moving_building = gv._move_candidate
            gv._move_candidate = None


def update_force_walls(gv: GameView, dt: float) -> None:
    """Update force wall lifetimes and absorb enemy projectiles they block."""
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


def update_missiles(gv: GameView, dt: float) -> None:
    """Update homing missiles and check hits."""
    from sprites.explosion import HitSpark

    # Gather targets (aliens in current zone)
    from zones import ZoneID
    targets = []
    if gv._zone.zone_id == ZoneID.MAIN:
        for a in gv.alien_list:
            targets.append((a.center_x, a.center_y))
        if gv._boss is not None and gv._boss.hp > 0:
            targets.append((gv._boss.center_x, gv._boss.center_y))
    elif hasattr(gv._zone, '_aliens'):
        for a in gv._zone._aliens:
            targets.append((a.center_x, a.center_y))

    from collisions import _apply_kill_rewards
    from character_data import bonus_iron_enemy
    from constants import ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN
    for m in list(gv._missile_list):
        m.update_missile(dt, targets)
        # Check hits on aliens
        if gv._zone.zone_id == ZoneID.MAIN:
            for a in list(gv.alien_list):
                if math.hypot(m.center_x - a.center_x, m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        _apply_kill_rewards(
                            gv, a.center_x, a.center_y,
                            ALIEN_IRON_DROP, bonus_iron_enemy,
                            BLUEPRINT_DROP_CHANCE_ALIEN,
                        )
                        a.remove_from_sprite_lists()
                    m.remove_from_sprite_lists()
                    break
        elif hasattr(gv._zone, '_aliens'):
            from zones.zone2_world import drop_zone2_alien_loot
            for a in list(gv._zone._aliens):
                if math.hypot(m.center_x - a.center_x, m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        drop_zone2_alien_loot(gv._zone, gv, a)
                    m.remove_from_sprite_lists()
                    break


def update_death_blossom(gv: GameView, dt: float) -> None:
    """Update death blossom sequence if active."""
    if not gv._death_blossom_active:
        return
    from constants import DEATH_BLOSSOM_FIRE_RATE, DEATH_BLOSSOM_MISSILES_PER_VOLLEY, DEATH_BLOSSOM_HP_AFTER
    from sprites.missile import HomingMissile

    # Continuous spin at the ship's max rotation rate while active
    gv.player.heading = (gv.player.heading + gv.player._rot_speed * dt) % 360
    gv.player.angle = gv.player.heading

    gv._death_blossom_timer -= dt
    if gv._death_blossom_timer <= 0 and gv._death_blossom_missiles_left > 0:
        gv._death_blossom_timer = DEATH_BLOSSOM_FIRE_RATE
        # Fire missiles in all directions
        count = min(DEATH_BLOSSOM_MISSILES_PER_VOLLEY, gv._death_blossom_missiles_left)
        for i in range(count):
            angle = (360.0 / count) * i + gv.player.heading
            m = HomingMissile(gv._missile_tex,
                              gv.player.center_x, gv.player.center_y, angle)
            gv._missile_list.append(m)
        gv._death_blossom_missiles_left -= count

    if gv._death_blossom_missiles_left <= 0:
        # End death blossom — power down
        gv._death_blossom_active = False
        gv.player.shields = 0
        gv.player.hp = DEATH_BLOSSOM_HP_AFTER


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
