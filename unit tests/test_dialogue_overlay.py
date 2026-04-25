"""Tests for dialogue_overlay.DialogueOverlay lifecycle + input routing.

Tree-structure tests live in test_refugee_npc.py; this file covers the
overlay UI: open/close, key/mouse routing, choice picking, end-node
aftermath flag commit, and graceful close on broken trees.
"""
from __future__ import annotations

import arcade
import pytest

from dialogue_overlay import DialogueOverlay


# ── Trees used in multiple tests ───────────────────────────────────────────

LINEAR_TREE = {
    "start": "n0",
    "n0": {"speaker": "A", "text": "hello", "next": "n1"},
    "n1": {"speaker": "A", "text": "goodbye", "end": True,
           "aftermath": {"met_a": True}},
}

CHOICE_TREE = {
    "start": "n0",
    "n0": {"speaker": "B", "text": "pick", "choices": [
        {"text": "first", "next": "n1"},
        {"text": "second", "next": "n2"},
    ]},
    "n1": {"speaker": "B", "text": "you picked first",
           "end": True, "aftermath": {"chose_first": True}},
    "n2": {"speaker": "B", "text": "you picked second",
           "end": True, "aftermath": {"chose_second": True}},
}

BROKEN_TREE = {
    "start": "n0",
    "n0": {"speaker": "C", "text": "broken", "next": "missing_node"},
}


# ── Lifecycle ──────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_starts_closed(self):
        ov = DialogueOverlay()
        assert ov.open is False

    def test_start_opens_on_valid_tree(self):
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE)
        assert ov.open is True
        assert ov._current == "n0"

    def test_start_with_missing_start_node_does_not_open(self):
        ov = DialogueOverlay()
        ov.start({"start": "nope"})
        assert ov.open is False

    def test_start_with_empty_tree_does_not_open(self):
        ov = DialogueOverlay()
        ov.start({})
        assert ov.open is False

    def test_close_sets_open_false(self):
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE)
        ov.close()
        assert ov.open is False


# ── Linear advance via SPACE / ENTER ───────────────────────────────────────

class TestAdvance:
    def test_space_advances_to_next_node(self):
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE)
        ov.on_key_press(arcade.key.SPACE)
        assert ov._current == "n1"
        assert ov.open is True

    def test_enter_also_advances(self):
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE)
        ov.on_key_press(arcade.key.ENTER)
        assert ov._current == "n1"

    def test_advance_on_end_node_closes_and_commits_aftermath(self):
        sink = {}
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE, aftermath_sink=sink)
        ov.on_key_press(arcade.key.SPACE)  # n0 → n1 (end)
        ov.on_key_press(arcade.key.SPACE)  # n1.end → close + commit
        assert ov.open is False
        assert sink == {"met_a": True}

    def test_broken_next_pointer_closes_overlay(self):
        ov = DialogueOverlay()
        ov.start(BROKEN_TREE)
        ov.on_key_press(arcade.key.SPACE)
        assert ov.open is False


# ── Choice picking via digit keys ──────────────────────────────────────────

class TestChoiceKeys:
    def test_key_1_picks_first_choice(self):
        sink = {}
        ov = DialogueOverlay()
        ov.start(CHOICE_TREE, aftermath_sink=sink)
        ov.on_key_press(arcade.key.KEY_1)
        assert ov._current == "n1"
        # Reach end and commit
        ov.on_key_press(arcade.key.SPACE)
        assert sink == {"chose_first": True}

    def test_key_2_picks_second_choice(self):
        sink = {}
        ov = DialogueOverlay()
        ov.start(CHOICE_TREE, aftermath_sink=sink)
        ov.on_key_press(arcade.key.KEY_2)
        assert ov._current == "n2"
        ov.on_key_press(arcade.key.SPACE)
        assert sink == {"chose_second": True}

    def test_out_of_range_digit_does_nothing(self):
        ov = DialogueOverlay()
        ov.start(CHOICE_TREE)
        # Tree has only 2 choices — KEY_5 should be a no-op
        ov.on_key_press(arcade.key.KEY_5)
        assert ov._current == "n0"
        assert ov.open is True

    def test_space_on_choice_node_does_not_advance(self):
        """Choice nodes ignore SPACE — must explicitly pick a choice."""
        ov = DialogueOverlay()
        ov.start(CHOICE_TREE)
        ov.on_key_press(arcade.key.SPACE)
        assert ov._current == "n0"


# ── ESC close ──────────────────────────────────────────────────────────────

class TestEscape:
    def test_esc_closes_without_committing(self):
        sink = {"baseline": True}
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE, aftermath_sink=sink)
        ov.on_key_press(arcade.key.ESCAPE)
        assert ov.open is False
        # Aftermath sink unchanged — no terminal node was reached
        assert sink == {"baseline": True}


# ── Input ignored when closed ──────────────────────────────────────────────

class TestClosedIsInert:
    def test_keypress_when_closed_is_noop(self):
        ov = DialogueOverlay()
        ov.on_key_press(arcade.key.SPACE)  # must not raise

    def test_mousepress_when_closed_is_noop(self):
        ov = DialogueOverlay()
        ov.on_mouse_press(100.0, 100.0)  # must not raise

    def test_draw_when_closed_is_noop(self):
        ov = DialogueOverlay()
        ov.draw()  # bails at top, must not raise


# ── Aftermath sink default ────────────────────────────────────────────────

class TestAftermath:
    def test_no_sink_does_not_crash_on_end(self):
        ov = DialogueOverlay()
        ov.start(LINEAR_TREE)  # no sink passed
        ov.on_key_press(arcade.key.SPACE)
        ov.on_key_press(arcade.key.SPACE)
        assert ov.open is False
