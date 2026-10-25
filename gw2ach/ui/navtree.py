from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

from .common import AppContext

SCOPE_ROLE = Qt.UserRole + 20
FIXED = (("summary", "☰   Summary"), ("tracked", "★   Watch List"), ("near", "◐   Nearly Completed"),
         ("all", "▦   All Achievements"))


def scope_key(scope: dict) -> tuple:
    return scope.get("kind"), scope.get("value")


class CategoryTree(QTreeWidget):
    scope_selected = Signal(dict)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("categories")
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        head = self.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        head.resizeSection(1, 64)
        self.itemClicked.connect(self._clicked)
        self.currentItemChanged.connect(lambda cur, _prev: cur and self._emit(cur))
        self._items: dict[tuple, QTreeWidgetItem] = {}
        self._emitting = True

    def _emit(self, item: QTreeWidgetItem) -> None:
        if self._emitting:
            scope = item.data(0, SCOPE_ROLE)
            if scope:
                self.scope_selected.emit(dict(scope))

    def _clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        scope = item.data(0, SCOPE_ROLE) or {}
        if scope.get("kind") == "group" and item.childCount():
            item.setExpanded(not item.isExpanded())

    def _item(self, parent, text: str, extra: str, scope: dict, bold: bool = False, serif: bool = False):
        item = QTreeWidgetItem([text, extra])
        item.setData(0, SCOPE_ROLE, scope)
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setForeground(1, QColor(self.ctx.c["muted"]))
        if bold or serif:
            font = QFont(self.ctx.c.get("serif") or self.font().family()) if serif else QFont(self.font())
            font.setPointSize(10 if not serif else 11)
            font.setBold(bold)
            item.setFont(0, font)
        if parent is None:
            self.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self._items[scope_key(scope)] = item
        return item

    def populate(self, data: dict, counts: dict) -> None:
        current = self.currentItem()
        current_key = scope_key(current.data(0, SCOPE_ROLE)) if current else ("summary", None)
        expanded = {key for key, item in self._items.items() if item.isExpanded()}
        self._emitting = False
        self.clear()
        self._items = {}
        totals = data.get("totals", {})
        extras = {"tracked": f"{counts.get('tracked', 0):,}", "near": f"{counts.get('near', 0):,}",
                  "all": f"{totals.get('total', 0):,}", "summary": ""}
        for kind, label in FIXED:
            self._item(None, label, extras[kind], {"kind": kind, "value": None, "title": label.split("   ", 1)[1]},
                       bold=True)
        for g in data.get("groups", []):
            pct = round(g["done"] * 100 / g["total"]) if g["total"] else 0
            gi = self._item(None, g["name"], f"{pct}%", {"kind": "group", "value": g["name"], "title": g["name"]},
                            bold=True, serif=True)
            for c in g["categories"]:
                cpct = round(c["done"] * 100 / c["total"]) if c["total"] else 0
                self._item(gi, c["name"], f"{cpct}%",
                           {"kind": "category", "value": c["id"], "title": f"{g['name']}  ›  {c['name']}"})
            gi.setExpanded(("group", g["name"]) in expanded)
        target = self._items.get(current_key) or self._items.get(("summary", None))
        if target:
            self.setCurrentItem(target)
        self._emitting = True

    def update_counts(self, counts: dict) -> None:
        for kind in ("tracked", "near"):
            item = self._items.get((kind, None))
            if item:
                item.setText(1, f"{counts.get(kind, 0):,}")

    def select(self, kind: str, value=None) -> None:
        item = self._items.get((kind, value))
        if item is None:
            return
        if item.parent():
            item.parent().setExpanded(True)
        if self.currentItem() is item:
            self._emit(item)
        else:
            self.setCurrentItem(item)
        self.scrollToItem(item)

    def current_scope(self) -> dict:
        item = self.currentItem()
        return dict(item.data(0, SCOPE_ROLE)) if item else {"kind": "summary", "value": None, "title": "Summary"}
