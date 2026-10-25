from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import model
from .common import (PCT_ROLE, STATUS_ROLE, AppContext, ProgressDelegate, heading_label, muted_label,
                     new_dialog)
from .tiles import tile_view


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("section", True)
    return lbl


def panel() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("panel", True)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    return frame, lay


class SummaryPage(QWidget):
    open_achievement = Signal(int)
    open_scope = Signal(str)

    def __init__(self, ctx: AppContext, icon_for):
        super().__init__()
        self.ctx = ctx
        self.icon_for = icon_for
        self._data = None
        self._daily = None
        self._monthly = None
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        title = QLabel("Summary")
        title.setProperty("title", True)
        lay.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(12)
        recent, rl = panel()
        rl.addWidget(section_label("Recently Completed:"))
        self.recent_list, self.recent_model, _ = tile_view(self.ctx, self.icon_for)
        self.recent_list.clicked.connect(lambda idx: self.open_achievement.emit(self.recent_model.rows[idx.row()]["id"]))
        rl.addWidget(self.recent_list, 1)
        self.recent_empty = muted_label("Achievements you finish show up here after your next syncs. "
                                        "(The API doesn't say when something was finished, so the tool notices "
                                        "it between syncs.)", wrap=True)
        rl.addWidget(self.recent_empty)
        top.addWidget(recent, 1)

        nearly, nl = panel()
        head = QHBoxLayout()
        head.addWidget(section_label("Nearly Completed:"))
        head.addStretch(1)
        more = QPushButton("Show all")
        more.setProperty("chip", True)
        more.clicked.connect(lambda: self.open_scope.emit("near"))
        head.addWidget(more)
        nl.addLayout(head)
        self.near_list, self.near_model, _ = tile_view(self.ctx, self.icon_for)
        self.near_list.clicked.connect(lambda idx: self.open_achievement.emit(self.near_model.rows[idx.row()]["id"]))
        nl.addWidget(self.near_list, 1)
        self.near_empty = muted_label("Nothing at 80% or more right now.", wrap=True)
        nl.addWidget(self.near_empty)
        top.addWidget(nearly, 1)
        lay.addLayout(top, 3)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        mastery, ml = panel()
        ml.addWidget(section_label("Mastery Points:"))
        self.mastery = QTreeWidget()
        self.mastery.setHeaderLabels(["Region", "Earned", "Completion"])
        self.mastery.setRootIsDecorated(False)
        self.mastery.setAlternatingRowColors(True)
        mh = self.mastery.header()
        mh.setStretchLastSection(False)
        mh.setSectionResizeMode(0, QHeaderView.Stretch)
        mh.setSectionResizeMode(1, QHeaderView.Fixed)
        mh.resizeSection(1, 80)
        mh.setSectionResizeMode(2, QHeaderView.Fixed)
        mh.resizeSection(2, 140)
        self.mastery.setItemDelegateForColumn(2, ProgressDelegate(self.ctx, self.mastery))
        ml.addWidget(self.mastery, 1)
        bottom.addWidget(mastery, 1)

        account, al = panel()
        al.addWidget(section_label("Achievement Points:"))
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(7)
        self.values = {}
        for key, label in (("permanent", "Permanent"), ("daily", "Daily"), ("total", "Total"),
                           ("next", "Next reward"), ("done", "Achievements done"),
                           ("watch", "Watch list"), ("near", "Nearly completed (80%+)")):
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.values[key] = value
            self.form.addRow(muted_label(label), value)
        al.addLayout(self.form)
        al.addStretch(1)
        buttons = QHBoxLayout()
        details = QPushButton("Points details")
        details.clicked.connect(self.show_ap_details)
        watch = QPushButton("Open watch list")
        watch.clicked.connect(lambda: self.open_scope.emit("tracked"))
        buttons.addWidget(details)
        buttons.addWidget(watch)
        buttons.addStretch(1)
        al.addLayout(buttons)
        bottom.addWidget(account, 1)
        lay.addLayout(bottom, 2)

    @staticmethod
    def _bar(item: QTreeWidgetItem, col: int, done: int, total: int) -> None:
        pct = done / total if total else 0.0
        item.setText(col, f"{round(pct * 100)}%")
        item.setData(col, PCT_ROLE, pct)
        item.setData(col, STATUS_ROLE, "done" if total and done >= total else "progress")
        item.setTextAlignment(col, Qt.AlignCenter)

    def refresh(self, data: dict, daily: int | None, monthly: int | None, counts: dict) -> None:
        storage = self.ctx.storage
        self._data, self._daily, self._monthly = data, daily, monthly
        recent_ids = storage.recent_completions(6)
        rows, _ = storage.search(ids=recent_ids, include_uncategorized=True)
        self.recent_model.set_rows([model.display_row(r) for r in rows])
        self.recent_empty.setVisible(not rows)
        self.recent_list.setVisible(bool(rows))
        near, _ = storage.search(view="near", limit=6)
        self.near_model.set_rows([model.display_row(r) for r in near])
        self.near_empty.setVisible(not near)
        self.near_list.setVisible(bool(near))
        self.ctx.icons.want([r.get("icon") or r.get("category_icon") for r in rows + near])

        t = data["totals"]
        permanent = t["earned_all"]
        periodic = (daily or 0) + (monthly or 0)
        total = permanent + periodic
        self.values["permanent"].setText(f"{permanent:,}")
        if daily is None and monthly is None:
            hint = ("press Sync to load it" if not storage.get_setting("account_ap_checked")
                    else "not sent by the API")
            self.values["daily"].setText(hint)
        else:
            self.values["daily"].setText(f"{periodic:,}")
        self.values["total"].setText(f"{total:,}")
        nxt = (total // 500 + 1) * 500
        self.values["next"].setText(f"{nxt:,}  ({nxt - total:,} to go)")
        pct = round(t["done"] * 100 / t["total"]) if t["total"] else 0
        self.values["done"].setText(f"{t['done']:,} / {t['total']:,}  ({pct}%)")
        self.values["watch"].setText(f"{counts.get('tracked', 0):,}")
        self.values["near"].setText(f"{counts.get('near', 0):,}")

        self.mastery.clear()
        for m in data["mastery"]:
            mi = QTreeWidgetItem([m["region"], f"{m['earned']} / {m['available']}", ""])
            mi.setTextAlignment(1, Qt.AlignCenter)
            self._bar(mi, 2, m["earned"], m["available"])
            self.mastery.addTopLevelItem(mi)

    def icons_updated(self) -> None:
        self.recent_model.refresh_all()
        self.near_model.refresh_all()

    def show_ap_details(self) -> None:
        if not self._data:
            return
        ap = self._data["ap"]
        daily, monthly = self._daily, self._monthly
        dlg, lay = new_dialog(self, "Achievement points details", 560)
        lay.addWidget(heading_label("Where the points come from"))
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(6)
        rows = [("Permanent achievements", f"{ap['permanent']:,}"),
                ("Repeatable achievements", f"{ap['repeatable']:,}  ({ap['repeatable_count']} with progress)"),
                ("Permanent total", f"{self._data['totals']['earned_all']:,}"),
                ("Daily AP (from your account)", "missing" if daily is None else f"{daily:,}"),
                ("Monthly AP (from your account)", "missing" if monthly is None else f"{monthly:,}")]
        for k, v in rows:
            value = QLabel(v)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(muted_label(k), value)
        lay.addLayout(form)
        lay.addWidget(muted_label(
            "Compare with the game: hover the points number in the Achievements panel (Hero panel, H). "
            "'Permanent' there should match 'Permanent total' here, and 'Daily' should match daily + monthly. "
            "Copy details lists every repeatable and daily-type achievement on your account, which helps "
            "find any difference. It contains no API key.", wrap=True))
        buttons = QHBoxLayout()
        copy = QPushButton("Copy details")

        def do_copy():
            QGuiApplication.clipboard().setText(model.ap_details_text(ap, daily, monthly))
            copy.setText("Copied ✓")

        copy.clicked.connect(do_copy)
        close = QPushButton("Close")
        close.setProperty("primary", True)
        close.clicked.connect(dlg.accept)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        dlg.show()
        self._details_dialog = dlg
