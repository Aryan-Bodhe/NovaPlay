from PyQt6.QtWidgets import QSlider, QWidget
from PyQt6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from config.player import VOL_MAX, SEEK_STEP_MS
from interface.icon_store import (
    ICON_SIZE_MEDIUM,
    ICON_SIZE_LARGE,
    play_icon, 
    pause_icon, 
    plus_icon,
    minus_icon,
    fullscreen_icon,
    audio_icon,
    mute_icon,
    subtitle_icon,
    restore_screen_icon,
    volume_icon
)
from utils.time_formatter import fmt_delay, fmt_time

class _SeekSlider(QSlider):
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


class PlayerControls(QFrame):

    play_clicked = pyqtSignal()
    seek_started = pyqtSignal()
    seek_requested = pyqtSignal(float)  # Float from 0.0 to 1.0 (ratio of the video)
    mute_clicked = pyqtSignal()
    volume_changed = pyqtSignal(int)
    sync_adjusted = pyqtSignal(int)     # Microseconds delta
    audio_menu_requested = pyqtSignal()
    sub_menu_requested = pyqtSignal()
    fullscreen_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted = False
        self._dragging_seek = False
        self._controls_bar = None
        self._build_ui()

    def _build_ui(self):
        # 1. Apply everything directly to 'self' instead of a new QFrame
        self.setObjectName("controls_bar")
        c_layout = QVBoxLayout(self)
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
        self._play_btn.setIconSize(ICON_SIZE_LARGE)
        self._play_btn.setObjectName("icon_btn")
        self._play_btn.setFixedSize(32, 32)
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.setToolTip("Play / Pause  [Space]")

        self._seek = _SeekSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setValue(0)
        self._seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        seek_row.addWidget(self._play_btn)
        seek_row.addWidget(self._seek)
        seek_row.addWidget(self._time_lbl)
        c_layout.addLayout(seek_row)

        # ── Row 2: transport controls ─────────────────────────────
        transport = QHBoxLayout()
        transport.setSpacing(6)

        self._mute_btn = QPushButton()
        self._mute_btn.setIcon(volume_icon)
        self._mute_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._mute_btn.setObjectName("icon_btn")
        self._mute_btn.setFixedSize(32, 32)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setToolTip("Mute / Unmute  [M]")

        self._vol_slider = _SeekSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, VOL_MAX)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(96)
        self._vol_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._vol_slider.setToolTip("Volume")

        self._vol_lbl = QLabel("80%")
        self._vol_lbl.setObjectName("subtitle")
        self._vol_lbl.setFixedWidth(36)

        self.sync_lbl = QLabel("A/V:")
        self.sync_lbl.setObjectName("subtitle")
        self.sync_lbl.setFixedWidth(36)

        self._sync_down_btn = QPushButton()
        self._sync_down_btn.setIcon(minus_icon)
        self._sync_down_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._sync_down_btn.setObjectName("icon_btn")
        self._sync_down_btn.setFixedSize(26, 26)
        self._sync_down_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sync_down_btn.setToolTip("Audio delay −100 ms")

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

        self._fs_btn = QPushButton()
        self._fs_btn.setIcon(fullscreen_icon)
        self._fs_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._fs_btn.setObjectName("icon_btn")
        self._fs_btn.setFixedSize(36, 32)
        self._fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fs_btn.setToolTip("Fullscreen  [F]")

        self._audio_btn = QPushButton()
        self._audio_btn.setIcon(audio_icon)
        self._audio_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._audio_btn.setObjectName("icon_btn")
        self._audio_btn.setToolTip("Select audio track")
        self._audio_btn.setFixedHeight(26)
        self._audio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._sub_btn = QPushButton()
        self._sub_btn.setIcon(subtitle_icon)
        self._sub_btn.setIconSize(ICON_SIZE_MEDIUM)
        self._sub_btn.setObjectName("icon_btn")
        self._sub_btn.setToolTip("Select subtitle track")
        self._sub_btn.setFixedHeight(26)
        self._sub_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        transport.addWidget(self._mute_btn)
        transport.addWidget(self._vol_slider)
        transport.addWidget(self._vol_lbl)

        transport.addWidget(self._sync_down_btn)
        transport.addWidget(self._sync_lbl)
        transport.addWidget(self._sync_up_btn)

        transport.addStretch()
        
        transport.addWidget(self._audio_btn)
        transport.addWidget(self._sub_btn)
        transport.addWidget(self._fs_btn)

        c_layout.addLayout(transport)

        # 2. Wire up all the internal UI events to emit your class signals
        self._play_btn.clicked.connect(self.play_clicked.emit)
        self._mute_btn.clicked.connect(self.mute_clicked.emit)
        self._fs_btn.clicked.connect(self.fullscreen_clicked.emit)
        self._audio_btn.clicked.connect(self.audio_menu_requested.emit)
        self._sub_btn.clicked.connect(self.sub_menu_requested.emit)

        # Sync buttons (assuming 100ms adjustments based on the tooltips)
        self._sync_up_btn.clicked.connect(lambda: self.sync_adjusted.emit(100000))
        self._sync_down_btn.clicked.connect(lambda: self.sync_adjusted.emit(-100000))

        # Wire up the sliders to the internal handlers you already wrote
        self._seek.sliderPressed.connect(self._on_seek_pressed)
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._vol_slider.valueChanged.connect(self._on_internal_volume_changed)

    # ── Internal Handlers ──────────────────────────────────────────

    def _on_seek_pressed(self):
        self._dragging_seek = True
        self.seek_started.emit()

    def _on_seek_released(self):
        self._dragging_seek = False
        
        # Calculate the exact ratio based on the dynamic maximum
        # (Using max(1, ...) to prevent division by zero errors on empty files)
        ratio = self._seek.value() / max(1, self._seek.maximum())
        
        self.seek_requested.emit(ratio)

    def _on_internal_volume_changed(self, val: int):
        self._vol_lbl.setText(f"{val}%")
        self.volume_changed.emit(val)

    # ── Public API (Incoming from Orchestrator) ───────────────────

    def set_playing_state(self, is_playing: bool):
        self._play_btn.setIcon(pause_icon if is_playing else play_icon)

    def update_time(self, current_ms: int, length_ms: int):
        if self._dragging_seek:
            return  # Don't rubber-band the slider if the user is holding it
        
        if length_ms > 0:
            # Dynamically set the slider's maximum to the actual video length in milliseconds
            if self._seek.maximum() != length_ms:
                self._seek.setMaximum(length_ms)
            
            self._seek.blockSignals(True)
            self._seek.setValue(current_ms)  # Now we can map the exact millisecond!
            self._seek.blockSignals(False)
            
        self._time_lbl.setText(f"{fmt_time(current_ms)} / {fmt_time(length_ms)}")

    def set_volume(self, val: int):
        """Update volume visually without emitting signals back to the controller."""
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(val)
        self._vol_slider.blockSignals(False)
        self._vol_lbl.setText(f"{val}%")

    def set_muted_state(self, is_muted: bool):
        self._mute_btn.setIcon(mute_icon if is_muted else volume_icon)

    def update_sync_label(self, delay_us: int):
        self._sync_lbl.setText(fmt_delay(delay_us))
        
    def set_fullscreen_state(self, is_fullscreen: bool):
        self._fs_btn.setIcon(restore_screen_icon if is_fullscreen else fullscreen_icon)
        
    def get_audio_button(self) -> QPushButton:
        return self._audio_btn
        
    def get_subtitle_button(self) -> QPushButton:
        return self._sub_btn

