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
    LANDING_TLASER_PNG, LANDING_XBLAST_PNG, LANDING_DOUBLE_LASER_PNG,
    LANDING_SKY_WORM_BODY_PNG, LANDING_CLOUD_DRONE_BODY_PNG,
    LANDING_THUNDER_WORM_BODY_PNG,
    LANDING_LASER_RANGE, LANDING_LASER_SPEED, LANDING_ENEMY_SCALE,
    LANDING_ENEMY_FIRE_CD, LANDING_ENEMY_BODY_RADIUS,
    LANDING_SKY_WORM_COUNT, LANDING_SKY_WORM_HP, LANDING_SKY_WORM_SHIELD,
    LANDING_SKY_WORM_SHIELD_CHANCE, LANDING_SKY_WORM_SPEED,
    LANDING_SKY_WORM_DAMAGE, LANDING_SKY_WORM_DETECT, LANDING_SKY_WORM_XP,
    LANDING_CLOUD_DRONE_COUNT, LANDING_CLOUD_DRONE_HP,
    LANDING_CLOUD_DRONE_SHIELD, LANDING_CLOUD_DRONE_SHIELD_CHANCE,
    LANDING_CLOUD_DRONE_SPEED, LANDING_CLOUD_DRONE_DAMAGE,
    LANDING_CLOUD_DRONE_DETECT, LANDING_CLOUD_DRONE_XP,
    LANDING_THUNDER_WORM_COUNT, LANDING_THUNDER_WORM_HP,
    LANDING_THUNDER_WORM_SHIELD, LANDING_THUNDER_WORM_SHIELD_CHANCE,
    LANDING_THUNDER_WORM_SPEED, LANDING_THUNDER_WORM_DAMAGE,
    LANDING_THUNDER_WORM_DETECT, LANDING_THUNDER_WORM_XP,
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


@dataclass(frozen=True)
class LandingEnemySpec:
    """One airborne enemy type for the Planetary Landing Scene
    (docs/planets.md section 5).  ``shots`` is how many projectiles a
    single fire event emits (Thunder Worm's Double Laser = 2)."""
    name: str
    count: int
    hp: int
    shield: int
    shield_chance: float
    speed: float
    damage: float
    detect: float
    xp: int
    shots: int
    body_png: str
    laser_png: str
    scale: float
    radius: float
    fire_cd: float
    laser_range: float
    laser_speed: float


SKY_WORM = LandingEnemySpec(
    name="Sky Worm",
    count=LANDING_SKY_WORM_COUNT, hp=LANDING_SKY_WORM_HP,
    shield=LANDING_SKY_WORM_SHIELD,
    shield_chance=LANDING_SKY_WORM_SHIELD_CHANCE,
    speed=LANDING_SKY_WORM_SPEED, damage=LANDING_SKY_WORM_DAMAGE,
    detect=LANDING_SKY_WORM_DETECT, xp=LANDING_SKY_WORM_XP, shots=1,
    body_png=LANDING_SKY_WORM_BODY_PNG, laser_png=LANDING_TLASER_PNG,
    scale=LANDING_ENEMY_SCALE, radius=LANDING_ENEMY_BODY_RADIUS,
    fire_cd=LANDING_ENEMY_FIRE_CD,
    laser_range=LANDING_LASER_RANGE, laser_speed=LANDING_LASER_SPEED,
)

CLOUD_DRONE = LandingEnemySpec(
    name="Cloud Drone",
    count=LANDING_CLOUD_DRONE_COUNT, hp=LANDING_CLOUD_DRONE_HP,
    shield=LANDING_CLOUD_DRONE_SHIELD,
    shield_chance=LANDING_CLOUD_DRONE_SHIELD_CHANCE,
    speed=LANDING_CLOUD_DRONE_SPEED, damage=LANDING_CLOUD_DRONE_DAMAGE,
    detect=LANDING_CLOUD_DRONE_DETECT, xp=LANDING_CLOUD_DRONE_XP, shots=1,
    body_png=LANDING_CLOUD_DRONE_BODY_PNG, laser_png=LANDING_XBLAST_PNG,
    scale=LANDING_ENEMY_SCALE, radius=LANDING_ENEMY_BODY_RADIUS,
    fire_cd=LANDING_ENEMY_FIRE_CD,
    laser_range=LANDING_LASER_RANGE, laser_speed=LANDING_LASER_SPEED,
)

THUNDER_WORM = LandingEnemySpec(
    name="Thunder Worm",
    count=LANDING_THUNDER_WORM_COUNT, hp=LANDING_THUNDER_WORM_HP,
    shield=LANDING_THUNDER_WORM_SHIELD,
    shield_chance=LANDING_THUNDER_WORM_SHIELD_CHANCE,
    speed=LANDING_THUNDER_WORM_SPEED, damage=LANDING_THUNDER_WORM_DAMAGE,
    detect=LANDING_THUNDER_WORM_DETECT, xp=LANDING_THUNDER_WORM_XP, shots=2,
    body_png=LANDING_THUNDER_WORM_BODY_PNG,
    laser_png=LANDING_DOUBLE_LASER_PNG,
    scale=LANDING_ENEMY_SCALE, radius=LANDING_ENEMY_BODY_RADIUS,
    fire_cd=LANDING_ENEMY_FIRE_CD,
    laser_range=LANDING_LASER_RANGE, laser_speed=LANDING_LASER_SPEED,
)

# All three landing-scene enemy types, in spawn order.
LANDING_ENEMIES: tuple[LandingEnemySpec, ...] = (
    SKY_WORM, CLOUD_DRONE, THUNDER_WORM,
)
