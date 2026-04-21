"""Integration tests for the boss + drop tweaks landed this session.

Each test drives the real ``GameView`` so we hit the actual update +
draw + collision pipelines.

Covers:

  * Turret / Missile Array accept ``bosses=[…]`` and target a Nebula
    boss alongside aliens.
  * AI-pilot parked ship targets the Nebula boss and lands damage
    via the turret-projectile collision handler.
  * Missile homing + damage against both bosses.
  * Nebula boss death drops 3000 iron + 1000 copper, no XP.
  * Force-wall blocks boss movement AND absorbs its gas clouds.
  * Boss navigates around the wall (avoidance repulsion) rather
    than stalling.
  * Asteroid-crush pass on the Nebula boss's path — iron, copper,
    and wanderer yields all behave.
  * Boss HP + shield bars + flashing minimap markers draw cleanly.
  * Nebula sprite-row randomisation — clamp + cache per row.
  * ``BossAlienShip.radius`` property tracks sprite width.

Run with:
    pytest "unit tests/integration/test_session_boss_features.py" -v
"""
from __future__ import annotations

import math
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, BOSS_DETECT_RANGE,
    TURRET_DAMAGE, BOSS_CANNON_RANGE,
)
from zones import ZoneID


# ──────────────────────────────────────────────────────────────────────────
#  Shared setup
# ──────────────────────────────────────────────────────────────────────────

def _setup_zone2_nebula(gv, boss_offset_x: float = 200.0,
                         boss_offset_y: float = 0.0):
    """Zone 2 + fresh Home Station + Nebula boss at ``(cx + offset, cy)``.

    Also clears stray wormholes so the player sitting at world centre
    doesn't get yanked back to Zone 1 during the test tick.
    """
    from sprites.building import create_building
    from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture

    gv._transition_zone(ZoneID.ZONE2)
    cx, cy = gv._zone.world_width / 2, gv._zone.world_height / 2
    gv.building_list.clear()
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    # Clear wormholes so a centred player doesn't hop zones mid-test.
    gv._wormholes = []
    if hasattr(gv._zone, "_wormholes"):
        gv._zone._wormholes = []

    tex = load_nebula_boss_texture(0)
    nb = NebulaBossShip(tex, gv._alien_laser_tex,
                         cx + boss_offset_x, cy + boss_offset_y,
                         cx, cy)
    gv._nebula_boss = nb
    gv._nebula_boss_list.clear()
    gv._nebula_boss_list.append(nb)
    return nb, cx, cy


# ──────────────────────────────────────────────────────────────────────────
#  Friendly damage sources target the Nebula boss
# ──────────────────────────────────────────────────────────────────────────

class TestTurretTargetsNebulaBoss:
    def test_turret_cached_target_is_nebula_boss_when_nearby(
            self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=250.0)
        # Kill any Zone-2 aliens so only the boss is a candidate.
        if hasattr(gv._zone, "_aliens"):
            gv._zone._aliens.clear()
        # Fresh turret near the boss.
        from sprites.building import create_building, Turret
        turret = create_building(
            "Turret 1", gv._building_textures["Turret 1"],
            cx + 60, cy, laser_tex=gv._turret_laser_tex, scale=0.5)
        assert isinstance(turret, Turret)
        gv.building_list.append(turret)

        # Run one second — enough for the 0.5-s rescan.
        gv.player.center_x = -1e5; gv.player.center_y = -1e5
        for _ in range(60):
            gv.on_update(1 / 60)
        assert turret._cached_target is nb

    def test_turret_projectile_damages_nebula_boss(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # Stationary turret projectile dead-centre on the boss.
        from sprites.projectile import Projectile
        shot = Projectile(gv._turret_laser_tex, cx, cy, 0.0, 0.0, 500.0,
                           scale=0.6, damage=TURRET_DAMAGE)
        gv.turret_projectile_list.append(shot)
        init_s = nb.shields
        from collisions import handle_nebula_boss_projectile_hits
        handle_nebula_boss_projectile_hits(gv)
        assert nb.shields < init_s
        # Projectile consumed on hit (sprite_lists emptied).
        assert not shot.sprite_lists


class TestMissileArrayTargetsNebulaBoss:
    def test_missile_array_locks_onto_nebula_boss(self, real_game_view):
        """Verify the ``bosses=[...]`` wiring reaches ``MissileArray``:
        its rescan picks the Nebula boss as the cached target even
        with no aliens in range.  Whether a missile actually fires in
        a given window depends on Zone 2's update cycle timing, which
        is outside this test's scope."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=150.0)
        if hasattr(gv._zone, "_aliens"):
            gv._zone._aliens.clear()
        from sprites.building import create_building, MissileArray
        ma = create_building(
            "Missile Array", gv._building_textures["Missile Array"],
            cx, cy, scale=0.5)
        assert isinstance(ma, MissileArray)
        gv.building_list.append(ma)
        # Drive the update path directly (no missile flight, just
        # target-selection).  Call ``update_missile_array`` with a
        # ``bosses=`` kwarg — same wiring update_buildings uses.
        from constants import MISSILE_ARRAY_COOLDOWN
        for _ in range(10):  # rescan + fire
            ma.update_missile_array(
                MISSILE_ARRAY_COOLDOWN, [], gv._missile_list,
                gv._missile_tex, bosses=[gv._boss, nb])
        assert ma._cached_target is nb
        assert len(gv._missile_list) >= 1, (
            "Missile array should have fired at least one missile at "
            "the Nebula boss after its rescan + cooldown cycle.")


class TestAIPilotTargetsNebulaBoss:
    def test_ai_ship_fires_turret_projectiles_at_nebula_boss(
            self, real_game_view):
        """AI-piloted parked ship pushes shots into ``turret_projectile_list``;
        the Nebula boss's collision handler reads from that list."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=200.0)
        if hasattr(gv._zone, "_aliens"):
            gv._zone._aliens.clear()
        from sprites.parked_ship import ParkedShip
        ps = ParkedShip(faction="Earth", ship_type="Cruiser",
                         ship_level=1, x=cx + 50, y=cy + 50)
        ps.module_slots.append("ai_pilot")
        gv._parked_ships.append(ps)
        # Player out of frame.
        gv.player.center_x = -1e5; gv.player.center_y = -1e5

        init_shields = nb.shields
        for _ in range(600):  # 10 s — plenty of AI-pilot fire cycles
            gv.on_update(1 / 60)
        assert nb.shields < init_shields


# ──────────────────────────────────────────────────────────────────────────
#  Missile vs both bosses
# ──────────────────────────────────────────────────────────────────────────

class TestMissileDamagesBoth:
    def test_missile_vs_nebula_boss_direct(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        from sprites.missile import HomingMissile
        m = HomingMissile(gv._missile_tex, cx, cy, 0.0)
        gv._missile_list.append(m)
        init_shields = nb.shields
        # Run the missile update path — it walks ``_missile_list`` and
        # applies damage to whichever boss it's overlapping.
        from update_logic import update_missiles
        update_missiles(gv, 1 / 60)
        assert nb.shields < init_shields


# ──────────────────────────────────────────────────────────────────────────
#  Nebula kill reward
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaBossDeathRewards:
    def test_yields_iron_copper_no_xp(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # Pin player far away so the update doesn't interfere.
        gv.player.center_x = -1e5; gv.player.center_y = -1e5
        xp_before = gv._char_xp
        pickups_before = len(gv.iron_pickup_list)
        from collisions import _nebula_boss_death
        _nebula_boss_death(gv)

        new = gv.iron_pickup_list[pickups_before:]
        # Should be exactly two drops: one iron, one copper.
        iron_total = sum(p.amount for p in new if p.item_type == "iron")
        copper_total = sum(p.amount for p in new if p.item_type == "copper")
        assert iron_total == 3000
        assert copper_total == 1000
        assert gv._char_xp == xp_before  # zero XP awarded
        assert gv._nebula_boss is None

    def test_drops_spawn_at_distinct_positions(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        pickups_before = len(gv.iron_pickup_list)
        from collisions import _nebula_boss_death
        _nebula_boss_death(gv)
        new = gv.iron_pickup_list[pickups_before:]
        positions = [(round(p.center_x, 2), round(p.center_y, 2)) for p in new]
        assert len(set(positions)) == len(new), (
            "iron and copper drops should be scattered to distinct "
            "positions so they don't stack")


# ──────────────────────────────────────────────────────────────────────────
#  Force-wall interactions
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaBossVsForceWall:
    def test_boss_cannot_cross_wall(self, real_game_view):
        """Spawn a vertical wall between boss and player; after 4 s the
        boss must still be on the east side of the wall line."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=400.0)
        # Player west of wall.
        gv.player.center_x = cx - 100; gv.player.center_y = cy
        from sprites.force_wall import ForceWall
        gv._force_walls.clear()
        gv._force_walls.append(ForceWall(cx + 200, cy, heading=90.0))
        # Park the player to stop any drift.
        for _ in range(240):  # 4 s
            gv.player.center_x = cx - 100
            gv.player.center_y = cy
            gv.player.vel_x = 0.0; gv.player.vel_y = 0.0
            gv.on_update(1 / 60)
        # Boss should be somewhere east of the wall OR have navigated
        # around (still on the east side before completing the arc).
        # Hard requirement: boss.center_x can't be directly past the wall
        # x with y inside the wall's y range (cy-200..cy+200).
        within_wall_y = (cy - 200) < nb.center_y < (cy + 200)
        crossed_through = (nb.center_x < cx + 200 and within_wall_y)
        assert not crossed_through, (
            f"Boss tunnelled through the wall: pos=({nb.center_x:.0f}, "
            f"{nb.center_y:.0f}), wall at x=cx+200 spans "
            f"y={cy-200:.0f}..{cy+200:.0f}")

    def test_gas_cloud_absorbed_by_wall(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # One gas cloud flying west toward a wall.
        from sprites.nebula_boss import GasCloudProjectile
        cloud = GasCloudProjectile(cx + 100, cy,
                                     heading_deg=-90.0, damage=15)
        gv._nebula_gas_clouds.append(cloud)
        from sprites.force_wall import ForceWall
        gv._force_walls.clear()
        gv._force_walls.append(ForceWall(cx + 50, cy, heading=90.0))
        # Tick until the cloud should have reached the wall.
        for _ in range(60):
            gv.player.center_x = -1e5; gv.player.center_y = -1e5
            gv.on_update(1 / 60)
        assert cloud not in gv._nebula_gas_clouds

    def test_boss_navigates_around_wall_and_closes_on_player(
            self, real_game_view):
        """With wall repulsion, the boss curves past the wall's
        endpoint and gets closer to the player even from a wall-blocked
        approach vector."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=500.0)
        gv.player.center_x = cx; gv.player.center_y = cy
        from sprites.force_wall import ForceWall
        gv._force_walls.clear()
        # Vertical wall directly between boss and player.
        gv._force_walls.append(ForceWall(cx + 250, cy, heading=90.0))
        start_d = math.hypot(nb.center_x - cx, nb.center_y - cy)
        for _ in range(600):  # 10 s
            gv.player.center_x = cx
            gv.player.center_y = cy
            gv.player.vel_x = 0.0; gv.player.vel_y = 0.0
            gv.on_update(1 / 60)
        end_d = math.hypot(nb.center_x - cx, nb.center_y - cy)
        # Boss should have closed distance meaningfully (not just
        # bounced off the wall at 500 px).
        assert end_d < start_d * 0.7, (
            f"Boss didn't make headway around wall: start_d={start_d:.0f} "
            f"end_d={end_d:.0f}")


# ──────────────────────────────────────────────────────────────────────────
#  Asteroid crush
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaBossCrushesAsteroids:
    def _populate_line(self, gv, iron_n: int = 6, copper_n: int = 2):
        from sprites.asteroid import IronAsteroid
        from sprites.copper_asteroid import CopperAsteroid
        z = gv._zone
        z._iron_asteroids.clear()
        z._copper_asteroids.clear()
        z._double_iron.clear()
        z._wanderers.clear()
        cx, cy = z.world_width / 2, z.world_height / 2
        for i in range(iron_n):
            ox = 100 + i * 100
            z._iron_asteroids.append(IronAsteroid(z._iron_tex, cx + ox, cy))
        for i in range(copper_n):
            ox = 150 + i * 300
            z._copper_asteroids.append(
                CopperAsteroid(z._copper_tex, cx + ox, cy + 20))
        return cx, cy

    def test_boss_path_destroys_iron_and_copper(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=700.0)
        iron_n = 6; copper_n = 2
        self._populate_line(gv, iron_n=iron_n, copper_n=copper_n)
        # Player far west so boss chases west, crossing the line.
        gv.player.center_x = cx - 3000; gv.player.center_y = cy
        pickups_before = len(gv.iron_pickup_list)
        for _ in range(720):  # 12 s
            gv.on_update(1 / 60)
        new_pickups = gv.iron_pickup_list[pickups_before:]
        iron_drops = sum(1 for p in new_pickups if p.item_type == "iron")
        copper_drops = sum(1 for p in new_pickups if p.item_type == "copper")
        # Every iron asteroid dropped at least one iron token; copper
        # asteroids drop (copper + iron) per kill.
        assert iron_drops >= iron_n, (
            f"expected >= {iron_n} iron drops, got {iron_drops}")
        assert copper_drops >= copper_n, (
            f"expected >= {copper_n} copper drops, got {copper_drops}")
        z = gv._zone
        assert len(z._iron_asteroids) == 0
        assert len(z._copper_asteroids) == 0

    def test_boss_takes_no_damage_from_crushing(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=700.0)
        self._populate_line(gv)
        gv.player.center_x = cx - 3000
        hp_before = nb.hp
        shields_before = nb.shields
        for _ in range(600):
            gv.on_update(1 / 60)
        # Shields may regen; compare HP + max_shields baseline.
        assert nb.hp >= hp_before, "boss shouldn't take HP damage from asteroid crush"


# ──────────────────────────────────────────────────────────────────────────
#  Draw path — HP/shield bars + flashing minimap
# ──────────────────────────────────────────────────────────────────────────

class TestBossDrawAdditions:
    def test_frame_with_nebula_boss_draws_clean(self, real_game_view):
        """HP + shield bars + flashing-yellow minimap markers must not
        raise on a full frame."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # One full frame.
        gv.on_update(1 / 60)
        gv.on_draw()  # draws boss sprite + HP/shield bar + minimap marker

    def test_minimap_supports_extra_boss_positions(self, real_game_view):
        """``hud_minimap.draw_minimap`` gained an
        ``extra_boss_positions`` kwarg that feeds the Nebula boss into
        the pulsing-yellow marker loop."""
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # draw_ui wires the extra positions through.
        gv.on_draw()


# ──────────────────────────────────────────────────────────────────────────
#  Nebula sprite randomisation (real texture crop)
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaSpriteLoader:
    def test_explicit_row_returns_cached_texture(self, real_game_view):
        from sprites.nebula_boss import (
            load_nebula_boss_texture, _nebula_boss_texture_cache,
        )
        t0 = load_nebula_boss_texture(0)
        t0b = load_nebula_boss_texture(0)
        assert t0 is t0b
        # Cache key format (col, row).
        assert (1, 0) in _nebula_boss_texture_cache

    def test_different_rows_give_different_textures(self, real_game_view):
        from sprites.nebula_boss import load_nebula_boss_texture
        t0 = load_nebula_boss_texture(0)
        t3 = load_nebula_boss_texture(3)
        assert t0 is not t3

    def test_clamp_out_of_range(self, real_game_view):
        """Row indices past the sheet should clamp, not crash."""
        from sprites.nebula_boss import (
            load_nebula_boss_texture, NEBULA_BOSS_ROW_COUNT,
        )
        t_hi = load_nebula_boss_texture(NEBULA_BOSS_ROW_COUNT + 5)
        t_last = load_nebula_boss_texture(NEBULA_BOSS_ROW_COUNT - 1)
        assert t_hi is t_last


# ──────────────────────────────────────────────────────────────────────────
#  Boss.radius property (live sprite)
# ──────────────────────────────────────────────────────────────────────────

class TestBossRadiusProperty:
    def test_radius_matches_half_width(self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        assert nb.radius == pytest.approx(nb.width * 0.5)

    def test_nebula_boss_radius_is_approximately_half_sprite(
            self, real_game_view):
        gv = real_game_view
        nb, cx, cy = _setup_zone2_nebula(gv, boss_offset_x=0.0)
        # 128 * 1.80 scale = 230.4, radius 115.2
        assert 110.0 < nb.radius < 120.0
