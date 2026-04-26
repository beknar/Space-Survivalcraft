"""Maze spawner — stationary turret at the centre of each Star Maze room.

Owns the spawn cadence (one ``MazeAlien`` every 30 s, cap 20 alive),
its own laser cooldown, HP + shield bars, and the "killed & stays
dead" flag.  Collision damage + kill rewards go through the same
pipeline as other alien-like entities; the Star Maze zone owns the
sprite list and drives ``update_spawner`` per tick.
"""
from __future__ import annotations

import arcade
import math
import random

from constants import (
    MAZE_SPAWNER_HP, MAZE_SPAWNER_SHIELD,
    MAZE_SPAWNER_LASER_DAMAGE, MAZE_SPAWNER_LASER_RANGE,
    MAZE_SPAWNER_LASER_SPEED, MAZE_SPAWNER_FIRE_CD,
    MAZE_SPAWNER_DETECT_DIST, MAZE_SPAWNER_MAX_ALIVE,
    MAZE_SPAWNER_SPAWN_INTERVAL, MAZE_SPAWNER_RADIUS,
    MAZE_SPAWNER_RESPAWN_INTERVAL,
    MAZE_SPAWNER_SPRITE_PNG, MAZE_SPAWNER_SCALE,
)
from sprites.projectile import Projectile


_SPRITE_TEX_CACHE: dict[str, arcade.Texture] = {}


def _load_sprite(path: str = MAZE_SPAWNER_SPRITE_PNG) -> arcade.Texture:
    tex = _SPRITE_TEX_CACHE.get(path)
    if tex is None:
        tex = arcade.load_texture(path)
        _SPRITE_TEX_CACHE[path] = tex
    return tex


class MazeSpawner(arcade.Sprite):
    """Stationary spawner + laser turret.

    Kill rewards (1000 iron, 100 XP) are applied by the collision
    handler that detects ``self.hp <= 0``; this class is not
    responsible for awarding them.  After death, ``_respawn_cd``
    ticks down; when it hits zero HP + shields refill, ``killed``
    flips back to False, and the spawner resumes its normal 30 s
    spawn cadence.  Alive children (if any) survive the death +
    resurrection so the cap stays accurate.
    """

    def __init__(self, x: float, y: float) -> None:
        super().__init__(
            path_or_texture=_load_sprite(),
            scale=MAZE_SPAWNER_SCALE,
        )
        self.center_x = x
        self.center_y = y
        self.hp: int = MAZE_SPAWNER_HP
        self.max_hp: int = MAZE_SPAWNER_HP
        self.shields: int = MAZE_SPAWNER_SHIELD
        self.max_shields: int = MAZE_SPAWNER_SHIELD
        self.radius: float = MAZE_SPAWNER_RADIUS
        # Rough collision proxy — spawner isn't circle-symmetric but
        # a single radius read keeps it consistent with the boss /
        # alien hit-test contract.
        self.width = MAZE_SPAWNER_RADIUS * 2.0
        self.height = MAZE_SPAWNER_RADIUS * 2.0

        self._fire_cd: float = random.uniform(0.0, MAZE_SPAWNER_FIRE_CD)
        # Stagger the very first spawn so 81 spawners don't all fire
        # their first alien on the same tick when the zone opens.
        self._spawn_cd: float = random.uniform(0.0, MAZE_SPAWNER_SPAWN_INTERVAL)
        self.killed: bool = False
        # Ticks down while ``killed`` is True; at zero the spawner
        # resurrects with full HP + shields.
        self._respawn_cd: float = 0.0
        # Latch flipped True the frame the spawner appears (initial
        # construction OR respawn after kill).  The zone reads this
        # flag in ``_update_spawners`` to drop 10 fresh maze aliens
        # around it (capped by MAZE_SPAWNER_MAX_ALIVE), then clears
        # the flag so subsequent ticks don't re-spawn the entourage.
        self.just_respawned: bool = True
        self._hit_timer: float = 0.0
        # Track how many MazeAliens this spawner has currently alive
        # so the zone can enforce the cap without walking every alien
        # each tick.  The zone decrements this when one of ours dies.
        self.alive_children: int = 0
        # Unique per-zone id so save/load can link children back.
        self.uid: int = 0

    def take_damage(self, amount: int) -> None:
        if self.killed:
            return
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hit_timer = 0.15
        if self.hp <= 0:
            self.killed = True
            self._respawn_cd = MAZE_SPAWNER_RESPAWN_INTERVAL
            self.visible = False

    def update_spawner(
        self,
        dt: float,
        player_x: float,
        player_y: float,
        laser_tex: arcade.Texture,
    ) -> tuple[list[Projectile], bool]:
        """Advance cooldowns + return ``(fired_projectiles, should_spawn)``.

        The zone layer handles the actual ``MazeAlien`` spawn so it
        can place the new alien inside the room's free interior and
        wire up the patrol-home + walls; returning a bool keeps this
        class free of zone coupling.
        """
        fired: list[Projectile] = []
        should_spawn = False
        if self.killed:
            # Tick the respawn timer.  When it hits zero the spawner
            # comes back to full HP + shields and resumes the spawn
            # cadence; alive children from before death carry over.
            self._respawn_cd -= dt
            if self._respawn_cd <= 0.0:
                self.killed = False
                self.hp = MAZE_SPAWNER_HP
                self.shields = MAZE_SPAWNER_SHIELD
                self._respawn_cd = 0.0
                # Reset spawn cadence to the full interval so the
                # post-respawn spawn doesn't fire immediately.
                self._spawn_cd = MAZE_SPAWNER_SPAWN_INTERVAL
                self.visible = True
                # Signal the zone to repopulate the entourage.
                self.just_respawned = True
            return fired, should_spawn

        # Visual hit tint.
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = ((255, 80, 80, 255) if self._hit_timer > 0.0
                          else (255, 255, 255, 255))

        # Laser fire — only when the player is inside detect range AND
        # inside the laser's effective range (spec lists both; detect
        # is the aggro threshold, range is the projectile max-distance).
        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if (dist <= MAZE_SPAWNER_DETECT_DIST
                and dist <= MAZE_SPAWNER_LASER_RANGE
                and self._fire_cd <= 0.0):
            self._fire_cd = MAZE_SPAWNER_FIRE_CD
            # Aim directly at the player — no lead-shot.  Heading uses
            # the same (sin, cos) convention as the player ship, so the
            # projectile flies forward on launch.
            heading = math.degrees(math.atan2(dx, dy)) % 360.0
            fired.append(Projectile(
                laser_tex,
                self.center_x, self.center_y,
                heading,
                MAZE_SPAWNER_LASER_SPEED, MAZE_SPAWNER_LASER_RANGE,
                scale=0.5,
                damage=MAZE_SPAWNER_LASER_DAMAGE,
            ))

        # Spawn cadence — tick down regardless of player distance.  A
        # room the player has scouted should still be populated when
        # they return to it.
        self._spawn_cd -= dt
        if (self._spawn_cd <= 0.0
                and self.alive_children < MAZE_SPAWNER_MAX_ALIVE):
            self._spawn_cd = MAZE_SPAWNER_SPAWN_INTERVAL
            should_spawn = True

        return fired, should_spawn

    # ── Save/load support ───────────────────────────────────────────

    def to_save_data(self) -> dict:
        return {
            "x": float(self.center_x),
            "y": float(self.center_y),
            "hp": int(self.hp),
            "shields": int(self.shields),
            "killed": bool(self.killed),
            "fire_cd": float(self._fire_cd),
            "spawn_cd": float(self._spawn_cd),
            "respawn_cd": float(self._respawn_cd),
            "alive_children": int(self.alive_children),
            "uid": int(self.uid),
        }

    def from_save_data(self, data: dict) -> None:
        # Position is intentionally NOT restored from the save: it's
        # derived deterministically from the world seed by
        # ``zones.maze_geometry.generate_maze`` (always the centre of
        # the centre room).  Saves predating layout/scale tweaks
        # carried stale x/y that placed the spawner in a wall after
        # restore — see issue noted 2026-04-23.  Keep saving + reading
        # the keys for save-format stability but drop the assignment.
        self.hp = int(data.get("hp", self.hp))
        self.shields = int(data.get("shields", self.shields))
        self.killed = bool(data.get("killed", False))
        self.visible = not self.killed
        self._fire_cd = float(data.get("fire_cd", self._fire_cd))
        self._spawn_cd = float(data.get("spawn_cd", self._spawn_cd))
        self._respawn_cd = float(data.get("respawn_cd", 0.0))
        self.alive_children = int(data.get("alive_children", 0))
        self.uid = int(data.get("uid", 0))
        # Restored spawners didn't "just respawn" — they're being
        # rehydrated from disk.  Clearing this flag prevents a phantom
        # 10-alien repopulation the first frame after load.
        self.just_respawned = False
