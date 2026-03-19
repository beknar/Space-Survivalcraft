"""Splash / title screen for Call of Orion."""
from __future__ import annotations

import os
import random
from typing import Optional

import arcade

import constants
from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    SFX_INTERFACE_DIR,
    SAVE_SLOT_COUNT,
)
from settings import audio
from world_setup import collect_music_tracks


# ── Button layout constants ───────────────────────────────────────────────
_BTN_W = 260
_BTN_H = 48
_BTN_GAP = 20
_BTN_LABELS = ["Play Now", "Load Game", "Options", "Exit Game"]

_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")


class SplashView(arcade.View):
    """Title screen shown when the game first launches.

    Displays the game title, three navigation buttons, background music,
    and a track-name indicator at the bottom of the screen.
    """

    def __init__(self) -> None:
        super().__init__()

        # ── Music ──────────────────────────────────────────────────────
        self._music_tracks = collect_music_tracks()
        self._music_idx: int = 0
        self._music_player: Optional[arcade.sound.media.Player] = None
        self._current_track_name: str = ""
        if self._music_tracks:
            self._play_next_track()

        # ── UI sounds ──────────────────────────────────────────────────
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 2.wav")
        )

        # ── Hover state ────────────────────────────────────────────────
        self._hover_idx: int = -1

        # ── Pre-compute button rectangles (centred on screen) ──────────
        # Read live module-level values (not the stale local import)
        sw = self.window.width
        sh = self.window.height
        total_h = len(_BTN_LABELS) * _BTN_H + (len(_BTN_LABELS) - 1) * _BTN_GAP
        top_y = sh // 2 - 20  # below the title
        self._btn_rects: list[tuple[int, int, int, int]] = []
        for i in range(len(_BTN_LABELS)):
            bx = (sw - _BTN_W) // 2
            by = top_y - i * (_BTN_H + _BTN_GAP)
            self._btn_rects.append((bx, by, _BTN_W, _BTN_H))

        # ── Pre-built text objects ─────────────────────────────────────
        self._t_title = arcade.Text(
            "CALL OF ORION",
            sw // 2, sh - 160,
            arcade.color.LIGHT_BLUE, 52, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_subtitle = arcade.Text(
            "A Space Survival Saga",
            sw // 2, sh - 210,
            (160, 180, 220), 16,
            anchor_x="center", anchor_y="center",
        )
        self._t_btn_labels: list[arcade.Text] = []
        for i, label in enumerate(_BTN_LABELS):
            bx, by, bw, bh = self._btn_rects[i]
            self._t_btn_labels.append(arcade.Text(
                label,
                bx + bw // 2, by + bh // 2,
                arcade.color.WHITE, 15, bold=True,
                anchor_x="center", anchor_y="center",
            ))

        self._t_track = arcade.Text(
            "", sw // 2, 30,
            arcade.color.KHAKI, 10,
            anchor_x="center", anchor_y="center",
        )
        self._t_music_hdr = arcade.Text(
            "NOW PLAYING", sw // 2, 48,
            (120, 120, 130), 8,
            anchor_x="center", anchor_y="center",
        )

        # ── Load-game sub-screen state ─────────────────────────────────
        self._show_load: bool = False
        self._load_hover: int = -1
        self._load_slots: list[dict] = []
        self._t_load_title = arcade.Text(
            "LOAD GAME", sw // 2, 0,
            arcade.color.LIGHT_BLUE, 20, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_load_labels: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 11,
                        anchor_x="left", anchor_y="center")
            for _ in range(SAVE_SLOT_COUNT)
        ]
        self._t_load_details: list[arcade.Text] = [
            arcade.Text("", 0, 0, (160, 180, 200), 9,
                        anchor_x="left", anchor_y="center")
            for _ in range(SAVE_SLOT_COUNT)
        ]
        self._t_load_back = arcade.Text(
            "Back", sw // 2, 0,
            arcade.color.WHITE, 13, bold=True,
            anchor_x="center", anchor_y="center",
        )

    # ── Music helpers ──────────────────────────────────────────────────

    def _play_next_track(self) -> None:
        if not self._music_tracks:
            return
        track, name = self._music_tracks[self._music_idx]
        self._current_track_name = name
        self._music_player = arcade.play_sound(track, volume=audio.music_volume)
        self._music_idx = (self._music_idx + 1) % len(self._music_tracks)

    def _stop_music(self) -> None:
        if self._music_player is not None:
            arcade.stop_sound(self._music_player)
            self._music_player = None

    # ── Load-game helpers ──────────────────────────────────────────────

    def _refresh_load_slots(self) -> None:
        import json
        self._load_slots = []
        os.makedirs(_SAVE_DIR, exist_ok=True)
        for i in range(SAVE_SLOT_COUNT):
            path = os.path.join(_SAVE_DIR, f"save_slot_{i + 1:02d}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    name = data.get("save_name", f"Save {i + 1}")
                    player = data.get("player", {})
                    self._load_slots.append({
                        "name": name,
                        "exists": True,
                        "faction": data.get("faction", "?"),
                        "ship_type": data.get("ship_type", "?"),
                        "hp": player.get("hp", 0),
                        "shields": player.get("shields", 0),
                    })
                except Exception:
                    self._load_slots.append({"name": "", "exists": False})
            else:
                self._load_slots.append({"name": "", "exists": False})

    def _load_slot_rects(self) -> list[tuple[int, int, int, int]]:
        """Compute slot button rectangles for the load sub-screen."""
        from constants import SAVE_SLOT_W, SAVE_SLOT_H, SAVE_SLOT_GAP, SAVE_MENU_H
        sw = self.window.width
        sh = self.window.height
        top_y = sh // 2 + SAVE_MENU_H // 2 - 60
        rects = []
        for i in range(SAVE_SLOT_COUNT):
            sx = (sw - SAVE_SLOT_W) // 2
            sy = top_y - i * (SAVE_SLOT_H + SAVE_SLOT_GAP)
            rects.append((sx, sy, SAVE_SLOT_W, SAVE_SLOT_H))
        return rects

    def _load_back_rect(self) -> tuple[int, int, int, int]:
        rects = self._load_slot_rects()
        last = rects[-1]
        return ((self.window.width - 240) // 2, last[1] - 50, 240, 35)

    # ── Layout ────────────────────────────────────────────────────────

    def _update_layout(self) -> None:
        """Recompute all UI positions from actual window size."""
        sw = self.window.width
        sh = self.window.height
        # Buttons
        top_y = sh // 2 - 20
        self._btn_rects = []
        for i in range(len(_BTN_LABELS)):
            bx = (sw - _BTN_W) // 2
            by = top_y - i * (_BTN_H + _BTN_GAP)
            self._btn_rects.append((bx, by, _BTN_W, _BTN_H))
        # Text positions
        self._t_title.x = sw // 2
        self._t_title.y = sh - 160
        self._t_subtitle.x = sw // 2
        self._t_subtitle.y = sh - 210
        for i in range(len(_BTN_LABELS)):
            bx, by, bw, bh = self._btn_rects[i]
            self._t_btn_labels[i].x = bx + bw // 2
            self._t_btn_labels[i].y = by + bh // 2
        self._t_track.x = sw // 2
        self._t_music_hdr.x = sw // 2

    # ── Drawing ────────────────────────────────────────────────────────

    def on_draw(self) -> None:
        self.clear()
        self._update_layout()

        sw = self.window.width
        sh = self.window.height
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, sw, sh),
            (6, 6, 18),
        )

        # Decorative star dots
        rng = random.Random(42)
        for _ in range(120):
            sx = rng.randint(0, sw)
            sy = rng.randint(0, sh)
            br = rng.randint(60, 220)
            arcade.draw_point(sx, sy, (br, br, br + 30, 200), 1.5)

        if self._show_load:
            self._draw_load_screen()
        else:
            self._draw_main()

        # Track name
        if self._current_track_name:
            self._t_music_hdr.draw()
            self._t_track.text = self._current_track_name
            self._t_track.draw()

    def _draw_main(self) -> None:
        self._t_title.draw()
        self._t_subtitle.draw()

        for i, label in enumerate(_BTN_LABELS):
            bx, by, bw, bh = self._btn_rects[i]
            hovered = (i == self._hover_idx)

            bg = (50, 80, 140, 255) if hovered else (25, 35, 70, 230)
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
            outline = arcade.color.CYAN if hovered else arcade.color.STEEL_BLUE
            arcade.draw_rect_outline(
                arcade.LBWH(bx, by, bw, bh), outline, border_width=2,
            )
            self._t_btn_labels[i].color = (
                arcade.color.CYAN if hovered else arcade.color.WHITE
            )
            self._t_btn_labels[i].draw()

    def _draw_load_screen(self) -> None:
        from constants import SAVE_MENU_W, SAVE_MENU_H
        # Panel background
        slot_rects = self._load_slot_rects()
        panel_w, panel_h = SAVE_MENU_W, SAVE_MENU_H
        px = (self.window.width - panel_w) // 2
        py = (self.window.height - panel_h) // 2
        arcade.draw_rect_filled(
            arcade.LBWH(px, py, panel_w, panel_h),
            (20, 20, 50, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, panel_w, panel_h),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_load_title.y = py + panel_h - 30
        self._t_load_title.draw()

        for i in range(SAVE_SLOT_COUNT):
            sx, sy, sw, sh = slot_rects[i]
            info = self._load_slots[i] if i < len(self._load_slots) else {"name": "", "exists": False}
            hovered = (i == self._load_hover)

            if not info["exists"]:
                bg = (20, 20, 40, 255)
                outline_c = (60, 60, 80)
                text_c = (80, 80, 100)
            elif hovered:
                bg = (50, 80, 140, 255)
                outline_c = arcade.color.CYAN
                text_c = arcade.color.CYAN
            else:
                bg = (30, 40, 80, 255)
                outline_c = arcade.color.STEEL_BLUE
                text_c = arcade.color.WHITE

            arcade.draw_rect_filled(arcade.LBWH(sx, sy, sw, sh), bg)
            arcade.draw_rect_outline(
                arcade.LBWH(sx, sy, sw, sh), outline_c, border_width=1,
            )

            if info["exists"]:
                label = f"Slot {i + 1}: {info['name']}"
            else:
                label = f"Slot {i + 1}: \u2014 Empty \u2014"
            self._t_load_labels[i].text = label
            self._t_load_labels[i].x = sx + 10
            self._t_load_labels[i].y = sy + sh - 10
            self._t_load_labels[i].color = text_c
            self._t_load_labels[i].draw()

            # Detail line (faction/ship/HP/shields)
            if info["exists"]:
                detail = (f"{info.get('faction', '?')} \u00b7 {info.get('ship_type', '?')}"
                          f"  |  HP {info.get('hp', 0)}  Shields {info.get('shields', 0)}")
                det_c = (140, 200, 240) if hovered else (120, 150, 180)
                self._t_load_details[i].text = detail
                self._t_load_details[i].x = sx + 10
                self._t_load_details[i].y = sy + 10
                self._t_load_details[i].color = det_c
                self._t_load_details[i].draw()

        # Back button
        bbx, bby, bbw, bbh = self._load_back_rect()
        back_hovered = (self._load_hover == 100)
        bg = (50, 80, 140, 255) if back_hovered else (30, 40, 80, 255)
        arcade.draw_rect_filled(arcade.LBWH(bbx, bby, bbw, bbh), bg)
        outline = arcade.color.CYAN if back_hovered else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(bbx, bby, bbw, bbh), outline, border_width=2,
        )
        self._t_load_back.y = bby + bbh // 2
        self._t_load_back.color = (
            arcade.color.CYAN if back_hovered else arcade.color.WHITE
        )
        self._t_load_back.draw()

    # ── Update ─────────────────────────────────────────────────────────

    def on_update(self, delta_time: float) -> None:
        # Advance music when track finishes
        if (self._music_player is not None
                and not self._music_player.playing):
            self._play_next_track()

    # ── Input ──────────────────────────────────────────────────────────

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._show_load:
            slot_rects = self._load_slot_rects()
            self._load_hover = -1
            for i, (sx, sy, sw, sh) in enumerate(slot_rects):
                if sx <= x <= sx + sw and sy <= y <= sy + sh:
                    self._load_hover = i
                    return
            bbx, bby, bbw, bbh = self._load_back_rect()
            if bbx <= x <= bbx + bbw and bby <= y <= bby + bbh:
                self._load_hover = 100
        else:
            self._hover_idx = -1
            for i, (bx, by, bw, bh) in enumerate(self._btn_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    self._hover_idx = i
                    return

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        if self._show_load:
            self._handle_load_click(x, y)
            return

        if self._hover_idx < 0:
            return
        arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
        label = _BTN_LABELS[self._hover_idx]
        if label == "Play Now":
            self._stop_music()
            from selection_view import SelectionView
            self.window.show_view(SelectionView())
        elif label == "Load Game":
            self._refresh_load_slots()
            self._show_load = True
            self._load_hover = -1
        elif label == "Options":
            self._stop_music()
            from options_view import OptionsView
            self.window.show_view(OptionsView())
        elif label == "Exit Game":
            arcade.exit()

    def _handle_load_click(self, x: int, y: int) -> None:
        arcade.play_sound(self._click_snd, volume=audio.sfx_volume)

        # Back button
        bbx, bby, bbw, bbh = self._load_back_rect()
        if bbx <= x <= bbx + bbw and bby <= y <= bby + bbh:
            self._show_load = False
            self._load_hover = -1
            return

        # Slot clicks
        slot_rects = self._load_slot_rects()
        for i, (sx, sy, sw, sh) in enumerate(slot_rects):
            if sx <= x <= sx + sw and sy <= y <= sy + sh:
                if i < len(self._load_slots) and self._load_slots[i]["exists"]:
                    self._stop_music()
                    self._do_load(i)
                return

    def _do_load(self, slot: int) -> None:
        """Load a saved game and transition to GameView."""
        import json
        path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            data = json.load(f)

        from game_view import GameView
        view = GameView(
            faction=data.get("faction"),
            ship_type=data.get("ship_type"),
        )

        # Restore player state
        p = data["player"]
        view.player.center_x = p["x"]
        view.player.center_y = p["y"]
        view.player.heading = p["heading"]
        view.player.angle = p["heading"]
        view.player.vel_x = p["vel_x"]
        view.player.vel_y = p["vel_y"]
        view.player.hp = p["hp"]
        view.player.shields = p["shields"]
        view.player._shield_acc = p.get("shield_acc", 0.0)

        view._weapon_idx = data.get("weapon_idx", 0)
        view.inventory.iron = data.get("iron", 0)

        # Restore asteroids
        view.asteroid_list.clear()
        from sprites.asteroid import IronAsteroid
        asteroid_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "Pixel Art Space", "Asteroid.png")
        )
        for ad in data.get("asteroids", []):
            a = IronAsteroid(asteroid_tex, ad["x"], ad["y"])
            a.hp = ad["hp"]
            view.asteroid_list.append(a)

        # Restore aliens
        view.alien_list.clear()
        from PIL import Image as PILImage
        from constants import ALIEN_SHIP_PNG, ALIEN_FX_PNG
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
        alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))
        _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
        alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
        from sprites.alien import SmallAlienShip
        for ald in data.get("aliens", []):
            al = SmallAlienShip(alien_ship_tex, alien_laser_tex, ald["x"], ald["y"])
            al.hp = ald["hp"]
            al.vel_x = ald.get("vel_x", 0.0)
            al.vel_y = ald.get("vel_y", 0.0)
            al._heading = ald.get("heading", 0.0)
            al.angle = al._heading
            al._state = ald.get("state", 0)
            al._home_x = ald.get("home_x", ald["x"])
            al._home_y = ald.get("home_y", ald["y"])
            view.alien_list.append(al)

        # Restore iron pickups
        view.iron_pickup_list.clear()
        for pd in data.get("pickups", []):
            view._spawn_iron_pickup(pd["x"], pd["y"], amount=pd.get("amount", 10))

        self.window.show_view(view)

    def on_key_press(self, key: int, modifiers: int) -> None:
        if self._show_load:
            if key == arcade.key.ESCAPE:
                self._show_load = False
                self._load_hover = -1
            return
        if key == arcade.key.ESCAPE:
            arcade.exit()
