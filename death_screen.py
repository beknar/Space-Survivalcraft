"""Death screen overlay shown when the player's HP reaches zero."""
from __future__ import annotations

import os
import random

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    SFX_INTERFACE_DIR, SAVE_SLOT_COUNT,
)
from settings import audio


_BTN_W = 240
_BTN_H = 45
_BTN_GAP = 16
_BTN_LABELS = ["Load Game", "Main Menu", "Exit Game"]

_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")

_DEATH_QUOTES = [
    "The void doesn't judge. It just... collects.",
    "Your ship called. It wants a better pilot.",
    "That wasn't flying — that was falling with extra steps.",
    "Space debris now. How the mighty have fallen.",
    "At least you died doing what you loved: exploding.",
    "Your insurance premiums just went through the hull.",
    "Plot twist: the asteroids were the main characters all along.",
    "Maybe try diplomacy next time? Oh wait, they're rocks.",
    "You zigged when you should have zagged. And also when you should have zigged.",
    "Your ship has been promoted to scrap metal.",
    "Fun fact: shields work better when they're not at zero.",
    "The aliens wanted to say thanks for the target practice.",
    "That explosion was almost pretty. Almost.",
    "Somewhere, a shipyard accountant just had a panic attack.",
    "You fought bravely. Briefly, but bravely.",
    "Have you considered a career in something less... explode-y?",
    "Your contribution to the asteroid belt has been noted.",
    "The cosmos giveth, and the cosmos bloweth up.",
    "Captain's log, final entry: 'What does this button d—'",
    "That's one small step for debris, one giant cloud for mankind.",
    "Breaking news: local pilot discovers asteroids are, in fact, solid.",
    "Error 404: Ship not found.",
    "Achievement unlocked: Rapid Unplanned Disassembly.",
    "The stars will remember you. Briefly.",
    "You've successfully converted a spaceship into modern art.",
    "Don't worry, space is big. There's room for another attempt.",
    "Your fuel efficiency is now infinite. Silver linings!",
    "Narrator: It was, in fact, not a shortcut.",
    "The alien scouts have updated their kill count. You're welcome.",
    "In space, no one can hear you ragequit.",
    "Remember: the brake pedal is the other one.",
    "Your autopilot filed for divorce.",
    "Today's forecast: scattered ship parts with a chance of regret.",
    "The good news? You found every asteroid in the sector.",
    "Tip: the red bar going down is generally considered bad.",
    "Your ship disassembled itself in protest.",
    "Looks like the aliens won this round of rock-paper-laser.",
    "That was either very brave or very foolish. Spoiler: it was the second one.",
    "You've been voted 'Most Likely to Respawn' by the alien council.",
    "Your shield generator is filing a complaint with HR.",
    "You turned a perfectly good spaceship into a fireworks show.",
    "Evasive manoeuvres are only effective when you actually... manoeuvre.",
    "The wreckage will make a lovely reef. In space. A space reef.",
    "Your cargo of iron has been donated to the void. How generous.",
    "Mission report: ship status — crunchy.",
    "The aliens send their regards. And also lasers.",
    "On the bright side, you'll never have to refuel again.",
    "They say space is cold, but that explosion looked pretty warm.",
    "Consider this a learning experience. An expensive one.",
    "Your ship has achieved room temperature. In space. Impressive.",
]


class DeathScreen:
    """Modal overlay displayed when the player ship is destroyed.

    Shows a quote, and three buttons: Load Game, Main Menu, Exit Game.
    """

    def __init__(self) -> None:
        self.active: bool = False
        self._hover_idx: int = -1

        # ── Load sub-screen state ──────────────────────────────────────
        self._show_load: bool = False
        self._load_hover: int = -1
        self._load_slots: list[dict] = []

        # ── Button rects (centred on screen) ───────────────────────────
        total_h = len(_BTN_LABELS) * _BTN_H + (len(_BTN_LABELS) - 1) * _BTN_GAP
        top_y = SCREEN_HEIGHT // 2 - 60
        self._btn_rects: list[tuple[int, int, int, int]] = []
        for i in range(len(_BTN_LABELS)):
            bx = (SCREEN_WIDTH - _BTN_W) // 2
            by = top_y - i * (_BTN_H + _BTN_GAP)
            self._btn_rects.append((bx, by, _BTN_W, _BTN_H))

        # ── Sound ──────────────────────────────────────────────────────
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 2.wav")
        )

        # ── Text objects ───────────────────────────────────────────────
        self._t_title = arcade.Text(
            "SHIP DESTROYED",
            SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 100,
            (255, 80, 60), 36, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_quote = arcade.Text(
            random.choice(_DEATH_QUOTES),
            SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 40,
            (200, 180, 140), 14, italic=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_btn_labels: list[arcade.Text] = []
        for i, label in enumerate(_BTN_LABELS):
            bx, by, bw, bh = self._btn_rects[i]
            self._t_btn_labels.append(arcade.Text(
                label,
                bx + bw // 2, by + bh // 2,
                arcade.color.WHITE, 14, bold=True,
                anchor_x="center", anchor_y="center",
            ))

        # ── Load sub-screen text objects ───────────────────────────────
        self._t_load_title = arcade.Text(
            "LOAD GAME", SCREEN_WIDTH // 2, 0,
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
            "Back", SCREEN_WIDTH // 2, 0,
            arcade.color.WHITE, 13, bold=True,
            anchor_x="center", anchor_y="center",
        )

    # ── Public API ─────────────────────────────────────────────────────

    def show(self) -> None:
        self.active = True
        self._hover_idx = -1
        self._show_load = False
        self._t_quote.text = random.choice(_DEATH_QUOTES)

    # ── Load slot helpers ──────────────────────────────────────────────

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
                        "name": name, "exists": True,
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
        from constants import SAVE_SLOT_W, SAVE_SLOT_H, SAVE_SLOT_GAP, SAVE_MENU_H
        top_y = SCREEN_HEIGHT // 2 + SAVE_MENU_H // 2 - 60
        rects = []
        for i in range(SAVE_SLOT_COUNT):
            sx = (SCREEN_WIDTH - SAVE_SLOT_W) // 2
            sy = top_y - i * (SAVE_SLOT_H + SAVE_SLOT_GAP)
            rects.append((sx, sy, SAVE_SLOT_W, SAVE_SLOT_H))
        return rects

    def _load_back_rect(self) -> tuple[int, int, int, int]:
        rects = self._load_slot_rects()
        last = rects[-1]
        return ((SCREEN_WIDTH - 240) // 2, last[1] - 50, 240, 35)

    # ── Drawing ────────────────────────────────────────────────────────

    def draw(self) -> None:
        if not self.active:
            return

        # Dark overlay
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT),
            (0, 0, 0, 200),
        )

        if self._show_load:
            self._draw_load()
        else:
            self._draw_main()

    def _draw_main(self) -> None:
        self._t_title.draw()
        self._t_quote.draw()

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

    def _draw_load(self) -> None:
        from constants import SAVE_MENU_W, SAVE_MENU_H
        slot_rects = self._load_slot_rects()
        panel_w, panel_h = SAVE_MENU_W, SAVE_MENU_H
        px = (SCREEN_WIDTH - panel_w) // 2
        py = (SCREEN_HEIGHT - panel_h) // 2
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

            label = f"Slot {i + 1}: {info['name']}" if info["exists"] else f"Slot {i + 1}: \u2014 Empty \u2014"
            self._t_load_labels[i].text = label
            self._t_load_labels[i].x = sx + 10
            self._t_load_labels[i].y = sy + sh - 10
            self._t_load_labels[i].color = text_c
            self._t_load_labels[i].draw()

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

    # ── Input ──────────────────────────────────────────────────────────

    def on_mouse_motion(self, x: int, y: int) -> None:
        if not self.active:
            return
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

    def on_mouse_press(self, x: int, y: int) -> str | None:
        """Handle click. Returns action string or None.

        Possible return values:
        - "load:<slot>" — load from the given slot number
        - "main_menu" — go to splash screen
        - "exit" — quit the game
        - None — no action taken
        """
        if not self.active:
            return None

        if self._show_load:
            return self._handle_load_click(x, y)

        if self._hover_idx < 0:
            return None
        arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
        label = _BTN_LABELS[self._hover_idx]
        if label == "Load Game":
            self._refresh_load_slots()
            self._show_load = True
            self._load_hover = -1
            return None
        elif label == "Main Menu":
            return "main_menu"
        elif label == "Exit Game":
            return "exit"
        return None

    def _handle_load_click(self, x: int, y: int) -> str | None:
        arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
        bbx, bby, bbw, bbh = self._load_back_rect()
        if bbx <= x <= bbx + bbw and bby <= y <= bby + bbh:
            self._show_load = False
            self._load_hover = -1
            return None
        slot_rects = self._load_slot_rects()
        for i, (sx, sy, sw, sh) in enumerate(slot_rects):
            if sx <= x <= sx + sw and sy <= y <= sy + sh:
                if i < len(self._load_slots) and self._load_slots[i]["exists"]:
                    return f"load:{i}"
        return None

    def on_key_press(self, key: int) -> None:
        if self._show_load and key == arcade.key.ESCAPE:
            self._show_load = False
            self._load_hover = -1
