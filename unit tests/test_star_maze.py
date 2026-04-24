"""Fast tests for the Star Maze geometry + zone-state scaffolding.

Everything here is pure-function or construction-only — no arcade
window needed.  Gameplay integration (ticking spawners + aliens with
a real GameView) lives in ``unit tests/integration/``.
"""
from __future__ import annotations

import arcade
import pytest

from constants import (
    STAR_MAZE_WIDTH, STAR_MAZE_HEIGHT,
    STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS, STAR_MAZE_ROOM_SIZE,
    STAR_MAZE_WALL_THICK, STAR_MAZE_SPAN,
    STAR_MAZE_COUNT, STAR_MAZE_CENTERS,
    MAZE_ALIEN_HP, MAZE_ALIEN_SPEED, MAZE_ALIEN_RADIUS,
    MAZE_ALIEN_LASER_DAMAGE, MAZE_ALIEN_LASER_RANGE,
    MAZE_ALIEN_LASER_SPEED, MAZE_ALIEN_FIRE_CD,
    MAZE_ALIEN_DETECT_DIST, MAZE_ALIEN_IRON_DROP, MAZE_ALIEN_XP,
    MAZE_SPAWNER_HP, MAZE_SPAWNER_SHIELD, MAZE_SPAWNER_SPEED,
    MAZE_SPAWNER_LASER_DAMAGE, MAZE_SPAWNER_LASER_RANGE,
    MAZE_SPAWNER_LASER_SPEED, MAZE_SPAWNER_FIRE_CD,
    MAZE_SPAWNER_DETECT_DIST, MAZE_SPAWNER_IRON_DROP, MAZE_SPAWNER_XP,
    MAZE_SPAWNER_MAX_ALIVE, MAZE_SPAWNER_SPAWN_INTERVAL,
    WARP_DANGER_DEFAULT, WARP_DANGER_NEBULA, WARP_DANGER_MAZE,
)
from zones import (
    ZoneID, NEBULA_WARP_ZONES, MAZE_WARP_ZONES, ALL_WARP_ZONES,
)
from zones.maze_geometry import (
    Rect, MazeLayout, generate_maze, generate_all_mazes,
    circle_hits_any_wall, segment_hits_any_wall,
    point_inside_any_room_interior, point_in_rect,
)


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── Spec-pinning: stat values must match user spec exactly ───────

class TestMazeAlienStats:
    def test_hp(self): assert MAZE_ALIEN_HP == 50
    def test_speed(self): assert MAZE_ALIEN_SPEED == 120.0
    def test_radius(self): assert MAZE_ALIEN_RADIUS == 20.0
    def test_laser_damage(self): assert MAZE_ALIEN_LASER_DAMAGE == 10.0
    def test_laser_range(self): assert MAZE_ALIEN_LASER_RANGE == 200.0
    def test_laser_speed(self): assert MAZE_ALIEN_LASER_SPEED == 300.0
    def test_fire_cd(self): assert MAZE_ALIEN_FIRE_CD == 1.5
    def test_detect(self): assert MAZE_ALIEN_DETECT_DIST == 300.0
    def test_iron_drop(self): assert MAZE_ALIEN_IRON_DROP == 10
    def test_xp(self): assert MAZE_ALIEN_XP == 30


class TestMazeSpawnerStats:
    def test_hp(self): assert MAZE_SPAWNER_HP == 100
    def test_shield(self): assert MAZE_SPAWNER_SHIELD == 100
    def test_stationary(self): assert MAZE_SPAWNER_SPEED == 0.0
    def test_laser_damage(self): assert MAZE_SPAWNER_LASER_DAMAGE == 30.0
    def test_laser_range(self): assert MAZE_SPAWNER_LASER_RANGE == 200.0
    def test_laser_speed(self): assert MAZE_SPAWNER_LASER_SPEED == 300.0
    def test_fire_cd(self): assert MAZE_SPAWNER_FIRE_CD == 1.0
    def test_detect(self): assert MAZE_SPAWNER_DETECT_DIST == 300.0
    def test_iron_drop(self): assert MAZE_SPAWNER_IRON_DROP == 1000
    def test_xp(self): assert MAZE_SPAWNER_XP == 100
    def test_cap(self): assert MAZE_SPAWNER_MAX_ALIVE == 20
    def test_cadence(self): assert MAZE_SPAWNER_SPAWN_INTERVAL == 30.0


class TestWarpDangerScalars:
    def test_default_unchanged(self):
        assert WARP_DANGER_DEFAULT == 1.0

    def test_nebula_is_2x_default(self):
        assert WARP_DANGER_NEBULA == WARP_DANGER_DEFAULT * 2.0

    def test_maze_is_2x_default(self):
        assert WARP_DANGER_MAZE == WARP_DANGER_DEFAULT * 2.0


# ── ZoneID enum sanity ────────────────────────────────────────────

class TestZoneIdAdditions:
    def test_star_maze_present(self):
        assert hasattr(ZoneID, "STAR_MAZE")

    def test_four_nebula_warp_variants(self):
        assert len(NEBULA_WARP_ZONES) == 4
        for name in ("NEBULA_WARP_METEOR", "NEBULA_WARP_LIGHTNING",
                     "NEBULA_WARP_GAS", "NEBULA_WARP_ENEMY"):
            assert getattr(ZoneID, name) in NEBULA_WARP_ZONES

    def test_four_maze_warp_variants(self):
        assert len(MAZE_WARP_ZONES) == 4
        for name in ("MAZE_WARP_METEOR", "MAZE_WARP_LIGHTNING",
                     "MAZE_WARP_GAS", "MAZE_WARP_ENEMY"):
            assert getattr(ZoneID, name) in MAZE_WARP_ZONES

    def test_all_warp_zones_superset(self):
        assert NEBULA_WARP_ZONES <= ALL_WARP_ZONES
        assert MAZE_WARP_ZONES <= ALL_WARP_ZONES
        for name in ("WARP_METEOR", "WARP_LIGHTNING",
                     "WARP_GAS", "WARP_ENEMY"):
            assert getattr(ZoneID, name) in ALL_WARP_ZONES


# ── Maze generator ──────────────────────────────────────────────

class TestMazeGenerator:
    def test_returns_rooms_and_walls_and_spawner(self):
        m = generate_maze(1000, 1000, seed=7)
        assert isinstance(m, MazeLayout)
        # 5x5 grid => 25 rooms.
        assert len(m.rooms) == STAR_MAZE_ROOM_COLS * STAR_MAZE_ROOM_ROWS
        # Spawner sits at the caller-specified centre.
        assert m.spawner == (1000, 1000)

    def test_at_least_15_rooms_per_maze(self):
        m = generate_maze(0, 0, seed=1)
        assert len(m.rooms) >= 15

    def test_rooms_are_spec_size(self):
        m = generate_maze(0, 0, seed=1)
        for r in m.rooms:
            assert r.w == STAR_MAZE_ROOM_SIZE
            assert r.h == STAR_MAZE_ROOM_SIZE

    def test_rooms_do_not_overlap(self):
        m = generate_maze(0, 0, seed=1)
        rooms = m.rooms
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                disjoint = (a.x + a.w <= b.x or b.x + b.w <= a.x
                            or a.y + a.h <= b.y or b.y + b.h <= a.y)
                assert disjoint

    def test_bounds_span_matches_constants(self):
        m = generate_maze(0, 0, seed=1)
        assert m.bounds.w == STAR_MAZE_SPAN
        assert m.bounds.h == STAR_MAZE_SPAN

    def test_ship_fits_inside_every_room(self):
        """Every room must be wide enough for a 56 px-diameter ship to
        U-turn inside — 300 px interior is 5.3x ship diameter."""
        from constants import SHIP_RADIUS
        m = generate_maze(0, 0, seed=1)
        for r in m.rooms:
            assert r.w >= SHIP_RADIUS * 4
            assert r.h >= SHIP_RADIUS * 4

    def test_deterministic_per_seed(self):
        a = generate_maze(0, 0, seed=42)
        b = generate_maze(0, 0, seed=42)
        assert a.rooms == b.rooms
        assert a.walls == b.walls

    def test_different_seeds_different_mazes(self):
        a = generate_maze(0, 0, seed=1)
        b = generate_maze(0, 0, seed=2)
        # Same rooms (grid layout) but different walls (carved edges).
        assert a.rooms == b.rooms
        assert a.walls != b.walls

    def test_centre_room_contains_spawner(self):
        m = generate_maze(500, 500, seed=1)
        rx, ry = m.spawner
        center_room = None
        for r in m.rooms:
            if r.x <= rx <= r.x + r.w and r.y <= ry <= r.y + r.h:
                center_room = r
                break
        assert center_room is not None, (
            "spawner must sit inside one of the rooms")


class TestGenerateAllMazes:
    def test_produces_four_mazes(self):
        mazes = generate_all_mazes(zone_seed=0)
        assert len(mazes) == STAR_MAZE_COUNT
        assert len(mazes) == 4

    def test_spawners_at_configured_centres(self):
        mazes = generate_all_mazes(zone_seed=0)
        spawner_positions = [m.spawner for m in mazes]
        expected = [tuple(c) for c in STAR_MAZE_CENTERS]
        assert sorted(spawner_positions) == sorted(expected)

    def test_mazes_do_not_overlap(self):
        mazes = generate_all_mazes(zone_seed=0)
        for i, a in enumerate(mazes):
            for b in mazes[i + 1:]:
                disjoint = (
                    a.bounds.x + a.bounds.w <= b.bounds.x
                    or b.bounds.x + b.bounds.w <= a.bounds.x
                    or a.bounds.y + a.bounds.h <= b.bounds.y
                    or b.bounds.y + b.bounds.h <= a.bounds.y
                )
                assert disjoint

    def test_each_maze_has_its_own_seed(self):
        """Different mazes in the same zone_seed batch produce
        distinct layouts."""
        mazes = generate_all_mazes(zone_seed=0)
        # All four should be distinct.
        walls_by_maze = [tuple(m.walls) for m in mazes]
        assert len(set(walls_by_maze)) == len(mazes)


class TestCollisionHelpers:
    def test_point_in_rect(self):
        r = Rect(10, 10, 20, 20)
        assert point_in_rect(15, 15, r)
        assert not point_in_rect(5, 5, r)
        assert not point_in_rect(35, 35, r)

    def test_circle_hits_wall(self):
        walls = [Rect(0, 0, 10, 100)]
        assert circle_hits_any_wall(15, 50, 6, walls)
        assert not circle_hits_any_wall(30, 50, 6, walls)

    def test_segment_hits_wall(self):
        walls = [Rect(50, 50, 20, 20)]
        assert segment_hits_any_wall(0, 60, 100, 60, walls)
        assert not segment_hits_any_wall(0, 500, 100, 500, walls)

    def test_point_inside_room_interior(self):
        m = generate_maze(500, 500, seed=1)
        # Centre of the first room must register as inside.
        first = m.rooms[0]
        assert point_inside_any_room_interior(
            first.x + first.w / 2, first.y + first.h / 2, m.rooms)
        # Point far away must not.
        assert not point_inside_any_room_interior(
            -1000, -1000, m.rooms)


# ── StarMazeZone construction ────────────────────────────────────

class TestStarMazeZoneConstruction:
    def test_imports_cleanly(self):
        from zones.star_maze import StarMazeZone
        z = StarMazeZone()
        assert z.zone_id == ZoneID.STAR_MAZE
        assert z.world_width == STAR_MAZE_WIDTH
        assert z.world_height == STAR_MAZE_HEIGHT

    def test_factory_maps_star_maze_id(self):
        from zones import create_zone
        z = create_zone(ZoneID.STAR_MAZE)
        assert z.zone_id == ZoneID.STAR_MAZE

    def test_factory_maps_nebula_warp_variants(self):
        from zones import create_zone
        for zid in NEBULA_WARP_ZONES:
            z = create_zone(zid)
            assert z.zone_id is zid

    def test_factory_maps_maze_warp_variants(self):
        from zones import create_zone
        for zid in MAZE_WARP_ZONES:
            z = create_zone(zid)
            assert z.zone_id is zid


# ── Warp-zone danger + exit routing ─────────────────────────────

class _StubPlayer:
    def __init__(self):
        self.center_x = 1600.0
        self.center_y = 3200.0


class _StubGameView:
    def __init__(self):
        self.player = _StubPlayer()
        self._fog_grid = None
        self._fog_revealed = 0
        self._alien_laser_tex = None


def _resolve_warp(zone_id):
    from zones import create_zone
    z = create_zone(zone_id)
    gv = _StubGameView()
    try:
        z.setup(gv)
    except Exception:
        # Subclass setup() may touch textures we can't load here —
        # the routing we care about is set in WarpZoneBase.setup()
        # BEFORE any subclass asset work.
        pass
    return z


class TestWarpDangerByZoneId:
    def test_zone1_launched_stays_1x(self):
        z = _resolve_warp(ZoneID.WARP_METEOR)
        assert z._danger == 1.0
        assert z._exit_bottom_zone is ZoneID.MAIN
        assert z._exit_top_zone is ZoneID.ZONE2

    def test_nebula_launched_is_2x(self):
        z = _resolve_warp(ZoneID.NEBULA_WARP_METEOR)
        assert z._danger == 2.0
        # Spec clarification: bottom exit returns to the source biome
        # (Zone 2), top exit advances forward into the Star Maze.
        assert z._exit_bottom_zone is ZoneID.ZONE2
        assert z._exit_top_zone is ZoneID.STAR_MAZE

    def test_maze_launched_is_2x(self):
        z = _resolve_warp(ZoneID.MAZE_WARP_LIGHTNING)
        assert z._danger == 2.0
        assert z._exit_bottom_zone is ZoneID.STAR_MAZE
        assert z._exit_top_zone is ZoneID.STAR_MAZE


# ── Zone 2 corner-wormhole unlock ────────────────────────────────

class TestZone2CornerWormholes:
    def test_build_corner_wormholes_emits_four(self):
        from zones.zone2 import Zone2
        z2 = Zone2()
        whs = z2._build_corner_wormholes()
        assert len(whs) == 4

    def test_corner_wormhole_targets_map_to_nebula_variants(self):
        from zones.zone2 import Zone2
        z2 = Zone2()
        whs = z2._build_corner_wormholes()
        targets = {w.zone_target for w in whs}
        assert targets == NEBULA_WARP_ZONES

    def test_starts_with_boss_not_defeated(self):
        from zones.zone2 import Zone2
        assert Zone2()._nebula_boss_defeated is False


# ── Welcome-message helper ───────────────────────────────────────

class TestWelcomeMessages:
    def test_star_maze(self):
        from zones import welcome_message_for
        assert welcome_message_for(ZoneID.STAR_MAZE) == (
            "Welcome to the Star Maze")

    def test_gas_warp(self):
        from zones import welcome_message_for
        assert welcome_message_for(ZoneID.NEBULA_WARP_GAS) == (
            "Welcome to the Gas Warp Zone")

    def test_main_returns_none(self):
        from zones import welcome_message_for
        assert welcome_message_for(ZoneID.MAIN) is None

    def test_zone2_returns_none(self):
        from zones import welcome_message_for
        assert welcome_message_for(ZoneID.ZONE2) is None


# ── Save / load round-trip helpers ───────────────────────────────

class TestMazeSpawnerSaveRoundTrip:
    def test_to_save_data_captures_state(self):
        from sprites.maze_spawner import MazeSpawner
        sp = MazeSpawner(100.0, 200.0)
        sp.hp = 40
        sp.shields = 10
        sp.killed = False
        sp._fire_cd = 0.7
        sp._spawn_cd = 12.3
        sp.alive_children = 4
        sp.uid = 17
        data = sp.to_save_data()
        assert data["x"] == 100.0
        assert data["y"] == 200.0
        assert data["hp"] == 40
        assert data["shields"] == 10
        assert data["killed"] is False
        assert abs(data["fire_cd"] - 0.7) < 1e-6
        assert abs(data["spawn_cd"] - 12.3) < 1e-6
        assert data["alive_children"] == 4
        assert data["uid"] == 17

    def test_from_save_data_restores_state(self):
        from sprites.maze_spawner import MazeSpawner
        sp = MazeSpawner(0.0, 0.0)
        sp.from_save_data({
            "x": 500.0, "y": 750.0,
            "hp": 20, "shields": 5,
            "killed": True,
            "fire_cd": 0.2, "spawn_cd": 5.0,
            "alive_children": 2, "uid": 9,
        })
        # Position is intentionally NOT restored from save data — the
        # zone re-derives it deterministically from the world seed via
        # ``generate_maze`` so saves predating layout/scale tweaks
        # don't drop the spawner inside a wall.
        assert sp.center_x == 0.0
        assert sp.center_y == 0.0
        assert sp.hp == 20
        assert sp.shields == 5
        assert sp.killed is True
        assert sp.alive_children == 2
        assert sp.uid == 9

    def test_killed_survives_round_trip(self):
        from sprites.maze_spawner import MazeSpawner
        sp1 = MazeSpawner(0.0, 0.0)
        sp1.hp = 0
        sp1.killed = True
        data = sp1.to_save_data()
        sp2 = MazeSpawner(0.0, 0.0)
        sp2.from_save_data(data)
        assert sp2.killed is True


class TestStarMazeZoneToSaveData:
    def test_unpopulated_returns_seed_and_populated_false(self):
        from zones.star_maze import StarMazeZone
        z = StarMazeZone()
        data = z.to_save_data()
        assert "seed" in data
        assert data["populated"] is False
        assert data["spawners"] == []


class TestZone2NebulaFlagPersistence:
    def test_default_false(self):
        from zones.zone2 import Zone2
        assert Zone2()._nebula_boss_defeated is False

    def test_mark_sets_flag(self):
        from zones.zone2 import Zone2
        z = Zone2()
        z._nebula_boss_defeated = True
        assert z._nebula_boss_defeated is True
