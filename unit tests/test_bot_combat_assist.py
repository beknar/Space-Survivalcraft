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
def _reset_assist_state(monkeypatch):
    """Each test starts with a fresh assist state.  Default the
    RNG to "no melee" so legacy range-based tests aren't randomly
    flipped into the melee-locked path; melee tests override
    _get_random themselves."""
    ca._state.update({
        "enabled": True,
        "fired_this_tick": False,
        "last_threat_dist": -1.0,
        "last_threat_type": "",
        "last_aim_heading": 0.0,
        "engagements": 0,
        "_holdover_until": 0.0,
        "melee_engaged": False,
        "_had_threat_last_tick": False,
        "_melee_engaged_until": 0.0,
        "misty_step_fires": 0,
        "force_wall_fires": 0,
        "death_blossom_fires": 0,
        "drone_deploys": 0,
    })
    monkeypatch.setattr(ca, "_get_random", lambda: 0.99)  # ranged
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

    def test_get_state_reports_melee_engaged(self):
        s = ca.get_state()
        assert "melee_engaged" in s
        assert s["melee_engaged"] is False


# ── Melee-commit dice + weapon lock ───────────────────────────────────────


class TestMeleeCommitRoll:
    """The dice roll fires on the tick that transitions
    no-threat -> threat (a "fresh engagement").  On hit the
    assist locks the Energy Blade for the rest of the
    engagement; on miss it falls back to the range-based
    auto-switch.  The lock survives a brief target loss
    (MELEE_LOCK_HOLDOVER_S) so a one-frame line-of-sight gap
    doesn't reroll mid-fight."""

    def test_low_roll_commits_to_melee(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv(aliens=[_alien(400, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True

    def test_high_roll_stays_ranged(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.99)
        gv = _gv(aliens=[_alien(400, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False

    def test_threshold_is_strict_lt(self, monkeypatch):
        # roll == MELEE_COMMIT_CHANCE -> miss.
        monkeypatch.setattr(ca, "_get_random",
                            lambda: ca.MELEE_COMMIT_CHANCE)
        gv = _gv(aliens=[_alien(400, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False

    def test_no_threat_does_not_roll(self, monkeypatch):
        # If the RNG would commit but there's no threat, the flag
        # must stay False -- we only roll on engagement transitions.
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv()  # no aliens
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False

    def test_does_not_re_roll_each_tick(self, monkeypatch):
        """First tick rolls and commits.  Subsequent ticks with
        the same threat must not re-roll, even if the RNG would
        now miss."""
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv(aliens=[_alien(400, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True
        # Flip the RNG -- no effect because we're already engaged.
        monkeypatch.setattr(ca, "_get_random", lambda: 0.99)
        for _ in range(10):
            ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True


class TestMeleeWeaponLock:
    """When committed, the assist forces the Energy Blade every
    frame regardless of distance -- otherwise the per-frame
    range auto-switch would fight the autopilot's slower 10 Hz
    Tab presses."""

    def test_committed_locks_melee_at_long_range(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        # Threat at 600 px -- ranged would normally pick Basic
        # Laser; with melee committed, must lock to Melee.
        gv = _gv(aliens=[_alien(600, 0)],
                 weapon_idx=0)  # start on Basic Laser
        ca.tick(gv, 1 / 60, original_fire=False)
        assert gv._weapons[gv._weapon_idx].name == "Melee"

    def test_uncommitted_uses_range_based_choice(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.99)
        gv = _gv(aliens=[_alien(600, 0)],
                 weapon_idx=0)
        ca.tick(gv, 1 / 60, original_fire=False)
        # 600 > MELEE_RANGE (100) -> Basic Laser.
        assert gv._weapons[gv._weapon_idx].name == "Basic Laser"


class TestMeleeLockGrace:
    """The melee lock survives a brief target-loss window so a
    momentary detection gap doesn't drop the commitment."""

    def test_lock_holds_through_short_target_loss(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv(aliens=[_alien(200, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True
        # Target gone, but the grace period hasn't elapsed.
        gv.alien_list = []
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True

    def test_lock_clears_after_grace_elapses(self, monkeypatch):
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv(aliens=[_alien(200, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True
        # Force the grace timer to be in the past, then tick with
        # no target -- lock must drop.
        ca._state["_melee_engaged_until"] = 0.0
        gv.alien_list = []
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False

    def test_fresh_engagement_after_clear_rerolls(self, monkeypatch):
        # First engagement -- commit.
        monkeypatch.setattr(ca, "_get_random", lambda: 0.0)
        gv = _gv(aliens=[_alien(200, 0)])
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is True
        # Force lock + had-threat to clear (grace elapsed, no target).
        ca._state["_melee_engaged_until"] = 0.0
        gv.alien_list = []
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False
        assert ca._state["_had_threat_last_tick"] is False
        # New engagement, this time RNG says miss.
        monkeypatch.setattr(ca, "_get_random", lambda: 0.99)
        gv.alien_list = [_alien(200, 0)]
        ca.tick(gv, 1 / 60, original_fire=False)
        assert ca._state["melee_engaged"] is False, (
            "fresh engagement must re-roll the dice, not inherit"
            " the prior engagement's commitment")


# ── Nebula-tier module-use helpers (2026-05-24) ───────────────────────────


def _gv_with_modules(modules, *, px=4000.0, py=4000.0, heading=0.0,
                     shields=120, max_shields=120,
                     ability_meter=100.0, gas_clouds=(),
                     aliens=(), missiles=0,
                     misty_cd=0.0, force_cd=0.0,
                     death_blossom_active=False):
    """gv stub with the attributes the new module helpers read.
    Tests can drive each helper in isolation without needing a
    real GameView."""

    class _Inv:
        def __init__(self, items):
            self._items = dict(items)

        def count_item(self, key):
            return self._items.get(key, 0)

        def remove_item(self, key, n=1):
            self._items[key] = max(0, self._items.get(key, 0) - n)

    class _Zone:
        def __init__(self, clouds):
            self._clouds = clouds
            self.rooms = None
            self.walls = None
    weapons = [_weapon("Basic Laser"), _weapon("Melee")]
    inv_items = {}
    if missiles:
        inv_items["missile"] = missiles
    return SimpleNamespace(
        player=SimpleNamespace(
            center_x=px, center_y=py, heading=heading, guns=1,
            shields=shields, max_shields=max_shields),
        alien_list=list(aliens),
        _boss=None,
        _nebula_boss=None,
        _weapons=weapons,
        _weapon_idx=0,
        _active_weapon=weapons[0],
        _module_slots=list(modules),
        _ability_meter=ability_meter,
        _misty_step_cd=misty_cd,
        _force_wall_cd=force_cd,
        _force_walls=[],
        _death_blossom_active=death_blossom_active,
        _death_blossom_timer=0.0,
        _death_blossom_missiles_left=0,
        _zone=_Zone(list(gas_clouds)),
        inventory=_Inv(inv_items),
        _escape_menu=SimpleNamespace(open=False),
        _player_dead=False,
        _hud=SimpleNamespace(
            get_quick_use=lambda i: None,
            set_quick_use=lambda i, t, c: None),
        _flash_game_msg=lambda *a, **kw: None,
        _misty_step_snd=None,
        _force_wall_snd=None,
        _use_glow=(0, 0, 0, 0),
        _use_glow_timer=0.0,
    )


def _cloud(x, y, r):
    return SimpleNamespace(center_x=x, center_y=y, radius=r)


class TestMaybeFireMistyStepGas:
    """The assist fires misty_step in the escape direction when
    the player is inside a damaging gas cloud."""

    def test_no_fire_without_module_installed(self, monkeypatch):
        gv = _gv_with_modules(
            modules=[], gas_clouds=[_cloud(4000.0, 4000.0, 200.0)])
        # If the module isn't installed, _maybe_fire returns False
        # immediately without ever calling the (un-installable)
        # game-side handler.
        assert ca._maybe_fire_misty_step_gas(gv) is False
        assert ca._state["misty_step_fires"] == 0

    def test_no_fire_outside_any_cloud(self, monkeypatch):
        gv = _gv_with_modules(
            modules=["misty_step"],
            gas_clouds=[_cloud(0.0, 0.0, 100.0)])
        # Player far from the cloud.
        assert ca._maybe_fire_misty_step_gas(gv) is False
        assert ca._state["misty_step_fires"] == 0

    def test_fires_when_inside_cloud(self, monkeypatch):
        """Player sitting at the cloud centre + module installed +
        ability budget + no cooldown -> fires and increments the
        counter.  We monkey-patch ``fire_misty_step`` so the test
        runs without spinning up a full GameView."""
        gv = _gv_with_modules(
            modules=["misty_step"], px=4000.0, py=4000.0,
            gas_clouds=[_cloud(3900.0, 4000.0, 250.0)])
        called: list = []
        from input_handlers_keys import fire_misty_step  # noqa: F401

        def fake_fire(g, key):
            called.append(key)
            return True

        import input_handlers_keys
        monkeypatch.setattr(
            input_handlers_keys, "fire_misty_step", fake_fire)
        fired = ca._maybe_fire_misty_step_gas(gv)
        assert fired is True
        assert ca._state["misty_step_fires"] == 1
        assert len(called) == 1

    def test_choose_escape_key_picks_axis_furthest_from_cloud(self):
        """Cloud east of player + heading=0 (N) -> escape ray
        points west -> pick A (strafe-left)."""
        import arcade
        gv = _gv_with_modules(modules=["misty_step"],
                              px=0.0, py=0.0, heading=0.0)
        key = ca._misty_step_escape_key(
            gv, (200.0, 0.0, 100.0))  # cloud east; player west
        assert key == arcade.key.A


class TestMaybeFireForceWall:
    """Force wall arms when shields drop under the threshold AND
    a threat is currently behind the ship."""

    def test_no_fire_without_module_installed(self):
        gv = _gv_with_modules(modules=[], shields=10, max_shields=120)
        threat = SimpleNamespace(center_x=-100.0, center_y=0.0, hp=50)
        assert ca._maybe_fire_force_wall(gv, threat, 100.0) is False

    def test_no_fire_above_shields_threshold(self):
        gv = _gv_with_modules(modules=["force_wall"],
                              shields=120, max_shields=120)
        threat = SimpleNamespace(center_x=-100.0, center_y=0.0, hp=50)
        assert ca._maybe_fire_force_wall(gv, threat, 100.0) is False

    def test_no_fire_when_threat_in_front(self):
        gv = _gv_with_modules(modules=["force_wall"], px=4000.0,
                              py=4000.0, shields=20, max_shields=120,
                              heading=0.0)
        # Heading=0 -> forward vector is (0, +y).  Threat directly
        # north of the player is "in front" -> force wall (which
        # plants behind) would be wasted.
        threat = SimpleNamespace(center_x=4000.0, center_y=4400.0, hp=50)
        assert ca._maybe_fire_force_wall(gv, threat, 400.0) is False

    def test_fires_when_threat_behind_and_shields_low(
            self, monkeypatch):
        gv = _gv_with_modules(modules=["force_wall"], px=4000.0,
                              py=4000.0, shields=20, max_shields=120,
                              heading=0.0, ability_meter=100.0,
                              force_cd=0.0)
        # Heading=0 (north) + threat south of player -> behind.
        threat = SimpleNamespace(center_x=4000.0, center_y=3600.0, hp=50)

        import input_handlers_keys
        called: list = []

        def fake_force(g):
            called.append(True)
            g._force_wall_cd = 2.0  # simulate game-side cooldown
            g._ability_meter -= 30.0

        monkeypatch.setattr(
            input_handlers_keys, "_try_force_wall", fake_force)
        fired = ca._maybe_fire_force_wall(gv, threat, 400.0)
        assert fired is True
        assert ca._state["force_wall_fires"] == 1
        assert called == [True]


class TestMaybeFireDeathBlossom:
    """Death Blossom fires only when the close-range alien cluster
    is dense enough (>= DEATH_BLOSSOM_CLUSTER_MIN inside the
    DEATH_BLOSSOM_CLUSTER_RANGE)."""

    def test_no_fire_without_module_installed(self):
        # Six aliens at the same spot as the player (px=4000 by
        # default) -- all inside cluster range -- but module missing.
        gv = _gv_with_modules(
            modules=[], missiles=20,
            aliens=[_alien(4000, 4000)] * 6)
        assert ca._maybe_fire_death_blossom(gv) is False

    def test_no_fire_without_missiles(self):
        gv = _gv_with_modules(
            modules=["death_blossom"], missiles=0,
            aliens=[_alien(4000, 4000)] * 6)
        assert ca._maybe_fire_death_blossom(gv) is False

    def test_no_fire_when_below_cluster_min(self, monkeypatch):
        # Two aliens close -- below the default threshold of 4.
        gv = _gv_with_modules(
            modules=["death_blossom"], missiles=20,
            aliens=[_alien(4000, 4000), _alien(4050, 4000)])
        assert ca._maybe_fire_death_blossom(gv) is False

    def test_fires_when_cluster_dense(self, monkeypatch):
        # Six aliens all within the death-blossom range of the
        # player (px=4000, py=4000 by default).
        aliens = [_alien(4000 + i * 20, 4000) for i in range(6)]
        gv = _gv_with_modules(
            modules=["death_blossom"], missiles=20, aliens=aliens)

        import input_handlers_keys
        called: list = []

        def fake_blossom(g):
            called.append(True)
            g._death_blossom_active = True

        monkeypatch.setattr(
            input_handlers_keys, "_try_death_blossom", fake_blossom)
        fired = ca._maybe_fire_death_blossom(gv)
        assert fired is True
        assert ca._state["death_blossom_fires"] == 1
        assert called == [True]

    def test_skips_aliens_beyond_close_range(self, monkeypatch):
        # Aliens FAR beyond DEATH_BLOSSOM_CLUSTER_RANGE_PX from
        # the player (px=4000).
        far = 4000 + ca.DEATH_BLOSSOM_CLUSTER_RANGE_PX + 100.0
        aliens = [_alien(far, 4000 + i * 10) for i in range(6)]
        gv = _gv_with_modules(
            modules=["death_blossom"], missiles=20, aliens=aliens)
        assert ca._maybe_fire_death_blossom(gv) is False



# ── Drone dispatch ────────────────────────────────────────────────────────


def _drone_gv(*, active_drone=None, mining=False,
              combat_drones=0, mining_drones=0, aliens=(),
              px=0.0, py=0.0):
    """gv stub for ``_maybe_deploy_drone``: active drone, active weapon
    (mines_rock decides the variant), ship inventory counts, and the
    alien list for the combat-drone cluster test."""
    weapon = SimpleNamespace(
        name="Mining Beam" if mining else "Basic Laser",
        mines_rock=mining)
    items = {}
    if combat_drones:
        items["combat_drone"] = combat_drones
    if mining_drones:
        items["mining_drone"] = mining_drones

    class _Inv:
        def __init__(self, it):
            self._items = dict(it)

        def count_item(self, k):
            return self._items.get(k, 0)

    return SimpleNamespace(
        _active_drone=active_drone,
        _active_weapon=weapon,
        inventory=_Inv(items),
        player=SimpleNamespace(center_x=px, center_y=py),
        alien_list=list(aliens),
    )


def _patch_deploy(monkeypatch):
    """Replace the heavy ``combat_helpers.deploy_drone`` (real sprite
    spawn) with a stub that just consumes a charge + sets _active_drone,
    so we test the GATING in _maybe_deploy_drone, not the sprite path."""
    import combat_helpers
    calls: list = []

    def _stub(gv):
        calls.append(gv)
        w = gv._active_weapon
        key = ("mining_drone" if getattr(w, "mines_rock", False)
               else "combat_drone")
        if gv.inventory.count_item(key) > 0:
            gv.inventory._items[key] -= 1
            gv._active_drone = SimpleNamespace(_kind=key)
    monkeypatch.setattr(combat_helpers, "deploy_drone", _stub)
    return calls


class TestMaybeDeployDrone:
    def test_deploys_combat_drone_under_cluster(self, monkeypatch):
        calls = _patch_deploy(monkeypatch)
        aliens = [_alien(100.0 * i, 0.0) for i in range(3)]  # 3 within range
        gv = _drone_gv(combat_drones=5, aliens=aliens)
        assert ca._maybe_deploy_drone(gv) is True
        assert len(calls) == 1
        assert ca._state["drone_deploys"] == 1
        assert gv._active_drone is not None

    def test_no_combat_drone_without_cluster(self, monkeypatch):
        calls = _patch_deploy(monkeypatch)
        gv = _drone_gv(combat_drones=5, aliens=[_alien(50.0, 0.0)])  # 1 alien
        assert ca._maybe_deploy_drone(gv) is False
        assert calls == []

    def test_no_deploy_when_drone_already_active(self, monkeypatch):
        calls = _patch_deploy(monkeypatch)
        aliens = [_alien(100.0 * i, 0.0) for i in range(5)]
        gv = _drone_gv(active_drone=SimpleNamespace(_kind="combat_drone"),
                       combat_drones=5, aliens=aliens)
        assert ca._maybe_deploy_drone(gv) is False
        assert calls == []

    def test_no_deploy_without_inventory(self, monkeypatch):
        calls = _patch_deploy(monkeypatch)
        aliens = [_alien(100.0 * i, 0.0) for i in range(5)]
        gv = _drone_gv(combat_drones=0, aliens=aliens)
        assert ca._maybe_deploy_drone(gv) is False
        assert calls == []

    def test_deploys_mining_drone_without_threat_gate(self, monkeypatch):
        # Mining weapon active, no aliens -> mining drone still deploys
        # (it speeds up mining; no cluster requirement).
        calls = _patch_deploy(monkeypatch)
        gv = _drone_gv(mining=True, mining_drones=5, aliens=())
        assert ca._maybe_deploy_drone(gv) is True
        assert len(calls) == 1
        assert gv._active_drone._kind == "mining_drone"

    def test_far_aliens_do_not_count_as_cluster(self, monkeypatch):
        calls = _patch_deploy(monkeypatch)
        far = ca.DRONE_DEPLOY_RANGE_PX + 500.0
        aliens = [_alien(far, 100.0 * i) for i in range(5)]  # all out of range
        gv = _drone_gv(combat_drones=5, aliens=aliens)
        assert ca._maybe_deploy_drone(gv) is False
        assert calls == []
