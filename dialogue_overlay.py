"""Dialogue tree overlay — renders NPC conversations.

The overlay is a centred panel that shows one beat at a time.  Each
beat has a speaker, a text body, and either follow-up ``choices`` (1-9
number keys or click to pick) or a single ``next`` auto-advance
(SPACE or click to continue).  The active conversation is a dict in
the format produced by ``dialogue/*.py`` — see ``dialogue/debra_refugee.py``.
"""
from __future__ import annotations

from typing import Optional

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT


_PANEL_W = 900
_PANEL_H = 360
_PANEL_COLOR = (15, 20, 45, 240)
_BORDER_COLOR = arcade.color.STEEL_BLUE
_MAX_CHOICES = 4
_CHOICE_H = 40


class DialogueOverlay:
    """Modal-ish dialogue UI — pauses world input while open but does
    not pause gameplay updates (aliens keep flying, but player controls
    are ignored by the input handlers while ``open`` is True)."""

    def __init__(self) -> None:
        self.open: bool = False
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None
        self._tree: dict = {}
        self._current: str = ""
        self._aftermath: dict = {}

        self._t_stage = arcade.Text(
            "", 0, 0, arcade.color.LIGHT_BLUE, 10, bold=True,
            anchor_x="center", anchor_y="top", multiline=True, width=_PANEL_W - 40,
        )
        self._t_speaker = arcade.Text(
            "", 0, 0, arcade.color.YELLOW, 14, bold=True,
            anchor_x="left", anchor_y="top",
        )
        self._t_body = arcade.Text(
            "", 0, 0, arcade.color.WHITE, 12,
            anchor_x="left", anchor_y="top", multiline=True, width=_PANEL_W - 40,
        )
        self._t_hint = arcade.Text(
            "", 0, 0, (180, 180, 180), 10,
            anchor_x="center", anchor_y="bottom",
        )
        # Pooled text objects for up to _MAX_CHOICES choices.
        self._t_choices: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 11,
                        anchor_x="left", anchor_y="center",
                        multiline=True, width=_PANEL_W - 60)
            for _ in range(_MAX_CHOICES)
        ]

    # ── Lifecycle ────────────────────────────────────────────────────
    def start(self, tree: dict, aftermath_sink: Optional[dict] = None) -> None:
        """Open the overlay with the given tree.

        ``aftermath_sink`` is an optional dict that receives the tree's
        terminal ``aftermath`` flags when the conversation ends — use it
        to persist quest state onto the game view.
        """
        self._tree = tree
        self._current = tree.get("start", "")
        self._aftermath = aftermath_sink if aftermath_sink is not None else {}
        self.open = bool(self._current) and self._current in self._tree

    def close(self) -> None:
        self.open = False

    # ── Rendering ────────────────────────────────────────────────────
    def _panel_rect(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return (sw - _PANEL_W) // 2, (sh - _PANEL_H) // 2

    def _current_node(self) -> Optional[dict]:
        return self._tree.get(self._current)

    def draw(self) -> None:
        if not self.open:
            return
        node = self._current_node()
        if node is None:
            self.close()
            return
        px, py = self._panel_rect()
        arcade.draw_rect_filled(arcade.LBWH(px, py, _PANEL_W, _PANEL_H),
                                _PANEL_COLOR)
        arcade.draw_rect_outline(arcade.LBWH(px, py, _PANEL_W, _PANEL_H),
                                 _BORDER_COLOR, border_width=2)
        cx = px + _PANEL_W // 2

        # Stage direction (optional scene header)
        stage = node.get("stage")
        if stage:
            self._t_stage.text = f"[ {stage} ]"
            self._t_stage.x = cx
            self._t_stage.y = py + _PANEL_H - 14
            self._t_stage.draw()
            body_top = py + _PANEL_H - 54
        else:
            body_top = py + _PANEL_H - 20

        # Speaker + body
        self._t_speaker.text = node.get("speaker", "") + ":"
        self._t_speaker.x = px + 24
        self._t_speaker.y = body_top
        self._t_speaker.draw()

        self._t_body.text = node.get("text", "")
        self._t_body.x = px + 24
        self._t_body.y = body_top - 24
        self._t_body.draw()

        choices = node.get("choices") or []
        if choices:
            base_y = py + _CHOICE_H * len(choices) + 40
            for i, ch in enumerate(choices[:_MAX_CHOICES]):
                iy = base_y - i * _CHOICE_H
                arcade.draw_rect_filled(
                    arcade.LBWH(px + 16, iy - _CHOICE_H + 6,
                                _PANEL_W - 32, _CHOICE_H - 10),
                    (30, 50, 80, 220))
                arcade.draw_rect_outline(
                    arcade.LBWH(px + 16, iy - _CHOICE_H + 6,
                                _PANEL_W - 32, _CHOICE_H - 10),
                    _BORDER_COLOR, border_width=1)
                t = self._t_choices[i]
                t.text = f"{i + 1}. {ch['text']}"
                t.x = px + 28
                t.y = iy - _CHOICE_H // 2 + 4
                t.draw()
            hint = "Click a choice or press 1-%d" % len(choices)
        else:
            if node.get("end"):
                hint = "Click or press SPACE to leave"
            else:
                hint = "Click or press SPACE to continue"

        self._t_hint.text = hint
        self._t_hint.x = cx
        self._t_hint.y = py + 12
        self._t_hint.draw()

    # ── Input ────────────────────────────────────────────────────────
    def on_mouse_press(self, x: float, y: float) -> None:
        if not self.open:
            return
        node = self._current_node()
        if node is None:
            self.close()
            return
        choices = node.get("choices") or []
        if choices:
            px, py = self._panel_rect()
            base_y = py + _CHOICE_H * len(choices) + 40
            for i, ch in enumerate(choices[:_MAX_CHOICES]):
                iy = base_y - i * _CHOICE_H
                if (px + 16 <= x <= px + _PANEL_W - 16
                        and iy - _CHOICE_H + 6 <= y <= iy - 4):
                    self._pick(i)
                    return
        else:
            self._advance()

    def on_key_press(self, key: int) -> None:
        if not self.open:
            return
        if key == arcade.key.ESCAPE:
            # ESC closes without committing aftermath for non-terminal
            # nodes; a terminal node reached via the tree already
            # committed. This matches how other overlays exit.
            self.close()
            return
        node = self._current_node()
        if node is None:
            self.close()
            return
        choices = node.get("choices") or []
        if choices:
            for i in range(len(choices)):
                if key == arcade.key.KEY_1 + i:
                    self._pick(i)
                    return
        elif key in (arcade.key.SPACE, arcade.key.ENTER):
            self._advance()

    # ── Internal ─────────────────────────────────────────────────────
    def _pick(self, idx: int) -> None:
        node = self._current_node()
        if node is None:
            return
        choices = node.get("choices") or []
        if not (0 <= idx < len(choices)):
            return
        self._current = choices[idx]["next"]
        if self._current not in self._tree:
            self.close()

    def _advance(self) -> None:
        node = self._current_node()
        if node is None:
            self.close()
            return
        if node.get("end"):
            self._aftermath.update(node.get("aftermath") or {})
            self.close()
            return
        nxt = node.get("next")
        if not nxt or nxt not in self._tree:
            self.close()
            return
        self._current = nxt
