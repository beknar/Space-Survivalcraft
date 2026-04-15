"""Soak / endurance tests for the Double Star Refugee dialogue tree.

Mirrors the pattern in ``test_soak.py`` but exercises the conversation
overlay: opens the tree, advances/picks a choice each tick, closes on
``end``, and reopens. Each test runs for 5 minutes and asserts FPS +
RSS stability.

Run with:
    pytest "unit tests/integration/test_soak_dialogue.py" -v -s
"""
from __future__ import annotations

import os
import time

import psutil

from zones import ZoneID
from integration.conftest import measure_fps as _measure_fps


SOAK_DURATION_S = 300
SAMPLE_INTERVAL_S = 30
FRAMES_PER_SAMPLE = 60
WARMUP_FRAMES = 30
MIN_FPS = 40
MAX_MEMORY_GROWTH_MB = 50


def _get_rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _measure_fps_quick(gv) -> float:
    return _measure_fps(gv, n_warmup=0, n_measure=FRAMES_PER_SAMPLE)


def _setup_refugee_zone2(gv, character: str) -> None:
    """Transition to Zone 2, stand up a Home Station, spawn a refugee
    right next to the player, and lock in the active character."""
    from sprites.building import create_building
    from sprites.npc_ship import RefugeeNPCShip
    from settings import audio

    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999
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


def _dialogue_churn_tick(gv, choice_picker, dt: float) -> None:
    """One churn tick — open/advance/close + step gameplay.

    ``choice_picker(step)`` returns the choice index for the current
    branch. ``step`` is the running count of dialogue opens (useful for
    rotating through branches)."""
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


def _run_dialogue_soak(gv, label: str, choice_picker) -> None:
    """Shared soak loop — 5 minutes of dialogue churn with FPS + RSS
    asserts matching the combat soak tests."""
    dt = 1 / 60

    for _ in range(WARMUP_FRAMES):
        _dialogue_churn_tick(gv, choice_picker, dt)

    fps_start = _measure_fps_quick(gv)
    mem_start = _get_rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, {mem_start:.0f} MB RSS")

    fps_min = fps_start
    frame_count = 0
    soak_start = time.perf_counter()
    last_sample = soak_start

    while True:
        elapsed = time.perf_counter() - soak_start
        if elapsed >= SOAK_DURATION_S:
            break
        for _ in range(60):
            _dialogue_churn_tick(gv, choice_picker, dt)
            frame_count += 1
        now = time.perf_counter()
        if now - last_sample >= SAMPLE_INTERVAL_S:
            fps = _measure_fps_quick(gv)
            mem = _get_rss_mb()
            fps_min = min(fps_min, fps)
            print(f"  [{label}] {elapsed / 60:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    fps_end = _measure_fps_quick(gv)
    mem_end = _get_rss_mb()
    fps_min = min(fps_min, fps_end)
    mem_growth = mem_end - mem_start
    print(f"  [{label}] END: {fps_end:.1f} FPS, {mem_end:.0f} MB RSS "
          f"(frames={frame_count})")

    assert fps_min >= MIN_FPS, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {MIN_FPS})"
    )
    assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {MAX_MEMORY_GROWTH_MB} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB"
    )


# ── Picker strategies ──────────────────────────────────────────────────────


def _first_choice(_step: int) -> int:
    """Deterministic spine walk — always pick the first choice."""
    return 0


def _rotating_choice(step: int) -> int:
    """Rotate the first-level choice to hit every branch over time."""
    return step


# ═══════════════════════════════════════════════════════════════════════════
#  Test 1 — Debra's full tree walked along the first-choice spine
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDebraDialogue:
    def test_debra_dialogue_tree_5min_soak(self, real_game_view):
        """Drive Debra's branching tree open → advance → end → reopen
        for 5 minutes. Catches cumulative leaks in the overlay's text
        pool, the sprite-free rect batch, and the aftermath dict flush."""
        gv = real_game_view
        _setup_refugee_zone2(gv, "Debra")
        _run_dialogue_soak(gv, "Dialogue (Debra spine)", _first_choice)


# ═══════════════════════════════════════════════════════════════════════════
#  Test 2 — Debra with rotating choice index so we hit every branch
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDebraTreeExhaustive:
    def test_debra_tree_every_branch_5min_soak(self, real_game_view):
        """Every iteration walks Debra's tree with a different first
        choice so we cover the whole tree across the 5-minute duration,
        not just the ``_pick(0)`` spine."""
        gv = real_game_view
        _setup_refugee_zone2(gv, "Debra")
        _run_dialogue_soak(gv, "Dialogue (Debra exhaustive)",
                           _rotating_choice)


# ═══════════════════════════════════════════════════════════════════════════
#  Test 3 — Rotate the active character so every tree is exercised
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDialogueCharacterRotation:
    def test_dialogue_rotates_all_three_characters_5min_soak(
            self, real_game_view):
        """Rotate the active character (Debra → Ellie → Tara) every
        time the overlay closes, so each tree's hot path runs. Catches
        any character-specific allocation that fails to be reclaimed
        when the overlay closes."""
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
            _run_dialogue_soak(gv, "Dialogue (rotation)", _first_choice)
        finally:
            gv._dialogue.close = original_close  # type: ignore[assignment]
