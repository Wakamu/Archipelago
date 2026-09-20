from __future__ import annotations

import json
import logging
import traceback
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from Utils import local_path, user_path
from worlds import AutoWorld


VISUAL_PACKS_FOLDER = "visual_packs"


@dataclass(frozen=True)
class VisualPresetEntry:
    path: str
    game: str
    name: str


def visual_packs_dir() -> Path:
    """Writable folder for visual packs (``user_path``, not the install tree).

    On Linux AppImage / ``/opt`` installs, ``local_path`` is read-only, so
    creating ``visual_packs`` there raises PermissionError / ERROFS. Archipelago
    already routes writable data through ``user_path`` (e.g.
    ``~/.local/share/Archipelago``).
    """
    path = Path(user_path(VISUAL_PACKS_FOLDER))
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Defensive fallback if user_path somehow isn't creatable yet.
        from Utils import home_path

        path = Path(home_path(VISUAL_PACKS_FOLDER))
        path.mkdir(parents=True, exist_ok=True)
    return path


def _visual_packs_search_dirs() -> list[Path]:
    """Writable user dir first; also read any packs left beside the install."""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        dirs.append(path)

    _add(visual_packs_dir())
    local_dir = Path(local_path(VISUAL_PACKS_FOLDER))
    if local_dir.is_dir():
        _add(local_dir)
    return dirs

def _visual_packs_search_dirs() -> list[Path]:
    """Writable user dir first; also read any packs left beside the install."""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        dirs.append(path)

    _add(visual_packs_dir())
    local_dir = Path(local_path(VISUAL_PACKS_FOLDER))
    if local_dir.is_dir():
        _add(local_dir)
    return dirs


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
    seen_paths: set[str] = set()
    try:
        search_dirs = _visual_packs_search_dirs()
    except OSError:
        return entries

    for packs_dir in search_dirs:
        try:
            paths = sorted(packs_dir.glob("*.zip"), key=lambda p: p.name.lower())
        except OSError:
            continue
        for path in paths:
            try:
                resolved = str(path.resolve())
            except OSError:
                resolved = str(path)
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            manifest = _read_preset_manifest(path)
            game = (manifest or {}).get("game") or path.stem
            entries.append(VisualPresetEntry(path=resolved, game=game, name=path.name))
    return entries


def resolve_visual_pack(
    query: str,
    *,
    preferred_game: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve a pack query to an absolute zip path.

    Accepts an absolute/relative zip path, a filename under visual_packs,
    a zip stem, or a pack game name from mapping.json.

    Returns (path, error). Exactly one of the two is set.
    """
    query = (query or "").strip().strip('"').strip("'")
    if not query:
        return None, "Empty pack name."

    direct = Path(query).expanduser()
    if direct.is_file() and is_zipfile(direct):
        return str(direct.resolve()), None

    packs_dir = visual_packs_dir()
    under_packs = packs_dir / query
    if under_packs.is_file() and is_zipfile(under_packs):
        return str(under_packs.resolve()), None
    if under_packs.suffix.lower() != ".zip":
        under_packs_zip = packs_dir / f"{query}.zip"
        if under_packs_zip.is_file() and is_zipfile(under_packs_zip):
            return str(under_packs_zip.resolve()), None

    # Also resolve filenames found only in the (possibly read-only) install folder.
    for search_dir in _visual_packs_search_dirs()[1:]:
        candidate = search_dir / query
        if candidate.is_file() and is_zipfile(candidate):
            return str(candidate.resolve()), None
        if candidate.suffix.lower() != ".zip":
            candidate_zip = search_dir / f"{query}.zip"
            if candidate_zip.is_file() and is_zipfile(candidate_zip):
                return str(candidate_zip.resolve()), None

    entries = list_visual_presets()
    if not entries:
        return None, f"No visual packs found in {packs_dir}."

    needle = query.lower()
    if needle.endswith(".zip"):
        needle_stem = Path(needle).stem
    else:
        needle_stem = needle

    def _matches(entry: VisualPresetEntry) -> bool:
        name = entry.name.lower()
        stem = Path(entry.name).stem.lower()
        game = entry.game.lower()
        return needle in {name, stem, game} or needle_stem in {name, stem, game}

    matches = [entry for entry in entries if _matches(entry)]
    if preferred_game:
        preferred = [entry for entry in matches if entry.game == preferred_game]
        if len(preferred) == 1:
            return preferred[0].path, None
        if len(preferred) > 1:
            names = ", ".join(entry.name for entry in preferred)
            return None, f"Ambiguous pack '{query}' for {preferred_game}: {names}"
        # Fall through to non-game-filtered matches when nothing matched the connected game.

    if len(matches) == 1:
        return matches[0].path, None
    if len(matches) > 1:
        names = ", ".join(f"{entry.name} ({entry.game})" for entry in matches)
        return None, f"Ambiguous pack '{query}': {names}"

    available = ", ".join(f"{entry.name} ({entry.game})" for entry in entries[:12])
    more = "" if len(entries) <= 12 else f", … (+{len(entries) - 12} more)"
    return None, f"No visual pack matching '{query}'. Available: {available}{more}"


def can_load_mapping_preset(ctx) -> bool:
    if not ctx.game:
        return False
    return ctx.game in AutoWorld.AutoWorldRegister.world_types


def loaded_pack_is_compatible(ctx) -> bool:
    """True when connected, a pack is loaded, and it matches the connected game."""
    if not ctx.server or not ctx.game or not ctx.mapping_preset_path:
        return False
    if not can_load_mapping_preset(ctx):
        return False
    manifest = _read_preset_manifest(Path(ctx.mapping_preset_path))
    pack_game = (manifest or {}).get("game")
    return not pack_game or pack_game == ctx.game


def _shortcut_connect_host(ctx) -> str | None:
    address = ctx.server_address
    if not address:
        return None
    if "://" not in address:
        address = f"ws://{address}"
    parsed = urllib.parse.urlparse(address)
    host = parsed.hostname
    if not host:
        # Fall back to netloc without credentials.
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.rsplit("@", 1)[-1]
        return netloc or None
    if parsed.port:
        return f"{host}:{parsed.port}"
    return host


def _shortcut_pack_arg(ctx) -> str | None:
    preset_path = ctx.mapping_preset_path
    if not preset_path:
        return None
    path = Path(preset_path)
    packs_dir = visual_packs_dir().resolve()
    try:
        if path.resolve().parent == packs_dir:
            return path.stem
    except OSError:
        pass
    manifest = _read_preset_manifest(path)
    if manifest and manifest.get("game"):
        return str(manifest["game"])
    return path.stem


def _safe_shortcut_name(*parts: str) -> str:
    raw = " - ".join(part for part in parts if part)
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in raw).strip(" ._")
    return cleaned[:120] or "Archipelago Visual Tracker"


def _quote_arg(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _create_windows_shortcut(
    *,
    target: str,
    arguments: str,
    name: str,
    working_dir: str | None,
    icon: str | None,
) -> Path:
    """Create a .lnk with a real TargetPath (pyshortcuts noexe leaves it empty)."""
    import subprocess

    try:
        import win32com.client
        from win32com.shell import shell, shellcon

        desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, None, 0))
        dest = desktop / f"{name}.lnk"
        shortcut = win32com.client.Dispatch("Wscript.Shell").CreateShortCut(str(dest))
        shortcut.Targetpath = target
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = working_dir or str(Path(target).parent)
        shortcut.WindowStyle = 1
        shortcut.Description = name
        if icon and Path(icon).is_file():
            shortcut.IconLocation = icon
        shortcut.save()
        return dest
    except ImportError:
        pass

    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "OneDrive" / "Desktop"
    dest = desktop / f"{name}.lnk"
    work = working_dir or str(Path(target).parent)

    def _ps_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_ps_quote(str(dest))}); "
        f"$s.TargetPath = {_ps_quote(target)}; "
        f"$s.Arguments = {_ps_quote(arguments)}; "
        f"$s.WorkingDirectory = {_ps_quote(work)}; "
        f"$s.Description = {_ps_quote(name)}; "
    )
    if icon and Path(icon).is_file():
        ps += f"$s.IconLocation = {_ps_quote(icon)}; "
    ps += "$s.Save()"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def create_connected_shortcut(ctx) -> str:
    """Create a desktop shortcut for the current connection + pack. Returns the shortcut name."""
    import os
    import sys

    from Utils import is_frozen, is_windows

    if not loaded_pack_is_compatible(ctx):
        raise RuntimeError("Connect and load a compatible visual pack before creating a shortcut.")

    connect = _shortcut_connect_host(ctx)
    slot = ctx.auth or (ctx.player_names.get(ctx.slot) if ctx.slot else None)
    pack = _shortcut_pack_arg(ctx)
    if not connect or not slot or not pack:
        raise RuntimeError("Missing connect address, slot name, or pack for shortcut.")

    env = os.environ
    component = "Archipelago Visual Tracker"
    arg_parts = [
        _quote_arg(component),
        "--",
        "--connect",
        _quote_arg(connect),
        "--name",
        _quote_arg(slot),
        "--pack",
        _quote_arg(pack),
    ]
    if ctx.password:
        arg_parts.extend(["--password", _quote_arg(ctx.password)])
    arguments = " ".join(arg_parts)

    shortcut_name = _safe_shortcut_name("AVT", slot, ctx.game or pack)
    icon = local_path("data", "icon.ico")
    if not Path(icon).is_file():
        icon = None

    if "APPIMAGE" in env:
        from pyshortcuts import make_shortcut

        make_shortcut(
            f'{env["ARGV0"]} {arguments}',
            name=shortcut_name,
            icon=icon,
            startmenu=False,
            terminal=False,
            working_dir=None,
            noexe=True,
        )
        return shortcut_name

    if is_windows:
        if is_frozen():
            launcher = local_path("ArchipelagoLauncher.exe")
            if not Path(launcher).is_file():
                launcher = sys.argv[0]
            wkdir = local_path()
        else:
            # Source checkout: python.exe Launcher.py ...
            launcher = sys.executable
            arguments = f'{_quote_arg(local_path("Launcher.py"))} {arguments}'
            wkdir = local_path()
        _create_windows_shortcut(
            target=str(Path(launcher).resolve()),
            arguments=arguments,
            name=shortcut_name,
            working_dir=wkdir,
            icon=icon,
        )
        return shortcut_name

    # macOS / Linux: pyshortcuts is fine when the executable is the first token.
    from pyshortcuts import make_shortcut

    if is_frozen():
        launcher = local_path("ArchipelagoLauncher")
        if not Path(launcher).is_file():
            launcher = sys.argv[0]
        script = f"{launcher} {arguments}"
        wkdir = local_path()
    else:
        script = f"{sys.executable} {_quote_arg(local_path('Launcher.py'))} {arguments}"
        wkdir = local_path()
    make_shortcut(
        script,
        name=shortcut_name,
        icon=icon,
        startmenu=False,
        terminal=False,
        working_dir=wkdir,
        noexe=is_frozen(),
    )
    return shortcut_name


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
    map_page_keys: list[str] | None = None,
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
        "map_page_keys": list(map_page_keys or []),
    }
    if children is not None:
        tab["children"] = children
    return tab


def _normalize_map_page_keys(manifest_tab: dict) -> list[str]:
    """Accept ``map_page_keys`` (list) and/or legacy ``map_page_key`` (str)."""
    keys: list[str] = []
    seen: set[str] = set()

    def _add(value) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _add(item)
            return
        text = str(value).strip()
        if not text:
            return
        folded = text.casefold()
        if folded in seen:
            return
        seen.add(folded)
        keys.append(text)

    _add(manifest_tab.get("map_page_keys"))
    _add(manifest_tab.get("map_page_key"))
    return keys


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


def _resolve_leaf_path(
    tabs: list[dict],
    path: list[int],
    *,
    ctx=None,
    show_out_of_logic: bool = True,
) -> list[int]:
    """Walk into folders until a leaf map tab is reached.

    When out-of-logic tabs are hidden, descend into the first child that still
    has in-logic/glitched checks (not always children[0]). Otherwise selecting a
    folder whose first sub-tab is empty would bounce away or show a blank map.
    """
    resolved = list(path)
    while True:
        tab = _tab_at_path(tabs, resolved)
        if tab is None or not tab.get("children"):
            return resolved
        children = tab["children"]
        child_index = 0
        if ctx is not None and not show_out_of_logic:
            for index, child in enumerate(children):
                if mapping_tab_is_listed(ctx, child, show_out_of_logic=False):
                    child_index = index
                    break
        resolved.append(child_index)


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
    map_page_keys = _normalize_map_page_keys(manifest_tab)
    child_manifests = manifest_tab.get("tabs")
    if child_manifests is not None:
        return _make_tab(
            manifest_tab.get("name", fallback_name),
            map_page_keys=map_page_keys,
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
        map_page_keys=map_page_keys,
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
    ctx._prefer_in_logic_tab = False
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
        ctx._prefer_in_logic_tab = True
        ctx.updateTracker()
        if ensure_preferred_mapping_tab(ctx, logger):
            ctx._prefer_in_logic_tab = False
            ctx.updateTracker()
        logger.info(f"Loaded mapping preset with {len(leaf_tabs)} map tab(s).")
        if ctx.ui and hasattr(ctx.ui, "refresh_mapping_tab_selectors"):
            ctx.ui.refresh_mapping_tab_selectors()
        if ctx.ui and hasattr(ctx.ui, "repaint_visual_packs_list"):
            ctx.ui.repaint_visual_packs_list()
        # Sync to the published current-map value once a pack is available.
        # Does not require UT tracker_world — AVT watches Slot:{player}:Current Map itself.
        if getattr(ctx, "auto_tab", False):
            try:
                ctx.load_map(None)
            except Exception:
                logger.debug("Auto-tab after pack load failed.", exc_info=True)
    except Exception:
        logger.error("Failed to load mapping preset archive.")
        logger.error(traceback.format_exc())


def load_mapping_tab(
    ctx,
    logger: logging.Logger,
    tab_path: list[int] | int | str,
    *,
    ignore_out_of_logic_filter: bool = False,
) -> None:
    if not ctx.ui or not ctx.mapping_page or not ctx.mapping_tabs:
        return

    show_out_of_logic = ignore_out_of_logic_filter or bool(
        getattr(ctx.ui, "show_out_of_logic_tabs", False)
    )

    if isinstance(tab_path, int):
        tab_path = _resolve_leaf_path(
            ctx.mapping_tabs,
            [tab_path],
            ctx=ctx,
            show_out_of_logic=show_out_of_logic,
        )
    elif isinstance(tab_path, str):
        for index, tab in enumerate(ctx.mapping_tabs):
            if tab["name"] == tab_path:
                tab_path = _resolve_leaf_path(
                    ctx.mapping_tabs,
                    [index],
                    ctx=ctx,
                    show_out_of_logic=show_out_of_logic,
                )
                break
        else:
            logger.error("Attempted to load a mapping tab that doesn't exist.")
            return
    elif isinstance(tab_path, list):
        tab_path = _resolve_leaf_path(
            ctx.mapping_tabs,
            tab_path,
            ctx=ctx,
            show_out_of_logic=show_out_of_logic,
        )
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
    if hasattr(ctx, "selected_mapping_pin"):
        ctx.selected_mapping_pin = None
    _display_tab(ctx, tab)
    # Pins are created with status "none"; paint real logic colors immediately.
    # Auto-tab used to skip this (UT called updateTracker after load_map).
    refresh = getattr(ctx, "refresh_mapping_pins", None)
    if callable(refresh):
        refresh()
    if ctx.ui and hasattr(ctx.ui, "refresh_mapping_tab_selectors"):
        ctx.ui.refresh_mapping_tab_selectors()
    if ctx.ui and hasattr(ctx.ui, "update_mapping_selection"):
        ctx.ui.update_mapping_selection(
            "Selection: none",
            "Click a map pin to inspect its locations.",
        )


def mapping_tab_has_available_checks(ctx, tab: dict) -> bool:
    return mapping_tab_has_status(ctx, tab, in_logic=True)


def mapping_tab_has_status(ctx, tab: dict, *, in_logic: bool = False, glitched: bool = False) -> bool:
    if not ctx.tracker_core:
        return False
    children = tab.get("children")
    if children:
        return any(
            mapping_tab_has_status(ctx, child, in_logic=in_logic, glitched=glitched)
            for child in children
        )
    location_ids = tab.get("location_ids", [])
    if in_logic and any(
        location_id in ctx.tracker_core.locations_available for location_id in location_ids
    ):
        return True
    if glitched and any(
        location_id in ctx.tracker_core.glitched_locations for location_id in location_ids
    ):
        return True
    return False


def mapping_tab_is_listed(ctx, tab: dict, *, show_out_of_logic: bool) -> bool:
    if show_out_of_logic:
        return True
    return mapping_tab_has_status(ctx, tab, in_logic=True, glitched=True)


def find_first_tab_path(tabs: list[dict], predicate, path_prefix: list[int] | None = None) -> list[int] | None:
    prefix = path_prefix or []
    for index, tab in enumerate(tabs):
        path = [*prefix, index]
        children = tab.get("children")
        if children:
            found = find_first_tab_path(children, predicate, path)
            if found is not None:
                return found
        elif predicate(tab):
            return path
    return None


def find_preferred_mapping_tab_path(ctx, *, allow_glitched_fallback: bool = True) -> list[int] | None:
    if not ctx.mapping_tabs:
        return None
    path = find_first_tab_path(
        ctx.mapping_tabs,
        lambda tab: mapping_tab_has_status(ctx, tab, in_logic=True),
    )
    if path is not None:
        return path
    if allow_glitched_fallback:
        return find_first_tab_path(
            ctx.mapping_tabs,
            lambda tab: mapping_tab_has_status(ctx, tab, glitched=True),
        )
    return None


def find_mapping_tab_path_by_name(
    tabs: list[dict],
    name: str,
    *,
    case_insensitive: bool = False,
    path_prefix: list[int] | None = None,
) -> list[int] | None:
    """Find a tab path by display name only."""
    return _find_mapping_tab_path_by_fields(
        tabs,
        name,
        fields=("name",),
        case_insensitive=case_insensitive,
        path_prefix=path_prefix,
    )


def find_mapping_tab_path_for_auto_tab(
    tabs: list[dict],
    target: str,
    *,
    case_insensitive: bool = False,
    path_prefix: list[int] | None = None,
) -> list[int] | None:
    """Find a tab path for UT auto-tabbing: ``map_page_keys`` first, then ``name``."""
    by_key = _find_mapping_tab_path_by_auto_tab_keys(
        tabs,
        target,
        case_insensitive=case_insensitive,
        path_prefix=path_prefix,
    )
    if by_key is not None:
        return by_key
    return _find_mapping_tab_path_by_fields(
        tabs,
        target,
        fields=("name",),
        case_insensitive=case_insensitive,
        path_prefix=path_prefix,
    )


def _tab_auto_tab_keys(tab: dict) -> list[str]:
    """Keys this tab should match for auto-tabbing (supports legacy singular)."""
    return _normalize_map_page_keys(tab)


def _find_mapping_tab_path_by_auto_tab_keys(
    tabs: list[dict],
    target: str,
    *,
    case_insensitive: bool = False,
    path_prefix: list[int] | None = None,
) -> list[int] | None:
    if not target:
        return None
    needle = target.casefold() if case_insensitive else target
    prefix = path_prefix or []
    for index, tab in enumerate(tabs):
        path = [*prefix, index]
        for key in _tab_auto_tab_keys(tab):
            hay = key.casefold() if case_insensitive else key
            if hay == needle:
                children = tab.get("children")
                if children:
                    leaf = find_first_tab_path(children, lambda _tab: True, path)
                    return leaf if leaf is not None else path
                return path
        children = tab.get("children")
        if children:
            found = _find_mapping_tab_path_by_auto_tab_keys(
                children,
                target,
                case_insensitive=case_insensitive,
                path_prefix=path,
            )
            if found is not None:
                return found
    return None


def _find_mapping_tab_path_by_fields(
    tabs: list[dict],
    target: str,
    *,
    fields: tuple[str, ...],
    case_insensitive: bool = False,
    path_prefix: list[int] | None = None,
    skip_empty: bool = False,
) -> list[int] | None:
    if not target:
        return None
    needle = target.casefold() if case_insensitive else target
    prefix = path_prefix or []
    for index, tab in enumerate(tabs):
        path = [*prefix, index]
        for field in fields:
            raw = tab.get(field)
            if raw is None or raw == "":
                if skip_empty:
                    continue
                raw = ""
            hay = str(raw).casefold() if case_insensitive else str(raw)
            if hay == needle:
                children = tab.get("children")
                if children:
                    leaf = find_first_tab_path(children, lambda _tab: True, path)
                    return leaf if leaf is not None else path
                return path
        children = tab.get("children")
        if children:
            found = _find_mapping_tab_path_by_fields(
                children,
                target,
                fields=fields,
                case_insensitive=case_insensitive,
                path_prefix=path,
                skip_empty=skip_empty,
            )
            if found is not None:
                return found
    return None


def apply_ut_auto_tab_to_mapping(ctx, logger: logging.Logger, map_id) -> bool:
    """Switch the visual pack tab to match a UT map_page_index result.

    Resolution order:
    1. UT map name / string id → tab ``map_page_keys`` / legacy ``map_page_key``, then ``name``
    2. Case-insensitive key/name match
    3. Integer index as a top-level VT tab index
    """
    if not ctx.ui or not ctx.mapping_tabs:
        return False

    target_name: str | None = None
    target_index: int | None = None

    if isinstance(map_id, str) and not map_id.isdecimal():
        target_name = map_id
    else:
        if isinstance(map_id, str):
            map_id = int(map_id)
        if not isinstance(map_id, int):
            return False
        target_index = map_id
        maps = getattr(ctx, "maps", None) or []
        if 0 <= map_id < len(maps):
            target_name = maps[map_id].get("name")

    path = None
    if target_name:
        path = find_mapping_tab_path_for_auto_tab(ctx.mapping_tabs, target_name)
        if path is None:
            path = find_mapping_tab_path_for_auto_tab(
                ctx.mapping_tabs,
                target_name,
                case_insensitive=True,
            )

    if path is None and target_index is not None and target_name is None:
        # Only use a bare integer as a top-level tab index when we never had a
        # map name to match (numeric datastorage). Never treat "unknown name →
        # index 0" as a reason to jump to the first tab.
        if 0 <= target_index < len(ctx.mapping_tabs):
            path = _resolve_leaf_path(
                ctx.mapping_tabs,
                [target_index],
                ctx=ctx,
                show_out_of_logic=True,
            )

    if path is None:
        logger.debug(f"Auto-tab: no Visual Tracker tab matching UT map {map_id!r}")
        return False

    if path == list(getattr(ctx, "mapping_tab_path", []) or []):
        return True

    # Auto-tab must open the matched tab even when "hide out of logic" is on.
    load_mapping_tab(ctx, logger, path, ignore_out_of_logic_filter=True)
    ctx._prefer_in_logic_tab = False
    return True


def ensure_preferred_mapping_tab(ctx, logger: logging.Logger) -> bool:
    """Select the first in-logic tab when available. Returns True if the tab changed."""
    if not ctx.ui or not ctx.mapping_tabs:
        return False
    preferred = find_preferred_mapping_tab_path(ctx, allow_glitched_fallback=False)
    if preferred is None:
        return False
    if preferred == list(ctx.mapping_tab_path):
        return False
    load_mapping_tab(ctx, logger, preferred)
    return True


def maybe_reselect_filtered_mapping_tab(ctx, logger: logging.Logger) -> bool:
    """If out-of-logic tabs are hidden and the current tab has nothing reachable, jump away.

    Skipped while auto-tab is enabled so UT/client map updates can stay on (or
    switch to) tabs that are hidden from the manual dropdown.
    """
    if not ctx.ui or not ctx.mapping_tabs:
        return False
    if getattr(ctx, "auto_tab", False):
        return False
    show_out_of_logic = bool(getattr(ctx.ui, "show_out_of_logic_tabs", False))
    if show_out_of_logic:
        return False
    current = _tab_at_path(ctx.mapping_tabs, list(ctx.mapping_tab_path))
    if current is not None and mapping_tab_is_listed(ctx, current, show_out_of_logic=False):
        return False
    preferred = find_preferred_mapping_tab_path(ctx, allow_glitched_fallback=True)
    if preferred is None:
        return False
    if preferred == list(ctx.mapping_tab_path):
        return False
    load_mapping_tab(ctx, logger, preferred)
    return True
