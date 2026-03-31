"""Character progression data and XP/level logic."""
from __future__ import annotations

# XP thresholds for each level (same for all characters)
_XP_THRESHOLDS = [0, 100, 300, 600, 1000]

# Character definitions: name → class, level benefits
CHARACTERS: dict[str, dict] = {
    "Debra": {
        "class": "Miner",
        "benefits": [
            "+10 iron from asteroids",
            "+10 iron from enemies",
            "+15 iron from asteroids",
            "+15 iron from enemies",
            "+20 iron from all",
        ],
    },
    "Ellie": {
        "class": "Fighter",
        "benefits": [
            "+10 laser damage",
            "-0.10s laser cooldown",
            "+50 px/s laser speed",
            "+100 px laser range",
            "+15 laser damage",
        ],
    },
    "Tara": {
        "class": "Builder",
        "benefits": [
            "+25% blueprint drop chance",
            "-10% build iron cost",
            "-10% craft iron cost",
            "-20% build iron cost",
            "+10% station HP",
        ],
    },
}


def level_for_xp(xp: int) -> int:
    """Return the character level (1-5) for the given XP total."""
    lvl = 1
    for i, threshold in enumerate(_XP_THRESHOLDS):
        if xp >= threshold:
            lvl = i + 1
    return min(lvl, 5)


def xp_for_next_level(xp: int) -> int | None:
    """Return XP needed for the next level, or None if max level."""
    lvl = level_for_xp(xp)
    if lvl >= 5:
        return None
    return _XP_THRESHOLDS[lvl]


def bonus_iron_asteroid(char_name: str, level: int) -> int:
    """Extra iron from destroying an asteroid (Debra only)."""
    if char_name != "Debra":
        return 0
    if level >= 5:
        return 20
    if level >= 3:
        return 15
    if level >= 1:
        return 10
    return 0


def bonus_iron_enemy(char_name: str, level: int) -> int:
    """Extra iron from destroying an enemy ship (Debra only)."""
    if char_name != "Debra":
        return 0
    if level >= 5:
        return 20
    if level >= 4:
        return 15
    if level >= 2:
        return 10
    return 0


def laser_damage_bonus(char_name: str, level: int) -> float:
    """Extra damage for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    bonus = 0.0
    if level >= 1:
        bonus += 10.0
    if level >= 5:
        bonus += 15.0
    return bonus


def laser_cooldown_bonus(char_name: str, level: int) -> float:
    """Cooldown reduction for the basic laser in seconds (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    if level >= 2:
        return 0.10
    return 0.0


def laser_speed_bonus(char_name: str, level: int) -> float:
    """Extra projectile speed for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    if level >= 3:
        return 50.0
    return 0.0


def laser_range_bonus(char_name: str, level: int) -> float:
    """Extra max range for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    if level >= 4:
        return 100.0
    return 0.0


def blueprint_drop_bonus(char_name: str, level: int) -> float:
    """Additional blueprint drop chance (Tara only, additive)."""
    if char_name != "Tara":
        return 0.0
    if level >= 1:
        return 0.25
    return 0.0


def build_cost_multiplier(char_name: str, level: int) -> float:
    """Iron cost multiplier for building station parts (Tara only)."""
    if char_name != "Tara":
        return 1.0
    mult = 1.0
    if level >= 2:
        mult -= 0.10
    if level >= 4:
        mult -= 0.20
    return max(0.1, mult)


def craft_cost_multiplier(char_name: str, level: int) -> float:
    """Iron cost multiplier for crafting items (Tara only)."""
    if char_name != "Tara":
        return 1.0
    if level >= 3:
        return 0.90
    return 1.0


def station_hp_multiplier(char_name: str, level: int) -> float:
    """HP multiplier for all station buildings (Tara only)."""
    if char_name != "Tara":
        return 1.0
    if level >= 5:
        return 1.10
    return 1.0
