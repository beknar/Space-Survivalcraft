"""Tests for zones.nebula_shared module-level helpers.

Both Zone 2 and Star Maze delegate their per-frame update + collision
work to functions in this module.  Integration tests in
test_zone2_real_gv.py / test_star_maze_real_gv.py exercise the zone
drivers; this file covers the helper functions in isolation so a
regression in the shared layer surfaces directly instead of through
zone-coupled fixtures.
"""
from __future__ import annotations

from unittest.mock import patch
from types import SimpleNamespace

import arcade
import pytest
from PIL import Image as PILImage

from zones import nebula_shared


# ── Test scaffolding ───────────────────────────────────────────────────────

@pytest.fixture
def tex():
    img = PILImage.new("RGBA", (32, 32), (200, 200, 200, 255))
    return arcade.Texture(img)


def _make_z(*, fog_w=8, fog_h=8, fog_cell=100, fog_reveal_r=200):
    """Minimal duck-typed zone with the attributes the helpers read."""
    grid = [[False for _ in range(fog_w)] for _ in range(fog_h)]
    return SimpleNamespace(
        world_width=800.0,
        world_height=800.0,
        _iron_asteroids=arcade.SpriteList(),
        _double_iron=arcade.SpriteList(),
        _copper_asteroids=arcade.SpriteList(),
        _wanderers=arcade.SpriteList(),
        _gas_areas=arcade.SpriteList(),
        _aliens=arcade.SpriteList(),
        _alien_projectiles=arcade.SpriteList(),
        _shielded_aliens=[],
        _null_fields=[],
        _slipspaces=arcade.SpriteList(),
        _gas_damage_cd=0.0,
        _respawn_timer=0.0,
        _gas_pos_cache=None,
        _alien_counts={},
        _fog_cell=fog_cell,
        _fog_reveal_r=fog_reveal_r,
        _fog_w=fog_w,
        _fog_h=fog_h,
        _fog_grid=grid,
        _fog_revealed=0,
        _world_seed=12345,
    )


def _silence_audio():
    return patch("arcade.play_sound", lambda *a, **kw: None)


# ── rebuild_shielded_list ──────────────────────────────────────────────────

class TestRebuildShieldedList:
    def test_empty_alien_list_yields_empty(self):
        z = _make_z()
        nebula_shared.rebuild_shielded_list(z)
        assert z._shielded_aliens == []

    def test_only_shielded_aliens_are_collected(self, tex):
        from sprites.zone2_aliens import ShieldedAlien, FastAlien
        z = _make_z()
        s = ShieldedAlien(tex, tex, 100.0, 100.0)
        f = FastAlien(tex, tex, 200.0, 200.0)
        z._aliens.append(s)
        z._aliens.append(f)
        nebula_shared.rebuild_shielded_list(z)
        assert z._shielded_aliens == [s]

    def test_overwrites_stale_entries(self, tex):
        from sprites.zone2_aliens import ShieldedAlien
        z = _make_z()
        # Stale entry — alien no longer in z._aliens
        old = ShieldedAlien(tex, tex, 0.0, 0.0)
        z._shielded_aliens = [old]
        nebula_shared.rebuild_shielded_list(z)
        assert z._shielded_aliens == []


# ── update_fog ─────────────────────────────────────────────────────────────

class TestUpdateFog:
    def test_reveals_cells_within_radius(self, stub_gv):
        z = _make_z(fog_w=10, fog_h=10, fog_cell=100, fog_reveal_r=150)
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        nebula_shared.update_fog(z, stub_gv)
        # Cell (5, 5) is centred at (550, 550) — within 150 px of (500, 500)
        assert z._fog_grid[5][5] is True
        assert z._fog_revealed >= 1

    def test_does_not_reveal_distant_cells(self, stub_gv):
        z = _make_z(fog_w=10, fog_h=10, fog_cell=100, fog_reveal_r=150)
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        nebula_shared.update_fog(z, stub_gv)
        # Cell (0, 0) is far away — must remain unrevealed
        assert z._fog_grid[0][0] is False

    def test_already_revealed_cells_are_not_double_counted(self, stub_gv):
        z = _make_z(fog_w=10, fog_h=10, fog_cell=100, fog_reveal_r=150)
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        nebula_shared.update_fog(z, stub_gv)
        first = z._fog_revealed
        nebula_shared.update_fog(z, stub_gv)  # second pass at same position
        assert z._fog_revealed == first

    def test_propagates_count_to_gv(self, stub_gv):
        z = _make_z(fog_w=10, fog_h=10, fog_cell=100, fog_reveal_r=150)
        stub_gv.player.center_x = 500.0
        stub_gv.player.center_y = 500.0
        nebula_shared.update_fog(z, stub_gv)
        assert stub_gv._fog_revealed == z._fog_revealed


# ── update_gas_damage ──────────────────────────────────────────────────────

class TestUpdateGasDamage:
    def test_no_damage_when_player_outside_gas(self, stub_gv, tex):
        from sprites.gas_area import GasArea
        z = _make_z()
        z._gas_areas.append(GasArea(tex, 100.0, 100.0, size=100))
        # Player nowhere near
        stub_gv.player.center_x = 5000.0
        stub_gv.player.center_y = 5000.0
        nebula_shared.update_gas_damage(z, stub_gv, 1 / 60)
        assert stub_gv.calls["damage"] == []

    def test_damage_applied_when_inside_and_cooldown_zero(self, stub_gv, tex):
        from sprites.gas_area import GasArea
        z = _make_z()
        gas = GasArea(tex, stub_gv.player.center_x, stub_gv.player.center_y,
                      size=200)
        z._gas_areas.append(gas)
        z._gas_damage_cd = 0.0
        nebula_shared.update_gas_damage(z, stub_gv, 1 / 60)
        assert len(stub_gv.calls["damage"]) == 1
        assert z._gas_damage_cd > 0.0

    def test_cooldown_blocks_repeat_damage(self, stub_gv, tex):
        from sprites.gas_area import GasArea
        z = _make_z()
        z._gas_areas.append(GasArea(
            tex, stub_gv.player.center_x, stub_gv.player.center_y, size=200))
        z._gas_damage_cd = 0.5  # still cooling
        nebula_shared.update_gas_damage(z, stub_gv, 1 / 60)
        assert stub_gv.calls["damage"] == []


# ── update_alien_laser_hits ────────────────────────────────────────────────

class TestUpdateAlienLaserHits:
    def test_overlapping_projectile_damages_and_is_removed(
            self, stub_gv, tex):
        from sprites.projectile import Projectile
        z = _make_z()
        proj = Projectile(
            tex,
            stub_gv.player.center_x, stub_gv.player.center_y,
            0.0, 0.0, 1000.0, scale=1.0, damage=7,
        )
        z._alien_projectiles.append(proj)
        nebula_shared.update_alien_laser_hits(z, stub_gv)
        assert stub_gv.calls["damage"] == [7]
        assert len(z._alien_projectiles) == 0

    def test_distant_projectile_is_not_consumed(self, stub_gv, tex):
        from sprites.projectile import Projectile
        z = _make_z()
        proj = Projectile(
            tex, 9000.0, 9000.0, 0.0, 0.0, 1000.0, scale=1.0, damage=7,
        )
        z._alien_projectiles.append(proj)
        nebula_shared.update_alien_laser_hits(z, stub_gv)
        assert stub_gv.calls["damage"] == []
        assert len(z._alien_projectiles) == 1


# ── update_player_asteroid_collision ───────────────────────────────────────

class TestPlayerAsteroidCollision:
    def test_cooldown_active_skips_branch(self, stub_gv, tex):
        from sprites.asteroid import IronAsteroid
        z = _make_z()
        z._iron_asteroids.append(IronAsteroid(
            tex, stub_gv.player.center_x, stub_gv.player.center_y))
        stub_gv.player._collision_cd = 0.5
        with _silence_audio():
            nebula_shared.update_player_asteroid_collision(z, stub_gv)
        assert stub_gv.calls["damage"] == []

    def test_overlapping_iron_damages_player(self, stub_gv, tex):
        from sprites.asteroid import IronAsteroid
        z = _make_z()
        z._iron_asteroids.append(IronAsteroid(
            tex, stub_gv.player.center_x, stub_gv.player.center_y))
        with _silence_audio():
            nebula_shared.update_player_asteroid_collision(z, stub_gv)
        assert len(stub_gv.calls["damage"]) == 1
        assert stub_gv.player._collision_cd > 0.0

    def test_only_one_collision_per_frame(self, stub_gv, tex):
        """Stack of asteroids must not multiply damage in a single tick."""
        from sprites.asteroid import IronAsteroid
        z = _make_z()
        for _ in range(3):
            z._iron_asteroids.append(IronAsteroid(
                tex, stub_gv.player.center_x, stub_gv.player.center_y))
        with _silence_audio():
            nebula_shared.update_player_asteroid_collision(z, stub_gv)
        assert len(stub_gv.calls["damage"]) == 1


# ── update_wanderer_collision ──────────────────────────────────────────────

class TestWandererCollision:
    def test_cooldown_active_skips(self, stub_gv, tex):
        from sprites.wandering_asteroid import WanderingAsteroid
        z = _make_z()
        w = WanderingAsteroid(
            tex, stub_gv.player.center_x, stub_gv.player.center_y,
            world_w=800.0, world_h=800.0)
        z._wanderers.append(w)
        stub_gv.player._collision_cd = 0.5
        with _silence_audio():
            nebula_shared.update_wanderer_collision(z, stub_gv)
        assert stub_gv.calls["damage"] == []

    def test_overlap_damages_and_starts_cooldown(self, stub_gv, tex):
        from sprites.wandering_asteroid import WanderingAsteroid
        z = _make_z()
        w = WanderingAsteroid(
            tex, stub_gv.player.center_x, stub_gv.player.center_y,
            world_w=800.0, world_h=800.0)
        z._wanderers.append(w)
        with _silence_audio():
            nebula_shared.update_wanderer_collision(z, stub_gv)
        assert len(stub_gv.calls["damage"]) == 1
        assert stub_gv.player._collision_cd > 0.0
