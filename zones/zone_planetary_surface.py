"""Planet Surface Scene — top-down, on-foot (docs/planets.md section 6).

Phase 2 ("on-foot surface slice").  Reached from the top edge of the
Planetary Landing Scene.  The player walks on foot (direct WASD), carries
an Armor stat, wields a ranged rifle + portable mining beam, and harvests
resource nodes (rock -> iron, copper vein -> copper, silicon vein ->
silicon).  Surface enemies, melee weapons, base-building, and L11-30
progression are later phases.

Implementation note — the on-foot character REUSES ``gv.player`` rather
than introducing a parallel sprite, so the camera / input / draw / weapon
pipelines all work unchanged.  ``setup`` stashes the ship's combat state
and flips the player into on-foot mode (texture, stats, arsenal,
``gv._on_foot = True``); ``teardown`` restores it.  Behaviour gated on
``gv._on_foot`` lives in ``update_logic.update_movement`` and
``combat_helpers.apply_damage_to_player`` (the armor stat).
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    PLANET_SURFACE_WIDTH, PLANET_SURFACE_HEIGHT,
    ON_FOOT_BASE_HP, ON_FOOT_BASE_ARMOR, ON_FOOT_SCALE, ON_FOOT_SPEED,
    ON_FOOT_RADIUS,
    ROCK_NODE_COUNT, COPPER_VEIN_COUNT, SILICON_VEIN_COUNT,
    FOG_CELL_SIZE,
)
from zones import ZoneID, ZoneState
from sprites.resource_node import ResourceNode

if TYPE_CHECKING:
    from game_view import GameView

_EXIT_THRESHOLD = 60.0           # px from the bottom edge to lift off
_GROUND_COLOR = (104, 88, 64, 255)


class PlanetarySurfaceZone(ZoneState):
    zone_id = ZoneID.PLANETARY_SURFACE
    world_width = PLANET_SURFACE_WIDTH
    world_height = PLANET_SURFACE_HEIGHT

    def __init__(self) -> None:
        self._nodes: arcade.SpriteList = arcade.SpriteList()
        self._origin_zone: ZoneID = ZoneID.STAR_MAZE
        self.planet_type: str = "earth"
        self._frames: dict | None = None
        # Ship state stashed on entry, restored on exit.
        self._ship_stash: dict | None = None
        # All-revealed fog grid sized for the surface (no fog this phase).
        fw = PLANET_SURFACE_WIDTH // FOG_CELL_SIZE
        fh = PLANET_SURFACE_HEIGHT // FOG_CELL_SIZE
        self._fog_grid = [[True] * fw for _ in range(fh)]
        self._fog_revealed = fw * fh

    # ── Enter / leave: ship <-> on-foot mode swap ───────────────────

    def setup(self, gv: GameView) -> None:
        from world_setup import load_on_foot_weapons, load_on_foot_frames

        self._origin_zone = getattr(
            gv, "_planet_origin_zone", ZoneID.STAR_MAZE) or ZoneID.STAR_MAZE
        self.planet_type = getattr(gv, "_pending_planet_type", "earth") or "earth"

        p = gv.player
        # Stash everything we mutate so the ship is byte-for-byte restored.
        self._ship_stash = {
            "texture": p.texture, "scale": p.scale,
            "hp": p.hp, "max_hp": p.max_hp,
            "shields": p.shields, "max_shields": p.max_shields,
            "armor": p.armor, "guns": p.guns, "heading": p.heading,
            "angle": p.angle, "vel_x": p.vel_x, "vel_y": p.vel_y,
            "weapons": gv._weapons, "weapon_idx": gv._weapon_idx,
        }

        # Flip into on-foot mode.
        gv._on_foot = True
        self._frames = load_on_foot_frames()
        p._on_foot_frames = self._frames
        p._facing = "down"
        p._walk_idx = 0
        p._walk_timer = 0.0
        p.texture = self._frames["down"][0]
        p.scale = ON_FOOT_SCALE
        p.angle = 0.0
        p.vel_x = p.vel_y = 0.0
        p.hp = p.max_hp = ON_FOOT_BASE_HP
        p.shields = p.max_shields = 0           # surface uses armor, not shields
        p.armor = ON_FOOT_BASE_ARMOR
        # Single "gun" so the 2-weapon on-foot list cycles 1-at-a-time.
        p.guns = 1
        gv._weapons = load_on_foot_weapons()
        gv._weapon_idx = 0

        # Fog hand-off (fully revealed — no fog on the surface this phase).
        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

        self._populate_nodes()

        # Swap the HUD character panel to the surface animation (Debra.mp4).
        from game_music import start_surface_character_video
        start_surface_character_video(gv)

        from zones import welcome_message_for
        msg = welcome_message_for(self.zone_id)
        if msg is not None:
            gv._flash_game_msg(msg, 1.8)

    def teardown(self, gv: GameView) -> None:
        # Restore the space character video before anything else.
        from game_music import restore_space_character_video
        restore_space_character_video(gv)
        s = self._ship_stash
        if s is not None:
            p = gv.player
            p.texture = s["texture"]
            p.scale = s["scale"]
            p.hp, p.max_hp = s["hp"], s["max_hp"]
            p.shields, p.max_shields = s["shields"], s["max_shields"]
            p.armor = s["armor"]
            p.guns = s["guns"]
            p.heading, p.angle = s["heading"], s["angle"]
            p.vel_x, p.vel_y = s["vel_x"], s["vel_y"]
            gv._weapons = s["weapons"]
            gv._weapon_idx = s["weapon_idx"]
            p._on_foot_frames = None       # stop the ship from animating
            self._ship_stash = None
        gv._on_foot = False
        self._nodes.clear()

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        # Spawn mid-field so the player doesn't immediately cross the
        # bottom lift-off edge.
        return self.world_width / 2, self.world_height / 2

    def _populate_nodes(self) -> None:
        """Scatter resource nodes (DESIGN-GAP: docs gives no surface
        layout — random placement with a small edge margin)."""
        self._nodes = arcade.SpriteList()
        plan = (["rock"] * ROCK_NODE_COUNT
                + ["copper"] * COPPER_VEIN_COUNT
                + ["silicon"] * SILICON_VEIN_COUNT)
        for node_type in plan:
            x = random.uniform(250.0, self.world_width - 250.0)
            y = random.uniform(250.0, self.world_height - 250.0)
            self._nodes.append(ResourceNode(node_type, x, y))

    # ── Per-frame update ────────────────────────────────────────────

    def update(self, gv: GameView, dt: float) -> None:
        from sprites.explosion import HitSpark

        for node in self._nodes:
            node.update_node(dt)

        px, py = gv.player.center_x, gv.player.center_y

        # Mining-beam projectiles vs nodes (rifle shots pass through —
        # they're for future surface enemies).
        for proj in list(gv.projectile_list):
            if not getattr(proj, "mines_rock", False):
                continue
            for node in list(self._nodes):
                if math.hypot(proj.center_x - node.center_x,
                              proj.center_y - node.center_y) < node.radius:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    node.take_damage(int(proj.damage))
                    if node.hp <= 0:
                        gv.inventory.add_item(node.yield_item, node.yield_amount)
                        gv._spawn_explosion(node.center_x, node.center_y)
                        gv._flash_game_msg(
                            f"+{node.yield_amount} {node.yield_item}", 0.8)
                        node.remove_from_sprite_lists()
                    break

        # Soft physical block so the character can't walk through nodes.
        for node in self._nodes:
            dx = px - node.center_x
            dy = py - node.center_y
            reach = node.radius + ON_FOOT_RADIUS
            d2 = dx * dx + dy * dy
            if 0.0 < d2 < reach * reach:
                d = math.sqrt(d2)
                nx, ny = dx / d, dy / d
                gv.player.center_x = node.center_x + nx * reach
                gv.player.center_y = node.center_y + ny * reach
                px, py = gv.player.center_x, gv.player.center_y

        # Bottom edge = lift off, back to the originating zone.
        if py < _EXIT_THRESHOLD:
            gv._flash_game_msg("Lifting off…", 1.5)
            gv._transition_zone(self._origin_zone, entry_side="wormhole_return")

    # ── Drawing ─────────────────────────────────────────────────────

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self.world_width, self.world_height),
            _GROUND_COLOR)
        self._nodes.draw()

    def get_minimap_objects(self):
        return self._nodes, arcade.SpriteList()
