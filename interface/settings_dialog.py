from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QLabel, QDialogButtonBox
)
from PyQt6.QtCore import Qt


class SettingsDialog(QDialog):
    """Dialog for managing watch directories."""

    def __init__(self, watch_dirs: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watch Directories")
        self.setMinimumSize(520, 380)
        self.setModal(True)

        self._dirs = list(watch_dirs)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Watch Directories")
        header.setObjectName("title")
        layout.addWidget(header)

        desc = QLabel(
            "NovaPlay will scan these directories for series and movies."
        )
        desc.setObjectName("subtitle")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.list_widget = QListWidget()
        for d in self._dirs:
            self.list_widget.addItem(QListWidgetItem(d))
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("+ Add Directory")
        add_btn.setObjectName("accent")
        add_btn.clicked.connect(self._add_dir)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _add_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Watch Directory", str(__import__("pathlib").Path.home())
        )
        if path and path not in self._dirs:
            self._dirs.append(path)
            self.list_widget.addItem(QListWidgetItem(path))

    def _remove_selected(self):
        for item in self.list_widget.selectedItems():
            self._dirs.remove(item.text())
            self.list_widget.takeItem(self.list_widget.row(item))

    def get_dirs(self) -> list[str]:
        return list(self._dirs)
