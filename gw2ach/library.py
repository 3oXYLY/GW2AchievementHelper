from __future__ import annotations

import logging
import threading

from . import guides
from .storage import Storage

log = logging.getLogger("gw2ach")

BATCH = 25
PAGE_DELAY = 1.5
DOWN_RETRY = 10 * 60
IDLE_RECHECK = 30 * 60

SETTING_ENABLED = "library_enabled"
SETTING_ASKED = "library_asked"
SETTING_SCOPE = "library_scope"


def scope_of(storage: Storage) -> str:
    return "all" if storage.get_setting(SETTING_SCOPE) == "all" else "unfinished"


class LibraryDownloader:
    def __init__(self, storage: Storage, notify=None, page_delay: float = PAGE_DELAY,
                 down_retry: float = DOWN_RETRY, idle_recheck: float = IDLE_RECHECK):
        self.storage = storage
        self.notify = notify or (lambda state: None)
        self.page_delay = page_delay
        self.down_retry = down_retry
        self.idle_recheck = idle_recheck
        self.state: dict = {"state": "stopped"}
        self._lock = threading.Lock()
        self._gen = 0
        self._event: threading.Event | None = None

    @property
    def active(self) -> bool:
        return self._event is not None

    def start(self) -> None:
        with self._lock:
            if self._event is not None:
                self._event.set()
            self._gen += 1
            gen, event = self._gen, threading.Event()
            self._event = event
        threading.Thread(target=self._run, args=(gen, event), daemon=True, name="wiki-library").start()

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            if self._event is not None:
                self._event.set()
            self._event = None
        self._emit({"state": "stopped"})

    def wake(self) -> None:
        with self._lock:
            event = self._event
        if event is not None:
            event.set()

    def _emit(self, state: dict) -> None:
        self.state = state
        try:
            self.notify(state)
        except Exception:
            pass

    def _sleep(self, gen: int, event: threading.Event, seconds: float) -> bool:
        event.wait(seconds)
        event.clear()
        return self._gen == gen

    def _counts(self, scope: str) -> dict:
        return self.storage.library_counts(scope)

    def _run(self, gen: int, event: threading.Event) -> None:
        try:
            while self._gen == gen:
                scope = scope_of(self.storage)
                todo = self.storage.library_todo(scope, BATCH)
                if not todo:
                    self._emit({"state": "done", **self._counts(scope)})
                    if not self._sleep(gen, event, self.idle_recheck):
                        return
                    continue
                self._emit({"state": "downloading", **self._counts(scope)})
                try:
                    titles = guides.resolve_titles([t["name"] for t in todo])
                except guides.WikiUnavailable as e:
                    self._emit({"state": "waiting", "message": str(e), **self._counts(scope)})
                    if not self._sleep(gen, event, self.down_retry):
                        return
                    continue
                if not self._sleep(gen, event, self.page_delay):
                    return
                for item in todo:
                    if self._gen != gen:
                        return
                    title = titles.get(item["name"])
                    if not title:
                        self.storage.mark_wiki_checked(item["id"], item["name"])
                        continue
                    try:
                        page = guides.fetch_live_title(title)
                    except guides.WikiUnavailable as e:
                        self._emit({"state": "waiting", "message": str(e), **self._counts(scope)})
                        if not self._sleep(gen, event, self.down_retry):
                            return
                        break
                    except Exception:
                        log.exception("Couldn't save the wiki page for %s", item["name"])
                        self.storage.mark_wiki_checked(item["id"], item["name"])
                        continue
                    if page:
                        self.storage.save_wiki_page(item["id"], item["name"], page.to_dict())
                    else:
                        self.storage.mark_wiki_checked(item["id"], item["name"])
                    self._emit({"state": "downloading", **self._counts(scope)})
                    if not self._sleep(gen, event, self.page_delay):
                        return
        except Exception:
            log.exception("Offline wiki library stopped")
            self._emit({"state": "error"})
