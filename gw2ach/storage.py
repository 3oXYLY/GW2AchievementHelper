from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

from . import secret

APP_DIR_NAME = "GW2AchievementHelper"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    requirement TEXT NOT NULL DEFAULT '',
    locked_text TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    flags TEXT NOT NULL DEFAULT '[]',
    tiers TEXT NOT NULL DEFAULT '[]',
    rewards TEXT NOT NULL DEFAULT '[]',
    bits TEXT NOT NULL DEFAULT '[]',
    prerequisites TEXT NOT NULL DEFAULT '[]',
    point_cap INTEGER,
    icon TEXT
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    ord INTEGER NOT NULL DEFAULT 0,
    icon TEXT,
    group_name TEXT,
    group_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS category_map (
    achievement_id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_category_map_cat ON category_map(category_id);
CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY,
    current INTEGER NOT NULL DEFAULT 0,
    max INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    bits TEXT NOT NULL DEFAULT '[]',
    repeated INTEGER,
    unlocked INTEGER
);
CREATE TABLE IF NOT EXISTS names (
    kind TEXT NOT NULL,
    id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS web_cache (
    query TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_pages (
    achievement_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    title TEXT,
    text TEXT,
    url TEXT,
    source TEXT,
    snapshot TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    fetched_at REAL NOT NULL DEFAULT 0,
    live_checked_at REAL
);
CREATE TABLE IF NOT EXISTS tracked (
    achievement_id INTEGER PRIMARY KEY,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    achievement_id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS item_info (
    kind TEXT NOT NULL,
    id INTEGER NOT NULL,
    icon TEXT,
    item_id INTEGER,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS completions (
    achievement_id INTEGER NOT NULL,
    completed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_completions_time ON completions(completed_at);
"""

LIBRARY_RECHECK = 30 * 24 * 3600
NEAR_SQL = ("(p.done = 0 AND p.max > 0 AND p.current * 1.0 / p.max >= 0.8"
            " AND a.flags NOT LIKE '%IgnoreNearlyComplete%')")
PCT_SQL = "(CASE WHEN p.max > 0 THEN p.current * 1.0 / p.max ELSE 0 END)"
REWARD_SQL = {
    "mastery": "a.rewards LIKE '%\"type\": \"Mastery\"%'",
    "title": "a.rewards LIKE '%\"type\": \"Title\"%'",
    "item": "a.rewards LIKE '%\"type\": \"Item\"%'",
}
REGION_ORDER = ["Tyria", "Maguuma", "Desert", "Tundra", "Jade", "Sky", "Wild", "Magic"]

ACCOUNT_SETTINGS = ("api_key", "account_name", "key_name", "key_permissions", "last_sync")


def data_dir() -> Path:
    override = os.environ.get("GW2ACH_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_DIR_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "gw2-achievement-helper"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _chunks(seq: list, size: int = 500):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


class Storage:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else data_dir() / "data.db"
        self._local = threading.local()
        conn = self._conn()
        conn.executescript(SCHEMA)
        conn.commit()
        if os.name == "posix":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def get_setting(self, key: str, default=None):
        row = self._conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value) -> None:
        conn = self._conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                         (key, None if value is None else str(value)))

    def delete_setting(self, key: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))

    def save_api_key(self, key: str) -> None:
        self.set_setting("api_key", secret.protect(key))

    def load_api_key(self) -> str | None:
        blob = self.get_setting("api_key")
        if not blob:
            return None
        try:
            return secret.unprotect(blob)
        except Exception:
            return None

    def has_unreadable_key(self) -> bool:
        return bool(self.get_setting("api_key")) and self.load_api_key() is None

    def api_key_encrypted(self) -> bool:
        return secret.is_encrypted(self.get_setting("api_key"))

    def clear_account(self) -> None:
        conn = self._conn()
        with conn:
            conn.executemany("DELETE FROM settings WHERE key=?", [(k,) for k in ACCOUNT_SETTINGS])
            conn.execute("DELETE FROM progress")

    def wipe_all(self) -> None:
        conn = self._conn()
        with conn:
            for table in ("settings", "achievements", "categories", "category_map", "progress", "names",
                          "web_cache", "wiki_pages", "tracked", "notes", "item_info", "completions"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("VACUUM")

    def achievement_ids(self) -> set[int]:
        return {r[0] for r in self._conn().execute("SELECT id FROM achievements")}

    def achievement_count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM achievements").fetchone()[0]

    def upsert_achievements(self, items: Iterable[dict]) -> int:
        rows = []
        for a in items:
            if not isinstance(a, dict) or "id" not in a:
                continue
            cap = a.get("point_cap")
            rows.append((
                int(a["id"]), a.get("name") or "", a.get("description") or "",
                a.get("requirement") or "", a.get("locked_text") or "", a.get("type") or "",
                json.dumps(a.get("flags") or []), json.dumps(a.get("tiers") or []),
                json.dumps(a.get("rewards") or []), json.dumps(a.get("bits") or []),
                json.dumps(a.get("prerequisites") or []),
                int(cap) if isinstance(cap, (int, float)) else None, a.get("icon"),
            ))
        conn = self._conn()
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO achievements (id, name, description, requirement, locked_text,"
                " type, flags, tiers, rewards, bits, prerequisites, point_cap, icon)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def delete_achievements(self, ids: Iterable[int]) -> None:
        conn = self._conn()
        with conn:
            conn.executemany("DELETE FROM achievements WHERE id=?", [(int(i),) for i in ids])

    def replace_categories(self, groups: list[dict], categories: list[dict]) -> None:
        group_of: dict[int, tuple[str, int]] = {}
        for g in groups:
            if not isinstance(g, dict):
                continue
            for cid in g.get("categories") or []:
                group_of[int(cid)] = (g.get("name") or "", int(g.get("order") or 0))

        cat_rows, map_rows, seen = [], [], set()
        for c in categories:
            if not isinstance(c, dict) or "id" not in c:
                continue
            cid = int(c["id"])
            gname, gorder = group_of.get(cid, (None, 9999))
            cat_rows.append((cid, c.get("name") or "", c.get("description") or "",
                             int(c.get("order") or 0), c.get("icon"), gname, gorder))
            for entry in c.get("achievements") or []:
                aid = entry.get("id") if isinstance(entry, dict) else entry
                if isinstance(aid, int) and aid not in seen:
                    seen.add(aid)
                    map_rows.append((aid, cid))
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM categories")
            conn.execute("DELETE FROM category_map")
            conn.executemany("INSERT OR REPLACE INTO categories (id, name, description, ord, icon, group_name,"
                             " group_order) VALUES (?,?,?,?,?,?,?)", cat_rows)
            conn.executemany("INSERT INTO category_map (achievement_id, category_id) VALUES (?,?)",
                             map_rows)

    def replace_progress(self, items: list[dict]) -> None:
        merged: dict[int, dict] = {}
        for p in items:
            if not isinstance(p, dict) or "id" not in p:
                continue
            aid = int(p["id"])
            cur = {"current": int(p.get("current") or 0), "max": int(p.get("max") or 0),
                   "done": bool(p.get("done")), "bits": set(p.get("bits") or []),
                   "repeated": p.get("repeated"), "unlocked": p.get("unlocked")}
            prev = merged.get(aid)
            if prev:
                cur["current"] = max(cur["current"], prev["current"])
                cur["max"] = max(cur["max"], prev["max"])
                cur["done"] = cur["done"] or prev["done"]
                cur["bits"] |= prev["bits"]
                reps = [r for r in (cur["repeated"], prev["repeated"]) if r is not None]
                cur["repeated"] = max(reps) if reps else None
                if prev["unlocked"] is not None or cur["unlocked"] is not None:
                    cur["unlocked"] = bool(prev["unlocked"]) or bool(cur["unlocked"])
            merged[aid] = cur
        rows = []
        for aid, p in merged.items():
            unlocked = p["unlocked"]
            rows.append((aid, p["current"], p["max"], 1 if p["done"] else 0,
                         json.dumps(sorted(p["bits"])), p["repeated"],
                         None if unlocked is None else (1 if unlocked else 0)))
        conn = self._conn()
        old = {r[0]: (bool(r[1]), int(r[2] or 0))
               for r in conn.execute("SELECT id, done, repeated FROM progress")}
        now = time.time()
        completed = []
        if old:
            for aid, p in merged.items():
                was_done, was_repeated = old.get(aid, (False, 0))
                if (p["done"] and not was_done) or int(p["repeated"] or 0) > was_repeated:
                    completed.append((aid, now))
        with conn:
            conn.executemany("INSERT INTO completions (achievement_id, completed_at) VALUES (?,?)", completed)
            conn.execute("DELETE FROM progress")
            conn.executemany("INSERT OR REPLACE INTO progress (id, current, max, done, bits, repeated, unlocked)"
                             " VALUES (?,?,?,?,?,?,?)", rows)

    def categories_list(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT c.id, c.name, c.group_name FROM categories c"
            " WHERE EXISTS (SELECT 1 FROM category_map m WHERE m.category_id = c.id)"
            " ORDER BY c.group_order, c.ord, c.name").fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        row = self._conn().execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN p.done = 1 THEN 1 ELSE 0 END), 0) AS done"
            " FROM category_map m LEFT JOIN progress p ON p.id = m.achievement_id"
            " JOIN achievements a ON a.id = m.achievement_id").fetchone()
        return {"total": row["total"], "done": row["done"]}

    def search(self, text: str = "", status: str = "all", category_id: int | None = None,
               include_uncategorized: bool = False, limit: int = 1500, view: str = "all",
               reward: str | None = None, search_wiki: bool = False, group: str | None = None,
               ids: list[int] | None = None, order: str | None = None) -> tuple[list[dict], bool]:
        if ids is not None and not ids:
            return [], False
        sql = ("SELECT a.id, a.name, a.tiers, a.point_cap, a.icon, c.name AS category, c.group_name,"
               " c.icon AS category_icon, p.current, p.max, p.done, p.repeated, p.unlocked,"
               " (p.id IS NOT NULL) AS has_progress, (t.achievement_id IS NOT NULL) AS tracked"
               " FROM achievements a"
               " LEFT JOIN category_map m ON m.achievement_id = a.id"
               " LEFT JOIN categories c ON c.id = m.category_id"
               " LEFT JOIN progress p ON p.id = a.id"
               " LEFT JOIN tracked t ON t.achievement_id = a.id"
               " LEFT JOIN notes n ON n.achievement_id = a.id")
        where, params = ["a.name <> ''"], []
        text = " ".join(text.split())
        for word in text.split(" ") if text else []:
            pat = f"%{_escape_like(word)}%"
            clause = ("a.name LIKE ? ESCAPE '\\' OR a.requirement LIKE ? ESCAPE '\\'"
                      " OR a.description LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\'"
                      " OR n.text LIKE ? ESCAPE '\\'")
            params += [pat] * 5
            if search_wiki:
                clause += (" OR EXISTS (SELECT 1 FROM wiki_pages w WHERE w.achievement_id = a.id"
                           " AND w.text LIKE ? ESCAPE '\\')")
                params.append(pat)
            where.append(f"({clause})")
        if ids is not None:
            where.append(f"a.id IN ({','.join('?' * len(ids))})")
            params += [int(i) for i in ids]
        if category_id is not None:
            where.append("m.category_id = ?")
            params.append(category_id)
        elif group is not None:
            if group == "Other":
                where.append("m.category_id IS NOT NULL AND c.group_name IS NULL")
            else:
                where.append("c.group_name = ?")
                params.append(group)
        elif not include_uncategorized and view != "tracked" and ids is None:
            where.append("m.category_id IS NOT NULL")
        if view == "tracked":
            where.append("t.achievement_id IS NOT NULL")
        elif view == "near":
            where.append(NEAR_SQL)
        if reward in REWARD_SQL:
            where.append(REWARD_SQL[reward])
        elif reward and reward.startswith("mastery:"):
            where.append("a.rewards LIKE ?")
            params.append(f'%"region": "{reward.split(":", 1)[1]}"%')
        if status == "done":
            where.append("p.done = 1")
        elif status == "todo":
            where.append("(p.done IS NULL OR p.done = 0)")
        elif status == "progress":
            where.append("p.done = 0 AND p.current > 0")
        sql += " WHERE " + " AND ".join(where)
        if order is None and view == "near" and not text:
            order = "pct"
        if order == "pct":
            sql += f" ORDER BY {PCT_SQL} DESC, a.name COLLATE NOCASE"
        elif text:
            sql += (" ORDER BY CASE WHEN a.name LIKE ? ESCAPE '\\' THEN 0"
                    " WHEN a.name LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END, a.name COLLATE NOCASE")
            params += [_escape_like(text), _escape_like(text) + "%"]
        else:
            sql += " ORDER BY a.name COLLATE NOCASE"
        sql += " LIMIT ?"
        params.append(limit + 1)
        rows = [dict(r) for r in self._conn().execute(sql, params).fetchall()]
        truncated = len(rows) > limit
        rows = rows[:limit]
        if ids is not None:
            position = {int(i): n for n, i in enumerate(ids)}
            rows.sort(key=lambda r: position.get(r["id"], len(position)))
        return rows, truncated

    def recent_completions(self, limit: int = 6) -> list[int]:
        return [r[0] for r in self._conn().execute(
            "SELECT achievement_id FROM completions GROUP BY achievement_id"
            " ORDER BY MAX(completed_at) DESC LIMIT ?", (limit,))]

    def get_achievement(self, aid: int) -> dict | None:
        row = self._conn().execute(
            "SELECT a.*, c.name AS category, c.group_name, c.icon AS category_icon FROM achievements a"
            " LEFT JOIN category_map m ON m.achievement_id = a.id"
            " LEFT JOIN categories c ON c.id = m.category_id WHERE a.id = ?", (aid,)).fetchone()
        if not row:
            return None
        a = dict(row)
        for key in ("flags", "tiers", "rewards", "bits", "prerequisites"):
            try:
                a[key] = json.loads(a[key] or "[]")
            except ValueError:
                a[key] = []
        prog = self._conn().execute("SELECT * FROM progress WHERE id = ?", (aid,)).fetchone()
        if prog:
            p = dict(prog)
            p["bits"] = json.loads(p["bits"] or "[]")
            a["progress"] = p
        else:
            a["progress"] = None
        return a

    def achievement_names(self, ids: Iterable[int]) -> dict[int, dict]:
        ids = [int(i) for i in ids]
        out: dict[int, dict] = {}
        for chunk in _chunks(ids):
            q = ",".join("?" * len(chunk))
            for r in self._conn().execute(
                    f"SELECT a.id, a.name, p.done FROM achievements a LEFT JOIN progress p ON p.id = a.id"
                    f" WHERE a.id IN ({q})", chunk):
                out[r["id"]] = {"name": r["name"], "done": bool(r["done"])}
        return out

    def get_names(self, kind: str, ids: Iterable[int]) -> dict[int, str]:
        ids = [int(i) for i in ids]
        out: dict[int, str] = {}
        for chunk in _chunks(ids):
            q = ",".join("?" * len(chunk))
            for r in self._conn().execute(f"SELECT id, name FROM names WHERE kind = ? AND id IN ({q})",
                                          [kind, *chunk]):
                out[r["id"]] = r["name"]
        return out

    def save_names(self, kind: str, mapping: dict[int, str]) -> None:
        conn = self._conn()
        with conn:
            conn.executemany("INSERT OR REPLACE INTO names (kind, id, name) VALUES (?,?,?)",
                             [(kind, int(i), n or "") for i, n in mapping.items()])

    def clear_names(self) -> None:
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM names")

    def get_cache(self, key: str, max_age: float):
        row = self._conn().execute("SELECT fetched_at, payload FROM web_cache WHERE query = ?",
                                   (key,)).fetchone()
        if not row or time.time() - row["fetched_at"] > max_age:
            return None
        try:
            return json.loads(row["payload"])
        except ValueError:
            return None

    def set_cache(self, key: str, payload) -> None:
        conn = self._conn()
        with conn:
            conn.execute("INSERT OR REPLACE INTO web_cache (query, fetched_at, payload) VALUES (?,?,?)",
                         (key, time.time(), json.dumps(payload)))

    def save_wiki_page(self, aid: int, name: str, page: dict) -> None:
        now = time.time()
        live = page.get("source") == "live"
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO wiki_pages (achievement_id, name, title, text, url, source,"
                " snapshot, status, fetched_at, live_checked_at) VALUES (?,?,?,?,?,?,?,'ok',?,?)",
                (int(aid), name, page.get("title"), page.get("text"), page.get("url"),
                 page.get("source"), page.get("snapshot"), now, now if live else None))

    def get_wiki_page(self, aid: int) -> dict | None:
        row = self._conn().execute(
            "SELECT title, text, url, source, snapshot, fetched_at FROM wiki_pages"
            " WHERE achievement_id = ? AND status = 'ok' AND text IS NOT NULL", (int(aid),)).fetchone()
        return dict(row) if row else None

    def mark_wiki_checked(self, aid: int, name: str) -> None:
        now = time.time()
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "UPDATE wiki_pages SET live_checked_at = ?,"
                " fetched_at = CASE WHEN status = 'missing' THEN ? ELSE fetched_at END"
                " WHERE achievement_id = ?", (now, now, int(aid)))
            if cur.rowcount == 0:
                conn.execute("INSERT INTO wiki_pages (achievement_id, name, status, fetched_at,"
                             " live_checked_at) VALUES (?,?,'missing',?,?)", (int(aid), name, now, now))

    @staticmethod
    def _library_from(scope: str) -> str:
        sql = (" FROM achievements a JOIN category_map m ON m.achievement_id = a.id"
               " LEFT JOIN progress p ON p.id = a.id"
               " LEFT JOIN wiki_pages w ON w.achievement_id = a.id WHERE a.name <> ''")
        if scope != "all":
            sql += " AND (p.done IS NULL OR p.done = 0)"
        return sql

    def library_todo(self, scope: str, limit: int) -> list[dict]:
        old = time.time() - LIBRARY_RECHECK
        rows = self._conn().execute(
            "SELECT a.id, a.name" + self._library_from(scope) +
            " AND (w.achievement_id IS NULL"
            "      OR (w.status = 'ok' AND w.source <> 'live'"
            "          AND (w.live_checked_at IS NULL OR w.live_checked_at < ?))"
            "      OR (w.status = 'missing' AND w.fetched_at < ?))"
            " ORDER BY CASE WHEN w.achievement_id IS NULL THEN 0 ELSE 1 END,"
            " CASE WHEN COALESCE(p.current, 0) > 0 THEN 0 ELSE 1 END, a.name COLLATE NOCASE"
            " LIMIT ?", (old, old, limit)).fetchall()
        return [dict(r) for r in rows]

    def library_counts(self, scope: str) -> dict:
        row = self._conn().execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(CASE WHEN w.status = 'ok' THEN 1 ELSE 0 END), 0) AS saved,"
            " COALESCE(SUM(CASE WHEN w.achievement_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS checked" +
            self._library_from(scope)).fetchone()
        return {"total": row["total"], "saved": row["saved"], "checked": row["checked"]}

    def library_size(self) -> tuple[int, int]:
        row = self._conn().execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM wiki_pages"
                                   " WHERE status = 'ok'").fetchone()
        return row[0], row[1]

    def clear_wiki_pages(self) -> None:
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM wiki_pages")

    def set_tracked(self, aid: int, on: bool) -> None:
        conn = self._conn()
        with conn:
            if on:
                conn.execute("INSERT OR IGNORE INTO tracked (achievement_id, added_at) VALUES (?,?)",
                             (int(aid), time.time()))
            else:
                conn.execute("DELETE FROM tracked WHERE achievement_id = ?", (int(aid),))

    def is_tracked(self, aid: int) -> bool:
        return self._conn().execute("SELECT 1 FROM tracked WHERE achievement_id = ?",
                                    (int(aid),)).fetchone() is not None

    def view_counts(self) -> dict:
        row = self._conn().execute(
            "SELECT (SELECT COUNT(*) FROM tracked t JOIN achievements a ON a.id = t.achievement_id)"
            " AS tracked, (SELECT COUNT(*) FROM progress p JOIN category_map m ON m.achievement_id = p.id"
            f" JOIN achievements a ON a.id = p.id WHERE {NEAR_SQL}) AS near").fetchone()
        return {"tracked": row["tracked"], "near": row["near"]}

    def get_note(self, aid: int) -> str:
        row = self._conn().execute("SELECT text FROM notes WHERE achievement_id = ?", (int(aid),)).fetchone()
        return row[0] if row else ""

    def set_note(self, aid: int, text: str) -> None:
        conn = self._conn()
        with conn:
            if text.strip():
                conn.execute("INSERT OR REPLACE INTO notes (achievement_id, text, updated_at) VALUES (?,?,?)",
                             (int(aid), text, time.time()))
            else:
                conn.execute("DELETE FROM notes WHERE achievement_id = ?", (int(aid),))

    def save_item_info(self, kind: str, mapping: dict[int, dict]) -> None:
        conn = self._conn()
        with conn:
            conn.executemany("INSERT OR REPLACE INTO item_info (kind, id, icon, item_id) VALUES (?,?,?,?)",
                             [(kind, int(i), v.get("icon"), v.get("item_id")) for i, v in mapping.items()])

    def get_item_info(self, kind: str, ids: Iterable[int]) -> dict[int, dict]:
        ids = [int(i) for i in ids]
        out: dict[int, dict] = {}
        for chunk in _chunks(ids):
            q = ",".join("?" * len(chunk))
            for r in self._conn().execute(
                    f"SELECT id, icon, item_id FROM item_info WHERE kind = ? AND id IN ({q})", [kind, *chunk]):
                out[r["id"]] = {"icon": r["icon"], "item_id": r["item_id"]}
        return out

    def mastery_regions(self) -> list[str]:
        regions = set()
        for (rewards,) in self._conn().execute(
                "SELECT a.rewards FROM achievements a JOIN category_map m ON m.achievement_id = a.id"
                " WHERE a.rewards LIKE '%\"type\": \"Mastery\"%'"):
            try:
                for r in json.loads(rewards):
                    if isinstance(r, dict) and r.get("type") == "Mastery" and r.get("region"):
                        regions.add(r["region"])
            except ValueError:
                continue
        known = [r for r in REGION_ORDER if r in regions]
        return known + sorted(regions - set(known))

    def overview_rows(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT a.id, a.name, a.flags, a.tiers, a.point_cap, a.rewards, m.category_id, c.name AS category,"
            " c.ord AS category_order, c.group_name, c.group_order, p.current, p.max, p.done, p.repeated,"
            " p.unlocked, (p.id IS NOT NULL) AS has_progress FROM achievements a"
            " LEFT JOIN category_map m ON m.achievement_id = a.id"
            " LEFT JOIN categories c ON c.id = m.category_id"
            " LEFT JOIN progress p ON p.id = a.id WHERE a.name <> ''").fetchall()
        return [dict(r) for r in rows]

    def category_icons(self) -> list[str]:
        return [r[0] for r in self._conn().execute(
            "SELECT DISTINCT icon FROM categories WHERE icon IS NOT NULL AND icon <> ''")]
