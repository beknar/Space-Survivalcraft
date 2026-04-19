"""5-minute soak tests for the Double Star boss.

These exercise the boss combat pipeline (movement + weapon firing +
charge attack + projectile lifecycle) under sustained load with the
player invulnerable.  Catches accumulating leaks the catch-all
``TestZone1WithBoss`` perf test (only 60 frames measured) can't see:

  - Boss projectile list growth if despawn paths regress
  - HitSpark / FireSpark accumulation from constant impacts
  - Phase-transition state churn (HP forced through thresholds)
  - Charge-attack windup / dash state lifecycle
  - Per-frame ``update_boss`` cost stability

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_boss.py" -v -s
"""
from __future__ import annotations

import math

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, BOSS_DETECT_RANGE,
    BOSS_PHASE2_HP, BOSS_PHASE3_HP,
)
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_boss_soak(gv):
    """Common setup — Zone 1 + station + boss, player invulnerable
    and parked just inside aggro range so the boss attacks every
    cycle of its weapon cooldowns."""
    from sprites.building import create_building
    from combat_helpers import spawn_boss

    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

    gv.building_list.clear()
    home_tex = gv._building_textures["Home Station"]
    home = create_building("Home Station", home_tex,
                           WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                           scale=0.5)
    gv.building_list.append(home)
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80)):
        t_tex = gv._building_textures[bt]
        b = create_building(bt, t_tex,
                            WORLD_WIDTH / 2 + ox,
                            WORLD_HEIGHT / 2,
                            laser_tex=gv._turret_laser_tex, scale=0.5)
        gv.building_list.append(b)

    gv._boss = None
    gv._boss_spawned = False
    gv._boss_defeated = False
    gv._boss_list.clear()
    gv._boss_projectile_list.clear()
    spawn_boss(gv, WORLD_WIDTH / 2, WORLD_HEIGHT / 2)

    # Park player in aggro range so combat stays hot.
    gv.player.center_x = gv._boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._boss.center_y

    make_invulnerable(gv)
    return gv._boss


def _force_phase(gv, phase: int) -> None:
    if phase == 2:
        gv._boss.hp = max(1, int(gv._boss.max_hp * (BOSS_PHASE2_HP - 0.05)))
    elif phase == 3:
        gv._boss.hp = max(1, int(gv._boss.max_hp * (BOSS_PHASE3_HP - 0.05)))
    gv._boss._update_phase()


def _make_boss_combat_churn(gv, *, keep_player_alive: bool = True):
    """Standard tick — invulnerable player taking shots, boss
    attacking back.  ``run_soak`` will call this 60×/s for 5 min."""
    def tick(dt: float) -> None:
        if keep_player_alive:
            # Topping up shields/HP each tick is cheaper than relying
            # on max_hp=999999 alone (some code clamps via float math).
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
        gv.on_update(dt)
        gv.on_draw()

    return tick


# ═══════════════════════════════════════════════════════════════════════════
#  1. Vanilla 5-min soak — boss in Phase 1 with player invulnerable
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBossPhase1:
    def test_boss_phase1_5min_soak(self, real_game_view):
        """5-minute soak with the boss in its starting phase, player
        invulnerable, boss attacking every weapon cooldown.  The
        primary "is the boss combat pipeline leak-free?" test."""
        gv = real_game_view
        _setup_boss_soak(gv)
        run_soak(gv, "Boss phase 1", _make_boss_combat_churn(gv))


# ═══════════════════════════════════════════════════════════════════════════
#  2. Phase 2 soak — charge attack lifecycle + 2× shield regen
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBossPhase2:
    def test_boss_phase2_5min_soak(self, real_game_view):
        """5-minute Phase 2 soak.  Charge attacks fire at their
        cooldown (8 s), so the soak captures dozens of charge
        windup → dash → reset cycles."""
        gv = real_game_view
        _setup_boss_soak(gv)
        _force_phase(gv, 2)

        # Pin HP every tick so phase doesn't drift if turrets land hits.
        target_hp = gv._boss.hp

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv._boss.hp = target_hp
            gv._boss._update_phase()
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Boss phase 2 (charge cycles)", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  3. Phase 3 soak — enraged, halved cooldowns, no shield regen
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBossPhase3:
    def test_boss_phase3_5min_soak(self, real_game_view):
        """5-minute Phase 3 soak.  Weapon cooldowns halve so this
        produces roughly 2× the projectile churn of Phase 1.  Most
        likely place for projectile-pool / spark-list leaks to show."""
        gv = real_game_view
        _setup_boss_soak(gv)
        _force_phase(gv, 3)

        target_hp = gv._boss.hp

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv._boss.hp = target_hp
            gv._boss._update_phase()
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Boss phase 3 (enraged)", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  4. Phase rotation soak — cycle through P1 → P2 → P3 every minute
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBossPhaseRotation:
    def test_boss_phase_rotation_5min_soak(self, real_game_view):
        """Force the boss through all three phases over the 5-minute
        soak (P1 → P2 → P3 → back to P1, repeat).  Catches
        accumulating state from the phase-transition path itself."""
        gv = real_game_view
        boss = _setup_boss_soak(gv)

        full = boss.max_hp
        targets = [
            int(full * 0.95),                       # Phase 1
            int(full * (BOSS_PHASE2_HP - 0.05)),    # Phase 2
            int(full * (BOSS_PHASE3_HP - 0.05)),    # Phase 3
        ]
        state = {"n": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Rotate target HP every 60 s (3600 frames at 60 FPS) so
            # the soak spends ~100 s in each phase per cycle.
            phase_idx = (state["n"] // 3600) % len(targets)
            gv._boss.hp = max(1, targets[phase_idx])
            gv._boss._update_phase()
            gv.on_update(dt)
            gv.on_draw()
            state["n"] += 1

        run_soak(gv, "Boss phase rotation", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  5. Player-invulnerable boss-attacking 5-min soak
#     (the "let the boss spam attacks for 5 minutes" requirement)
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBossInvulnerablePlayerAttacked:
    def test_boss_attacks_invulnerable_player_5min_soak(
            self, real_game_view):
        """5-minute soak with the player invulnerable and the boss
        firing every cooldown.  The player drifts inside aggro range
        so the boss alternates between weapon fire and charge dashes
        the whole time.

        This is the dedicated "boss attacks for 5 minutes against an
        invulnerable player" scenario, separate from the phase-
        specific soaks above.  Tests that the boss damage path +
        ``apply_damage_to_player`` shield/HP code stays leak-free
        under sustained hit pressure."""
        gv = real_game_view
        _setup_boss_soak(gv)

        def tick(dt: float) -> None:
            # Top up before the tick so apply_damage_to_player has a
            # full shield/HP pool to chew through every frame.
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Boss vs invulnerable player",
                 _make_boss_combat_churn(gv))
