from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from Utils import local_path
from worlds import AutoWorld


VISUAL_PACKS_FOLDER = "visual_packs"


@dataclass(frozen=True)
class VisualPresetEntry:
    path: str
    game: str
    name: str


def visual_packs_dir() -> Path:
    path = Path(local_path(VISUAL_PACKS_FOLDER))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_preset_manifest(path: Path) -> dict | None:
    if not is_zipfile(path):
        return None
    try:
        with ZipFile(path) as archive:
            manifest_name = None
            for candidate in ("mapping.json", "preset.json"):
                try:
                    archive.getinfo(candidate)
                    manifest_name = candidate
                    break
                except KeyError:
                    continue
            if manifest_name is None:
                return None
            return json.loads(archive.read(manifest_name).decode("utf-8-sig"))
    except Exception:
        return None


def list_visual_presets() -> list[VisualPresetEntry]:
    entries: list[VisualPresetEntry] = []
    for path in sorted(visual_packs_dir().glob("*.zip"), key=lambda p: p.name.lower()):
        manifest = _read_preset_manifest(path)
        game = (manifest or {}).get("game") or path.stem
        entries.append(VisualPresetEntry(path=str(path.resolve()), game=game, name=path.name))
    return entries


def can_load_mapping_preset(ctx) -> bool:
    if not ctx.game:
        return False
    return ctx.game in AutoWorld.AutoWorldRegister.world_types


def get_mapping_preset_block_reason(ctx) -> str | None:
    if not ctx.game:
        return "Connect to a slot before loading a mapping preset."
    if ctx.game not in AutoWorld.AutoWorldRegister.world_types:
        return f"The connected game ({ctx.game}) is not installed in this Archipelago install."
    return None


def _marker_locations(marker: dict) -> list[str]:
    locations = marker.get("locations")
    if locations is None and "location" in marker:
        locations = [marker["location"]]
    return [location for location in (locations or []) if location]


def _make_tab(
    name: str,
    *,
    image_source: str = "",
    image_archive_path: str = "",
    source_archive_path: str | None = None,
    markers: list[dict] | None = None,
    location_size: int | None = None,
    children: list[dict] | None = None,
) -> dict:
    tab = {
        "name": name,
        "image_source": image_source,
        "image_archive_path": image_archive_path,
        "source_archive_path": source_archive_path,
        "markers": markers or [],
        "coords": {},
        "location_ids": [],
        "location_size": location_size,
    }
    if children is not None:
        tab["children"] = children
    return tab


def _tab_at_path(tabs: list[dict], path: list[int]) -> dict | None:
    current = tabs
    tab: dict | None = None
    for index in path:
        if index < 0 or index >= len(current):
            return None
        tab = current[index]
        current = tab.get("children", [])
    return tab


def _siblings_at_depth(tabs: list[dict], path: list[int], depth: int) -> list[dict]:
    if depth == 0:
        return tabs
    parent = _tab_at_path(tabs, path[:depth])
    if parent is None:
        return []
    return parent.get("children", [])


def _resolve_leaf_path(tabs: list[dict], path: list[int]) -> list[int]:
    resolved = list(path)
    while True:
        tab = _tab_at_path(tabs, resolved)
        if tab is None or not tab.get("children"):
            return resolved
        resolved.append(0)


def _iter_leaf_tabs(tabs: list[dict]):
    for tab in tabs:
        children = tab.get("children")
        if children:
            yield from _iter_leaf_tabs(children)
        else:
            yield tab


def _path_to_label(tabs: list[dict], path: list[int]) -> str:
    parts: list[str] = []
    for depth in range(len(path)):
        siblings = _siblings_at_depth(tabs, path, depth)
        index = path[depth]
        if 0 <= index < len(siblings):
            parts.append(siblings[index]["name"])
    return " / ".join(parts)


def _load_manifest_tab(
    ctx,
    manifest_tab: dict,
    *,
    root_path: str,
    preset_path: str,
    fallback_name: str,
) -> dict:
    child_manifests = manifest_tab.get("tabs")
    if child_manifests is not None:
        return _make_tab(
            manifest_tab.get("name", fallback_name),
            children=[
                _load_manifest_tab(
                    ctx,
                    child,
                    root_path=root_path,
                    preset_path=preset_path,
                    fallback_name=f"Tab {index}",
                )
                for index, child in enumerate(child_manifests, start=1)
            ],
        )

    image_path = manifest_tab.get("image", "")
    tab = _make_tab(
        manifest_tab.get("name", fallback_name),
        image_source=f"{root_path}/{image_path}" if image_path else "",
        image_archive_path=image_path,
        source_archive_path=preset_path,
        markers=[
            {
                "x": int(marker["x"]),
                "y": int(marker["y"]),
                "locations": _marker_locations(marker),
                "label": marker.get("label"),
                "size": marker.get("size"),
            }
            for marker in manifest_tab.get("markers", [])
            if _marker_locations(marker)
        ],
        location_size=manifest_tab.get("location_size"),
    )
    _rebuild_tab_runtime(ctx, tab)
    return tab


def _rebuild_tab_runtime(ctx, tab: dict) -> None:
    location_name_to_id = AutoWorld.AutoWorldRegister.world_types[ctx.game].location_name_to_id
    available_ids = set(ctx.server_locations)
    coords = {}
    location_ids: set[int] = set()
    deduped_markers = []
    for marker in tab.get("markers", []):
        marker_locations = _marker_locations(marker)
        section_ids = [
            location_name_to_id[name]
            for name in marker_locations
            if name in location_name_to_id and location_name_to_id[name] in available_ids
        ]
        if not section_ids:
            continue
        clean_marker = {
            "x": int(marker["x"]),
            "y": int(marker["y"]),
            "locations": marker_locations,
        }
        if marker.get("label"):
            clean_marker["label"] = marker["label"]
        if marker.get("size") is not None:
            clean_marker["size"] = int(marker["size"])
        deduped_markers.append(clean_marker)
        coords[(clean_marker["x"], clean_marker["y"])] = (
            section_ids,
            clean_marker.get("size"),
            clean_marker.get("label"),
        )
        location_ids.update(section_ids)
    tab["markers"] = deduped_markers
    tab["coords"] = coords
    tab["location_ids"] = sorted(location_ids)


def _display_tab(ctx, tab: dict) -> None:
    ctx.ui.mapping_current_tab = _path_to_label(ctx.mapping_tabs, ctx.mapping_tab_path)
    ctx.ui.mapping_source = tab.get("image_source", "")
    location_size = tab.get("location_size")
    ctx.ui.mapping_loc_size = int(location_size) if location_size is not None else 32
    ctx.mapping_coord_dict = ctx.mapping_page.load_coords(
        tab["coords"],
        ctx.use_split,
        int(ctx.ui.mapping_loc_size),
        on_select=getattr(ctx, "select_mapping_pin", None),
    )


def clear_mapping_state(ctx, empty_label: str = "No preset loaded") -> None:
    ctx.mapping_coord_dict = {}
    ctx.mapping_tabs = []
    ctx.mapping_tab_path = []
    ctx.mapping_tab_index = None
    ctx.mapping_root_path = None
    ctx.mapping_preset_path = None
    if hasattr(ctx, "selected_mapping_pin"):
        ctx.selected_mapping_pin = None
    if ctx.ui:
        ctx.ui.mapping_source = ""
        ctx.ui.mapping_current_tab = empty_label
        ctx.ui.mapping_preset_path = ""
        if hasattr(ctx.ui, "update_mapping_selection"):
            ctx.ui.update_mapping_selection("Selection: none", "Click a map pin to inspect its locations.")
        if ctx.mapping_page is not None:
            loc_size = int(ctx.ui.mapping_loc_size) if ctx.ui.mapping_loc_size else 32
            ctx.mapping_page.load_coords({}, ctx.use_split, loc_size)
        if hasattr(ctx.ui, "refresh_mapping_tab_selectors"):
            ctx.ui.refresh_mapping_tab_selectors()
        if hasattr(ctx.ui, "repaint_visual_packs_list"):
            ctx.ui.repaint_visual_packs_list()


def load_mapping_preset(ctx, logger: logging.Logger, preset_path: str | None = None) -> None:
    if not ctx.ui:
        return
    block_reason = get_mapping_preset_block_reason(ctx)
    if block_reason:
        logger.info(block_reason)
        return
    if preset_path is None:
        logger.info("No mapping preset path provided.")
        return

    try:
        if not is_zipfile(preset_path):
            logger.error("Selected mapping preset is not a zip archive.")
            return

        with ZipFile(preset_path) as archive:
            manifest_name = None
            for candidate in ("mapping.json", "preset.json"):
                try:
                    archive.getinfo(candidate)
                    manifest_name = candidate
                    break
                except KeyError:
                    continue
            if manifest_name is None:
                logger.error("Mapping preset archive must contain mapping.json or preset.json.")
                return
            manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))

        root_path = f"ap:zip:{preset_path}"
        tabs = [
            _load_manifest_tab(
                ctx,
                manifest_tab,
                root_path=root_path,
                preset_path=preset_path,
                fallback_name=f"Tab {index}",
            )
            for index, manifest_tab in enumerate(manifest.get("tabs", []), start=1)
        ]

        ctx.mapping_tabs = tabs
        ctx.mapping_root_path = root_path
        ctx.mapping_preset_path = preset_path
        if ctx.ui:
            ctx.ui.mapping_preset_path = preset_path
        leaf_tabs = list(_iter_leaf_tabs(ctx.mapping_tabs))
        if not leaf_tabs or not any(tab.get("location_ids") for tab in leaf_tabs):
            logger.info("Mapping preset loaded, but no markers matched this connected slot.")
            clear_mapping_state(ctx, "No matching tabs")
            ctx.mapping_preset_path = preset_path
            if ctx.ui:
                ctx.ui.mapping_preset_path = preset_path
            return

        load_mapping_tab(ctx, logger, [0])
        ctx.updateTracker()
        logger.info(f"Loaded mapping preset with {len(leaf_tabs)} map tab(s).")
        if ctx.ui and hasattr(ctx.ui, "refresh_mapping_tab_selectors"):
            ctx.ui.refresh_mapping_tab_selectors()
        if ctx.ui and hasattr(ctx.ui, "repaint_visual_packs_list"):
            ctx.ui.repaint_visual_packs_list()
    except Exception:
        logger.error("Failed to load mapping preset archive.")
        logger.error(traceback.format_exc())


def load_mapping_tab(ctx, logger: logging.Logger, tab_path: list[int] | int | str) -> None:
    if not ctx.ui or not ctx.mapping_page or not ctx.mapping_tabs:
        return

    if isinstance(tab_path, int):
        tab_path = _resolve_leaf_path(ctx.mapping_tabs, [tab_path])
    elif isinstance(tab_path, str):
        for index, tab in enumerate(ctx.mapping_tabs):
            if tab["name"] == tab_path:
                tab_path = _resolve_leaf_path(ctx.mapping_tabs, [index])
                break
        else:
            logger.error("Attempted to load a mapping tab that doesn't exist.")
            return
    elif isinstance(tab_path, list):
        tab_path = _resolve_leaf_path(ctx.mapping_tabs, tab_path)
    else:
        logger.error("Attempted to load a mapping tab that doesn't exist.")
        return

    tab = _tab_at_path(ctx.mapping_tabs, tab_path)
    if tab is None or tab.get("children"):
        logger.error("Attempted to load a mapping tab that doesn't exist.")
        return

    _rebuild_tab_runtime(ctx, tab)
    ctx.mapping_tab_path = tab_path
    ctx.mapping_tab_index = tab_path[0] if tab_path else None
    _display_tab(ctx, tab)
    if ctx.ui and hasattr(ctx.ui, "refresh_mapping_tab_selectors"):
        ctx.ui.refresh_mapping_tab_selectors()


def mapping_tab_has_available_checks(ctx, tab: dict) -> bool:
    if not ctx.tracker_core or not ctx.tracker_core.locations_available:
        return False
    children = tab.get("children")
    if children:
        return any(mapping_tab_has_available_checks(ctx, child) for child in children)
    return any(location_id in ctx.tracker_core.locations_available for location_id in tab.get("location_ids", []))
