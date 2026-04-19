"""Integration tests for the QWI + Nebula boss flow.

Real GameView so we can:
  - Load the QWI + Nebula boss textures via the actual asset pipeline
  - Drive the full place-building → auto-spawn-Double-Star-boss flow
  - Drive the click-QWI → QWI menu → spawn Nebula boss flow
  - Exercise the Nebula boss gas attacks against the real
    GameView combat pipeline

Run with:
    pytest "unit tests/integration/test_qwi_and_nebula_boss.py" -v
"""
from __future__ import annotations

import math
import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID


def _setup_main_with_station(gv):
    """Zone 1 + a Home Station at the world centre."""
    from sprites.building import create_building
    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
    gv.building_list.clear()
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex,
        WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
    # Stock enough iron + copper to build a QWI.
    gv.inventory._items[(0, 0)] = ("iron", 1100)
    gv.inventory._items[(0, 1)] = ("copper", 2100)
    gv.inventory._mark_dirty()


# ── Texture loading + building creation ───────────────────────────────────

class TestQWITextureLoad:
    def test_building_textures_include_qwi(self, real_game_view):
        """``world_setup.load_building_textures`` must successfully
        load the QWI's custom-path texture."""
        gv = real_game_view
        assert "Quantum Wave Integrator" in gv._building_textures
        tex = gv._building_textures["Quantum Wave Integrator"]
        assert tex is not None
        assert tex.width > 0

    def test_nebula_boss_texture_loads(self, real_game_view):
        """Crop column 1, row 0 of the 128×128 sheet into an
        arcade.Texture."""
        from sprites.nebula_boss import load_nebula_boss_texture
        tex = load_nebula_boss_texture()
        from constants import NEBULA_BOSS_FRAME_SIZE
        assert tex.width == NEBULA_BOSS_FRAME_SIZE
        assert tex.height == NEBULA_BOSS_FRAME_SIZE


# ── Building the QWI spawns the Double Star boss ───────────────────────────

class TestBuildingQWISpawnsDoubleStarBoss:
    def test_place_qwi_auto_spawns_double_star_boss(self, real_game_view):
        from sprites.building import create_building, QuantumWaveIntegrator
        gv = real_game_view
        _setup_main_with_station(gv)

        # Build the QWI via the same code path place_building uses
        # after cancelling the ghost — append the building and fire
        # the post-place hook manually.
        qwi_tex = gv._building_textures["Quantum Wave Integrator"]
        qwi = create_building("Quantum Wave Integrator", qwi_tex,
                              WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2,
                              scale=0.5)
        assert isinstance(qwi, QuantumWaveIntegrator)
        gv.building_list.append(qwi)

        # Invoke the auto-spawn branch by simulating the place_building
        # post-append code.
        from combat_helpers import spawn_boss
        gv._boss_spawned = False
        gv._boss_defeated = False
        spawn_boss(gv, WORLD_WIDTH / 2, WORLD_HEIGHT / 2)

        assert gv._boss is not None
        assert gv._boss.hp > 0


# ── QWIMenu click → spawn_nebula_boss → NebulaBossShip exists ──────────────

class TestQWIMenuSpawnsNebulaBoss:
    def test_click_button_spawns_nebula_boss(self, real_game_view):
        from combat_helpers import spawn_nebula_boss
        gv = real_game_view
        _setup_main_with_station(gv)

        # Ensure no nebula boss exists + resources are stocked.
        gv._nebula_boss = None
        gv.inventory._items[(0, 2)] = ("iron", 200)
        gv.inventory._mark_dirty()
        iron_before = gv.inventory.total_iron + gv._station_inv.total_iron

        ok = spawn_nebula_boss(gv)
        assert ok is True
        assert gv._nebula_boss is not None
        assert gv._nebula_boss.hp > 0
        # 100 iron deducted.
        iron_after = gv.inventory.total_iron + gv._station_inv.total_iron
        assert iron_before - iron_after == 100

    def test_double_summon_rejected(self, real_game_view):
        from combat_helpers import spawn_nebula_boss
        gv = real_game_view
        _setup_main_with_station(gv)
        gv._nebula_boss = None
        gv.inventory._items[(0, 2)] = ("iron", 500)
        gv.inventory._mark_dirty()
        assert spawn_nebula_boss(gv) is True
        # Second call must refuse.
        iron_before = gv.inventory.total_iron + gv._station_inv.total_iron
        assert spawn_nebula_boss(gv) is False
        iron_after = gv.inventory.total_iron + gv._station_inv.total_iron
        assert iron_before == iron_after

    def test_qwi_menu_flow_end_to_end(self, real_game_view):
        """Open the QWI menu → click the spawn button → Nebula boss
        appears."""
        gv = real_game_view
        _setup_main_with_station(gv)
        gv._nebula_boss = None
        gv.inventory._items[(0, 2)] = ("iron", 200)
        gv.inventory._mark_dirty()

        gv._qwi_menu.toggle()   # open
        assert gv._qwi_menu.open is True
        bx, by, bw, bh = gv._qwi_menu._btn_rect()
        action = gv._qwi_menu.on_mouse_press(bx + bw // 2, by + bh // 2)
        assert action == "spawn_nebula_boss"

        from combat_helpers import spawn_nebula_boss
        assert spawn_nebula_boss(gv) is True
        assert gv._nebula_boss is not None


# ── Nebula boss gas attacks in the combat pipeline ─────────────────────────

class TestNebulaBossGasAttacks:
    def test_gas_cloud_fires_on_cooldown(self, real_game_view):
        """Drive ``tick_nebula`` long enough for the gas cooldown to
        expire with the player in range — a GasCloudProjectile must
        be returned."""
        from combat_helpers import spawn_nebula_boss
        from sprites.nebula_boss import GasCloudProjectile
        gv = real_game_view
        _setup_main_with_station(gv)
        gv._nebula_boss = None
        gv.inventory._items[(0, 2)] = ("iron", 500)
        gv.inventory._mark_dirty()
        assert spawn_nebula_boss(gv) is True
        nb = gv._nebula_boss
        nb._gas_cd = 0.0
        # Park player close enough to be in detect range.
        from constants import BOSS_DETECT_RANGE
        px = nb.center_x - 100
        py = nb.center_y
        cloud = nb.tick_nebula(1 / 60, px, py)
        assert isinstance(cloud, GasCloudProjectile)

    def test_gas_cloud_damages_player_and_slows(self, real_game_view):
        """A gas cloud touching the player applies damage AND sets
        the slow timer so the next ``update_movement`` halves
        effective dt."""
        from sprites.nebula_boss import GasCloudProjectile
        import update_logic as _ul
        gv = real_game_view
        _setup_main_with_station(gv)
        # Player at the origin of a cloud — guaranteed hit.
        gv.player.center_x = 100.0
        gv.player.center_y = 100.0
        gv.player.hp = gv.player.max_hp
        # Zero shields so gas damage lands on HP directly.
        gv.player.shields = 0
        gv._nebula_boss = _StubNebulaBoss(100.0, 100.0)
        gv._nebula_gas_clouds = [
            GasCloudProjectile(100.0, 100.0, 0.0, damage=15.0)]
        hp_before = gv.player.hp
        _ul.update_nebula_boss(gv, 1 / 60)
        assert gv.player.hp < hp_before
        assert gv._nebula_slow_timer > 0.0

    def test_cone_damages_player_while_inside(self, real_game_view):
        import update_logic as _ul
        gv = real_game_view
        _setup_main_with_station(gv)
        gv.player.center_x = 200.0
        gv.player.center_y = 100.0
        gv.player.hp = gv.player.max_hp
        gv.player.shields = 0
        # Stub nebula boss with an active cone pointing east.
        nb = _StubNebulaBoss(100.0, 100.0)
        nb._cone_active = True
        nb._cone_timer = 1.0
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        gv._nebula_boss = nb
        gv._nebula_gas_clouds = []
        gv._nebula_cone_tick_cd = 0.0
        hp_before = gv.player.hp
        _ul.update_nebula_boss(gv, 1 / 60)
        assert gv.player.hp < hp_before


class _StubNebulaBoss:
    """Minimal stand-in for NebulaBossShip that ``update_nebula_boss``
    can tick without running the full BossAlienShip update path
    (which would require the zone's asteroid list + a valid laser
    texture).  Exposes just the attributes the helper reads."""

    def __init__(self, x: float, y: float):
        self.center_x = x
        self.center_y = y
        self.hp = 100
        self.max_hp = 100
        self._charging = False
        self._cone_active = False
        self._cone_timer = 0.0
        self._cone_dir_x = 1.0
        self._cone_dir_y = 0.0

    def update_boss(self, *a, **kw):
        return []

    def tick_nebula(self, *a, **kw):
        return None

    def cone_contains_point(self, px, py) -> bool:
        from constants import NEBULA_BOSS_CONE_RANGE, NEBULA_BOSS_CONE_WIDTH
        if not self._cone_active:
            return False
        dx = px - self.center_x
        dy = py - self.center_y
        forward = dx * self._cone_dir_x + dy * self._cone_dir_y
        if forward < 0 or forward > NEBULA_BOSS_CONE_RANGE:
            return False
        perp_x = dx - forward * self._cone_dir_x
        perp_y = dy - forward * self._cone_dir_y
        perp = math.hypot(perp_x, perp_y)
        half = (NEBULA_BOSS_CONE_WIDTH / 2.0) * (forward / NEBULA_BOSS_CONE_RANGE)
        return perp <= half


# ── GasCloudProjectile + NebulaBossShip unit-level checks (need GL) ───────

class TestGasCloudGeometry:
    def test_velocity_from_heading_0_is_straight_up(self, real_window):
        from sprites.nebula_boss import GasCloudProjectile
        from constants import NEBULA_BOSS_GAS_SPEED
        c = GasCloudProjectile(0.0, 0.0, 0.0, damage=10.0)
        assert c._vx == pytest.approx(0.0)
        assert c._vy == pytest.approx(NEBULA_BOSS_GAS_SPEED)

    def test_cloud_expires_after_500px(self, real_window):
        from sprites.nebula_boss import GasCloudProjectile
        from constants import NEBULA_BOSS_GAS_RANGE, NEBULA_BOSS_GAS_SPEED
        c = GasCloudProjectile(0.0, 0.0, 0.0, damage=10.0)
        dt = (NEBULA_BOSS_GAS_RANGE + 1) / NEBULA_BOSS_GAS_SPEED
        assert c.update_gas(dt) is True

    def test_cloud_does_not_expire_before_500px(self, real_window):
        from sprites.nebula_boss import GasCloudProjectile
        from constants import NEBULA_BOSS_GAS_RANGE, NEBULA_BOSS_GAS_SPEED
        c = GasCloudProjectile(0.0, 0.0, 0.0, damage=10.0)
        dt = (NEBULA_BOSS_GAS_RANGE / 2) / NEBULA_BOSS_GAS_SPEED
        assert c.update_gas(dt) is False

    def test_contains_point(self, real_window):
        from sprites.nebula_boss import GasCloudProjectile
        from constants import NEBULA_BOSS_GAS_RADIUS
        c = GasCloudProjectile(100.0, 100.0, 0.0, damage=10.0)
        assert c.contains_point(100.0, 100.0) is True
        assert c.contains_point(
            100.0 + NEBULA_BOSS_GAS_RADIUS - 1, 100.0) is True
        assert c.contains_point(
            100.0 + NEBULA_BOSS_GAS_RADIUS + 10, 100.0) is False


class TestConeGeometry:
    def test_cone_active_east_hits_forward_point(self, real_window):
        from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
        tex = load_nebula_boss_texture()
        nb = NebulaBossShip(tex, tex, 500.0, 500.0, 0.0, 0.0)
        nb._cone_active = True
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        assert nb.cone_contains_point(600.0, 500.0) is True

    def test_cone_rejects_backward(self, real_window):
        from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
        tex = load_nebula_boss_texture()
        nb = NebulaBossShip(tex, tex, 500.0, 500.0, 0.0, 0.0)
        nb._cone_active = True
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        assert nb.cone_contains_point(400.0, 500.0) is False

    def test_cone_rejects_beyond_range(self, real_window):
        from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
        from constants import NEBULA_BOSS_CONE_RANGE
        tex = load_nebula_boss_texture()
        nb = NebulaBossShip(tex, tex, 500.0, 500.0, 0.0, 0.0)
        nb._cone_active = True
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        assert nb.cone_contains_point(
            500.0 + NEBULA_BOSS_CONE_RANGE + 10, 500.0) is False

    def test_cone_rejects_outside_half_width(self, real_window):
        from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
        from constants import NEBULA_BOSS_CONE_RANGE, NEBULA_BOSS_CONE_WIDTH
        tex = load_nebula_boss_texture()
        nb = NebulaBossShip(tex, tex, 500.0, 500.0, 0.0, 0.0)
        nb._cone_active = True
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        assert nb.cone_contains_point(
            500.0 + NEBULA_BOSS_CONE_RANGE - 1,
            500.0 + NEBULA_BOSS_CONE_WIDTH) is False

    def test_inactive_cone_always_rejects(self, real_window):
        from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
        tex = load_nebula_boss_texture()
        nb = NebulaBossShip(tex, tex, 0.0, 0.0, 0.0, 0.0)
        nb._cone_active = False
        assert nb.cone_contains_point(1.0, 0.0) is False


class TestQWIMenuAPI:
    def test_click_button_returns_spawn_action(self, real_window):
        from qwi_menu import QWIMenu
        m = QWIMenu()
        m.open = True
        bx, by, bw, bh = m._btn_rect()
        assert m.on_mouse_press(bx + bw // 2, by + bh // 2) == "spawn_nebula_boss"

    def test_click_outside_panel_closes(self, real_window):
        from qwi_menu import QWIMenu
        m = QWIMenu()
        m.open = True
        assert m.on_mouse_press(-100, -100) is None
        assert m.open is False

    def test_click_inside_panel_off_button_returns_none(self, real_window):
        from qwi_menu import QWIMenu
        m = QWIMenu()
        m.open = True
        px, py = m._panel_origin()
        assert m.on_mouse_press(px + 50, py + 160) is None
        assert m.open is True

    def test_closed_menu_ignores_clicks(self, real_window):
        from qwi_menu import QWIMenu
        m = QWIMenu()
        m.open = False
        bx, by, bw, bh = m._btn_rect()
        assert m.on_mouse_press(bx, by) is None


# ── Slow effect on movement ───────────────────────────────────────────────

class TestSlowEffectHalvesMovement:
    def test_slow_timer_halves_effective_dt(self, real_game_view):
        """While ``_nebula_slow_timer > 0`` the movement update
        passes ``dt * NEBULA_BOSS_SLOW_FACTOR`` to the player."""
        import update_logic as _ul
        from constants import NEBULA_BOSS_SLOW_FACTOR
        gv = real_game_view
        _setup_main_with_station(gv)
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        gv.player.hp = gv.player.max_hp
        gv._nebula_slow_timer = 1.0

        # Stub apply_input to record the dt it received.
        dts = []
        orig = gv.player.apply_input
        gv.player.apply_input = lambda dt, *a, **kw: dts.append(dt)
        try:
            _ul.update_movement(gv, 1 / 60)
        finally:
            gv.player.apply_input = orig

        assert dts, "apply_input not called"
        assert dts[0] == pytest.approx((1 / 60) * NEBULA_BOSS_SLOW_FACTOR)
