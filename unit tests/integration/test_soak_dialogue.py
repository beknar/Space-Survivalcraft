"""Soak / endurance tests for the Double Star Refugee dialogue tree.

See ``_soak_base.py`` for the shared thresholds and the ``run_soak``
helper. Each test drives the dialogue overlay (open → advance / pick →
close → reopen) for 5 minutes while Zone 2 gameplay ticks and asserts
FPS + RSS stability.

Run with:
    pytest "unit tests/integration/test_soak_dialogue.py" -v -s
"""
from __future__ import annotations

from zones import ZoneID
from integration._soak_base import (
    WARMUP_FRAMES, make_invulnerable, run_soak,
)


def _setup_refugee_zone2(gv, character: str) -> None:
    """Zone 2 + Home Station + refugee parked next to the player."""
    from sprites.building import create_building
    from sprites.npc_ship import RefugeeNPCShip
    from settings import audio

    make_invulnerable(gv)
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)

    gv.building_list.clear()
    cx, cy = gv.player.center_x, gv.player.center_y
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(
        create_building("Home Station", tex, cx, cy, scale=0.5))

    gv._refugee_npc = RefugeeNPCShip(cx + 120, cy, (cx, cy))
    gv._refugee_spawned = True
    audio.character_name = character


def _make_dialogue_churn(gv, choice_picker):
    """Return a ``churn_tick(dt)`` closure that opens/advances/closes
    the dialogue overlay once per tick."""
    def churn(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        if not gv._dialogue.open:
            from dialogue import get_refugee_tree
            from settings import audio
            tree = get_refugee_tree(audio.character_name or "Debra")
            gv._quest_flags = {}
            gv._dialogue.start(tree, aftermath_sink=gv._quest_flags)
            gv._dialogue_step_counter = (
                getattr(gv, "_dialogue_step_counter", 0) + 1)
        node = gv._dialogue._current_node()
        if node is None:
            gv._dialogue.close()
        elif node.get("choices"):
            idx = choice_picker(gv._dialogue_step_counter) % len(node["choices"])
            gv._dialogue._pick(idx)
        else:
            gv._dialogue._advance()
        gv.on_update(dt)
        gv.on_draw()
    return churn


def _first_choice(_step: int) -> int:
    return 0


def _rotating_choice(step: int) -> int:
    return step


class TestSoakDebraDialogue:
    def test_debra_dialogue_tree_5min_soak(self, real_game_view):
        """Debra's full tree walked along the first-choice spine for 5
        minutes — catches leaks in the overlay's text pool, the rect
        batch, and the aftermath-dict flush."""
        gv = real_game_view
        _setup_refugee_zone2(gv, "Debra")
        run_soak(gv, "Dialogue (Debra spine)",
                 _make_dialogue_churn(gv, _first_choice))


class TestSoakDebraTreeExhaustive:
    def test_debra_tree_every_branch_5min_soak(self, real_game_view):
        """Rotating first-choice index covers every branch in the tree
        across the duration, not just the spine."""
        gv = real_game_view
        _setup_refugee_zone2(gv, "Debra")
        run_soak(gv, "Dialogue (Debra exhaustive)",
                 _make_dialogue_churn(gv, _rotating_choice))


class TestSoakDialogueCharacterRotation:
    def test_dialogue_rotates_all_three_characters_5min_soak(
            self, real_game_view):
        """Rotate the active character each time the overlay closes so
        Debra / Ellie / Tara trees all churn."""
        from settings import audio
        gv = real_game_view
        _setup_refugee_zone2(gv, "Debra")

        rotation = ("Debra", "Ellie", "Tara")
        counter = {"i": 0}
        original_close = gv._dialogue.close

        def close_and_rotate(*args, **kwargs) -> None:
            res = original_close(*args, **kwargs)
            counter["i"] = (counter["i"] + 1) % len(rotation)
            audio.character_name = rotation[counter["i"]]
            return res

        gv._dialogue.close = close_and_rotate  # type: ignore[assignment]
        try:
            run_soak(gv, "Dialogue (rotation)",
                     _make_dialogue_churn(gv, _first_choice))
        finally:
            gv._dialogue.close = original_close  # type: ignore[assignment]


# WARMUP_FRAMES is re-exported so legacy test runners that import it
# directly from this module keep working.
__all__ = ["WARMUP_FRAMES"]
