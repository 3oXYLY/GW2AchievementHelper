from __future__ import annotations

import logging
import sys
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from .. import APP_TITLE, AUTHOR, __version__, model, sync
from ..api import AuthError, GW2Client
from ..icons import IconCache
from ..library import SETTING_ASKED, SETTING_ENABLED, LibraryDownloader, scope_of
from ..storage import REGION_ORDER, Storage, data_dir
from . import dialogs
from .achievements import AchievementsView, IconSource
from .common import AppContext, asset_path, friendly_error, muted_label
from .header import HeaderBar
from .navtree import CategoryTree
from .summary import SummaryPage
from .theme import DEFAULT_THEME, apply_theme

log = logging.getLogger("gw2ach")

AUTO_SYNC_AFTER = 15 * 60


class _Signals(QObject):
    library = Signal(object)
    icons = Signal()


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage, colors: dict, client_factory=None, auto_start: bool = True):
        super().__init__()
        self.storage = storage
        self._busy = False
        self._dialog: QDialog | None = None
        self.data: dict = {"totals": {}, "groups": [], "mastery": [], "ap": {}}

        self._signals = _Signals()
        self._signals.library.connect(self.refresh_library_ui, Qt.QueuedConnection)
        self._signals.icons.connect(lambda: self._icon_timer.start(), Qt.QueuedConnection)
        icons = IconCache(data_dir() / "icons", notify=self._signals.icons.emit)
        self.ctx = AppContext(storage, colors, client_factory or (lambda key, lang: GW2Client(key, lang)),
                              icons)
        self.icon_for = IconSource(self.ctx)
        self.library = LibraryDownloader(storage, notify=self._signals.library.emit)

        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1480, 900)
        self.setMinimumSize(1120, 680)
        self._icon_timer = self._timer(300, self._icons_arrived)
        self._search_timer = self._timer(220, self._apply_search)
        self._build()
        self.ctx.set_status = self.set_status

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(60_000)
        self._tick_timer.timeout.connect(self.update_header)
        self._tick_timer.start()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("F5"), self, activated=self.start_sync)

        self.refresh_data()
        self.refresh_library_ui()
        self._want_category_icons()
        if auto_start:
            self._maybe_start_library()
            QTimer.singleShot(300, self._startup)

    def _timer(self, ms: int, slot) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(slot)
        return t

    @property
    def c(self) -> dict:
        return self.ctx.c

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = HeaderBar(self.ctx, self.start_sync, self.open_settings)
        root.addWidget(self.header)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 6)
        bl.setSpacing(14)
        side = QVBoxLayout()
        side.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        side.addWidget(self.search)
        self.tree = CategoryTree(self.ctx)
        self.tree.setFixedWidth(300)
        self.tree.scope_selected.connect(self._on_scope)
        side.addWidget(self.tree, 1)
        self.credit = muted_label(f"v{__version__}   •   Made by {AUTHOR}")
        credit_font = self.credit.font()
        credit_font.setPointSizeF(max(credit_font.pointSizeF() - 1, 7.5))
        self.credit.setFont(credit_font)
        side.addWidget(self.credit)
        bl.addLayout(side)

        self.stack = QStackedWidget()
        self.summary = SummaryPage(self.ctx, self.icon_for)
        self.achievements = AchievementsView(self.ctx, self.icon_for)
        self.stack.addWidget(self.summary)
        self.stack.addWidget(self.achievements)
        bl.addWidget(self.stack, 1)
        root.addWidget(body, 1)
        self.summary.open_achievement.connect(self.open_achievement)
        self.summary.open_scope.connect(lambda kind: self.tree.select(kind))
        self.achievements.tracked_changed.connect(self._tracked_changed)

        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setContentsMargins(10, 0, 0, 2)
        bar.addWidget(self.status_lbl, 1)
        self.lib_lbl = muted_label()
        self.lib_lbl.setToolTip("Offline wiki library: keeps wiki pages on this computer so explanations "
                                "work even when the wiki is down.")
        self.lib_btn = QPushButton()
        self.lib_btn.setProperty("chip", True)
        self.lib_btn.clicked.connect(self._toggle_library)
        bar.addPermanentWidget(self.lib_lbl)
        bar.addPermanentWidget(self.lib_btn)
        gap = QWidget()
        gap.setFixedWidth(14)
        bar.addPermanentWidget(gap)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(200, 6)
        bar.addPermanentWidget(self.progress)

    def _account_ap(self) -> tuple[int | None, int | None]:
        values = []
        for key in ("daily_ap", "monthly_ap"):
            raw = self.storage.get_setting(key)
            values.append(int(raw) if raw not in (None, "") else None)
        return values[0], values[1]

    def refresh_data(self) -> None:
        self.data = model.build_overview(self.storage.overview_rows(), REGION_ORDER)
        daily, monthly = self._account_ap()
        counts = self.storage.view_counts()
        total = self.data["totals"].get("earned_all", 0) + (daily or 0) + (monthly or 0)
        self.header.set_points(total if self.storage.achievement_count() else None)
        self.tree.populate(self.data, counts)
        self.summary.refresh(self.data, daily, monthly, counts)
        self.update_header()

    def _on_scope(self, scope: dict) -> None:
        if scope.get("kind") == "summary":
            if self.search.text().strip():
                self.search.blockSignals(True)
                self.search.clear()
                self.search.blockSignals(False)
                self.achievements.search_text = ""
            self.stack.setCurrentWidget(self.summary)
            return
        self.stack.setCurrentWidget(self.achievements)
        self.achievements.set_scope(scope["kind"], scope.get("value"), scope.get("title"))

    def _apply_search(self) -> None:
        text = self.search.text()
        if text.strip() and self.stack.currentWidget() is self.summary:
            self.tree.select("all")
        self.achievements.set_search(text)

    def open_achievement(self, aid: int) -> None:
        self.tree.select("all")
        self.achievements.select_achievement(aid)

    def _tracked_changed(self) -> None:
        counts = self.storage.view_counts()
        self.tree.update_counts(counts)
        daily, monthly = self._account_ap()
        self.summary.refresh(self.data, daily, monthly, counts)

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _icons_arrived(self) -> None:
        self.achievements.icons_updated()
        self.summary.icons_updated()

    def _want_category_icons(self) -> None:
        self.ctx.icons.want(self.storage.category_icons())

    def set_status(self, text: str, frac: float | None = None) -> None:
        self.status_lbl.setText(text)
        if frac is not None:
            self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    def _set_busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        self.header.set_busy(busy)
        if text:
            self.set_status(text, 0.0 if busy else None)

    def update_header(self) -> None:
        parts = []
        totals = (getattr(self, "data", None) or {}).get("totals") or self.storage.stats()
        if totals.get("total"):
            parts.append(f"{totals['done']:,} / {totals['total']:,} done")
        last = self.storage.get_setting("last_sync")
        if last:
            parts.append("synced " + model.time_ago(float(last)))
        self.header.set_account(self.storage.get_setting("account_name"), "   •   ".join(parts))

    def _startup(self) -> None:
        if self.storage.has_unreadable_key():
            QMessageBox.warning(self, APP_TITLE, "Your saved API key couldn't be read on this computer "
                                                 "(it only works for the Windows user that saved it). "
                                                 "Please add it again.")
        if not self.storage.load_api_key():
            self.set_status("Add your GW2 API key to get started.")
            self.open_key_dialog()
            return
        last = float(self.storage.get_setting("last_sync") or 0)
        if time.time() - last > AUTO_SYNC_AFTER:
            self.start_sync()
        QTimer.singleShot(800, self._maybe_ask_library)

    def start_sync(self, full: bool = False) -> None:
        if self._busy:
            return
        key = self.storage.load_api_key()
        if not key:
            self.open_key_dialog()
            return
        client = self.ctx.client(key)
        self._set_busy(True, "Syncing…")
        self.ctx.worker.run(lambda report: sync.sync_all(self.storage, client, report, full_refresh=full),
                            on_ok=self._sync_done, on_err=self._sync_failed, on_progress=self.set_status)

    def _after_data_change(self) -> None:
        self.refresh_data()
        self.achievements.reload()
        self._want_category_icons()

    def _sync_done(self, summary: dict) -> None:
        self._set_busy(False)
        new = f"{summary['downloaded']:,} achievement definitions downloaded, " if summary["downloaded"] else ""
        self.set_status(f"Synced {summary['account_name']}: {new}"
                        f"{summary['with_progress']:,} with progress on your account.", 1.0)
        self._after_data_change()
        self._maybe_start_library()
        self.refresh_library_ui()
        QTimer.singleShot(500, self._maybe_ask_library)

    def _sync_failed(self, err: Exception) -> None:
        self._set_busy(False)
        self.set_status("Sync failed: " + friendly_error(err), 0.0)
        self._after_data_change()
        if isinstance(err, (AuthError, sync.MissingPermissions)):
            answer = QMessageBox.question(self, APP_TITLE, friendly_error(err) +
                                          "\n\nDo you want to enter a different key?")
            if answer == QMessageBox.Yes:
                self.open_key_dialog()
        else:
            QMessageBox.critical(self, APP_TITLE, "Sync failed:\n\n" + friendly_error(err))

    def library_enabled(self) -> bool:
        return self.storage.get_setting(SETTING_ENABLED) == "1"

    def _maybe_start_library(self) -> None:
        if self.library_enabled() and self.storage.achievement_count():
            if self.library.active:
                self.library.wake()
            else:
                self.library.start()

    def set_library_enabled(self, on: bool) -> None:
        self.storage.set_setting(SETTING_ENABLED, "1" if on else "0")
        self.storage.set_setting(SETTING_ASKED, "1")
        if on:
            self._maybe_start_library()
        else:
            self.library.stop()
        self.refresh_library_ui()

    def _toggle_library(self) -> None:
        setting = self.storage.get_setting(SETTING_ENABLED)
        if setting is None:
            self.open_library_dialog()
        elif setting == "1" and self.library.state.get("state") == "error":
            self.library.start()
        else:
            self.set_library_enabled(setting != "1")

    def _maybe_ask_library(self) -> None:
        if self.storage.get_setting(SETTING_ASKED) or not self.storage.achievement_count():
            return
        if self._dialog is not None and self._dialog.isVisible():
            return
        self.open_library_dialog()

    def refresh_library_ui(self, state: dict | None = None) -> None:
        if state is None:
            state = self.library.state
        elif not state:
            state = {k: v for k, v in self.library.state.items() if k in ("state", "message")}
        setting = self.storage.get_setting(SETTING_ENABLED)
        tip = ""
        if setting is None:
            text, button = "Offline wiki library: off", "Turn on…"
        elif setting != "1":
            saved = self.storage.library_counts(scope_of(self.storage))["saved"]
            text, button = f"Offline wiki: paused  ·  {saved:,} pages saved", "Resume"
        else:
            counts = state if "total" in state else self.storage.library_counts(scope_of(self.storage))
            saved, total, checked = counts["saved"], counts["total"], counts["checked"]
            pct = int(checked * 100 / total) if total else 100
            kind = state.get("state")
            button = "Pause"
            if kind == "waiting":
                text = f"Offline wiki: waiting for the wiki to come back  ·  {saved:,} saved"
                tip = (state.get("message") or "") + " It tries again every 10 minutes."
            elif kind == "done":
                text = f"Offline wiki: up to date  ·  {saved:,} pages saved"
            elif kind == "downloading":
                text = f"Offline wiki: downloading  ·  {saved:,} saved  ·  {pct}%"
            elif kind == "error":
                text, button = "Offline wiki: stopped after an error (details in app.log)", "Restart"
            else:
                text = f"Offline wiki: on  ·  {saved:,} pages saved"
        self.lib_lbl.setText(text)
        self.lib_btn.setText(button)
        self.lib_btn.setToolTip(tip or {"Turn on…": "Save wiki pages on this computer",
                                        "Pause": "Stop downloading for now",
                                        "Resume": "Continue downloading wiki pages",
                                        "Restart": "Start the download again"}[button])
        self.achievements.library_changed(state)

    def open_key_dialog(self) -> None:
        dialogs.open_key_dialog(self)

    def open_settings(self) -> None:
        dialogs.open_settings(self)

    def open_library_dialog(self) -> None:
        dialogs.open_library_dialog(self)

    def remove_all_data(self) -> None:
        self.library.stop()
        self.achievements.flush()
        self.storage.wipe_all()
        self.achievements.reset()
        self.refresh_data()
        self.refresh_library_ui()
        self.tree.select("summary")
        self.set_status("All data removed.", 0.0)

    def set_theme(self, name: str) -> None:
        self.storage.set_setting("theme", name)
        self.ctx.c = apply_theme(QApplication.instance(), name)
        self.header.theme_changed()
        self.refresh_data()
        self.achievements.theme_changed()

    def closeEvent(self, event) -> None:
        self.achievements.flush()
        self.library.stop()
        self.ctx.icons.close()
        super().closeEvent(event)


def main() -> None:
    logging.basicConfig(filename=str(data_dir() / "app.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Foxi.GW2AchievementHelper")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    icon = asset_path("app.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    font = QFont("Segoe UI", 10) if sys.platform == "win32" else app.font()
    if sys.platform != "win32":
        font.setPointSize(10)
    app.setFont(font)
    storage = Storage()
    colors = apply_theme(app, storage.get_setting("theme") or DEFAULT_THEME)
    window = MainWindow(storage, colors)

    def excepthook(exc_type, exc, tb):
        log.error("Unhandled error", exc_info=(exc_type, exc, tb))
        QMessageBox.critical(window, APP_TITLE, f"Something went wrong:\n{exc}\n\n"
                                                f"Details are in app.log in {data_dir()}")

    sys.excepthook = excepthook
    window.show()
    sys.exit(app.exec())
