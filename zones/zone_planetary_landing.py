"""Planetary Landing Scene — aerial descent toward a planet surface.

Phase 1 ("Reach + Descend") of the planet game mode (docs/planets.md
section 5).  A warp-zone-sized (3200x6400) scene the player drops into
after ramming a planet with the Planetary Landing Adapter installed.
Modeled closely on ``EnemySpawnerWarpZone`` — it owns its enemy +
projectile SpriteLists and does inline player<->enemy collision in
``_update_hazards``.

Differences from the warp zones:

* **Routing** — bottom edge returns to the originating zone (the Star
  Maze), recorded on entry; the top edge would load the on-foot surface
  scene, which is a later phase, so it is currently a stub.
* **Walls** — touching the left/right wall costs a fraction of shields
  and HP (docs section 5) instead of fully draining shields and ejecting.
* **Enemies** — a fixed population of the three airborne types rather
  than spawners producing waves.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_RADIUS, SHIP_COLLISION_COOLDOWN,
    PLANET_CONTACT_DAMAGE_FRAC, PLANET_SKY_BG_PNG,
)
from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, EXIT_THRESHOLD
from specs import LANDING_ENEMIES
from sprites.landing_enemy import LandingEnemy

if TYPE_CHECKING:
    from game_view import GameView

_WALL_DAMAGE_COOLDOWN = 0.5     # seconds between wall damage ticks
_ENEMY_TOUCH_DAMAGE = 5         # HP per enemy body collision


class PlanetaryLandingZone(WarpZoneBase):
    zone_id = ZoneID.PLANETARY_LANDING

    def __init__(self) -> None:
        super().__init__()
        self._enemies: arcade.SpriteList = arcade.SpriteList()
        self._enemy_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._sky_bg_tex: arcade.Texture | None = None
        self.planet_type: str = "earth"
        # Origin zone to return to on the bottom-edge exit.  Set in
        # setup() from the GameView; defaults to the Star Maze (the only
        # zone that hosts planets in Phase 1).
        self._origin_zone: ZoneID = ZoneID.STAR_MAZE
        self._wall_dmg_cd: float = 0.0

    def setup(self, gv: GameView) -> None:
        # Read where we came from + which planet, before super().setup()
        # runs _apply_zone_id_routing (which reads self._origin_zone).
        self._origin_zone = getattr(
            gv, "_planet_origin_zone", ZoneID.STAR_MAZE) or ZoneID.STAR_MAZE
        self.planet_type = getattr(gv, "_pending_planet_type", "earth") or "earth"
        super().setup(gv)

        self._sky_bg_tex = arcade.load_texture(PLANET_SKY_BG_PNG)
        self._enemies = arcade.SpriteList()
        self._enemy_projectiles = arcade.SpriteList()
        self._wall_dmg_cd = 0.0
        self._populate_enemies()

    def _populate_enemies(self) -> None:
        """Place the fixed enemy population at random points in the upper
        ~75% of the scene (DESIGN-GAP: docs gives counts but no layout)."""
        for spec in LANDING_ENEMIES:
            body_tex = arcade.load_texture(spec.body_png)
            laser_tex = arcade.load_texture(spec.laser_png)
            for _ in range(spec.count):
                x = random.uniform(200.0, self.world_width - 200.0)
                y = random.uniform(self.world_height * 0.25, self.world_height - 200.0)
                self._enemies.append(
                    LandingEnemy(spec, body_tex, laser_tex, x, y))

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._enemies.clear()
        self._enemy_projectiles.clear()

    def _apply_zone_id_routing(self) -> None:
        """Bottom edge returns to the origin zone; the top edge (surface
        entry) is handled as a stub in ``_check_exits``."""
        self._exit_bottom_zone = self._origin_zone
        self._exit_top_zone = self._origin_zone  # unused; top is stubbed

    def _check_exits(self, gv: GameView) -> None:
        """Bottom = return to origin.  Top = surface entry (stubbed until
        the on-foot surface phase lands)."""
        if gv.player.center_y < EXIT_THRESHOLD:
            self._return_to_source(gv)
        elif gv.player.center_y > self.world_height - EXIT_THRESHOLD:
            # DESIGN-GAP: surface scene not implemented yet.  Flash a
            # notice and nudge the player back in so the seam is ready
            # for the next phase without dangling code.
            gv._flash_game_msg("Planet surface — coming soon", 2.0)
            gv.player.center_y = self.world_height - EXIT_THRESHOLD - 40.0
            gv.player.vel_y = min(0.0, getattr(gv.player, "vel_y", 0.0))

    def _check_walls(self, gv: GameView) -> None:
        """Left/right walls cost a fraction of shields + HP per tick and
        bounce the player inward (docs section 5)."""
        px = gv.player.center_x
        wall = self._effective_wall
        hit_left = px < wall
        hit_right = px > self.world_width - wall
        if not (hit_left or hit_right):
            return
        if self._wall_dmg_cd <= 0.0:
            self._wall_dmg_cd = _WALL_DAMAGE_COOLDOWN
            gv.player.shields = int(
                gv.player.shields * (1.0 - PLANET_CONTACT_DAMAGE_FRAC))
            dmg = int(gv.player.max_hp * PLANET_CONTACT_DAMAGE_FRAC)
            gv._apply_damage_to_player(dmg)
            gv._trigger_shake()
            gv._flash_game_msg("Atmospheric turbulence!", 1.0)
        # Bounce inward regardless of cooldown so the player can't park
        # in the wall between ticks.
        if hit_left:
            gv.player.center_x = wall + 10.0
        else:
            gv.player.center_x = self.world_width - wall - 10.0

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        from sprites.explosion import HitSpark

        self._wall_dmg_cd = max(0.0, self._wall_dmg_cd - dt)
        px, py = gv.player.center_x, gv.player.center_y

        # Enemy AI + fire
        for enemy in self._enemies:
            for proj in enemy.update_enemy(dt, px, py):
                self._enemy_projectiles.append(proj)

        # Enemy projectiles -> player
        for proj in list(self._enemy_projectiles):
            proj.update_projectile(dt)
            if math.hypot(proj.center_x - px, proj.center_y - py) < SHIP_RADIUS + 8:
                proj.remove_from_sprite_lists()
                gv._apply_damage_to_player(int(proj.damage))
                gv._trigger_shake()

        # Player projectiles -> enemies (shields then HP; XP + boom on kill)
        for proj in list(gv.projectile_list):
            if proj.mines_rock:
                continue
            for enemy in list(self._enemies):
                if math.hypot(proj.center_x - enemy.center_x,
                              proj.center_y - enemy.center_y) < enemy.spec.radius:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    enemy.take_damage(int(proj.damage))
                    if enemy.hp <= 0:
                        gv._spawn_explosion(enemy.center_x, enemy.center_y)
                        gv._add_xp(enemy.spec.xp)
                        enemy.remove_from_sprite_lists()
                    break

        # Enemy body -> player collision
        for enemy in list(self._enemies):
            if (math.hypot(enemy.center_x - px, enemy.center_y - py)
                    < enemy.spec.radius + SHIP_RADIUS
                    and gv.player._collision_cd <= 0.0):
                gv._apply_damage_to_player(_ENEMY_TOUCH_DAMAGE)
                gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._trigger_shake()

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        # Sky backdrop first (behind the walls + enemies the base draws).
        if self._sky_bg_tex is not None:
            arcade.draw_texture_rect(
                self._sky_bg_tex,
                arcade.LBWH(0, 0, self.world_width, self.world_height))
        super().draw_world(gv, cx, cy, hw, hh)

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._enemies.draw()
        self._enemy_projectiles.draw()

    def get_minimap_objects(self):
        return arcade.SpriteList(), self._enemies
