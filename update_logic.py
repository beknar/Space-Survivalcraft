"""Game update logic extracted from GameView.on_update.

Section index (search for ``═══`` headers):

* GC + sound cleanup           — _tracked_play_sound, _cleanup_finished_sounds
* update_preamble              — per-frame pre-update housekeeping
* Distance-attenuated SFX      — play_sfx_at, _play_throttled_alien_sfx,
                                  play_alien_laser_sound,
                                  play_missile_launch_sound, emit_alien_shots
* Death + timers               — update_death_state, update_timers
* Repair / shield / craft      — update_repair_and_shields, update_crafting
* Player movement / weapons    — update_movement, update_contrail, update_weapons
* Entities / buildings         — update_entities, _update_parked_ships,
                                  update_buildings, update_respawns
* Boss helpers                 — update_boss, update_nebula_boss
* Wormholes / abilities        — update_wormholes, update_ability_meter
* Null fields / slipspaces     — active_null_fields, update_null_fields,
                                  player_is_cloaked,
                                  disable_null_field_around_player,
                                  update_slipspaces
* Force walls                  — update_force_walls
* Drone tick                   — update_drone
* Misc                         — update_missiles, update_death_blossom,
                                  update_effects, update_station_shield,
                                  update_refugee_npc

The file is large (~1500 lines) but every section is a self-contained
function callable directly from GameView.  A future split would carry
import-churn cost across ~15 call sites that read these helpers by
name; the section markers below let editors jump straight to the
function being tuned.
"""
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
    handle_parked_ship_damage,
)

if TYPE_CHECKING:
    from game_view import GameView


# ── Sound player cleanup (impl in update_audio) ─────────────────────────
# Audio tracking + cleanup helpers (``_tracked_play_sound``,
# ``_cleanup_finished_sounds``, the monkey-patch of ``arcade.play_sound``,
# and the ``_sound_players`` / ``_SOUND_*`` globals) live in
# ``update_audio``.  Re-exported here so existing call sites
# (``from update_logic import _tracked_play_sound`` and tests that
# read ``update_logic._sound_players``) keep working.
from update_audio import (  # noqa: E402
    _SOUND_MAX_AGE,
    _sound_players,
    _real_play_sound,
    _SOUND_HARD_CAP,
    _MAX_DELETES_PER_TICK,
    _tracked_play_sound,
    _cleanup_finished_sounds,
)
import time as _time  # used by other helpers below

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


# ═══ Update preamble ═════════════════════════════════════════════════════


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


# ═══ Distance-attenuated SFX (impl in update_logic_sfx) ═════════════════
#
# Re-exported here so existing call sites + tests that read
# ``update_logic.play_sfx_at`` etc. keep working.
from update_logic_sfx import (  # noqa: E402
    _ALIEN_LASER_SND_INTERVAL,
    play_sfx_at,
    _nearest_alien_to_player,
    _play_throttled_alien_sfx,
    play_alien_laser_sound,
    play_missile_launch_sound,
    emit_alien_shots,
)


# ═══ Death state + per-frame timers ═════════════════════════════════════


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
    if getattr(gv, "_alien_laser_snd_cd", 0.0) > 0.0:
        gv._alien_laser_snd_cd = max(0.0, gv._alien_laser_snd_cd - dt)
    # Hold-to-sell loop: consume timer and drain inventory if held.
    if gv._trade_menu.open:
        action = gv._trade_menu.on_update(
            dt, inventory=gv.inventory, station_inv=gv._station_inv,
        )
        if action is not None:
            from input_handlers import apply_trade_action
            apply_trade_action(gv, action)


# ═══ Repair / shields / craft ═══════════════════════════════════════════


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
                # Per-crafter target so two parallel crafters can
                # produce different items.  Falls back to the menu's
                # shared ``_craft_target`` for old saves whose
                # crafters didn't carry the field yet.
                target = getattr(b, "craft_target", "") \
                    or gv._craft_menu._craft_target
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
                # Reset this crafter's target so the next craft starts
                # fresh.  The menu's _craft_target is intentionally
                # left alone — it tracks the LAST opened crafter's
                # current selection, not a per-crafter state.
                if hasattr(b, "craft_target"):
                    b.craft_target = ""

    if gv._craft_menu.open and gv._active_crafter is not None:
        gv._craft_menu.update(
            gv._active_crafter.craft_progress,
            gv._active_crafter.crafting,
        )


# ═══ Player movement / contrail / weapons ════════════════════════════════


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

    # On-foot (planet surface) movement is direct WASD steering — no
    # rotation, thrust, drag-physics, shield sprite, or thruster sound.
    # WASD/arrows map straight to up/down/left/right (docs/planets.md).
    if getattr(gv, "_on_foot", False):
        up = arcade.key.UP in gv._keys or arcade.key.W in gv._keys
        down = arcade.key.DOWN in gv._keys or arcade.key.S in gv._keys
        left = arcade.key.LEFT in gv._keys or arcade.key.A in gv._keys
        right = arcade.key.RIGHT in gv._keys or arcade.key.D in gv._keys
        if gv._escape_menu.open:
            up = down = left = right = fire = False
        gv.player.apply_input_on_foot(dt, up, down, left, right)
        return fire

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


# ═══ Blade / pickaxe AOE (impl in update_blade) ═══════════════════════════
#
# The lightsabre + Energy Pickaxe share a lifecycle (lazy-spawn / despawn /
# per-tick AOE damage) that lives in ``update_blade``.  Re-exported here
# so existing ``from update_logic import update_melee_blade`` /
# ``_ensure_melee_blade`` etc. call sites keep working.
from update_blade import (  # noqa: E402
    _melee_blade_stats,
    _pickaxe_blade_stats,
    _BladeKind,
    _enemies_for_lightsabre,
    _asteroids_for_pickaxe,
    _reward_alien_kill,
    _reward_asteroid_kill,
    _pickaxe_sprite_kwargs,
    LIGHTSABRE_KIND,
    PICKAXE_KIND,
    _ensure_blade,
    _remove_blade,
    _update_blade_aoe,
    _ensure_melee_blade,
    _remove_melee_blade,
    _ensure_pickaxe_blade,
    _remove_pickaxe_blade,
    update_melee_blade,
    update_pickaxe_blade,
)


# ── Weapons tick (impl in update_logic_weapons) ───────────────────────────
# Re-exported so existing call sites (game_view + bot_combat_assist
# monkey-patch) keep working unchanged.
from update_logic_weapons import update_weapons  # noqa: E402,F401


# ═══ Zone-1 entity / building / boss / wormhole tick ════════════════════


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
        emit_alien_shots(gv, gv.alien_projectile_list, proj)

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
    # Star Maze (and any future zone) can expose extra hostile
    # SpriteLists that turrets / missile arrays should ALSO target
    # for selection.  We build a plain Python list (no SpriteList
    # allocation — arcade's SpriteList.clear()+append() cycle leaks
    # ~15 KB per call which tanks soak runs) and use it as the
    # targeting iterable.  Projectile collision is run separately
    # against each real SpriteList in handle_turret_projectile_hits
    # so the existing ``arcade.check_for_collision_with_list``
    # contract holds without the leak.
    extra_lists = getattr(
        gv._zone, "_turret_extra_target_lists", None) or ()
    if extra_lists:
        target_iter: list = list(gv.alien_list)
        for el in extra_lists:
            target_iter.extend(el)
    else:
        target_iter = gv.alien_list
    for b in list(gv.building_list):
        b.update_building(dt)
        if isinstance(b, Turret):
            b.update_turret(dt, target_iter,
                            gv.turret_projectile_list,
                            bosses=live_bosses)
        elif isinstance(b, MissileArray):
            b.update_missile_array(
                dt, target_iter, gv._missile_list,
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


# ═══ Boss + Nebula boss tick (impl in update_boss) ═══════════════════════
#
# Boss / Nebula-boss per-frame helpers live in ``update_boss``.
# Re-exported here so existing ``from update_logic import update_boss``
# / ``update_nebula_boss`` / ``_apply_nebula_slow`` call sites keep
# working.
from update_boss import (  # noqa: E402
    _boss_update_context,
    update_boss,
    update_nebula_boss,
    _apply_nebula_slow,
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


# ═══ Null fields / slipspaces / force walls (impl in update_logic_zone_effects) ═══
#
# Re-exported so the dozens of ``from update_logic import …`` call
# sites (draw_logic, collisions, combat_helpers, input_handlers,
# integration tests) keep working unchanged.
from update_logic_zone_effects import (  # noqa: E402
    active_null_fields,
    find_null_field_at,
    disable_null_field_around_player,
    player_is_cloaked,
    active_slipspaces,
    update_slipspaces,
    _check_slipspace_teleport,
    update_null_fields,
    update_force_walls,
)


# ── Drone / missile / death-blossom ticks (impl in update_logic_drone
#    + update_logic_missiles) ────────────────────────
# Re-exported so existing call sites (game_view, integration tests
# that import these by name from update_logic) keep working
# unchanged.
from update_logic_drone import update_drone  # noqa: E402,F401
from update_logic_missiles import (  # noqa: E402,F401
    update_missiles,
    update_death_blossom,
)


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
