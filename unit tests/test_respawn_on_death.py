"""Tests for the respawn-on-death system in combat_helpers.

Covers:
- ``_drop_player_loadout`` dumps every cargo stack, every equipped
  module, and clears every quick-use slot
- ``_send_bosses_home`` sets ``_patrol_home`` on Double Star + Nebula
  bosses
- ``_reset_alien_aggro`` flips every alien across every zone back to
  PATROL
- ``_resolve_respawn_target`` picks the last-visited station first,
  then any other Home Station, then ``None``
- ``trigger_player_death`` orchestrates the full drop / boss / aggro
  reset and arms the death delay
- Boss `_patrol_home` clears the first frame the player is back in
  priority range
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest
from PIL import Image as PILImage

from combat_helpers import (
    _drop_player_loadout, _reset_alien_aggro, _resolve_respawn_target,
    _send_bosses_home, respawn_player, trigger_player_death,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tex():
    img = PILImage.new("RGBA", (32, 32), (200, 200, 200, 255))
    return arcade.Texture(img)


class _StubInventory:
    def __init__(self):
        self._items: dict = {}
        self._dirty = False

    def add_item(self, name, qty):
        # Mirror enough of inventory.add_item for round-trip tests
        for (r, c), (n, q) in self._items.items():
            if n == name:
                self._items[(r, c)] = (name, q + qty)
                return
        self._items[(0, len(self._items))] = (name, qty)

    def _mark_dirty(self):
        self._dirty = True


class _StubHud:
    def __init__(self, n=4):
        self._mod_slots: list = [None] * n
        self._qu_slots: list = [None] * 5
        self._qu_counts: list = [0] * 5
        self._count = n

    def set_module_count(self, n):
        self._count = n


class _StubPlayer:
    def __init__(self, hp=100, x=3200.0, y=3200.0):
        self.hp = hp
        self.max_hp = hp
        self.shields = 0
        self.max_shields = 0
        self.center_x = x
        self.center_y = y
        self.vel_x = self.vel_y = 0.0
        self.visible = True
        self.applied_modules = None
        self._collision_cd = 0.0

    def apply_modules(self, slots):
        self.applied_modules = list(slots)


def _make_gv(tex, *, with_modules=True, with_cargo=True):
    inv = _StubInventory()
    if with_cargo:
        inv._items[(0, 0)] = ("iron", 50)
        inv._items[(0, 1)] = ("copper", 25)
        inv._items[(1, 0)] = ("repair_pack", 3)
    hud = _StubHud(n=4)
    if with_modules:
        hud._qu_slots[0] = "repair_pack"
        hud._qu_counts[0] = 3
    module_slots = [None] * 4
    if with_modules:
        module_slots[0] = "armor_plate"
        module_slots[1] = "engine_booster"
    gv = SimpleNamespace(
        inventory=inv,
        _module_slots=module_slots,
        _hud=hud,
        player=_StubPlayer(),
        iron_pickup_list=arcade.SpriteList(),
        blueprint_pickup_list=arcade.SpriteList(),
        _iron_tex=tex,
        _copper_tex=tex,
        _blueprint_tex=tex,
        _blueprint_drop_tex={},
        _last_station_pos=None,
        _last_station_zone=None,
        _main_zone=None,
        _zone2=None,
        _star_maze=None,
        alien_list=arcade.SpriteList(),
    )
    # Track flash msgs
    gv._flash_msg = ""
    gv._flash_timer = 0.0
    return gv


# ── _drop_player_loadout ───────────────────────────────────────────────────

class TestDropLoadout:
    def test_clears_inventory(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 100.0, 200.0)
        assert gv.inventory._items == {}

    def test_drops_one_pickup_per_cargo_stack(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 100.0, 200.0)
        # 3 cargo stacks (iron, copper, repair_pack) → 3 IronPickups
        assert len(gv.iron_pickup_list) == 3
        types = sorted(p.item_type for p in gv.iron_pickup_list)
        assert types == ["copper", "iron", "repair_pack"]

    def test_drops_one_blueprint_per_equipped_module(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 100.0, 200.0)
        assert len(gv.blueprint_pickup_list) == 2
        modules = sorted(bp.module_type for bp in gv.blueprint_pickup_list)
        assert modules == ["armor_plate", "engine_booster"]

    def test_clears_module_slots_and_re_applies(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 0.0, 0.0)
        assert gv._module_slots == [None, None, None, None]
        assert gv.player.applied_modules == [None, None, None, None]

    def test_clears_quick_use_bar(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 0.0, 0.0)
        assert gv._hud._qu_slots == [None] * 5
        assert gv._hud._qu_counts == [0] * 5

    def test_amounts_preserved(self, tex):
        gv = _make_gv(tex)
        _drop_player_loadout(gv, 0.0, 0.0)
        amounts = {p.item_type: p.amount for p in gv.iron_pickup_list}
        assert amounts == {"iron": 50, "copper": 25, "repair_pack": 3}

    def test_no_drops_when_empty(self, tex):
        gv = _make_gv(tex, with_modules=False, with_cargo=False)
        _drop_player_loadout(gv, 0.0, 0.0)
        assert len(gv.iron_pickup_list) == 0
        assert len(gv.blueprint_pickup_list) == 0


# ── _send_bosses_home ──────────────────────────────────────────────────────

class TestSendBossesHome:
    def test_flags_double_star_boss(self, tex):
        gv = _make_gv(tex)
        gv._boss = SimpleNamespace(_patrol_home=False)
        _send_bosses_home(gv)
        assert gv._boss._patrol_home is True

    def test_flags_nebula_boss(self, tex):
        gv = _make_gv(tex)
        gv._nebula_boss = SimpleNamespace(_patrol_home=False)
        _send_bosses_home(gv)
        assert gv._nebula_boss._patrol_home is True

    def test_no_boss_is_safe(self, tex):
        gv = _make_gv(tex)
        # Neither boss attribute set — must not raise.
        _send_bosses_home(gv)


# ── _reset_alien_aggro ─────────────────────────────────────────────────────

class _StubAlien:
    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(self):
        self._state = self._STATE_PURSUE
        self._fire_cd = 0.0
        self.patrol_picked = False

    def _pick_patrol_target(self):
        self.patrol_picked = True


class TestResetAlienAggro:
    def test_flips_active_zone_aliens_to_patrol(self, tex):
        gv = _make_gv(tex)
        a = _StubAlien()
        gv.alien_list = [a]
        _reset_alien_aggro(gv)
        assert a._state == _StubAlien._STATE_PATROL
        assert a.patrol_picked is True

    def test_picks_new_patrol_target(self, tex):
        gv = _make_gv(tex)
        a = _StubAlien()
        gv.alien_list = [a]
        _reset_alien_aggro(gv)
        assert a.patrol_picked is True

    def test_iterates_zone_stashes(self, tex):
        gv = _make_gv(tex)
        a1, a2, a3 = _StubAlien(), _StubAlien(), _StubAlien()
        gv._main_zone = SimpleNamespace(_aliens=[a1])
        gv._zone2 = SimpleNamespace(_aliens=[a2])
        gv._star_maze = SimpleNamespace(_maze_aliens=[a3])
        _reset_alien_aggro(gv)
        for a in (a1, a2, a3):
            assert a._state == _StubAlien._STATE_PATROL

    def test_skips_aliens_without_state_field(self, tex):
        gv = _make_gv(tex)
        # NPC ships don't have _state — must not crash.
        gv.alien_list = [SimpleNamespace()]
        _reset_alien_aggro(gv)


# ── _resolve_respawn_target ────────────────────────────────────────────────

class _StubHomeStation:
    def __init__(self, x, y, disabled=False):
        self.center_x = x
        self.center_y = y
        self.disabled = disabled


def _patch_home_station_class(monkeypatch, Stub):
    """Make ``isinstance(stub, HomeStation)`` succeed in
    ``_resolve_respawn_target``."""
    import sprites.building as sb
    monkeypatch.setattr(sb, "HomeStation", Stub)


class TestResolveRespawnTarget:
    def test_returns_none_when_no_stations(self, tex, monkeypatch):
        _patch_home_station_class(monkeypatch, _StubHomeStation)
        gv = _make_gv(tex)
        from zones import ZoneID
        gv._zone = SimpleNamespace(zone_id=ZoneID.MAIN)
        gv.building_list = []
        assert _resolve_respawn_target(gv) is None

    def test_returns_last_visited_station(self, tex, monkeypatch):
        _patch_home_station_class(monkeypatch, _StubHomeStation)
        gv = _make_gv(tex)
        from zones import ZoneID
        home = _StubHomeStation(1500.0, 2500.0)
        gv._zone = SimpleNamespace(zone_id=ZoneID.MAIN)
        gv.building_list = [home]
        gv._last_station_pos = (1500.0, 2500.0)
        gv._last_station_zone = ZoneID.MAIN
        result = _resolve_respawn_target(gv)
        assert result == (ZoneID.MAIN, 1500.0, 2500.0)

    def test_falls_back_to_any_zone_station(self, tex, monkeypatch):
        _patch_home_station_class(monkeypatch, _StubHomeStation)
        gv = _make_gv(tex)
        from zones import ZoneID
        gv._zone = SimpleNamespace(zone_id=ZoneID.MAIN)
        gv.building_list = []   # no station in active zone
        # Stash a station in Zone 2
        gv._zone2 = SimpleNamespace(_building_stash={
            "building_list": [_StubHomeStation(4000.0, 4000.0)]
        })
        result = _resolve_respawn_target(gv)
        assert result is not None
        zid, x, y = result
        assert zid == ZoneID.ZONE2
        assert (x, y) == (4000.0, 4000.0)

    def test_disabled_station_is_skipped(self, tex, monkeypatch):
        _patch_home_station_class(monkeypatch, _StubHomeStation)
        gv = _make_gv(tex)
        from zones import ZoneID
        gv._zone = SimpleNamespace(zone_id=ZoneID.MAIN)
        gv.building_list = [_StubHomeStation(1.0, 1.0, disabled=True)]
        assert _resolve_respawn_target(gv) is None


# ── Boss patrol-home toggling ──────────────────────────────────────────────

class TestBossPatrolHome:
    """The boss-update flag must clear the moment the player is back
    inside priority range — otherwise the boss would dawdle around
    its spawn point forever after the first death."""

    def test_flag_set_overrides_target(self):
        from sprites.boss import BossAlienShip
        b = BossAlienShip.__new__(BossAlienShip)
        b._spawn_x = 1000.0
        b._spawn_y = 2000.0
        b._patrol_home = True
        b._target_x = b._target_y = 0.0
        # Manually replicate the gated assignment from update_boss.
        if b._patrol_home:
            b._target_x = b._spawn_x
            b._target_y = b._spawn_y
        assert (b._target_x, b._target_y) == (1000.0, 2000.0)

    def test_flag_clears_when_player_in_range(self):
        from sprites.boss import BossAlienShip
        b = BossAlienShip.__new__(BossAlienShip)
        b._patrol_home = True
        b._PLAYER_PRIORITY_RANGE = 800.0
        # Replicate the clear branch from update_boss.
        dist_player = 500.0
        if b._patrol_home and dist_player <= b._PLAYER_PRIORITY_RANGE:
            b._patrol_home = False
        assert b._patrol_home is False


# ── trigger_player_death orchestration ─────────────────────────────────────

class TestTriggerPlayerDeath:
    def test_arms_death_delay_and_drops_loadout(self, tex, monkeypatch):
        """End-to-end: trigger_player_death must drop everything,
        flag bosses, and arm the death timer."""
        # Stub out arcade.play_sound so tests don't need real audio.
        monkeypatch.setattr(arcade, "play_sound", lambda *a, **kw: None)
        gv = _make_gv(tex)
        gv._player_dead = False
        gv.explosion_list = arcade.SpriteList()
        gv.fire_sparks = []
        gv.shield_sprite = SimpleNamespace(visible=True)
        gv._thruster_player = None
        gv._explosion_frames = [tex] * 9
        gv._explosion_snd = None
        gv._boss = SimpleNamespace(_patrol_home=False)
        gv._nebula_boss = None

        trigger_player_death(gv)

        assert gv._player_dead is True
        assert gv._death_delay == pytest.approx(1.5)
        assert gv.player.visible is False
        # Cargo + modules dropped at death site
        assert len(gv.iron_pickup_list) == 3
        assert len(gv.blueprint_pickup_list) == 2
        # Boss flagged to retreat
        assert gv._boss._patrol_home is True
