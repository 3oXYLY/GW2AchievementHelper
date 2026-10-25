from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import __version__

API_BASE = "https://api.guildwars2.com"
USER_AGENT = f"GW2AchievementHelper/{__version__}"
BATCH_SIZE = 200
LANGS = ("en", "de", "fr", "es", "zh")


class GW2Error(Exception):
    pass


class AuthError(GW2Error):
    pass


class NetworkError(GW2Error):
    pass


def _error_text(err: HTTPError) -> str:
    try:
        body = err.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            return str(data.get("text") or data.get("error") or "")
    except ValueError:
        pass
    return body[:200]


class GW2Client:
    def __init__(self, api_key: str | None = None, lang: str = "en", timeout: float = 25,
                 opener=None, retries: int = 4):
        self.api_key = api_key
        self.lang = lang if lang in LANGS else "en"
        self.timeout = timeout
        self.retries = retries
        self._open = opener or urlopen

    def get(self, path: str, params: dict | None = None, auth: bool = False, localized: bool = False):
        params = dict(params or {})
        if localized:
            params["lang"] = self.lang
        url = API_BASE + path + ("?" + urlencode(params, safe=",") if params else "")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if auth:
            if not self.api_key:
                raise AuthError("No API key set.")
            headers["Authorization"] = "Bearer " + self.api_key

        delay = 1.0
        last_error: Exception = NetworkError("Request failed")
        for _ in range(self.retries):
            try:
                with self._open(Request(url, headers=headers), timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                try:
                    return json.loads(body)
                except ValueError:
                    raise GW2Error("The GW2 API sent an unexpected response.")
            except HTTPError as e:
                text = _error_text(e)
                low = text.lower()
                if e.code == 404 and "all ids provided are invalid" in low:
                    return []
                if e.code in (401, 403) or (e.code == 400 and ("key" in low or "token" in low)):
                    raise AuthError(text or f"HTTP {e.code}")
                if e.code in (429, 500, 502, 503, 504):
                    last_error = GW2Error(f"The GW2 API is busy or down (HTTP {e.code}). {text}".strip())
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise GW2Error(f"GW2 API error (HTTP {e.code}). {text}".strip())
            except (URLError, TimeoutError, ConnectionError, OSError) as e:
                last_error = NetworkError(f"Couldn't reach the GW2 API ({getattr(e, 'reason', e)}).")
                time.sleep(delay)
                delay *= 2
        raise last_error

    def tokeninfo(self) -> dict:
        return self.get("/v2/tokeninfo", auth=True)

    def account(self) -> dict:
        return self.get("/v2/account", auth=True)

    def account_achievements(self) -> list:
        return self.get("/v2/account/achievements", auth=True)

    def iter_bulk(self, path: str, ids, localized: bool = True):
        ids = list(ids)
        total = len(ids)
        for i in range(0, total, BATCH_SIZE):
            chunk = ids[i:i + BATCH_SIZE]
            data = self.get(path, {"ids": ",".join(str(x) for x in chunk)}, localized=localized)
            if isinstance(data, dict):
                data = [data]
            yield min(i + BATCH_SIZE, total), total, data or []

    def bulk(self, path: str, ids, localized: bool = True) -> list:
        out: list = []
        for _, _, batch in self.iter_bulk(path, ids, localized):
            out.extend(batch)
        return out
