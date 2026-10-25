from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from . import __version__

log = logging.getLogger("gw2ach")

USER_AGENT = f"GW2AchievementHelper/{__version__}"
ALLOWED_HOSTS = ("https://render.guildwars2.com/",)

_open = urlopen


class IconCache:
    def __init__(self, folder: Path, notify=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.notify = notify or (lambda: None)
        self._queue: list[str] = []
        self._queued: set[str] = set()
        self._failed: set[str] = set()
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False

    def file_for(self, url: str) -> Path:
        return self.folder / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:24] + ".png")

    def path(self, url: str | None) -> Path | None:
        if not url:
            return None
        f = self.file_for(url)
        return f if f.exists() else None

    def want(self, urls) -> None:
        added = False
        with self._lock:
            for url in urls:
                if (not url or url in self._queued or url in self._failed
                        or not url.startswith(ALLOWED_HOSTS) or self.file_for(url).exists()):
                    continue
                self._queue.append(url)
                self._queued.add(url)
                added = True
            if added and self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="icons")
                self._thread.start()
        if added:
            self._event.set()

    def close(self) -> None:
        self._closed = True
        self._event.set()

    def _run(self) -> None:
        idle_rounds = 0
        while not self._closed:
            with self._lock:
                url = self._queue.pop() if self._queue else None
                if url is None and idle_rounds >= 3:
                    self._thread = None
                    return
            if url is None:
                idle_rounds += 1
                self._event.wait(2)
                self._event.clear()
                continue
            idle_rounds = 0
            target = self.file_for(url)
            try:
                with _open(Request(url, headers={"User-Agent": USER_AGENT}), timeout=20) as resp:
                    data = resp.read()
                if not data.startswith(b"\x89PNG"):
                    raise ValueError("not a PNG")
                tmp = target.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(target)
            except Exception as e:
                log.info("Icon download failed for %s: %s", url, e)
                with self._lock:
                    self._failed.add(url)
            finally:
                with self._lock:
                    self._queued.discard(url)
            try:
                self.notify()
            except Exception:
                pass
