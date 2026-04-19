"""Build menu UI overlay for constructing space station modules."""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay
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
]

# Scrollbar geometry — small enough to stay out of the way of the row
# layout but big enough to grab with the mouse.
_SCROLL_W = 10            # scrollbar track width
_SCROLL_THUMB_MIN_H = 22  # minimum drag-thumb height in pixels


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

        # Scroll state: pixel offset from the top of the row list.
        self._scroll_px: float = 0.0
        # Drag state: when True, mouse motion sets scroll position.
        self._dragging_scrollbar: bool = False
        self._drag_anchor_y: float = 0.0
        self._drag_anchor_scroll: float = 0.0

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
        # Reusable text objects for item rows
        self._t_name = arcade.Text("", 0, 0, arcade.color.WHITE, 10, bold=True)
        self._t_cost = arcade.Text("", 0, 0, arcade.color.ORANGE, 9)
        self._t_reason = arcade.Text("", 0, 0, (200, 80, 80), 8)
        self._t_destroy = arcade.Text(
            "DESTROY", 0, 0, (255, 80, 80), 12, bold=True,
            anchor_x="center", anchor_y="center",
        )

    def set_textures(self, textures: dict[str, arcade.Texture]) -> None:
        """Provide icon textures for each building type (called once at init)."""
        self._textures = textures

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            # Reset scroll on open so the player always lands at the top.
            self._scroll_px = 0.0
            self._dragging_scrollbar = False

    def _update_layout(self) -> None:
        """Recalculate panel position and size from current window."""
        max_h = int(self._window.height * self._MAX_PANEL_H_FRACTION)
        # Title (~40 px) + capacity row (~20 px) + hint (~24 px) chrome +
        # padding.  When the content is shorter than the cap the panel
        # shrinks to fit; when it's longer, the row area is clipped and
        # the rest scrolls.
        chrome = BUILD_MENU_PAD * 2 + 32 + 24
        wanted = chrome + self._content_h
        self._panel_h = min(max_h, wanted)
        self._panel_x = self._window.width - self._panel_w - 8
        self._panel_y = (self._window.height - self._panel_h) // 2
        self._clamp_scroll()

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
        x = self._panel_x + BUILD_MENU_PAD
        top = self._panel_y + self._panel_h - BUILD_MENU_PAD - 32
        bottom = self._panel_y + 24
        viewport_h = max(0, top - bottom)
        return self._content_h > viewport_h

    def _max_scroll(self) -> float:
        _, _, _, viewport_h = self._viewport_rect()
        return max(0.0, self._content_h - viewport_h)

    def _clamp_scroll(self) -> None:
        self._scroll_px = max(0.0, min(self._max_scroll(), self._scroll_px))

    def _scrollbar_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) for the scrollbar TRACK."""
        vx, vy, _, vh = self._viewport_rect()
        track_x = self._panel_x + self._panel_w - BUILD_MENU_PAD - _SCROLL_W
        return track_x, vy, _SCROLL_W, vh

    def _scrollbar_thumb_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) for the draggable scrollbar THUMB."""
        tx, ty, tw, th = self._scrollbar_rect()
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return tx, ty, tw, th
        # Thumb height proportional to viewport / content ratio.
        ratio = th / (th + max_scroll)
        thumb_h = max(_SCROLL_THUMB_MIN_H, int(th * ratio))
        # Top-anchored: scroll_px = 0 → thumb at top of track
        thumb_y = ty + th - thumb_h - int(
            (th - thumb_h) * (self._scroll_px / max_scroll))
        return tx, thumb_y, tw, thumb_h

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
        # Drag-scroll: while the scrollbar thumb is held, mouse motion
        # converts vertical delta into a scroll position.
        if self._dragging_scrollbar:
            self._set_scroll_from_drag(y)
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
        self._dragging_scrollbar = False

    def on_mouse_scroll(self, scroll_y: float) -> None:
        """Mouse-wheel scroll — one row per click, up = scroll up."""
        if not self.open or not self._needs_scrollbar():
            return
        # Up scroll (positive scroll_y) reveals earlier items, which
        # means a SMALLER scroll_px (we anchor scroll at the top).
        self._scroll_px -= scroll_y * BUILD_MENU_ITEM_H
        self._clamp_scroll()

    def _set_scroll_from_drag(self, mouse_y: float) -> None:
        """Translate a thumb drag into a scroll_px value."""
        tx, ty, tw, th = self._scrollbar_rect()
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return
        # Thumb anchor: scroll grows as thumb moves DOWN.
        # Compute the thumb top position based on current drag vs anchor.
        delta = self._drag_anchor_y - mouse_y
        ratio = th / (th + max_scroll)
        thumb_h = max(_SCROLL_THUMB_MIN_H, int(th * ratio))
        movable = max(1, th - thumb_h)
        self._scroll_px = (self._drag_anchor_scroll
                           + (delta / movable) * max_scroll)
        self._clamp_scroll()

    def _handle_scrollbar_press(self, x: float, y: float) -> bool:
        """If the click hit the scrollbar, handle it and return True."""
        if not self._needs_scrollbar():
            return False
        tx, ty, tw, th = self._scrollbar_rect()
        if not (tx <= x <= tx + tw and ty <= y <= ty + th):
            return False
        thx, thy, thw, thh = self._scrollbar_thumb_rect()
        if thy <= y <= thy + thh:
            # Started a thumb drag.
            self._dragging_scrollbar = True
            self._drag_anchor_y = y
            self._drag_anchor_scroll = self._scroll_px
            return True
        # Clicked above thumb → page up; below → page down.
        _, _, _, vh = self._viewport_rect()
        page = max(BUILD_MENU_ITEM_H, vh - BUILD_MENU_ITEM_H)
        if y > thy + thh:
            self._scroll_px -= page  # toward top
        else:
            self._scroll_px += page  # toward bottom
        self._clamp_scroll()
        return True

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

        # Capacity indicator
        cap_text = f"Modules: {modules_used}/{module_capacity}"
        self._t_name.text = cap_text
        self._t_name.x = self._panel_x + self._panel_w // 2
        self._t_name.y = self._panel_y + self._panel_h - BUILD_MENU_PAD - 28
        self._t_name.color = arcade.color.LIGHT_GRAY
        self._t_name.anchor_x = "center"
        self._t_name.bold = False
        self._t_name.draw()
        self._t_name.anchor_x = "left"
        self._t_name.bold = True

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
        """Draw the list of buildable module rows."""
        for i, name in enumerate(_MENU_ORDER):
            ix, iy, iw, ih = self._item_rect(i)
            if not self._row_visible(iy, ih):
                continue
            avail, reason = self._check_availability(
                name, iron, building_counts,
                modules_used, module_capacity, has_home,
                copper, unlocked_blueprints, self._ship_level,
                self._max_ship_exists, self._l1_ship_exists,
            )

            # Row background
            is_hover = (i == self._hover_idx)
            if is_hover and avail:
                fill = (50, 70, 100, 220)
            elif avail:
                fill = (30, 50, 30, 200)
            else:
                fill = (40, 30, 30, 200)

            arcade.draw_rect_filled(arcade.LBWH(ix, iy, iw, ih), fill)
            arcade.draw_rect_outline(
                arcade.LBWH(ix, iy, iw, ih), (60, 80, 120), border_width=1,
            )

            # Icon thumbnail
            tex = self._textures.get(name)
            if tex is not None:
                icon_size = ih - 8
                alpha = 255 if avail else 100
                arcade.draw_texture_rect(
                    tex,
                    arcade.LBWH(ix + 4, iy + 4, icon_size, icon_size),
                    alpha=alpha,
                )

            # Name
            name_x = ix + ih + 4
            name_colour = arcade.color.WHITE if avail else (120, 120, 120)
            self._t_name.text = name
            self._t_name.x = name_x
            self._t_name.y = iy + ih - 16
            self._t_name.color = name_colour
            self._t_name.draw()

            # Cost
            stats = BUILDING_TYPES[name]
            cost_label = f"{stats['cost']} iron"
            if stats.get("cost_copper", 0) > 0:
                cost_label += f" + {stats['cost_copper']} copper"
            self._t_cost.text = cost_label
            self._t_cost.x = name_x
            self._t_cost.y = iy + 6
            self._t_cost.color = arcade.color.ORANGE if avail else (100, 70, 30)
            self._t_cost.draw()

            # Reason (unavailable)
            if not avail and reason:
                self._t_reason.text = reason
                self._t_reason.x = ix + iw - 8
                self._t_reason.y = iy + ih // 2 - 4
                self._t_reason.anchor_x = "right"
                self._t_reason.draw()
                self._t_reason.anchor_x = "left"

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
        tx, ty, tw, th = self._scrollbar_rect()
        # Track
        arcade.draw_rect_filled(
            arcade.LBWH(tx, ty, tw, th), (20, 30, 50, 220))
        # Thumb
        thx, thy, thw, thh = self._scrollbar_thumb_rect()
        thumb_color = ((180, 220, 255, 240) if self._dragging_scrollbar
                       else (120, 160, 220, 240))
        arcade.draw_rect_filled(
            arcade.LBWH(thx, thy, thw, thh), thumb_color)
