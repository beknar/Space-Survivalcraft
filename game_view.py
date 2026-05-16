"""GameView -- core gameplay view for Space Survivalcraft."""
from __future__ import annotations

import gc
import math
import random
from typing import Optional

import arcade

from constants import (
    STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT, SHIP_RADIUS, ASTEROID_IRON_YIELD,
    SHAKE_DURATION,
    FOG_REVEAL_RADIUS, FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H,
)
from settings import audio
from sprites.projectile import Weapon
from sprites.wormhole import Wormhole
from video_player import VideoPlayer

# Extracted modules
import combat_helpers as _ch
import building_manager as _bm
import draw_logic as _dl
import update_logic as _ul
import input_handlers as _ih
import game_view_init as _gvi

# Re-export init-time helpers from the extracted module so existing
# ``from game_view import _make_blueprint_red_dot_variant`` test
# imports keep working after the split (PR series alongside #126).
from game_view_init import (
    _make_blueprint_red_dot_variant,
    _BP_DOT_VARIANT_CACHE,
)


class GameView(arcade.View):

    def __init__(
        self,
        faction: Optional[str] = None,
        ship_type: Optional[str] = None,
        skip_music: bool = False,
        ship_level: int = 1,
        character_name: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._skip_music = skip_music
        self._faction = faction
        self._ship_type = ship_type
        self._ship_level: int = ship_level
        # Set the global character_name BEFORE any helper that reads
        # it (weapons_and_audio calls _apply_character_weapon_bonuses
        # which looks up the bonus from audio.character_name).  When
        # the constructor is called from load_game(), passing the
        # save's character_name here means the very first weapon
        # bonus calculation uses the loaded character — not whatever
        # character was previously global.  Catches save-load bleed
        # where loading save B left audio.character_name pointing at
        # save A's character.
        if character_name is not None:
            from settings import audio as _audio
            _audio.character_name = character_name

        # Sectioned init — each helper sets up one cohesive group of
        # state, and the call order below is load-bearing (e.g. iron
        # texture before inventories, inventories before hud).  The
        # per-helper contracts live in ``game_view_init.py``.
        _gvi.init_player_and_camera(self, faction)
        _gvi.init_abilities_and_effects(self)
        _gvi.init_text_overlays(self)
        _gvi.init_input_devices(self)
        _gvi.init_weapons_and_audio(self)
        _gvi.init_world_entities(self)
        _gvi.init_boss_and_wormholes(self)
        _gvi.init_consumable_textures(self)
        _gvi.init_inventories(self)
        _gvi.init_buildings_and_overlays(self)
        _gvi.init_world_state(self)
        _gvi.init_hud(self)
        _gvi.init_video_and_menus(self)
        _gvi.init_zones(self)

        # Optional bot API — only starts when COO_BOT_API is set.
        try:
            import bot_api
            bot_api.maybe_start_from_env(self)
        except Exception as e:
            print(f"[bot_api] failed to start: {e}")

    # ── Zone transitions ──────────────────────────────────────────────────
    def _transition_zone(self, target_zone_id, entry_side: str = "bottom") -> None:
        """Tear down current zone, set up target zone, reposition player."""
        from zones import ZoneID, create_zone
        # Store player position for return
        if hasattr(self._zone, '_stash'):
            self._zone._stash["_player_pos"] = (
                self.player.center_x, self.player.center_y)
        self._zone.teardown(self)
        # Reuse persistent zone instances (preserves state across visits)
        if target_zone_id == ZoneID.MAIN:
            self._zone = self._main_zone
        elif target_zone_id == ZoneID.ZONE2:
            if self._zone2 is None:
                self._zone2 = create_zone(ZoneID.ZONE2)
            self._zone = self._zone2
        elif target_zone_id == ZoneID.STAR_MAZE:
            if self._star_maze is None:
                self._star_maze = create_zone(ZoneID.STAR_MAZE)
            self._zone = self._star_maze
        else:
            self._zone = create_zone(target_zone_id)
        self._zone.setup(self)
        # Update player world bounds
        self.player.world_width = self._zone.world_width
        self.player.world_height = self._zone.world_height
        # Reposition player
        px, py = self._zone.get_player_spawn(entry_side)
        self.player.center_x = px
        self.player.center_y = py
        self.player.vel_x = 0.0
        self.player.vel_y = 0.0
        # Drag the active drone through the wormhole with the player
        # — it doesn't make sense to leave the drone stranded in the
        # zone the player just left.  Drop it next to the spawn so
        # the slot picker can settle it on the next tick; reset the
        # un-stick nudge anchor so the tracker doesn't fire on the
        # teleport jump.  Also clear the planner's cached path since
        # the maze geometry just changed (the planner rebuilds via
        # ``attach_maze_planner`` on the next ``update_drone`` call).
        active_drone = getattr(self, "_active_drone", None)
        if active_drone is not None:
            active_drone.center_x = px + 30
            active_drone.center_y = py + 30
            active_drone._nudge_anchor_x = active_drone.center_x
            active_drone._nudge_anchor_y = active_drone.center_y
            active_drone._nudge_timer = 0.0
            # Force the maze planner to re-attach with the new
            # zone's geometry on the next tick.
            active_drone._follow_planner_geom_id = 0
        # Zone entry announcement
        _ZONE_NAMES = {
            ZoneID.MAIN: "Entering the Double Star Zone",
            ZoneID.ZONE2: "Entering the Nebula Zone",
            ZoneID.WARP_METEOR: "Meteor Warp Zone",
            ZoneID.WARP_LIGHTNING: "Lightning Warp Zone",
            ZoneID.WARP_GAS: "Gas Cloud Warp Zone",
            ZoneID.WARP_ENEMY: "Enemy Spawner Warp Zone",
        }
        zone_name = _ZONE_NAMES.get(target_zone_id, "")
        if zone_name:
            self._boss_announce_timer = 3.0
            self._t_boss_announce.text = zone_name
            self._t_boss_subtitle.text = ""

    # ── Music delegates (game_music module) ────────────────────────────────
    def _play_next_track(self) -> None:
        from game_music import play_next_track; play_next_track(self)

    def _stop_music(self) -> None:
        from game_music import stop_music; stop_music(self)

    def _play_video(self, filepath: str) -> None:
        from game_music import play_video; play_video(self, filepath)

    def _start_character_video(self) -> None:
        from game_music import start_character_video; start_character_video(self)

    def _select_character(self, name: str) -> None:
        from game_music import select_character; select_character(self, name)

    def _stop_video(self) -> None:
        from game_music import stop_video; stop_video(self)

    def _stop_song(self) -> None:
        from game_music import stop_song; stop_song(self)

    def _other_song(self) -> None:
        from game_music import other_song; other_song(self)

    # ── Character progression ──────────────────────────────────────────────
    def _apply_character_weapon_bonuses(self) -> None:
        """Recompute Basic Laser stats as ``baseline + character_bonus``.

        Idempotent: each weapon's ``_base_*`` attrs (set in
        ``Weapon.__init__``) are the ground truth, so calling this
        twice in a row leaves the same final values.  Without this,
        loading save A then save B stacked both characters' bonuses
        on the same weapon (each call did ``wpn.damage += dmg``).
        """
        from character_data import (laser_damage_bonus, laser_cooldown_bonus,
                                    laser_speed_bonus, laser_range_bonus)
        name = audio.character_name
        lvl = self._char_level
        dmg = laser_damage_bonus(name, lvl)
        cd = laser_cooldown_bonus(name, lvl)
        spd = laser_speed_bonus(name, lvl)
        rng = laser_range_bonus(name, lvl)
        for wpn in self._weapons:
            if wpn.name == "Basic Laser":
                wpn.damage = wpn._base_damage + dmg
                wpn.cooldown = max(0.05, wpn._base_cooldown - cd)
                wpn._proj_speed = wpn._base_proj_speed + spd
                wpn._max_range = wpn._base_max_range + rng

    @property
    def _active_weapon(self) -> Weapon:
        gun_count = self.player.guns
        base_idx = (self._weapon_idx // gun_count) * gun_count
        return self._weapons[base_idx]

    def _cycle_weapon(self) -> None:
        gun_count = self.player.guns
        self._weapon_idx = (self._weapon_idx + gun_count) % len(self._weapons)

    # ── Fog of war ─────────────────────────────────────────────────────────
    def _update_fog(self) -> None:
        px, py = self.player.center_x, self.player.center_y
        cx = int(px / FOG_CELL_SIZE)
        cy = int(py / FOG_CELL_SIZE)
        r = int(FOG_REVEAL_RADIUS / FOG_CELL_SIZE) + 1
        for gy in range(max(0, cy - r), min(FOG_GRID_H, cy + r + 1)):
            for gx in range(max(0, cx - r), min(FOG_GRID_W, cx + r + 1)):
                if not self._fog_grid[gy][gx]:
                    cell_cx = (gx + 0.5) * FOG_CELL_SIZE
                    cell_cy = (gy + 0.5) * FOG_CELL_SIZE
                    if math.hypot(px - cell_cx, py - cell_cy) <= FOG_REVEAL_RADIUS:
                        self._fog_grid[gy][gx] = True
                        self._fog_revealed += 1

    def is_revealed(self, wx: float, wy: float) -> bool:
        gx = int(wx / FOG_CELL_SIZE)
        gy = int(wy / FOG_CELL_SIZE)
        if 0 <= gx < FOG_GRID_W and 0 <= gy < FOG_GRID_H:
            return self._fog_grid[gy][gx]
        return False

    # ── Combat helpers (delegates to combat_helpers module) ─────────────────
    def _trigger_shake(self) -> None:
        _ch.trigger_shake(self)

    def _apply_damage_to_player(self, amount: int) -> None:
        _ch.apply_damage_to_player(self, amount)

    def _flash_game_msg(self, msg: str, duration: float = 1.5) -> None:
        _ch.flash_game_msg(self, msg, duration)

    def _use_repair_pack(self, slot: int) -> None:
        _ch.use_repair_pack(self, slot)

    def _use_shield_recharge(self, slot: int) -> None:
        _ch.use_shield_recharge(self, slot)

    def _fire_missile(self, slot: int) -> None:
        _ch.fire_missile(self, slot)

    def _spawn_asteroid_explosion(self, x: float, y: float) -> None:
        _ch.spawn_asteroid_explosion(self, x, y)

    def _spawn_explosion(self, x: float, y: float) -> None:
        _ch.spawn_explosion(self, x, y)

    def _spawn_iron_pickup(self, x: float, y: float,
                           amount: int = ASTEROID_IRON_YIELD,
                           lifetime: Optional[float] = None) -> None:
        _ch.spawn_iron_pickup(self, x, y, amount, lifetime)

    def _spawn_blueprint_pickup(self, x: float, y: float) -> None:
        _ch.spawn_blueprint_pickup(self, x, y)

    def _add_xp(self, amount: int) -> None:
        _ch.add_xp(self, amount)

    def _try_respawn_asteroids(self) -> None:
        _ch.try_respawn_asteroids(self)

    def _try_respawn_aliens(self) -> None:
        _ch.try_respawn_aliens(self)

    def _check_boss_spawn(self) -> None:
        _ch.check_boss_spawn(self)

    def _spawn_wormholes(self) -> None:
        """Spawn 4 wormholes in the corners of the map."""
        margin = 200.0
        corners = [
            (margin, margin),
            (WORLD_WIDTH - margin, margin),
            (margin, WORLD_HEIGHT - margin),
            (WORLD_WIDTH - margin, WORLD_HEIGHT - margin),
        ]
        from zones import ZoneID
        targets = [ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                   ZoneID.WARP_GAS, ZoneID.WARP_ENEMY]
        for (cx, cy), target in zip(corners, targets):
            wh = Wormhole(cx, cy)
            wh.zone_target = target
            self._wormholes.append(wh)
            self._wormhole_list.append(wh)

    # ── Building helpers (delegates to building_manager module) ─────────────
    def _spawn_trade_station(self) -> None:
        _bm.spawn_trade_station(self)

    def _building_counts(self) -> dict[str, int]:
        return _bm.building_counts(self)

    def _has_home_station(self) -> bool:
        return _bm.has_home_station(self)

    def _find_nearest_snap_port(self, wx: float, wy: float,
                                max_dist: float = 0.0):
        return _bm.find_nearest_snap_port(self, wx, wy, max_dist)

    def _enter_placement_mode(self, building_type: str) -> None:
        _bm.enter_placement_mode(self, building_type)

    def _cancel_placement(self) -> None:
        _bm.cancel_placement(self)

    def _enter_destroy_mode(self) -> None:
        _bm.enter_destroy_mode(self)

    def _exit_destroy_mode(self) -> None:
        _bm.exit_destroy_mode(self)

    def _disconnect_ports(self, building) -> None:
        _bm.disconnect_ports(self, building)

    def _destroy_building_at(self, wx: float, wy: float) -> None:
        _bm.destroy_building_at(self, wx, wy)

    def _place_building(self, wx: float, wy: float) -> None:
        _bm.place_building(self, wx, wy)

    # ── Cleanup ────────────────────────────────────────────────────────────
    def _cleanup(self) -> None:
        """Release resources before this view is replaced (e.g. on load game)."""
        # Stop audio
        if self._thruster_player is not None:
            arcade.stop_sound(self._thruster_player)
            self._thruster_player = None
        self._stop_music()
        self._stop_video()
        # Stop character video
        if self._char_video_player.active:
            self._char_video_player.stop()
        # Clear sprite lists to drop texture references
        self.asteroid_list.clear()
        self.alien_list.clear()
        self.building_list.clear()
        self.explosion_list.clear()
        self.iron_pickup_list.clear()
        self.blueprint_pickup_list.clear()
        self.projectile_list.clear()
        self.alien_projectile_list.clear()
        self.turret_projectile_list.clear()
        self._boss_list.clear()
        self._boss_projectile_list.clear()
        self._boss = None
        self._wormholes.clear()
        self._wormhole_list.clear()
        self._missile_list.clear()
        self._force_walls.clear()
        self._death_blossom_active = False
        # Re-enable GC so old view can be collected
        gc.enable()

    # ── Save / Load / Menu delegates ──────────────────────────────────────
    def _save_to_dict(self, name: str = "") -> dict:
        from game_save import save_to_dict; return save_to_dict(self, name)

    def _save_game(self, slot: int, name: str) -> None:
        from game_save import save_game; save_game(self, slot, name)

    @staticmethod
    def _restore_state(view: "GameView", data: dict) -> None:
        from game_save import restore_state; restore_state(view, data)

    def _load_game(self, slot: int) -> None:
        from game_save import load_game; load_game(self, slot)

    def _change_resolution(self, width: int, height: int, display_mode: str) -> None:
        from game_music import change_resolution; change_resolution(self, width, height, display_mode)

    def _return_to_menu(self) -> None:
        from game_music import return_to_menu; return_to_menu(self)

    # ── Drawing ──────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        VideoPlayer._frame_id += 1
        self.clear()
        sw = self.window.width
        sh = self.window.height
        hw = sw / 2
        hh = sh / 2
        zw = self._zone.world_width
        zh = self._zone.world_height
        cx = max(hw - STATUS_WIDTH, min(zw - hw, self.player.center_x))
        cy = max(hh, min(zh - hh, self.player.center_y))
        shake_x = shake_y = 0.0
        if self._shake_timer > 0.0:
            frac = self._shake_timer / SHAKE_DURATION
            amp = self._shake_amp * frac
            shake_x = random.uniform(-amp, amp)
            shake_y = random.uniform(-amp, amp)
        self.world_cam.position = (cx + shake_x, cy + shake_y)
        with self.world_cam.activate():
            _dl.draw_world(self, cx, cy, hw, hh)
        with self.ui_cam.activate():
            _dl.draw_ui(self)

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        # Drain bot-API main-thread work (e.g. building placements
        # queued from HTTP handlers) BEFORE per-frame logic so the
        # game state is up-to-date for this tick.  No-op when the
        # bot API isn't running or the queue is empty.
        try:
            import bot_api
            bot_api.pump_main_thread_queue(self)
        except Exception:
            pass
        _ul.update_preamble(self, delta_time)
        if self._player_dead:
            _ul.update_death_state(self, delta_time)
            return
        _ul.update_timers(self, delta_time)
        _ul.update_repair_and_shields(self, delta_time)
        _ul.update_crafting(self, delta_time)
        fire = _ul.update_movement(self, delta_time)
        _ul.update_contrail(self, delta_time)
        _ul.update_weapons(self, delta_time, fire or self._death_blossom_active)
        # Always advance player projectiles (shared across all zones)
        for proj in list(self.projectile_list):
            proj.update_projectile(delta_time)
        # Always collect pickups (shared across all zones)
        sx, sy = self.player.center_x, self.player.center_y
        for pickup in list(self.iron_pickup_list):
            collected = pickup.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item(getattr(pickup, 'item_type', 'iron'), pickup.amount)
        for bp in list(self.blueprint_pickup_list):
            collected = bp.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item(bp.item_type, 1)
        # Zone-specific updates
        from zones import ZoneID
        if self._zone.zone_id == ZoneID.MAIN:
            self._update_fog()
            _ul.update_entities(self, delta_time)
            _ul.update_buildings(self, delta_time)
            _ul.update_respawns(self, delta_time)
            _ul.update_boss(self, delta_time)
            _ul.update_wormholes(self, delta_time)
        else:
            self._zone.update(self, delta_time)
        # Background simulation of inactive zones (if enabled)
        if audio.simulate_all_zones:
            if self._zone.zone_id != ZoneID.MAIN and self._main_zone is not None:
                self._main_zone.background_update(self, delta_time)
            if self._zone.zone_id != ZoneID.ZONE2 and self._zone2 is not None:
                self._zone2.background_update(self, delta_time)
        _ul.update_ability_meter(self, delta_time)
        _ul.update_force_walls(self, delta_time)
        _ul.update_null_fields(self, delta_time)
        _ul.update_slipspaces(self, delta_time)
        _ul.update_nebula_boss(self, delta_time)
        # Decay the gas-slow timer set by nebula boss cloud/cone hits.
        if getattr(self, "_nebula_slow_timer", 0.0) > 0.0:
            self._nebula_slow_timer = max(
                0.0, self._nebula_slow_timer - delta_time)
        _ul.update_station_shield(self, delta_time)
        _ul.update_refugee_npc(self, delta_time)
        _ul.update_missiles(self, delta_time)
        _ul.update_drone(self, delta_time)
        _ul.update_death_blossom(self, delta_time)
        _ul.update_effects(self, delta_time)

    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        _ih.handle_key_press(self, key, modifiers)

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        _ih.handle_mouse_press(self, x, y, button, modifiers)

    def on_mouse_drag(
        self, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int
    ) -> None:
        _ih.handle_mouse_drag(self, x, y, dx, dy, buttons, modifiers)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        _ih.handle_mouse_release(self, x, y, button, modifiers)

    def on_mouse_scroll(
        self, x: int, y: int, scroll_x: int, scroll_y: int
    ) -> None:
        _ih.handle_mouse_scroll(self, x, y, scroll_x, scroll_y)

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        _ih.handle_mouse_motion(self, x, y, dx, dy)

    def on_text(self, text: str) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_text(text)
