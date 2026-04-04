"""Zone 2 (The Nebula) — second biome with new resources, hazards, and enemies."""
from __future__ import annotations

import math
import os
import random
from typing import TYPE_CHECKING

import arcade
from PIL import Image as PILImage

from constants import (
    ZONE2_WIDTH, ZONE2_HEIGHT,
    ASTEROID_HP, ASTEROID_COUNT, ASTEROID_IRON_YIELD, ASTEROID_MIN_DIST,
    DOUBLE_IRON_COUNT, DOUBLE_IRON_HP, DOUBLE_IRON_YIELD, DOUBLE_IRON_SCALE,
    DOUBLE_IRON_XP, COPPER_ASTEROID_COUNT, COPPER_ASTEROID_HP,
    COPPER_YIELD, COPPER_XP, COPPER_ASTEROID_PNG, COPPER_PICKUP_PNG,
    GAS_AREA_COUNT, GAS_AREA_DAMAGE, GAS_AREA_SLOW,
    GAS_AREA_MIN_SIZE, GAS_AREA_MAX_SIZE,
    WANDERING_COUNT, WANDERING_DAMAGE, WANDERING_RADIUS,
    SHIP_RADIUS, SHIP_COLLISION_COOLDOWN,
    ALIEN_DETECT_DIST, ALIEN_LASER_DAMAGE, ALIEN_LASER_RANGE,
    ALIEN_LASER_SPEED, ALIEN_FIRE_COOLDOWN,
    Z2_SHIELDED_COUNT, Z2_SHIELDED_XP,
    Z2_FAST_COUNT, Z2_FAST_XP,
    Z2_GUNNER_COUNT, Z2_GUNNER_XP,
    Z2_RAMMER_COUNT, Z2_RAMMER_XP,
    Z2_ALIEN_SHIP_PNG,
    BLUEPRINT_DROP_CHANCE_ALIEN, BLUEPRINT_DROP_CHANCE_ASTEROID,
    RESPAWN_INTERVAL, RESPAWN_EXCLUSION_RADIUS,
    MODULE_TYPES,
)
from zones import ZoneID, ZoneState
from sprites.wormhole import Wormhole
from sprites.asteroid import IronAsteroid

if TYPE_CHECKING:
    from game_view import GameView


class Zone2(ZoneState):
    """The Nebula — second biome with copper, gas clouds, new aliens."""
    zone_id = ZoneID.ZONE2
    world_width = ZONE2_WIDTH
    world_height = ZONE2_HEIGHT

    def __init__(self) -> None:
        # Sprite lists
        self._iron_asteroids: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._double_iron: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._copper_asteroids: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._aliens: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._alien_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._gas_areas: arcade.SpriteList = arcade.SpriteList()
        self._wanderers: arcade.SpriteList = arcade.SpriteList()
        # Textures (loaded on setup)
        self._iron_tex: arcade.Texture | None = None
        self._copper_tex: arcade.Texture | None = None
        self._copper_pickup_tex: arcade.Texture | None = None
        self._alien_textures: dict[str, arcade.Texture] = {}
        self._alien_laser_tex: arcade.Texture | None = None
        self._wanderer_tex: arcade.Texture | None = None
        # State
        self._gas_damage_cd: float = 0.0
        self._respawn_timer: float = 0.0
        self._alien_counts: dict[str, int] = {}

    def setup(self, gv: GameView) -> None:
        _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Load textures
        self._iron_tex = gv._asteroid_tex
        self._copper_tex = arcade.load_texture(COPPER_ASTEROID_PNG)
        self._copper_pickup_tex = arcade.load_texture(COPPER_PICKUP_PNG)
        self._alien_laser_tex = gv._alien_laser_tex

        # Load alien textures from Ship.png crops
        from sprites.zone2_aliens import ALIEN_CROPS
        pil_ship = PILImage.open(Z2_ALIEN_SHIP_PNG).convert("RGBA")
        for name, crop in ALIEN_CROPS.items():
            frame = pil_ship.crop(crop)
            self._alien_textures[name] = arcade.Texture(frame)
        pil_ship.close()

        # Wanderer uses same asteroid texture
        self._wanderer_tex = self._iron_tex

        # Populate iron asteroids (same count as zone 1)
        self._populate_iron_asteroids()
        # Populate double iron asteroids
        self._populate_double_iron()
        # Populate copper asteroids
        self._populate_copper_asteroids()
        # Populate gas areas
        self._populate_gas_areas()
        # Populate wandering asteroids
        self._populate_wanderers()
        # Populate aliens
        self._populate_aliens()

        # Return wormhole at centre
        wh = Wormhole(self.world_width / 2, self.world_height / 2)
        wh.zone_target = ZoneID.MAIN
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)

        # Spawn a trader station in Zone 2
        if gv._trade_station is None:
            gv._spawn_trade_station()

    def teardown(self, gv: GameView) -> None:
        self._iron_asteroids.clear()
        self._double_iron.clear()
        self._copper_asteroids.clear()
        self._aliens.clear()
        self._alien_projectiles.clear()
        self._gas_areas.clear()
        self._wanderers.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        # Find a safe position near centre, not inside any gas cloud
        cx, cy = self.world_width / 2, self.world_height / 2 - 200
        for _ in range(50):
            safe = True
            for g in self._gas_areas:
                if g.contains_point(cx, cy):
                    safe = False
                    break
            if safe:
                return cx, cy
            # Try a random nearby position
            cx = self.world_width / 2 + random.uniform(-300, 300)
            cy = self.world_height / 2 - 200 + random.uniform(-300, 300)
        return self.world_width / 2, self.world_height / 2 - 200

    # ── Population ─────────────────────────────────────────────────────────

    def _rand_pos(self, margin: float = 100.0) -> tuple[float, float]:
        return (random.uniform(margin, self.world_width - margin),
                random.uniform(margin, self.world_height - margin))

    def _populate_iron_asteroids(self) -> None:
        for _ in range(ASTEROID_COUNT):
            x, y = self._rand_pos()
            self._iron_asteroids.append(IronAsteroid(self._iron_tex, x, y))

    def _populate_double_iron(self) -> None:
        for _ in range(DOUBLE_IRON_COUNT):
            x, y = self._rand_pos()
            a = IronAsteroid(self._iron_tex, x, y)
            a.hp = DOUBLE_IRON_HP
            a.scale = DOUBLE_IRON_SCALE
            self._double_iron.append(a)

    def _populate_copper_asteroids(self) -> None:
        from sprites.copper_asteroid import CopperAsteroid
        for _ in range(COPPER_ASTEROID_COUNT):
            x, y = self._rand_pos()
            self._copper_asteroids.append(CopperAsteroid(self._copper_tex, x, y))

    def _populate_gas_areas(self) -> None:
        from sprites.gas_area import GasArea, generate_gas_texture
        textures = {}
        sizes = [64, 128, 192, 256, 384]
        for _ in range(GAS_AREA_COUNT):
            size = random.choice(sizes)
            if size not in textures:
                textures[size] = generate_gas_texture(size)
            x, y = self._rand_pos(200)
            self._gas_areas.append(GasArea(textures[size], x, y, size,
                                           world_w=self.world_width,
                                           world_h=self.world_height))

    def _populate_wanderers(self) -> None:
        from sprites.wandering_asteroid import WanderingAsteroid
        for _ in range(WANDERING_COUNT):
            x, y = self._rand_pos()
            self._wanderers.append(
                WanderingAsteroid(self._wanderer_tex, x, y,
                                  self.world_width, self.world_height))

    def _populate_aliens(self) -> None:
        from sprites.zone2_aliens import (
            ShieldedAlien, FastAlien, GunnerAlien, RammerAlien,
        )
        kw = dict(world_w=self.world_width, world_h=self.world_height)
        tex_s = self._alien_textures["shielded"]
        tex_f = self._alien_textures["fast"]
        tex_g = self._alien_textures["gunner"]
        tex_r = self._alien_textures["rammer"]
        lt = self._alien_laser_tex

        for _ in range(Z2_SHIELDED_COUNT):
            x, y = self._rand_pos(200)
            self._aliens.append(ShieldedAlien(tex_s, lt, x, y, **kw))
        for _ in range(Z2_FAST_COUNT):
            x, y = self._rand_pos(200)
            self._aliens.append(FastAlien(tex_f, lt, x, y, **kw))
        for _ in range(Z2_GUNNER_COUNT):
            x, y = self._rand_pos(200)
            self._aliens.append(GunnerAlien(tex_g, lt, x, y, **kw))
        for _ in range(Z2_RAMMER_COUNT):
            x, y = self._rand_pos(200)
            self._aliens.append(RammerAlien(tex_r, lt, x, y, **kw))

        self._alien_counts = {
            "shielded": Z2_SHIELDED_COUNT,
            "fast": Z2_FAST_COUNT,
            "gunner": Z2_GUNNER_COUNT,
            "rammer": Z2_RAMMER_COUNT,
        }

    # ── Update ─────────────────────────────────────────────────────────────

    def update(self, gv: GameView, dt: float) -> None:
        from sprites.explosion import HitSpark
        from sprites.zone2_aliens import ShieldedAlien

        px, py = gv.player.center_x, gv.player.center_y

        # Wormhole animation + collision
        for wh in gv._wormholes:
            wh.update_wormhole(dt)
            if math.hypot(px - wh.center_x, py - wh.center_y) < 100:
                gv._use_glow = (100, 180, 255, 200)
                gv._use_glow_timer = 0.5
                arcade.play_sound(gv._victory_snd, volume=0.6)
                gv._flash_game_msg("Returning through wormhole...", 1.5)
                target = wh.zone_target if wh.zone_target is not None else ZoneID.MAIN
                gv._transition_zone(target, entry_side="wormhole_return")
                return

        # Update asteroids
        for a in self._iron_asteroids:
            a.update_asteroid(dt)
        for a in self._double_iron:
            a.update_asteroid(dt)
        for a in self._copper_asteroids:
            a.update_asteroid(dt)

        # Update gas areas
        for g in self._gas_areas:
            g.update_gas(dt)
        self._update_gas_damage(gv, dt)

        # Update wandering asteroids
        # Wandering asteroids: spin only, no movement in Zone 2
        for w in self._wanderers:
            w.angle = (w.angle + w._rot_speed * dt) % 360
        self._update_wanderer_collision(gv, dt)

        # Update aliens
        for alien in list(self._aliens):
            projs = alien.update_alien(
                dt, px, py, self._iron_asteroids, self._aliens)
            for p in projs:
                self._alien_projectiles.append(p)

        # Alien projectiles
        for proj in list(self._alien_projectiles):
            proj.update_projectile(dt)
            dist = math.hypot(proj.center_x - px, proj.center_y - py)
            if dist < SHIP_RADIUS + 8:
                proj.remove_from_sprite_lists()
                gv._apply_damage_to_player(int(proj.damage))
                gv._trigger_shake()

        # Player projectile hits
        self._handle_projectile_hits(gv)

        # Player-asteroid collision (iron, double iron, copper)
        from constants import ASTEROID_RADIUS, SHIP_COLLISION_DAMAGE, SHIP_BOUNCE
        for alist in (self._iron_asteroids, self._double_iron, self._copper_asteroids):
            for a in alist:
                ddx = gv.player.center_x - a.center_x
                ddy = gv.player.center_y - a.center_y
                ddist = math.hypot(ddx, ddy)
                # Use half the sprite width as radius for copper (larger)
                a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                combined = a_radius + SHIP_RADIUS
                if ddist < combined and ddist > 0 and gv.player._collision_cd <= 0.0:
                    # Push apart
                    nx, ny = ddx / ddist, ddy / ddist
                    overlap = combined - ddist
                    gv.player.center_x += nx * overlap
                    gv.player.center_y += ny * overlap
                    # Bounce
                    dot = gv.player.vel_x * nx + gv.player.vel_y * ny
                    if dot < 0:
                        gv.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
                        gv.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny
                    gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                    gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    gv._trigger_shake()
                    arcade.play_sound(gv._bump_snd, volume=0.4)

        # Alien-player collision (with push-apart so they don't stick)
        from constants import ALIEN_RADIUS, ALIEN_BOUNCE
        for alien in list(self._aliens):
            ddx = alien.center_x - gv.player.center_x
            ddy = alien.center_y - gv.player.center_y
            ddist = math.hypot(ddx, ddy)
            combined = 20 + SHIP_RADIUS
            if ddist < combined and ddist > 0:
                # Push apart
                nx, ny = ddx / ddist, ddy / ddist
                overlap = combined - ddist
                alien.center_x += nx * overlap * 0.5
                alien.center_y += ny * overlap * 0.5
                gv.player.center_x -= nx * overlap * 0.5
                gv.player.center_y -= ny * overlap * 0.5
                # Bounce alien away
                alien.vel_x += nx * 150
                alien.vel_y += ny * 150
                # Bounce player
                dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
                if dot < 0:
                    gv.player.vel_x -= (1 + ALIEN_BOUNCE) * dot * (-nx) * 0.4
                    gv.player.vel_y -= (1 + ALIEN_BOUNCE) * dot * (-ny) * 0.4
                if gv.player._collision_cd <= 0.0:
                    gv._apply_damage_to_player(5)
                    gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    gv._trigger_shake()
                    arcade.play_sound(gv._bump_snd, volume=0.3)

        # Respawn timer
        self._respawn_timer += dt
        if self._respawn_timer >= RESPAWN_INTERVAL:
            self._respawn_timer = 0.0
            self._try_respawn(gv)

    def _update_gas_damage(self, gv: GameView, dt: float) -> None:
        """Check if player is in a gas area — damage and slow."""
        self._gas_damage_cd = max(0.0, self._gas_damage_cd - dt)
        px, py = gv.player.center_x, gv.player.center_y
        in_gas = False
        for g in self._gas_areas:
            if g.contains_point(px, py):
                in_gas = True
                if self._gas_damage_cd <= 0.0:
                    gv._apply_damage_to_player(int(GAS_AREA_DAMAGE))
                    gv._trigger_shake()
                    gv._flash_game_msg("Toxic gas!", 0.5)
                    self._gas_damage_cd = 1.0
                break
        # Slow player while in gas
        if in_gas:
            gv.player.vel_x *= GAS_AREA_SLOW ** (dt * 60)
            gv.player.vel_y *= GAS_AREA_SLOW ** (dt * 60)

    def _update_wanderer_collision(self, gv: GameView, dt: float) -> None:
        """Check wandering asteroid collision with player."""
        px, py = gv.player.center_x, gv.player.center_y
        for w in list(self._wanderers):
            dist = math.hypot(w.center_x - px, w.center_y - py)
            if dist < WANDERING_RADIUS + SHIP_RADIUS:
                if gv.player._collision_cd <= 0.0:
                    gv._apply_damage_to_player(WANDERING_DAMAGE)
                    gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    gv._trigger_shake()
                    arcade.play_sound(gv._bump_snd, volume=0.4)

    def _handle_projectile_hits(self, gv: GameView) -> None:
        """Player projectile hits on asteroids and aliens."""
        from sprites.explosion import HitSpark
        from sprites.zone2_aliens import ShieldedAlien

        for proj in list(gv.projectile_list):
            consumed = False

            # Mining beam vs asteroids
            if proj.mines_rock:
                # Iron asteroids
                for a in list(self._iron_asteroids):
                    if math.hypot(proj.center_x - a.center_x,
                                  proj.center_y - a.center_y) < 36:
                        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                        proj.remove_from_sprite_lists()
                        consumed = True
                        a.take_damage(int(proj.damage))
                        if a.hp <= 0:
                            gv._spawn_explosion(a.center_x, a.center_y)
                            gv._spawn_iron_pickup(a.center_x, a.center_y,
                                                  amount=ASTEROID_IRON_YIELD)
                            gv._add_xp(10)
                            # Blueprint chance
                            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
                            a.remove_from_sprite_lists()
                        break
                if consumed:
                    continue

                # Double iron asteroids
                for a in list(self._double_iron):
                    if math.hypot(proj.center_x - a.center_x,
                                  proj.center_y - a.center_y) < 60:
                        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                        proj.remove_from_sprite_lists()
                        consumed = True
                        a.take_damage(int(proj.damage))
                        if a.hp <= 0:
                            gv._spawn_explosion(a.center_x, a.center_y)
                            gv._spawn_iron_pickup(a.center_x, a.center_y,
                                                  amount=DOUBLE_IRON_YIELD)
                            gv._add_xp(DOUBLE_IRON_XP)
                            if random.random() < BLUEPRINT_DROP_CHANCE_ASTEROID:
                                gv._spawn_blueprint_pickup(a.center_x, a.center_y)
                            a.remove_from_sprite_lists()
                        break
                if consumed:
                    continue

                # Copper asteroids
                for a in list(self._copper_asteroids):
                    if math.hypot(proj.center_x - a.center_x,
                                  proj.center_y - a.center_y) < 96:
                        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                        proj.remove_from_sprite_lists()
                        consumed = True
                        a.take_damage(int(proj.damage))
                        if a.hp <= 0:
                            gv._spawn_explosion(a.center_x, a.center_y)
                            # Spawn copper pickup
                            from sprites.pickup import IronPickup
                            from character_data import bonus_copper_asteroid
                            from settings import audio
                            base = COPPER_YIELD
                            extra = bonus_copper_asteroid(audio.character_name, gv._char_level)
                            pickup = IronPickup(self._copper_pickup_tex,
                                                a.center_x, a.center_y,
                                                amount=base + extra)
                            pickup.item_type = "copper"
                            gv.iron_pickup_list.append(pickup)
                            gv._add_xp(COPPER_XP)
                            a.remove_from_sprite_lists()
                        break
                if consumed:
                    continue

                # Wandering asteroids (minable)
                for w in list(self._wanderers):
                    if math.hypot(proj.center_x - w.center_x,
                                  proj.center_y - w.center_y) < 30:
                        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                        proj.remove_from_sprite_lists()
                        consumed = True
                        w.take_damage(int(proj.damage))
                        if w.hp <= 0:
                            gv._spawn_explosion(w.center_x, w.center_y)
                            w.remove_from_sprite_lists()
                        break
                if consumed:
                    continue

            # Basic laser vs aliens
            if not proj.mines_rock:
                for alien in list(self._aliens):
                    dist = math.hypot(proj.center_x - alien.center_x,
                                      proj.center_y - alien.center_y)
                    if dist < 25:
                        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                        gv._trigger_shake()
                        proj.remove_from_sprite_lists()
                        consumed = True
                        alien.take_damage(int(proj.damage))
                        if alien.hp <= 0:
                            gv._spawn_explosion(alien.center_x, alien.center_y)
                            gv._spawn_iron_pickup(alien.center_x, alien.center_y, amount=5)
                            # Copper bonus from Debra
                            from character_data import bonus_copper_enemy
                            from settings import audio
                            copper_extra = bonus_copper_enemy(audio.character_name, gv._char_level)
                            if copper_extra > 0:
                                from sprites.pickup import IronPickup
                                cp = IronPickup(self._copper_pickup_tex,
                                                alien.center_x, alien.center_y,
                                                amount=copper_extra)
                                cp.item_type = "copper"
                                gv.iron_pickup_list.append(cp)
                            # XP based on type
                            xp = self._xp_for_alien(alien)
                            gv._add_xp(xp)
                            # Blueprint drop
                            from character_data import blueprint_drop_bonus
                            bp_chance = BLUEPRINT_DROP_CHANCE_ALIEN + blueprint_drop_bonus(
                                audio.character_name, gv._char_level)
                            if random.random() < bp_chance:
                                gv._spawn_blueprint_pickup(alien.center_x, alien.center_y)
                            alien.remove_from_sprite_lists()
                        break

    def _xp_for_alien(self, alien) -> int:
        from sprites.zone2_aliens import (
            ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
        if isinstance(alien, ShieldedAlien):
            return Z2_SHIELDED_XP
        elif isinstance(alien, FastAlien):
            return Z2_FAST_XP
        elif isinstance(alien, GunnerAlien):
            return Z2_GUNNER_XP
        elif isinstance(alien, RammerAlien):
            return Z2_RAMMER_XP
        return 25

    def _try_respawn(self, gv: GameView) -> None:
        """Respawn one alien of each type if below max."""
        from sprites.zone2_aliens import (
            ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
        lt = self._alien_laser_tex
        kw = dict(world_w=self.world_width, world_h=self.world_height)
        # Count current
        counts = {"shielded": 0, "fast": 0, "gunner": 0, "rammer": 0}
        for a in self._aliens:
            if isinstance(a, ShieldedAlien):
                counts["shielded"] += 1
            elif isinstance(a, FastAlien):
                counts["fast"] += 1
            elif isinstance(a, GunnerAlien):
                counts["gunner"] += 1
            elif isinstance(a, RammerAlien):
                counts["rammer"] += 1
        maxes = {"shielded": Z2_SHIELDED_COUNT, "fast": Z2_FAST_COUNT,
                 "gunner": Z2_GUNNER_COUNT, "rammer": Z2_RAMMER_COUNT}
        classes = {"shielded": ShieldedAlien, "fast": FastAlien,
                   "gunner": GunnerAlien, "rammer": RammerAlien}
        for name, max_count in maxes.items():
            if counts[name] < max_count:
                x, y = self._rand_pos(200)
                cls = classes[name]
                tex = self._alien_textures[name]
                self._aliens.append(cls(tex, lt, x, y, **kw))

    # ── Drawing ────────────────────────────────────────────────────────────

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        from sprites.zone2_aliens import ShieldedAlien

        self._gas_areas.draw()
        self._iron_asteroids.draw()
        self._double_iron.draw()
        self._copper_asteroids.draw()
        self._wanderers.draw()
        # Wormholes
        if gv._wormholes:
            gv._wormhole_list.draw()
        # Aliens + shield overlays
        self._aliens.draw()
        for alien in self._aliens:
            if isinstance(alien, ShieldedAlien):
                alien.draw_shield()
        self._alien_projectiles.draw()
        # Pickups that may have been spawned
        gv.iron_pickup_list.draw()
        gv.blueprint_pickup_list.draw()

    def to_save_data(self) -> dict:
        return {}  # Zone 2 state not yet persisted (regenerated on entry)

    def from_save_data(self, data: dict, gv: GameView) -> None:
        pass
