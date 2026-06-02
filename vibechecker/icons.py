"""Icon registry — CommitMono Nerd Font (Codicons BMP PUA)."""
from __future__ import annotations
import dearpygui.dearpygui as dpg
from vibechecker._paths import resource_path

FONT_SIZE = 16  # 12pt @ 96 DPI

# Codicons — all in BMP PUA 0xE000-0xFFFF (safe with DPG ImWchar16).
# Codepoints verified against CommitMonoNerdFont-Regular.otf via fontTools.
IC: dict[str, str] = {
    # card header setup / sensor buttons
    'settings':            '\ueaf8',  # cod-gear
    'sensors':             '\ueaad',  # cod-broadcast
    # card section leading icons
    'developer_board':     '\uea7a',  # cod-vm
    'channels':            '\ueb2d',  # cod-plug
    'acquisition':         '\uf469',  # oct-pulse
    'folder':              '\uea83',  # cod-folder
    'monitor_heart':       '\ueb05',  # cod-heart
    # acquisition action buttons
    'play_arrow':          '\ueb2c',  # cod-play
    'stop':                '\uead7',  # cod-debug_stop
    'photo_camera':        '\uead9',  # cod-device_camera_video
    'fit_screen':          '\ueb4c',  # cod-screen_full
    'delete_sweep':        '\uea81',  # cod-trash
    # browse waveform nav
    'first_page':          '\uea9b',  # cod-arrow_left
    'navigate_before':     '\uea9e',  # cod-arrow_small_left
    'navigate_next':       '\uea9f',  # cod-arrow_small_right
    'last_page':           '\uea9c',  # cod-arrow_right
    # file handling
    'save':                '\ueb4b',  # cod-save
    'folder_open':         '\ueaf7',  # cod-folder_opened
    # monitor arm / disarm
    'arm':                 '\uebf8',  # cod-target
    'disarm':              '\uead7',  # cod-debug_stop (reuse)
    # config dialog
    'refresh':             '\uea77',  # cod-sync
    'add':                 '\uea60',  # cod-add
    'delete':              '\uea81',  # cod-trash (reuse)
    'close':               '\uea76',  # cod-close
}

_font_tag: int | str | None = None


def load() -> int | str:
    """Register the font with DPG. Idempotent within one DPG context lifetime."""
    global _font_tag
    if _font_tag is not None:
        return _font_tag
    font_path = str(resource_path('assets/fonts/CommitMonoNerdFont-Regular.otf'))
    with dpg.font_registry():
        with dpg.font(font_path, FONT_SIZE) as tag:
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
            dpg.add_font_range(0xe000, 0xffff)
    _font_tag = tag
    return tag


def reset() -> None:
    """Clear cached font tag. Call after dpg.destroy_context()."""
    global _font_tag
    _font_tag = None


def font_tag() -> int | str:
    if _font_tag is None:
        raise RuntimeError('icons.load() must be called first')
    return _font_tag
