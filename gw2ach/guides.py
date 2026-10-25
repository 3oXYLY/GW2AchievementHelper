from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from . import __version__

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
TOOL_UA = f"GW2AchievementHelper/{__version__} (personal desktop tool)"
WIKI_BASE = "https://wiki.guildwars2.com"
ARCHIVE = "https://web.archive.org"

TRUSTED_SITES = {
    "wiki.guildwars2.com": "GW2 Wiki",
    "reddit.com": "Reddit",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "guildwars2.com": "Official",
    "gw2efficiency.com": "gw2efficiency",
    "guildjen.com": "GuildJen",
    "dulfy.net": "Dulfy",
    "fast.farming-community.eu": "Fast Farming",
    "snowcrows.com": "Snow Crows",
    "metabattle.com": "MetaBattle",
    "hardstuck.gg": "Hardstuck",
    "gw2mists.com": "GW2Mists",
    "steamcommunity.com": "Steam",
    "web.archive.org": "Web Archive",
}

_open = urlopen


class SearchError(Exception):
    pass


class WikiError(Exception):
    pass


class WikiUnavailable(WikiError):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str
    site: str
    trusted: bool

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class WikiPage:
    title: str
    text: str
    url: str
    source: str
    snapshot: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _get(url: str, data: bytes | None = None, timeout: float = 20, headers: dict | None = None) -> str:
    h = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    with _open(Request(url, data=data, headers=h), timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def default_query(name: str) -> str:
    return f"{name} gw2 achievement guide"


def _site_of(url: str) -> tuple[str, str, bool]:
    host = urlparse(url).netloc.lower().split(":")[0]
    for prefix in ("www.", "m.", "old.", "new."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    for domain, label in TRUSTED_SITES.items():
        if host == domain or host.endswith("." + domain):
            return host, label, True
    return host, host, False


def wiki_title(name: str) -> str:
    name = " ".join(name.split())
    return name[:1].upper() + name[1:]


def wiki_page_url(title: str) -> str:
    return f"{WIKI_BASE}/wiki/" + quote(wiki_title(title).replace(" ", "_"), safe="/:;@$!*(),~'")


def archive_url(url: str) -> str:
    return f"{ARCHIVE}/web/2026/{url}"


def quick_links(name: str) -> list[tuple[str, str]]:
    wiki = wiki_page_url(name)
    return [
        ("Wiki", wiki),
        ("Wiki (archived)", archive_url(wiki)),
        ("YouTube", "https://www.youtube.com/results?search_query=" + quote_plus(f"{name} gw2 achievement")),
        ("Reddit", "https://www.reddit.com/r/Guildwars2/search/?q=" + quote_plus(name)),
        ("Google", "https://www.google.com/search?q=" + quote_plus(f"{name} gw2 achievement")),
    ]


class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._field: str | None = None
        self._end_tag: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self.results.append({"title": "", "url": a.get("href") or "", "snippet": ""})
            self._field, self._end_tag = "title", "a"
        elif "result__snippet" in classes and self.results:
            self._field, self._end_tag = "snippet", tag

    def handle_endtag(self, tag):
        if self._field and tag == self._end_tag:
            self._field = self._end_tag = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target or href
    return href


def parse_ddg(html: str) -> list[dict]:
    p = _DDGParser()
    p.feed(html)
    out = []
    for r in p.results:
        url = _ddg_url(r["url"])
        if not url.startswith("http") or "duckduckgo.com/y.js" in url or "/y.js?" in r["url"]:
            continue
        out.append({"title": " ".join(r["title"].split()), "url": url,
                    "snippet": " ".join(r["snippet"].split())})
    return out


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._in_result = 0
        self._in_h2 = False
        self._field: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "li":
            if "b_algo" in classes:
                self.results.append({"title": "", "url": "", "snippet": ""})
                self._in_result = 1
            elif self._in_result:
                self._in_result += 1
            return
        if not self._in_result:
            return
        cur = self.results[-1]
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and not cur["url"]:
            cur["url"] = a.get("href") or ""
            self._field = "title"
        elif tag == "p" and not cur["snippet"]:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag == "li" and self._in_result:
            self._in_result -= 1
            self._field = None
        elif tag == "h2":
            self._in_h2 = False
            if self._field == "title":
                self._field = None
        elif tag == "a" and self._field == "title":
            self._field = None
        elif tag == "p" and self._field == "snippet":
            self._field = None

    def handle_data(self, data):
        if self._field and self._in_result and self.results:
            self.results[-1][self._field] += data


def _bing_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
        u = parse_qs(parsed.query).get("u", [""])[0]
        if u.startswith("a1"):
            b64 = u[2:] + "=" * (-len(u[2:]) % 4)
            try:
                return base64.urlsafe_b64decode(b64).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass
    return url


def parse_bing(html: str) -> list[dict]:
    p = _BingParser()
    p.feed(html)
    out = []
    for r in p.results:
        url = _bing_url(r["url"])
        if url.startswith("http") and r["title"].strip():
            out.append({"title": " ".join(r["title"].split()), "url": url,
                        "snippet": " ".join(r["snippet"].split())})
    return out


def _search_ddg(query: str) -> list[dict]:
    html = _get("https://html.duckduckgo.com/html/",
                data=urlencode({"q": query, "kl": "us-en"}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Referer": "https://html.duckduckgo.com/"})
    return parse_ddg(html)


def _search_bing(query: str) -> list[dict]:
    html = _get("https://www.bing.com/search?" + urlencode({"q": query, "setlang": "en", "cc": "US"}))
    return parse_bing(html)


def _rank(raw: list[dict]) -> list[SearchResult]:
    seen, out = set(), []
    for r in raw:
        key = r["url"].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        domain, site, trusted = _site_of(r["url"])
        out.append(SearchResult(r["title"] or r["url"], r["url"], r["snippet"], domain, site, trusted))
    out.sort(key=lambda x: not x.trusted)
    return out


def web_search(query: str, max_results: int = 15) -> tuple[list[SearchResult], str]:
    errors = []
    for engine_name, engine in (("DuckDuckGo", _search_ddg), ("Bing", _search_bing)):
        try:
            raw = engine(query)
        except Exception as e:
            errors.append(f"{engine_name}: {e}")
            continue
        if raw:
            return _rank(raw)[:max_results], engine_name
        errors.append(f"{engine_name}: no results")
    raise SearchError("; ".join(errors))


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
         "source", "track", "wbr"}
_SKIP_TAGS = {"script", "style", "noscript", "sup", "template", "button"}
_SKIP_CLASSES = {"navbox", "toc", "mw-editsection", "noprint", "reference", "references",
                 "mw-references-wrap", "catlinks", "printfooter", "mw-empty-elt", "mw-jump-link"}
_BLOCK = {"p", "div", "ul", "ol", "dl", "table", "tbody", "thead", "section", "blockquote",
          "pre", "center", "figure", "figcaption", "caption"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.cells: list[int] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br" and not self.skip:
                self.parts.append("\n")
            return
        if self.skip:
            self.skip += 1
            return
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        style = (a.get("style") or "").replace(" ", "").lower()
        if (tag in _SKIP_TAGS or classes & _SKIP_CLASSES or a.get("id") == "toc"
                or "display:none" in style):
            self.skip = 1
            return
        if tag in _HEADINGS:
            self.parts.append("\n\n## ")
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag == "dt":
            self.parts.append("\n")
        elif tag == "dd":
            self.parts.append("\n    ")
        elif tag == "tr":
            self.parts.append("\n")
            self.cells.append(0)
        elif tag in ("td", "th"):
            if self.cells:
                if self.cells[-1]:
                    self.parts.append("  |  ")
                self.cells[-1] += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.skip:
            self.skip -= 1
            return
        if tag in _HEADINGS:
            self.parts.append("\n")
        elif tag == "tr":
            if self.cells:
                self.cells.pop()
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        text = re.sub(r"\s+", " ", data)
        if text.strip():
            self.parts.append(text)
        elif text and self.parts and not self.parts[-1].endswith((" ", "\n")):
            self.parts.append(" ")


def html_to_text(html: str, limit: int = 30000) -> str:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    lines = []
    for raw in "".join(p.parts).split("\n"):
        line = raw.strip()
        if line.startswith("|"):
            line = line.lstrip("| ").strip()
        if line.endswith("|"):
            line = line.rstrip("| ").strip()
        lines.append(line)
    out, blank = [], False
    for line in lines:
        if line in ("", "•", "##"):
            blank = True
            continue
        if blank and out:
            out.append("")
        blank = False
        out.append(line)
    text = "\n".join(out).strip()
    return text[:limit]


def _looks_unavailable(text: str) -> bool:
    low = text.lower()
    return "temporarily unavailable" in low or "technical issues" in low[:400]


def extract_mw_content(html: str) -> str | None:
    i = html.find('id="mw-content-text"')
    if i < 0:
        return None
    start = html.rfind("<", 0, i)
    ends = [html.find(m, i) for m in ('id="catlinks"', 'class="printfooter"', 'id="mw-navigation"',
                                      'id="footer"')]
    ends = [e for e in ends if e > 0]
    end = min(ends) if ends else len(html)
    end = html.rfind("<", i, end) if ends else end
    return html[start:end]


def _wiki_api(params: dict, timeout: float = 15) -> dict:
    query = dict(params)
    query.update({"format": "json", "formatversion": "2", "maxlag": "5"})
    url = f"{WIKI_BASE}/api.php?" + urlencode(query)
    try:
        raw = _get(url, timeout=timeout, headers={"User-Agent": TOOL_UA})
    except Exception as e:
        raise WikiUnavailable(f"The wiki can't be reached ({e}).") from e
    try:
        data = json.loads(raw)
    except ValueError:
        raise WikiUnavailable("The wiki is down for maintenance.") from None
    if not isinstance(data, dict):
        raise WikiUnavailable("Unexpected answer from the wiki.")
    err = data.get("error")
    if isinstance(err, dict) and err.get("code") in ("maxlag", "readonly"):
        raise WikiUnavailable("The wiki is busy right now.")
    return data


_BAD_TITLE_CHARS = set("|#<>[]{}")


def resolve_titles(names: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {n: None for n in names}
    wanted = {}
    for n in names:
        t = wiki_title(n)
        if t and not (set(t) & _BAD_TITLE_CHARS):
            wanted[n] = (f"{t} (achievement)", t)
    if not wanted:
        return out
    titles = [t for pair in wanted.values() for t in pair]
    data = _wiki_api({"action": "query", "titles": "|".join(titles), "redirects": "1"})
    q = data.get("query") or {}
    norm = {x.get("from"): x.get("to") for x in q.get("normalized") or []}
    redirects = {x.get("from"): x.get("to") for x in q.get("redirects") or []}
    exists = {p.get("title") for p in q.get("pages") or []
              if isinstance(p, dict) and not p.get("missing") and not p.get("invalid")}

    def final(title):
        title = norm.get(title, title)
        for _ in range(5):
            if title not in redirects:
                break
            title = redirects[title]
        return title

    for name, candidates in wanted.items():
        for cand in candidates:
            if final(cand) in exists:
                out[name] = final(cand)
                break
    return out


def fetch_live_title(title: str) -> WikiPage | None:
    data = _wiki_api({"action": "parse", "page": title, "prop": "text", "redirects": "1"}, timeout=20)
    if "error" in data:
        return None
    parse = data.get("parse") or {}
    text = html_to_text(parse.get("text") or "")
    if not text or _looks_unavailable(text):
        return None
    real = parse.get("title") or title
    return WikiPage(real, text, wiki_page_url(real), "live")


def _fetch_live(name: str) -> WikiPage | None:
    title = resolve_titles([name]).get(name)
    return fetch_live_title(title) if title else None


def _archive_keys(title: str) -> list[str]:
    path = title.replace(" ", "_")
    keys = []
    for safe in ("/:;@$!*(),~'", "/:"):
        key = "wiki.guildwars2.com/wiki/" + quote(path, safe=safe)
        if key not in keys:
            keys.append(key)
    return keys


def _fetch_archive(name: str) -> WikiPage | None:
    title = wiki_title(name)
    reached_archive = False
    for candidate in (f"{title} (achievement)", title):
        for key in _archive_keys(candidate):
            cdx = f"{ARCHIVE}/cdx/search/cdx?" + urlencode({
                "url": key, "output": "json", "filter": "statuscode:200",
                "fl": "timestamp,original", "limit": "-6", "fastLatest": "true"})
            try:
                rows = json.loads(_get(cdx, timeout=30) or "[]")
                reached_archive = True
            except Exception:
                continue
            snaps = [r for r in rows if isinstance(r, list) and len(r) >= 2 and r[0] != "timestamp"]
            for ts, original in sorted(snaps, reverse=True)[:4]:
                try:
                    html = _get(f"{ARCHIVE}/web/{ts}id_/{original}", timeout=40)
                except Exception:
                    continue
                content = extract_mw_content(html)
                if not content:
                    continue
                text = html_to_text(content)
                if len(text) < 40 or _looks_unavailable(text):
                    continue
                return WikiPage(candidate, text, f"{ARCHIVE}/web/{ts}/{original}", "archive", ts)
    if not reached_archive:
        raise WikiError("Couldn't reach web.archive.org either - check your internet connection.")
    return None


def fetch_wiki(name: str) -> WikiPage:
    try:
        page = _fetch_live(name)
    except WikiUnavailable:
        page = None
    if page:
        return page
    page = _fetch_archive(name)
    if page:
        return page
    raise WikiError("No wiki page found for this achievement (live wiki or archive). "
                    "Try the web search instead.")
