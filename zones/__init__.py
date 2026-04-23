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
    # Post-Nebula-boss warp variants: same four themes as the Zone 1
    # variants but with a 2× danger scalar applied.  These route the
    # player OUT to the Star Maze on exit rather than back to Zone 2.
    NEBULA_WARP_METEOR = auto()
    NEBULA_WARP_LIGHTNING = auto()
    NEBULA_WARP_GAS = auto()
    NEBULA_WARP_ENEMY = auto()
    # The Star Maze itself — a full-size zone filled with dungeon-wall
    # rooms, each guarded by a MazeSpawner.  Reached via the Nebula
    # corner wormholes.
    STAR_MAZE = auto()
    # Star Maze's own corner wormholes chain onward to deeper warp
    # variants that return the player to the Star Maze (same pattern
    # as Zone 2's existing warp access).
    MAZE_WARP_METEOR = auto()
    MAZE_WARP_LIGHTNING = auto()
    MAZE_WARP_GAS = auto()
    MAZE_WARP_ENEMY = auto()


# Zone-id groupings used throughout the code for routing decisions.
NEBULA_WARP_ZONES = frozenset({
    ZoneID.NEBULA_WARP_METEOR,
    ZoneID.NEBULA_WARP_LIGHTNING,
    ZoneID.NEBULA_WARP_GAS,
    ZoneID.NEBULA_WARP_ENEMY,
})
MAZE_WARP_ZONES = frozenset({
    ZoneID.MAZE_WARP_METEOR,
    ZoneID.MAZE_WARP_LIGHTNING,
    ZoneID.MAZE_WARP_GAS,
    ZoneID.MAZE_WARP_ENEMY,
})
# Every warp-zone id, whether launched from Zone 1, Zone 2, or the
# Star Maze.  Used for "am I currently in a warp zone" checks.
ALL_WARP_ZONES = frozenset({
    ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
    ZoneID.WARP_GAS, ZoneID.WARP_ENEMY,
}) | NEBULA_WARP_ZONES | MAZE_WARP_ZONES


# Human-readable theme names, used by the welcome-message helper.
_WARP_ZONE_THEMES = {
    "METEOR": "Meteor Warp Zone",
    "LIGHTNING": "Lightning Warp Zone",
    "GAS": "Gas Warp Zone",
    "ENEMY": "Enemy Warp Zone",
}


def welcome_message_for(zone_id: "ZoneID") -> str | None:
    """Return the on-arrival flash text for ``zone_id`` — ``None``
    means no welcome (fall back to whatever message the caller
    wants, or silence).

    Star Maze + any warp-zone variant get a "Welcome to ..." line;
    MAIN and ZONE2 return ``None`` so the caller can decide between
    "Returning through wormhole..." and silence based on context.
    """
    if zone_id is ZoneID.STAR_MAZE:
        return "Welcome to the Star Maze"
    if zone_id in ALL_WARP_ZONES:
        # Theme suffix is the last underscore-separated chunk of the
        # enum name (WARP_METEOR, NEBULA_WARP_METEOR, MAZE_WARP_METEOR
        # all resolve to "METEOR").
        theme = zone_id.name.rsplit("_", 1)[-1]
        friendly = _WARP_ZONE_THEMES.get(theme, theme.title() + " Warp Zone")
        return f"Welcome to the {friendly}"
    return None


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

    def background_update(self, gv: GameView, dt: float) -> None:
        """Tick this zone while the player is in a different zone.

        Only called when 'Simulate All Zones' is enabled. Runs cheap
        updates (respawns, timers) without player interaction or drawing.
        """

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

    # Post-Nebula-boss + post-Star-Maze warp variants reuse the same
    # four warp-zone classes as Zone 1's access points; the difficulty
    # scalar and the zone they route back to on exit are set inside
    # ``setup()`` based on the actual ``zone_id`` of this instance.
    _MAP = {
        ZoneID.MAIN: MainZone,
        ZoneID.WARP_METEOR: MeteorWarpZone,
        ZoneID.WARP_LIGHTNING: LightningWarpZone,
        ZoneID.WARP_GAS: GasCloudWarpZone,
        ZoneID.WARP_ENEMY: EnemySpawnerWarpZone,
        ZoneID.ZONE2: Zone2,
        ZoneID.NEBULA_WARP_METEOR: MeteorWarpZone,
        ZoneID.NEBULA_WARP_LIGHTNING: LightningWarpZone,
        ZoneID.NEBULA_WARP_GAS: GasCloudWarpZone,
        ZoneID.NEBULA_WARP_ENEMY: EnemySpawnerWarpZone,
        ZoneID.MAZE_WARP_METEOR: MeteorWarpZone,
        ZoneID.MAZE_WARP_LIGHTNING: LightningWarpZone,
        ZoneID.MAZE_WARP_GAS: GasCloudWarpZone,
        ZoneID.MAZE_WARP_ENEMY: EnemySpawnerWarpZone,
    }
    if zone_id is ZoneID.STAR_MAZE:
        # Late-imported so the module-level import graph of ``zones``
        # stays cycle-free.  StarMazeZone depends on sprite + combat
        # modules that in turn import from ``zones``.
        from zones.star_maze import StarMazeZone
        instance: ZoneState = StarMazeZone()
    else:
        instance = _MAP[zone_id]()
    # Tag reused warp-zone instances so their setup() can branch on
    # the actual id rather than on class identity (MeteorWarpZone is
    # used by three different ZoneIDs).
    instance.zone_id = zone_id
    return instance
