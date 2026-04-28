"""Unit tests for ``bot_combat_assist`` -- the in-process auto-aim
+ auto-fire defence layer that monkey-patches ``update_logic
.update_weapons`` when ``COO_BOT_API`` is set.

The module is pure-Python logic (no arcade window required) so
we drive it with ``SimpleNamespace`` stubs for ``gv`` instead of
spinning up a real GameView.  Tests focus on the behaviours
that a future refactor could break:

  * Threat selection (closest live hostile within DETECT_RANGE).
  * Weapon switching by range (Energy Blade / Basic Laser).
  * Heading snap to face the target.
  * Menu state suppression (assist must never act while a modal
    is open).
  * Holdover after threat departs.
  * set_enabled / get_state surface contract.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

import bot_combat_assist as ca


# ── Helpers ───────────────────────────────────────────────────────────────


def _alien(x: float, y: float, hp: int = 50):
    return SimpleNamespace(center_x=x, center_y=y, hp=hp, name="alien")


def _weapon(name: str):
    return SimpleNamespace(name=name)


def _gv(
    px: float = 0.0,
    py: float = 0.0,
    heading: float = 0.0,
    aliens=(),
    boss=None,
    nebula_boss=None,
    weapon_idx: int = 0,
    weapons=None,
    guns: int = 1,
    flags=None,
):
    flags = flags or {}
    if weapons is None:
        weapons = [
            _weapon("Basic Laser"),
            _weapon("Mining Beam"),
            _weapon("Melee"),
        ]
    gv = SimpleNamespace(
        player=SimpleNamespace(
            center_x=px, center_y=py, heading=heading, guns=guns,
        ),
        alien_list=list(aliens),
        _boss=boss,
        _nebula_boss=nebula_boss,
        _weapons=weapons,
        _weapon_idx=weapon_idx,
        _build_menu_open=flags.get("build", False),
        _escape_menu_open=flags.get("escape", False),
        _player_dead=flags.get("dead", False),
        _dialogue_open=flags.get("dialogue", False),
        inventory=SimpleNamespace(_open=flags.get("inventory", False)),
    )
    gv._active_weapon = weapons[weapon_idx]
    return gv


@pytest.fixture(autouse=True)
def _reset_assist_state():
    """Each test starts with a fresh assist state."""
    ca._state.update({
        "enabled": True,
        "fired_this_tick": False,
        "last_threat_dist": -1.0,
        "last_threat_type": "",
        "last_aim_heading": 0.0,
        "engagements": 0,
        "_holdover_until": 0.0,
    })
    yield


# ── Threat selection ──────────────────────────────────────────────────────


class TestFindNearestThreat:
    def test_returns_none_when_no_aliens_or_boss(self):
        gv = _gv()
        threat, dist = ca._find_nearest_threat(gv)
        assert threat is None
        assert dist == float("inf")

    def test_picks_nearest_of_multiple_aliens(self):
        gv = _gv(px=0, py=0, aliens=[
            _alien(500, 0),       # 500
            _alien(100, 0),       # 100  ← nearest
            _alien(300, 400),     # 500
        ])
        threat, dist = ca._find_nearest_threat(gv)
        assert dist == pytest.approx(100.0)
        assert threat.center_x == 100

    def test_skips_dead_aliens(self):
        gv = _gv(aliens=[
            _alien(50, 0, hp=0),     # dead -- skip even though closest
            _alien(200, 0, hp=10),   # next closest live
        ])
        threat, dist = ca._find_nearest_threat(gv)
        assert dist == pytest.approx(200.0)
        assert threat.hp == 10

    def test_skips_threats_outside_detect_range(self):
        gv = _gv(aliens=[_alien(ca.DETECT_RANGE + 10, 0)])
        threat, dist = ca._find_nearest_threat(gv)
        assert threat is None

    def test_includes_alive_boss(self):
        boss = SimpleNamespace(center_x=200, center_y=0, hp=100)
        gv = _gv(boss=boss, aliens=[_alien(400, 0)])
        threat, dist = ca._find_nearest_threat(gv)
        assert threat is boss
        assert dist == pytest.approx(200.0)

    def test_includes_alive_nebula_boss(self):
        nb = SimpleNamespace(center_x=150, center_y=0, hp=300)
        gv = _gv(nebula_boss=nb)
        threat, _ = ca._find_nearest_threat(gv)
        assert threat is nb

    def test_skips_dead_boss(self):
        boss = SimpleNamespace(center_x=10, center_y=0, hp=0)
        gv = _gv(boss=boss, aliens=[_alien(300, 0)])
        threat, dist = ca._find_nearest_threat(gv)
        assert threat is not boss
        assert dist == pytest.approx(300.0)


# ── Weapon switching ──────────────────────────────────────────────────────


class TestEnsureWeapon:
    def test_switch_to_melee(self):
        gv = _gv(weapon_idx=0)        # Basic Laser
        switched = ca._ensure_weapon(gv, "Melee")
        assert switched is True
        assert gv._weapon_idx == 2

    def test_switch_to_basic_from_mining(self):
        gv = _gv(weapon_idx=1)        # Mining Beam
        ca._ensure_weapon(gv, "Basic Laser")
        assert gv._weapon_idx == 0

    def test_no_switch_when_already_active(self):
        gv = _gv(weapon_idx=0)
        switched = ca._ensure_weapon(gv, "Basic Laser")
        assert switched is False
        assert gv._weapon_idx == 0

    def test_unknown_weapon_no_op(self):
        gv = _gv(weapon_idx=0)
        ca._ensure_weapon(gv, "Plasma Cannon")
        assert gv._weapon_idx == 0

    def test_dual_gun_block_picks_first_entry(self):
        # Thunderbolt: each weapon group has 2 entries.
        weapons = [
            _weapon("Basic Laser"), _weapon("Basic Laser"),
            _weapon("Mining Beam"), _weapon("Mining Beam"),
            _weapon("Melee"),       _weapon("Melee"),
        ]
        gv = _gv(weapons=weapons, weapon_idx=0, guns=2)
        ca._ensure_weapon(gv, "Melee")
        assert gv._weapon_idx == 4


# ── tick() per-frame behaviour ────────────────────────────────────────────


class TestTick:
    def test_no_threat_returns_original_fire_unchanged(self):
        gv = _gv()
        assert ca.tick(gv, 1 / 60, original_fire=False) is False
        assert ca.tick(gv, 1 / 60, original_fire=True) is True

    def test_threat_in_laser_range_forces_fire(self):
        gv = _gv(px=0, py=0, aliens=[_alien(500, 0)])
        out = ca.tick(gv, 1 / 60, original_fire=False)
        assert out is True
        assert ca._state["fired_this_tick"] is True

    def test_heading_snaps_to_face_threat(self):
        # Threat directly east -- arcade heading 90 (0=N, CW positive).
        gv = _gv(px=0, py=0, heading=0.0, aliens=[_alien(300, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert gv.player.heading == pytest.approx(90.0, abs=0.5)

    def test_picks_melee_at_point_blank(self):
        gv = _gv(px=0, py=0, aliens=[_alien(50, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert gv._weapon_idx == 2
        assert gv._weapons[gv._weapon_idx].name == "Melee"

    def test_picks_basic_laser_at_range(self):
        gv = _gv(px=0, py=0, aliens=[_alien(500, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert gv._weapon_idx == 0
        assert gv._weapons[gv._weapon_idx].name == "Basic Laser"

    def test_disabled_assist_is_no_op(self):
        ca.set_enabled(False)
        gv = _gv(px=0, py=0, aliens=[_alien(100, 0)], heading=0.0)
        out = ca.tick(gv, 1 / 60, original_fire=False)
        assert out is False
        # Heading + weapon untouched.
        assert gv.player.heading == 0.0
        assert gv._weapon_idx == 0

    @pytest.mark.parametrize("flag", [
        "build", "inventory", "escape", "dead", "dialogue",
    ])
    def test_menu_open_suppresses_assist(self, flag):
        gv = _gv(aliens=[_alien(100, 0)], flags={flag: True})
        out = ca.tick(gv, 1 / 60, original_fire=False)
        # Assist must yield to the player while modals are open.
        assert out is False
        assert gv.player.heading == 0.0

    def test_engagements_counter_increments(self):
        gv = _gv(aliens=[_alien(200, 0)])
        before = ca._state["engagements"]
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["engagements"] == before + 1

    def test_holdover_keeps_fire_after_threat_leaves(self):
        gv = _gv(aliens=[_alien(200, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["_holdover_until"] > 0
        # Same tick, threat removed -- assist should still hold fire
        # because the holdover hasn't elapsed yet.
        gv.alien_list = []
        out = ca.tick(gv, 1 / 60, original_fire=False)
        assert out is True


# ── set_enabled / get_state contract ──────────────────────────────────────


class TestSetEnabledAndGetState:
    def test_get_state_reports_tunables(self):
        s = ca.get_state()
        assert s["detect_range"] == ca.DETECT_RANGE
        assert s["laser_range"] == ca.LASER_RANGE
        assert s["melee_range"] == ca.MELEE_RANGE

    def test_set_enabled_round_trip(self):
        s1 = ca.set_enabled(False)
        assert s1["enabled"] is False
        s2 = ca.set_enabled(True)
        assert s2["enabled"] is True

    def test_install_idempotent(self):
        # install() short-circuits when COO_BOT_API isn't set, but
        # the install flag itself should never raise.
        ca.install(SimpleNamespace())
        ca.install(SimpleNamespace())   # second call is a no-op
