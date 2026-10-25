from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

ROW_ROLE = Qt.UserRole + 10


class TileModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self.row_of: dict[int, int] = {}

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.row_of = {r["id"]: i for i, r in enumerate(rows)}
        self.endResetModel()

    def update_row(self, aid: int, **changes) -> None:
        row = self.row_of.get(aid)
        if row is None:
            return
        self.rows[row].update(changes)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)

    def refresh_all(self) -> None:
        if self.rows:
            self.dataChanged.emit(self.index(0), self.index(len(self.rows) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        if role == ROW_ROLE:
            return r
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return r["name"]
        if role == Qt.UserRole:
            return r["id"]
        return None


class TileDelegate(QStyledItemDelegate):
    def __init__(self, ctx, icon_for, parent=None, height: int = 74):
        super().__init__(parent)
        self.ctx = ctx
        self.icon_for = icon_for
        self.height = height

    def sizeHint(self, option, index):
        return QSize(260, self.height)

    def _fonts(self):
        serif = self.ctx.c.get("serif") or QFont().family()
        name = QFont(serif, 11)
        name.setBold(True)
        small = QFont()
        small.setPointSize(9)
        big = QFont(serif, 13)
        big.setBold(True)
        return name, small, big

    def paint(self, p: QPainter, option, index):
        r = index.data(ROW_ROLE)
        if not r:
            return
        c = self.ctx.c
        name_font, small_font, big_font = self._fonts()
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(c["gold"] if selected else c["border"]), 1))
        p.setBrush(QColor(c["select"] if selected else (c["tile_hover"] if hover else c["tile"])))
        p.drawRoundedRect(rect, 6, 6)

        key = r.get("status_key")
        ring = c["done"] if key == "done" else (c["gold"] if key == "progress" else c["border"])
        size = rect.height() - 16
        box = QRect(rect.x() + 8, rect.y() + 8, size, size)
        p.setPen(QPen(QColor(ring), 2))
        p.setBrush(QColor(c["alt"]))
        p.drawRoundedRect(box, 5, 5)
        icon = self.icon_for(r.get("icon"))
        if icon is not None:
            icon.paint(p, box.adjusted(4, 4, -4, -4))

        right_w = 120
        x0 = box.right() + 12
        text_w = rect.right() - x0 - right_w - 8
        top = rect.y() + 8

        name = r["name"]
        if r.get("tracked"):
            p.setFont(name_font)
            p.setPen(QColor(c["star"]))
            p.drawText(QRect(x0, top, 18, 22), Qt.AlignLeft | Qt.AlignVCenter, "★")
            name_x = x0 + 18
        else:
            name_x = x0
        p.setFont(name_font)
        p.setPen(QColor(c["sel_text"] if selected else c["text"]))
        fm = QFontMetrics(name_font)
        p.drawText(QRect(name_x, top, text_w - (name_x - x0), 22), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideRight, text_w - (name_x - x0)))

        p.setFont(small_font)
        fm_small = QFontMetrics(small_font)
        category = r.get("category") or ""
        status = r.get("status") or ""
        cat_text = fm_small.elidedText(category, Qt.ElideRight, max(text_w - fm_small.horizontalAdvance(status) - 20, 40))
        p.setPen(QColor(c["muted"]))
        p.drawText(QRect(x0, top + 22, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter, cat_text)
        p.setPen(QColor(c.get(key, c["muted"])))
        p.drawText(QRect(x0 + fm_small.horizontalAdvance(cat_text) + 12, top + 22, text_w, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, status)

        rx = rect.right() - right_w - 8
        p.setFont(small_font)
        p.setPen(QColor(c["gold"]))
        ap = f"{r.get('earned', 0)}/{r.get('total', 0)} AP" if r.get("total") else ""
        p.drawText(QRect(rx, top, right_w, 18), Qt.AlignRight | Qt.AlignVCenter, ap)
        p.setFont(big_font)
        if r.get("done") and not r.get("repeated"):
            p.setPen(QColor(c["done"]))
            big = "✓ Done"
        else:
            p.setPen(QColor(c["sel_text"] if selected else c["text"]))
            big = f"{r.get('current', 0):,}/{r.get('max', 0):,}" if r.get("max") else "—"
        p.drawText(QRect(rx, top + 16, right_w, 24), Qt.AlignRight | Qt.AlignVCenter, big)

        bar = QRect(x0, rect.bottom() - 13, rect.right() - x0 - 12, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["border"]))
        p.drawRoundedRect(bar, 2, 2)
        pct = float(r.get("pct") or 0)
        if pct > 0:
            p.setBrush(QColor(c["done"] if key == "done" else c["gold"]))
            p.drawRoundedRect(QRect(bar.x(), bar.y(), max(5, int(bar.width() * pct)), bar.height()), 2, 2)
        p.restore()


def tile_view(ctx, icon_for, height: int = 74) -> tuple[QListView, TileModel, TileDelegate]:
    view = QListView()
    view.setObjectName("tiles")
    model = TileModel()
    delegate = TileDelegate(ctx, icon_for, view, height)
    view.setModel(model)
    view.setItemDelegate(delegate)
    view.setMouseTracking(True)
    view.setUniformItemSizes(True)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setResizeMode(QListView.Adjust)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.setContextMenuPolicy(Qt.CustomContextMenu)
    return view, model, delegate
