from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QPushButton,
    QLabel, QFrame, QSizePolicy, QAbstractItemView, QFileDialog,
    QStyledItemDelegate, QStyleOptionViewItem,
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QEvent, QRect, QRectF

from config.config import VIDEO_EXT
from core.scanner import scan_series
from utils.logger import get_logger
from interface.icon_store import (
    ICON_SIZE,
    new_folder_icon,
    refresh_icon,
    trash_icon,
    pin_icon,
    pinned_icon,
)

log = get_logger("file_explorer")

EXPANDED_WIDTH = 300
COLLAPSED_WIDTH = 44

# ── Item data roles ───────────────────────────────────────────────
ROLE_PATH = Qt.ItemDataRole.UserRole + 1
ROLE_TYPE = Qt.ItemDataRole.UserRole + 2  # "file" | "series" | "season" | "dir"

# ── Unicode icons ─────────────────────────────────────────────────
ICON_SERIES  = "📺"
ICON_SEASON  = "🗂"
ICON_EPISODE = "▶"
ICON_MOVIE   = "🎬"
ICON_FOLDER  = "📁"


class ScanWorker(QThread):
    """Background thread that scans all watch directories."""
    done = pyqtSignal(object)

    def __init__(self, watch_dirs: list[str]):
        super().__init__()
        self._dirs = watch_dirs

    def run(self):
        results = []
        for d in self._dirs:
            root = Path(d)
            if not root.exists():
                log.warning("Watch directory not found: %s", root)
                continue
            try:
                results.append(self._scan_dir(root))
            except Exception:
                log.exception("Error scanning directory: %s", root)
        self.done.emit(results)

    def _scan_dir(self, root: Path) -> dict:
        children = []
        for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name.startswith("."):
                continue
            if item.is_file() and item.suffix.lower() in VIDEO_EXT:
                children.append({"type": "movie", "name": item.name, "path": item})
            elif item.is_dir():
                node = self._classify_dir(item)
                if node:
                    children.append(node)
        return {"type": "watch_root", "name": root.name, "path": root, "children": children}

    def _classify_dir(self, d: Path) -> dict | None:
        try:
            series = scan_series(d)
            if series.seasons:
                seasons = []
                for s in series.seasons:
                    eps = [
                        {"type": "episode", "name": ep.path.name,
                         "path": ep.path, "ep_no": ep.episode_no}
                        for ep in s.episodes
                    ]
                    seasons.append({
                        "type": "season", "name": f"Season {s.season_no}",
                        "path": s.path, "episodes": eps,
                    })
                return {"type": "series", "name": d.name, "path": d, "seasons": seasons}
        except Exception:
            pass

        children = []
        try:
            for item in sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if item.name.startswith("."):
                    continue
                if item.is_file() and item.suffix.lower() in VIDEO_EXT:
                    children.append({"type": "movie", "name": item.name, "path": item})
                elif item.is_dir():
                    node = self._classify_dir(item)
                    if node:
                        children.append(node)
        except Exception:
            log.exception("Error listing directory: %s", d)

        if children:
            return {"type": "dir", "name": d.name, "path": d, "children": children}
        return None


class RootFolderDelegate(QStyledItemDelegate):
    """
    Delegate for root watch-dir rows.

    On hover: shows [pin] [trash] icons on the right with a highlight background
    when the cursor is directly over each icon.
    When a folder is pinned: pin icon stays visible even when not hovered.
    Text area is always shortened to avoid overlapping the icon area.
    """

    remove_requested = pyqtSignal(str)   # path_str
    pin_toggled      = pyqtSignal(str)   # path_str

    _ICON_W   = 14   # px, each icon
    _GAP      = 10   # px between pin and trash icons
    _MARGIN   = 6    # px from the right edge of the cell
    _PAD      = 3    # extra padding around icon for the highlight rect
    # total pixels reserved on the right for both icons, always:
    _RESERVE  = _MARGIN + _ICON_W + _GAP + _ICON_W + 6   # +6 left breathing room

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered_row  = -1
        self._hovered_icon = ""   # "" | "pin" | "trash"
        self._pinned: set[str] = set()

    def set_hovered_row(self, row: int) -> None:
        self._hovered_row = row

    def set_hovered_icon(self, icon: str) -> None:
        self._hovered_icon = icon

    def set_pinned(self, pinned: set[str]) -> None:
        self._pinned = pinned

    # ── helpers ──────────────────────────────────────────────────────

    def _trash_rect(self, cell_rect) -> QRect:
        x = cell_rect.right() - self._ICON_W - self._MARGIN
        y = cell_rect.center().y() - self._ICON_W // 2
        return QRect(x, y, self._ICON_W, self._ICON_W)

    def _pin_rect(self, cell_rect) -> QRect:
        x = cell_rect.right() - self._ICON_W - self._MARGIN - self._GAP - self._ICON_W
        y = cell_rect.center().y() - self._ICON_W // 2
        return QRect(x, y, self._ICON_W, self._ICON_W)

    def _is_root(self, index) -> bool:
        return index.isValid() and not index.parent().isValid()

    def _path_str(self, index) -> str:
        return str(index.data(ROLE_PATH) or "")

    def _draw_highlight(self, painter, icon_rect: QRect) -> None:
        """Paint a subtle rounded-rect background behind an icon."""
        r = icon_rect.adjusted(-self._PAD, -self._PAD, self._PAD, self._PAD)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#3a3a60"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(r), 4.0, 4.0)
        painter.restore()

    # ── painting ─────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        if self._is_root(index):
            # Always trim the text rect — text can never reach the icon area
            opt = QStyleOptionViewItem(option)
            opt.rect = option.rect.adjusted(0, 0, -self._RESERVE, 0)
            super().paint(painter, opt, index)

            is_hovered = (index.row() == self._hovered_row)
            is_pinned  = self._path_str(index) in self._pinned

            if is_hovered:
                trash_r  = self._trash_rect(option.rect)
                pin_r    = self._pin_rect(option.rect)
                cur_pin  = pinned_icon if is_pinned else pin_icon
                # Draw highlight behind whichever icon the cursor is over
                if self._hovered_icon == "trash":
                    self._draw_highlight(painter, trash_r)
                elif self._hovered_icon == "pin":
                    self._draw_highlight(painter, pin_r)
                trash_icon.paint(painter, trash_r)
                cur_pin.paint(  painter, pin_r)
            elif is_pinned:
                pinned_icon.paint(painter, self._pin_rect(option.rect))
        else:
            super().paint(painter, option, index)

    # ── click handling ───────────────────────────────────────────────

    def editorEvent(self, event, model, option, index):
        if not self._is_root(index) or index.row() != self._hovered_row:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            pos  = event.position().toPoint()
            path = self._path_str(index)
            if self._trash_rect(option.rect).contains(pos):
                if path:
                    self.remove_requested.emit(path)
                return True
            if self._pin_rect(option.rect).contains(pos):
                if path:
                    self.pin_toggled.emit(path)
                return True
        return False


class FileExplorerPanel(QWidget):
    """Collapsible left-sidebar file explorer."""

    file_selected = pyqtSignal(Path)
    dirs_changed  = pyqtSignal(list)

    def __init__(self, watch_dirs: list[str], settings_manager, parent=None):
        super().__init__(parent)
        self._watch_dirs    = list(watch_dirs)
        self._settings_manager = settings_manager
        self._scan_worker: ScanWorker | None = None

        settings = self._settings_manager.load()
        self._pinned_dirs: list[str] = list(settings.pinned_dirs)

        self.setObjectName("explorer_panel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self.refresh()

    # ── UI construction ───────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        self._header = QFrame()
        self._header.setFixedHeight(48)
        self._header.setObjectName("sidebar_header")

        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(10, 0, 8, 0)
        h_layout.setSpacing(4)

        self._title_lbl = QLabel("LIBRARY")
        self._title_lbl.setObjectName("title")
        h_layout.addWidget(self._title_lbl)
        h_layout.addStretch()

        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(refresh_icon)
        self._refresh_btn.setIconSize(ICON_SIZE)
        self._refresh_btn.setObjectName("icon_btn")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh library")
        self._refresh_btn.clicked.connect(self.refresh)

        self._add_dir_btn = QPushButton()
        self._add_dir_btn.setIcon(new_folder_icon)
        self._add_dir_btn.setIconSize(ICON_SIZE)
        self._add_dir_btn.setObjectName("icon_btn")
        self._add_dir_btn.setFixedSize(32, 28)
        self._add_dir_btn.setToolTip("Add watch directory")
        self._add_dir_btn.clicked.connect(self._add_directory)

        h_layout.addWidget(self._refresh_btn)
        h_layout.addWidget(self._add_dir_btn)

        layout.addWidget(self._header)

        # ── Status label ──────────────────────────────────────────
        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setObjectName("subtitle")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setVisible(False)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._status_lbl)

        # ── Tree ──────────────────────────────────────────────────
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels([""])

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setUniformRowHeights(False)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.clicked.connect(self._on_click)

        # Hover-only trash icon via delegate
        self._delegate = RootFolderDelegate(self)
        self._delegate.remove_requested.connect(self._remove_directory)
        self._delegate.pin_toggled.connect(self._toggle_pin)
        self._delegate.set_pinned(set(self._pinned_dirs))
        self._tree.setItemDelegateForColumn(0, self._delegate)
        self._tree.viewport().setMouseTracking(True)
        self._tree.viewport().installEventFilter(self)

        layout.addWidget(self._tree)

    # ── Public API ────────────────────────────────────────────────

    def set_watch_dirs(self, dirs: list[str]):
        self._watch_dirs = dirs
        self.refresh()

    def refresh(self):
        if self._scan_worker and self._scan_worker.isRunning():
            return

        self._model.clear()
        self._model.setHorizontalHeaderLabels([""])

        if not self._watch_dirs:
            self._status_lbl.setText("No watch directories.\nClick 📁+ to add one.")
            self._status_lbl.setVisible(True)
            return

        self._status_lbl.setText("Scanning…")
        self._status_lbl.setVisible(True)
        self._scan_worker = ScanWorker(self._watch_dirs)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def eventFilter(self, obj, event):
        if obj is self._tree.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos   = event.position().toPoint()
                index = self._tree.indexAt(pos)
                if index.isValid() and not index.parent().isValid():
                    row       = index.row()
                    cell_rect = self._tree.visualRect(index)
                    if self._delegate._trash_rect(cell_rect).contains(pos):
                        icon = "trash"
                    elif self._delegate._pin_rect(cell_rect).contains(pos):
                        icon = "pin"
                    else:
                        icon = ""
                else:
                    row  = -1
                    icon = ""

                changed = (row  != self._delegate._hovered_row or
                           icon != self._delegate._hovered_icon)
                if changed:
                    self._delegate.set_hovered_row(row)
                    self._delegate.set_hovered_icon(icon)
                    self._tree.viewport().update()

            elif event.type() == QEvent.Type.Leave:
                if self._delegate._hovered_row != -1 or self._delegate._hovered_icon:
                    self._delegate.set_hovered_row(-1)
                    self._delegate.set_hovered_icon("")
                    self._tree.viewport().update()
        return super().eventFilter(obj, event)

    # ── Slots ─────────────────────────────────────────────────────

    @pyqtSlot(object)
    def _on_scan_done(self, results: list[dict]):
        self._status_lbl.setVisible(False)
        self._model.clear()
        self._model.setHorizontalHeaderLabels([""])

        # Sort: pinned dirs first (in pin order), then the rest
        pinned_set = set(self._pinned_dirs)
        def _sort_key(r):
            p = str(r["path"])
            if p in pinned_set:
                try:
                    return (0, self._pinned_dirs.index(p))
                except ValueError:
                    pass
            return (1, 0)
        results.sort(key=_sort_key)

        for root_data in results:
            root_item = self._make_item(
                root_data["name"], ICON_FOLDER, root_data["path"], "dir"
            )
            self._populate_item(root_item, root_data.get("children", []))
            self._model.appendRow(root_item)

        log.info("Library scan complete – %d root(s) loaded", len(results))

    def _populate_item(self, parent_item: QStandardItem, children: list[dict]):
        for node in children:
            t = node["type"]
            if t == "series":
                item = self._make_item(node["name"], ICON_SERIES, node["path"], "series")
                for season in node["seasons"]:
                    s_item = self._make_item(
                        season["name"], ICON_SEASON, season["path"], "season"
                    )
                    for ep in season["episodes"]:
                        e_item = self._make_item(
                            ep["name"], ICON_EPISODE, ep["path"], "file"
                        )
                        s_item.appendRow(e_item)
                    item.appendRow(s_item)
                parent_item.appendRow(item)

            elif t in ("movie", "episode"):
                item = self._make_item(node["name"], ICON_MOVIE, node["path"], "file")
                parent_item.appendRow(item)

            elif t in ("dir", "watch_root"):
                item = self._make_item(node["name"], ICON_FOLDER, node["path"], "dir")
                self._populate_item(item, node.get("children", []))
                parent_item.appendRow(item)

    def _make_item(self, name: str, icon: str, path: Path, item_type: str) -> QStandardItem:
        item = QStandardItem(f"  {icon}  {name}")
        item.setData(path, ROLE_PATH)
        item.setData(item_type, ROLE_TYPE)
        item.setEditable(False)
        return item

    def _on_click(self, index):
        """Single-click: play files, toggle expand/collapse for folders."""
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        item_type = item.data(ROLE_TYPE)
        path: Path = item.data(ROLE_PATH)

        if item_type == "file":
            if path and path.exists():
                log.info("File selected: %s", path)
                self.file_selected.emit(path)
            else:
                log.warning("Selected file not found: %s", path)
        else:
            # Toggle expand/collapse for dirs/series/seasons
            if self._tree.isExpanded(index):
                self._tree.collapse(index)
            else:
                self._tree.expand(index)

    def _add_directory(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Watch Directory", str(Path.home())
        )
        if path and path not in self._watch_dirs:
            self._watch_dirs.append(path)
            settings = self._settings_manager.load()
            settings.watch_dirs = self._watch_dirs
            self._settings_manager.save(settings)
            self.dirs_changed.emit(self._watch_dirs)
            self.refresh()
            log.info("Added watch directory: %s", path)

    def _toggle_pin(self, path_str: str):
        if path_str in self._pinned_dirs:
            self._pinned_dirs.remove(path_str)
        else:
            self._pinned_dirs.append(path_str)   # oldest pin stays highest
        settings = self._settings_manager.load()
        settings.pinned_dirs = self._pinned_dirs
        self._settings_manager.save(settings)
        self._delegate.set_pinned(set(self._pinned_dirs))
        self.refresh()
        log.info("Pin toggled for directory: %s", path_str)

    def _remove_directory(self, path_str: str):
        if path_str in self._watch_dirs:
            self._watch_dirs.remove(path_str)
        if path_str in self._pinned_dirs:
            self._pinned_dirs.remove(path_str)
        settings = self._settings_manager.load()
        settings.watch_dirs  = self._watch_dirs
        settings.pinned_dirs = self._pinned_dirs
        self._settings_manager.save(settings)
        self._delegate.set_pinned(set(self._pinned_dirs))
        self.dirs_changed.emit(self._watch_dirs)
        self.refresh()
        log.info("Removed watch directory: %s", path_str)
