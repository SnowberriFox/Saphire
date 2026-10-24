"""The patch notes window: CHANGELOG sections since the version you last saw."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextBrowser,
                               QVBoxLayout)

from sapphire import __version__, patchnotes
from sapphire.ui import theme


class PatchNotesDialog(QDialog):
    def __init__(self, parent, manager, seen: str = ""):
        super().__init__(parent)
        self.mgr = manager
        notes = patchnotes.notes_between(patchnotes.changelog_text(), seen)
        newer = len(notes) > 1
        self.setWindowTitle(f"What's new in Sapphire {__version__}")
        self.resize(theme.px(640), theme.px(620))
        lay = QVBoxLayout(self)
        title = QLabel(f"What's new in Sapphire {__version__}")
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        if newer:
            sub = QLabel(f"Everything since {seen}, newest first.")
            sub.setObjectName("Muted")
            lay.addWidget(sub)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        if notes:
            md = "\n\n".join((f"## {h}\n\n{b}" if newer else b) for h, b in notes)
        else:
            md = "No patch notes came with this version."
        view.document().setDefaultStyleSheet("h2 { margin-top: 18px; } h3 { margin-top: 10px; } "
                                              "li { margin-bottom: 5px; }")
        view.document().setDocumentMargin(theme.px(10))
        view.setMarkdown(md)
        lay.addWidget(view, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Show patch notes"))
        self.mode = QComboBox()
        for key, label in patchnotes.MODES.items():
            self.mode.addItem(label, key)
        cur = manager.lib.settings.patch_notes
        self.mode.setCurrentIndex(max(0, list(patchnotes.MODES).index(cur) if cur in patchnotes.MODES else 0))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        bottom.addWidget(self.mode)
        bottom.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        bottom.addWidget(box)
        lay.addLayout(bottom)

    def _mode_changed(self):
        self.mgr.lib.settings.patch_notes = self.mode.currentData()
        self.mgr.lib.save()
