"""Music and video management extracted from GameView."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import arcade

from settings import audio
from video_player import character_video_path

if TYPE_CHECKING:
    from game_view import GameView


def play_next_track(gv: GameView) -> None:
    """Start playing the next music track in the shuffled playlist."""
    if not gv._music_tracks:
        return
    gv._music_idx = (gv._music_idx + 1) % len(gv._music_tracks)
    path, name = gv._music_tracks[gv._music_idx]
    gv._current_track_name = name
    gv._music_player = arcade.play_sound(
        arcade.load_sound(path), volume=audio.music_volume, looping=False)


def stop_music(gv: GameView) -> None:
    """Stop the currently playing background music track."""
    if gv._music_player is not None:
        try:
            arcade.stop_sound(gv._music_player)
        except Exception:
            pass
        gv._music_player = None


def play_video(gv: GameView, filepath: str) -> None:
    """Start video playback, replacing the music track."""
    stop_music(gv)
    gv._current_track_name = ""
    success = gv._video_player.play(filepath, volume=audio.music_volume)
    gv._escape_menu._last_video_error = gv._video_player.error if not success else ""
    if not success and gv._music_tracks:
        play_next_track(gv)


def start_character_video(gv: GameView) -> None:
    """Start the character video if one is configured."""
    name = audio.character_name
    if not name:
        return
    path = character_video_path(name)
    if path:
        gv._char_video_player.play_segments(path, volume=0.0)


def select_character(gv: GameView, name: str) -> None:
    """Called when the player picks a character in the ESC menu."""
    gv._char_video_player.stop()
    if name:
        path = character_video_path(name)
        if path:
            gv._char_video_player.play_segments(path, volume=0.0)


def stop_video(gv: GameView) -> None:
    """Stop video playback without resuming music or equalizer."""
    gv._video_player.stop()
    gv._current_track_name = ""


def stop_song(gv: GameView) -> None:
    """Stop the current background music track and any video."""
    if gv._video_player.active:
        gv._video_player.stop()
    stop_music(gv)
    gv._current_track_name = ""


def other_song(gv: GameView) -> None:
    """Skip to a random different song from the OST (stops video first)."""
    if gv._video_player.active:
        gv._video_player.stop()
    stop_music(gv)
    if gv._music_tracks:
        if len(gv._music_tracks) > 1:
            import random as _rng
            old = gv._music_idx
            while gv._music_idx == old:
                gv._music_idx = _rng.randrange(len(gv._music_tracks))
        play_next_track(gv)


def return_to_menu(gv: GameView) -> None:
    """Return to the splash / title screen."""
    gv._video_player.stop()
    gv._char_video_player.stop()
    if gv._thruster_player is not None:
        arcade.stop_sound(gv._thruster_player)
        gv._thruster_player = None
    stop_music(gv)
    from splash_view import SplashView
    gv.window.show_view(SplashView())


def change_resolution(gv: GameView, width: int, height: int, display_mode: str) -> None:
    """Change resolution mid-game: save state, resize, rebuild view."""
    from settings import apply_resolution
    from game_save import save_to_dict, restore_state

    data = save_to_dict(gv)
    video_was_active = gv._video_player.active
    video_file = getattr(gv._video_player, '_current_file', "")
    music_was_playing = (gv._music_player is not None and gv._current_track_name != "")
    if video_was_active:
        gv._video_player.stop()
    gv._char_video_player.stop()
    if gv._thruster_player is not None:
        arcade.stop_sound(gv._thruster_player)
        gv._thruster_player = None
    stop_music(gv)
    apply_resolution(gv.window, width, height, display_mode=display_mode)
    from game_view import GameView as GV
    view = GV(faction=data.get("faction"), ship_type=data.get("ship_type"),
              skip_music=True)
    restore_state(view, data)
    if video_was_active and video_file:
        video_dir = getattr(audio, 'video_dir', "")
        if video_dir:
            full_path = os.path.join(video_dir, video_file)
            if os.path.isfile(full_path):
                view._video_player.play(full_path, volume=audio.music_volume)
    if not view._video_player.active and music_was_playing:
        play_next_track(view)
    gv.window.show_view(view)
