"""Character progression data and XP/level logic."""
from __future__ import annotations

# XP thresholds for each level (same for all characters)
_XP_THRESHOLDS = [0, 100, 300, 600, 1000, 2500, 3600, 4700, 5800, 7000]
MAX_LEVEL = 10
MAX_XP = _XP_THRESHOLDS[-1]

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
            "+10 copper from copper asteroids",
            "+10 copper from new enemies",
            "+15 copper from copper asteroids",
            "+15 copper from new enemies",
            "+20 copper from all sources",
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
            "+20 laser damage",
            "-0.20s total laser cooldown",
            "+75 px/s laser speed",
            "+150 px laser range",
            "+25 laser damage",
        ],
    },
    "Tara": {
        "class": "Builder",
        "benefits": [
            "+25% blueprint drop chance",
            "-10% iron build cost",
            "-10% iron craft cost",
            "-20% iron build cost",
            "+10% station HP",
            "+50% blueprint drop chance",
            "-10% copper build cost",
            "-10% copper craft cost",
            "-20% copper build cost",
            "+20% station HP",
        ],
    },
}


def level_for_xp(xp: int) -> int:
    """Return the character level (1-10) for the given XP total."""
    lvl = 1
    for i, threshold in enumerate(_XP_THRESHOLDS):
        if xp >= threshold:
            lvl = i + 1
    return min(lvl, MAX_LEVEL)


def xp_for_next_level(xp: int) -> int | None:
    """Return XP needed for the next level, or None if max level."""
    lvl = level_for_xp(xp)
    if lvl >= MAX_LEVEL:
        return None
    return _XP_THRESHOLDS[lvl]


def bonus_iron_asteroid(char_name: str, level: int) -> int:
    """Extra iron from destroying an asteroid (Debra only)."""
    if char_name != "Debra":
        return 0
    bonus = 0
    if level >= 1:
        bonus = 10
    if level >= 3:
        bonus = 15
    if level >= 5:
        bonus = 20
    return bonus


def bonus_iron_enemy(char_name: str, level: int) -> int:
    """Extra iron from destroying an enemy ship (Debra only)."""
    if char_name != "Debra":
        return 0
    bonus = 0
    if level >= 2:
        bonus = 10
    if level >= 4:
        bonus = 15
    if level >= 5:
        bonus = 20
    return bonus


def bonus_copper_asteroid(char_name: str, level: int) -> int:
    """Extra copper from destroying a copper asteroid (Debra only)."""
    if char_name != "Debra":
        return 0
    bonus = 0
    if level >= 6:
        bonus = 10
    if level >= 8:
        bonus = 15
    if level >= 10:
        bonus = 20
    return bonus


def bonus_copper_enemy(char_name: str, level: int) -> int:
    """Extra copper from destroying a Zone 2 enemy (Debra only)."""
    if char_name != "Debra":
        return 0
    bonus = 0
    if level >= 7:
        bonus = 10
    if level >= 9:
        bonus = 15
    if level >= 10:
        bonus = 20
    return bonus


def laser_damage_bonus(char_name: str, level: int) -> float:
    """Extra damage for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    bonus = 0.0
    if level >= 1:
        bonus += 10.0
    if level >= 5:
        bonus += 15.0
    if level >= 6:
        bonus += 20.0
    if level >= 10:
        bonus += 25.0
    return bonus


def laser_cooldown_bonus(char_name: str, level: int) -> float:
    """Cooldown reduction for the basic laser in seconds (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    bonus = 0.0
    if level >= 2:
        bonus += 0.10
    if level >= 7:
        bonus += 0.20
    return bonus


def laser_speed_bonus(char_name: str, level: int) -> float:
    """Extra projectile speed for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    bonus = 0.0
    if level >= 3:
        bonus += 50.0
    if level >= 8:
        bonus += 75.0
    return bonus


def laser_range_bonus(char_name: str, level: int) -> float:
    """Extra max range for the basic laser (Ellie only)."""
    if char_name != "Ellie":
        return 0.0
    bonus = 0.0
    if level >= 4:
        bonus += 100.0
    if level >= 9:
        bonus += 150.0
    return bonus


def blueprint_drop_bonus(char_name: str, level: int) -> float:
    """Additional blueprint drop chance (Tara only, additive)."""
    if char_name != "Tara":
        return 0.0
    bonus = 0.0
    if level >= 1:
        bonus += 0.25
    if level >= 6:
        bonus += 0.50
    return bonus


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


def build_cost_copper_multiplier(char_name: str, level: int) -> float:
    """Copper cost multiplier for building station parts (Tara only)."""
    if char_name != "Tara":
        return 1.0
    mult = 1.0
    if level >= 7:
        mult -= 0.10
    if level >= 9:
        mult -= 0.20
    return max(0.1, mult)


def craft_cost_multiplier(char_name: str, level: int) -> float:
    """Iron cost multiplier for crafting items (Tara only)."""
    if char_name != "Tara":
        return 1.0
    mult = 1.0
    if level >= 3:
        mult -= 0.10
    return max(0.1, mult)


def craft_cost_copper_multiplier(char_name: str, level: int) -> float:
    """Copper cost multiplier for crafting items (Tara only)."""
    if char_name != "Tara":
        return 1.0
    mult = 1.0
    if level >= 8:
        mult -= 0.10
    return max(0.1, mult)


def station_hp_multiplier(char_name: str, level: int) -> float:
    """HP multiplier for all station buildings (Tara only)."""
    if char_name != "Tara":
        return 1.0
    mult = 1.0
    if level >= 5:
        mult += 0.10
    if level >= 10:
        mult += 0.20
    return mult
