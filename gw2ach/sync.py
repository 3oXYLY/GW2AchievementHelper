from __future__ import annotations

import json
import logging
import time

from .api import GW2Client, GW2Error
from .storage import Storage

log = logging.getLogger("gw2ach")

REQUIRED_PERMISSIONS = ("account", "progression")
NAME_ENDPOINTS = {"item": "/v2/items", "skin": "/v2/skins", "mini": "/v2/minis", "title": "/v2/titles"}
ICON_KINDS = ("item", "skin", "mini")
PRICE_TTL = 15 * 60


class MissingPermissions(GW2Error):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("This API key is missing permission(s): " + ", ".join(missing))


def _noop(msg, frac=None):
    pass


def check_key(client: GW2Client) -> dict:
    info = client.tokeninfo()
    perms = set(info.get("permissions") or [])
    missing = [p for p in REQUIRED_PERMISSIONS if p not in perms]
    if missing:
        raise MissingPermissions(missing)
    account = client.account()
    log.info("Account fields returned by the API: %s", ", ".join(sorted(account)))
    return {"key_name": info.get("name") or "", "permissions": sorted(perms),
            "account_name": account.get("name") or "",
            "daily_ap": account.get("daily_ap"), "monthly_ap": account.get("monthly_ap")}


def save_key(storage: Storage, key: str, info: dict) -> None:
    previous = storage.get_setting("account_name")
    if previous and previous != info.get("account_name"):
        storage.clear_account()
    storage.save_api_key(key)
    storage.set_setting("account_name", info.get("account_name"))
    storage.set_setting("key_name", info.get("key_name"))
    storage.set_setting("key_permissions", json.dumps(info.get("permissions") or []))


def sync_all(storage: Storage, client: GW2Client, progress=_noop, full_refresh: bool = False) -> dict:
    progress("Checking your API key…", 0.01)
    info = check_key(client)
    storage.set_setting("account_name", info["account_name"])
    storage.set_setting("key_name", info["key_name"])
    storage.set_setting("key_permissions", json.dumps(info["permissions"]))
    for key in ("daily_ap", "monthly_ap"):
        value = info.get(key)
        if isinstance(value, int):
            storage.set_setting(key, value)
        else:
            storage.delete_setting(key)
    storage.set_setting("account_ap_checked", "1")

    progress("Getting the achievement list…", 0.03)
    all_ids = [int(i) for i in client.get("/v2/achievements")]
    same_lang = storage.get_setting("defs_lang") == client.lang
    have = storage.achievement_ids() if (same_lang and not full_refresh) else set()
    missing = [i for i in all_ids if i not in have]
    if missing:
        for done, total, batch in client.iter_bulk("/v2/achievements", missing):
            storage.upsert_achievements(batch)
            progress(f"Downloading achievement data {done:,}/{total:,}…", 0.05 + 0.75 * done / total)
    stale = storage.achievement_ids() - set(all_ids)
    if stale:
        storage.delete_achievements(stale)
    if not same_lang:
        storage.clear_names()
    storage.set_setting("defs_lang", client.lang)

    progress("Getting categories…", 0.84)
    groups = client.bulk("/v2/achievements/groups", client.get("/v2/achievements/groups"))
    categories = client.bulk("/v2/achievements/categories", client.get("/v2/achievements/categories"))
    storage.replace_categories(groups, categories)

    progress("Getting your progress…", 0.93)
    account_progress = client.account_achievements()
    storage.replace_progress(account_progress)
    storage.set_setting("last_sync", time.time())
    progress("Sync complete", 1.0)
    return {"account_name": info["account_name"], "downloaded": len(missing),
            "total": len(all_ids),
            "with_progress": len({p.get("id") for p in account_progress if isinstance(p, dict)})}


def missing_lookups(storage: Storage, wanted: dict[str, set[int]]) -> dict[str, set[int]]:
    missing = {}
    for kind, ids in wanted.items():
        known = storage.get_names(kind, ids)
        need = {i for i in ids if i not in known}
        if kind in ICON_KINDS:
            info = storage.get_item_info(kind, ids)
            need |= {i for i in ids if i not in info}
        if need:
            missing[kind] = need
    return missing


def resolve_names(storage: Storage, client: GW2Client, wanted: dict[str, set[int]]) -> int:
    saved = 0
    for kind, todo in missing_lookups(storage, wanted).items():
        endpoint = NAME_ENDPOINTS.get(kind)
        if not endpoint:
            continue
        names, info = {}, {}
        for entry in client.bulk(endpoint, sorted(todo)):
            if isinstance(entry, dict) and "id" in entry:
                eid = int(entry["id"])
                names[eid] = entry.get("name") or ""
                info[eid] = {"icon": entry.get("icon"), "item_id": entry.get("item_id")}
        for i in todo:
            names.setdefault(int(i), "")
            info.setdefault(int(i), {"icon": None, "item_id": None})
        storage.save_names(kind, names)
        if kind in ICON_KINDS:
            storage.save_item_info(kind, info)
        saved += len(names)
    return saved


def cached_prices(storage: Storage, item_ids) -> tuple[dict[int, dict], set[int]]:
    prices, missing = {}, set()
    for iid in item_ids:
        cached = storage.get_cache(f"price::{iid}", PRICE_TTL)
        if cached is None:
            missing.add(iid)
        else:
            prices[iid] = cached
    return prices, missing


def fetch_prices(storage: Storage, client: GW2Client, item_ids: set[int]) -> dict[int, dict]:
    prices, missing = cached_prices(storage, item_ids)
    todo = sorted(missing)
    if todo:
        found = {}
        for entry in client.bulk("/v2/commerce/prices", sorted(todo), localized=False):
            if isinstance(entry, dict) and "id" in entry:
                buys, sells = entry.get("buys") or {}, entry.get("sells") or {}
                found[int(entry["id"])] = {
                    "buy": buys.get("unit_price") if buys.get("quantity") else None,
                    "sell": sells.get("unit_price") if sells.get("quantity") else None}
        for iid in todo:
            value = found.get(iid, {"buy": None, "sell": None})
            storage.set_cache(f"price::{iid}", value)
            prices[iid] = value
    return prices
