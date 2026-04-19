"""5-minute soak tests for the QWI click-menu and the Nebula boss
rebuild loop.

* ``TestSoakQWIMenuOpen`` — holds the QWI overlay open for 5 min on
  top of Zone 2 so any per-frame allocation in the overlay (Text
  reposition, status-string recreation) compounds visibly over
  ~18 000 frames.

* ``TestSoakNebulaBossRebuild`` — spawn + kill + re-spawn the Nebula
  boss every ~30 s.  Mirrors the existing ``TestSoakBasicShipRebuild``
  pattern but for the boss combat pipeline (gas cloud projectile
  list, cone state, BossAlienShip _boss_projectile_list churn).

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run with:
    pytest "unit tests/integration/test_soak_qwi_and_nebula.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_zone2_with_home(gv):
    from sprites.building import create_building
    gv._transition_zone(ZoneID.ZONE2)
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))


# ═══════════════════════════════════════════════════════════════════════════
#  1. QWI menu held open for 5 min
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakQWIMenuOpen:
    def test_qwi_menu_open_5min_soak(self, real_game_view):
        gv = real_game_view
        make_invulnerable(gv)
        _setup_zone2_with_home(gv)
        gv._qwi_menu.toggle()
        assert gv._qwi_menu.open is True

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()

        try:
            run_soak(gv, "QWI menu open", tick)
        finally:
            gv._qwi_menu.open = False


# ═══════════════════════════════════════════════════════════════════════════
#  2. Nebula boss rebuild loop — spawn, kill, re-spawn every ~30 s
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakNebulaBossRebuild:
    def test_nebula_boss_rebuild_5min_soak(self, real_game_view):
        """Every 1800 frames (~30 s) kill the current Nebula boss
        (clear ``gv._nebula_boss``) and re-summon via
        ``spawn_nebula_boss``.  Roughly 10 cycles in 5 minutes —
        enough to surface any accumulation in the per-spawn
        GasCloudProjectile / cone-state / NebulaBossShip lifecycle
        that a single long combat soak might miss."""
        from combat_helpers import spawn_nebula_boss
        gv = real_game_view
        make_invulnerable(gv)
        _setup_zone2_with_home(gv)

        # Stock a pile of iron — each summon burns 100.  11 cycles
        # needs 1100; provide 2000 for headroom.
        gv._station_inv._items[(0, 0)] = ("iron", 2000)
        gv._station_inv._mark_dirty()
        gv._nebula_boss = None
        assert spawn_nebula_boss(gv) is True

        # Park player in aggro range so combat stays hot.
        from constants import BOSS_DETECT_RANGE
        gv.player.center_x = gv._nebula_boss.center_x + (BOSS_DETECT_RANGE * 0.6)
        gv.player.center_y = gv._nebula_boss.center_y

        state = {"n": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Every 1800 frames, simulate killing + re-summoning.
            if state["n"] > 0 and state["n"] % 1800 == 0:
                if gv._nebula_boss is not None:
                    gv._nebula_boss.hp = 0
                    gv._nebula_boss = None
                    gv._nebula_boss_list.clear()
                    gv._nebula_gas_clouds.clear()
                # Top up iron in case the previous cycles drained it.
                if gv._station_inv.total_iron < 200:
                    gv._station_inv._items[(0, 0)] = ("iron", 500)
                    gv._station_inv._mark_dirty()
                try:
                    spawn_nebula_boss(gv)
                except Exception:
                    # Keep ticking even if a summon fails mid-soak —
                    # we're testing for leaks, not asserting every
                    # summon works.
                    pass
            gv.on_update(dt)
            gv.on_draw()
            state["n"] += 1

        run_soak(gv, "Nebula boss rebuild loop", tick)
