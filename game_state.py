"""GameState — groups game state fields that were spread across GameView."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import arcade
    from sprites.boss import BossAlienShip
    from sprites.wormhole import Wormhole


@dataclass
class BossState:
    """Boss encounter tracking."""
    entity: Optional[BossAlienShip] = None
    spawned: bool = False
    defeated: bool = False
    announce_timer: float = 0.0


@dataclass
class FogState:
    """Fog of war grid and reveal counter."""
    grid: list[list[bool]] = field(default_factory=list)
    revealed: int = 0

    @staticmethod
    def create(width: int, height: int) -> FogState:
        grid = [[False] * width for _ in range(height)]
        return FogState(grid=grid, revealed=0)


@dataclass
class CombatTimers:
    """Shared combat-related timers and cooldowns."""
    shake_timer: float = 0.0
    shake_amp: float = 0.0
    collision_cd: float = 0.0
    broadside_cd: float = 0.0
    enhancer_angle: float = 0.0
    rear_turret_cd: float = 0.0
    repair_acc: float = 0.0
    building_repair_acc: float = 0.0
    asteroid_respawn_timer: float = 0.0
    alien_respawn_timer: float = 0.0


@dataclass
class AbilityState:
    """Special ability meter and death blossom state."""
    meter: float = 100.0
    meter_max: float = 100.0
    misty_step_cd: float = 0.0
    death_blossom_active: bool = False
    death_blossom_timer: float = 0.0
    death_blossom_missiles_left: int = 0


@dataclass
class EffectState:
    """Visual effect state (glow, flash)."""
    use_glow: tuple[int, int, int, int] = (0, 0, 0, 0)
    use_glow_timer: float = 0.0
    flash_msg: str = ""
    flash_timer: float = 0.0
