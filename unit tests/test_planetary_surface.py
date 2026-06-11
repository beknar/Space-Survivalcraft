"""Fast unit tests for Planets Phase 2 — the on-foot surface slice.

Covers (docs/planets.md section 6):
* on-foot movement (direct WASD, fixed speed, heading tracking),
* the Armor stat in the damage pipeline,
* resource-node mining yields,
* the surface zone's ship<->on-foot mode swap (setup/teardown),
* the lift-off (bottom-edge) exit.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
from PIL import Image as PILImage

import constants as C
import combat_helpers
from sprites.player import PlayerShip
from sprites.resource_node import ResourceNode
from sprites.projectile import Projectile
from world_setup import load_on_foot_frames
from zones import ZoneID
from zones.zone_planetary_surface import PlanetarySurfaceZone


# ── On-foot walk animation ──────────────────────────────────────────────────

class TestOnFootAnimation:
    def test_frames_loaded_per_direction(self):
        f = load_on_foot_frames()
        assert sorted(f.keys()) == ["down", "left", "right", "up"]
        assert len(f["down"]) == 2 and len(f["up"]) == 2     # 2-frame walk
        assert len(f["left"]) == 1 and len(f["right"]) == 1  # single profile

    def test_facing_follows_dominant_axis(self):
        p = PlayerShip()
        p._on_foot_frames = load_on_foot_frames()
        cases = [
            (dict(up=True, down=False, left=False, right=False), "up"),
            (dict(up=False, down=True, left=False, right=False), "down"),
            (dict(up=False, down=False, left=True, right=False), "left"),
            (dict(up=False, down=False, left=False, right=True), "right"),
        ]
        for keys, expected in cases:
            p.apply_input_on_foot(1 / 60, **keys)
            assert p._facing == expected

    def test_diagonal_resolves_to_vertical(self):
        p = PlayerShip()
        p._on_foot_frames = load_on_foot_frames()
        p.apply_input_on_foot(1 / 60, up=True, down=False, left=False, right=True)
        assert p._facing == "up"            # vertical wins the tie

    def test_texture_matches_facing_frame(self):
        p = PlayerShip()
        f = load_on_foot_frames()
        p._on_foot_frames = f
        p.apply_input_on_foot(1 / 60, up=False, down=False, left=False, right=True)
        assert p.texture is f["right"][0]

    def test_walk_cycle_advances_then_resets_when_idle(self):
        p = PlayerShip()
        p._on_foot_frames = load_on_foot_frames()
        # Hold "down" long enough to flip the 2-frame cycle (6 fps -> ~0.17 s).
        p.apply_input_on_foot(0.2, up=False, down=True, left=False, right=False)
        assert p._walk_idx == 1
        # Releasing keys resets to the standing frame.
        p.apply_input_on_foot(1 / 60, up=False, down=False, left=False, right=False)
        assert p._walk_idx == 0


# ── On-foot movement ────────────────────────────────────────────────────────

class TestOnFootMovement:
    def test_moves_right_at_walk_speed(self):
        p = PlayerShip()                      # legacy ship, fine for math
        p.center_x = 1000.0
        p.center_y = 1000.0
        p.vel_x = p.vel_y = 0.0
        p.apply_input_on_foot(1.0, up=False, down=False, left=False, right=True)
        # One second at ON_FOOT_SPEED to the right.
        assert p.center_x > 1000.0
        assert abs(p.vel_x - C.ON_FOOT_SPEED) < 1e-6
        assert abs(p.vel_y) < 1e-6

    def test_diagonal_is_normalized(self):
        p = PlayerShip()
        p.vel_x = p.vel_y = 0.0
        p.apply_input_on_foot(1.0, up=True, down=False, left=False, right=True)
        speed = (p.vel_x ** 2 + p.vel_y ** 2) ** 0.5
        assert abs(speed - C.ON_FOOT_SPEED) < 1e-6   # not faster on the diagonal

    def test_no_input_decays_velocity(self):
        p = PlayerShip()
        p.vel_x = 200.0
        p.vel_y = 0.0
        p.apply_input_on_foot(1 / 60, up=False, down=False, left=False, right=False)
        assert p.vel_x < 200.0                # damped toward rest

    def test_heading_tracks_movement(self):
        p = PlayerShip()
        p.apply_input_on_foot(1 / 60, up=True, down=False, left=False, right=False)
        assert abs(p.heading - 0.0) < 1e-6    # up == heading 0
        p.apply_input_on_foot(1 / 60, up=False, down=False, left=False, right=True)
        assert abs(p.heading - 90.0) < 1e-6   # right == heading 90


# ── Armor stat ──────────────────────────────────────────────────────────────

def _dmg_gv(hp=100, armor=0, shields=0, shield_absorb=0):
    img = PILImage.new("RGBA", (8, 8), (0, 200, 255, 255))
    player = SimpleNamespace(
        hp=hp, max_hp=hp, shields=shields, max_shields=shields,
        armor=armor, shield_absorb=shield_absorb,
        center_x=0.0, center_y=0.0)
    return SimpleNamespace(
        _player_dead=False, player=player,
        shield_sprite=SimpleNamespace(hit_flash=lambda: None),
        fire_sparks=[], _shake_amp=0.0)


class TestArmor:
    def test_armor_reduces_hp_damage(self):
        gv = _dmg_gv(hp=100, armor=3)
        combat_helpers.apply_damage_to_player(gv, 10)
        assert gv.player.hp == 93            # 10 - 3 armor

    def test_armor_never_negates_below_one(self):
        gv = _dmg_gv(hp=100, armor=50)
        combat_helpers.apply_damage_to_player(gv, 10)
        assert gv.player.hp == 99            # clamped to 1 through

    def test_zero_armor_is_noop(self):
        gv = _dmg_gv(hp=100, armor=0)
        combat_helpers.apply_damage_to_player(gv, 10)
        assert gv.player.hp == 90


# ── Resource node mining ─────────────────────────────────────────────────────

class _FakeInv:
    def __init__(self):
        self.added: list[tuple[str, int]] = []

    def add_item(self, item, count):
        self.added.append((item, count))


class TestResourceNode:
    def test_take_damage_then_yield(self, stub_gv):
        zone = PlanetarySurfaceZone()
        node = ResourceNode("rock", 500.0, 500.0)
        zone._nodes.append(node)
        inv = _FakeInv()
        stub_gv.inventory = inv
        stub_gv.player.center_x = 50.0       # far from node, no exit
        stub_gv.player.center_y = 2000.0
        # A mining projectile sitting on the node, lethal in one hit.
        img = arcade.Texture(PILImage.new("RGBA", (4, 4), (0, 255, 0, 255)))
        proj = Projectile(img, 500.0, 500.0, 0.0, 600.0, 300.0,
                          scale=1.0, damage=999.0)
        proj.mines_rock = True
        stub_gv.projectile_list.append(proj)

        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone.update(stub_gv, 1 / 60)

        assert ("iron", C.ROCK_NODE_YIELD) in inv.added
        assert len(zone._nodes) == 0          # node consumed
        assert len(stub_gv.calls["explosion"]) == 1

    def test_rifle_shot_does_not_mine(self, stub_gv):
        zone = PlanetarySurfaceZone()
        node = ResourceNode("copper", 500.0, 500.0)
        zone._nodes.append(node)
        inv = _FakeInv()
        stub_gv.inventory = inv
        stub_gv.player.center_x = 50.0
        stub_gv.player.center_y = 2000.0
        img = arcade.Texture(PILImage.new("RGBA", (4, 4), (0, 0, 255, 255)))
        proj = Projectile(img, 500.0, 500.0, 0.0, 900.0, 600.0,
                          scale=1.0, damage=999.0)
        proj.mines_rock = False              # rifle shot
        stub_gv.projectile_list.append(proj)
        zone.update(stub_gv, 1 / 60)
        assert inv.added == []               # not mined
        assert len(zone._nodes) == 1


# ── Surface zone enter / leave (mode swap) ──────────────────────────────────

class _FakeCVP:
    """Records calls the surface video swap makes on the HUD char video."""
    def __init__(self):
        self.calls: list = []
    def stop(self):
        self.calls.append("stop")
    def play_segments(self, path, volume=0.0):
        self.calls.append(("play", path))
        return True


def _surface_stub(stub_gv):
    """Attach the fields the surface setup/teardown touch onto a stub."""
    p = stub_gv.player
    p.armor = 0
    p.guns = 2
    p.heading = 0.0
    stub_gv._weapons = ["ship_a", "ship_b", "ship_c", "ship_d"]
    stub_gv._weapon_idx = 2
    stub_gv._planet_origin_zone = ZoneID.STAR_MAZE
    stub_gv._pending_planet_type = "earth"
    stub_gv._char_video_player = _FakeCVP()
    return stub_gv


class TestSurfaceModeSwap:
    def test_setup_enters_on_foot(self, stub_gv):
        gv = _surface_stub(stub_gv)
        zone = PlanetarySurfaceZone()
        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone.setup(gv)
        assert gv._on_foot is True
        assert gv.player.armor == C.ON_FOOT_BASE_ARMOR
        assert gv.player.hp == C.ON_FOOT_BASE_HP
        assert gv.player.max_shields == 0
        assert gv.player.guns == 1            # so the weapon list cycles 1-by-1
        assert len(gv._weapons) == 4          # rifle, mining beam, sword, pick
        assert gv.player._on_foot_frames is not None   # walk frames loaded
        assert gv.player._facing == "down"
        assert len(zone._nodes) == (
            C.ROCK_NODE_COUNT + C.COPPER_VEIN_COUNT + C.SILICON_VEIN_COUNT)

    def test_teardown_restores_ship(self, stub_gv):
        gv = _surface_stub(stub_gv)
        zone = PlanetarySurfaceZone()
        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone.setup(gv)
            zone.teardown(gv)
        assert gv._on_foot is False
        assert gv.player.armor == 0
        assert gv.player.guns == 2
        assert gv._weapons == ["ship_a", "ship_b", "ship_c", "ship_d"]
        assert gv._weapon_idx == 2
        assert gv.player._on_foot_frames is None    # ship won't animate


# ── Lift-off exit ───────────────────────────────────────────────────────────

class TestLiftOff:
    def test_bottom_edge_returns_to_origin(self, stub_gv):
        zone = PlanetarySurfaceZone()
        zone._origin_zone = ZoneID.STAR_MAZE
        stub_gv.inventory = _FakeInv()
        stub_gv.player.center_x = zone.world_width / 2
        stub_gv.player.center_y = 10.0       # on the bottom lift-off edge
        zone.update(stub_gv, 1 / 60)
        targets = [c[0][0] if isinstance(c, tuple) else c
                   for c in stub_gv.calls["transition"]]
        assert ZoneID.STAR_MAZE in targets


# ── Surface HUD character video swap ────────────────────────────────────────

class TestSurfaceHudVideo:
    def test_surface_video_file_exists(self):
        import os
        assert os.path.isfile(C.DEBRA_SURFACE_VIDEO)

    def test_setup_swaps_hud_video_to_debra(self, stub_gv):
        gv = _surface_stub(stub_gv)
        zone = PlanetarySurfaceZone()
        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone.setup(gv)
        # Stopped the prior clip, then started Debra.mp4 via play_segments.
        assert ("play", C.DEBRA_SURFACE_VIDEO) in gv._char_video_player.calls

    def test_teardown_restores_space_video(self, stub_gv):
        gv = _surface_stub(stub_gv)
        zone = PlanetarySurfaceZone()
        with patch("arcade.play_sound", lambda *a, **kw: None):
            zone.setup(gv)
            gv._char_video_player.calls.clear()
            zone.teardown(gv)
        # Restore stops the surface clip; it does NOT re-play Debra.mp4.
        assert "stop" in gv._char_video_player.calls
        assert ("play", C.DEBRA_SURFACE_VIDEO) not in gv._char_video_player.calls
