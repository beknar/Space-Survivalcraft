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
    handle_nebula_boss_projectile_hits,
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
# Full ``gc.collect()`` (gen-2) is measurably expensive in a populated
# Zone 2 — the fps_drops log showed one 60–100 ms spike every 5 s that
# lined up exactly with this timer.  Split so the 5-s cadence only
# runs a cheap gen-0 sweep and the heavy full collection runs 6×
# less often (every 30 s).
_full_gc_timer: float = 0.0
# Last fps_drops.log showed the 30-s scheduled full gc.collect was
# freeing only ~3 MB per run (memory steady at ~268 MB from frame
# 36s onwards) yet costing 100–230 ms spikes that visibly stutter
# the game.  Extend to 120 s — same 3 MB / 30 s average reclaim,
# just 4× fewer pauses.  The sound-cleanup gen-0 sweep every 5 s
# still runs, and modal overlays (ESC, CRAFT, …) still trigger an
# opportunistic full gc below since those frames are already
# pause-natural.
_FULL_GC_INTERVAL = 60.0

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


_MAX_DELETES_PER_TICK = 4  # spread pyglet Player.delete over frames


def _cleanup_finished_sounds() -> None:
    """Delete at most ``_MAX_DELETES_PER_TICK`` pyglet Players older
    than ``_SOUND_MAX_AGE`` seconds.

    ``Player.delete`` releases native OpenAL + FFmpeg resources and
    can stall 20–40 ms each — with 10+ stale players piling up
    during a combat burst, the prior "delete everything at once"
    pass caused the 150–200 ms mid-session spikes seen in
    fps_drops.log.  Rate-limiting to 4 per tick keeps the worst
    cleanup cost under ~160 ms total across separate frames.
    Remaining stale players survive into the next 5-s tick, which
    is fine — they're already finished playing.
    """
    now = _time.perf_counter()
    deletes_remaining = _MAX_DELETES_PER_TICK
    alive: list[tuple[float, object]] = []
    for created_at, p in _sound_players:
        if now - created_at < _SOUND_MAX_AGE or deletes_remaining <= 0:
            alive.append((created_at, p))
        else:
            deletes_remaining -= 1
            try:
                p.delete()
            except Exception:
                pass
    _sound_players.clear()
    _sound_players.extend(alive)


def update_preamble(gv: GameView, dt: float) -> None:
    """GC, FPS, video/music sync, sound cleanup, and escape menu tick."""
    global _sound_cleanup_timer, _full_gc_timer
    # (Previously ran a forced ``gc.collect()`` the first frame the
    # ESC menu opened — the comment claimed the 60–100 ms hit was
    # "invisible" because the frame is paused anyway.  fps_drops.log
    # then showed a 602 ms spike on ESC-open.  Removed; the 120-s
    # periodic full GC below is sufficient and doesn't spike visibly.)
    gv._gc_ran = False
    # Periodic sound-player cleanup (every 5 s).  Always paired with
    # a cheap gen-0 collection to reclaim the short-lived cycles the
    # cleanup itself creates (list churn, exception objects from the
    # occasional ``p.delete()`` throw).  gen-0 is ~0.1–0.2 ms.
    _sound_cleanup_timer += dt
    if _sound_cleanup_timer >= 5.0:
        _sound_cleanup_timer = 0.0
        _cleanup_finished_sounds()
        gc.collect(0)
    # Periodic generation-1 sweep — replaces the 120-s gen-2
    # gc.collect() that was costing 49–51 ms spikes (visible in
    # logs/star_maze_perf.jsonl as gv_preamble outliers).  gen-1
    # collects gen-0 + gen-1 (skip gen-2's deep cycle walk), so the
    # spike drops from ~50 ms to ~5 ms.  Cadence shortened to 60 s
    # since each pass is cheaper.  gen-2 still runs automatically via
    # Python's threshold-based scheduler when allocations actually
    # warrant it.
    _full_gc_timer += dt
    if _full_gc_timer >= _FULL_GC_INTERVAL:
        _full_gc_timer = 0.0
        gc.collect(1)
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
    # Always drain VideoPlayer's deferred-cleanup queue, even when
    # neither video player is active.  vp.update / vp.update_volume
    # only run while active, so without this an idle window between
    # video sessions would let retired pyglet Players pile up in
    # the cleanup queue, leaking ~12 MB of FFmpeg state per cycle.
    from video_player import VideoPlayer
    VideoPlayer._drain_pending_cleanup()
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
    """Update explosions/sparks during death delay; auto-respawn
    the player when the timer expires.  The legacy death screen is
    no longer shown — the respawn-on-death system in
    ``combat_helpers.respawn_player`` handles every death case
    (soft respawn at the last station, or full reset to Zone 1
    centre when no stations exist)."""
    for exp in list(gv.explosion_list):
        exp.update_explosion(dt)
    for fs in gv.fire_sparks:
        fs.update(dt)
    gv.fire_sparks = [fs for fs in gv.fire_sparks if not fs.dead]
    if hasattr(gv, '_death_delay') and gv._death_delay > 0:
        gv._death_delay -= dt
        if gv._death_delay <= 0:
            from combat_helpers import respawn_player
            respawn_player(gv)


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

    # Scale movement dt by the Nebula-boss gas-slow factor when the
    # slow timer is active.  Halves effective thrust/speed by
    # shortening the simulated frame the player sees.
    from constants import NEBULA_BOSS_SLOW_FACTOR
    move_dt = dt
    if getattr(gv, "_nebula_slow_timer", 0.0) > 0.0:
        move_dt = dt * NEBULA_BOSS_SLOW_FACTOR
    gv.player.apply_input(move_dt, rl, rr, tf, tb, sl, sr)

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
                # Ascended Thunderbolt's engine exhaust sits at the
                # centre of the sprite, not the tail — emit from the
                # ship centre for that combo only.
                if (getattr(gv.player, "_faction", None) == "Ascended"
                        and getattr(gv.player, "_ship_type", None)
                            == "Thunderbolt"):
                    offset = 0.0
                else:
                    offset = abs(CONTRAIL_OFFSET)
                ex = gv.player.center_x - math.sin(rad) * offset
                ey = gv.player.center_y - math.cos(rad) * offset
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

    fired_any = False
    if fire:
        from sprites.explosion import HitSpark
        spawn_pts = gv.player.gun_spawn_points()
        gun_count = gv.player.guns
        base_idx = (gv._weapon_idx // gun_count) * gun_count
        for gi in range(gun_count):
            wpn = gv._weapons[base_idx + gi]
            pt = spawn_pts[gi] if gi < len(spawn_pts) else spawn_pts[0]
            proj = wpn.fire(pt[0], pt[1], gv.player.heading)
            if proj is not None:
                gv.projectile_list.append(proj)
                fired_any = True
                # Muzzle flash — short ring-flash at the gun barrel so
                # every shot reads visibly regardless of projectile
                # speed.  Re-uses the existing HitSpark primitive
                # (0.18 s lifetime, already drawn in draw_world).
                gv.hit_sparks.append(HitSpark(pt[0], pt[1]))
    if fired_any:
        disable_null_field_around_player(gv)

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

    # Alien AI — when the player is cloaked by a null field, feed the
    # aliens a synthetic player position far outside detect range so
    # they stay in PATROL (and drop out of PURSUE).
    px, py = gv.player.center_x, gv.player.center_y
    if player_is_cloaked(gv):
        ai_px, ai_py = px + 1e9, py + 1e9
    else:
        ai_px, ai_py = px, py
    for alien in list(gv.alien_list):
        proj = alien.update_alien(
            dt, ai_px, ai_py,
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


def _station_outer_radius(gv: GameView, home) -> float:
    """Return the furthest distance from the Home Station to any other
    connected building's EDGE — used to size both the station shield and
    the refugee's parking spot. Adds ``BUILDING_RADIUS`` so the measured
    radius covers the full visual extent, not just building centres."""
    import math as _math
    from constants import BUILDING_RADIUS
    r = 0.0
    hx, hy = home.center_x, home.center_y
    for b in gv.building_list:
        if b is home:
            continue
        d = _math.hypot(b.center_x - hx, b.center_y - hy) + BUILDING_RADIUS
        if d > r:
            r = d
    return r


def update_station_shield(gv: GameView, dt: float) -> None:
    """Spawn + maintain the station shield.

    Triggered by the presence of a ``Shield Generator`` while a Home
    Station is up. Shield HP resets to ``STATION_SHIELD_MAX_HP`` on
    first spawn; each frame the shield's radius is recomputed so it
    grows with the station. Damage is applied by the collision
    handlers in `collisions.py` (see `_try_absorb_station_shield`).
    Once HP reaches zero the sprite stays attached but is hidden.
    """
    from sprites.building import HomeStation
    from world_setup import get_shield_frames, faction_shield_tint
    from sprites.shield import ShieldSprite
    from constants import (
        STATION_SHIELD_HP, STATION_SHIELD_PADDING, SHIELD_FRAME_W,
    )

    home = next((b for b in gv.building_list
                 if isinstance(b, HomeStation) and not b.disabled), None)
    has_sg = any(b.building_type == "Shield Generator"
                 for b in gv.building_list)
    if home is None or not has_sg:
        return

    if gv._station_shield_sprite is None:
        tint = faction_shield_tint(gv._faction)
        frames = get_shield_frames()
        sprite = ShieldSprite(frames, tint=tint, scale=1.0, alpha=15)
        sprite.center_x = home.center_x
        sprite.center_y = home.center_y
        gv._station_shield_sprite = sprite
        gv._station_shield_list = arcade.SpriteList()
        gv._station_shield_list.append(sprite)
        if gv._station_shield_hp <= 0:
            gv._station_shield_hp = STATION_SHIELD_HP
        gv._station_shield_max_hp = STATION_SHIELD_HP

    # Size the shield so it covers every connected building.
    outer_r = _station_outer_radius(gv, home) + STATION_SHIELD_PADDING
    gv._station_shield_radius = outer_r
    diameter = max(2.0 * outer_r, 160.0)
    gv._station_shield_sprite.scale = diameter / SHIELD_FRAME_W
    gv._station_shield_sprite.update_shield(
        dt, home.center_x, home.center_y, gv._station_shield_hp)


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

    # The refugee parks OUTSIDE the station so its sprite doesn't
    # overlap any building. The parking spot is placed to the right of
    # the Home Station by (station_outer_radius + padding).
    from constants import NPC_REFUGEE_HOLD_DIST as _NPC_BASE_HOLD
    _NPC_PARK_HOLD = 24.0     # stop within this of the parking spot
    _NPC_PARK_PAD = 120.0     # extra clearance from the outermost building edge

    def _parking_spot(gv_: GameView, home_) -> tuple[float, float]:
        outer = _station_outer_radius(gv_, home_) + _NPC_PARK_PAD
        return (home_.center_x + outer, home_.center_y)

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
            spawn_x, spawn_y, _parking_spot(gv, home),
            hold_dist=_NPC_PARK_HOLD)
        gv._refugee_spawned = True
        return

    # Already spawned — keep the parking spot fresh (it grows with the
    # station) while approaching or arrived.
    if home is not None:
        gv._refugee_npc._target = _parking_spot(gv, home)
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
    nb = getattr(gv, "_nebula_boss", None)
    if nb is not None and nb.hp > 0:
        targets.append(nb)
    laser_tex = getattr(gv, "_turret_laser_tex", None)
    for ps in gv._parked_ships:
        ps.update_parked(dt)
        if ps.has_ai_pilot:
            ps.update_ai(dt, home_pos, targets,
                         gv.turret_projectile_list, laser_tex)


def update_buildings(gv: GameView, dt: float) -> None:
    """Update buildings, turrets, and station info."""
    from sprites.building import MissileArray
    # Station defenders (turrets + missile arrays) fire at every live
    # boss, not just the Double Star, so summoning the Nebula boss
    # via the QWI doesn't leave the station staring at an enemy it
    # can't engage.  ``bosses`` is a list of current targets; dead /
    # missing ones are filtered inside the building's targeting loop.
    live_bosses = [gv._boss, getattr(gv, "_nebula_boss", None)]
    for b in list(gv.building_list):
        b.update_building(dt)
        if isinstance(b, Turret):
            b.update_turret(dt, gv.alien_list,
                            gv.turret_projectile_list,
                            bosses=live_bosses)
        elif isinstance(b, MissileArray):
            b.update_missile_array(
                dt, gv.alien_list, gv._missile_list,
                gv._missile_tex, bosses=live_bosses,
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


def _boss_update_context(gv: GameView) -> tuple[float, float, float, float]:
    """Return (station_x, station_y, boss_px, boss_py) for the boss
    update path.  Looks up the active Home Station (falls back to
    world centre) and feeds the boss a cloak-aware player position:
    when the player is inside an active null field, we hand the boss
    coordinates a billion pixels away so its AI stays in patrol
    instead of engaging.  Shared by both the Double Star boss and
    the Nebula boss update loops.
    """
    station_x, station_y = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    for b in gv.building_list:
        if isinstance(b, HomeStation) and not b.disabled:
            station_x, station_y = b.center_x, b.center_y
            break
    if player_is_cloaked(gv):
        boss_px, boss_py = gv.player.center_x + 1e9, gv.player.center_y + 1e9
    else:
        boss_px, boss_py = gv.player.center_x, gv.player.center_y
    return station_x, station_y, boss_px, boss_py


def update_boss(gv: GameView, dt: float) -> None:
    """Boss spawn check and update."""
    gv._check_boss_spawn()
    if gv._boss is not None and gv._boss.hp > 0:
        station_x, station_y, boss_px, boss_py = _boss_update_context(gv)
        projs = gv._boss.update_boss(
            dt, boss_px, boss_py,
            station_x, station_y,
            gv.asteroid_list,
            force_walls=getattr(gv, "_force_walls", None),
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


def update_nebula_boss(gv: GameView, dt: float) -> None:
    """Per-frame tick for the Nebula boss (spawned via QWI menu).

    Inherits the parent ``update_boss`` flow for movement + cannon
    fire + phase management, and layers on the gas-cloud projectile
    + cone-AoE attacks.  Gas clouds apply damage + a time-limited
    slow to the player on contact.  The cone applies both while the
    player is inside it."""
    import math as _math
    nb = getattr(gv, "_nebula_boss", None)
    if nb is None or nb.hp <= 0:
        return

    # Shared preamble: home station anchor + cloak-aware player pos.
    station_x, station_y, boss_px, boss_py = _boss_update_context(gv)

    # Run the base BossAlienShip update (movement, cannon + spread,
    # charge dash).  Projectiles go to the standard boss projectile
    # list so existing collision handlers deliver damage.
    asteroid_list = gv.asteroid_list
    zone = getattr(gv, "_zone", None)
    zone_asts = getattr(zone, "_iron_asteroids", None)
    if zone_asts is not None:
        asteroid_list = zone_asts
    projs = nb.update_boss(
        dt, boss_px, boss_py, station_x, station_y, asteroid_list,
        force_walls=getattr(gv, "_force_walls", None))
    # Nebula boss rams through asteroids instead of steering around
    # them — destroy any the boss is currently overlapping and drop
    # normal loot.  Only runs when the boss lives in Zone 2 (the
    # crush helper reads from ``zone._iron_asteroids`` etc.).
    if zone is not None and hasattr(zone, "_iron_asteroids"):
        from zones.zone2_world import nebula_boss_destroy_asteroids
        nebula_boss_destroy_asteroids(zone, gv, nb)
    for p in projs:
        gv._boss_projectile_list.append(p)

    # Nebula-specific tick — returns a GasCloudProjectile when the
    # gas cooldown expires.
    new_gas = nb.tick_nebula(dt, boss_px, boss_py)
    if new_gas is not None:
        gv._nebula_gas_clouds.append(new_gas)

    # Advance gas clouds + test hit on the player.
    px, py = gv.player.center_x, gv.player.center_y
    survivors = []
    for c in gv._nebula_gas_clouds:
        expired = c.update_gas(dt)
        hit = c.contains_point(px, py)
        if hit and not getattr(gv, "_player_dead", False):
            from combat_helpers import apply_damage_to_player
            apply_damage_to_player(gv, int(c.damage))
            _apply_nebula_slow(gv)
            # Cloud dissipates on hit.
            continue
        if not expired:
            survivors.append(c)
    gv._nebula_gas_clouds = survivors

    # Cone tick — damage while player inside; slow + damage ~2 Hz.
    if getattr(nb, "_cone_active", False):
        if nb.cone_contains_point(px, py):
            if not hasattr(gv, "_nebula_cone_tick_cd"):
                gv._nebula_cone_tick_cd = 0.0
            gv._nebula_cone_tick_cd -= dt
            if gv._nebula_cone_tick_cd <= 0.0:
                from constants import NEBULA_BOSS_CONE_DAMAGE
                from combat_helpers import apply_damage_to_player
                apply_damage_to_player(gv, int(NEBULA_BOSS_CONE_DAMAGE))
                _apply_nebula_slow(gv)
                gv._nebula_cone_tick_cd = 0.5

    # Route player + turret projectiles at the Nebula boss.  Station
    # turrets, Missile Arrays (via missile-explosion hits below), and
    # AI-piloted parked ships all push shots into the same two lists
    # ``_projectiles_vs_boss`` walks, so this one call wires every
    # friendly damage source into the Nebula boss's HP pool.
    handle_nebula_boss_projectile_hits(gv)

    # Clear the boss from GameView once HP drops to zero — the
    # projectile handler already runs _nebula_boss_death on the
    # frame that lands the killing shot, but the boss can also die
    # from gas-cloud / cone internals touching its own HP in
    # future changes, so keep this fallback.
    if gv._nebula_boss is not None and gv._nebula_boss.hp <= 0:
        gv._nebula_boss = None
        gv._nebula_boss_list.clear()
        gv._nebula_gas_clouds.clear()


def _apply_nebula_slow(gv) -> None:
    """Mark the player as slowed for ``NEBULA_BOSS_SLOW_DURATION``
    seconds.  Player movement code (update_movement) honors the
    ``_nebula_slow_timer`` by halving effective speed while it's
    positive."""
    from constants import NEBULA_BOSS_SLOW_DURATION
    gv._nebula_slow_timer = max(
        getattr(gv, "_nebula_slow_timer", 0.0),
        NEBULA_BOSS_SLOW_DURATION,
    )


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


def active_null_fields(gv: GameView) -> list:
    """Return the null-field list for the zone the player is currently
    in. Used by the cloaking gate + the fire-disable hook + drawing.

    Warp zones (meteor / lightning / gas / enemy) never host null
    fields, so when the player is in one we return ``[]`` rather than
    falling through to ``gv._null_fields`` (which belongs to Zone 1).
    """
    from zones import ZoneID
    zone = getattr(gv, "_zone", None)
    zone_fields = getattr(zone, "_null_fields", None)
    if zone_fields:
        return zone_fields
    if getattr(zone, "zone_id", None) is ZoneID.MAIN:
        return getattr(gv, "_null_fields", None) or []
    return []


def find_null_field_at(gv: GameView, x: float, y: float):
    """Return the first null field (in the active zone's list) that
    contains ``(x, y)``, or ``None``. Used by the fire-disable hook."""
    for nf in active_null_fields(gv):
        if nf.contains_point(x, y):
            return nf
    return None


def disable_null_field_around_player(gv: GameView) -> None:
    """Disable every null field containing the player's current
    position for `NULL_FIELD_DISABLE_S` seconds. Called whenever the
    player fires a weapon or triggers an ability from inside one."""
    px, py = gv.player.center_x, gv.player.center_y
    for nf in active_null_fields(gv):
        if nf.contains_point(px, py):
            nf.trigger_disable()


def player_is_cloaked(gv: GameView) -> bool:
    """True when the player is inside an ACTIVE null field (not one
    currently serving a 30-second disable penalty)."""
    if getattr(gv, "_player_dead", False):
        return False
    px, py = gv.player.center_x, gv.player.center_y
    for nf in active_null_fields(gv):
        if nf.active and nf.contains_point(px, py):
            return True
    return False


def active_slipspaces(gv: GameView):
    """Return the slipspace SpriteList for the player's current zone.

    Zone 2 stores its own list on ``zone._slipspaces``; Zone 1 stores
    them on ``gv._slipspaces``.  Warp zones return ``[]`` because they
    deliberately don't host slipspaces — same rule as null fields.
    """
    from zones import ZoneID
    zone = getattr(gv, "_zone", None)
    zone_ss = getattr(zone, "_slipspaces", None)
    if zone_ss:
        return zone_ss
    if getattr(zone, "zone_id", None) is ZoneID.MAIN:
        return getattr(gv, "_slipspaces", None) or []
    return []


def update_slipspaces(gv: GameView, dt: float) -> None:
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


def _check_slipspace_teleport(gv: GameView) -> None:
    """Teleport the player to a random other slipspace if they're
    inside one and weren't inside it last frame.  Velocity + heading
    are preserved.  ``gv._inside_slipspace`` blocks re-trigger while
    the player is still overlapping the destination, so the jump
    fires exactly once per entry."""
    if getattr(gv, "_player_dead", False):
        return
    active = active_slipspaces(gv)
    if not active or len(active) < 2:
        # Need at least one other slipspace to teleport TO.  Also
        # clear the "inside" flag if the player drifted out of the
        # current one between frames.
        gv._inside_slipspace = None
        return
    px, py = gv.player.center_x, gv.player.center_y

    # Still inside the same slipspace as last frame? — do nothing.
    inside = gv._inside_slipspace
    if inside is not None and inside in active and inside.contains_point(px, py):
        return

    # Find the slipspace the player has just entered.
    hit = None
    for ss in active:
        if ss.contains_point(px, py):
            hit = ss
            break
    if hit is None:
        gv._inside_slipspace = None
        return

    # Pick a random destination that isn't the entry slipspace.
    import random as _r
    candidates = [ss for ss in active if ss is not hit]
    dest = _r.choice(candidates)

    # Teleport — preserve velocity + heading.
    gv.player.center_x = dest.center_x
    gv.player.center_y = dest.center_y
    # Mark the destination as the "currently inside" so we don't
    # immediately bounce back through another slipspace.
    gv._inside_slipspace = dest
    # Keep the shield sprite glued to the player so it doesn't
    # streak across the screen for one frame.
    if hasattr(gv, "shield_sprite") and gv.shield_sprite is not None:
        gv.shield_sprite.center_x = dest.center_x
        gv.shield_sprite.center_y = dest.center_y

    # Sound — use the cached slipspace SFX loaded in GameView init.
    snd = getattr(gv, "_slipspace_snd", None)
    if snd is not None:
        try:
            from settings import audio as _audio
            arcade.play_sound(snd, volume=_audio.sfx_volume)
        except Exception:
            pass


def update_null_fields(gv: GameView, dt: float) -> None:
    """Tick disabled-timer animation on every null field in the
    active zone (and the Zone 1 fields too, so Zone 2 -> Zone 1
    transitions don't leave a stale disable on a Zone 1 field)."""
    seen: set = set()
    # Zone 1 fields on the GameView
    z1 = getattr(gv, "_null_fields", None) or []
    for nf in z1:
        if id(nf) not in seen:
            nf.update_null_field(dt)
            seen.add(id(nf))
    # Zone 2 fields on the zone object
    zone = getattr(gv, "_zone", None)
    z2 = getattr(zone, "_null_fields", None) or []
    for nf in z2:
        if id(nf) not in seen:
            nf.update_null_field(dt)
            seen.add(id(nf))


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


def update_missiles(gv: GameView, dt: float) -> None:
    """Update homing missiles and check hits."""
    from sprites.explosion import HitSpark

    # Gather targets (aliens in current zone + any live boss in any zone).
    from zones import ZoneID
    targets = []
    if gv._zone.zone_id == ZoneID.MAIN:
        for a in gv.alien_list:
            targets.append((a.center_x, a.center_y))
    elif hasattr(gv._zone, '_aliens'):
        for a in gv._zone._aliens:
            targets.append((a.center_x, a.center_y))
    # Star Maze: maze aliens + live spawners are both homing targets.
    if gv._zone.zone_id == ZoneID.STAR_MAZE:
        for a in getattr(gv._zone, "_maze_aliens", ()):
            targets.append((a.center_x, a.center_y))
        for sp in getattr(gv._zone, "spawners", ()):
            if not sp.killed:
                targets.append((sp.center_x, sp.center_y))
    # Bosses are zone-agnostic targets — the Double Star lives in the
    # zone it was summoned in, the Nebula boss in Zone 2 via the QWI.
    if gv._boss is not None and gv._boss.hp > 0:
        targets.append((gv._boss.center_x, gv._boss.center_y))
    nb_target = getattr(gv, "_nebula_boss", None)
    if nb_target is not None and nb_target.hp > 0:
        targets.append((nb_target.center_x, nb_target.center_y))

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
        elif gv._zone.zone_id == ZoneID.STAR_MAZE:
            # Checked BEFORE the generic hasattr(_aliens) branch below
            # because the Star Maze now also has ``_aliens`` (its Zone
            # 2-style Nebula population); without this order the
            # Zone-2-style branch would eat every hit and the maze
            # spawner / maze aliens would never take damage.
            from zones.zone2_world import drop_zone2_alien_loot
            from constants import (
                MAZE_ALIEN_IRON_DROP, MAZE_ALIEN_XP,
                MAZE_SPAWNER_IRON_DROP, MAZE_SPAWNER_XP,
            )
            hit = False
            # Maze aliens first.
            for a in list(gv._zone._maze_aliens):
                if math.hypot(m.center_x - a.center_x,
                              m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        _apply_kill_rewards(
                            gv, a.center_x, a.center_y,
                            MAZE_ALIEN_IRON_DROP, bonus_iron_enemy,
                            BLUEPRINT_DROP_CHANCE_ALIEN,
                            xp=MAZE_ALIEN_XP,
                        )
                        gv._zone._on_maze_alien_killed(a)
                        a.remove_from_sprite_lists()
                    m.remove_from_sprite_lists()
                    hit = True
                    break
            # Spawners.
            if not hit:
                for sp in gv._zone.spawners:
                    if sp.killed:
                        continue
                    if math.hypot(m.center_x - sp.center_x,
                                  m.center_y - sp.center_y) <= (
                            sp.radius + 10):
                        gv.hit_sparks.append(HitSpark(
                            m.center_x, m.center_y))
                        gv._spawn_explosion(m.center_x, m.center_y)
                        sp.take_damage(int(m.damage))
                        if sp.killed:
                            _apply_kill_rewards(
                                gv, sp.center_x, sp.center_y,
                                MAZE_SPAWNER_IRON_DROP, bonus_iron_enemy,
                                0.0, xp=MAZE_SPAWNER_XP,
                            )
                        m.remove_from_sprite_lists()
                        hit = True
                        break
            # Finally the Nebula-population aliens (same-bucket as
            # Zone 2 so reuse the zone-2 loot drop).
            if not hit:
                for a in list(gv._zone._aliens):
                    if math.hypot(m.center_x - a.center_x,
                                  m.center_y - a.center_y) < 25:
                        gv.hit_sparks.append(HitSpark(
                            m.center_x, m.center_y))
                        gv._spawn_explosion(m.center_x, m.center_y)
                        a.take_damage(int(m.damage))
                        if a.hp <= 0:
                            drop_zone2_alien_loot(gv._zone, gv, a)
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

        # Missile vs bosses.  Homing already steers missiles toward
        # live bosses via the ``targets`` list above; this block is
        # what actually deals damage on arrival.  Uses the boss's
        # live ``.radius`` (derived from the rendered sprite size)
        # so the hitbox always matches what the player sees.
        if not m.sprite_lists:
            continue  # already consumed by an alien hit above
        for _boss in (gv._boss, getattr(gv, "_nebula_boss", None)):
            if _boss is None or _boss.hp <= 0:
                continue
            _boss_hit = _boss.radius + 10.0
            if math.hypot(m.center_x - _boss.center_x,
                          m.center_y - _boss.center_y) < _boss_hit:
                gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                gv._spawn_explosion(m.center_x, m.center_y)
                _boss.take_damage(int(m.damage))
                m.remove_from_sprite_lists()
                if _boss.hp <= 0:
                    from collisions import _boss_death, _nebula_boss_death
                    if _boss is gv._boss:
                        _boss_death(gv)
                    else:
                        _nebula_boss_death(gv)
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
