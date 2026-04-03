"""Zone state machine for multi-zone gameplay."""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView


class ZoneID(Enum):
    MAIN = auto()
    WARP_METEOR = auto()
    WARP_LIGHTNING = auto()
    WARP_GAS = auto()
    WARP_ENEMY = auto()
    ZONE2 = auto()


class ZoneState:
    """Base class for zone-specific logic.

    Each zone manages its own entities (asteroids, aliens, hazards) while
    the player, inventory, HUD, weapons, and shields persist across zones.
    """
    zone_id: ZoneID
    world_width: int = 6400
    world_height: int = 6400

    def setup(self, gv: GameView) -> None:
        """Called when entering this zone. Populate zone-specific state."""

    def teardown(self, gv: GameView) -> None:
        """Called when leaving this zone. Stash/clear zone-specific state."""

    def update(self, gv: GameView, dt: float) -> None:
        """Per-frame update for zone-specific entities."""

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        """Draw zone-specific world-space entities."""

    def draw_ui(self, gv: GameView) -> None:
        """Draw zone-specific UI overlays (optional)."""

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        """Where to place the player when entering this zone."""
        return self.world_width / 2, self.world_height / 2

    def to_save_data(self) -> dict:
        """Serialize zone-specific state."""
        return {}

    def from_save_data(self, data: dict, gv: GameView) -> None:
        """Restore zone-specific state."""


def create_zone(zone_id: ZoneID) -> ZoneState:
    """Factory: create a ZoneState instance for the given ID."""
    from zones.zone1_main import MainZone
    from zones.zone_warp_meteor import MeteorWarpZone
    from zones.zone_warp_lightning import LightningWarpZone
    from zones.zone_warp_gas import GasCloudWarpZone
    from zones.zone_warp_enemy import EnemySpawnerWarpZone
    from zones.zone2 import Zone2

    _MAP = {
        ZoneID.MAIN: MainZone,
        ZoneID.WARP_METEOR: MeteorWarpZone,
        ZoneID.WARP_LIGHTNING: LightningWarpZone,
        ZoneID.WARP_GAS: GasCloudWarpZone,
        ZoneID.WARP_ENEMY: EnemySpawnerWarpZone,
        ZoneID.ZONE2: Zone2,
    }
    return _MAP[zone_id]()
