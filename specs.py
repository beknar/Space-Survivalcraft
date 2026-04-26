"""Bundled stat specs for drones + late-game enemies.

Each spec is a frozen dataclass that pulls its values from
``constants.py``.  Use these from new code that wants a single
named bundle instead of ``DRONE_HP`` / ``DRONE_MAX_SPEED`` / etc.
imports — existing call sites continue to read the flat constants
unchanged so this module doesn't force a churn pass.

The point isn't to add a layer of indirection; it's to give
future tuning passes (difficulty modes, item upgrades, etc.) one
place to swap in a different bundle.
"""
from __future__ import annotations

from dataclasses import dataclass

from constants import (
    DRONE_HP, DRONE_MAX_SPEED, DRONE_ROTATE_SPEED,
    DRONE_FOLLOW_DIST, DRONE_ORBIT_SPEED, DRONE_FIRE_COOLDOWN,
    DRONE_DETECT_RANGE, DRONE_LASER_RANGE, DRONE_LASER_SPEED,
    DRONE_SCALE, DRONE_RADIUS,
    MINING_DRONE_SHIELD, MINING_DRONE_LASER_DAMAGE,
    MINING_DRONE_PICKUP_RADIUS, MINING_DRONE_MINING_RANGE,
    COMBAT_DRONE_SHIELD, COMBAT_DRONE_LASER_DAMAGE,
    STALKER_HP, STALKER_SPEED, STALKER_RADIUS, STALKER_COUNT,
    STALKER_DETECT_DIST, STALKER_FIRE_COOLDOWN, STALKER_FIRE_RANGE,
    STALKER_STANDOFF_DIST, STALKER_IRON_DROP, STALKER_XP,
    STALKER_SCALE,
    MAZE_ALIEN_HP_MIN, MAZE_ALIEN_HP_MAX,
    MAZE_ALIEN_LASER_DAMAGE_MIN, MAZE_ALIEN_LASER_DAMAGE_MAX,
    MAZE_ALIEN_SHIELD_CHANCE, MAZE_ALIEN_SHIELD,
    MAZE_ALIEN_SPEED, MAZE_ALIEN_RADIUS,
    MAZE_ALIEN_DETECT_DIST, MAZE_ALIEN_LASER_RANGE,
    MAZE_ALIEN_LASER_SPEED, MAZE_ALIEN_FIRE_CD,
    MAZE_ALIEN_IRON_DROP, MAZE_ALIEN_XP,
)


@dataclass(frozen=True)
class _DroneShared:
    hp: int
    max_speed: float
    rotate_speed: float
    follow_dist: float
    orbit_speed: float
    fire_cooldown: float
    detect_range: float
    laser_range: float
    laser_speed: float
    scale: float
    radius: float


@dataclass(frozen=True)
class MiningDroneSpec(_DroneShared):
    shield: int
    laser_damage: float
    pickup_radius: float
    mining_range: float


@dataclass(frozen=True)
class CombatDroneSpec(_DroneShared):
    shield: int
    laser_damage: float


MINING_DRONE = MiningDroneSpec(
    hp=DRONE_HP, max_speed=DRONE_MAX_SPEED,
    rotate_speed=DRONE_ROTATE_SPEED,
    follow_dist=DRONE_FOLLOW_DIST, orbit_speed=DRONE_ORBIT_SPEED,
    fire_cooldown=DRONE_FIRE_COOLDOWN,
    detect_range=DRONE_DETECT_RANGE,
    laser_range=DRONE_LASER_RANGE, laser_speed=DRONE_LASER_SPEED,
    scale=DRONE_SCALE, radius=DRONE_RADIUS,
    shield=MINING_DRONE_SHIELD,
    laser_damage=MINING_DRONE_LASER_DAMAGE,
    pickup_radius=MINING_DRONE_PICKUP_RADIUS,
    mining_range=MINING_DRONE_MINING_RANGE,
)

COMBAT_DRONE = CombatDroneSpec(
    hp=DRONE_HP, max_speed=DRONE_MAX_SPEED,
    rotate_speed=DRONE_ROTATE_SPEED,
    follow_dist=DRONE_FOLLOW_DIST, orbit_speed=DRONE_ORBIT_SPEED,
    fire_cooldown=DRONE_FIRE_COOLDOWN,
    detect_range=DRONE_DETECT_RANGE,
    laser_range=DRONE_LASER_RANGE, laser_speed=DRONE_LASER_SPEED,
    scale=DRONE_SCALE, radius=DRONE_RADIUS,
    shield=COMBAT_DRONE_SHIELD,
    laser_damage=COMBAT_DRONE_LASER_DAMAGE,
)


@dataclass(frozen=True)
class StalkerSpec:
    count: int
    hp: int
    speed: float
    radius: float
    scale: float
    detect_dist: float
    fire_cooldown: float
    fire_range: float
    standoff_dist: float
    iron_drop: int
    xp: int


STALKER = StalkerSpec(
    count=STALKER_COUNT, hp=STALKER_HP, speed=STALKER_SPEED,
    radius=STALKER_RADIUS, scale=STALKER_SCALE,
    detect_dist=STALKER_DETECT_DIST,
    fire_cooldown=STALKER_FIRE_COOLDOWN,
    fire_range=STALKER_FIRE_RANGE,
    standoff_dist=STALKER_STANDOFF_DIST,
    iron_drop=STALKER_IRON_DROP, xp=STALKER_XP,
)


@dataclass(frozen=True)
class MazeAlienSpec:
    hp_min: int
    hp_max: int
    laser_damage_min: float
    laser_damage_max: float
    shield_chance: float
    shield: int
    speed: float
    radius: float
    detect_dist: float
    laser_range: float
    laser_speed: float
    fire_cd: float
    iron_drop: int
    xp: int


MAZE_ALIEN = MazeAlienSpec(
    hp_min=MAZE_ALIEN_HP_MIN, hp_max=MAZE_ALIEN_HP_MAX,
    laser_damage_min=MAZE_ALIEN_LASER_DAMAGE_MIN,
    laser_damage_max=MAZE_ALIEN_LASER_DAMAGE_MAX,
    shield_chance=MAZE_ALIEN_SHIELD_CHANCE,
    shield=MAZE_ALIEN_SHIELD,
    speed=MAZE_ALIEN_SPEED, radius=MAZE_ALIEN_RADIUS,
    detect_dist=MAZE_ALIEN_DETECT_DIST,
    laser_range=MAZE_ALIEN_LASER_RANGE,
    laser_speed=MAZE_ALIEN_LASER_SPEED,
    fire_cd=MAZE_ALIEN_FIRE_CD,
    iron_drop=MAZE_ALIEN_IRON_DROP, xp=MAZE_ALIEN_XP,
)
