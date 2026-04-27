"""Star Maze: station turrets target the full enemy population.

Pre-fix: ``StarMazeZone.update`` swapped ``gv.alien_list =
self._maze_aliens`` for the ``update_buildings`` call, so turrets
only saw maze aliens.  Stalkers + Z2-style aliens populating the
zone outside the maze structures were ignored.
"""
from __future__ import annotations

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


def _enter_star_maze(gv):
    from zones import ZoneID
    if gv._zone.zone_id != ZoneID.STAR_MAZE:
        gv._transition_zone(ZoneID.STAR_MAZE)


# ── Combined target list contents ─────────────────────────────────────────


class TestTurretTargetsIncludeAllStarMazeEnemies:
    def test_alien_list_during_update_buildings_combines_lists(
            self, monkeypatch):
        """When ``StarMazeZone.update`` calls ``update_buildings``,
        ``gv.alien_list`` must contain every mobile hostile sprite
        the zone exposes — not just the maze aliens.  Spy on
        update_buildings to capture the swapped list."""
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone

        # Drop a turret in so update_turret actually fires.  Spy
        # on its targeting iterable to confirm the combined list
        # is what the turret sees for selection.
        from sprites.building import Turret, create_building
        captured: dict = {}
        original_update = Turret.update_turret

        def spy(self, dt, alien_list, *args, **kwargs):
            captured["sprite_ids"] = {id(s) for s in alien_list}
            return original_update(self, dt, alien_list, *args, **kwargs)

        from constants import WORLD_WIDTH, WORLD_HEIGHT
        t_tex = gv._building_textures["Turret 1"]
        gv.building_list.append(create_building(
            "Turret 1", t_tex,
            zone.world_width / 2, zone.world_height / 2,
            laser_tex=gv._turret_laser_tex, scale=0.5))

        monkeypatch.setattr(Turret, "update_turret", spy)
        zone.update(gv, 1 / 60)

        # The captured iterable must include EVERY sprite from
        # _maze_aliens, _stalkers, and _aliens.
        ids = captured.get("sprite_ids", set())
        for label, src in (
                ("maze aliens", zone._maze_aliens),
                ("stalkers", zone._stalkers),
                ("z2 aliens", zone._aliens)):
            missing = {id(s) for s in src} - ids
            assert not missing, (
                f"turret targeting list missing {label}: "
                f"{len(missing)} sprite(s) not present")


# ── Turret damage actually lands on a stalker ─────────────────────────────


class TestTurretTargetListNoLeak:
    """Regression: previous designs of this fix used
    ``arcade.SpriteList`` for the combined targeting list — both
    a fresh-per-frame allocation AND a cached clear()+refill cycle
    leak ~15 KB per call (verified 2026-04-27 in a tight-loop test
    against arcade's allocator).  Soak runs reported 500+ MB
    growth in 5 min because of this.

    Current design: targeting iterable is a plain Python list,
    projectile collision queries each existing zone SpriteList
    separately (via ``_turret_extra_target_lists``).  No
    SpriteList allocation per frame, no back-reference accumulation
    on contained sprites.

    These tests pin the design constraints.
    """

    def test_extra_target_lists_property_lists_stalkers_and_aliens(self):
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        extras = zone._turret_extra_target_lists
        # Identity equality with the actual zone lists — proves
        # we're reusing the existing SpriteLists, not allocating
        # new ones.
        assert zone._stalkers in extras
        assert zone._aliens in extras

    def test_no_back_reference_accumulation_after_many_ticks(self):
        """After ticking many frames, no Star Maze sprite holds
        MORE THAN ONE back-reference to its ORIGINAL SpriteList.
        Catches the leak that caused the soak FPS / RSS collapse
        — without the fix, sprites accumulated ~75 stale refs
        per frame from the per-frame combined-SpriteList rebuild.
        """
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        for _ in range(60):
            zone.update(gv, 1 / 60)
        # Each sprite should be in EXACTLY ONE Star-Maze SpriteList
        # (its native one).  Assert the count is ≤ 2 to allow for
        # any unrelated arcade-internal list (defensive — the
        # actual count under the fix is 1).
        for src in (zone._maze_aliens, zone._stalkers, zone._aliens):
            for s in src:
                assert len(s.sprite_lists) <= 2, (
                    f"sprite carries {len(s.sprite_lists)} "
                    f"SpriteList back-refs — leak regressed")


class TestTurretProjectileDamagesStalker:
    """End-to-end: spawn a turret + a stalker right next to each
    other; tick the zone for a frame; the turret-projectile
    collision handler should reduce the stalker's HP."""

    def test_stalker_takes_turret_damage(self):
        from game_view import GameView
        from sprites.building import create_building
        from sprites.projectile import Projectile
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        # Pick a stalker, parked at a known location.
        assert len(zone._stalkers) > 0
        st = zone._stalkers[0]
        st.center_x = 6000.0
        st.center_y = 6000.0
        before_hp = st.hp
        # Inject a turret projectile centered on the stalker so
        # collision detection lands on the first frame.
        proj_tex = gv._turret_laser_tex
        proj = Projectile(
            proj_tex, st.center_x, st.center_y,
            heading=0.0, speed=1.0, max_dist=1000.0,
            scale=1.0, damage=20.0)
        gv.turret_projectile_list.append(proj)
        # Tick the zone — update_buildings runs
        # handle_turret_projectile_hits which checks
        # gv.alien_list, which is the combined list during this
        # call.
        zone.update(gv, 1 / 60)
        # Stalker took damage.
        assert st.hp < before_hp, (
            f"stalker HP unchanged after turret projectile hit: "
            f"before={before_hp} after={st.hp}")
