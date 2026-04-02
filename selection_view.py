"""Faction and ship type selection screen."""
from __future__ import annotations

import os

import arcade
from PIL import Image as PILImage

import constants
from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    FACTION_SHIPS_DIR, FACTIONS, SHIP_TYPES,
    SHIP_FRAME_SIZE, SHIP_SHEET_COLS,
    SFX_INTERFACE_DIR, SFX_VEHICLES_DIR,
)


class SelectionView(arcade.View):
    """Two-phase selection screen: choose faction, then ship type."""

    _PHASE_FACTION = 0
    _PHASE_SHIP = 1
    _PHASE_CHARACTER = 2

    def __init__(self) -> None:
        super().__init__()

        self._phase: int = self._PHASE_FACTION
        self._faction_names: list[str] = list(FACTIONS.keys())
        self._ship_names: list[str] = list(SHIP_TYPES.keys())
        self._selected_faction: int = 0     # index into _faction_names
        self._selected_ship: int = 0        # index into _ship_names
        self._chosen_faction: str = ""      # set after faction is confirmed
        self._chosen_ship: str = ""         # set after ship is confirmed

        # Character selection
        from video_player import scan_characters_dir, character_video_path
        self._character_names: list[str] = scan_characters_dir()
        if not self._character_names:
            self._character_names = ["(none)"]
        self._selected_char: int = 0

        # Load character thumbnails (first frame from each video)
        self._char_previews: list[arcade.Texture | None] = []
        for cname in self._character_names:
            thumb = self._extract_video_thumbnail(character_video_path(cname) if cname != "(none)" else None)
            self._char_previews.append(thumb)

        # Pre-load one preview frame per faction (first ship, first col)
        # We'll use the Cruiser row (row 7) col 0 as the faction preview
        # Upscale with nearest-neighbor so pixel art stays crisp at display size
        self._preview_scale: float = 1.5  # scale for sharp pixels (128 -> 192 px)
        self._faction_previews: list[arcade.Texture] = []
        for faction_name, filename in FACTIONS.items():
            path = os.path.join(FACTION_SHIPS_DIR, filename)
            pil_img = PILImage.open(path).convert("RGBA")
            # Use Cruiser row (7) col 0 as the faction representative
            row = SHIP_TYPES["Cruiser"]["row"]
            x0 = 0
            y0 = row * SHIP_FRAME_SIZE
            frame = pil_img.crop((x0, y0, x0 + SHIP_FRAME_SIZE, y0 + SHIP_FRAME_SIZE))
            preview_px = int(SHIP_FRAME_SIZE * self._preview_scale)
            frame = frame.resize((preview_px, preview_px), PILImage.NEAREST)
            self._faction_previews.append(arcade.Texture(frame))

        # Ship previews will be loaded once a faction is chosen
        self._ship_previews: list[arcade.Texture] = []

        # UI sounds — clean ping for navigation, different ping for confirm
        self._switch_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 1.wav")
        )
        self._confirm_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 2.wav")
        )

        # Pre-built text objects
        self._init_text_objects()

    def _init_text_objects(self) -> None:
        """Create pre-built arcade.Text objects for all selection phases."""
        self._t_title = arcade.Text(
            "CHOOSE YOUR FACTION",
            self.window.width // 2, self.window.height - 60,
            arcade.color.LIGHT_BLUE, 28, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "UP / DOWN to select    ENTER to confirm    ESC to go back",
            self.window.width // 2, 40,
            (160, 160, 160), 12,
            anchor_x="center", anchor_y="center",
        )
        self._t_label = arcade.Text(
            "", self.window.width // 2, 0,
            arcade.color.WHITE, 16, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_stats = arcade.Text(
            "", 0, 0,
            arcade.color.LIGHT_GRAY, 11,
            anchor_x="left", anchor_y="top",
            multiline=True, width=400,
        )

    def _load_ship_previews(self, faction: str) -> None:
        """Load the first-column sprite for each ship type from the chosen faction."""
        filename = FACTIONS[faction]
        path = os.path.join(FACTION_SHIPS_DIR, filename)
        pil_img = PILImage.open(path).convert("RGBA")
        self._ship_previews = []
        preview_px = int(SHIP_FRAME_SIZE * self._preview_scale)
        for ship_name in self._ship_names:
            row = SHIP_TYPES[ship_name]["row"]
            x0 = 0
            y0 = row * SHIP_FRAME_SIZE
            frame = pil_img.crop((x0, y0, x0 + SHIP_FRAME_SIZE, y0 + SHIP_FRAME_SIZE))
            frame = frame.resize((preview_px, preview_px), PILImage.NEAREST)
            self._ship_previews.append(arcade.Texture(frame))

    # ── Drawing ─────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        self.clear()

        # Dark space background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self.window.width, self.window.height),
            (8, 8, 24),
        )

        if self._phase == self._PHASE_FACTION:
            self._draw_faction_phase()
        elif self._phase == self._PHASE_SHIP:
            self._draw_ship_phase()
        elif self._phase == self._PHASE_CHARACTER:
            self._draw_character_phase()

        self._t_hint.draw()

    def _draw_faction_phase(self) -> None:
        self._t_title.text = "CHOOSE YOUR FACTION"
        self._t_title.draw()

        count = len(self._faction_names)
        spacing = 240
        total_w = (count - 1) * spacing
        start_x = self.window.width // 2 - total_w // 2

        for i, name in enumerate(self._faction_names):
            cx = start_x + i * spacing
            cy = self.window.height // 2 + 30
            selected = (i == self._selected_faction)

            # Selection highlight
            if selected:
                arcade.draw_rect_filled(
                    arcade.LBWH(cx - 70, cy - 80, 140, 160),
                    (40, 60, 100, 180),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx - 70, cy - 80, 140, 160),
                    arcade.color.CYAN, border_width=2,
                )

            # Ship preview (pre-upscaled with nearest-neighbor for crisp pixels)
            tex = self._faction_previews[i]
            w = tex.width
            h = tex.height
            arcade.draw_texture_rect(
                tex,
                arcade.LBWH(cx - w / 2, cy - h / 2 + 10, w, h),
            )

            # Faction name
            self._t_label.text = name
            self._t_label.x = cx
            self._t_label.y = cy - 70
            color = arcade.color.CYAN if selected else arcade.color.WHITE
            self._t_label.color = color
            self._t_label.draw()

    def _draw_ship_phase(self) -> None:
        self._t_title.text = f"{self._chosen_faction.upper()} — CHOOSE YOUR SHIP"
        self._t_title.draw()

        count = len(self._ship_names)
        spacing = 220
        total_w = (count - 1) * spacing
        start_x = self.window.width // 2 - total_w // 2

        for i, name in enumerate(self._ship_names):
            cx = start_x + i * spacing
            cy = self.window.height // 2 + 60
            selected = (i == self._selected_ship)

            if selected:
                arcade.draw_rect_filled(
                    arcade.LBWH(cx - 70, cy - 80, 140, 160),
                    (40, 60, 100, 180),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx - 70, cy - 80, 140, 160),
                    arcade.color.CYAN, border_width=2,
                )

            # Ship preview (pre-upscaled with nearest-neighbor for crisp pixels)
            if i < len(self._ship_previews):
                tex = self._ship_previews[i]
                w = tex.width
                h = tex.height
                arcade.draw_texture_rect(
                    tex,
                    arcade.LBWH(cx - w / 2, cy - h / 2 + 10, w, h),
                )

            # Ship name
            self._t_label.text = name
            self._t_label.x = cx
            self._t_label.y = cy - 70
            color = arcade.color.CYAN if selected else arcade.color.WHITE
            self._t_label.color = color
            self._t_label.draw()

        # Stats panel for the selected ship
        ship_type = self._ship_names[self._selected_ship]
        stats = SHIP_TYPES[ship_type]
        self._draw_ship_stats(
            stats, ship_type,
            self.window.width // 2 - 200,
            self.window.height // 2 - 80,
        )

    def _draw_ship_stats(self, stats: dict, ship_type: str,
                         x: int, y: int) -> None:
        """Draw the stats panel for a ship type at the given position."""
        lines = [
            f"HP: {stats['hp']}",
            f"Shields: {stats['shields']}",
            f"Shield Regen: {stats['shield_regen']} pt/s",
            f"Rotation: {stats['rot_speed']} deg/s",
            f"Thrust: {stats['thrust']} px/s\u00b2",
            f"Brake: {stats['brake']} px/s\u00b2",
            f"Max Speed: {stats['max_speed']} px/s",
            f"Damping: {stats['damping']}x/frame",
            f"Guns: {stats['guns']}",
        ]
        self._t_stats.text = "\n".join(lines)
        self._t_stats.x = x
        self._t_stats.y = y
        self._t_stats.draw()

    @staticmethod
    def _extract_video_thumbnail(path: str | None) -> arcade.Texture | None:
        """Extract the first frame from a video file as an arcade Texture."""
        if path is None or not os.path.isfile(path):
            return None
        try:
            import pyglet.media
            from pyglet.media.codecs.ffmpeg import FFmpegDecoder
            source = pyglet.media.load(path, decoder=FFmpegDecoder())
            if source.video_format is None:
                source.delete()
                return None
            frame = source.get_next_video_frame()
            if frame is None:
                source.delete()
                return None
            w, h = frame.width, frame.height
            raw = frame.get_data("RGBA", w * 4)
            pil_img = PILImage.frombytes("RGBA", (w, h), raw)
            pil_img = pil_img.resize((150, 150), PILImage.BILINEAR)
            source.delete()
            return arcade.Texture(pil_img)
        except Exception:
            return None

    def _draw_character_phase(self) -> None:
        self._t_title.text = "CHOOSE YOUR CHARACTER"
        self._t_title.draw()

        count = len(self._character_names)
        spacing = min(220, (self.window.width - 100) // max(count, 1))
        total_w = (count - 1) * spacing
        start_x = self.window.width // 2 - total_w // 2

        for i, name in enumerate(self._character_names):
            cx = start_x + i * spacing
            cy = self.window.height // 2 + 30
            selected = (i == self._selected_char)

            if selected:
                arcade.draw_rect_filled(
                    arcade.LBWH(cx - 85, cy - 90, 170, 190),
                    (40, 60, 100, 180),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx - 85, cy - 90, 170, 190),
                    arcade.color.CYAN, border_width=2,
                )

            # Character thumbnail
            if i < len(self._char_previews) and self._char_previews[i] is not None:
                tex = self._char_previews[i]
                tw, th = tex.width, tex.height
                arcade.draw_texture_rect(
                    tex,
                    arcade.LBWH(cx - tw / 2, cy - th / 2 + 15, tw, th),
                )

            # Character name
            self._t_label.text = name
            self._t_label.x = cx
            self._t_label.y = cy - 80
            color = arcade.color.CYAN if selected else arcade.color.WHITE
            self._t_label.color = color
            self._t_label.draw()

    def _item_positions(self, items: list, spacing: int) -> list[int]:
        """Return center-X positions for a list of items, evenly spaced."""
        count = len(items)
        total_w = (count - 1) * spacing
        start_x = self.window.width // 2 - total_w // 2
        return [start_x + i * spacing for i in range(count)]

    def _hit_item(self, x: float, y: float, items: list, spacing: int,
                  cy: float, half_w: float = 70, half_h: float = 80) -> int:
        """Return the index of the item at (x, y), or -1."""
        positions = self._item_positions(items, spacing)
        for i, cx in enumerate(positions):
            if cx - half_w <= x <= cx + half_w and cy - half_h <= y <= cy + half_h:
                return i
        return -1

    # ── Input ───────────────────────────────────────────────────────────────
    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        if self._phase == self._PHASE_FACTION:
            cy = self.window.height // 2 + 30
            idx = self._hit_item(x, y, self._faction_names, 240, cy)
            if idx >= 0:
                self._selected_faction = idx
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._chosen_faction = self._faction_names[idx]
                self._load_ship_previews(self._chosen_faction)
                self._selected_ship = 0
                self._phase = self._PHASE_SHIP

        elif self._phase == self._PHASE_SHIP:
            cy = self.window.height // 2 + 60
            idx = self._hit_item(x, y, self._ship_names, 220, cy)
            if idx >= 0:
                self._selected_ship = idx
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._chosen_ship = self._ship_names[idx]
                self._selected_char = 0
                self._phase = self._PHASE_CHARACTER

        elif self._phase == self._PHASE_CHARACTER:
            cy = self.window.height // 2 + 30
            spacing = min(220, (self.window.width - 100) // max(len(self._character_names), 1))
            idx = self._hit_item(x, y, self._character_names, spacing, cy, 85, 90)
            if idx >= 0:
                self._selected_char = idx
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._confirm_selection()

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._phase == self._PHASE_FACTION:
            cy = self.window.height // 2 + 30
            idx = self._hit_item(x, y, self._faction_names, 240, cy)
            if idx >= 0:
                self._selected_faction = idx

        elif self._phase == self._PHASE_SHIP:
            cy = self.window.height // 2 + 60
            idx = self._hit_item(x, y, self._ship_names, 220, cy)
            if idx >= 0:
                self._selected_ship = idx

        elif self._phase == self._PHASE_CHARACTER:
            cy = self.window.height // 2 + 30
            spacing = min(220, (self.window.width - 100) // max(len(self._character_names), 1))
            idx = self._hit_item(x, y, self._character_names, spacing, cy, 85, 90)
            if idx >= 0:
                self._selected_char = idx

    def on_key_press(self, key: int, modifiers: int) -> None:
        if self._phase == self._PHASE_FACTION:
            if key in (arcade.key.LEFT, arcade.key.A):
                self._selected_faction = (self._selected_faction - 1) % len(self._faction_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RIGHT, arcade.key.D):
                self._selected_faction = (self._selected_faction + 1) % len(self._faction_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._chosen_faction = self._faction_names[self._selected_faction]
                self._load_ship_previews(self._chosen_faction)
                self._selected_ship = 0
                self._phase = self._PHASE_SHIP
            elif key == arcade.key.ESCAPE:
                from splash_view import SplashView
                self.window.show_view(SplashView())

        elif self._phase == self._PHASE_SHIP:
            if key in (arcade.key.LEFT, arcade.key.A):
                self._selected_ship = (self._selected_ship - 1) % len(self._ship_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RIGHT, arcade.key.D):
                self._selected_ship = (self._selected_ship + 1) % len(self._ship_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._chosen_ship = self._ship_names[self._selected_ship]
                self._selected_char = 0
                self._phase = self._PHASE_CHARACTER
            elif key == arcade.key.ESCAPE:
                arcade.play_sound(self._switch_snd, volume=0.4)
                self._phase = self._PHASE_FACTION

        elif self._phase == self._PHASE_CHARACTER:
            if key in (arcade.key.LEFT, arcade.key.A):
                self._selected_char = (self._selected_char - 1) % len(self._character_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RIGHT, arcade.key.D):
                self._selected_char = (self._selected_char + 1) % len(self._character_names)
                arcade.play_sound(self._switch_snd, volume=0.5)
            elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
                arcade.play_sound(self._confirm_snd, volume=0.6)
                self._confirm_selection()
            elif key == arcade.key.ESCAPE:
                arcade.play_sound(self._switch_snd, volume=0.4)
                self._phase = self._PHASE_SHIP

    def _confirm_selection(self) -> None:
        """Transition to GameView with the chosen faction, ship type, and character."""
        from game_view import GameView
        from settings import audio

        faction = self._chosen_faction
        ship_type = self._chosen_ship
        # Set character in settings so GameView picks it up
        char_name = self._character_names[self._selected_char]
        if char_name != "(none)":
            audio.character_name = char_name
        else:
            audio.character_name = ""
        view = GameView(faction=faction, ship_type=ship_type)
        self.window.show_view(view)
