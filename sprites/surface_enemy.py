"""Planet-surface enemies (Tiny Rangers Frosty Forest) — Phase 3.

Front-facing (top-down) animated creatures that hunt the on-foot
character.  All eight types share one ``SurfaceEnemy`` class; behaviour
comes from the ``SurfaceEnemySpec`` (see specs.py).  The owning
``PlanetarySurfaceZone`` drives the per-frame update and owns the
projectile / thrown-axe lists, mirroring the landing-scene pattern.

Assets are individual frame PNGs per enemy (idle 1-4, walk 1-6 or run
1-4, a single dead frame, attack 1-4 for some) plus bullet / axe
sprites.  They're loaded once and cached, shared across every instance.

Four attack behaviours:
  * **projectile** — pursue to ``attack_range``, fire a bullet that flies
    at the player (orange helmet sniper, horned helmet rifle, voodoo ice
    axe, horned breather breath).
  * **throw_return** — boomerang axe that flies to the player and returns
    to the thrower, plus a close-range spear (ice crown).
  * **bump** — charge straight into the player for contact damage
    (ice cat, teal cat).
  * **melee** — close in and swing an attack animation (horned biter).
"""
from __future__ import annotations

import math
import os
import random
from typing import TYPE_CHECKING

import arcade
from PIL import Image as PILImage

from constants import (
    SURFACE_ENEMY_DIR, SURFACE_ENEMY_SCALE, SURFACE_ENEMY_RADIUS,
    SURFACE_ENEMY_ANIM_FPS, SURFACE_ENEMY_DEAD_LINGER,
    SURFACE_ENEMY_PROJ_SPEED, SURFACE_ENEMY_PROJ_SCALE,
    SURFACE_AXE_SPEED, SURFACE_AXE_SPIN,
)
from sprites.projectile import Projectile

if TYPE_CHECKING:
    from specs import SurfaceEnemySpec


# ── Asset loading (cached, shared across instances) ─────────────────────────

_asset_cache: dict[str, dict] | None = None


def _load_frames(folder: str, base: str, prefix: str, count: int) -> list[arcade.Texture]:
    out: list[arcade.Texture] = []
    for i in range(1, count + 1):
        path = os.path.join(folder, f"enemy_{base}_{prefix}_{i}.png")
        if os.path.isfile(path):
            out.append(arcade.Texture(PILImage.open(path).convert("RGBA")))
    return out


def load_surface_enemy_assets() -> dict[str, dict]:
    """Load + cache every surface-enemy animation set.  Returns a dict
    keyed by enemy ``key`` → ``{idle, move, attack, dead, bullet, axe}``.
    Front-facing sprites, so no left/right mirroring is needed."""
    global _asset_cache
    if _asset_cache is not None:
        return _asset_cache
    from specs import SURFACE_ENEMIES

    cache: dict[str, dict] = {}
    for key, spec in SURFACE_ENEMIES.items():
        folder = os.path.join(SURFACE_ENEMY_DIR, f"Enemy {spec.folder}")
        base = str(spec.folder)
        idle = _load_frames(folder, base, "idle", 4)
        move = _load_frames(folder, base, spec.locomotion, 6)
        attack = (_load_frames(folder, base, "attack", 4)
                  if spec.has_attack_frames else None)
        dead_path = os.path.join(folder, f"enemy_{base}_dead.png")
        dead = arcade.Texture(PILImage.open(dead_path).convert("RGBA"))
        bullet = None
        if spec.bullet_file:
            bp = os.path.join(folder, spec.bullet_file)
            if os.path.isfile(bp):
                bullet = arcade.Texture(PILImage.open(bp).convert("RGBA"))
        axe = None
        if spec.axe_file:
            ap = os.path.join(folder, spec.axe_file)
            if os.path.isfile(ap):
                axe = arcade.Texture(PILImage.open(ap).convert("RGBA"))
        cache[key] = {"idle": idle, "move": move, "attack": attack,
                      "dead": dead, "bullet": bullet, "axe": axe}
    _asset_cache = cache
    return cache


# ── Thrown axe (ice crown boomerang) ────────────────────────────────────────

class ThrownAxe(arcade.Sprite):
    """A boomerang axe: spins out toward where the player was, then
    returns to the thrower.  Deals its damage once on the outbound pass
    (the owning zone checks the player hit)."""

    _MAX_LIFETIME = 4.0

    def __init__(self, texture: arcade.Texture, owner: "SurfaceEnemy",
                 target_x: float, target_y: float, damage: int) -> None:
        super().__init__(path_or_texture=texture, scale=SURFACE_ENEMY_SCALE)
        self._owner = owner
        self.center_x = owner.center_x
        self.center_y = owner.center_y
        self._tx, self._ty = target_x, target_y
        self.damage = damage
        self._phase = "out"
        self._hit = False
        self.dead = False
        self._life = 0.0

    def update_axe(self, dt: float) -> None:
        self._life += dt
        self.angle = (self.angle + SURFACE_AXE_SPIN * dt) % 360
        if self._phase == "out":
            tx, ty = self._tx, self._ty
        else:
            # Return to the (possibly moved) thrower.
            tx, ty = self._owner.center_x, self._owner.center_y
        dx, dy = tx - self.center_x, ty - self.center_y
        dist = math.hypot(dx, dy)
        step = SURFACE_AXE_SPEED * dt
        if dist <= step:
            self.center_x, self.center_y = tx, ty
            if self._phase == "out":
                self._phase = "back"
            else:
                self.dead = True
        else:
            self.center_x += dx / dist * step
            self.center_y += dy / dist * step
        if self._life >= self._MAX_LIFETIME:
            self.dead = True


# ── Surface enemy ───────────────────────────────────────────────────────────

class SurfaceEnemy(arcade.Sprite):
    """One animated, pursuing surface creature."""

    def __init__(self, spec: "SurfaceEnemySpec", assets: dict,
                 x: float, y: float,
                 world_w: float, world_h: float,
                 rng: random.Random | None = None) -> None:
        self._assets = assets
        super().__init__(path_or_texture=assets["idle"][0],
                         scale=SURFACE_ENEMY_SCALE)
        self.center_x = x
        self.center_y = y
        self.spec = spec
        self.hp: int = spec.hp
        self.max_hp: int = spec.hp
        self.armor: int = spec.armor
        self.radius: float = SURFACE_ENEMY_RADIUS
        self._world_w = world_w
        self._world_h = world_h
        self.state: str = "alive"           # "alive" | "dying"
        self.dead: bool = False             # True once removable
        self._dead_timer: float = 0.0
        r = rng or random
        self._atk_cd: float = r.uniform(0.0, spec.attack_cooldown)
        self._melee_cd: float = 0.0
        self._anim_idx: int = 0
        self._anim_timer: float = 0.0

    # ── Damage ──────────────────────────────────────────────────────
    def take_damage(self, amount: int) -> None:
        """Armor reduces incoming damage (never below 1), then HP."""
        if self.state != "alive":
            return
        amount = max(1, int(amount) - self.armor)
        self.hp -= amount
        if self.hp <= 0:
            self.state = "dying"
            self._dead_timer = SURFACE_ENEMY_DEAD_LINGER

    # ── Per-frame update ────────────────────────────────────────────
    def update_enemy(self, dt: float, px: float, py: float):
        """Advance one frame.  Returns ``(projectiles, axes, contact_dmg)``:
        new bullets to add, new thrown axes to add, and melee/bump damage
        to apply to the player this frame (0 if none)."""
        self._anim_timer += dt
        if self.state == "dying":
            self._dead_timer -= dt
            if self._dead_timer <= 0:
                self.dead = True
            self.texture = self._assets["dead"]
            return [], [], 0

        projectiles: list = []
        axes: list = []
        contact = 0
        self._atk_cd = max(0.0, self._atk_cd - dt)
        self._melee_cd = max(0.0, self._melee_cd - dt)

        dx, dy = px - self.center_x, py - self.center_y
        dist = math.hypot(dx, dy)
        spec = self.spec
        moving = False
        attacking = False

        if spec.attack_kind == "projectile":
            if dist > spec.attack_range:
                self._move_toward(dx, dy, dist, dt)
                moving = True
            else:
                attacking = spec.has_attack_frames
                if self._atk_cd <= 0.0:
                    self._atk_cd = spec.attack_cooldown
                    projectiles.append(self._make_bullet(dx, dy, dist))
        elif spec.attack_kind == "throw_return":
            if dist > spec.attack_range:
                self._move_toward(dx, dy, dist, dt)
                moving = True
            elif self._atk_cd <= 0.0:
                self._atk_cd = spec.attack_cooldown
                axes.append(ThrownAxe(self._assets["axe"], self, px, py,
                                      spec.damage))
            # Secondary spear at close range.
            if (spec.melee_damage and dist <= spec.melee_range
                    and self._melee_cd <= 0.0):
                self._melee_cd = spec.attack_cooldown
                contact = spec.melee_damage
        elif spec.attack_kind == "bump":
            self._move_toward(dx, dy, dist, dt)
            moving = True
            if dist <= spec.attack_range and self._atk_cd <= 0.0:
                self._atk_cd = spec.attack_cooldown
                contact = spec.damage
        elif spec.attack_kind == "melee":
            if dist > spec.attack_range:
                self._move_toward(dx, dy, dist, dt)
                moving = True
            else:
                attacking = spec.has_attack_frames
                if self._atk_cd <= 0.0:
                    self._atk_cd = spec.attack_cooldown
                    contact = spec.damage

        # Animation frame selection.
        if attacking and self._assets["attack"]:
            frames = self._assets["attack"]
        elif moving:
            frames = self._assets["move"] or self._assets["idle"]
        else:
            frames = self._assets["idle"]
        self._advance_anim(frames)
        return projectiles, axes, contact

    def _move_toward(self, dx: float, dy: float, dist: float, dt: float) -> None:
        if dist < 1.0:
            return
        nx, ny = dx / dist, dy / dist
        r = self.radius
        self.center_x = max(r, min(self._world_w - r,
                                   self.center_x + nx * self.spec.speed * dt))
        self.center_y = max(r, min(self._world_h - r,
                                   self.center_y + ny * self.spec.speed * dt))

    def _advance_anim(self, frames: list) -> None:
        if not frames:
            return
        step = 1.0 / SURFACE_ENEMY_ANIM_FPS
        while self._anim_timer >= step:
            self._anim_timer -= step
            self._anim_idx += 1
        self.texture = frames[self._anim_idx % len(frames)]

    def _make_bullet(self, dx: float, dy: float, dist: float) -> Projectile:
        heading = (math.degrees(math.atan2(dx / dist, dy / dist)) % 360
                   if dist > 0 else 0.0)
        return Projectile(
            self._assets["bullet"],
            self.center_x, self.center_y, heading,
            SURFACE_ENEMY_PROJ_SPEED, self.spec.attack_range * 2.5,
            scale=SURFACE_ENEMY_PROJ_SCALE, damage=self.spec.damage,
        )
