from __future__ import annotations

import time

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import guides, model, sync
from .common import AppContext, browser, clear_layout, friendly_error, muted_label, open_url, qicon
from .theme import segments_to_html
from .tiles import tile_view

STATUS_FILTERS = [("All", "all"), ("Not done", "todo"), ("In progress", "progress"), ("Done", "done")]
SORTS = [("Default order", None), ("Name", "name"), ("Progress", "progress"), ("Points", "ap"),
         ("Status", "status"), ("Watch list first", "tracked")]
LIST_LIMIT = 20000
WEB_CACHE_TTL = 24 * 3600
PLACEHOLDER = [("Select an achievement to see its details.", ("muted",))]


class IconSource:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._cache: dict[str, object] = {}

    def __call__(self, url):
        if not url:
            return None
        icon = self._cache.get(url)
        if icon is None:
            path = self.ctx.icons.path(url)
            if path is None:
                return None
            icon = qicon(path)
            self._cache[url] = icon
        return icon

    def known(self, url) -> bool:
        return url in self._cache


class AchievementsView(QWidget):
    tracked_changed = Signal()

    def __init__(self, ctx: AppContext, icon_for: IconSource):
        super().__init__()
        self.ctx = ctx
        self.storage = ctx.storage
        self.icon_for = icon_for
        self.scope = {"kind": "all", "value": None, "title": "All Achievements"}
        self.search_text = ""
        self._current_id: int | None = None
        self._rendered_id: int | None = None
        self._resolving: set[int] = set()
        self._pricing: set[int] = set()
        self._price_errors: set[int] = set()
        self._details_waiting_icons = False
        self._web_busy = False
        self._wiki_busy = False
        self._web_results: list[dict] = []
        self._wiki_page: dict | None = None
        self._wiki_saved = False
        self._loading_note = False
        self._note_dirty_id: int | None = None

        self._icon_timer = self._timer(150, self._request_visible_icons)
        self._note_timer = self._timer(600, self._save_note)
        self._build()
        self._load_filters()

    def _timer(self, ms: int, slot) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(slot)
        return t

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        left, right = QWidget(), QWidget()
        self._build_list(left)
        self._build_side(right)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 520])
        lay.addWidget(splitter)

    def _build_list(self, parent: QWidget) -> None:
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        self.title_lbl = QLabel("All Achievements")
        self.title_lbl.setProperty("title", True)
        self.count_lbl = muted_label()
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        head.addWidget(self.count_lbl)
        lay.addLayout(head)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.status_cb = QComboBox()
        for label, key in STATUS_FILTERS:
            self.status_cb.addItem(label, key)
        self.reward_cb = QComboBox()
        self.sort_cb = QComboBox()
        for label, key in SORTS:
            self.sort_cb.addItem(label, key)
        for cb in (self.status_cb, self.reward_cb, self.sort_cb):
            cb.currentIndexChanged.connect(lambda _i: self.refresh_list())
        filters.addWidget(self.status_cb)
        filters.addWidget(self.reward_cb, 1)
        filters.addWidget(self.sort_cb)
        lay.addLayout(filters)

        toggles = QHBoxLayout()
        self.uncat_cb = QCheckBox("Include uncategorized")
        self.uncat_cb.toggled.connect(lambda _b: self.refresh_list())
        self.wiki_search_cb = QCheckBox("Search saved wiki pages")
        self.wiki_search_cb.setToolTip("Also look inside the wiki pages saved on this computer")
        self.wiki_search_cb.toggled.connect(lambda _b: self.refresh_list())
        toggles.addWidget(self.uncat_cb)
        toggles.addSpacing(10)
        toggles.addWidget(self.wiki_search_cb)
        toggles.addStretch(1)
        lay.addLayout(toggles)

        self.list, self.model, self.delegate = tile_view(self.ctx, self.icon_for)
        self.list.selectionModel().currentChanged.connect(self._on_current_changed)
        self.list.doubleClicked.connect(lambda _i: self.find_guide())
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.list.verticalScrollBar().valueChanged.connect(lambda _v: self._icon_timer.start())
        lay.addWidget(self.list, 1)

    def _build_side(self, parent: QWidget) -> None:
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs)

        self.details_tab = QWidget()
        dl = QVBoxLayout(self.details_tab)
        dl.setContentsMargins(0, 10, 0, 0)
        actions = QHBoxLayout()
        self.track_btn = QPushButton("☆ Watch")
        self.track_btn.clicked.connect(lambda: self.toggle_track())
        self.guide_btn = QPushButton("Find guides online")
        self.guide_btn.clicked.connect(self.find_guide)
        self.wiki_btn = QPushButton("Wiki explanation")
        self.wiki_btn.clicked.connect(lambda: self.load_wiki())
        for b in (self.track_btn, self.guide_btn, self.wiki_btn):
            b.setEnabled(False)
            actions.addWidget(b)
        actions.addStretch(1)
        dl.addLayout(actions)
        self.details = browser()
        dl.addWidget(self.details, 1)
        dl.addWidget(muted_label("My notes"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Your notes for this achievement - saved automatically on this computer")
        self.notes.setFixedHeight(84)
        self.notes.setEnabled(False)
        self.notes.textChanged.connect(self._note_changed)
        dl.addWidget(self.notes)
        self.tabs.addTab(self.details_tab, "Details")
        self._set_html(self.details, PLACEHOLDER)

        self.web_tab = QWidget()
        wl = QVBoxLayout(self.web_tab)
        wl.setContentsMargins(0, 10, 0, 0)
        wl.setSpacing(8)
        qrow = QHBoxLayout()
        self.query = QLineEdit()
        self.query.returnPressed.connect(lambda: self.run_web_search(force=True))
        self.web_btn = QPushButton("Search")
        self.web_btn.setProperty("primary", True)
        self.web_btn.clicked.connect(lambda: self.run_web_search(force=True))
        qrow.addWidget(self.query, 1)
        qrow.addWidget(self.web_btn)
        wl.addLayout(qrow)
        self.links_row = QHBoxLayout()
        self.links_row.setSpacing(6)
        wl.addLayout(self.links_row)
        self.web_info = muted_label("Pick an achievement, then press Search.", wrap=True)
        wl.addWidget(self.web_info)
        self.web_tree = QTreeWidget()
        self.web_tree.setHeaderLabels(["Result", "Site"])
        self.web_tree.setRootIsDecorated(False)
        self.web_tree.setAlternatingRowColors(True)
        self.web_tree.setUniformRowHeights(True)
        wh = self.web_tree.header()
        wh.setSectionResizeMode(0, QHeaderView.Stretch)
        wh.setSectionResizeMode(1, QHeaderView.Fixed)
        wh.resizeSection(1, 130)
        wh.setStretchLastSection(False)
        self.web_tree.itemSelectionChanged.connect(self._on_web_select)
        self.web_tree.itemActivated.connect(lambda *_: self._open_web_result())
        self.web_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_tree.customContextMenuRequested.connect(self._web_menu)
        wl.addWidget(self.web_tree, 1)
        wl.addWidget(muted_label("Double-click a result to open it  •  right-click for more"))
        self.snippet = browser()
        self.snippet.setFixedHeight(120)
        wl.addWidget(self.snippet)
        self.tabs.addTab(self.web_tab, "Web guides")

        self.wiki_tab = QWidget()
        kl = QVBoxLayout(self.wiki_tab)
        kl.setContentsMargins(0, 10, 0, 0)
        top = QHBoxLayout()
        self.wiki_src_lbl = muted_label("Pick an achievement, then press 'Wiki explanation'.", wrap=True)
        self.wiki_refresh_btn = QPushButton("Refresh")
        self.wiki_refresh_btn.setToolTip("Download this page again")
        self.wiki_refresh_btn.setEnabled(False)
        self.wiki_refresh_btn.clicked.connect(lambda: self.load_wiki(force=True))
        self.wiki_open_btn = QPushButton("Open in browser")
        self.wiki_open_btn.setEnabled(False)
        self.wiki_open_btn.clicked.connect(lambda: self._wiki_page and open_url(self._wiki_page["url"]))
        top.addWidget(self.wiki_src_lbl, 1)
        top.addWidget(self.wiki_refresh_btn, 0, Qt.AlignTop)
        top.addWidget(self.wiki_open_btn, 0, Qt.AlignTop)
        kl.addLayout(top)
        self.wiki_text = browser()
        kl.addWidget(self.wiki_text, 1)
        self.tabs.addTab(self.wiki_tab, "Wiki text")

    def _set_html(self, target, segments) -> None:
        target.setHtml(segments_to_html(segments, self.ctx.c))

    def _load_filters(self) -> None:
        current = self.reward_cb.currentData()
        self.reward_cb.blockSignals(True)
        self.reward_cb.clear()
        self.reward_cb.addItem("Any reward", None)
        self.reward_cb.addItem("Mastery point (any region)", "mastery")
        for region in self.storage.mastery_regions():
            self.reward_cb.addItem(f"Mastery point: {region}", f"mastery:{region}")
        self.reward_cb.addItem("Title", "title")
        self.reward_cb.addItem("Item", "item")
        idx = self.reward_cb.findData(current) if current is not None else 0
        self.reward_cb.setCurrentIndex(max(idx, 0))
        self.reward_cb.blockSignals(False)

    def set_scope(self, kind: str, value=None, title: str | None = None) -> None:
        self.scope = {"kind": kind, "value": value, "title": title or "All Achievements"}
        self.refresh_list()

    def set_search(self, text: str) -> None:
        self.search_text = " ".join(text.split())
        self.refresh_list()

    def reload(self) -> None:
        self._load_filters()
        self.refresh_list()
        if self._current_id is not None:
            self.render_details()

    def refresh_list(self) -> None:
        kind, value = self.scope["kind"], self.scope["value"]
        view = kind if kind in ("tracked", "near") else "all"
        rows, truncated = self.storage.search(
            self.search_text, self.status_cb.currentData() or "all",
            value if kind == "category" else None, self.uncat_cb.isChecked(), limit=LIST_LIMIT,
            view=view, reward=self.reward_cb.currentData(), search_wiki=self.wiki_search_cb.isChecked(),
            group=value if kind == "group" else None)
        display = [model.display_row(r) for r in rows]
        sort = self.sort_cb.currentData()
        if sort:
            display.sort(key=model.sort_key(sort), reverse=sort in ("progress", "ap"))
        self.model.set_rows(display)
        title = self.scope["title"]
        if self.search_text:
            title = f"Search: “{self.search_text}”" + (f"  in {title}" if kind != "all" else "")
        self.title_lbl.setText(title)
        if not self.storage.achievement_count():
            self.count_lbl.setText("No data yet - add your API key and press Sync")
        elif not display and kind == "tracked":
            self.count_lbl.setText("Your watch list is empty - press ☆ Watch on an achievement")
        else:
            note = "  (first 20,000 shown)" if truncated else ""
            self.count_lbl.setText(f"{len(display):,} achievement{'' if len(display) == 1 else 's'}{note}")
        if self._current_id is not None:
            self._reselect(self._current_id)
        self._icon_timer.start()

    def _reselect(self, aid: int) -> bool:
        row = self.model.row_of.get(aid)
        if row is None:
            return False
        idx = self.model.index(row)
        self.list.selectionModel().setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
        self.list.scrollTo(idx)
        return True

    def select_achievement(self, aid: int) -> None:
        if self._reselect(aid):
            return
        self.search_text = ""
        self.status_cb.setCurrentIndex(0)
        self.reward_cb.setCurrentIndex(0)
        self.uncat_cb.setChecked(True)
        self.scope = {"kind": "all", "value": None, "title": "All Achievements"}
        self.refresh_list()
        self._reselect(aid)

    def _request_visible_icons(self) -> None:
        count = self.model.rowCount()
        if not count:
            return
        top = self.list.indexAt(self.list.viewport().rect().topLeft()).row()
        bottom = self.list.indexAt(self.list.viewport().rect().bottomLeft()).row()
        top = max(top, 0)
        bottom = count - 1 if bottom < 0 else min(bottom + 8, count - 1)
        urls = [self.model.rows[i].get("icon") for i in range(top, bottom + 1)]
        urls = [u for u in urls if u and not self.icon_for.known(u)]
        if urls:
            self.ctx.icons.want(urls)

    def icons_updated(self) -> None:
        self.model.refresh_all()
        if self._details_waiting_icons and self._current_id is not None:
            self.render_details()

    def _list_menu(self, pos) -> None:
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        self.list.selectionModel().setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
        aid = self.model.rows[idx.row()]["id"]
        tracked = self.model.rows[idx.row()].get("tracked")
        menu = QMenu(self)
        menu.addAction("Remove from watch list" if tracked else "Add to watch list", lambda: self.toggle_track(aid))
        menu.addAction("Find guides online", self.find_guide)
        menu.addAction("Wiki explanation", lambda: self.load_wiki())
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def toggle_track(self, aid: int | None = None) -> None:
        aid = self._current_id if aid is None else aid
        if aid is None:
            return
        on = not self.storage.is_tracked(aid)
        self.storage.set_tracked(aid, on)
        self.model.update_row(aid, tracked=on)
        if aid == self._current_id:
            self._update_track_button()
            self.render_details()
        if self.scope["kind"] == "tracked" and not on:
            self.refresh_list()
        self.ctx.set_status("Added to your watch list." if on else "Removed from your watch list.")
        self.tracked_changed.emit()

    def _update_track_button(self) -> None:
        on = self._current_id is not None and self.storage.is_tracked(self._current_id)
        self.track_btn.setText("★ Watching" if on else "☆ Watch")
        self.track_btn.setToolTip("Click to remove from your watch list" if on else "Add to your watch list")

    def _note_changed(self) -> None:
        if self._loading_note or self._current_id is None:
            return
        self._note_dirty_id = self._current_id
        self._note_timer.start()

    def _save_note(self) -> None:
        if self._note_dirty_id is None:
            return
        self.storage.set_note(self._note_dirty_id, self.notes.toPlainText())
        self._note_dirty_id = None

    def _load_note(self) -> None:
        self._loading_note = True
        self.notes.setPlainText(self.storage.get_note(self._current_id) if self._current_id else "")
        self.notes.setEnabled(self._current_id is not None)
        self._loading_note = False

    def _on_current_changed(self, current: QModelIndex, _previous=None) -> None:
        if not current.isValid():
            return
        aid = self.model.data(current, Qt.UserRole)
        if aid is None:
            return
        if aid != self._current_id:
            self._note_timer.stop()
            self._save_note()
            self._current_id = aid
            self._price_errors.discard(aid)
            a = self.storage.get_achievement(aid) or {}
            name = a.get("name") or ""
            self.query.setText(guides.default_query(name))
            self._clear_web_results("Press Search to look for guides for this achievement.")
            self._build_quick_links(name)
            self._wiki_page = None
            self.wiki_open_btn.setEnabled(False)
            self.wiki_text.clear()
            self.wiki_src_lbl.setText("Press 'Wiki explanation' to load the wiki text for this achievement.")
            self._load_note()
        self._sync_wiki_from_library()
        self._update_track_button()
        for b in (self.track_btn, self.guide_btn):
            b.setEnabled(True)
        self.wiki_btn.setEnabled(not self._wiki_busy)
        self.wiki_refresh_btn.setEnabled(not self._wiki_busy)
        self.render_details()

    def render_details(self) -> None:
        aid = self._current_id
        if aid is None:
            return
        a = self.storage.get_achievement(aid)
        if a is None:
            return
        storage, icons = self.storage, self.ctx.icons
        wanted = model.wanted_names(a)
        names = {kind: storage.get_names(kind, ids) for kind, ids in wanted.items()}
        lookups = sync.missing_lookups(storage, wanted)
        info = {kind: storage.get_item_info(kind, ids) for kind, ids in wanted.items() if kind in sync.ICON_KINDS}
        mini_items = {mid: v["item_id"] for mid, v in info.get("mini", {}).items() if v.get("item_id")}

        urls, icon_paths = [], {}
        for kind, entries in info.items():
            for eid, v in entries.items():
                url = v.get("icon")
                if url:
                    urls.append(url)
                    path = icons.path(url)
                    if path:
                        icon_paths[(kind, eid)] = path
        header_url = a.get("icon") or a.get("category_icon")
        if header_url:
            urls.append(header_url)
        header_path = icons.path(header_url)
        missing_urls = [u for u in urls if icons.path(u) is None]
        self._details_waiting_icons = bool(missing_urls)
        if missing_urls:
            icons.want(missing_urls)

        targets = model.price_targets(a, mini_items)
        prices, missing_prices = sync.cached_prices(storage, targets)
        price_state = None
        if missing_prices:
            if aid in self._price_errors:
                price_state = "error"
            else:
                price_state = "loading"
                self._fetch_prices(aid, missing_prices)

        extra = {"icon": header_path, "icons": icon_paths, "mini_items": mini_items, "prices": prices,
                 "price_state": price_state, "tracked": storage.is_tracked(aid)}
        prereqs = storage.achievement_names(a.get("prerequisites") or [])
        same = self._rendered_id == aid
        scroll = self.details.verticalScrollBar().value() if same else 0
        self._set_html(self.details, model.detail_segments(a, names, prereqs, extra))
        self.details.verticalScrollBar().setValue(scroll)
        self._rendered_id = aid

        if lookups and aid not in self._resolving:
            self._resolving.add(aid)
            client = self.ctx.client()

            def done(_result, aid=aid):
                self._resolving.discard(aid)
                if self._current_id == aid:
                    self.render_details()

            def failed(err, aid=aid):
                self._resolving.discard(aid)
                self.ctx.set_status("Couldn't load item names: " + friendly_error(err))

            self.ctx.worker.run(lambda report: sync.resolve_names(storage, client, lookups),
                                on_ok=done, on_err=failed)

    def _fetch_prices(self, aid: int, item_ids: set[int]) -> None:
        if aid in self._pricing:
            return
        self._pricing.add(aid)
        client = self.ctx.client()

        def done(_prices, aid=aid):
            self._pricing.discard(aid)
            if self._current_id == aid:
                self.render_details()

        def failed(err, aid=aid):
            self._pricing.discard(aid)
            self._price_errors.add(aid)
            if self._current_id == aid:
                self.render_details()

        self.ctx.worker.run(lambda report: sync.fetch_prices(self.storage, client, item_ids),
                            on_ok=done, on_err=failed)

    def _build_quick_links(self, name: str) -> None:
        clear_layout(self.links_row)
        if not name:
            return
        self.links_row.addWidget(muted_label("Open directly:"))
        for label, url in guides.quick_links(name):
            btn = QPushButton(label)
            btn.setProperty("chip", True)
            btn.setToolTip(url)
            btn.clicked.connect(lambda _c=False, u=url: open_url(u))
            self.links_row.addWidget(btn)
        self.links_row.addStretch(1)

    def _clear_web_results(self, info: str) -> None:
        self._web_results = []
        self.web_tree.clear()
        self.web_info.setText(info)
        self.snippet.clear()

    def find_guide(self) -> None:
        if self._current_id is None:
            return
        self.tabs.setCurrentWidget(self.web_tab)
        self.run_web_search()

    def run_web_search(self, force: bool = False) -> None:
        query = " ".join(self.query.text().split())
        if not query or self._web_busy:
            return
        cached = self.storage.get_cache("web::" + query.lower(), WEB_CACHE_TTL)
        if cached and cached.get("results") and not force:
            self._show_web_results(cached["results"], cached.get("engine"), cached=True)
            return
        self._web_busy = True
        self.web_btn.setEnabled(False)
        self._clear_web_results(f"Searching the web for “{query}”…")

        def job(_report):
            results, engine = guides.web_search(query)
            return {"results": [r.to_dict() for r in results], "engine": engine}

        def ok(payload):
            self._web_busy = False
            self.web_btn.setEnabled(True)
            self.storage.set_cache("web::" + query.lower(), payload)
            if " ".join(self.query.text().split()) == query:
                self._show_web_results(payload["results"], payload["engine"])

        def err(e):
            self._web_busy = False
            self.web_btn.setEnabled(True)
            self.web_info.setText(f"Web search didn't work ({e}). The 'Open directly' buttons above open "
                                  "the same search in your browser.")

        self.ctx.worker.run(job, on_ok=ok, on_err=err)

    def _show_web_results(self, results: list[dict], engine: str | None, cached: bool = False) -> None:
        self._web_results = results
        self.web_tree.clear()
        for i, r in enumerate(results):
            title = ("★ " if r.get("trusted") else "") + (r.get("title") or r.get("url"))
            item = QTreeWidgetItem([title, r.get("site") or r.get("domain") or ""])
            item.setData(0, Qt.UserRole, i)
            item.setToolTip(0, r.get("url"))
            if not r.get("trusted"):
                for col in (0, 1):
                    item.setForeground(col, QColor(self.ctx.c["muted"]))
            self.web_tree.addTopLevelItem(item)
        src = f" via {engine}" if engine else ""
        self.web_info.setText(f"{len(results)} results{src}{' (saved from earlier)' if cached else ''}. "
                              "★ = known GW2 sites. If a wiki link won't open, right-click → archived copy.")
        if results:
            self.web_tree.setCurrentItem(self.web_tree.topLevelItem(0))

    def _selected_web(self) -> dict | None:
        item = self.web_tree.currentItem()
        if item is None:
            return None
        idx = item.data(0, Qt.UserRole)
        return self._web_results[idx] if isinstance(idx, int) and 0 <= idx < len(self._web_results) else None

    def _on_web_select(self) -> None:
        r = self._selected_web()
        if r:
            self._set_html(self.snippet, [(r.get("title", "") + "\n", ("bold",)),
                                          (r.get("url", "") + "\n", ("link",)),
                                          (r.get("snippet") or "(no preview text)", ())])

    def _open_web_result(self, archived: bool = False) -> None:
        r = self._selected_web()
        if r:
            open_url(guides.archive_url(r["url"]) if archived else r["url"])

    def _web_menu(self, pos) -> None:
        item = self.web_tree.itemAt(pos)
        if item is None:
            return
        self.web_tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Open in browser", self._open_web_result)
        menu.addAction("Open archived copy (web.archive.org)", lambda: self._open_web_result(archived=True))

        def copy():
            r = self._selected_web()
            if r:
                QGuiApplication.clipboard().setText(r["url"])
                self.ctx.set_status("Link copied.")

        menu.addAction("Copy link", copy)
        menu.exec(self.web_tree.viewport().mapToGlobal(pos))

    def load_wiki(self, force: bool = False) -> None:
        aid = self._current_id
        if aid is None or self._wiki_busy:
            return
        a = self.storage.get_achievement(aid)
        if not a:
            return
        name = a["name"]
        self.tabs.setCurrentWidget(self.wiki_tab)
        if not force:
            saved = self.storage.get_wiki_page(aid)
            if saved:
                self._show_wiki(saved, saved=True)
                return
        self._wiki_busy = True
        for b in (self.wiki_btn, self.wiki_refresh_btn, self.wiki_open_btn):
            b.setEnabled(False)
        self.wiki_src_lbl.setText("Looking for the wiki page… (live wiki first, then the web archive - "
                                  "this can take up to a minute)")
        if not force:
            self.wiki_text.clear()

        def finish():
            self._wiki_busy = False
            has = self._current_id is not None
            self.wiki_btn.setEnabled(has)
            self.wiki_refresh_btn.setEnabled(has)
            self.wiki_open_btn.setEnabled(self._wiki_page is not None)

        def ok(page, aid=aid):
            data = page.to_dict()
            self.storage.save_wiki_page(aid, name, data)
            stored = self.storage.get_wiki_page(aid) or data
            finish()
            if self._current_id == aid:
                self._show_wiki(stored, saved=True)
                self.wiki_btn.setText("Wiki explanation  ✓")

        def err(e, aid=aid):
            if self._current_id == aid:
                note = "  Showing the copy saved earlier." if force and self._wiki_page else ""
                self.wiki_src_lbl.setText(str(e) + note)
            finish()

        self.ctx.worker.run(lambda report: guides.fetch_wiki(name), on_ok=ok, on_err=err)

    def _sync_wiki_from_library(self) -> None:
        aid = self._current_id
        if aid is None or self._wiki_busy:
            return
        saved = self.storage.get_wiki_page(aid)
        if saved and (self._wiki_page is None or saved.get("fetched_at") != self._wiki_page.get("fetched_at")):
            self._show_wiki(saved, saved=True)
        self.wiki_btn.setText("Wiki explanation  ✓" if saved else "Wiki explanation")
        self.wiki_btn.setToolTip("Saved on this computer - opens instantly" if saved else
                                 "Loads the wiki page (or a web.archive.org copy if the wiki is down)")

    def _show_wiki(self, page: dict, saved: bool = False) -> None:
        self._wiki_page = page
        self._wiki_saved = saved
        if page.get("source") == "live":
            origin = "GW2 Wiki"
        else:
            ts = page.get("snapshot") or ""
            date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else "an earlier date"
            origin = f"Web archive copy from {date} (may miss recent changes)"
        parts = [origin, page.get("title") or ""]
        if saved and page.get("fetched_at"):
            parts.append("saved on this computer " +
                         time.strftime("%Y-%m-%d", time.localtime(page["fetched_at"])))
        self.wiki_src_lbl.setText("  ·  ".join(p for p in parts if p))
        self.wiki_open_btn.setEnabled(True)
        self.wiki_refresh_btn.setEnabled(not self._wiki_busy)
        segs = []
        for line in page.get("text", "").split("\n"):
            segs.append((line[3:] + "\n", ("h2",)) if line.startswith("## ") else (line + "\n", ()))
        self._set_html(self.wiki_text, segs)

    def library_changed(self, state: dict) -> None:
        if state.get("state") in ("downloading", "done"):
            self._sync_wiki_from_library()

    def library_cleared(self) -> None:
        self.wiki_btn.setText("Wiki explanation")

    def theme_changed(self) -> None:
        self.list.viewport().update()
        if self._current_id is not None:
            self.render_details()
            if self._wiki_page:
                self._show_wiki(self._wiki_page, saved=self._wiki_saved)
        else:
            self._set_html(self.details, PLACEHOLDER)
        if self._web_results:
            self._show_web_results(self._web_results, None)

    def reset(self) -> None:
        self._note_timer.stop()
        self._note_dirty_id = None
        self._current_id = None
        self._rendered_id = None
        self._wiki_page = None
        self.wiki_text.clear()
        self._clear_web_results("Pick an achievement, then press Search.")
        clear_layout(self.links_row)
        self._load_note()
        for b in (self.track_btn, self.guide_btn, self.wiki_btn, self.wiki_refresh_btn, self.wiki_open_btn):
            b.setEnabled(False)
        self._set_html(self.details, PLACEHOLDER)
        self.reload()

    def flush(self) -> None:
        self._note_timer.stop()
        self._save_note()
