"""Soak test for the shared scaffolding added in the refactor pass.

Runs a minimal tick loop for 5 minutes via ``_soak_base.run_soak`` so
any regression in the shared loop itself (FPS measurement cadence,
sample printing, memory accounting, assertion wording) shows up.

Not executed by the default pytest run — see ``pytest.ini``.

Run explicitly with:
    pytest "unit tests/integration/test_soak_refactor.py" -v -s
"""
from __future__ import annotations

from zones import ZoneID
from integration._soak_base import (
    make_invulnerable, run_soak,
)


class TestSoakSharedScaffolding:
    def test_shared_run_soak_drives_5min_minimal_churn(self, real_game_view):
        """Zone 1 with nothing but player healing + on_update/on_draw
        — the goal is to exercise the shared `run_soak` helper itself,
        not any particular feature."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        make_invulnerable(gv)

        def churn(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Shared scaffolding", churn)
