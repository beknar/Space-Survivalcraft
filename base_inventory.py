"""Shared inventory data logic for both ship and station inventories."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import MAX_STACK, MAX_STACK_DEFAULT, SCREEN_WIDTH, SCREEN_HEIGHT


class BaseInventoryData:
    """Mixin providing shared item storage, counting, drag state, and drawing helpers.

    Subclasses must set:
        _items: dict[tuple[int, int], tuple[str, int]]
        _rows: int
        _cols: int
    """

    _items: dict[tuple[int, int], tuple[str, int]]
    _rows: int
    _cols: int

    def _init_drag_state(self) -> None:
        """Initialize drag-and-drop state. Call from subclass __init__."""
        self._drag_type: Optional[str] = None
        self._drag_amount: int = 0
        self._drag_src: Optional[tuple[int, int]] = None
        self._drag_x: float = 0.0
        self._drag_y: float = 0.0
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        # Dirty-flag render cache: marked dirty on item change / drag state change
        self._render_dirty: bool = True
        self._cache_icon_list: Optional[arcade.SpriteList] = None
        self._cache_fill_list: Optional[arcade.SpriteList] = None
        self._cache_badge_list: Optional[arcade.SpriteList] = None
        # Blueprint-marker overlay: small red dot at top-right of any
        # cell holding a ``bp_*`` item so the player can tell at a
        # glance which stacks are blueprints (install into a crafter)
        # vs. consumables or pre-built modules.
        self._cache_bp_marker_list: Optional[arcade.SpriteList] = None
        self._cache_origin: tuple[int, int] = (-1, -1)
        # PIL-rendered count badge textures keyed by count string
        self._badge_tex_cache: dict[str, arcade.Texture] = {}
        # Cached fill texture (shared by all fill sprites across rebuilds
        # to avoid leaking atlas entries — SpriteSolidColor creates a new
        # atlas slot per instance)
        self._fill_tex: arcade.Texture | None = None
        # Shared red-dot texture for the blueprint marker.  One atlas
        # entry used by every ``bp_*`` cell across ship + station
        # inventories.
        self._bp_marker_tex: arcade.Texture | None = None

    def _mark_dirty(self) -> None:
        self._render_dirty = True

    def _init_icons(
        self,
        iron_icon: Optional[arcade.Texture],
        repair_pack_icon: Optional[arcade.Texture],
        shield_recharge_icon: Optional[arcade.Texture],
    ) -> None:
        """Initialize item icon references. Call from subclass __init__."""
        self._iron_icon = iron_icon
        self._repair_pack_icon = repair_pack_icon
        self._shield_recharge_icon = shield_recharge_icon
        self.item_icons: dict[str, arcade.Texture] = {}
        self._count_cache: dict[str, arcade.Text] = {}

    def _init_window(self) -> None:
        """Initialize window reference. Call from subclass __init__."""
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

    @property
    def total_iron(self) -> int:
        return self.count_item("iron")

    @property
    def iron(self) -> int:
        return self.total_iron

    def count_item(self, item_type: str) -> int:
        total = 0
        for (it, ct) in self._items.values():
            if it == item_type:
                total += ct
        return total

    def migrate_legacy_keys(self) -> None:
        """Rewrite stale item-type keys left over from earlier versions."""
        legacy_map = {"mod_homing_missile": "missile"}
        legacy_cells = [
            (cell, legacy_map[it], ct)
            for cell, (it, ct) in self._items.items()
            if it in legacy_map
        ]
        for cell, _, _ in legacy_cells:
            del self._items[cell]
        for _, new_it, ct in legacy_cells:
            self.add_item(new_it, ct)
        if legacy_cells:
            self._mark_dirty()

    def add_item(self, item_type: str, count: int = 1) -> None:
        # Migrate stale keys from earlier versions
        if item_type == "mod_homing_missile":
            item_type = "missile"
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                self._items[cell] = (it, ct + count)
                self._mark_dirty()
                return
        for r in range(self._rows):
            for c in range(self._cols):
                if (r, c) not in self._items:
                    self._items[(r, c)] = (item_type, count)
                    self._mark_dirty()
                    return

    def remove_item(self, item_type: str, count: int = 1) -> int:
        removed = 0
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                take = min(ct, count - removed)
                remaining = ct - take
                removed += take
                if remaining <= 0:
                    del self._items[cell]
                else:
                    self._items[cell] = (it, remaining)
                if removed >= count:
                    break
        if removed > 0:
            self._mark_dirty()
        return removed

    def consolidate(self) -> None:
        totals: dict[str, int] = {}
        for (it, ct) in self._items.values():
            totals[it] = totals.get(it, 0) + ct
        self._items.clear()
        cell = 0
        for it, total in totals.items():
            max_s = MAX_STACK.get(it, MAX_STACK_DEFAULT)
            while total > 0 and cell < self._rows * self._cols:
                amt = min(total, max_s)
                r, c = divmod(cell, self._cols)
                self._items[(r, c)] = (it, amt)
                total -= amt
                cell += 1
        self._mark_dirty()

    def toggle(self) -> None:
        self.open = not self.open

    # ── Shared grid helpers ────────────────────────────────────────────────

    def _resolve_icon(self, item_type: str) -> Optional[arcade.Texture]:
        """Look up the icon texture for an item type."""
        if item_type == "iron" and self._iron_icon is not None:
            return self._iron_icon
        if item_type == "repair_pack" and self._repair_pack_icon is not None:
            return self._repair_pack_icon
        if item_type == "shield_recharge" and self._shield_recharge_icon is not None:
            return self._shield_recharge_icon
        return self.item_icons.get(item_type)

    def _draw_count_badge(self, count: int, x: float, y: float, cell_size: int) -> None:
        """Draw count badge at bottom-right of cell."""
        ct_str = str(count)
        ct_text = self._count_cache.get(ct_str)
        if ct_text is None:
            ct_text = arcade.Text(ct_str, 0, 0, arcade.color.ORANGE, 8,
                                  bold=True, anchor_x="right")
            self._count_cache[ct_str] = ct_text
        ct_text.x = x + cell_size - 4
        ct_text.y = y + 3
        ct_text.draw()

    def _start_drag(self, cell: tuple[int, int], x: float, y: float) -> bool:
        """Start dragging item from cell. Returns True if drag started."""
        item = self._items.get(cell)
        if item is not None:
            self._drag_type = item[0]
            self._drag_amount = item[1]
            self._drag_src = cell
            del self._items[cell]
            self._drag_x = x
            self._drag_y = y
            self._mark_dirty()
            return True
        return False

    def _finish_drag(self, target: Optional[tuple[int, int]]) -> None:
        """Drop dragged item onto target cell (handles stacking/swapping)."""
        if target is None:
            if self._drag_src is not None:
                self._items[self._drag_src] = (self._drag_type, self._drag_amount)
        else:
            existing = self._items.get(target)
            if existing is not None:
                if existing[0] == self._drag_type:
                    self._items[target] = (self._drag_type, existing[1] + self._drag_amount)
                else:
                    if self._drag_src is not None:
                        self._items[self._drag_src] = existing
                    self._items[target] = (self._drag_type, self._drag_amount)
            else:
                self._items[target] = (self._drag_type, self._drag_amount)
        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None
        self._mark_dirty()

    def _clear_drag(self) -> tuple[str, int]:
        """Clear drag state, returning (type, amount) of what was being dragged."""
        dt, da = self._drag_type, self._drag_amount
        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None
        self._mark_dirty()
        return dt, da

    def _get_badge_texture(self, count: int) -> arcade.Texture:
        """Return a small PIL-rendered texture for a count badge number.

        Cached per count string so each unique number (e.g. "5", "100") is
        only rendered once across the lifetime of the inventory. This is
        called during cache rebuild — NOT per frame.
        """
        key = str(count)
        tex = self._badge_tex_cache.get(key)
        if tex is not None:
            return tex
        from PIL import Image as PILImage, ImageDraw, ImageFont
        # Render orange bold text on a transparent background
        w, h = 32, 14
        img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 11)
        except (OSError, IOError):
            font = ImageFont.load_default()
        draw.text((w - 2, 1), key, fill=(255, 165, 0, 255),
                  font=font, anchor="ra")
        tex = arcade.Texture(img)
        self._badge_tex_cache[key] = tex
        return tex

    def _build_render_cache(self, gx: int, gy: int, cs: int) -> None:
        """Build batched SpriteList caches for cell fills, icons, AND
        count badges.

        Called from draw() only when _render_dirty is True or grid origin
        changed. Replaces per-cell draw_rect_filled + draw_texture_rect +
        arcade.Text.draw() calls with three GPU draw calls (one per
        SpriteList).
        """
        from arcade import Sprite, SpriteList, SpriteSolidColor

        # Reuse existing SpriteList objects AND individual Sprite objects
        # across rebuilds. Creating 375+ new Sprite instances per dirty
        # cycle piles up Python/GL overhead that isn't reclaimed between
        # rebuilds; mutating pooled sprites in place avoids that churn.
        # The pools (_fill_pool/_icon_pool/_badge_pool) grow once to the
        # high-water mark, then sprites are rebound to new textures and
        # positions on subsequent rebuilds.
        if self._cache_fill_list is None:
            self._cache_fill_list = SpriteList()
        else:
            self._cache_fill_list.clear()
        if self._cache_icon_list is None:
            self._cache_icon_list = SpriteList()
        else:
            self._cache_icon_list.clear()
        if self._cache_badge_list is None:
            self._cache_badge_list = SpriteList()
        else:
            self._cache_badge_list.clear()
        if self._cache_bp_marker_list is None:
            self._cache_bp_marker_list = SpriteList()
        else:
            self._cache_bp_marker_list.clear()
        if not hasattr(self, "_fill_pool"):
            self._fill_pool: list = []
            self._icon_pool: list = []
            self._badge_pool: list = []
            self._bp_marker_pool: list = []
        fills = self._cache_fill_list
        icons = self._cache_icon_list
        badges = self._cache_badge_list
        bp_markers = self._cache_bp_marker_list
        fill_pool = self._fill_pool
        icon_pool = self._icon_pool
        badge_pool = self._badge_pool
        bp_marker_pool = self._bp_marker_pool
        # Lazily build the red-dot texture once — same pattern the fill
        # texture uses.  Drawn with PIL (anti-aliased circle) into a
        # tiny RGBA image; atlas holds a single entry shared by every
        # blueprint cell.
        if self._bp_marker_tex is None:
            from PIL import Image, ImageDraw
            dot_size = 12
            img = Image.new("RGBA", (dot_size, dot_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((1, 1, dot_size - 2, dot_size - 2),
                         fill=(230, 40, 40, 255),
                         outline=(255, 255, 255, 220))
            self._bp_marker_tex = arcade.Texture(img)
        if self._fill_tex is None:
            _tmp = SpriteSolidColor(cs - 2, cs - 2, 0, 0, (255, 255, 255))
            self._fill_tex = _tmp.texture
        fill_idx = 0
        icon_idx = 0
        badge_idx = 0
        bp_marker_idx = 0
        for cell, (it, ct) in self._items.items():
            r, c = cell
            row_from_bottom = self._rows - 1 - r
            cx = gx + c * cs
            cy = gy + row_from_bottom * cs
            cell_cx = cx + cs / 2
            cell_cy = cy + cs / 2
            # Cell fill — SpriteSolidColor stores color as a sprite TINT on
            # a white texture, so we must set the color on each fill sprite.
            if fill_idx < len(fill_pool):
                fill = fill_pool[fill_idx]
                fill.texture = self._fill_tex
                fill.center_x = cell_cx
                fill.center_y = cell_cy
            else:
                fill = Sprite(self._fill_tex, center_x=cell_cx, center_y=cell_cy)
                fill_pool.append(fill)
            fill.width = cs - 2
            fill.height = cs - 2
            fill.color = (50, 80, 50, 200)
            fills.append(fill)
            fill_idx += 1
            # Icon (if any)
            icon_tex = self._resolve_icon(it)
            if icon_tex is not None:
                isz = cs - 12
                if icon_idx < len(icon_pool):
                    spr = icon_pool[icon_idx]
                    spr.texture = icon_tex
                    spr.center_x = cell_cx
                    spr.center_y = cell_cy
                else:
                    spr = Sprite(icon_tex, center_x=cell_cx, center_y=cell_cy)
                    icon_pool.append(spr)
                spr.width = isz
                spr.height = isz
                icons.append(spr)
                icon_idx += 1
            # Count badge (PIL-rendered texture, batched into SpriteList)
            badge_tex = self._get_badge_texture(ct)
            bx = cx + cs - badge_tex.width / 2 - 1
            by = cy + badge_tex.height / 2 + 1
            if badge_idx < len(badge_pool):
                badge = badge_pool[badge_idx]
                badge.texture = badge_tex
                badge.center_x = bx
                badge.center_y = by
            else:
                badge = Sprite(badge_tex, center_x=bx, center_y=by)
                badge_pool.append(badge)
            badges.append(badge)
            badge_idx += 1
            # Blueprint marker — small red dot in the top-right corner
            # for any ``bp_*`` cell so the player can visually pick
            # blueprints out of a mixed stack of modules + consumables.
            if it.startswith("bp_"):
                marker_tex = self._bp_marker_tex
                mx = cx + cs - marker_tex.width / 2 - 2
                my = cy + cs - marker_tex.height / 2 - 2
                if bp_marker_idx < len(bp_marker_pool):
                    marker = bp_marker_pool[bp_marker_idx]
                    marker.texture = marker_tex
                    marker.center_x = mx
                    marker.center_y = my
                else:
                    marker = Sprite(marker_tex, center_x=mx, center_y=my)
                    bp_marker_pool.append(marker)
                bp_markers.append(marker)
                bp_marker_idx += 1
        self._cache_origin = (gx, gy)
        self._render_dirty = False

    def _ensure_render_cache(self, gx: int, gy: int, cs: int) -> None:
        """Rebuild the render cache if dirty or if the grid origin moved
        (e.g. after a window resize)."""
        if self._render_dirty or self._cache_origin != (gx, gy):
            self._build_render_cache(gx, gy, cs)

    def _screen_size(self) -> tuple[int, int]:
        """Return current screen dimensions."""
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return sw, sh
