"""Build menu UI overlay for constructing space station modules."""
from __future__ import annotations

from typing import Optional

import arcade
import pyglet

from menu_overlay import MenuOverlay
from menu_scroll import ScrollState, SCROLL_W as _SCROLL_W_SHARED
from constants import (
    BUILD_MENU_W, BUILD_MENU_ITEM_H, BUILD_MENU_PAD,
    BUILDING_TYPES,
)


# Ordered list of building types as they appear in the menu.
# "Basic Ship" sits right before "Advanced Ship" so the two ship-build
# rows are visually adjacent.
_MENU_ORDER = [
    "Home Station",
    "Service Module",
    "Power Receiver",
    "Solar Array 1",
    "Solar Array 2",
    "Turret 1",
    "Turret 2",
    "Repair Module",
    "Basic Crafter",
    "Advanced Crafter",
    "Fission Generator",
    "Basic Ship",
    "Advanced Ship",
    "Shield Generator",
    "Missile Array",
    "Quantum Wave Integrator",
]

# Scrollbar track width — sourced from the shared ``menu_scroll``
# module.  Kept as a module-local alias so existing ``_SCROLL_W``
# references in this file continue to work.
_SCROLL_W = _SCROLL_W_SHARED


class BuildMenu(MenuOverlay):
    """Non-pausing overlay that lists buildable station modules.

    Drawn on the right side of the screen (opposite the HUD on the left).
    Each row shows an icon thumbnail, the module name, and its iron cost.
    Unavailable items are greyed out with a reason displayed.

    The menu is scrollable.  Mouse wheel scrolls one row per click; the
    scrollbar on the right edge is also draggable for fine control, and
    clicking the track above/below the thumb scrolls one page at a time.
    """

    _title_text = "BUILD MENU"
    _close_text = "B / ESC — close    click to build"

    # Cap the panel height to keep it on-screen even on very small
    # windows.  When the building list is taller than this, the row
    # area scrolls instead of overflowing.
    _MAX_PANEL_H_FRACTION = 0.92

    def __init__(self) -> None:
        super().__init__()
        self._textures: dict[str, arcade.Texture] = {}
        self._hover_idx: int = -1
        self._hover_destroy: bool = False
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._ship_level: int = 1
        self._max_ship_exists: bool = False
        self._l1_ship_exists: bool = False

        # Scroll state + scrollbar geometry delegated to the shared
        # ``menu_scroll.ScrollState`` component (was ~70 lines of
        # private code here, identical to craft_menu).
        self._scroll = ScrollState(line_h=BUILD_MENU_ITEM_H)

        # Panel geometry — right side of screen, vertically centred
        item_count = len(_MENU_ORDER)
        # Full content height if every row was visible — determines
        # whether scrolling is needed and how big the thumb is.
        self._content_h = (item_count * BUILD_MENU_ITEM_H
                           + BUILD_MENU_ITEM_H + 8)  # rows + destroy
        self._panel_w = BUILD_MENU_W
        # Computed in _update_layout() once the window size is known.
        self._panel_h = 100
        self._panel_x = 0
        self._panel_y = 0
        self._update_layout()

        # Reposition inherited title + close text
        cx = self._panel_x + self._panel_w // 2
        self._t_title.x = cx
        self._t_title.y = self._panel_y + self._panel_h - BUILD_MENU_PAD - 10

        self._t_hint = arcade.Text(
            self._close_text,
            cx,
            self._panel_y + 12,
            (160, 160, 160), 9,
            anchor_x="center", anchor_y="center",
        )
        # Top-of-panel capacity readout — used to reuse ``_t_name``
        # which created a per-frame label rebuild fight with the
        # per-row name labels (see profile).  Now a dedicated Text,
        # guarded below so it only rebuilds when the counts change.
        self._t_capacity = arcade.Text(
            "", 0, 0, arcade.color.LIGHT_GRAY, 10, anchor_x="center",
        )
        self._last_cap_text: str = ""

        # Per-item Text pools.  The Advanced Crafter refactor
        # (commit d79cdaa) showed that rewriting one shared Text's
        # ``.text`` / ``.color`` per row per frame is the dominant
        # cost of a scrollable menu.  Build menu has ~16 rows × 3
        # Text mutations/row = ~48 pyglet layout rebuilds per frame
        # during scroll.  Pre-built per-row Texts sharing a pyglet
        # Batch collapses that to near-zero.
        self._text_batch = pyglet.graphics.Batch()
        self._t_names: list[arcade.Text] = []
        self._t_costs: list[arcade.Text] = []
        self._t_reasons: list[arcade.Text] = []
        for name in _MENU_ORDER:
            tn = arcade.Text(name, 0, 0, arcade.color.WHITE, 10, bold=True)
            tn._label.batch = self._text_batch
            self._t_names.append(tn)
            tc = arcade.Text("", 0, 0, arcade.color.ORANGE, 9)
            tc._label.batch = self._text_batch
            self._t_costs.append(tc)
            tr = arcade.Text("", 0, 0, (200, 80, 80), 8, anchor_x="right")
            tr._label.batch = self._text_batch
            self._t_reasons.append(tr)
        # Cached per-row state so we only touch pyglet when something
        # changed (cost labels + reasons are stable unless the world
        # state shifts).
        self._last_cost_text: list[str] = [""] * len(_MENU_ORDER)
        self._last_reason_text: list[str] = [""] * len(_MENU_ORDER)

        # Pooled fill rects for row backgrounds (same pattern as
        # craft_menu + HUD) — one SpriteList.draw replaces 16 per-
        # frame draw_rect_filled calls during scroll.
        self._rect_sprites: arcade.SpriteList = arcade.SpriteList()
        self._rect_slot: int = 0

        self._t_destroy = arcade.Text(
            "DESTROY", 0, 0, (255, 80, 80), 12, bold=True,
            anchor_x="center", anchor_y="center",
        )

    def _rect_reset(self) -> None:
        self._rect_slot = 0

    def _rect_add(self, x: float, y: float, w: float, h: float,
                  color: tuple) -> None:
        if self._rect_slot >= len(self._rect_sprites):
            self._rect_sprites.append(arcade.SpriteSolidColor(
                int(max(1, w)), int(max(1, h)), 0, 0, color))
        s = self._rect_sprites[self._rect_slot]
        s.width = max(1.0, w)
        s.height = max(1.0, h)
        s.center_x = x + w / 2
        s.center_y = y + h / 2
        s.color = color
        s.visible = True
        self._rect_slot += 1

    def _rect_flush(self) -> None:
        for i in range(self._rect_slot, len(self._rect_sprites)):
            self._rect_sprites[i].visible = False
        self._rect_sprites.draw()

    def set_textures(self, textures: dict[str, arcade.Texture]) -> None:
        """Provide icon textures for each building type (called once at init)."""
        self._textures = textures

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            # Reset scroll on open so the player always lands at the top.
            self._scroll.scroll_px = 0.0
            self._scroll.dragging = False

    # ── Backward-compatible attribute shims ─────────────────────────────────
    # Tests and legacy call sites may still access ``_scroll_px`` and
    # ``_dragging_scrollbar`` directly.  These properties keep that
    # contract while the actual state lives in ``self._scroll``.

    @property
    def _scroll_px(self) -> float:
        return self._scroll.scroll_px

    @_scroll_px.setter
    def _scroll_px(self, v: float) -> None:
        self._scroll.scroll_px = v

    @property
    def _dragging_scrollbar(self) -> bool:
        return self._scroll.dragging

    @_dragging_scrollbar.setter
    def _dragging_scrollbar(self, v: bool) -> None:
        self._scroll.dragging = v

    def _update_layout(self) -> None:
        """Recalculate panel position and size from current window."""
        max_h = int(self._window.height * self._MAX_PANEL_H_FRACTION)
        chrome = BUILD_MENU_PAD * 2 + 32 + 24
        wanted = chrome + self._content_h
        self._panel_h = min(max_h, wanted)
        self._panel_x = self._window.width - self._panel_w - 8
        self._panel_y = (self._window.height - self._panel_h) // 2
        _, _, _, viewport_h = self._viewport_rect()
        self._scroll.clamp(self._content_h, viewport_h)

    # ── Scroll geometry ───────────────────────────────────────────────────────

    def _viewport_rect(self) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the scrollable rows region."""
        x = self._panel_x + BUILD_MENU_PAD
        # Top of viewport sits below the capacity-indicator line.
        top = self._panel_y + self._panel_h - BUILD_MENU_PAD - 32
        # Bottom of viewport sits above the hint line.
        bottom = self._panel_y + 24
        h = max(BUILD_MENU_ITEM_H, top - bottom)
        # Reserve scrollbar width on the right when scrolling is needed.
        w = self._panel_w - BUILD_MENU_PAD * 2
        if self._needs_scrollbar():
            w -= (_SCROLL_W + 4)
        return x, bottom, w, h

    def _needs_scrollbar(self) -> bool:
        """True when the row list is taller than the viewport."""
        top = self._panel_y + self._panel_h - BUILD_MENU_PAD - 32
        bottom = self._panel_y + 24
        viewport_h = max(0, top - bottom)
        return self._scroll.needs(self._content_h, viewport_h)

    def _max_scroll(self) -> float:
        _, _, _, viewport_h = self._viewport_rect()
        return self._scroll.max_scroll(self._content_h, viewport_h)

    def _scrollbar_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) for the scrollbar TRACK."""
        vx, vy, _, vh = self._viewport_rect()
        track_x = self._panel_x + self._panel_w - BUILD_MENU_PAD - _SCROLL_W
        return track_x, vy, _SCROLL_W, vh

    def _scrollbar_thumb_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) for the draggable scrollbar THUMB."""
        return self._scroll.thumb_rect(
            self._scrollbar_rect(), self._content_h)

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _row_y(self, idx: int) -> int:
        """Top-anchored Y for row *idx* (within its own coordinate space).

        The visible Y on screen is computed in ``_item_rect`` which adds
        the viewport top and subtracts the scroll offset.
        """
        return idx * BUILD_MENU_ITEM_H

    def _item_rect(self, idx: int) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the clickable area of menu item *idx*.

        May return a y that's outside the viewport when scrolled — the
        draw + click handlers must check visibility themselves."""
        vx, vy, vw, vh = self._viewport_rect()
        # Top of viewport in screen coords
        top = vy + vh
        rel_y = self._row_y(idx)
        y = top - rel_y - BUILD_MENU_ITEM_H + int(self._scroll_px)
        h = BUILD_MENU_ITEM_H - 4
        return vx, y, vw, h

    def _destroy_rect(self) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the Destroy button."""
        vx, vy, vw, vh = self._viewport_rect()
        top = vy + vh
        rel_y = self._row_y(len(_MENU_ORDER)) + 4
        y = top - rel_y - BUILD_MENU_ITEM_H + int(self._scroll_px)
        h = BUILD_MENU_ITEM_H - 4
        return vx, y, vw, h

    def _row_visible(self, y: int, h: int) -> bool:
        _, vy, _, vh = self._viewport_rect()
        return (y + h) > vy and y < (vy + vh)

    def _panel_contains(self, x: float, y: float) -> bool:
        px, py = self._panel_x, self._panel_y
        return px <= x <= px + self._panel_w and py <= y <= py + self._panel_h

    # ── Availability logic ────────────────────────────────────────────────────

    @staticmethod
    def _check_availability(
        name: str,
        iron: int,
        building_counts: dict[str, int],
        modules_used: int,
        module_capacity: int,
        has_home: bool,
        copper: int = 0,
        unlocked_blueprints: set | None = None,
        ship_level: int = 1,
        max_ship_exists: bool = False,
        l1_ship_exists: bool = True,
    ) -> tuple[bool, str]:
        """Return (available, reason) for a building type."""
        from constants import SHIP_MAX_LEVEL
        stats = BUILDING_TYPES[name]
        cost = stats["cost"]
        copper_cost = stats.get("cost_copper", 0)
        max_count = stats["max"]
        slots = stats["slots_used"]

        if name == "Home Station":
            if building_counts.get("Home Station", 0) >= 1:
                return False, "Already built"
            if iron < cost:
                return False, f"Need {cost} iron"
            return True, ""

        # All other buildings require a Home Station
        if not has_home:
            return False, "Need Home Station"

        if name == "Advanced Ship":
            if ship_level >= SHIP_MAX_LEVEL:
                return False, "Ship already at max level"
            if max_ship_exists:
                return False, "Max-level ship already exists"

        if name == "Basic Ship":
            # Only one L1 ship allowed (player or parked).  Once a L1
            # parked ship is destroyed, the count drops and the player
            # can rebuild for the half-cost listed in constants.
            if l1_ship_exists:
                return False, "L1 ship already exists"

        # Blueprint gate
        bp_key = stats.get("requires_blueprint")
        if bp_key:
            if not unlocked_blueprints or bp_key not in unlocked_blueprints:
                return False, "Need blueprint"

        if iron < cost:
            return False, f"Need {cost} iron"

        if copper_cost > 0 and copper < copper_cost:
            return False, f"Need {copper_cost} copper"

        if max_count is not None and building_counts.get(name, 0) >= max_count:
            return False, f"Max {max_count} built"

        if modules_used + slots > module_capacity:
            return False, "At capacity"

        return True, ""

    # ── Input ─────────────────────────────────────────────────────────────────

    def on_mouse_motion(self, x: float, y: float) -> None:
        self._update_layout()
        self._mouse_x = x
        self._mouse_y = y
        # Drag-scroll: delegate to the shared scroll component.
        if self._scroll.dragging:
            self._scroll.on_motion(
                y, self._scrollbar_rect(), self._content_h)
            return
        self._hover_idx = -1
        self._hover_destroy = False
        if not self.open:
            return
        for i in range(len(_MENU_ORDER)):
            ix, iy, iw, ih = self._item_rect(i)
            if not self._row_visible(iy, ih):
                continue
            if ix <= x <= ix + iw and iy <= y <= iy + ih:
                self._hover_idx = i
                return
        # Check destroy button hover
        dx, dy, dw, dh = self._destroy_rect()
        if self._row_visible(dy, dh) and dx <= x <= dx + dw and dy <= y <= dy + dh:
            self._hover_destroy = True

    def on_mouse_release(self, x: float, y: float) -> None:
        """Drop scrollbar drag on mouse-up."""
        self._scroll.on_release()

    def on_mouse_scroll(self, scroll_y: float) -> None:
        """Mouse-wheel scroll — one row per click, up = scroll up."""
        if not self.open:
            return
        _, _, _, viewport_h = self._viewport_rect()
        self._scroll.on_wheel(scroll_y, self._content_h, viewport_h)

    def _handle_scrollbar_press(self, x: float, y: float) -> bool:
        """If the click hit the scrollbar, handle it and return True."""
        return self._scroll.on_press(
            x, y, self._scrollbar_rect(), self._content_h)

    def on_mouse_press(
        self,
        x: float,
        y: float,
        iron: int,
        building_counts: dict[str, int],
        modules_used: int,
        module_capacity: int,
        has_home: bool,
        copper: int = 0,
        unlocked_blueprints: set | None = None,
        ship_level: int = 1,
        max_ship_exists: bool = False,
        l1_ship_exists: bool = True,
    ) -> Optional[str]:
        """Handle a click. Returns building type name, or "__destroy__" for destroy mode."""
        self._update_layout()
        self._ship_level = ship_level
        self._max_ship_exists = max_ship_exists
        self._l1_ship_exists = l1_ship_exists
        if not self.open:
            return None
        # Scrollbar interactions take priority — a click on the bar
        # never falls through to a row click underneath.
        if self._handle_scrollbar_press(x, y):
            return None
        for i, name in enumerate(_MENU_ORDER):
            ix, iy, iw, ih = self._item_rect(i)
            if not self._row_visible(iy, ih):
                continue
            if ix <= x <= ix + iw and iy <= y <= iy + ih:
                avail, _ = self._check_availability(
                    name, iron, building_counts,
                    modules_used, module_capacity, has_home,
                    copper, unlocked_blueprints, ship_level,
                    max_ship_exists, l1_ship_exists,
                )
                if avail:
                    return name
                return None
        # Check destroy button
        dx, dy, dw, dh = self._destroy_rect()
        if (self._row_visible(dy, dh)
                and dx <= x <= dx + dw and dy <= y <= dy + dh):
            if has_home:
                return "__destroy__"
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(
        self,
        iron: int,
        building_counts: dict[str, int],
        modules_used: int,
        module_capacity: int,
        has_home: bool,
        copper: int = 0,
        unlocked_blueprints: set | None = None,
        ship_level: int = 1,
        max_ship_exists: bool = False,
        l1_ship_exists: bool = True,
    ) -> None:
        if not self.open:
            return
        self._update_layout()
        self._ship_level = ship_level
        self._max_ship_exists = max_ship_exists
        self._l1_ship_exists = l1_ship_exists
        # Update text positions for current layout
        cx = self._panel_x + self._panel_w // 2
        self._t_title.x = cx
        self._t_title.y = self._panel_y + self._panel_h - BUILD_MENU_PAD - 10
        self._t_hint.x = cx
        self._t_hint.y = self._panel_y + 12

        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(self._panel_x, self._panel_y,
                        self._panel_w, self._panel_h),
            (10, 10, 35, 230),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(self._panel_x, self._panel_y,
                        self._panel_w, self._panel_h),
            arcade.color.STEEL_BLUE, border_width=2,
        )
        self._t_title.draw()
        self._t_hint.draw()

        # Capacity indicator — dedicated Text, text rebuilt only on
        # count change.
        cap_text = f"Modules: {modules_used}/{module_capacity}"
        if cap_text != self._last_cap_text:
            self._last_cap_text = cap_text
            self._t_capacity.text = cap_text
        self._t_capacity.x = self._panel_x + self._panel_w // 2
        self._t_capacity.y = self._panel_y + self._panel_h - BUILD_MENU_PAD - 28
        self._t_capacity.draw()

        self._draw_menu_items(iron, building_counts, modules_used,
                              module_capacity, has_home, copper,
                              unlocked_blueprints)
        self._draw_destroy_button(has_home)
        if self._needs_scrollbar():
            self._draw_scrollbar()

    def _draw_menu_items(
        self,
        iron: int,
        building_counts: dict[str, int],
        modules_used: int,
        module_capacity: int,
        has_home: bool,
        copper: int = 0,
        unlocked_blueprints: set | None = None,
    ) -> None:
        """Draw the list of buildable module rows.

        Phase 1 collects every fill rect into the shared SpriteList
        pool; Phase 2 updates per-row Text state (guarded) and marks
        off-viewport labels invisible; ``batch.draw()`` renders every
        label in one GL call.  Outlines + icons stay immediate-mode —
        border_width=1 isn't sprite-batchable without 4 edge sprites
        per row, and textures are already batched by arcade's atlas.
        """
        # Pre-compute availability once per row so Phase 1 + Phase 2
        # share the same visibility/color decisions without re-running
        # the ``_check_availability`` cost (~1 ms/frame cumulatively
        # over 16 rows).
        statuses: list[tuple] = []
        for i, name in enumerate(_MENU_ORDER):
            ix, iy, iw, ih = self._item_rect(i)
            visible = self._row_visible(iy, ih)
            avail: bool = False
            reason: str = ""
            if visible:
                avail, reason = self._check_availability(
                    name, iron, building_counts,
                    modules_used, module_capacity, has_home,
                    copper, unlocked_blueprints, self._ship_level,
                    self._max_ship_exists, self._l1_ship_exists,
                )
            statuses.append((ix, iy, iw, ih, visible, avail, reason))

        # Phase 1 — pool fills.
        self._rect_reset()
        for i, (ix, iy, iw, ih, visible, avail, _reason) in enumerate(statuses):
            if not visible:
                continue
            is_hover = (i == self._hover_idx)
            if is_hover and avail:
                fill = (50, 70, 100, 220)
            elif avail:
                fill = (30, 50, 30, 200)
            else:
                fill = (40, 30, 30, 200)
            self._rect_add(ix, iy, iw, ih, fill)
        self._rect_flush()

        # Phase 2 — outlines, icons, and per-row Text state.  Each
        # Text mutation is guarded so pyglet only rebuilds a label
        # when its content / color / position actually changed.
        for i, (ix, iy, iw, ih, visible, avail, reason) in enumerate(statuses):
            tn = self._t_names[i]
            tc = self._t_costs[i]
            tr = self._t_reasons[i]
            if not visible:
                if tn._label.visible:
                    tn._label.visible = False
                if tc._label.visible:
                    tc._label.visible = False
                if tr._label.visible:
                    tr._label.visible = False
                continue
            arcade.draw_rect_outline(
                arcade.LBWH(ix, iy, iw, ih), (60, 80, 120), border_width=1,
            )
            name = _MENU_ORDER[i]
            tex = self._textures.get(name)
            if tex is not None:
                icon_size = ih - 8
                alpha = 255 if avail else 100
                arcade.draw_texture_rect(
                    tex,
                    arcade.LBWH(ix + 4, iy + 4, icon_size, icon_size),
                    alpha=alpha,
                )
            name_x = ix + ih + 4
            # Name label (content is static per row — ``.text`` was
            # preset in __init__; only position + color change).
            name_colour = (arcade.color.WHITE if avail
                           else arcade.color.Color(120, 120, 120, 255))
            if tn.x != name_x:
                tn.x = name_x
            ny = iy + ih - 16
            if tn.y != ny:
                tn.y = ny
            if tuple(tn.color) != tuple(name_colour):
                tn.color = name_colour
            if not tn._label.visible:
                tn._label.visible = True
            # Cost label.
            stats = BUILDING_TYPES[name]
            cost_label = f"{stats['cost']} iron"
            if stats.get("cost_copper", 0) > 0:
                cost_label += f" + {stats['cost_copper']} copper"
            if cost_label != self._last_cost_text[i]:
                self._last_cost_text[i] = cost_label
                tc.text = cost_label
            if tc.x != name_x:
                tc.x = name_x
            cy = iy + 6
            if tc.y != cy:
                tc.y = cy
            cost_colour = (arcade.color.ORANGE if avail
                           else arcade.color.Color(100, 70, 30, 255))
            if tuple(tc.color) != tuple(cost_colour):
                tc.color = cost_colour
            if not tc._label.visible:
                tc._label.visible = True
            # Reason label — only set when unavailable + non-empty.
            if not avail and reason:
                if reason != self._last_reason_text[i]:
                    self._last_reason_text[i] = reason
                    tr.text = reason
                rx = ix + iw - 8
                ry_ = iy + ih // 2 - 4
                if tr.x != rx:
                    tr.x = rx
                if tr.y != ry_:
                    tr.y = ry_
                if not tr._label.visible:
                    tr._label.visible = True
            else:
                if tr._label.visible:
                    tr._label.visible = False

        # One batch draw for every per-row label — replaces ~48
        # pyglet ``Label.draw`` calls and 48 ``set_state`` invocations
        # per frame while scrolling.
        self._text_batch.draw()

    def _draw_destroy_button(self, has_home: bool) -> None:
        """Draw the destroy-mode button at the bottom of the menu."""
        dx, dy, dw, dh = self._destroy_rect()
        if not self._row_visible(dy, dh):
            return
        destroy_fill = (80, 30, 30, 220) if self._hover_destroy else (50, 20, 20, 200)
        if not has_home:
            destroy_fill = (40, 30, 30, 150)
        arcade.draw_rect_filled(arcade.LBWH(dx, dy, dw, dh), destroy_fill)
        arcade.draw_rect_outline(
            arcade.LBWH(dx, dy, dw, dh), (120, 50, 50), border_width=1,
        )
        self._t_destroy.x = dx + dw // 2
        self._t_destroy.y = dy + dh // 2
        self._t_destroy.color = (255, 80, 80) if has_home else (100, 50, 50)
        self._t_destroy.draw()

    def _draw_scrollbar(self) -> None:
        """Delegate to the shared ScrollState draw path."""
        self._scroll.draw(self._scrollbar_rect(), self._content_h)
