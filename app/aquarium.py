"""Decorating projects. The first is an aquarium; finished projects can be archived to a
gallery and a new one started (other project types can reuse this shape later)."""
import random
import tomllib
import uuid

from . import economy
from .config import ROOT
from .scheduler import utcnow

PROJECTS = "projects"
SHOP = ROOT / "shop.toml"


def shop() -> dict:
    with open(SHOP, "rb") as f:
        return tomllib.load(f)


def catalog() -> dict[str, dict]:
    return {i["id"]: i for i in shop()["item"]}


def _new_project(n: int) -> dict:
    return {"id": uuid.uuid4().hex[:10], "type": "aquarium", "name": f"Aquarium {n}", "status": "active",
            "created": utcnow().isoformat(), "archived_at": None, "items": [], "upgrades": [],
            "tank": {"background": None, "sand": None}}


def active(store) -> dict:
    projects = store.docs(PROJECTS)
    a = next((p for p in projects.values() if p["status"] == "active"), None)
    if not a:
        a = _new_project(len(projects) + 1)
        store.put_docs(PROJECTS, [a])
    return a


def owned_upgrades(store) -> set[str]:
    """Tank upgrades she has bought for any tank: they stay hers when she starts a new one."""
    return {u for p in store.docs(PROJECTS).values() for u in p.get("upgrades", [])}


def capacity(store) -> int:
    t = shop()["tank"]
    return t["big_capacity"] if "big-tank" in owned_upgrades(store) else t["capacity"]


def view(store) -> dict:
    p = active(store)
    items = catalog()
    upgrades = owned_upgrades(store)
    for it in items.values():
        it["owned"] = it["id"] in upgrades if it["category"] == "tank" else \
            sum(1 for x in p["items"] if x["item"] == it["id"])
    archived = sorted((x for x in store.docs(PROJECTS).values() if x["status"] == "archived"),
                      key=lambda x: x["archived_at"])
    return {"project": p, "capacity": capacity(store), "balance": economy.balance(store),
            "shop": list(items.values()), "gallery": archived}


def buy(store, item_id: str, rng=random) -> dict:
    item = catalog().get(item_id)
    if not item:
        raise ValueError("unknown item")
    p = active(store)
    if item["category"] == "tank":
        if item_id in owned_upgrades(store):
            raise ValueError("already owned")
    elif len(p["items"]) >= capacity(store):
        raise ValueError("the tank is full")
    if economy.balance(store) < item["price"]:
        raise ValueError("not enough credits")
    economy.award(store, "purchase", -item["price"], item_id)
    if item["category"] == "tank":
        p["upgrades"].append(item_id)
        _apply(p, item_id)
    else:
        swims = item["category"] == "fish"
        p["items"].append({"uid": uuid.uuid4().hex[:8], "item": item_id,
                           "x": round(rng.uniform(10, 85), 1),
                           "y": round(rng.uniform(15, 60), 1) if swims else 0})
    store.put_docs(PROJECTS, [p])
    return p


def _apply(p: dict, item_id: str) -> None:
    slot = "background" if item_id.startswith("bg-") else "sand" if item_id.startswith("sand-") else None
    if slot:
        p.setdefault("tank", {})[slot] = item_id


def use_upgrade(store, item_id: str | None, slot: str) -> dict:
    """Switch between owned backgrounds/sands (None = the default look)."""
    p = active(store)
    if item_id and item_id not in owned_upgrades(store):
        raise ValueError("not owned")
    p.setdefault("tank", {})[slot] = item_id
    store.put_docs(PROJECTS, [p])
    return p


def save_layout(store, positions: dict[str, dict]) -> bool:
    """positions: uid -> {x, y} (percent of tank). Returns True if anything moved."""
    p = active(store)
    moved = False
    for it in p["items"]:
        new = positions.get(it["uid"])
        if new:
            x, y = max(0, min(100, float(new["x"]))), max(0, min(100, float(new.get("y", it["y"]))))
            moved |= (x, y) != (it["x"], it["y"])
            it["x"], it["y"] = round(x, 1), round(y, 1)
    store.put_docs(PROJECTS, [p])
    return moved


def archive(store, name: str | None) -> dict:
    p = active(store)
    if not p["items"]:
        raise ValueError("add something to the tank before archiving it")
    p["status"], p["archived_at"] = "archived", utcnow().isoformat()
    if name:
        p["name"] = name.strip()[:40]
    store.put_docs(PROJECTS, [p])
    return active(store)


def stats(store) -> dict:
    p = active(store)
    items = catalog()
    corals = {i for i, it in items.items() if it["category"] == "coral"}
    owned = {x["item"] for x in p["items"]}
    bought = {r["detail"] for r in store.records(economy.LEDGER) if r["source"] == "purchase"}
    return {
        "fish_owned": sum(1 for x in p["items"] if items.get(x["item"], {}).get("category") == "fish"),
        "corals_complete": int(corals <= owned),
        "whale_shark": int("whale-shark" in bought),
        "projects_archived": sum(1 for x in store.docs(PROJECTS).values() if x["status"] == "archived"),
    }
