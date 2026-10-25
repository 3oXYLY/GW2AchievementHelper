from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .common import AppContext, emblem_pixmap, muted_label

MILESTONE_STEP = 500
MILESTONE_COUNT = 5


class HeaderBar(QWidget):
    def __init__(self, ctx: AppContext, on_sync, on_settings):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("header")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(14)

        self.emblem = QLabel()
        self.emblem.setFixedSize(48, 48)
        lay.addWidget(self.emblem)
        self.ap = QLabel("—")
        self.ap.setObjectName("apValue")
        self.ap.setToolTip("Total achievement points (permanent + daily)")
        lay.addWidget(self.ap)
        lay.addSpacing(26)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.addWidget(muted_label("Points to next reward:"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.milestones = []
        for _ in range(MILESTONE_COUNT):
            lbl = QLabel("—")
            lbl.setObjectName("milestone")
            lbl.setAlignment(Qt.AlignCenter)
            self.milestones.append(lbl)
            row.addWidget(lbl)
        row.addStretch(1)
        mid.addLayout(row)
        prow = QHBoxLayout()
        self.next_bar = QProgressBar()
        self.next_bar.setRange(0, MILESTONE_STEP)
        self.next_bar.setTextVisible(False)
        self.next_bar.setFixedSize(220, 6)
        self.next_lbl = muted_label("")
        prow.addWidget(self.next_bar)
        prow.addWidget(self.next_lbl)
        prow.addStretch(1)
        mid.addLayout(prow)
        lay.addLayout(mid)
        lay.addStretch(1)

        who = QVBoxLayout()
        who.setSpacing(2)
        self.account = QLabel("No account connected")
        self.account.setProperty("account", True)
        self.account.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.info = muted_label("")
        self.info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        who.addWidget(self.account)
        who.addWidget(self.info)
        lay.addLayout(who)
        self.sync_btn = QPushButton("Sync now")
        self.sync_btn.setProperty("primary", True)
        self.sync_btn.clicked.connect(lambda: on_sync())
        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.clicked.connect(on_settings)
        lay.addWidget(self.sync_btn)
        lay.addWidget(self.settings_btn)
        self.theme_changed()

    def theme_changed(self) -> None:
        self.emblem.setPixmap(emblem_pixmap(48))

    def set_points(self, total: int | None) -> None:
        if total is None:
            self.ap.setText("—")
            for lbl in self.milestones:
                lbl.setText("—")
            self.next_bar.setValue(0)
            self.next_lbl.setText("")
            return
        self.ap.setText(f"{total:,}")
        nxt = (total // MILESTONE_STEP + 1) * MILESTONE_STEP
        for i, lbl in enumerate(self.milestones):
            lbl.setText(f"{nxt + i * MILESTONE_STEP:,}")
            lbl.setProperty("next", i == 0)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        self.next_bar.setValue(MILESTONE_STEP - (nxt - total))
        self.next_lbl.setText(f"{nxt - total:,} to go")

    def set_account(self, name: str | None, info: str) -> None:
        self.account.setText(name or "No account connected")
        self.info.setText(info)

    def set_busy(self, busy: bool) -> None:
        self.sync_btn.setEnabled(not busy)
        self.sync_btn.setText("Syncing…" if busy else "Sync now")
