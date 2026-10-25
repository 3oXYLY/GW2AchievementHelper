from __future__ import annotations

import json
import re
import time

_TAG_RE = re.compile(r"<[^>]+>")
STATUS_ORDER = {"progress": 0, "todo": 1, "locked": 2, "done": 3}


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value or "[]")
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return _TAG_RE.sub("", text).strip()


def summarize(tiers, point_cap, prog: dict | None) -> dict:
    tiers = [t for t in _json_list(tiers) if isinstance(t, dict)]
    last = int(tiers[-1].get("count") or 0) if tiers else 0
    tier_points = sum(int(t.get("points") or 0) for t in tiers)
    total = point_cap if isinstance(point_cap, int) and point_cap > 0 else tier_points

    if prog:
        current = int(prog.get("current") or 0)
        mx = int(prog.get("max") or 0) or last
        done = bool(prog.get("done"))
        repeated = int(prog.get("repeated") or 0)
        unlocked = prog.get("unlocked")
        unlocked = True if unlocked is None else bool(unlocked)
    else:
        current, mx, done, repeated, unlocked = 0, last, False, 0, True

    partial = sum(int(t.get("points") or 0) for t in tiers if current >= int(t.get("count") or 0))
    if repeated:
        earned = min(total, repeated * tier_points + (0 if done else partial))
    else:
        earned = tier_points if done else partial

    if repeated:
        key, label = "done", f"Done ×{repeated}"
    elif done:
        key, label = "done", "Done"
    elif not unlocked:
        key, label = "locked", "Locked"
    elif current > 0:
        key, label = "progress", "In progress"
    else:
        key, label = "todo", "Not started"

    pct = 1.0 if done else (min(current / mx, 1.0) if mx else 0.0)
    progress_text = "✓" if done and not repeated else (f"{current:,}/{mx:,}" if mx else "—")
    return {"current": current, "max": mx, "done": done, "repeated": repeated, "unlocked": unlocked,
            "earned": earned, "total": total, "pct": pct, "status_key": key, "status_label": label,
            "progress_text": progress_text}


def display_row(row: dict) -> dict:
    prog = None
    if row.get("has_progress"):
        prog = {k: row.get(k) for k in ("current", "max", "done", "repeated", "unlocked")}
    s = summarize(row.get("tiers"), row.get("point_cap"), prog)
    category = row.get("category") or "—"
    return {"id": row["id"], "name": row.get("name") or f"#{row['id']}", "category": category,
            "progress": s["progress_text"], "ap": f"{s['earned']}/{s['total']}" if s["total"] else "—",
            "status": s["status_label"], "status_key": s["status_key"], "pct": s["pct"],
            "earned": s["earned"], "total": s["total"], "current": s["current"], "max": s["max"],
            "done": s["done"], "repeated": s["repeated"], "tracked": bool(row.get("tracked")),
            "icon": row.get("icon") or row.get("category_icon")}


def sort_key(column: str):
    if column == "tracked":
        return lambda r: (not r["tracked"], r["name"].lower())
    if column == "name":
        return lambda r: r["name"].lower()
    if column == "category":
        return lambda r: (r["category"] == "—", r["category"].lower(), r["name"].lower())
    if column == "progress":
        return lambda r: (r["pct"], r["name"].lower())
    if column == "ap":
        return lambda r: (r["earned"], r["name"].lower())
    if column == "status":
        return lambda r: (STATUS_ORDER.get(r["status_key"], 9), -r["pct"], r["name"].lower())
    return lambda r: r["name"].lower()


def fill_requirement(requirement: str, tiers: list, current: int) -> str:
    requirement = clean_text(requirement)
    tiers = [t for t in tiers if isinstance(t, dict)]
    if "  " not in requirement or not tiers:
        return requirement
    target = next((int(t.get("count") or 0) for t in tiers if current < int(t.get("count") or 0)),
                  int(tiers[-1].get("count") or 0))
    return requirement.replace("  ", f" {target:,} ", 1)


def format_coins(count: int) -> str:
    count = int(count or 0)
    gold, silver, copper = count // 10000, (count // 100) % 100, count % 100
    parts = [f"{gold}g" if gold else "", f"{silver}s" if silver else "", f"{copper}c" if copper else ""]
    return " ".join(p for p in parts if p) or "0c"


def time_ago(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    days = secs // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


BIT_KINDS = {"Item": "item", "Skin": "skin", "Minipet": "mini"}


def wanted_names(a: dict) -> dict[str, set[int]]:
    wanted: dict[str, set[int]] = {}
    for b in a.get("bits") or []:
        kind = BIT_KINDS.get(b.get("type")) if isinstance(b, dict) else None
        if kind and isinstance(b.get("id"), int):
            wanted.setdefault(kind, set()).add(b["id"])
    for r in a.get("rewards") or []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        if r.get("type") == "Item":
            wanted.setdefault("item", set()).add(r["id"])
        elif r.get("type") == "Title":
            wanted.setdefault("title", set()).add(r["id"])
    return wanted


def bit_label(bit: dict, names: dict[str, dict[int, str]]) -> str:
    btype = bit.get("type")
    if btype == "Text":
        return clean_text(bit.get("text")) or "(unnamed objective)"
    kind = BIT_KINDS.get(btype)
    if kind:
        bid = bit.get("id")
        name = names.get(kind, {}).get(bid)
        if name is None:
            name = "loading…"
        elif not name:
            name = f"{btype} #{bid}"
        suffix = {"skin": " (skin)", "mini": " (mini)"}.get(kind, "")
        return name + suffix
    return clean_text(bit.get("text")) or str(btype or "objective")


def reward_label(reward: dict, names: dict[str, dict[int, str]]) -> str:
    rtype = reward.get("type")
    if rtype == "Coins":
        return format_coins(reward.get("count") or 0)
    if rtype == "Item":
        name = names.get("item", {}).get(reward.get("id"))
        name = "loading…" if name is None else (name or f"Item #{reward.get('id')}")
        count = int(reward.get("count") or 1)
        return f"{count}× {name}" if count > 1 else name
    if rtype == "Mastery":
        return f"Mastery point ({reward.get('region') or 'unknown region'})"
    if rtype == "Title":
        name = names.get("title", {}).get(reward.get("id"))
        name = "loading…" if name is None else (name or f"#{reward.get('id')}")
        return f"Title: {name}"
    return str(rtype or "Reward")


def missing_bits(a: dict) -> list[tuple[int, dict]]:
    prog = a.get("progress") or {}
    if prog.get("done"):
        return []
    done_bits = set(prog.get("bits") or [])
    return [(i, b) for i, b in enumerate(a.get("bits") or []) if isinstance(b, dict) and i not in done_bits]


def bit_item_id(bit: dict, mini_items: dict[int, int]) -> int | None:
    kind = BIT_KINDS.get(bit.get("type"))
    bid = bit.get("id")
    if kind == "item" and isinstance(bid, int):
        return bid
    if kind == "mini" and isinstance(bid, int):
        return mini_items.get(bid)
    return None


def price_targets(a: dict, mini_items: dict[int, int]) -> set[int]:
    return {iid for _, b in missing_bits(a) if (iid := bit_item_id(b, mini_items))}


def collection_cost(a: dict, mini_items: dict[int, int], prices: dict[int, dict]) -> dict:
    sell = buy = priced = unpriced = skins = 0
    for _, b in missing_bits(a):
        kind = BIT_KINDS.get(b.get("type"))
        if kind == "skin":
            skins += 1
            continue
        if kind not in ("item", "mini"):
            continue
        iid = bit_item_id(b, mini_items)
        p = prices.get(iid) if iid else None
        if p and p.get("sell"):
            priced += 1
            sell += p["sell"]
            buy += p.get("buy") or p["sell"]
        else:
            unpriced += 1
    return {"sell": sell, "buy": buy, "priced": priced, "unpriced": unpriced, "skins": skins}


def detail_segments(a: dict, names: dict[str, dict[int, str]], prereqs: dict[int, dict],
                    extra: dict | None = None) -> list:
    extra = extra or {}
    icons = extra.get("icons") or {}
    mini_items = extra.get("mini_items") or {}
    prices = extra.get("prices") or {}
    price_state = extra.get("price_state")
    out: list[tuple[str, tuple]] = []

    def add(text, *tags):
        out.append((text, tags))

    def img(path, size):
        if path:
            out.append(("", ("img", str(path), str(size))))
            add("  ")

    prog = a.get("progress")
    s = summarize(a.get("tiers"), a.get("point_cap"), prog)
    img(extra.get("icon"), 40)
    add(a.get("name") or f"Achievement #{a['id']}", "h1")
    if extra.get("tracked"):
        add("  ★", "h1", "star")
    add("\n")
    where = " › ".join(x for x in (a.get("group_name"), a.get("category")) if x) or "Uncategorized"
    add(where + "\n", "muted")
    add(s["status_label"], s["status_key"], "bold")
    line = f"    Progress {s['current']:,}/{s['max']:,}" if s["max"] else ""
    if s["total"]:
        line += f"    AP {s['earned']}/{s['total']}"
    add(line + "\n\n", "muted")

    desc = clean_text(a.get("description"))
    if desc:
        add("Description\n", "h2")
        add(desc + "\n\n")
    req = fill_requirement(a.get("requirement") or "", a.get("tiers") or [], s["current"])
    if req:
        add("Requirement\n", "h2")
        add(req + "\n\n")
    locked = clean_text(a.get("locked_text"))
    if locked and not s["unlocked"]:
        add("How to unlock\n", "h2")
        add(locked + "\n\n")

    tiers = [t for t in a.get("tiers") or [] if isinstance(t, dict)]
    if len(tiers) > 1 or (tiers and int(tiers[0].get("count") or 0) > 1):
        add("Tiers\n", "h2")
        for i, t in enumerate(tiers, 1):
            count = int(t.get("count") or 0)
            reached = s["done"] or s["current"] >= count
            add(f"{'✓' if reached else '○'}  Tier {i}: {count:,}  →  {t.get('points', 0)} AP\n",
                "done" if reached else "todo")
        add("\n")

    bits = [b for b in a.get("bits") or [] if isinstance(b, dict)]
    if bits:
        done_bits = set((prog or {}).get("bits") or [])
        got, need = [], []
        for i, b in enumerate(bits):
            (got if s["done"] or i in done_bits else need).append(b)
        add(f"Collection / objectives — {len(got)}/{len(bits)}\n", "h2")

        def bit_line(b, mark, tag, with_price):
            add(f"{mark}  ", tag)
            kind = BIT_KINDS.get(b.get("type"))
            img(icons.get((kind, b.get("id"))) if kind else None, 18)
            add(bit_label(b, names), tag)
            if with_price and kind in ("item", "mini"):
                iid = bit_item_id(b, mini_items)
                p = prices.get(iid) if iid else None
                if p is not None:
                    add(f"    {format_coins(p['sell'])}" if p.get("sell") else "    not on the Trading Post",
                        "muted")
            add("\n")

        if need:
            add(f"Still needed ({len(need)})\n", "h3")
            for b in need:
                bit_line(b, "○", "todo", True)
            cost_kinds = [BIT_KINDS.get(b.get("type")) for b in need]
            if any(k in ("item", "mini") for k in cost_kinds) and (price_state or prices):
                add("Cost to finish (Trading Post): ", "bold")
                if price_state == "loading":
                    add("checking prices…", "muted")
                elif price_state == "error":
                    add("couldn't load prices right now.", "muted")
                elif prices:
                    cost = collection_cost(a, mini_items, prices)
                    if cost["priced"]:
                        add(f"{format_coins(cost['sell'])} buying now  ·  "
                            f"{format_coins(cost['buy'])} with buy orders", "progress")
                    else:
                        add("nothing missing can be bought there", "muted")
                    notes = []
                    if cost["unpriced"]:
                        notes.append(f"{cost['unpriced']} not sold on the Trading Post")
                    if cost["skins"]:
                        notes.append(f"{cost['skins']} skins not priced")
                    if notes:
                        add("  (" + ", ".join(notes) + ")", "muted")
                add("\n")
        if got:
            add(f"Completed ({len(got)})\n", "h3")
            for b in got:
                bit_line(b, "✓", "done", False)
        add("\n")

    rewards = [r for r in a.get("rewards") or [] if isinstance(r, dict)]
    if rewards:
        add("Rewards\n", "h2")
        for r in rewards:
            add("•  ")
            if r.get("type") == "Item":
                img(icons.get(("item", r.get("id"))), 18)
            add(f"{reward_label(r, names)}\n")
        add("\n")

    pre = a.get("prerequisites") or []
    if pre:
        add("Requires first\n", "h2")
        for pid in pre:
            info = prereqs.get(pid) or {}
            name = info.get("name") or f"Achievement #{pid}"
            ok = info.get("done")
            add(f"{'✓' if ok else '○'}  {name}\n", "done" if ok else "todo")
        add("\n")

    flags = [f for f in a.get("flags") or [] if f not in ("CategoryDisplay", "MoveToTop", "RepairOnLogin")]
    meta = f"ID {a['id']}"
    if flags:
        meta += "   •   " + ", ".join(flags)
    add(meta + "\n", "muted")
    return out


PERIODIC_FLAGS = {"Daily", "Weekly", "Monthly"}


def ap_kind(flags) -> str:
    flags = set(_json_list(flags))
    if flags & PERIODIC_FLAGS:
        return "periodic"
    if "Repeatable" in flags:
        return "repeatable"
    return "permanent"


def build_overview(rows: list[dict], region_order: list[str] | None = None) -> dict:
    totals = {"done": 0, "total": 0, "earned": 0, "possible": 0, "earned_all": 0}
    ap = {"permanent": 0, "repeatable": 0, "periodic": 0, "repeatable_count": 0, "periodic_count": 0,
          "details": []}
    groups: dict[str, dict] = {}
    mastery: dict[str, dict] = {}
    for r in rows:
        prog = None
        if r.get("has_progress"):
            prog = {k: r.get(k) for k in ("current", "max", "done", "repeated", "unlocked")}
        s = summarize(r.get("tiers"), r.get("point_cap"), prog)
        kind = ap_kind(r.get("flags"))
        ap[kind] += s["earned"]
        if kind != "permanent" and prog:
            ap[f"{kind}_count"] += 1
            tiers = [t for t in _json_list(r.get("tiers")) if isinstance(t, dict)]
            ap["details"].append({
                "id": r.get("id"), "name": r.get("name") or "", "kind": kind,
                "current": s["current"], "max": s["max"], "done": s["done"], "repeated": s["repeated"],
                "tier_points": sum(int(t.get("points") or 0) for t in tiers),
                "point_cap": r.get("point_cap"), "earned": s["earned"]})
        if kind == "periodic":
            s = dict(s, earned=0, total=0)
        else:
            totals["earned_all"] += s["earned"]
        if r.get("category_id") is None:
            continue
        done = 1 if s["done"] or s["repeated"] else 0
        gname = r.get("group_name") or "Other"
        g = groups.setdefault(gname, {"name": gname, "order": r.get("group_order") or 9999, "done": 0,
                                      "total": 0, "earned": 0, "possible": 0, "categories": {}})
        cid = r["category_id"]
        c = g["categories"].setdefault(cid, {"id": cid, "name": r.get("category") or f"#{cid}",
                                             "order": r.get("category_order") or 0, "done": 0, "total": 0,
                                             "earned": 0, "possible": 0})
        for bucket in (totals, g, c):
            bucket["done"] += done
            bucket["total"] += 1
            bucket["earned"] += s["earned"]
            bucket["possible"] += s["total"]
        for reward in _json_list(r.get("rewards")):
            if isinstance(reward, dict) and reward.get("type") == "Mastery":
                region = reward.get("region") or "Unknown"
                m = mastery.setdefault(region, {"region": region, "earned": 0, "available": 0})
                m["available"] += 1
                m["earned"] += done
    ordered_groups = sorted(groups.values(), key=lambda g: (g["order"], g["name"]))
    for g in ordered_groups:
        g["categories"] = sorted(g["categories"].values(), key=lambda c: (c["order"], c["name"]))
    order = region_order or []
    ordered_mastery = sorted(mastery.values(),
                             key=lambda m: (order.index(m["region"]) if m["region"] in order else len(order),
                                            m["region"]))
    ap["details"].sort(key=lambda d: (d["kind"], -d["earned"], d["name"].lower()))
    return {"totals": totals, "groups": ordered_groups, "mastery": ordered_mastery, "ap": ap}


def ap_details_text(ap: dict, daily: int | None, monthly: int | None) -> str:
    lines = ["GW2 Achievement Helper - AP details",
             f"Permanent achievements: {ap['permanent']:,}",
             f"Repeatable achievements: {ap['repeatable']:,} ({ap['repeatable_count']} with progress)",
             f"Daily/weekly/monthly achievements (not added): {ap['periodic']:,} "
             f"({ap['periodic_count']} with progress)",
             f"daily_ap from account: {'missing' if daily is None else f'{daily:,}'}",
             f"monthly_ap from account: {'missing' if monthly is None else f'{monthly:,}'}",
             "", "id | name | kind | current/max | done | repeated | tier points | point_cap | counted AP"]
    for d in ap["details"]:
        lines.append(f"{d['id']} | {d['name']} | {d['kind']} | {d['current']}/{d['max']} | {d['done']} | "
                     f"{d['repeated']} | {d['tier_points']} | {d['point_cap']} | {d['earned']}")
    return "\n".join(lines)
