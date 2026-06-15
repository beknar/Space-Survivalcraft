"""Planetary surface build menu (docs/planets.md section 10).

A lean screen-space overlay listing the placeable surface buildings.  It is
distinct from the space ``BuildMenu`` (different rules: Home-Base-first, a
500 px home radius, and a power-slot budget instead of docking ports), so it
lives in its own module and is owned by the surface zone.

Toggle with ``B`` while on foot; click a row to enter placement, then click
in the world to place.  Rows gray out with a reason (need Home Base / max
built / no power budget / need resources) via ``planet_base.menu_availability``.
"""
from __future__ import annotations

import arcade

from specs import PLANETARY_BUILD_ORDER
from planet_base import menu_availability, build_budget, slots_used

_PANEL_W = 268
_ROW_H = 34
_TITLE_H = 30
_FOOTER_H = 30
_PAD = 8


class PlanetaryBuildMenu:
    def __init__(self) -> None:
        self.open: bool = False
        self._order = PLANETARY_BUILD_ORDER
        self._hover_idx: int = -1
        # Lazily created cached Text objects (one per row + chrome).
        self._t_title: arcade.Text | None = None
        self._t_footer: arcade.Text | None = None
        self._t_names: list[arcade.Text] = []
        self._t_costs: list[arcade.Text] = []

    # ── Geometry ────────────────────────────────────────────────────

    def _panel_rect(self) -> tuple[int, int, int, int]:
        win = arcade.get_window()
        h = _TITLE_H + _ROW_H * len(self._order) + _FOOTER_H + _PAD * 2
        x = win.width - _PANEL_W - 12
        y = win.height - h - 60
        return x, y, _PANEL_W, h

    def _row_rect(self, i: int) -> tuple[int, int, int, int]:
        x, y, w, h = self._panel_rect()
        top = y + h - _PAD - _TITLE_H
        ry = top - (i + 1) * _ROW_H
        return x + _PAD, ry, w - _PAD * 2, _ROW_H - 4

    def _row_at(self, mx: float, my: float) -> int:
        for i in range(len(self._order)):
            rx, ry, rw, rh = self._row_rect(i)
            if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                return i
        return -1

    # ── State ───────────────────────────────────────────────────────

    def toggle(self) -> None:
        self.open = not self.open
        self._hover_idx = -1

    def on_mouse_motion(self, x: float, y: float) -> None:
        if self.open:
            self._hover_idx = self._row_at(x, y)

    def on_mouse_press(self, x: float, y: float, buildings,
                       iron: int, copper: int, silicon: int) -> str | None:
        """Return the selected building key (if available) else None."""
        if not self.open:
            return None
        i = self._row_at(x, y)
        if i < 0:
            return None
        spec = self._order[i]
        ok, _ = menu_availability(spec, buildings, iron, copper, silicon)
        if not ok:
            return None
        return spec.key

    # ── Draw ────────────────────────────────────────────────────────

    def _ensure_text(self) -> None:
        if self._t_title is not None:
            return
        self._t_title = arcade.Text(
            "PLANETARY BUILD", 0, 0, arcade.color.CYAN, 12, bold=True)
        self._t_footer = arcade.Text(
            "", 0, 0, arcade.color.LIGHT_GRAY, 10)
        for _ in self._order:
            self._t_names.append(arcade.Text("", 0, 0, arcade.color.WHITE, 10))
            self._t_costs.append(
                arcade.Text("", 0, 0, arcade.color.LIGHT_GRAY, 8))

    def draw(self, buildings, iron: int, copper: int, silicon: int) -> None:
        if not self.open:
            return
        self._ensure_text()
        bs = list(buildings)
        px, py, pw, ph = self._panel_rect()
        arcade.draw_rect_filled(arcade.LBWH(px, py, pw, ph), (12, 16, 30, 235))
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, pw, ph), arcade.color.STEEL_BLUE, border_width=2)
        self._t_title.x = px + _PAD
        self._t_title.y = py + ph - _PAD - 18
        self._t_title.draw()

        for i, spec in enumerate(self._order):
            rx, ry, rw, rh = self._row_rect(i)
            ok, reason = menu_availability(spec, bs, iron, copper, silicon)
            hovered = (i == self._hover_idx)
            if not ok:
                bg = (30, 24, 24, 230)
            elif hovered:
                bg = (50, 80, 140, 255)
            else:
                bg = (25, 35, 70, 230)
            arcade.draw_rect_filled(arcade.LBWH(rx, ry, rw, rh), bg)
            arcade.draw_rect_outline(
                arcade.LBWH(rx, ry, rw, rh),
                arcade.color.CYAN if hovered else arcade.color.STEEL_BLUE,
                border_width=1)
            name = self._t_names[i]
            name.text = spec.label
            name.color = arcade.color.WHITE if ok else (130, 130, 140, 255)
            name.x = rx + 6
            name.y = ry + rh - 14
            name.draw()
            cost = self._t_costs[i]
            if ok:
                cost.text = (f"{spec.cost_iron}i {spec.cost_copper}c "
                             f"{spec.cost_silicon}s  ·  {spec.slots_used} slot")
                cost.color = arcade.color.LIGHT_GRAY
            else:
                cost.text = reason
                cost.color = (210, 140, 90, 255)
            cost.x = rx + 6
            cost.y = ry + 3
            cost.draw()

        used = slots_used(bs)
        total = build_budget(bs)
        self._t_footer.text = (
            f"Power budget: {used}/{total}   "
            f"Iron {iron}  Cu {copper}  Si {silicon}")
        self._t_footer.x = px + _PAD
        self._t_footer.y = py + _PAD
        self._t_footer.draw()
