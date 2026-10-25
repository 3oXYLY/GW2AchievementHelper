from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTextBrowser, QVBoxLayout)

from .. import guides, sync
from ..api import LANGS, AuthError, NetworkError

log = logging.getLogger("gw2ach")

SORT_ROLE = Qt.UserRole + 1
PCT_ROLE = Qt.UserRole + 2
STATUS_ROLE = Qt.UserRole + 3
KEY_PAGE = "https://account.arena.net/applications"


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets" / name


def friendly_error(err: Exception) -> str:
    if isinstance(err, sync.MissingPermissions):
        return (f"This key is missing: {', '.join(err.missing)}. Create a new key on "
                f"account.arena.net with 'account' and 'progression' ticked.")
    if isinstance(err, AuthError):
        return f"The GW2 API rejected the key: {err}"
    if isinstance(err, NetworkError):
        return "Couldn't reach the GW2 API. Check your internet connection and try again."
    return str(err) or err.__class__.__name__


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def muted_label(text: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", True)
    lbl.setWordWrap(wrap)
    return lbl


def heading_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("heading", True)
    return lbl


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


def browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenExternalLinks(True)
    b.document().setDocumentMargin(14)
    return b


def new_dialog(parent, title: str, width: int = 560) -> tuple[QDialog, QVBoxLayout]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(width)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(22, 20, 22, 18)
    lay.setSpacing(10)
    return dlg, lay


def group(title: str, horizontal: bool = False):
    box = QGroupBox(title)
    lay = QHBoxLayout(box) if horizontal else QVBoxLayout(box)
    lay.setContentsMargins(14, 20, 14, 12)
    lay.setSpacing(8)
    return box, lay


def card(title: str) -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setProperty("card", True)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(2)
    lay.addWidget(muted_label(title))
    value = QLabel("—")
    value.setProperty("cardvalue", True)
    lay.addWidget(value)
    sub = muted_label("", wrap=True)
    lay.addWidget(sub)
    return frame, value, sub


_icon_cache: dict[str, QIcon] = {}


def qicon(path) -> QIcon:
    key = str(path)
    icon = _icon_cache.get(key)
    if icon is None:
        icon = QIcon(QPixmap(key))
        _icon_cache[key] = icon
    return icon


class _Bridge(QObject):
    deliver = Signal(object, object)


class Worker:
    def __init__(self):
        self._bridge = _Bridge()
        self._bridge.deliver.connect(self._dispatch, Qt.QueuedConnection)

    @staticmethod
    def _dispatch(cb, args):
        if cb:
            try:
                cb(*args)
            except Exception:
                log.exception("UI callback failed")

    def run(self, fn, on_ok=None, on_err=None, on_progress=None):
        def report(msg, frac=None):
            self._bridge.deliver.emit(on_progress, (msg, frac))

        def target():
            try:
                result = fn(report)
            except Exception as e:
                expected = (AuthError, NetworkError, guides.SearchError, guides.WikiError)
                log.warning("Background job failed: %s", e, exc_info=not isinstance(e, expected))
                self._bridge.deliver.emit(on_err, (e,))
            else:
                self._bridge.deliver.emit(on_ok, (result,))

        threading.Thread(target=target, daemon=True).start()


class AppContext:
    def __init__(self, storage, colors: dict, client_factory, icons):
        self.storage = storage
        self.c = colors
        self.client_factory = client_factory
        self.icons = icons
        self.worker = Worker()
        self.set_status = lambda text, frac=None: None

    def lang(self) -> str:
        lang = self.storage.get_setting("lang") or "en"
        return lang if lang in LANGS else "en"

    def client(self, key: str | None = None):
        return self.client_factory(key, self.lang())


class ProgressDelegate(QStyledItemDelegate):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx

    def paint(self, painter: QPainter, option, index):
        c = self.ctx.c
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        pct = float(index.data(PCT_ROLE) or 0)
        key = index.data(STATUS_ROLE) or "todo"
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        bar = QRect(r.x() + 12, r.bottom() - 8, max(r.width() - 24, 4), 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c["border"]))
        painter.drawRoundedRect(bar, 2, 2)
        if pct > 0:
            painter.setBrush(QColor(c.get(key, c["accent"])))
            painter.drawRoundedRect(QRect(bar.x(), bar.y(), max(4, int(bar.width() * pct)), bar.height()), 2, 2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor(c["sel_text"] if selected else c["text"]))
        painter.drawText(r.adjusted(0, -4, 0, -4), Qt.AlignCenter, text)
        painter.restore()


def emblem_pixmap(size: int) -> QPixmap:
    scale = 2
    pm = QPixmap(str(asset_path("app.png")))
    if pm.isNull():
        return QPixmap()
    pm = pm.scaled(size * scale, size * scale, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(scale)
    return pm
