import sys
from pathlib import Path

import vlc
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSlider,
    QPushButton, QLabel, QSizePolicy, QStackedWidget, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QPoint, QRect
from PyQt6.QtGui import QIcon, QPalette, QColor, QFont, QAction

from config.config import STATE_FILE, REWIND_ON_RESUME
from core.state_manager import StateManager
from models.state import PlayerState
from interface.icon_store import *

from utils.logger import get_logger

log = get_logger("player")

_SEEK_STEP_MS = 10_000   # 10 seconds in milliseconds
_CONTROLS_BAR_HIDE_TIMER = 4_000


def _fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02}:{sec:02}"
    return f"{m}:{sec:02}"


def _fmt_delay(us: int) -> str:
    """Format microseconds as e.g. '+200 ms' or '-1.5 s'."""
    ms = us // 1000
    if abs(ms) < 1000:
        return f"{ms:+d} ms"
    return f"{ms / 1000:+.1f} s"


class SeekSlider(QSlider):
    """QSlider that jumps directly to the clicked position."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = event.position().x() / max(self.width(), 1)
            value = round(ratio * (self.maximum() - self.minimum()) + self.minimum())
            self.setValue(value)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        # Let Left/Right propagate to PlayerWidget instead of moving the slider
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            event.ignore()
            return
        super().keyPressEvent(event)


class FullscreenOverlay(QWidget):
    """
    Covers the main window completely — no separate OS window.

    Layout (all children of this widget):
      _video_frame        – native QFrame; VLC renders here, fills everything
      _controls_wrapper   – semi-transparent QWidget at the bottom, overlaid
                            on top of the video via Qt6/XComposite
    """

    def __init__(self, player_widget: "PlayerWidget"):
        parent = player_widget.window()
        super().__init__(parent)
        self._player = player_widget
        self._controls_hidden = False

        self.setGeometry(parent.rect())
        self.setStyleSheet("background: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # ── Video frame (native; VLC embeds its XWindow here) ────────
        self._video_frame = QFrame(self)
        self._video_frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        pal = self._video_frame.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self._video_frame.setPalette(pal)
        self._video_frame.setAutoFillBackground(True)

        # ── Semi-transparent controls overlay ────────────────────────
        # WA_NativeWindow gives it its own X11 window so it can be raised
        # above VLC's native _video_frame sub-window.
        # WA_TranslucentBackground requests an ARGB visual so the rgba()
        # stylesheet colour actually appears translucent (needs a compositor).
        self._controls_wrapper = QWidget(self)
        self._controls_wrapper.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._controls_wrapper.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._controls_wrapper.setStyleSheet("background: rgba(0, 0, 0, 180);")

        wrapper_layout = QVBoxLayout(self._controls_wrapper)
        wrapper_layout.setContentsMargins(0, 4, 0, 0)
        wrapper_layout.setSpacing(0)

        # Reparent the controls bar into the overlay; make its background
        # transparent so only the wrapper's rgba shows.
        self._orig_controls_style = player_widget._controls_bar.styleSheet()
        player_widget._controls_bar.setStyleSheet("background: transparent;")
        wrapper_layout.addWidget(player_widget._controls_bar)

        # ── Auto-hide timer (t s of inactivity) ─────────────────────
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_CONTROLS_BAR_HIDE_TIMER)
        self._hide_timer.timeout.connect(self._hide_controls)

        # Catch mouse moves globally (VLC's XWindow eats Qt mouse events
        # over the video area, so a widget-level filter wouldn't work).
        QApplication.instance().installEventFilter(self)
        parent.installEventFilter(self)  # handle parent resize

        self._layout_children()
        self.show()
        self.raise_()
        self.setFocus()
        self._hide_timer.start()

    # ── Geometry helpers ─────────────────────────────────────────────

    def _layout_children(self):
        r = self.rect()
        ctrl_h = self._player._controls_bar.sizeHint().height() + 12
        self._video_frame.setGeometry(r)
        self._controls_wrapper.setGeometry(0, r.height() - ctrl_h, r.width(), ctrl_h)
        # Keep controls stacked above VLC's native sub-window
        self._controls_wrapper.raise_()

    def resizeEvent(self, event):
        self._layout_children()
        super().resizeEvent(event)

    # ── Event filter ─────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        # Keep overlay in sync when the main window is resized
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            return False
        # Any mouse movement anywhere in the app resets the hide timer
        if event.type() == QEvent.Type.MouseMove:
            self._on_mouse_activity()
        # Left-click in the video area toggles play/pause.
        # VLC's native X11 window eats Qt widget events, so we must intercept
        # at the application level using global coordinates.
        if (event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            gp = event.globalPosition().toPoint()
            overlay_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            ctrl_rect    = QRect(
                self._controls_wrapper.mapToGlobal(QPoint(0, 0)),
                self._controls_wrapper.size(),
            )
            if overlay_rect.contains(gp):
                self._on_mouse_activity()          # always show/reset controls on click
                if not ctrl_rect.contains(gp):    # only toggle if not on controls
                    self._player.toggle_play()
        return False

    # ── Controls show / hide ─────────────────────────────────────────

    def _on_mouse_activity(self):
        if self._controls_hidden:
            self._show_controls()
        else:
            self._hide_timer.start()   # restart the 5-second countdown

    def _show_controls(self):
        self._controls_hidden = False
        self._controls_wrapper.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hide_timer.start()

    def _hide_controls(self):
        self._controls_hidden = True
        self._controls_wrapper.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    # ── Key / mouse events ───────────────────────────────────────────

    def keyPressEvent(self, event):
        pw = self._player
        k = event.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_F, Qt.Key.Key_F11):
            pw.toggle_fullscreen()
        elif k == Qt.Key.Key_Space:
            pw.toggle_play()
        elif k == Qt.Key.Key_Left:
            pw.seek_relative(-_SEEK_STEP_MS)
        elif k == Qt.Key.Key_Right:
            pw.seek_relative(_SEEK_STEP_MS)
        elif k == Qt.Key.Key_M:
            pw.toggle_mute()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._player.toggle_fullscreen()

    # ── Cleanup ──────────────────────────────────────────────────────

    def cleanup(self):
        """Remove event filters and restore controls-bar style."""
        QApplication.instance().removeEventFilter(self)
        if self.parent():
            self.parent().removeEventFilter(self)
        self._hide_timer.stop()
        self._player._controls_bar.setStyleSheet(self._orig_controls_style)
        # Restore cursor on the main window
        self.parent().unsetCursor() if self.parent() else None


class PlayerWidget(QWidget):
    """Embedded VLC player with audio/subtitle/sync controls."""

    def __init__(self, volume: int = 80, parent=None):
        super().__init__(parent)
        self._is_fullscreen = False
        self._fullscreen_win: FullscreenOverlay | None = None
        self._current_path: Path | None = None
        self._last_played_path: Path | None = None
        self._state_manager: StateManager | None = None
        self._dragging_seek = False
        self._seeking = False
        self._muted = False
        self._audio_delay_us: int = 0   # microseconds

        self._vlc_instance = vlc.Instance("--no-xlib")
        self._player = self._vlc_instance.media_player_new()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()
        self.set_volume(volume)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._update_ui)
        self._timer.start()

        self._seek_block_timer = QTimer(self)
        self._seek_block_timer.setSingleShot(True)
        self._seek_block_timer.setInterval(700)
        self._seek_block_timer.timeout.connect(lambda: setattr(self, "_seeking", False))

        # Intercept mouse presses app-wide so clicks on the VLC native window
        # (which eats Qt widget-level events) still reach us.
        QApplication.instance().installEventFilter(self)

    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Stacked: blank slate (0) / video frame (1) ────────────
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._blank = self._make_blank_slate()
        self._stack.addWidget(self._blank)

        self._video_frame = QFrame()
        self._video_frame.setObjectName("video_frame")
        self._video_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        pal = self._video_frame.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self._video_frame.setPalette(pal)
        self._video_frame.setAutoFillBackground(True)
        self._video_frame.mouseDoubleClickEvent = lambda e: self.toggle_fullscreen()
        self._stack.addWidget(self._video_frame)

        self._stack.setCurrentIndex(0)

        # ── Controls bar ──────────────────────────────────────────
        controls = QFrame()
        controls.setObjectName("controls_bar")
        c_layout = QVBoxLayout(controls)
        c_layout.setContentsMargins(12, 6, 12, 8)
        c_layout.setSpacing(6)

        # ── Row 1: seek slider ────────────────────────────────────
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)

        self._time_lbl = QLabel("0:00 : 0:00")
        self._time_lbl.setObjectName("subtitle")
        self._time_lbl.setFixedWidth(90)
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(play_icon)
        self._play_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._play_btn.setObjectName("icon_btn")
        self._play_btn.setFixedSize(32, 32)
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.setToolTip("Play / Pause  [Space]")
        self._play_btn.clicked.connect(self.toggle_play)

        self._seek = SeekSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setValue(0)
        self._seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._seek.sliderPressed.connect(self._on_seek_press)
        self._seek.sliderReleased.connect(self._on_seek_release)

        seek_row.addWidget(self._play_btn)
        seek_row.addWidget(self._seek)
        seek_row.addWidget(self._time_lbl)
        c_layout.addLayout(seek_row)

        # ── Row 2: transport controls ─────────────────────────────
        transport = QHBoxLayout()
        transport.setSpacing(6)

        # self._mute_btn = QPushButton("🔊")
        self._mute_btn = QPushButton()
        self._mute_btn.setIcon(volume_icon)
        self._mute_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._mute_btn.setObjectName("icon_btn")
        self._mute_btn.setFixedSize(32, 32)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setToolTip("Mute / Unmute  [M]")
        self._mute_btn.clicked.connect(self.toggle_mute)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 150)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(96)
        self._vol_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vol_slider.setToolTip("Volume")
        self._vol_slider.valueChanged.connect(self._on_volume_change)

        self._vol_lbl = QLabel("80%")
        self._vol_lbl.setObjectName("subtitle")
        self._vol_lbl.setFixedWidth(36)

        # self._title_lbl = QLabel("")
        # self._title_lbl.setObjectName("subtitle")
        # self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sync_lbl = QLabel("A/V:")
        sync_lbl.setObjectName("subtitle")

        self._sync_down_btn = QPushButton()
        self._sync_down_btn.setIcon(minus_icon)
        self._sync_down_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._sync_down_btn.setObjectName("icon_btn")
        self._sync_down_btn.setFixedSize(26, 26)
        self._sync_down_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sync_down_btn.setToolTip("Audio delay −100 ms")
        self._sync_down_btn.clicked.connect(lambda: self._adjust_audio_delay(-100_000))

        self._sync_lbl = QLabel("0 ms")
        self._sync_lbl.setObjectName("subtitle")
        self._sync_lbl.setFixedWidth(40)
        self._sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sync_up_btn = QPushButton()
        self._sync_up_btn.setIcon(plus_icon)
        self._sync_up_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._sync_up_btn.setObjectName("icon_btn")
        self._sync_up_btn.setFixedSize(26, 26)
        self._sync_up_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sync_up_btn.setToolTip("Audio delay +100 ms")
        self._sync_up_btn.clicked.connect(lambda: self._adjust_audio_delay(100_000))

        # self._sync_reset_btn = QPushButton("Reset")
        # self._sync_reset_btn.setObjectName("icon_btn")
        # self._sync_reset_btn.setFixedHeight(26)
        # self._sync_reset_btn.setToolTip("Reset A/V sync to 0")
        # self._sync_reset_btn.clicked.connect(self._reset_audio_delay)

        self._fs_btn = QPushButton()
        self._fs_btn.setIcon(fullscreen_icon)
        self._fs_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._fs_btn.setObjectName("icon_btn")
        self._fs_btn.setFixedSize(36, 32)
        self._fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fs_btn.setToolTip("Fullscreen  [F]")
        self._fs_btn.clicked.connect(self.toggle_fullscreen)

        self._audio_btn = QPushButton()
        self._audio_btn.setIcon(audio_icon)
        self._audio_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._audio_btn.setObjectName("icon_btn")
        self._audio_btn.setToolTip("Select audio track")
        self._audio_btn.setFixedHeight(26)
        self._audio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._audio_btn.clicked.connect(self._show_audio_menu)

        self._sub_btn = QPushButton()
        self._sub_btn.setIcon(subtitle_icon)
        self._sub_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._sub_btn.setObjectName("icon_btn")
        self._sub_btn.setToolTip("Select subtitle track")
        self._sub_btn.setFixedHeight(26)
        self._sub_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sub_btn.clicked.connect(self._show_subtitle_menu)

        # transport.addWidget(self._play_btn)
        # transport.addWidget(self._stop_btn)
        transport.addWidget(self._mute_btn)
        transport.addWidget(self._vol_slider)
        transport.addWidget(self._vol_lbl)

        transport.addWidget(self._sync_down_btn)
        transport.addWidget(self._sync_lbl)
        transport.addWidget(self._sync_up_btn)

        transport.addStretch()
        # transport.addWidget(self._title_lbl)
        transport.addWidget(self._audio_btn)
        transport.addWidget(self._sub_btn)
        # transport.addStretch()
        transport.addWidget(self._fs_btn)
        c_layout.addLayout(transport)

        # ── Row 3: VLC track controls ─────────────────────────────
        # vlc_row = QHBoxLayout()
        # vlc_row.setSpacing(6)

        # self._audio_btn = QPushButton("🎵 Audio")
        # self._audio_btn.setObjectName("icon_btn")
        # self._audio_btn.setToolTip("Select audio track")
        # self._audio_btn.setFixedHeight(26)
        # self._audio_btn.clicked.connect(self._show_audio_menu)

        # self._sub_btn = QPushButton("💬 Subtitles")
        # self._sub_btn.setObjectName("icon_btn")
        # self._sub_btn.setToolTip("Select subtitle track")
        # self._sub_btn.setFixedHeight(26)
        # self._sub_btn.clicked.connect(self._show_subtitle_menu)

        # A/V sync
        # sync_lbl = QLabel("A/V:")
        # sync_lbl.setObjectName("subtitle")

        # self._sync_down_btn = QPushButton()
        # self._sync_down_btn.setIcon(minus_icon)
        # self._sync_down_btn.setObjectName("icon_btn")
        # self._sync_down_btn.setFixedSize(26, 26)
        # self._sync_down_btn.setToolTip("Audio delay −100 ms")
        # self._sync_down_btn.clicked.connect(lambda: self._adjust_audio_delay(-100_000))

        # self._sync_lbl = QLabel("0 ms")
        # self._sync_lbl.setObjectName("subtitle")
        # self._sync_lbl.setFixedWidth(70)
        # self._sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # self._sync_up_btn = QPushButton()
        # self._sync_up_btn.setIcon(plus_icon)
        # self._sync_up_btn.setObjectName("icon_btn")
        # self._sync_up_btn.setFixedSize(26, 26)
        # self._sync_up_btn.setToolTip("Audio delay +100 ms")
        # self._sync_up_btn.clicked.connect(lambda: self._adjust_audio_delay(100_000))

        # self._sync_reset_btn = QPushButton("Reset")
        # self._sync_reset_btn.setObjectName("icon_btn")
        # self._sync_reset_btn.setFixedHeight(26)
        # self._sync_reset_btn.setToolTip("Reset A/V sync to 0")
        # self._sync_reset_btn.clicked.connect(self._reset_audio_delay)

        # vlc_row.addWidget(self._audio_btn)
        # vlc_row.addWidget(self._sub_btn)
        # vlc_row.addSpacing(16)
        # vlc_row.addWidget(sync_lbl)
        # vlc_row.addWidget(self._sync_down_btn)
        # vlc_row.addWidget(self._sync_lbl)
        # vlc_row.addWidget(self._sync_up_btn)
        # vlc_row.addWidget(self._sync_reset_btn)
        # vlc_row.addStretch()
        # c_layout.addLayout(vlc_row)

        self._controls_bar = controls
        root.addWidget(controls)

    def _make_blank_slate(self) -> QWidget:
        from PyQt6.QtCore import QSize as _QSize
        w = QWidget()
        w.setStyleSheet("background:#000000;")
        inner = QVBoxLayout(w)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(16)

        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setStyleSheet("background:transparent;")
        logo_lbl.setPixmap(novaplay_icon.pixmap(_QSize(160, 160)))
        inner.addWidget(logo_lbl)

        name_lbl = QLabel("NovaPlay")
        font = QFont()
        font.setPointSize(32)
        font.setWeight(QFont.Weight.Thin)
        name_lbl.setFont(font)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("color:#c8c0e8;background:transparent;letter-spacing:6px;")
        inner.addWidget(name_lbl)

        hint_lbl = QLabel("Select a file from the library to begin")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setStyleSheet(
            "color:#3a3a5a;font-size:13px;background:transparent;"
        )
        inner.addWidget(hint_lbl)
        return w

    # ── Public API ───────────────────────────────────────────────

    def play(self, path: Path):
        is_same_file = (path == self._last_played_path)
        self._last_played_path = path
        self._current_path = path
        # self._title_lbl.setText(path.name)

        series_name = path.name
        self._state_manager = StateManager(STATE_FILE, series_name)

        resume_ms = 0
        if is_same_file:
            state = self._state_manager.load()
            resume_ms = max(0, (state.pos - REWIND_ON_RESUME) * 1000)

        try:
            media = self._vlc_instance.media_new(str(path))
            self._player.set_media(media)
            self._attach_window()
            self._stack.setCurrentIndex(1)
            self._player.play()

            if resume_ms > 0:
                QTimer.singleShot(800, lambda: self._player.set_time(resume_ms))

            # Reset A/V sync display for new file
            self._audio_delay_us = 0
            self._sync_lbl.setText("0 ms")
            # self._play_btn.setText("⏸")
            self._play_btn.setIcon(pause_icon)
            log.info("Playing: %s (resume=%dms)", path.name, resume_ms)
        except Exception:
            log.exception("Failed to start playback: %s", path)

    def toggle_play(self):
        state = self._player.get_state()
        if state == vlc.State.Playing:
            self._player.pause()
            self._play_btn.setIcon(play_icon)
            self._save_state()
        elif state in (vlc.State.Paused, vlc.State.Stopped):
            self._player.play()
            # self._play_btn.setText("⏸")
            self._play_btn.setIcon(pause_icon)

    def stop(self):
        self._save_state()
        self._player.stop()
        # self._play_btn.setText("▶")
        self._play_btn.setIcon(play_icon)
        self._seek.setValue(0)
        self._time_lbl.setText("0:00 : 0:00")
        self._stack.setCurrentIndex(0)

    def set_volume(self, vol: int):
        self._vol_slider.setValue(vol)
        self._player.audio_set_volume(vol)

    def get_volume(self) -> int:
        return self._vol_slider.value()

    def toggle_mute(self):
        self._muted = not self._muted
        self._player.audio_set_mute(self._muted)
        # self._mute_btn.setText("🔇" if self._muted else "🔊")
        self._mute_btn.setIcon(mute_icon if self._muted else volume_icon)

    def seek_relative(self, delta_ms: int):
        """Seek forward/backward by delta_ms milliseconds."""
        current = self._player.get_time()
        length = self._player.get_length()
        if length <= 0:
            return
        target = max(0, min(current + delta_ms, length))
        # Update UI immediately so it feels instant
        self._seek.setValue(int(target / length * 1000))
        self._time_lbl.setText(f"{_fmt_time(target)} / {_fmt_time(length)}")
        self._seeking = True
        self._seek_block_timer.start()  # restarts if already running
        self._player.set_time(target)

    def toggle_fullscreen(self):
        if not self._is_fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    # ── VLC track menus ──────────────────────────────────────────

    def _show_audio_menu(self):
        menu = QMenu(self)
        try:
            tracks = self._player.audio_get_track_description()
            if not tracks:
                menu.addAction("(no audio tracks)").setEnabled(False)
            else:
                current = self._player.audio_get_track()
                for t in tracks:
                    if hasattr(t, "id") and hasattr(t, "name"):
                        tid, name = t.id, t.name
                    elif isinstance(t, (tuple, list)) and len(t) >= 2:
                        tid, name = t[0], t[1]
                    else:
                        continue
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    action = QAction(name, self)
                    action.setCheckable(True)
                    action.setChecked(tid == current)
                    action.triggered.connect(
                        lambda checked, i=tid: self._player.audio_set_track(i)
                    )
                    menu.addAction(action)
        except Exception:
            log.exception("Failed to list audio tracks")
            menu.addAction("(error listing tracks)").setEnabled(False)
        menu.exec(self._audio_btn.mapToGlobal(
            QPoint(0, -menu.sizeHint().height())
        ))

    def _show_subtitle_menu(self):
        menu = QMenu(self)
        try:
            subs = self._player.video_get_spu_description()
            if not subs:
                menu.addAction("(no subtitle tracks)").setEnabled(False)
            else:
                current = self._player.video_get_spu()
                for s in subs:
                    if hasattr(s, "id") and hasattr(s, "name"):
                        sid, name = s.id, s.name
                    elif isinstance(s, (tuple, list)) and len(s) >= 2:
                        sid, name = s[0], s[1]
                    else:
                        continue
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    action = QAction(name, self)
                    action.setCheckable(True)
                    action.setChecked(sid == current)
                    action.triggered.connect(
                        lambda checked, i=sid: self._player.video_set_spu(i)
                    )
                    menu.addAction(action)
        except Exception:
            log.exception("Failed to list subtitle tracks")
            menu.addAction("(error listing subtitles)").setEnabled(False)
        menu.exec(self._sub_btn.mapToGlobal(
            QPoint(0, -menu.sizeHint().height())
        ))

    def _adjust_audio_delay(self, delta_us: int):
        """Shift audio delay by delta microseconds."""
        try:
            self._audio_delay_us = self._player.audio_get_delay() + delta_us
            self._player.audio_set_delay(self._audio_delay_us)
            self._sync_lbl.setText(_fmt_delay(self._audio_delay_us))
            log.debug("Audio delay: %d µs", self._audio_delay_us)
        except Exception:
            log.exception("Failed to set audio delay")

    def _reset_audio_delay(self):
        try:
            self._audio_delay_us = 0
            self._player.audio_set_delay(0)
            self._sync_lbl.setText("0 ms")
        except Exception:
            log.exception("Failed to reset audio delay")

    # ── Fullscreen ───────────────────────────────────────────────

    def _enter_fullscreen(self):
        if self._current_path is None:
            return
        self._is_fullscreen = True
        # self._fs_btn.setText("⊡")
        self._fs_btn.setIcon(restore_screen_icon)

        pos_ms = max(0, self._player.get_time())
        self._player.stop()  # tears down vout so set_xwindow takes effect

        self._fullscreen_win = FullscreenOverlay(self)
        # Make the main window itself go fullscreen so the overlay fills it
        self.window().showFullScreen()

        def _start():
            if self._fullscreen_win is None:
                return
            self._attach_window(self._fullscreen_win._video_frame)
            media = self._vlc_instance.media_new(str(self._current_path))
            media.add_option(f":start-time={pos_ms / 1000:.3f}")
            self._player.set_media(media)
            self._player.play()
            # self._play_btn.setText("⏸")
            self._play_btn.setIcon(pause_icon)

        QTimer.singleShot(300, _start)

    def _exit_fullscreen(self):
        if self._current_path is None:
            return
        self._is_fullscreen = False
        # self._fs_btn.setText("⛶")
        self._fs_btn.setIcon(fullscreen_icon)

        pos_ms = max(0, self._player.get_time())
        self._player.stop()

        # Move controls back to the main layout BEFORE destroying the overlay
        # so the widget is not destroyed along with it
        self._root_layout.addWidget(self._controls_bar)

        if self._fullscreen_win:
            self._fullscreen_win.cleanup()
            self._fullscreen_win.close()
            self._fullscreen_win = None

        # Restore the main window to its normal state
        self.window().showNormal()

        self._attach_window(self._video_frame)
        media = self._vlc_instance.media_new(str(self._current_path))
        media.add_option(f":start-time={pos_ms / 1000:.3f}")
        self._player.set_media(media)
        self._player.play()
        # self._play_btn.setText("⏸")
        self._play_btn.setIcon(pause_icon)
        self.setFocus()

    def _attach_window(self, frame=None):
        if frame is None:
            frame = self._video_frame
        frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        win_id = int(frame.winId())
        if sys.platform.startswith("linux"):
            self._player.set_xwindow(win_id)
        elif sys.platform == "win32":
            self._player.set_hwnd(win_id)
        elif sys.platform == "darwin":
            self._player.set_nsobject(win_id)

    # ── Seek / volume / UI update ────────────────────────────────

    def _on_seek_press(self):
        self._dragging_seek = True

    def _on_seek_release(self):
        length = self._player.get_length()
        if length > 0:
            self._player.set_time(int(self._seek.value() / 1000.0 * length))
        self._dragging_seek = False

    def _on_volume_change(self, val: int):
        self._player.audio_set_volume(val)
        self._vol_lbl.setText(f"{val}%")

    def _update_ui(self):
        state = self._player.get_state()
        # self._play_btn.setText(
        #     "⏸" if state == vlc.State.Playing else "▶"
        # )
        self._play_btn.setIcon(
            pause_icon if state == vlc.State.Playing else play_icon
        )
        if self._dragging_seek or self._seeking:
            return
        length = self._player.get_length()
        current = self._player.get_time()
        if length > 0 and current >= 0:
            self._seek.setValue(int(current / length * 1000))
            self._time_lbl.setText(f"{_fmt_time(current)} / {_fmt_time(length)}")

    def _save_state(self):
        if self._state_manager is None or self._current_path is None:
            return
        try:
            pos_s = max(0, self._player.get_time() // 1000)
            self._state_manager.save(PlayerState(
                series=self._current_path.name,
                season=None, episode=0, pos=pos_s,
            ))
            log.debug("State saved: %s @ %ds", self._current_path.name, pos_s)
        except Exception:
            log.exception("Failed to save player state")

    # ── Key events ───────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        """Left-click on video frame in non-fullscreen mode toggles play/pause."""
        if (not self._is_fullscreen
                and self._stack.currentIndex() == 1
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            gp = event.globalPosition().toPoint()
            vr = QRect(self._video_frame.mapToGlobal(QPoint(0, 0)),
                       self._video_frame.size())
            cr = QRect(self._controls_bar.mapToGlobal(QPoint(0, 0)),
                       self._controls_bar.size())
            if vr.contains(gp) and not cr.contains(gp):
                self.toggle_play()
        return False

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_Space:
            self.toggle_play()
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape and self._is_fullscreen:
            self._exit_fullscreen()
        elif k == Qt.Key.Key_Left:
            self.seek_relative(-_SEEK_STEP_MS)
        elif k == Qt.Key.Key_Right:
            self.seek_relative(_SEEK_STEP_MS)
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._save_state()
        self._player.stop()
        super().closeEvent(event)
