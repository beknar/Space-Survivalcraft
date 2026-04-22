"""Trading station menu overlay."""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay
from constants import SCREEN_WIDTH, SCREEN_HEIGHT, CRAFT_IRON_COST, CRAFT_RESULT_COUNT, MODULE_TYPES

_PANEL_W = 340
_PANEL_H = 400       # main/buy modes; sell mode computes a dynamic height
_PANEL_H_MIN = 400
_PANEL_H_MAX = 500   # cap so the panel scrolls rather than filling the screen
_ITEM_H = 26
_SELL_HEADER_H = 100  # pixels above the first item row (title + credits + hint)
_SELL_FOOTER_H = 60  # pixels below the last item row (back button area)
_SCROLL_W = 8        # scrollbar track width

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
        # Pool of Text objects for list rows (sell + buy). Mutating a single
        # Text per row rebuilds the label atlas every frame which tanked FPS
        # with many rows; pooled Texts only refresh when the row text changes.
        self._row_texts: list[arcade.Text] = []
        self._hint_text = arcade.Text(
            "", 0, 0, (160, 160, 160), 10, anchor_x="center")
        self._empty_text = arcade.Text(
            "Nothing to sell", 0, 0, (200, 80, 80), 10, anchor_x="center")
        # Batched filled-rectangle draws — a single SpriteList.draw() call
        # replaces the 15+ immediate-mode arcade.draw_rect_filled calls the
        # panel used to issue per frame. Sprites are pooled and reused.
        self._rect_sprites: arcade.SpriteList = arcade.SpriteList()
        self._rect_slot: int = 0
        # Hold-to-sell state: while the left mouse button is held over a
        # sell row, tick off one unit every _HOLD_SELL_INTERVAL seconds.
        self._held_sell_item: str | None = None
        self._held_sell_timer: float = 0.0
        self._HOLD_SELL_INTERVAL: float = 0.15

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
            self._sell_scroll = 0
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
        # Scroll position is NOT reset here — this runs after every sale
        # and resetting would snap the view back to the top mid-sell.
        # Callers that open the sell view (``toggle`` / SELL button) reset
        # ``_sell_scroll`` themselves; ``_draw_sell`` clamps if the list
        # shrunk below the current scroll offset.

    def _panel_height(self) -> int:
        """Dynamic height — in sell mode grows to fit every row."""
        if self._mode == "sell":
            rows = max(1, len(self._sell_items))
            needed = _SELL_HEADER_H + rows * _ITEM_H + _SELL_FOOTER_H
            sh = self._window.height if self._window else SCREEN_HEIGHT
            return max(_PANEL_H_MIN, min(needed, _PANEL_H_MAX, sh - 40))
        return _PANEL_H

    def _rect_reset(self) -> None:
        """Begin a new frame's rectangle pool usage."""
        self._rect_slot = 0

    def _rect_add(self, x: float, y: float, w: float, h: float,
                  color: tuple[int, int, int, int]) -> None:
        """Enqueue one filled rectangle for batched drawing this frame.

        x/y is the bottom-left corner (LBWH), matching the immediate-mode
        call sites we replaced.
        """
        if self._rect_slot >= len(self._rect_sprites):
            s = arcade.SpriteSolidColor(int(w), int(h), 0, 0, color)
            self._rect_sprites.append(s)
        s = self._rect_sprites[self._rect_slot]
        s.width = w
        s.height = h
        s.center_x = x + w / 2
        s.center_y = y + h / 2
        s.color = color
        s.visible = True
        self._rect_slot += 1

    def _rect_flush(self) -> None:
        """Hide any unused sprites in the pool and draw the batch."""
        for i in range(self._rect_slot, len(self._rect_sprites)):
            self._rect_sprites[i].visible = False
        self._rect_sprites.draw()

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return (sw - _PANEL_W) // 2, (sh - self._panel_height()) // 2

    def draw(self) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()
        ph = self._panel_height()
        self._rect_reset()
        self._rect_add(px, py, _PANEL_W, ph, (15, 20, 45, 240))
        cx = px + _PANEL_W // 2

        if self._mode == "main":
            self._draw_main(px, py, ph, cx)
        elif self._mode == "sell":
            self._draw_sell(px, py, ph, cx)
        elif self._mode == "buy":
            self._draw_buy(px, py, ph, cx)

        # One SpriteList.draw() replaces all the filled-rect immediate calls.
        self._rect_flush()

        # Outlines + text happen after fills so they sit on top.
        arcade.draw_rect_outline(arcade.LBWH(px, py, _PANEL_W, ph),
                                 arcade.color.STEEL_BLUE, border_width=2)
        self._t_title.x = cx; self._t_title.y = py + ph - 20
        self._t_title.draw()
        self._t_credits.text = f"Credits: {self._credits}"
        self._t_credits.x = cx; self._t_credits.y = py + ph - 42
        self._t_credits.draw()

        if self._mode == "main":
            self._draw_main_text(px, py, ph, cx)
        elif self._mode == "sell":
            self._draw_sell_text(px, py, ph, cx)
        elif self._mode == "buy":
            self._draw_buy_text(px, py, ph, cx)

        self._t_close.x = cx; self._t_close.y = py + 10
        self._t_close.draw()

    _MAIN_BUTTONS: tuple = (
        ("SELL Items", arcade.color.ORANGE),
        ("BUY Items", arcade.color.LIME_GREEN),
    )

    def _draw_main(self, px: int, py: int, ph: int, cx: int) -> None:
        # Fills phase: enqueue button backgrounds.
        for i in range(len(self._MAIN_BUTTONS)):
            bx = px + (_PANEL_W - 200) // 2
            by = py + ph - 90 - i * 50
            self._rect_add(bx, by, 200, 36, (30, 50, 80, 220))

    def _draw_main_text(self, px: int, py: int, ph: int, cx: int) -> None:
        for i, (label, color) in enumerate(self._MAIN_BUTTONS):
            bx = px + (_PANEL_W - 200) // 2
            by = py + ph - 90 - i * 50
            arcade.draw_rect_outline(arcade.LBWH(bx, by, 200, 36),
                                     arcade.color.STEEL_BLUE, border_width=1)
            self._t_btn.text = label; self._t_btn.color = color
            self._t_btn.x = bx + 100; self._t_btn.y = by + 18
            self._t_btn.draw()

    def _draw_hint(self, cx: int, y: int, text: str) -> None:
        """Draw a centered grey hint line."""
        h = self._hint_text
        if h.text != text:
            h.text = text
        h.x = cx; h.y = y
        h.draw()

    def _get_row_text(self, idx: int) -> arcade.Text:
        """Return a pooled Text for row idx, allocating lazily."""
        while idx >= len(self._row_texts):
            self._row_texts.append(arcade.Text(
                "", 0, 0, arcade.color.WHITE, 10, anchor_x="left"))
        return self._row_texts[idx]

    def _enqueue_row_fill(self, px: int, iy: int,
                          fill: tuple[int, int, int, int]) -> None:
        self._rect_add(px + 10, iy, _PANEL_W - 20, _ITEM_H - 2, fill)

    def _draw_row_text(self, row_idx: int, px: int, iy: int, text: str,
                       text_color: tuple[int, int, int]) -> None:
        t = self._get_row_text(row_idx)
        if t.text != text:
            t.text = text
        t.x = px + 16; t.y = iy + _ITEM_H // 2
        if t.color != text_color:
            t.color = text_color
        t.draw()

    def _enqueue_back_button_fill(self, px: int, py: int) -> None:
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        self._rect_add(bx, by, 100, 28, (50, 40, 40, 220))

    def _draw_back_button_chrome(self, px: int, py: int) -> None:
        """Outline + label — fill is already enqueued via the batch."""
        bx = px + (_PANEL_W - 100) // 2; by = py + 30
        arcade.draw_rect_outline(arcade.LBWH(bx, by, 100, 28),
                                 arcade.color.STEEL_BLUE, border_width=1)
        self._t_btn.text = "Back"; self._t_btn.color = arcade.color.WHITE
        self._t_btn.x = bx + 50; self._t_btn.y = by + 14; self._t_btn.draw()

    def _draw_sell(self, px: int, py: int, ph: int, cx: int) -> None:
        """Fills phase — enqueue row + scrollbar + back-button backgrounds."""
        list_y = py + ph - _SELL_HEADER_H
        max_vis = max(1, (ph - _SELL_HEADER_H - _SELL_FOOTER_H) // _ITEM_H)
        total = len(self._sell_items)
        max_scroll = max(0, total - max_vis)
        if self._sell_scroll > max_scroll:
            self._sell_scroll = max_scroll
        if self._sell_items:
            for i in range(min(max_vis, total - self._sell_scroll)):
                iy = list_y - i * _ITEM_H
                self._enqueue_row_fill(px, iy, (30, 40, 60, 200))
            if total > max_vis:
                self._enqueue_scrollbar_fills(px, py, ph, total, max_vis)
        self._enqueue_back_button_fill(px, py)

    def _draw_sell_text(self, px: int, py: int, ph: int, cx: int) -> None:
        """Text phase — draws labels and outlines on top of the fills."""
        self._draw_hint(cx, py + ph - 65, "Click an item to sell 1 unit")
        list_y = py + ph - _SELL_HEADER_H
        max_vis = max(1, (ph - _SELL_HEADER_H - _SELL_FOOTER_H) // _ITEM_H)
        total = len(self._sell_items)
        if not self._sell_items:
            self._empty_text.x = cx; self._empty_text.y = list_y - 20
            self._empty_text.draw()
        else:
            for i in range(min(max_vis, total - self._sell_scroll)):
                idx = self._sell_scroll + i
                it, name, price, count = self._sell_items[idx]
                iy = list_y - i * _ITEM_H
                self._draw_row_text(
                    i, px, iy,
                    f"{name} x{count}  —  {price} cr/ea",
                    arcade.color.WHITE,
                )
        self._draw_back_button_chrome(px, py)

    def _enqueue_scrollbar_fills(self, px: int, py: int, ph: int,
                                 total: int, max_vis: int) -> None:
        track_x = px + _PANEL_W - 10 - _SCROLL_W
        track_y = py + _SELL_FOOTER_H
        track_h = ph - _SELL_HEADER_H - _SELL_FOOTER_H
        self._rect_add(track_x, track_y, _SCROLL_W, track_h,
                       (20, 30, 50, 220))
        thumb_h = max(20, int(track_h * max_vis / total))
        max_scroll = max(1, total - max_vis)
        thumb_y = track_y + track_h - thumb_h - int(
            (track_h - thumb_h) * self._sell_scroll / max_scroll)
        self._rect_add(track_x, thumb_y, _SCROLL_W, thumb_h,
                       (120, 160, 220, 240))

    def _draw_buy(self, px: int, py: int, ph: int, cx: int) -> None:
        list_y = py + ph - _SELL_HEADER_H
        for i, (it, name, cost, qty) in enumerate(BUY_CATALOG):
            iy = list_y - i * _ITEM_H
            affordable = self._credits >= cost
            fill = (30, 60, 30, 200) if affordable else (50, 30, 30, 200)
            self._enqueue_row_fill(px, iy, fill)
        self._enqueue_back_button_fill(px, py)

    def _draw_buy_text(self, px: int, py: int, ph: int, cx: int) -> None:
        self._draw_hint(cx, py + ph - 65, "Click an item to buy")
        list_y = py + ph - _SELL_HEADER_H
        for i, (it, name, cost, qty) in enumerate(BUY_CATALOG):
            iy = list_y - i * _ITEM_H
            affordable = self._credits >= cost
            color = arcade.color.WHITE if affordable else (150, 80, 80)
            self._draw_row_text(
                i, px, iy, f"{name} x{qty}  —  {cost} credits", color)
        self._draw_back_button_chrome(px, py)

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
                self._sell_scroll = 0
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
                # Start the hold-to-sell loop so dragging / holding the
                # left mouse button keeps selling this item.
                self._held_sell_item = it
                self._held_sell_timer = self._HOLD_SELL_INTERVAL
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

    def on_mouse_release(self, x: float, y: float) -> None:
        """End any hold-to-sell loop when the mouse button is released."""
        self._held_sell_item = None
        self._held_sell_timer = 0.0

    def on_update(self, dt: float,
                  inventory=None, station_inv=None) -> Optional[str]:
        """Tick the hold-to-sell timer. Returns ``sell:it:1`` when a
        held item should sell one more unit, or ``None`` otherwise.

        Clears the hold if the item runs out in both inventories so the
        loop doesn't linger after the stock is gone.
        """
        if self._held_sell_item is None or not self.open or self._mode != "sell":
            return None
        have = 0
        for inv in (inventory, station_inv):
            if inv is not None:
                have += inv.count_item(self._held_sell_item)
        if have <= 0:
            self._held_sell_item = None
            self._held_sell_timer = 0.0
            return None
        self._held_sell_timer -= dt
        if self._held_sell_timer > 0.0:
            return None
        self._held_sell_timer = self._HOLD_SELL_INTERVAL
        price = SELL_PRICES.get(self._held_sell_item, 1)
        self._credits += price
        return f"sell:{self._held_sell_item}:1"

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
