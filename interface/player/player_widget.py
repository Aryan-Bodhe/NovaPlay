import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog, QWidget, QVBoxLayout, QFrame, QLabel, QSizePolicy, 
    QStackedWidget, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QIcon, QPalette, QColor, QFont, QAction

from config.app import STATE_FILE
from config.player import REWIND_ON_RESUME, SEEK_STEP_MS
from core.state_manager import StateManager
from models.state import PlayerState
from interface.icon_store import novaplay_icon, play_icon, pause_icon

# --- NEW IMPORTS ---
from interface.player.player_controls import PlayerControls
from core.vlc_engine import VLCEngine
from utils.logger import get_logger

log = get_logger("player")


class PlayerWidget(QWidget):
    """Orchestrator widget that binds VLCEngine to PlayerControls."""
    fullscreen_toggled = pyqtSignal(bool)

    def __init__(self, volume: int = 80, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._is_fullscreen = False
        self._current_path: Path | None = None
        self._last_played_path: Path | None = None
        self._state_manager: StateManager | None = None
        self._muted = False
        self._audio_delay_us = 0
        self._media_length_ms = 0  # Cached to calculate seeks

        self._center_state_hint: QLabel | None = None

        # 1. Initialize our decoupled components
        self.engine = VLCEngine()
        self.controls = PlayerControls(parent=self)
        
        self.engine.set_volume(volume)
        self.controls.set_volume(volume)

        # 2. Build the structural layout
        self._build_layout()

        # 3. Connect UI Signals to Engine Logic
        self._connect_signals()

        # 4. Timers for UI states
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(4000)
        self._hide_timer.timeout.connect(self._hide_controls)
        self._controls_hidden = False

        self._controls_hidden = False
        
        # Add this to track real mouse movements
        self._last_mouse_pos = QPoint() 

        # Global event filter for fullscreen mouse tracking
        QApplication.instance().installEventFilter(self)


    # ── Initialization ──────────────────────────────────────────────

    def _build_layout(self):
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Stacked Widget (0 = Blank Slate, 1 = Video Player)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._blank = self._make_blank_slate()
        self._stack.addWidget(self._blank)

        self._video_frame = QFrame()
        self._video_frame.setObjectName("video_frame")
        self._video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        pal = self._video_frame.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self._video_frame.setPalette(pal)
        self._video_frame.setAutoFillBackground(True)
        self._video_frame.mouseDoubleClickEvent = lambda e: self.toggle_fullscreen()
        
        # Ensure VLC can embed here
        self._video_frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        
        self._stack.addWidget(self._video_frame)
        self._stack.setCurrentIndex(0)

        # Add the imported controls bar to the bottom
        root.addWidget(self.controls)
        self.controls.hide()

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
        return w

    def _connect_signals(self):
        # UI -> Orchestrator/Engine
        self.controls.play_clicked.connect(self.toggle_play)
        self.controls.seek_requested.connect(self._on_ui_seek_requested)
        self.controls.volume_changed.connect(self.engine.set_volume)
        self.controls.mute_clicked.connect(self.toggle_mute)
        self.controls.sync_adjusted.connect(self._adjust_audio_delay)
        self.controls.fullscreen_clicked.connect(self.toggle_fullscreen)
        self.controls.audio_menu_requested.connect(self._show_audio_menu)
        self.controls.sub_menu_requested.connect(self._show_subtitle_menu)

        # Engine -> UI
        self.engine.time_changed.connect(self._on_engine_time_changed)
        self.engine.media_ended.connect(self.stop)


    # ── Playback API ────────────────────────────────────────────────

    def play(self, path: Path):
        is_same_file = (path == self._last_played_path)
        self._last_played_path = path
        self._current_path = path

        self._state_manager = StateManager(STATE_FILE, path.name)

        resume_ms = 0
        if is_same_file:
            state = self._state_manager.load()
            resume_ms = max(0, (state.pos - REWIND_ON_RESUME) * 1000)

        try:
            # 1. Load the media into the engine
            self.engine.load_media(path)
            self.controls._seek.setRange(0, self.engine._media_length)
            
            # 2. Bind the engine to our PyQt Frame
            self.engine.attach_window(int(self._video_frame.winId()))
            
            # 3. Swap UI and Start
            self._stack.setCurrentIndex(1)
            self.controls.show()
            self.engine.play()

            if resume_ms > 0:
                # Slight delay to let VLC parse the header before seeking
                QTimer.singleShot(800, lambda: self.engine.seek(resume_ms))

            self._audio_delay_us = 0
            self.controls.update_sync_label(0)
            self.controls.set_playing_state(True)
            
            log.info("Playing: %s (resume=%dms)", path.name, resume_ms)
        except Exception:
            log.exception("Failed to start playback: %s", path)

    def toggle_play(self, show_overlay: bool = True):
        if self.engine.is_playing():
            self.engine.pause()
            self.controls.set_playing_state(False)
            if show_overlay:
                self._show_center_state_hint(pause_icon)
            self._save_state()
        else:
            self.engine.play()
            self.controls.set_playing_state(True)
            if show_overlay:
                self._show_center_state_hint(play_icon)

    def stop(self):
        self._save_state()
        self.engine.stop()
        self.controls.set_playing_state(False)
        self.controls.update_time(0, 0)
        self._stack.setCurrentIndex(0)
        self.controls.hide()

    def toggle_mute(self):
        self._muted = not self._muted
        if self._muted:
            self.engine.mute()
        else:
            self.engine.unmute()
        self.controls.set_muted_state(self._muted)

    def _adjust_audio_delay(self, delta_us: int):
        self._audio_delay_us += delta_us
        self.engine.set_audio_delay(self._audio_delay_us // 1000) # Engine expects ms
        self.controls.update_sync_label(self._audio_delay_us)

    def get_volume(self) -> int:
        return self.engine.get_volume()


    # ── Signal Handlers ─────────────────────────────────────────────

    def _on_ui_seek_requested(self, ratio: float):
        """Called when the user drops the seek slider."""
        target_ms = int(ratio * self._media_length_ms)
        
        # Safety buffer: Prevent seeking past 500ms before the end of the file
        # to stop the FFmpeg decoder from throwing a buffer panic.
        safe_max = max(0, self._media_length_ms - 5000)
        target_ms = min(target_ms, safe_max)
        
        self.engine.seek(target_ms)

    def _on_engine_time_changed(self, current_ms: int, length_ms: int):
        """Called automatically by the engine's background thread."""
        self._media_length_ms = length_ms
        self.controls.update_time(current_ms, length_ms)

    # ── Menus ───────────────────────────────────────────────────────

    def _show_audio_menu(self):
        menu = QMenu(self)
        try:
            tracks = self.engine.get_audio_track_list()
            if not tracks:
                menu.addAction("(no audio tracks)").setEnabled(False)
            else:
                for t in tracks:
                    action = QAction(t.name, self)
                    action.triggered.connect(lambda checked, i=t.id: self.engine.set_audio_track(i))
                    menu.addAction(action)
        except Exception:
            menu.addAction("(error)").setEnabled(False)
            
        btn = self.controls.get_audio_button()
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _show_subtitle_menu(self):
        menu = QMenu(self)
        
        # 1. Add "Choose subtitle file..." as the firstmost option
        choose_file_action = QAction("Choose subtitle file...", self)
        choose_file_action.triggered.connect(self._load_external_subtitle)
        menu.addAction(choose_file_action)
        
        # Add a visual separator between the manual file picker and the built-in tracks
        menu.addSeparator()

        # 2. Append existing subtitle tracks from the engine
        try:
            subs = self.engine.get_subtitles_list()
            if subs:
                for s in subs:
                    action = QAction(s.name, self)
                    # Note: lambda checked=False, i=s.id prevents late-binding bugs in loops
                    action.triggered.connect(lambda checked=False, i=s.id: self.engine.set_subtitle(i))
                    menu.addAction(action)
            else:
                no_subs_action = menu.addAction("(No internal subtitles)")
                no_subs_action.setEnabled(False)
        except Exception:
            menu.addAction("(error loading subtitles)").setEnabled(False)
            
        btn = self.controls.get_subtitle_button()
        # Adjusted slightly: mapToGlobal might need adjustments depending on Qt version, 
        # but kept your original positioning logic.
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _load_external_subtitle(self):
        """Helper method to open a file picker and load an SRT file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Subtitle File",
            "", 
            "Subtitle Files (*.srt);;All Files (*)"
        )
        
        if file_path:
            # NOTE: Replace `load_external_subtitle` with whatever method 
            # your specific media engine uses to load an external file.
            # e.g., for VLC it might be video_set_spu(), for QtMultimedia it varies.
            self.engine.load_external_subtitle(file_path)


    # ── Fullscreen Logic ────────────────────────────────────────────

    def toggle_fullscreen(self):
        if not self._is_fullscreen:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    def _enter_fullscreen(self):
        if self._current_path is None:
            return
        self._is_fullscreen = True
        self.controls.set_fullscreen_state(True)
        self.window().showFullScreen()

        self.controls.hide()
        self._root_layout.removeWidget(self.controls)
        
        # 1. Parent to the top-level Main Window to escape the video stack
        self.controls.setParent(self.window())
        
        # 2. Force OS-level window rendering so it can compete with VLC
        self.controls.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.controls.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.controls.setStyleSheet("QFrame#controls_bar { background: rgba(0, 0, 0, 180); }")

        self.controls.show()
        self.controls.raise_()
        self._layout_floating_controls()

        self._hide_timer.start()
        self.fullscreen_toggled.emit(True)

    def _exit_fullscreen(self):
        if self._current_path is None:
            return
        self._is_fullscreen = False
        self.controls.set_fullscreen_state(False)
        self.window().showNormal()
        self.window().unsetCursor()

        self._hide_timer.stop()
        self._controls_hidden = False
        
        self.controls.hide()
        self.controls.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)
        self.controls.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.controls.setStyleSheet("")  
        
        self._root_layout.addWidget(self.controls)
        self.controls.show()
        self.fullscreen_toggled.emit(False)

    def _layout_floating_controls(self):
        if self._is_fullscreen:
            ctrl_h = self.controls.sizeHint().height() + 12
            host = self.window()
            
            # Map our bottom-left corner to the host's coordinate system
            bottom_left_global = self.mapToGlobal(QPoint(0, self.height()))
            bottom_left_host = host.mapFromGlobal(bottom_left_global)
            
            self.controls.setGeometry(
                bottom_left_host.x(),
                bottom_left_host.y() - ctrl_h,
                self.width(),
                ctrl_h
            )
            # Force to front just in case resizing buried it
            self.controls.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_floating_controls()
    
    def _show_controls(self):
        if not self._is_fullscreen:
            return
        self._controls_hidden = False
        self.controls.show()
        
        # Force the OS to pull the UI back over the video frame
        self.controls.raise_() 
        
        self.window().unsetCursor()
        self._hide_timer.start()

    def _hide_controls(self):
        if not self._is_fullscreen:
            return
        self._controls_hidden = True
        self.controls.hide()
        self.window().setCursor(Qt.CursorShape.BlankCursor)


    # ── Keyboard & Mouse Events ─────────────────────────────────────
    def _show_center_state_hint(self, icon: QIcon):
        if self._stack.currentIndex() != 1 or self._video_frame.isHidden():
            return

        host = self.window()
        top_left = host.mapFromGlobal(self._video_frame.mapToGlobal(QPoint(0, 0)))
        target_rect = QRect(top_left, self._video_frame.size())

        # 1. Safely remove the old hint
        self._hide_center_state_hint()

        hint = QLabel(host)
        hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        # 2. IMPORTANT: Force native window so it draws over VLC on Linux/Wayland
        hint.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        
        hint.setFixedSize(84, 84)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("background: transparent;")
        hint.setPixmap(icon.pixmap(46, 46))
        
        cx = target_rect.x() + (target_rect.width() - hint.width()) // 2
        cy = target_rect.y() + (target_rect.height() - hint.height()) // 2
        hint.move(cx, cy)
        hint.show()
        hint.raise_()

        self._center_state_hint = hint
        
        # 3. Call our safe cleanup method instead of a dangling lambda
        QTimer.singleShot(550, self._hide_center_state_hint)


    def _hide_center_state_hint(self):
        """Safely delete the center hint and clear the Python reference."""
        if self._center_state_hint is not None:
            try:
                self._center_state_hint.deleteLater()
            except RuntimeError:
                pass # Already cleaned up by Qt
            self._center_state_hint = None


    def eventFilter(self, obj, event) -> bool:
        if not self.isVisible() or QApplication.activeModalWidget() is not None:
            return False

        if self._is_fullscreen and event.type() == QEvent.Type.MouseMove:
            current_pos = event.globalPosition().toPoint()
            
            # Ignore the event if the mouse hasn't actually moved across the screen
            if hasattr(self, '_last_mouse_pos') and self._last_mouse_pos == current_pos:
                return False
                
            self._last_mouse_pos = current_pos

            if self._controls_hidden:
                self._show_controls()
            else:
                self._hide_timer.start()

        if (self._stack.currentIndex() == 1 and 
            event.type() == QEvent.Type.MouseButtonPress and 
            event.button() == Qt.MouseButton.LeftButton):
            
            gp = event.globalPosition().toPoint()
            
            vr = QRect(self._video_frame.mapToGlobal(QPoint(0, 0)), self._video_frame.size()) if not self._video_frame.isHidden() else QRect()
            cr = QRect(self.controls.mapToGlobal(QPoint(0, 0)), self.controls.size()) if not self.controls.isHidden() else QRect()

            if vr.contains(gp) and not cr.contains(gp):
                self.toggle_play()
                return True
                
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
            target = max(0, self.engine.get_current_seek() - SEEK_STEP_MS)
            self.engine.seek(target)
        elif k == Qt.Key.Key_Right:
            target = min(self._media_length_ms, self.engine.get_current_seek() + SEEK_STEP_MS)
            self.engine.seek(target)
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        elif k == Qt.Key.Key_Up:
            new_vol = min(150, self.engine.get_volume() + 5)
            self.engine.set_volume(new_vol)
            self.controls.set_volume(new_vol)
        elif k == Qt.Key.Key_Down:
            new_vol = max(0, self.engine.get_volume() - 5)
            self.engine.set_volume(new_vol)
            self.controls.set_volume(new_vol)
        else:
            super().keyPressEvent(event)


    def _save_state(self):
        if self._state_manager is None or self._current_path is None:
            return
        try:
            pos_s = max(0, self.engine.get_current_seek() // 1000)
            self._state_manager.save(PlayerState(
                series=self._current_path.name,
                season=None, episode=0, pos=pos_s,
            ))
        except Exception:
            pass

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._save_state()
        self.engine.stop()
        super().closeEvent(event)