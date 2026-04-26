"""Lock in the drone-related help-menu entries so a future
constants/refactor pass can't silently drop them."""
from __future__ import annotations


def test_r_key_listed_in_help():
    from escape_menu._help_mode import _HELP_LINES
    keys = [k for k, _ in _HELP_LINES]
    assert "R" in keys


def test_shift_r_recall_listed_in_help():
    from escape_menu._help_mode import _HELP_LINES
    keys = [k for k, _ in _HELP_LINES]
    assert "Shift+R" in keys


def test_m_map_key_listed_in_help():
    from escape_menu._help_mode import _HELP_LINES
    keys = [k for k, _ in _HELP_LINES]
    assert "M" in keys


def test_drone_procedure_section_exists():
    from escape_menu._help_mode import _DRONE_LINES
    # Section needs to mention each of the four canonical cases:
    # mining beam → mining drone, basic laser → combat drone,
    # same-variant no-op, recall (Shift+R).
    text = "\n".join(_DRONE_LINES).lower()
    assert "mining" in text
    assert "combat" in text
    assert "no-op" in text or "no op" in text
    assert "shift+r" in text or "recall" in text


def test_drone_procedure_mentions_craft_recipe():
    from escape_menu._help_mode import _DRONE_LINES
    text = "\n".join(_DRONE_LINES).lower()
    assert "200 iron" in text
    assert "100 copper" in text
