from __future__ import annotations

import json
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton)

from .. import APP_TITLE, sync
from ..api import LANGS
from ..library import SETTING_ASKED, SETTING_SCOPE, scope_of
from ..storage import data_dir
from .theme import DEFAULT_THEME, THEME_NAMES
from .common import KEY_PAGE, friendly_error, group, heading_label, muted_label, new_dialog, open_url

LANG_NAMES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "zh": "中文"}


def _show(win, dlg) -> None:
    win._dialog = dlg
    dlg.show()


def open_key_dialog(win) -> None:
    dlg, lay = new_dialog(win, "Connect your GW2 account", 600)
    lay.addWidget(heading_label("Connect your Guild Wars 2 account"))
    where = "encrypted with your Windows account" if sys.platform == "win32" else "in your user folder"
    lay.addWidget(QLabel("1.  Open the ArenaNet applications page and press “New Key”.\n"
                         "2.  Give it a name and tick only:  account  and  progression.\n"
                         "3.  Copy the key and paste it below."))
    lay.addWidget(muted_label(f"The key is saved only on this computer ({where}) and is only ever sent "
                              "to api.guildwars2.com. Nothing goes to any other server.", wrap=True))
    open_btn = QPushButton("Open account.arena.net/applications")
    open_btn.clicked.connect(lambda: open_url(KEY_PAGE))
    lay.addWidget(open_btn, 0, Qt.AlignLeft)
    entry = QLineEdit()
    entry.setEchoMode(QLineEdit.Password)
    entry.setPlaceholderText("Paste your API key here")
    lay.addSpacing(6)
    lay.addWidget(entry)
    show = QCheckBox("Show key")
    show.toggled.connect(lambda on: entry.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
    lay.addWidget(show)
    msg = QLabel("")
    msg.setProperty("error", True)
    msg.setWordWrap(True)
    lay.addWidget(msg)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    save_btn = QPushButton("Save && sync")
    save_btn.setProperty("primary", True)
    save_btn.setDefault(True)
    buttons.addWidget(cancel)
    buttons.addWidget(save_btn)
    lay.addLayout(buttons)

    def save():
        key = entry.text().strip()
        if len(key) < 20 or any(ch.isspace() for ch in key):
            msg.setText("That doesn't look like a GW2 API key - it's a long code with dashes.")
            return
        save_btn.setEnabled(False)
        msg.setText("Checking the key with the GW2 API…")
        client = win.ctx.client(key)

        def ok(info):
            sync.save_key(win.storage, key, info)
            dlg.accept()
            win.update_header()
            win.achievements.refresh_list()
            win.start_sync()

        def fail(err):
            save_btn.setEnabled(True)
            msg.setText(friendly_error(err))

        win.ctx.worker.run(lambda report: sync.check_key(client), on_ok=ok, on_err=fail)

    save_btn.clicked.connect(save)
    entry.returnPressed.connect(save)
    _show(win, dlg)
    entry.setFocus()


def library_estimate(pages: int) -> str:
    size = max(1, round(pages * 4 / 1024))
    minutes = max(1, round(pages * 2.2 / 60))
    when = f"about {minutes} min" if minutes < 90 else f"about {round(minutes / 60)} hours"
    return f"{pages:,} pages, ~{size} MB, {when}"


def open_library_dialog(win) -> None:
    storage = win.storage
    dlg, lay = new_dialog(win, "Offline wiki library", 600)
    storage.set_setting(SETTING_ASKED, "1")
    lay.addWidget(heading_label("Save wiki pages on your computer?"))
    intro = QLabel("The tool can download the wiki page of each achievement and keep it on this "
                   "computer, so explanations open instantly and still work when the wiki is down.")
    intro.setWordWrap(True)
    lay.addWidget(intro)
    lay.addWidget(muted_label(
        "•  It downloads slowly in the background (one page every couple of seconds) so it doesn't "
        "put load on the wiki.\n"
        "•  It only downloads while the wiki is online. If the wiki is down, it waits and continues later.\n"
        "•  You can pause or resume it anytime from the bar at the bottom of the window, or in Settings.\n"
        "•  Pages you open yourself with 'Wiki explanation' are always kept, even when this is off.",
        wrap=True))
    lay.addSpacing(4)
    lay.addWidget(QLabel("Download pages for:"))
    unfinished = storage.library_counts("unfinished")["total"]
    everything = storage.library_counts("all")["total"]
    r1 = QRadioButton(f"Achievements I haven't finished   ({library_estimate(unfinished)})")
    r2 = QRadioButton(f"All achievements   ({library_estimate(everything)})")
    (r2 if scope_of(storage) == "all" else r1).setChecked(True)
    lay.addWidget(r1)
    lay.addWidget(r2)
    lay.addSpacing(6)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    later = QPushButton("Not now")
    later.clicked.connect(dlg.reject)
    turn_on = QPushButton("Turn on")
    turn_on.setProperty("primary", True)
    turn_on.setDefault(True)

    def accept():
        storage.set_setting(SETTING_SCOPE, "all" if r2.isChecked() else "unfinished")
        dlg.accept()
        win.set_library_enabled(True)

    turn_on.clicked.connect(accept)
    buttons.addWidget(later)
    buttons.addWidget(turn_on)
    lay.addLayout(buttons)
    dlg.finished.connect(lambda _r: win.refresh_library_ui())
    _show(win, dlg)


def open_settings(win) -> None:
    storage = win.storage
    dlg, lay = new_dialog(win, "Settings", 580)
    lay.addWidget(heading_label("Settings"))

    acct, al = group("Account")
    key = storage.load_api_key()
    if key:
        perms = json.loads(storage.get_setting("key_permissions") or "[]")
        stored = ("encrypted with Windows (DPAPI)" if storage.api_key_encrypted()
                  else "saved in your user folder (not encrypted)")
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(6)
        rows = (("Account", storage.get_setting("account_name") or "?"),
                ("Key", f"{storage.get_setting('key_name') or '(no name)'}   {key[:8]}…{key[-4:]}"),
                ("Permissions", ", ".join(perms)),
                ("Stored", stored))
        for k, v in rows:
            value = QLabel(v)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(muted_label(k), value)
        al.addLayout(form)
    else:
        al.addWidget(QLabel("No API key yet."))
    row = QHBoxLayout()
    change = QPushButton("Change API key" if key else "Add API key")
    change.clicked.connect(lambda: (dlg.accept(), open_key_dialog(win)))
    remove = QPushButton("Remove key && all my data")

    def do_remove():
        answer = QMessageBox.question(dlg, APP_TITLE, "Remove the API key and all saved data (including "
                                                      "tracked achievements and notes) from this computer?")
        if answer == QMessageBox.Yes:
            dlg.accept()
            win.remove_all_data()

    remove.clicked.connect(do_remove)
    row.addWidget(change)
    row.addWidget(remove)
    row.addStretch(1)
    al.addLayout(row)
    lay.addWidget(acct)

    prefs, pl = group("Preferences")
    lang_row = QHBoxLayout()
    lang_row.addWidget(QLabel("Achievement language"))
    lang_cb = QComboBox()
    for code in LANGS:
        lang_cb.addItem(LANG_NAMES[code], code)
    lang_cb.setCurrentIndex(max(lang_cb.findData(win.ctx.lang()), 0))
    lang_row.addWidget(lang_cb)
    lang_row.addSpacing(24)
    lang_row.addWidget(QLabel("Theme"))
    theme_cb = QComboBox()
    for code, label in THEME_NAMES.items():
        theme_cb.addItem(label, code)
    theme_cb.setCurrentIndex(max(theme_cb.findData(storage.get_setting("theme") or DEFAULT_THEME), 0))
    theme_cb.currentIndexChanged.connect(lambda _i: win.set_theme(theme_cb.currentData()))
    lang_row.addWidget(theme_cb)
    lang_row.addStretch(1)
    pl.addLayout(lang_row)

    def lang_changed(_i):
        code = lang_cb.currentData()
        if code and code != win.ctx.lang():
            storage.set_setting("lang", code)
            if storage.load_api_key() and QMessageBox.question(
                    dlg, APP_TITLE, "Download the achievement texts in the new language now?") == QMessageBox.Yes:
                dlg.accept()
                win.start_sync()

    lang_cb.currentIndexChanged.connect(lang_changed)
    redl = QPushButton("Re-download the whole achievement database")
    redl.clicked.connect(lambda: (dlg.accept(), win.start_sync(full=True)))
    pl.addWidget(redl, 0, Qt.AlignLeft)
    lay.addWidget(prefs)

    lib, ll = group("Offline wiki library")
    lib_on = QCheckBox("Download wiki pages in the background")
    lib_on.setChecked(win.library_enabled())
    lib_on.toggled.connect(win.set_library_enabled)
    ll.addWidget(lib_on)
    scope_row = QHBoxLayout()
    scope_row.addWidget(QLabel("Pages for"))
    scope_cb = QComboBox()
    scope_cb.addItem("Achievements I haven't finished", "unfinished")
    scope_cb.addItem("All achievements", "all")
    scope_cb.setCurrentIndex(max(scope_cb.findData(scope_of(storage)), 0))

    def scope_changed(_i):
        storage.set_setting(SETTING_SCOPE, scope_cb.currentData())
        win.library.wake()
        win.refresh_library_ui({})

    scope_cb.currentIndexChanged.connect(scope_changed)
    scope_row.addWidget(scope_cb)
    scope_row.addStretch(1)
    ll.addLayout(scope_row)
    lib_row = QHBoxLayout()
    pages, chars = storage.library_size()
    size = f"{chars / 1e6:.1f} MB" if chars >= 100_000 else f"{max(1, round(chars / 1000))} KB"
    lib_info = muted_label(f"{pages:,} page{'' if pages == 1 else 's'} saved on this computer (~{size})")
    lib_row.addWidget(lib_info, 1)
    clear_lib = QPushButton("Delete saved pages")

    def do_clear():
        if QMessageBox.question(dlg, APP_TITLE, "Delete all wiki pages saved on this computer?") \
                == QMessageBox.Yes:
            storage.clear_wiki_pages()
            lib_info.setText("0 pages saved on this computer")
            win.library.wake()
            win.refresh_library_ui({})
            win.achievements.library_cleared()

    clear_lib.clicked.connect(do_clear)
    lib_row.addWidget(clear_lib)
    ll.addLayout(lib_row)
    lay.addWidget(lib)

    folder, fl = group("Your data folder (only on this computer, not in the program folder)")
    path = data_dir()
    frow = QHBoxLayout()
    path_lbl = muted_label(str(path))
    path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    path_lbl.setToolTip("If you share the program with someone, they start empty and add their own key.")
    frow.addWidget(path_lbl, 1)
    open_folder = QPushButton("Open folder")
    open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
    frow.addWidget(open_folder)
    fl.addLayout(frow)
    lay.addWidget(folder)

    close = QPushButton("Close")
    close.clicked.connect(dlg.accept)
    lay.addWidget(close, 0, Qt.AlignRight)
    _show(win, dlg)
