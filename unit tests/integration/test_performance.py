"""Performance integration tests — rump file.

The original ``test_performance.py`` was split into per-feature
modules.  Run them via the directory wildcard, or pick a specific
file:

  * ``test_performance_zones_baseline.py`` — Zone 1 / Zone 2 / boss
    / minimap / alien-asteroid baselines.
  * ``test_performance_inventory.py`` — both inventories open.
  * ``test_performance_combat.py`` — heavy combat + escape menu.
  * ``test_performance_warp_zones.py`` — all four warp zones.
  * ``test_performance_video_char.py`` — char portrait video.
  * ``test_performance_video_dual.py`` — char + music-stand-in videos.
  * ``test_performance_video_music.py`` — real ./yvideos music + cleanup.
  * ``test_performance_station_info.py`` — Station Info / T menu.
  * ``test_performance_missile_array.py`` — Missile Array buildings.
  * ``test_performance_trade.py`` — trade menu sell / buy / churn.
  * ``test_performance_parked_ships.py`` — parked-ship rendering.
  * ``test_performance_ai_pilot.py`` — AI Pilot fleets.
  * ``test_performance_station_shield.py`` — station + AI yellow shields.
  * ``test_performance_null_field.py`` — null field draw + cloak path.
  * ``test_performance_explosions.py`` — asteroid-explosion animation.
  * ``test_performance_slipspace.py`` — slipspace minimap markers.

Other performance suites in this directory (unchanged):

  * ``test_performance_drone.py`` — active-drone update path.
  * ``test_performance_menu_scroll.py`` — build / craft scroll menus.
  * ``test_performance_nebula_boss.py`` — Nebula boss + QWI.
  * ``test_performance_session_boss.py`` — long-session boss soak.
  * ``test_performance_station_combo.py`` — station-combo perf.
  * ``test_performance_boss_phases.py`` — boss phase coverage.

Each new file follows the original test contract — simulate N frame
loops with a real GameView on the hidden Arcade window and assert
``fps >= MIN_FPS`` (40).  Tests are calibrated for the dev machine;
weaker hardware should raise the threshold or skip per-class.
"""
from __future__ import annotations
