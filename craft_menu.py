"""Craft menu overlay for the Basic Crafter module."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    CRAFT_TIME, CRAFT_IRON_COST, CRAFT_RESULT_COUNT,
    MODULE_TYPES,
)

_PANEL_W = 300
_PANEL_H_MIN = 280
_RECIPE_H = 28
_HEADER = 55   # title area
_DETAIL = 40   # detail text + padding
_BTN_AREA = 80 # craft button + progress bar + close text



class CraftMenu:
    """Overlay for the Basic Crafter — shows Repair Pack recipe + unlocked module recipes."""

    def __init__(self) -> None:
        self.open: bool = False
        self._crafting: bool = False
        self._progress: float = 0.0
        self._craft_target: str = ""  # "" = repair pack, "shield_recharge", or module key

        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

        # Available module recipes
        self._recipes: list[dict] = []
        self._unlocked: set[str] = set()  # permanently unlocked module keys
        self._scroll: int = 0
        self._selected: int = 0  # 0 = repair pack, 1+ = module recipes

        self._t_title = arcade.Text(
            "BASIC CRAFTER", 0, 0,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_line = arcade.Text("", 0, 0, arcade.color.WHITE, 9)
        # Pre-built recipe text objects (avoid .text churn per frame)
        self._t_recipes: list[arcade.Text] = []
        self._t_detail = arcade.Text("", 0, 0, arcade.color.LIME_GREEN, 9)
        self._last_pct: int = -1  # cached progress percentage
        self._t_btn = arcade.Text(
            "CRAFT", 0, 0, arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_status = arcade.Text("", 0, 0, arcade.color.YELLOW, 10,
                                     bold=True, anchor_x="center")
        self._t_close = arcade.Text(
            "ESC / click outside to close", 0, 0,
            (120, 120, 120), 8, anchor_x="center",
        )
        # Item icons (set by game_view)
        self.item_icons: dict[str, arcade.Texture] = {}
        self.repair_pack_icon: Optional[arcade.Texture] = None
        self.shield_recharge_icon: Optional[arcade.Texture] = None

    def refresh_recipes(self, station_inv) -> None:
        """Scan station inventory for blueprints and build recipe list.

        Once a blueprint is deposited, the recipe is permanently unlocked.
        """
        # Unlock any new blueprints found in station inv
        for key in MODULE_TYPES:
            if station_inv.count_item(f"bp_{key}") > 0:
                self._unlocked.add(key)
        # Build recipe list from all unlocked modules
        self._recipes = []
        for key in MODULE_TYPES:
            if key in self._unlocked:
                info = MODULE_TYPES[key]
                self._recipes.append({
                    "key": key,
                    "label": info["label"],
                    "cost": info["craft_cost"],
                    "cost_copper": info.get("craft_cost_copper", 0),
                })
        self._selected = 0
        self._scroll = 0
        # Pre-build recipe text objects (index 0 = repair pack, 1 = shield recharge, then modules)
        self._t_recipes = [
            arcade.Text(f"Repair Pack x{CRAFT_RESULT_COUNT}  —  {CRAFT_IRON_COST} iron",
                        0, 0, arcade.color.WHITE, 9),
            arcade.Text(f"Shield Recharge x{CRAFT_RESULT_COUNT}  —  {CRAFT_IRON_COST} iron",
                        0, 0, arcade.color.WHITE, 9),
        ]
        for recipe in self._recipes:
            info = MODULE_TYPES[recipe["key"]]
            if info.get("blueprint_only"):
                from constants import BUILDING_TYPES
                bld = BUILDING_TYPES.get("Advanced Crafter", {})
                b_iron = bld.get("cost", 0)
                b_copper = bld.get("cost_copper", 0)
                cost_text = f"Unlocks building ({b_iron} iron + {b_copper} copper)"
            else:
                cost_text = f"{recipe['cost']} iron"
                if recipe.get("cost_copper", 0) > 0:
                    cost_text += f" + {recipe['cost_copper']} copper"
            self._t_recipes.append(
                arcade.Text(f"{recipe['label']}  —  {cost_text}",
                            0, 0, arcade.color.WHITE, 9)
            )
        # Pre-build detail text
        self._t_detail.text = f"Produces {CRAFT_RESULT_COUNT}x Repair Pack ({int(CRAFT_TIME)}s)"

    def toggle(self) -> None:
        self.open = not self.open

    def _panel_height(self) -> int:
        n = 2 + len(self._recipes)  # repair pack + shield recharge + modules
        return max(_PANEL_H_MIN, _HEADER + n * _RECIPE_H + _DETAIL + _BTN_AREA)

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ph = self._panel_height()
        return (sw - _PANEL_W) // 2, (sh - ph) // 2

    def _craft_btn_rect(self) -> tuple[int, int, int, int]:
        px, py = self._panel_origin()
        bw, bh = 140, 32
        bx = px + (_PANEL_W - bw) // 2
        by = py + 40
        return bx, by, bw, bh

    def on_mouse_press(self, x: float, y: float, station_iron: int) -> Optional[str]:
        """Returns 'craft' or 'craft_module:key' if craft button clicked, None otherwise."""
        if not self.open:
            return None
        px, py = self._panel_origin()
        ph = self._panel_height()
        if not (px <= x <= px + _PANEL_W and py <= y <= py + ph):
            self.open = False
            return None

        # Recipe list clicks (0=repair pack, 1=shield recharge, 2+=modules)
        list_y = py + ph - _HEADER
        total_recipes = 2 + len(self._recipes)  # 2 consumables + modules
        for i in range(total_recipes):
            ry = list_y - i * _RECIPE_H
            if px + 10 <= x <= px + _PANEL_W - 10 and ry <= y <= ry + _RECIPE_H:
                self._selected = i
                return None

        # Craft button
        bx, by, bw, bh = self._craft_btn_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            if self._crafting:
                return "cancel_craft"
            if self._selected == 0:
                # Repair pack
                if station_iron >= CRAFT_IRON_COST:
                    self._craft_target = ""
                    return "craft"
            elif self._selected == 1:
                # Shield Recharge
                if station_iron >= CRAFT_IRON_COST:
                    self._craft_target = "shield_recharge"
                    return "craft"
            else:
                # Module recipe
                idx = self._selected - 2
                if idx < len(self._recipes):
                    recipe = self._recipes[idx]
                    if station_iron >= recipe["cost"]:
                        self._craft_target = recipe["key"]
                        return f"craft_module:{recipe['key']}"
        return None

    def update(self, progress: float, crafting: bool) -> None:
        self._progress = progress
        self._crafting = crafting

    def draw(self, station_iron: int) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()
        ph = self._panel_height()

        arcade.draw_rect_filled(
            arcade.LBWH(px, py, _PANEL_W, ph), (15, 20, 45, 240))
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, _PANEL_W, ph),
            arcade.color.STEEL_BLUE, border_width=2)

        self._t_title.x = px + _PANEL_W // 2
        self._t_title.y = py + ph - 20
        self._t_title.draw()

        self._draw_recipe_list(px, py, ph, station_iron)
        self._draw_craft_button(px, py, station_iron)

        self._t_close.x = px + _PANEL_W // 2; self._t_close.y = py + 10
        self._t_close.draw()

    def _draw_recipe_list(self, px: int, py: int, ph: int, station_iron: int) -> None:
        """Draw the scrollable recipe list and selected recipe detail."""
        list_y = py + ph - _HEADER

        # Draw recipe list using pre-built text objects
        # Costs: index 0=repair pack, 1=shield recharge, 2+=modules
        costs = [CRAFT_IRON_COST, CRAFT_IRON_COST] + [r["cost"] for r in self._recipes]
        for i, tr in enumerate(self._t_recipes):
            ry = list_y - i * _RECIPE_H
            sel = (self._selected == i)
            fill = (50, 70, 100, 220) if sel else (25, 30, 50, 180)
            arcade.draw_rect_filled(arcade.LBWH(px + 10, ry, _PANEL_W - 20, _RECIPE_H - 2), fill)
            affordable = station_iron >= costs[i] if i < len(costs) else False
            tr.color = arcade.color.CYAN if sel else (arcade.color.WHITE if affordable else (150, 80, 80))
            # Draw recipe icon
            icon_w = 0
            if i == 0 and self.repair_pack_icon:
                arcade.draw_texture_rect(self.repair_pack_icon,
                    arcade.LBWH(px + 14, ry + 2, _RECIPE_H - 6, _RECIPE_H - 6))
                icon_w = _RECIPE_H - 2
            elif i == 1 and self.shield_recharge_icon:
                arcade.draw_texture_rect(self.shield_recharge_icon,
                    arcade.LBWH(px + 14, ry + 2, _RECIPE_H - 6, _RECIPE_H - 6))
                icon_w = _RECIPE_H - 2
            elif i >= 2 and i - 2 < len(self._recipes):
                ricon = self.item_icons.get(self._recipes[i - 2]["key"])
                if ricon:
                    arcade.draw_texture_rect(ricon,
                        arcade.LBWH(px + 14, ry + 2, _RECIPE_H - 6, _RECIPE_H - 6))
                    icon_w = _RECIPE_H - 2
            tr.x = px + 16 + icon_w; tr.y = ry + _RECIPE_H // 2
            tr.draw()

        # Selected recipe detail with icon
        detail_y = list_y - len(self._t_recipes) * _RECIPE_H - 10
        icon = None
        if self._selected == 0:
            self._t_detail.text = f"Produces {CRAFT_RESULT_COUNT}x Repair Pack ({int(CRAFT_TIME)}s)"
            icon = self.repair_pack_icon
        elif self._selected == 1:
            self._t_detail.text = f"Produces {CRAFT_RESULT_COUNT}x Shield Recharge ({int(CRAFT_TIME)}s)"
            icon = self.shield_recharge_icon
        elif self._selected - 2 < len(self._recipes):
            recipe = self._recipes[self._selected - 2]
            info = MODULE_TYPES[recipe["key"]]
            self._t_detail.text = f"{info['label']}: {_effect_desc(info)} ({int(CRAFT_TIME)}s)"
            icon = self.item_icons.get(recipe["key"])
        icon_w = 0
        if icon:
            icon_w = 22
            arcade.draw_texture_rect(icon,
                arcade.LBWH(px + 14, detail_y - 4, 20, 20))
        self._t_detail.x = px + 16 + icon_w; self._t_detail.y = detail_y
        self._t_detail.draw()

    def _draw_craft_button(self, px: int, py: int, station_iron: int) -> None:
        """Draw the craft/cancel button and progress bar."""
        bx, by, bw, bh = self._craft_btn_rect()
        if self._crafting:
            btn_fill = (40, 40, 60, 220)
        elif self._selected <= 1 and station_iron >= CRAFT_IRON_COST:
            btn_fill = (30, 80, 30, 220)
        elif self._selected >= 2 and self._selected - 2 < len(self._recipes):
            cost = self._recipes[self._selected - 2]["cost"]
            btn_fill = (30, 80, 30, 220) if station_iron >= cost else (60, 30, 30, 220)
        else:
            btn_fill = (60, 30, 30, 220)
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), btn_fill)
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                                 arcade.color.STEEL_BLUE, border_width=1)
        self._t_btn.text = "CANCEL" if self._crafting else "CRAFT"
        self._t_btn.x = bx + bw // 2; self._t_btn.y = by + bh // 2
        self._t_btn.draw()

        # Progress bar + crafting label (below craft button)
        if self._crafting:
            if self._craft_target and self._craft_target in MODULE_TYPES:
                crafting_name = MODULE_TYPES[self._craft_target]["label"]
            elif self._craft_target == "shield_recharge":
                crafting_name = "Shield Recharge"
            else:
                crafting_name = "Repair Pack"
            bar_w = _PANEL_W - 32; bar_x = px + 16; bar_y = by - 22
            arcade.draw_rect_filled(arcade.LBWH(bar_x, bar_y, bar_w, 12), (30, 30, 50))
            arcade.draw_rect_filled(
                arcade.LBWH(bar_x, bar_y, int(bar_w * self._progress), 12), (50, 180, 50))
            arcade.draw_rect_outline(
                arcade.LBWH(bar_x, bar_y, bar_w, 12), arcade.color.STEEL_BLUE, border_width=1)
            pct = int(self._progress * 100)
            if pct != self._last_pct:
                self._last_pct = pct
                self._t_status.text = f"{pct}%"
            self._t_status.x = px + _PANEL_W // 2; self._t_status.y = bar_y + 6
            self._t_status.draw()
            self._t_detail.text = f"Crafting: {crafting_name}"
            self._t_detail.color = arcade.color.YELLOW
            self._t_detail.x = px + 16; self._t_detail.y = bar_y - 14
            self._t_detail.draw()


def _effect_desc(info: dict) -> str:
    """Short description of a module's effect."""
    eff = info["effect"]
    val = info["value"]
    descs = {
        "max_hp": f"+{val} HP",
        "max_speed": f"+{val} speed",
        "max_shields": f"+{val} shields",
        "shield_regen": f"+{val} shield regen",
        "shield_absorb": f"-{val} shield damage",
        "broadside": "side-firing lasers",
    }
    return descs.get(eff, str(val))
