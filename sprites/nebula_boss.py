"""Nebula boss — variant of BossAlienShip with two extra gas attacks.

Same core stats and phase logic as ``BossAlienShip`` (HP, shields,
three phases, charge dash, main cannon + spread shot).  Adds:

  * **Gas cloud projectile** — slow, persistent, damages + slows the
    player on contact.  Expires after travelling ``NEBULA_BOSS_GAS_RANGE``
    pixels.
  * **Gas cone** — short-range AoE that ticks damage + slow to the
    player while they're inside it.  Shaped as a triangle of
    ``NEBULA_BOSS_CONE_WIDTH`` at its far end, ``NEBULA_BOSS_CONE_RANGE``
    long.

Sprite is cropped from column 1 / row 0 of the
``faction_6_monsters_128x128.png`` sheet (8×8 grid), per user spec:
"one of the eight images in the second column."
"""
from __future__ import annotations

import math
from typing import Optional

import arcade
from PIL import Image as PILImage

from constants import (
    NEBULA_BOSS_PNG, NEBULA_BOSS_FRAME_SIZE,
    NEBULA_BOSS_COL_INDEX, NEBULA_BOSS_ROW_INDEX,
    NEBULA_BOSS_GAS_SPEED, NEBULA_BOSS_GAS_RANGE,
    NEBULA_BOSS_GAS_COOLDOWN, NEBULA_BOSS_GAS_RADIUS,
    NEBULA_BOSS_CONE_RANGE, NEBULA_BOSS_CONE_WIDTH,
    NEBULA_BOSS_CONE_DURATION, NEBULA_BOSS_CONE_COOLDOWN,
    BOSS_DETECT_RANGE,
)
from sprites.boss import BossAlienShip, _PHASE1, _PHASE2, _PHASE3


_nebula_boss_texture_cache: arcade.Texture | None = None


def load_nebula_boss_texture() -> arcade.Texture:
    """Crop and cache the Nebula boss texture (col=1, row=0 of the
    128×128 grid)."""
    global _nebula_boss_texture_cache
    if _nebula_boss_texture_cache is not None:
        return _nebula_boss_texture_cache
    sheet = PILImage.open(NEBULA_BOSS_PNG).convert("RGBA")
    size = NEBULA_BOSS_FRAME_SIZE
    x = NEBULA_BOSS_COL_INDEX * size
    y = NEBULA_BOSS_ROW_INDEX * size
    crop = sheet.crop((x, y, x + size, y + size))
    sheet.close()
    _nebula_boss_texture_cache = arcade.Texture(crop)
    return _nebula_boss_texture_cache


# ─────────────────────────────────────────────────────────────────────────────
#  Gas cloud projectile
# ─────────────────────────────────────────────────────────────────────────────

class GasCloudProjectile(arcade.Sprite):
    """Slow-moving gas puff fired by the Nebula boss.

    Implemented as a hollow sprite (no texture).  Drawn as a pulsing
    green circle via ``NebulaBossShip.draw_gas_clouds``.  Travels at
    ``NEBULA_BOSS_GAS_SPEED`` px/s in a straight line; despawns once
    ``_traveled`` reaches ``NEBULA_BOSS_GAS_RANGE``.

    Shares the collision API of regular projectiles (``damage`` +
    ``center_x``/``center_y`` + ``radius``) so existing handlers can
    grep for it in the boss projectile list.
    """

    def __init__(self, x: float, y: float, heading_deg: float,
                 damage: float) -> None:
        # No texture — we render via primitives in the boss draw path.
        # Build a tiny transparent stand-in so arcade's hit-box math
        # has something to hold.
        blank = PILImage.new("RGBA",
                              (int(NEBULA_BOSS_GAS_RADIUS * 2),
                               int(NEBULA_BOSS_GAS_RADIUS * 2)),
                              (0, 0, 0, 0))
        super().__init__(path_or_texture=arcade.Texture(blank),
                          scale=1.0)
        self.center_x = x
        self.center_y = y
        self.damage: float = damage
        self.radius: float = NEBULA_BOSS_GAS_RADIUS
        self._heading: float = heading_deg
        rad = math.radians(heading_deg)
        self._vx: float = math.sin(rad) * NEBULA_BOSS_GAS_SPEED
        self._vy: float = math.cos(rad) * NEBULA_BOSS_GAS_SPEED
        self._traveled: float = 0.0
        # Visual pulse — gas clouds breathe.
        self._phase: float = 0.0

    def update_gas(self, dt: float) -> bool:
        """Advance position + pulse.  Returns True when the cloud
        should despawn (travelled past ``NEBULA_BOSS_GAS_RANGE``)."""
        self.center_x += self._vx * dt
        self.center_y += self._vy * dt
        step = math.hypot(self._vx, self._vy) * dt
        self._traveled += step
        self._phase = (self._phase + dt * 3.0) % math.tau
        return self._traveled >= NEBULA_BOSS_GAS_RANGE

    def contains_point(self, px: float, py: float) -> bool:
        dx = px - self.center_x
        dy = py - self.center_y
        return dx * dx + dy * dy <= self.radius * self.radius


# ─────────────────────────────────────────────────────────────────────────────
#  Nebula boss
# ─────────────────────────────────────────────────────────────────────────────

class NebulaBossShip(BossAlienShip):
    """Double Star boss's gas-themed sibling.

    Reuses every parent mechanic (3 phases, charge dash, cannon +
    spread, shield regen changes per phase).  Adds one gas cloud
    projectile attack on a 4 s cooldown and one gas cone AoE on a
    6 s cooldown, both gated by the same ``BOSS_DETECT_RANGE`` the
    parent uses for its own weapons.

    Gas clouds are fired through ``NebulaBossShip._fire_gas_cloud``
    into a caller-provided list; the cone state is carried on the
    boss itself (``_cone_active`` / ``_cone_timer``) and drawn +
    damage-tested by ``update_logic`` each frame.
    """

    def __init__(
        self,
        texture: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float,
        y: float,
        target_x: float,
        target_y: float,
    ) -> None:
        super().__init__(texture, laser_tex, x, y, target_x, target_y)

        # Gas cloud cooldown — staggered from the cone so both don't
        # fire on the same tick.
        self._gas_cd: float = 2.0
        # Gas cone state.
        self._cone_cd: float = NEBULA_BOSS_CONE_COOLDOWN
        self._cone_active: bool = False
        self._cone_timer: float = 0.0
        self._cone_dir_x: float = 0.0
        self._cone_dir_y: float = 0.0

    # Override weapon firing so that in addition to the parent cannon
    # + spread shot, the Nebula boss also queues up gas clouds and
    # can open a cone AoE when its cone cooldown expires and the
    # player is inside range.
    def _try_fire_weapons(self, dist_player: float) -> list:
        """Fire cannon + spread (via super) + optionally queue a gas
        cloud projectile.  Returns the list of projectiles the parent
        would have returned, PLUS any gas clouds this frame."""
        result = super()._try_fire_weapons(dist_player)
        # Gas cloud cooldown is independent of the parent's weapons;
        # the actual cooldown tick + attack trigger runs in
        # ``tick_nebula`` so the return path stays compatible with
        # ``update_boss``.
        return result

    def tick_nebula(
        self,
        dt: float,
        player_x: float,
        player_y: float,
    ) -> Optional[GasCloudProjectile]:
        """Per-frame hook called AFTER ``update_boss``.  Advances the
        gas cloud + cone cooldowns and returns a freshly-fired
        ``GasCloudProjectile`` when the cooldown elapses and the
        player is in aggro range.

        The cone is opened by flipping ``_cone_active = True`` and
        populating the direction — ``update_logic.update_nebula_boss``
        owns the damage tick + draw.
        """
        # Decay cooldowns.
        self._gas_cd = max(0.0, self._gas_cd - dt)
        self._cone_cd = max(0.0, self._cone_cd - dt)
        # Cone state timer.
        if self._cone_active:
            self._cone_timer -= dt
            if self._cone_timer <= 0.0:
                self._cone_active = False
                self._cone_cd = NEBULA_BOSS_CONE_COOLDOWN

        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        # Gas cloud fire — ranged attack (same engagement range as
        # the parent cannon).
        if (self._gas_cd <= 0.0 and dist <= BOSS_DETECT_RANGE
                and not self._charging):
            self._gas_cd = NEBULA_BOSS_GAS_COOLDOWN
            return GasCloudProjectile(
                self.center_x, self.center_y,
                self._heading,
                damage=_gas_damage_for_phase(self._phase),
            )

        # Cone fire — short-range, only while the player is within
        # the cone's own reach.
        if (not self._cone_active and self._cone_cd <= 0.0
                and dist <= NEBULA_BOSS_CONE_RANGE + self.radius
                and not self._charging):
            self._cone_active = True
            self._cone_timer = NEBULA_BOSS_CONE_DURATION
            if dist > 1.0:
                self._cone_dir_x = dx / dist
                self._cone_dir_y = dy / dist
            else:
                rad = math.radians(self._heading)
                self._cone_dir_x = math.sin(rad)
                self._cone_dir_y = math.cos(rad)

        return None

    def cone_contains_point(self, px: float, py: float) -> bool:
        """True when (px, py) is inside the currently-active cone.

        The cone is a triangle: apex at the boss centre, extending
        ``NEBULA_BOSS_CONE_RANGE`` along ``(_cone_dir_x, _cone_dir_y)``,
        widening to ``NEBULA_BOSS_CONE_WIDTH`` at the far end.  We
        check (1) point projects forward onto the axis within range,
        and (2) perpendicular distance from axis stays inside the
        linearly-growing half-width."""
        if not self._cone_active:
            return False
        dx = px - self.center_x
        dy = py - self.center_y
        # Forward distance along the cone axis.
        forward = dx * self._cone_dir_x + dy * self._cone_dir_y
        if forward < 0.0 or forward > NEBULA_BOSS_CONE_RANGE:
            return False
        # Perpendicular distance.
        perp_x = dx - forward * self._cone_dir_x
        perp_y = dy - forward * self._cone_dir_y
        perp = math.hypot(perp_x, perp_y)
        # Cone half-width grows linearly from 0 at apex to
        # (WIDTH / 2) at far end.
        half_width = (NEBULA_BOSS_CONE_WIDTH / 2.0) * (
            forward / NEBULA_BOSS_CONE_RANGE)
        return perp <= half_width


def _gas_damage_for_phase(phase: int) -> float:
    """Mirror the parent boss's phase-scaled damage: Phase 3
    enraged variants hit harder."""
    from constants import NEBULA_BOSS_GAS_DAMAGE
    if phase == _PHASE3:
        return NEBULA_BOSS_GAS_DAMAGE * 1.5
    return NEBULA_BOSS_GAS_DAMAGE
