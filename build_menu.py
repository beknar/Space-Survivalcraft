"""Build menu UI overlay for constructing space station modules."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    BUILD_MENU_W, BUILD_MENU_ITEM_H, BUILD_MENU_PAD,
    BUILDING_TYPES,
)


# Ordered list of building types as they appear in the menu
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
    "Advanced Ship",
    "Shield Generator",
    "Missile Array",
]


class BuildMenu:
    """Non-pausing overlay that lists buildable station modules.

    Drawn on the right side of the screen (opposite the HUD on the left).
    Each row shows an icon thumbnail, the module name, and its iron cost.
    Unavailable items are greyed out with a reason displayed.
    """

    def __init__(self) -> None:
        self.open: bool = False
        self._textures: dict[str, arcade.Texture] = {}
        self._hover_idx: int = -1
        self._hover_destroy: bool = False
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0

        # Panel geometry — right side of screen, vertically centred
        item_count = len(_MENU_ORDER)
        # Extra space for destroy button (BUILD_MENU_ITEM_H) below items
        self._panel_h = (BUILD_MENU_PAD * 2 + 32
                         + item_count * BUILD_MENU_ITEM_H
                         + BUILD_MENU_ITEM_H + 8  # destroy button + gap
                         + 24)
        self._panel_w = BUILD_MENU_W
        self._window = arcade.get_window()
        self._panel_x = self._window.width - self._panel_w - 8
        self._panel_y = (self._window.height - self._panel_h) // 2

        # Pre-built Text objects
        cx = self._panel_x + self._panel_w // 2
        self._t_title = arcade.Text(
            "BUILD MENU", cx,
            self._panel_y + self._panel_h - BUILD_MENU_PAD - 10,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "B / ESC \u2014 close    click to build",
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

    def _update_layout(self) -> None:
        """Recalculate panel position from current window size."""
        self._panel_x = self._window.width - self._panel_w - 8
        self._panel_y = (self._window.height - self._panel_h) // 2

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _item_rect(self, idx: int) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the clickable area of menu item *idx*."""
        x = self._panel_x + BUILD_MENU_PAD
        y = (self._panel_y + self._panel_h - BUILD_MENU_PAD - 32
             - (idx + 1) * BUILD_MENU_ITEM_H)
        w = self._panel_w - BUILD_MENU_PAD * 2
        h = BUILD_MENU_ITEM_H - 4
        return x, y, w, h

    def _destroy_rect(self) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) for the Destroy button."""
        x = self._panel_x + BUILD_MENU_PAD
        y = (self._panel_y + self._panel_h - BUILD_MENU_PAD - 32
             - (len(_MENU_ORDER) + 1) * BUILD_MENU_ITEM_H - 4)
        w = self._panel_w - BUILD_MENU_PAD * 2
        h = BUILD_MENU_ITEM_H - 4
        return x, y, w, h

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
    ) -> tuple[bool, str]:
        """Return (available, reason) for a building type."""
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
        self._hover_idx = -1
        self._hover_destroy = False
        if not self.open:
            return
        for i in range(len(_MENU_ORDER)):
            ix, iy, iw, ih = self._item_rect(i)
            if ix <= x <= ix + iw and iy <= y <= iy + ih:
                self._hover_idx = i
                return
        # Check destroy button hover
        dx, dy, dw, dh = self._destroy_rect()
        if dx <= x <= dx + dw and dy <= y <= dy + dh:
            self._hover_destroy = True

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
    ) -> Optional[str]:
        """Handle a click. Returns building type name, or "__destroy__" for destroy mode."""
        self._update_layout()
        if not self.open:
            return None
        for i, name in enumerate(_MENU_ORDER):
            ix, iy, iw, ih = self._item_rect(i)
            if ix <= x <= ix + iw and iy <= y <= iy + ih:
                avail, _ = self._check_availability(
                    name, iron, building_counts,
                    modules_used, module_capacity, has_home,
                    copper, unlocked_blueprints,
                )
                if avail:
                    return name
                return None
        # Check destroy button
        dx, dy, dw, dh = self._destroy_rect()
        if dx <= x <= dx + dw and dy <= y <= dy + dh:
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
    ) -> None:
        if not self.open:
            return
        self._update_layout()
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
            avail, reason = self._check_availability(
                name, iron, building_counts,
                modules_used, module_capacity, has_home,
                copper, unlocked_blueprints,
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
            self._t_cost.text = f"{stats['cost']} iron"
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
