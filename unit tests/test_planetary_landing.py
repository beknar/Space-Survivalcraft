"""Fast unit tests for Planets Phase 1 — "Reach + Descend".

Covers (docs/planets.md sections 3-5):
* the Planet sprite,
* the Planetary Landing Adapter module registration,
* the planet-contact gate in the Star Maze (adapter -> descend,
  no adapter -> damage),
* LandingEnemy combat (shields-then-HP, pursue, single/double fire),
* PlanetaryLandingZone routing (bottom return, top-edge stub, walls),
* spec/constant agreement.

All tests use the shared ``stub_gv`` fixture + dummy textures; nothing
here needs the heavyweight zone ``setup`` (full enemy population +
maze generation is exercised by the integration smoke test).
"""
from __future__ import annotations

from unittest.mock import patch

import arcade
from PIL import Image as PILImage

import constants as C
from specs import (
    SKY_WORM, CLOUD_DRONE, THUNDER_WORM, LANDING_ENEMIES,
)
from sprites.planet import Planet
from sprites.landing_enemy import LandingEnemy
from zones import ZoneID
from zones.star_maze import StarMazeZone
from zones.zone_planetary_landing import PlanetaryLandingZone
from zones.zone_warp_base import EXIT_THRESHOLD


# ── Planet sprite ───────────────────────────────────────────────────────────

class TestPlanetSprite:
    def test_defaults_to_earth(self):
        p = Planet(100.0, 200.0)
        assert p.planet_type == "earth"
        assert p.center_x == 100.0 and p.center_y == 200.0
        assert p.radius == C.PLANET_RADIUS

    def test_type_is_stored(self):
        assert Planet(0, 0, "frost").planet_type == "frost"
        assert Planet(0, 0, "barren").planet_type == "barren"

    def test_unknown_type_falls_back_to_earth_texture(self):
        # Unknown type still constructs (falls back to the earth png).
        p = Planet(0, 0, "nonsense")
        assert p.planet_type == "nonsense"  # type stored verbatim
        assert p.texture is not None


# ── Module registration ─────────────────────────────────────────────────────

class TestLandingModule:
    def test_module_registered(self):
        m = C.MODULE_TYPES["planetary_landing"]
        assert m["advanced"] is True
        assert m["effect"] == "planetary_landing"
        assert m["craft_cost"] == 500
        assert m["craft_cost_copper"] == 500


# ── Planet contact gate in the Star Maze ────────────────────────────────────

def _maze_with_planet_at(px, py, ptype="earth"):
    """A StarMazeZone with a single planet sitting on (px, py).  We skip
    the heavy ``setup`` and just seed ``_planets`` directly."""
    zone = StarMazeZone()
    zone._planets.append(Planet(px, py, ptype))
    return zone


class TestPlanetContact:
    def test_with_adapter_transitions_to_landing(self, stub_gv):
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        stub_gv._module_slots = ["planetary_landing", None, None, None]
        zone = _maze_with_planet_at(500.0, 500.0, "earth")

        with patch("arcade.play_sound", lambda *a, **kw: None):
            consumed = zone._update_planet_contact(stub_gv, 1 / 60)

        assert consumed is True
        # Recorded a transition into the landing scene.
        targets = [c[0][0] if isinstance(c, tuple) else c
                   for c in stub_gv.calls["transition"]]
        assert ZoneID.PLANETARY_LANDING in targets
        assert stub_gv._pending_planet_type == "earth"
        assert stub_gv._planet_origin_zone == ZoneID.STAR_MAZE
        # No collision damage on the landing path.
        assert stub_gv.calls["damage"] == []

    def test_without_adapter_applies_damage_no_transition(self, stub_gv):
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        stub_gv.player.hp = 100
        stub_gv.player.max_hp = 100
        stub_gv.player.shields = 40
        stub_gv._module_slots = [None, None, None, None]
        zone = _maze_with_planet_at(500.0, 500.0)

        with patch("arcade.play_sound", lambda *a, **kw: None):
            consumed = zone._update_planet_contact(stub_gv, 1 / 60)

        assert consumed is False
        assert stub_gv.calls["transition"] == []
        # 25% of max HP = 25 damage; 25% off shields -> 30.
        assert stub_gv.calls["damage"] == [25]
        assert stub_gv.player.shields == 30
        assert stub_gv.calls["shake"] >= 1

    def test_no_contact_when_far_away(self, stub_gv):
        stub_gv.player.center_x = 0.0
        stub_gv.player.center_y = 0.0
        stub_gv._module_slots = ["planetary_landing", None, None, None]
        zone = _maze_with_planet_at(8000.0, 8000.0)

        consumed = zone._update_planet_contact(stub_gv, 1 / 60)
        assert consumed is False
        assert stub_gv.calls["transition"] == []
        assert stub_gv.calls["damage"] == []


# ── LandingEnemy combat ─────────────────────────────────────────────────────

def _enemy(spec, x=0.0, y=0.0):
    img = arcade.Texture(PILImage.new("RGBA", (16, 16), (255, 0, 0, 255)))
    return LandingEnemy(spec, img, img, x, y)


class TestLandingEnemy:
    def test_take_damage_drains_shields_then_hp(self):
        e = _enemy(SKY_WORM)
        e.shields = 50
        e.hp = 50
        e.take_damage(30)
        assert e.shields == 20 and e.hp == 50
        e.take_damage(40)          # 20 to shields, 20 to hp
        assert e.shields == 0 and e.hp == 30

    def test_fires_one_shot_when_in_range(self):
        e = _enemy(SKY_WORM, 0.0, 0.0)
        e._fire_cd = 0.0           # force a shot this tick
        shots = e.update_enemy(1 / 60, 50.0, 0.0)  # player within detect+range
        assert len(shots) == 1

    def test_thunder_worm_double_shot(self):
        e = _enemy(THUNDER_WORM, 0.0, 0.0)
        e._fire_cd = 0.0
        shots = e.update_enemy(1 / 60, 30.0, 0.0)
        assert len(shots) == 2

    def test_pursues_player_in_detect_range(self):
        e = _enemy(CLOUD_DRONE, 0.0, 0.0)
        e._fire_cd = 99.0          # suppress firing so we isolate movement
        # Player to the right, inside the 300 px detect range.
        e.update_enemy(0.5, 200.0, 0.0)
        assert e.center_x > 0.0    # moved toward the player

    def test_no_action_outside_detect_range(self):
        e = _enemy(THUNDER_WORM, 0.0, 0.0)
        e._fire_cd = 0.0
        far = THUNDER_WORM.detect + 1000.0
        shots = e.update_enemy(1 / 60, far, 0.0)
        assert shots == []
        assert e.center_x == 0.0 and e.center_y == 0.0


# ── PlanetaryLandingZone routing ────────────────────────────────────────────

def _landing_zone(origin=ZoneID.STAR_MAZE):
    zone = PlanetaryLandingZone()
    zone._origin_zone = origin
    zone._apply_zone_id_routing()
    return zone


class TestLandingZoneRouting:
    def test_bottom_edge_returns_to_origin(self, stub_gv):
        zone = _landing_zone(ZoneID.STAR_MAZE)
        stub_gv.player.center_y = EXIT_THRESHOLD - 10.0
        zone._check_exits(stub_gv)
        targets = [c[0][0] if isinstance(c, tuple) else c
                   for c in stub_gv.calls["transition"]]
        assert targets == [ZoneID.STAR_MAZE]

    def test_top_edge_is_stub_no_transition(self, stub_gv):
        zone = _landing_zone()
        stub_gv.player.center_y = zone.world_height - 10.0
        stub_gv.player.vel_y = 50.0
        zone._check_exits(stub_gv)
        assert stub_gv.calls["transition"] == []      # surface not built yet
        assert stub_gv.calls["flash"]                  # "coming soon" notice
        assert stub_gv.player.center_y < zone.world_height - EXIT_THRESHOLD

    def test_wall_contact_applies_fractional_damage(self, stub_gv):
        zone = _landing_zone()
        zone._wall_dmg_cd = 0.0
        stub_gv.player.center_x = 10.0     # inside the left wall band
        stub_gv.player.max_hp = 100
        stub_gv.player.shields = 80
        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone._check_walls(stub_gv)
        assert stub_gv.calls["damage"] == [25]         # 25% of max hp
        assert stub_gv.player.shields == 60            # 25% off shields
        # Player bounced back inside the wall band.
        assert stub_gv.player.center_x > zone._effective_wall


# ── spec / constant agreement ───────────────────────────────────────────────

class TestSpecs:
    def test_landing_enemies_tuple(self):
        assert [s.name for s in LANDING_ENEMIES] == [
            "Sky Worm", "Cloud Drone", "Thunder Worm"]

    def test_counts_total_60(self):
        assert sum(s.count for s in LANDING_ENEMIES) == 60

    def test_sky_worm_matches_constants(self):
        assert SKY_WORM.hp == C.LANDING_SKY_WORM_HP
        assert SKY_WORM.shield == C.LANDING_SKY_WORM_SHIELD
        assert SKY_WORM.damage == C.LANDING_SKY_WORM_DAMAGE
        assert SKY_WORM.xp == C.LANDING_SKY_WORM_XP
        assert SKY_WORM.shots == 1

    def test_thunder_worm_is_shieldless_double_shot(self):
        assert THUNDER_WORM.shield == 0
        assert THUNDER_WORM.shots == 2
        assert THUNDER_WORM.hp == C.LANDING_THUNDER_WORM_HP
