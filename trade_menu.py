"""Trading station menu overlay."""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay
from constants import SCREEN_WIDTH, SCREEN_HEIGHT, CRAFT_IRON_COST, CRAFT_RESULT_COUNT, MODULE_TYPES

_PANEL_W = 340
_PANEL_H = 400       # main/buy modes; sell mode computes a dynamic height
_PANEL_H_MIN = 400
_ITEM_H = 26
_SELL_HEADER_H = 85  # pixels above the first item row (title + credits + hint)
_SELL_FOOTER_H = 60  # pixels below the last item row (back button area)

# Sell prices (credits per unit)
SELL_PRICES: dict[str, int] = {
    "iron": 20,
    "repair_pack": 100,
    "shield_recharge": 100,
    "copper": 20,
    "missile": 200,
}
# Add blueprint sell prices (half the module craft cost)
for _k, _info in MODULE_TYPES.items():
    SELL_PRICES[f"bp_{_k}"] = _info["craft_cost"] // 2
    SELL_PRICES[f"mod_{_k}"] = _info["craft_cost"]

# Buy catalog: item_type → (label, credit cost, stack produced)
BUY_CATALOG: list[tuple[str, str, int, int]] = [
    ("iron", "Iron x50", 1500, 50),
    ("repair_pack", "Repair Pack", CRAFT_IRON_COST * 2, CRAFT_RESULT_COUNT),
    ("shield_recharge", "Shield Recharge", CRAFT_IRON_COST * 2, CRAFT_RESULT_COUNT),
    ("missile", "Homing Missile x10", 500, 10),
]

# Display names
_ITEM_NAMES: dict[str, str] = {
    "iron": "Iron",
    "repair_pack": "Repair Pack",
    "shield_recharge": "Shield Recharge",
    "copper": "Copper",
    "missile": "Homing Missile",
}
for _k, _info in MODULE_TYPES.items():
    _ITEM_NAMES[f"bp_{_k}"] = f"BP {_info['label']}"
    _ITEM_NAMES[f"mod_{_k}"] = _info["label"]


class TradeMenu(MenuOverlay):
    """Overlay for the trading station — sell items for credits, buy consumables."""

    _title_text = "TRADING STATION"
    _close_text = "ESC to close"

    def __init__(self) -> None:
        super().__init__()
        self._mode: str = "main"  # "main", "sell", "buy"
        self._credits: int = 0
        self._t_credits = arcade.Text("", 0, 0, arcade.color.YELLOW, 11, bold=True,
                                      anchor_x="center")

        # Sell list (populated on open)
        self._sell_items: list[tuple[str, str, int, int]] = []  # (type, name, price, count)
        self._sell_scroll: int = 0

    @property
    def credits(self) -> int:
        return self._credits

    @credits.setter
    def credits(self, val: int) -> None:
        self._credits = max(0, val)

    def toggle(self, inventory=None, station_inv=None) -> None:
        self.open = not self.open
        if self.open:
            self._mode = "main"
            self._refresh_sell_list(inventory, station_inv)

    def _refresh_sell_list(self, inventory=None, station_inv=None) -> None:
        """Build list of sellable items from both inventories."""
        self._sell_items = []
        seen: dict[str, int] = {}
        for inv in [inventory, station_inv]:
            if inv is None:
                continue
            for (it, ct) in inv._items.values():
                if it in SELL_PRICES:
                    seen[it] = seen.get(it, 0) + ct
        # Sort priority: raw resources → consumables → modules → blueprints.
        # Alphabetical within each group. Without this, bp_* entries flooded
        # the top of the 10-row window and pushed copper/iron out of view.
        def _sort_key(it: str) -> tuple[int, str]:
            if it in ("iron", "copper"):
                return (0, it)
            if it in ("repair_pack", "shield_recharge", "missile"):
                return (1, it)
            if it.startswith("mod_"):
                return (2, it)
            return (3, it)  # bp_* and anything else
        for it, ct in sorted(seen.items(), key=lambda kv: _sort_key(kv[0])):
            name = _ITEM_NAMES.get(it, it)
            price = SELL_PRICES.get(it, 1)
            self._sell_items.append((it, name, price, ct))
        self._sell_scroll = 0

    def _panel_height(self) -> int:
        """Dynamic height — in sell mode grows to fit every row."""
        if self._mode == "sell":
            rows = max(1, len(self._sell_items))
            needed = _SELL_HEADER_H + rows * _ITEM_H + _SELL_FOOTER_H
            sh = self._window.height if self._window else SCREEN_HEIGHT
            return max(_PANEL_H_MIN, min(needed, sh - 40))
        return _PANEL_H

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return (sw - _PANEL_W) // 2, (sh - self._panel_height()) // 2

    def draw(self) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()
        ph = self._panel_height()
        arcade.draw_rect_filled(arcade.LBWH(px, py, _PANEL_W, ph), (15, 20, 45, 240))
        arcade.draw_rect_outline(arcade.LBWH(px, py, _PANEL_W, ph),
                                 arcade.color.STEEL_BLUE, border_width=2)
        cx = px + _PANEL_W // 2
        self._t_title.x = cx; self._t_title.y = py + ph - 20
        self._t_title.draw()
        self._t_credits.text = f"Credits: {self._credits}"
        self._t_credits.x = cx; self._t_credits.y = py + ph - 42
        self._t_credits.draw()

        if self._mode == "main":
            self._draw_main(px, py, ph, cx)
        elif self._mode == "sell":
            self._draw_sell(px, py, ph, cx)
        elif self._mode == "buy":
            self._draw_buy(px, py, ph, cx)

        self._t_close.x = cx; self._t_close.y = py + 10
        self._t_close.draw()

    def _draw_main(self, px: int, py: int, ph: int, cx: int) -> None:
        for i, (label, color) in enumerate([
            ("SELL Items", arcade.color.ORANGE),
            ("BUY Items", arcade.color.LIME_GREEN),
        ]):
            bx = px + (_PANEL_W - 200) // 2
            by = py + ph - 90 - i * 50
            arcade.draw_rect_filled(arcade.LBWH(bx, by, 200, 36),
                                    (30, 50, 80, 220))
            arcade.draw_rect_outline(arcade.LBWH(bx, by, 200, 36),
                                     arcade.color.STEEL_BLUE, border_width=1)
            self._t_btn.text = label; self._t_btn.color = color
            self._t_btn.x = bx + 100; self._t_btn.y = by + 18
            self._t_btn.draw()

    def _draw_sell(self, px: int, py: int, ph: int, cx: int) -> None:
        self._t_line.text = "Click an item to sell 1 unit"
        self._t_line.x = cx; self._t_line.y = py + ph - 65
        self._t_line.color = (160, 160, 160)
        self._t_line.anchor_x = "center"; self._t_line.draw()
        self._t_line.anchor_x = "left"
        list_y = py + ph - _SELL_HEADER_H
        max_vis = max(1, (ph - _SELL_HEADER_H - _SELL_FOOTER_H) // _ITEM_H)
        if not self._sell_items:
            self._t_line.text = "Nothing to sell"
            self._t_line.x = cx; self._t_line.y = list_y - 20
            self._t_line.color = (200, 80, 80)
            self._t_line.anchor_x = "center"; self._t_line.draw()
            self._t_line.anchor_x = "left"
        else:
            for i in range(min(max_vis, len(self._sell_items) - self._sell_scroll)):
                idx = self._sell_scroll + i
                it, name, price, count = self._sell_items[idx]
                iy = list_y - i * _ITEM_H
                arcade.draw_rect_filled(arcade.LBWH(px + 10, iy, _PANEL_W - 20, _ITEM_H - 2),
                                        (30, 40, 60, 200))
                self._t_line.text = f"{name} x{count}  —  {price} cr/ea"
                self._t_line.x = px + 16; self._t_line.y = iy + _ITEM_H // 2
                self._t_line.color = arcade.color.WHITE
                self._t_line.draw()
        # Back button
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        arcade.draw_rect_filled(arcade.LBWH(bx, by, 100, 28), (50, 40, 40, 220))
        arcade.draw_rect_outline(arcade.LBWH(bx, by, 100, 28),
                                 arcade.color.STEEL_BLUE, border_width=1)
        self._t_btn.text = "Back"; self._t_btn.color = arcade.color.WHITE
        self._t_btn.x = bx + 50; self._t_btn.y = by + 14; self._t_btn.draw()

    def _draw_buy(self, px: int, py: int, ph: int, cx: int) -> None:
        self._t_line.text = "Click an item to buy"
        self._t_line.x = cx; self._t_line.y = py + ph - 65
        self._t_line.color = (160, 160, 160)
        self._t_line.anchor_x = "center"; self._t_line.draw()
        self._t_line.anchor_x = "left"
        list_y = py + ph - _SELL_HEADER_H
        for i, (it, name, cost, qty) in enumerate(BUY_CATALOG):
            iy = list_y - i * _ITEM_H
            affordable = self._credits >= cost
            fill = (30, 60, 30, 200) if affordable else (50, 30, 30, 200)
            arcade.draw_rect_filled(arcade.LBWH(px + 10, iy, _PANEL_W - 20, _ITEM_H - 2), fill)
            self._t_line.text = f"{name} x{qty}  —  {cost} credits"
            self._t_line.x = px + 16; self._t_line.y = iy + _ITEM_H // 2
            self._t_line.color = arcade.color.WHITE if affordable else (150, 80, 80)
            self._t_line.draw()
        # Back button
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        arcade.draw_rect_filled(arcade.LBWH(bx, by, 100, 28), (50, 40, 40, 220))
        arcade.draw_rect_outline(arcade.LBWH(bx, by, 100, 28),
                                 arcade.color.STEEL_BLUE, border_width=1)
        self._t_btn.text = "Back"; self._t_btn.color = arcade.color.WHITE
        self._t_btn.x = bx + 50; self._t_btn.y = by + 14; self._t_btn.draw()

    def on_mouse_press(self, x: float, y: float, inventory=None,
                       station_inv=None) -> Optional[str]:
        """Handle click. Returns action string or None."""
        if not self.open:
            return None
        px, py = self._panel_origin()
        ph = self._panel_height()
        if not (px <= x <= px + _PANEL_W and py <= y <= py + ph):
            self.open = False
            return None

        if self._mode == "main":
            bx = px + (_PANEL_W - 200) // 2
            # Sell button
            by = py + ph - 90
            if bx <= x <= bx + 200 and by <= y <= by + 36:
                self._mode = "sell"
                self._refresh_sell_list(inventory, station_inv)
                return None
            # Buy button
            by2 = py + ph - 140
            if bx <= x <= bx + 200 and by2 <= y <= by2 + 36:
                self._mode = "buy"
                return None

        elif self._mode == "sell":
            return self._handle_sell_click(x, y, px, py, ph)

        elif self._mode == "buy":
            return self._handle_buy_click(x, y, px, py, ph)

        return None

    def _handle_sell_click(self, x: float, y: float,
                           px: int, py: int, ph: int) -> Optional[str]:
        """Process a click in sell mode (back button or item list)."""
        # Back button
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        if bx <= x <= bx + 100 and by <= y <= by + 28:
            self._mode = "main"
            return None
        # Item list
        list_y = py + ph - _SELL_HEADER_H
        max_vis = max(1, (ph - _SELL_HEADER_H - _SELL_FOOTER_H) // _ITEM_H)
        for i in range(min(max_vis, len(self._sell_items) - self._sell_scroll)):
            idx = self._sell_scroll + i
            iy = list_y - i * _ITEM_H
            if px + 10 <= x <= px + _PANEL_W - 10 and iy <= y <= iy + _ITEM_H:
                it, name, price, count = self._sell_items[idx]
                # Sell 1 unit
                self._credits += price
                return f"sell:{it}:1"
        return None

    def _handle_buy_click(self, x: float, y: float,
                          px: int, py: int, ph: int) -> Optional[str]:
        """Process a click in buy mode (back button or catalog item)."""
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        if bx <= x <= bx + 100 and by <= y <= by + 28:
            self._mode = "main"
            return None
        list_y = py + ph - _SELL_HEADER_H
        for i, (it, name, cost, qty) in enumerate(BUY_CATALOG):
            iy = list_y - i * _ITEM_H
            if (px + 10 <= x <= px + _PANEL_W - 10
                    and iy <= y <= iy + _ITEM_H
                    and self._credits >= cost):
                self._credits -= cost
                return f"buy:{it}:{qty}"
        return None

    def on_key_press(self, key: int) -> None:
        if key == arcade.key.ESCAPE:
            if self._mode != "main":
                self._mode = "main"
            else:
                self.open = False

    def on_mouse_scroll(self, scroll_y: float) -> None:
        if self._mode == "sell" and self._sell_items:
            ph = self._panel_height()
            max_vis = max(1, (ph - _SELL_HEADER_H - _SELL_FOOTER_H) // _ITEM_H)
            mx = max(0, len(self._sell_items) - max_vis)
            self._sell_scroll = int(max(0, min(mx, self._sell_scroll - scroll_y)))
