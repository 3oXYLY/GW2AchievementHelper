from __future__ import annotations

import html
import logging
from string import Template

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from ..storage import data_dir

log = logging.getLogger("gw2ach")

DEFAULT_THEME = "tyria"
THEME_NAMES = {"tyria": "Tyria (game style)", "dark": "Dark", "light": "Light"}
SERIF_CANDIDATES = ["Palatino Linotype", "Book Antiqua", "Georgia", "Cambria", "DejaVu Serif",
                    "Liberation Serif", "Noto Serif"]

THEMES = {
    "tyria": dict(window="#141210", base="#1c1916", alt="#231f1b", text="#ece4d4", muted="#a69b88",
                  border="#3a3229", button="#2a241e", accent="#c9973a", accent_text="#1b140b",
                  select="#3d3428", sel_text="#f6eedf", done="#86d06f", progress="#e8b04a",
                  todo="#d2c9b8", locked="#7d7366", link="#8fb7ff", h2="#e8b04a", star="#ffcf5a",
                  tile="#201c18", tile_hover="#29241f", gold="#e8b04a", gold_bright="#ffd27a",
                  header_top="#3b2a19", header_bottom="#17120e", nav="#191613"),
    "dark": dict(window="#1b1c1f", base="#232428", alt="#27292e", text="#e7e7ea", muted="#9a9ba3",
                 border="#34363c", button="#2b2d32", accent="#c8323a", accent_text="#ffffff",
                 select="#4f2125", sel_text="#ffffff", done="#5cc27a", progress="#f0a14a",
                 todo="#c9c9cf", locked="#7c7d84", link="#7aa7ff", h2="#ef6b70", star="#f2c14e",
                 tile="#26272c", tile_hover="#2d2f35", gold="#f0b54a", gold_bright="#ffd27a",
                 header_top="#26272c", header_bottom="#1b1c1f", nav="#1f2023"),
    "light": dict(window="#f3f4f6", base="#ffffff", alt="#f7f8fa", text="#1d2129", muted="#6b7280",
                  border="#d8dbe0", button="#ffffff", accent="#b4232a", accent_text="#ffffff",
                  select="#f6d5d7", sel_text="#1d2129", done="#1f7a3a", progress="#b45309",
                  todo="#4b5563", locked="#9ca3af", link="#1d4ed8", h2="#b4232a", star="#c98a00",
                  tile="#ffffff", tile_hover="#f6f7f9", gold="#a86a12", gold_bright="#c98a00",
                  header_top="#ffffff", header_bottom="#eceef2", nav="#eceef1"),
}

QSS = Template("""
QPushButton { background: $button; color: $text; border: 1px solid $border; border-radius: 4px;
              padding: 6px 14px; }
QPushButton:hover { border-color: $gold; }
QPushButton:pressed { background: $alt; }
QPushButton:disabled { color: $muted; border-color: $border; }
QPushButton[primary="true"] { background: $accent; color: $accent_text; border-color: $accent; font-weight: 600; }
QPushButton[chip="true"] { padding: 4px 12px; border-radius: 12px; }
QPushButton[chip="true"]:checked { background: $accent; color: $accent_text; border-color: $accent; }
QLineEdit { background: $base; border: 1px solid $border; border-radius: 4px; padding: 6px 8px; }
QLineEdit:focus { border-color: $gold; }
QPlainTextEdit { background: $base; border: 1px solid $border; border-radius: 6px; padding: 4px; }
QPlainTextEdit:focus { border-color: $gold; }
QComboBox { background: $base; border: 1px solid $border; border-radius: 4px; padding: 5px 8px; }
QComboBox:focus { border-color: $gold; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("$arrow"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: $base; border: 1px solid $border;
                              selection-background-color: $select; selection-color: $sel_text; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid $muted; border-radius: 3px;
                       background: $base; }
QCheckBox::indicator:hover { border-color: $gold; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QTableView, QTreeWidget, QTextBrowser { background: $base; border: 1px solid $border;
                                        border-radius: 6px; }
QTableView, QTreeWidget { alternate-background-color: $alt; selection-background-color: $select;
                          selection-color: $sel_text; outline: 0; }
QTreeWidget::item { padding: 6px 2px; }
QTreeWidget::item:selected { background: $select; color: $sel_text; }
QTreeWidget#categories { background: $nav; border: 1px solid $border; border-radius: 6px; }
QTreeWidget#categories::item { padding: 6px 2px; border: none; }
QTreeWidget#categories::item:hover { background: $alt; }
QTreeWidget#categories::item:selected { background: $select; color: $sel_text; }
QListView#tiles { background: transparent; border: none; outline: 0; }
QHeaderView::section { background: $base; color: $muted; border: none;
                       border-bottom: 1px solid $border; padding: 6px 8px; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: $muted; padding: 8px 16px; border: none;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $gold; }
QTabBar::tab:hover { color: $text; }
QWidget#header { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $header_top, stop:1 $header_bottom);
                 border-bottom: 1px solid $gold; }
QLabel#apValue { color: $gold_bright; font-family: "$serif"; font-size: 26pt; font-weight: 700; }
QLabel#milestone { color: $muted; background: $alt; border: 1px solid $border; border-radius: 4px;
                   padding: 3px 8px; }
QLabel#milestone[next="true"] { color: $gold_bright; border-color: $gold; }
QLabel[serif="true"] { font-family: "$serif"; }
QLabel[title="true"] { font-family: "$serif"; font-size: 15pt; font-weight: 700; color: $gold; }
QLabel[section="true"] { font-family: "$serif"; font-size: 12pt; font-weight: 700; color: $text; }
QLabel[account="true"] { font-family: "$serif"; font-size: 13pt; font-weight: 700; color: $text; }
QFrame[panel="true"] { background: $base; border: 1px solid $border; border-radius: 8px; }
QFrame[card="true"] { background: $base; border: 1px solid $border; border-radius: 8px; }
QLabel[cardvalue="true"] { font-family: "$serif"; font-size: 18pt; font-weight: 700; color: $gold_bright; }
QProgressBar { background: $alt; border: none; border-radius: 3px; }
QProgressBar::chunk { background: $gold; border-radius: 3px; }
QLabel[muted="true"] { color: $muted; }
QLabel[heading="true"] { font-family: "$serif"; font-size: 16pt; font-weight: 700; }
QLabel[error="true"] { color: $h2; }
QGroupBox { border: 1px solid $border; border-radius: 6px; margin-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $muted; }
QStatusBar { color: $muted; }
QStatusBar::item { border: none; }
QSplitter::handle { background: transparent; }
QToolTip { background: $base; color: $text; border: 1px solid $border; padding: 4px; }
""")


def pick_serif() -> str:
    families = set(QFontDatabase.families())
    for name in SERIF_CANDIDATES:
        if name in families:
            return name
    return QApplication.font().family()


def _theme_images(c: dict, name: str) -> dict:
    folder = data_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    arrow, check = folder / f"arrow_{name}.png", folder / "check.png"

    pm = QPixmap(20, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(c["muted"]), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(3, 3), QPointF(10, 9), QPointF(17, 3)])
    p.end()
    pm.save(str(arrow))

    pm = QPixmap(30, 30)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#ffffff"), 4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(6, 15), QPointF(12, 21), QPointF(24, 8)])
    p.end()
    pm.save(str(check))
    return {"arrow": arrow.as_posix(), "check": check.as_posix()}


def apply_theme(app: QApplication, name: str) -> dict:
    if name not in THEMES:
        name = DEFAULT_THEME
    c = dict(THEMES[name])
    c["name"] = name
    c["serif"] = pick_serif()
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {QPalette.Window: "window", QPalette.WindowText: "text", QPalette.Base: "base",
             QPalette.AlternateBase: "alt", QPalette.Text: "text", QPalette.Button: "button",
             QPalette.ButtonText: "text", QPalette.Highlight: "select",
             QPalette.HighlightedText: "sel_text", QPalette.ToolTipBase: "base",
             QPalette.ToolTipText: "text", QPalette.PlaceholderText: "muted", QPalette.Link: "link"}
    for role, key in roles.items():
        pal.setColor(role, QColor(c[key]))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)
    try:
        images = _theme_images(c, name)
    except Exception:
        log.exception("Couldn't draw theme images")
        images = {"arrow": "", "check": ""}
    app.setStyleSheet(QSS.substitute(c, **images))
    return c


def tag_style(tags, c: dict) -> str:
    css = []
    for t in tags:
        if t == "h1":
            css.append(f"font-family:'{c.get('serif', 'serif')}'; font-size:17pt; font-weight:700; "
                       f"color:{c.get('gold_bright', c['text'])};")
        elif t == "h2":
            css.append(f"font-family:'{c.get('serif', 'serif')}'; color:{c['h2']}; font-size:12pt; font-weight:700;")
        elif t in ("h3", "bold"):
            css.append("font-weight:700;")
        elif t == "link":
            css.append(f"color:{c['link']}; text-decoration:underline;")
        elif t in ("muted", "done", "progress", "todo", "locked", "star"):
            css.append(f"color:{c['muted' if t == 'muted' else t]};")
    return " ".join(css)


def segments_to_html(segments, c: dict) -> str:
    parts = [f'<div style="white-space:pre-wrap; color:{c["text"]};">']
    for text, tags in segments:
        if tags and tags[0] == "img":
            src = QUrl.fromLocalFile(tags[1]).toString()
            size = tags[2]
            parts.append(f'<img src="{html.escape(src)}" width="{size}" height="{size}" align="middle">')
            continue
        esc = html.escape(text)
        style = tag_style(tags, c)
        parts.append(f'<span style="{style}">{esc}</span>' if style else esc)
    parts.append("</div>")
    return "".join(parts)
