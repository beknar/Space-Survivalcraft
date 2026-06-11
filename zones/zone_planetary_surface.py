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
    SURFACE_ENEMY_RESPAWN_S, SURFACE_ENEMY_RADIUS,
    ON_FOOT_SWORD_PNG, ON_FOOT_SWORD_RADIUS, ON_FOOT_SWORD_COOLDOWN,
    ON_FOOT_SWORD_SWING_TIME, ON_FOOT_SWORD_DEFLECT, ON_FOOT_SWORD_DAMAGE,
    ON_FOOT_SWORD_DMG_BY_CHAR,
    ON_FOOT_PICK_PNG, ON_FOOT_PICK_RADIUS, ON_FOOT_PICK_COOLDOWN,
    ON_FOOT_PICK_SWING_TIME, ON_FOOT_PICK_DAMAGE, ON_FOOT_PICK_DMG_BY_CHAR,
    ON_FOOT_MELEE_SWING_SCALE,
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
        # Surface enemies (Phase 3) + their projectiles + thrown axes.
        self._enemies: arcade.SpriteList = arcade.SpriteList()
        self._enemy_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._axes: arcade.SpriteList = arcade.SpriteList()
        self._enemy_assets: dict | None = None
        self._respawn_timer: float = 0.0
        # On-foot melee (Phase 4): electron sword + pick axe swing state.
        self._sword_cd: float = 0.0
        self._pick_cd: float = 0.0
        self._swing_timer: float = 0.0
        self._swing_kind: str = ""          # "sword" | "pick" | ""
        self._sword_tex = None
        self._pick_tex = None
        self._swing_sprite = None
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
        self._populate_enemies(gv)

        # Melee swing visuals (Phase 4).
        self._sword_tex = arcade.load_texture(ON_FOOT_SWORD_PNG)
        self._pick_tex = arcade.load_texture(ON_FOOT_PICK_PNG)
        self._swing_sprite = arcade.Sprite(
            path_or_texture=self._sword_tex, scale=ON_FOOT_MELEE_SWING_SCALE)
        self._sword_cd = self._pick_cd = self._swing_timer = 0.0
        self._swing_kind = ""

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
        self._enemies.clear()
        self._enemy_projectiles.clear()
        self._axes.clear()

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

    # ── Surface enemies (Phase 3) ───────────────────────────────────

    def _populate_enemies(self, gv: GameView) -> None:
        """Fill every tier's budget at zone entry."""
        from sprites.surface_enemy import load_surface_enemy_assets
        from specs import SURFACE_TIER_ROSTER, SURFACE_TIER_MAX
        self._enemy_assets = load_surface_enemy_assets()
        self._enemies = arcade.SpriteList()
        self._enemy_projectiles = arcade.SpriteList()
        self._axes = arcade.SpriteList()
        self._respawn_timer = 0.0
        px, py = gv.player.center_x, gv.player.center_y
        for tier in SURFACE_TIER_ROSTER:
            for _ in range(SURFACE_TIER_MAX[tier]):
                self._spawn_enemy(tier, px, py)

    def _spawn_enemy(self, tier: str, px: float, py: float) -> None:
        from sprites.surface_enemy import SurfaceEnemy
        from specs import SURFACE_TIER_ROSTER
        from constants import SURFACE_ENEMY_SPAWN_MIN_DIST
        spec = random.choice(SURFACE_TIER_ROSTER[tier])
        # Pick a point a safe distance from the player so enemies appear
        # at range and walk in.
        for _ in range(20):
            x = random.uniform(120.0, self.world_width - 120.0)
            y = random.uniform(120.0, self.world_height - 120.0)
            if math.hypot(x - px, y - py) >= SURFACE_ENEMY_SPAWN_MIN_DIST:
                break
        self._enemies.append(SurfaceEnemy(
            spec, self._enemy_assets[spec.key], x, y,
            self.world_width, self.world_height))

    def _respawn_enemies(self, dt: float, px: float, py: float) -> None:
        """Top each tier back up to its budget on a cadence."""
        from specs import SURFACE_TIER_MAX
        self._respawn_timer += dt
        if self._respawn_timer < SURFACE_ENEMY_RESPAWN_S:
            return
        self._respawn_timer = 0.0
        counts = {"A": 0, "B": 0, "C": 0}
        for e in self._enemies:
            counts[e.spec.tier] += 1
        for tier, cap in SURFACE_TIER_MAX.items():
            if counts[tier] < cap:
                self._spawn_enemy(tier, px, py)

    # ── On-foot melee + kill rewards (Phase 4) ──────────────────────

    def _damage_enemy(self, gv: GameView, e, amount: int) -> None:
        """Apply damage; on the killing blow, drop iron + award XP."""
        if e.state != "alive":
            return
        e.take_damage(amount)
        if e.state == "dying":
            self._award_kill(gv, e)

    def _award_kill(self, gv: GameView, e) -> None:
        # Reuse the shared reward path (explosion + iron pickup + XP).
        # bp_chance=0: blueprint drops arrive with the §8 item trees.
        from collisions_common import _apply_kill_rewards
        from character_data import bonus_iron_enemy
        _apply_kill_rewards(
            gv, e.center_x, e.center_y, e.spec.iron_drop,
            bonus_iron_enemy, 0.0, xp=e.spec.xp)

    def _melee_char_damage(self, kind: str) -> int:
        from settings import audio
        name = getattr(audio, "character_name", "") or ""
        if kind == "sword":
            return ON_FOOT_SWORD_DMG_BY_CHAR.get(name, ON_FOOT_SWORD_DAMAGE)
        return ON_FOOT_PICK_DMG_BY_CHAR.get(name, ON_FOOT_PICK_DAMAGE)

    def _update_melee(self, gv: GameView, dt: float, fire: bool,
                      active_name: str, px: float, py: float) -> None:
        """Electron Sword (AOE vs enemies) + Electron Pick Axe (AOE node
        mining) swings, cooldown-gated while fire is held."""
        from sprites.explosion import HitSpark
        self._sword_cd = max(0.0, self._sword_cd - dt)
        self._pick_cd = max(0.0, self._pick_cd - dt)
        self._swing_timer = max(0.0, self._swing_timer - dt)
        if not fire:
            return

        if active_name == "Electron Sword" and self._sword_cd <= 0.0:
            self._sword_cd = ON_FOOT_SWORD_COOLDOWN
            self._swing_timer = ON_FOOT_SWORD_SWING_TIME
            self._swing_kind = "sword"
            arcade.play_sound(gv._active_weapon._sound, volume=0.5)
            dmg = self._melee_char_damage("sword")
            reach = ON_FOOT_SWORD_RADIUS + SURFACE_ENEMY_RADIUS
            for e in list(self._enemies):
                if e.state == "alive" and math.hypot(
                        e.center_x - px, e.center_y - py) <= reach:
                    self._damage_enemy(gv, e, dmg)
        elif active_name == "Electron Pick Axe" and self._pick_cd <= 0.0:
            self._pick_cd = ON_FOOT_PICK_COOLDOWN
            self._swing_timer = ON_FOOT_PICK_SWING_TIME
            self._swing_kind = "pick"
            arcade.play_sound(gv._active_weapon._sound, volume=0.5)
            dmg = self._melee_char_damage("pick")
            for node in list(self._nodes):
                if math.hypot(node.center_x - px,
                              node.center_y - py) <= ON_FOOT_PICK_RADIUS + node.radius:
                    node.take_damage(dmg)
                    gv.hit_sparks.append(HitSpark(node.center_x, node.center_y))
                    if node.hp <= 0:
                        gv.inventory.add_item(node.yield_item, node.yield_amount)
                        gv._spawn_explosion(node.center_x, node.center_y)
                        gv._flash_game_msg(
                            f"+{node.yield_amount} {node.yield_item}", 0.8)
                        node.remove_from_sprite_lists()

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

        # Player rifle (non-mining) shots vs enemies.
        for proj in list(gv.projectile_list):
            if getattr(proj, "mines_rock", False):
                continue
            for e in self._enemies:
                if e.state != "alive":
                    continue
                if math.hypot(proj.center_x - e.center_x,
                              proj.center_y - e.center_y) < SURFACE_ENEMY_RADIUS + 6:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    self._damage_enemy(gv, e, int(proj.damage))
                    break

        # On-foot melee swings (Phase 4) — electron sword + pick axe.
        # Read defensively so windowless unit tests (no _active_weapon /
        # _keys / _escape_menu on the stub) just no-op the melee path.
        active_weapon = getattr(gv, "_active_weapon", None)
        active_name = active_weapon.name if active_weapon is not None else ""
        keys = getattr(gv, "_keys", ())
        esc = getattr(gv, "_escape_menu", None)
        fire = (arcade.key.SPACE in keys) and not (esc.open if esc else False)
        sword_active = active_name == "Electron Sword"
        self._update_melee(gv, dt, fire, active_name, px, py)

        # Enemy AI + attacks.
        for e in self._enemies:
            projs, axes, contact = e.update_enemy(dt, px, py)
            for p in projs:
                self._enemy_projectiles.append(p)
            for a in axes:
                self._axes.append(a)
            if contact:
                gv._apply_damage_to_player(int(contact))
                gv._trigger_shake()

        # Enemy bullets vs player (the electron sword deflects a fraction).
        for proj in list(self._enemy_projectiles):
            proj.update_projectile(dt)
            if not proj.sprite_lists:
                continue
            if math.hypot(proj.center_x - px,
                          proj.center_y - py) < ON_FOOT_RADIUS + 8:
                proj.remove_from_sprite_lists()
                if sword_active and random.random() < ON_FOOT_SWORD_DEFLECT:
                    gv.hit_sparks.append(HitSpark(px, py))   # parried
                else:
                    gv._apply_damage_to_player(int(proj.damage))
                    gv._trigger_shake()

        # Thrown axes (boomerang) — damage once on the outbound pass.
        for axe in list(self._axes):
            axe.update_axe(dt)
            if (not axe._hit
                    and math.hypot(axe.center_x - px,
                                   axe.center_y - py) < ON_FOOT_RADIUS + 10):
                axe._hit = True
                if sword_active and random.random() < ON_FOOT_SWORD_DEFLECT:
                    gv.hit_sparks.append(HitSpark(px, py))   # parried
                else:
                    gv._apply_damage_to_player(int(axe.damage))
                    gv._trigger_shake()
            if axe.dead:
                axe.remove_from_sprite_lists()

        # Reap dead enemies + top tiers back up.
        for e in list(self._enemies):
            if e.dead:
                e.remove_from_sprite_lists()
        self._respawn_enemies(dt, px, py)

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

        # Downed on the surface — respawn mid-field (no Home Base yet).
        if gv.player.hp <= 0:
            self._respawn_player(gv)
            return

        # Bottom edge = lift off, back to the originating zone.
        if py < _EXIT_THRESHOLD:
            gv._flash_game_msg("Lifting off…", 1.5)
            gv._transition_zone(self._origin_zone, entry_side="wormhole_return")

    def _respawn_player(self, gv: GameView) -> None:
        """On-foot death has no Home Base yet (later phase): refill HP and
        drop the player back at mid-field, away from the lift-off edge."""
        gv.player.hp = gv.player.max_hp = ON_FOOT_BASE_HP
        gv.player.center_x = self.world_width / 2
        gv.player.center_y = self.world_height / 2
        gv.player.vel_x = gv.player.vel_y = 0.0
        gv._flash_game_msg("You were downed — respawning…", 2.0)

    # ── Drawing ─────────────────────────────────────────────────────

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self.world_width, self.world_height),
            _GROUND_COLOR)
        self._nodes.draw()
        self._enemies.draw()
        self._enemy_projectiles.draw()
        self._axes.draw()

        # Melee swing flash — the weapon sprite arcs in front of the
        # character for the swing window.
        if self._swing_timer > 0.0 and self._swing_sprite is not None:
            p = gv.player
            rad = math.radians(p.heading)
            fx, fy = math.sin(rad), math.cos(rad)
            sp = self._swing_sprite
            sp.texture = (self._sword_tex if self._swing_kind == "sword"
                          else self._pick_tex)
            sp.center_x = p.center_x + fx * 38.0
            sp.center_y = p.center_y + fy * 38.0
            swing_time = (ON_FOOT_SWORD_SWING_TIME
                          if self._swing_kind == "sword"
                          else ON_FOOT_PICK_SWING_TIME)
            progress = 1.0 - (self._swing_timer / max(1e-6, swing_time))
            sp.angle = (p.heading + (progress * 120.0 - 60.0)) % 360
            arcade.draw_sprite(sp)

    def get_minimap_objects(self):
        return self._enemies, arcade.SpriteList()
