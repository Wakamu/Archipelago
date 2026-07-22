from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from BaseClasses import Item, ItemClassification

ITEM_QUALITIES = ("progression", "useful", "filler", "trap", "event")
QUALITY_LABELS = {
    "progression": "Progression",
    "useful": "Useful",
    "filler": "Filler",
    "trap": "Trap",
    "event": "Events",
}
QUALITY_COLORS = {
    "progression": "in_logic",
    "useful": "hinted_in_logic",
    "filler": "out_of_logic",
    "trap": "glitched",
    "event": "collected_light",
}


@dataclass
class InventoryEntry:
    name: str
    count: int
    qualities: set[str] = field(default_factory=set)


def item_qualities(item: Item) -> set[str]:
    if item.code is None:
        return {"event"}
    qualities: set[str] = set()
    if item.advancement:
        qualities.add("progression")
    if item.useful:
        qualities.add("useful")
    if item.trap:
        qualities.add("trap")
    if item.filler:
        qualities.add("filler")
    return qualities


def _resolve_world_item(ctx, item_name: str, item_flags: int) -> Item | None:
    if not ctx.tracker_core or not ctx.tracker_core.multiworld:
        return None
    try:
        world_item = ctx.tracker_core.multiworld.create_item(item_name, ctx.tracker_core.player_id)
        world_item.classification = world_item.classification | ItemClassification(item_flags)
        return world_item
    except Exception:
        return None


def build_inventory_entries(ctx, tracker_state=None) -> list[InventoryEntry]:
    if not ctx.tracker_core or not ctx.game or not ctx.tracker_core.multiworld:
        return []

    player_id = ctx.tracker_core.player_id
    item_id_to_name = ctx.tracker_core.multiworld.worlds[player_id].item_id_to_name
    counts: Counter[str] = Counter()
    qualities_by_name: dict[str, set[str]] = {}

    for network_item in ctx.tracker_items_received:
        if network_item.item <= 0:
            continue
        item_name = item_id_to_name.get(network_item.item)
        if not item_name:
            continue
        world_item = _resolve_world_item(ctx, item_name, network_item.flags)
        if world_item is None:
            continue
        counts[item_name] += 1
        qualities_by_name.setdefault(item_name, set()).update(item_qualities(world_item))

    for item_name in ctx.tracker_core.manual_items:
        counts[item_name] += 1
        qualities_by_name.setdefault(item_name, set()).add("progression")

    if tracker_state is not None:
        for event_name, event_count in Counter(tracker_state.events).items():
            counts[event_name] += event_count
            qualities_by_name.setdefault(event_name, set()).add("event")

    return [
        InventoryEntry(name=name, count=counts[name], qualities=qualities_by_name.get(name, set()))
        for name in sorted(counts)
    ]


def filter_inventory_entries(entries: list[InventoryEntry], enabled_qualities: set[str]) -> list[InventoryEntry]:
    if not enabled_qualities:
        return []
    return [entry for entry in entries if entry.qualities & enabled_qualities]


def format_inventory_entry(entry: InventoryEntry, get_color: Callable[[str], str]) -> str:
    if entry.count > 1:
        prefix = f"{entry.count}x "
    else:
        prefix = ""
    if not entry.qualities:
        return f"{prefix}{entry.name}"

    tags = []
    for quality in ITEM_QUALITIES:
        if quality in entry.qualities:
            color = get_color(QUALITY_COLORS[quality])
            tags.append(f"[color={color}]{QUALITY_LABELS[quality]}[/color]")
    return f"{prefix}{entry.name} ({', '.join(tags)})"


def inventory_summary(entries: list[InventoryEntry]) -> dict[str, int]:
    summary = {quality: 0 for quality in ITEM_QUALITIES}
    for entry in entries:
        for quality in entry.qualities:
            summary[quality] += entry.count
    return summary
