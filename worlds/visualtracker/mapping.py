from __future__ import annotations



import json

import logging

import traceback

from zipfile import ZipFile, is_zipfile



from Utils import open_filename

from worlds import AutoWorld





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

) -> dict:

    return {

        "name": name,

        "image_source": image_source,

        "image_archive_path": image_archive_path,

        "source_archive_path": source_archive_path,

        "markers": markers or [],

        "coords": {},

        "location_ids": [],

        "location_size": location_size,

    }





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

    ctx.ui.mapping_current_tab = tab["name"]

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

    ctx.mapping_tab_index = None

    ctx.mapping_root_path = None

    if hasattr(ctx, "selected_mapping_pin"):

        ctx.selected_mapping_pin = None

    if ctx.ui:

        ctx.ui.mapping_source = ""

        ctx.ui.mapping_current_tab = empty_label

        if hasattr(ctx.ui, "update_mapping_selection"):

            ctx.ui.update_mapping_selection("Selection: none", "Click a map pin to inspect its locations.")

        if ctx.mapping_page is not None:

            loc_size = int(ctx.ui.mapping_loc_size) if ctx.ui.mapping_loc_size else 32

            ctx.mapping_page.load_coords({}, ctx.use_split, loc_size)





def load_mapping_preset(ctx, logger: logging.Logger, preset_path: str | None = None) -> None:

    if not ctx.ui:

        return

    block_reason = get_mapping_preset_block_reason(ctx)

    if block_reason:

        logger.info(block_reason)

        return

    if preset_path is None:

        preset_path = open_filename(

            "Select Mapping Preset Archive",

            filetypes=[("Mapping Preset", [".zip"])],

        )

    if not preset_path:

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



        tabs = []

        root_path = f"ap:zip:{preset_path}"

        for index, manifest_tab in enumerate(manifest.get("tabs", []), start=1):

            image_path = manifest_tab.get("image", "")

            tab = _make_tab(

                manifest_tab.get("name", f"Tab {index}"),

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

            tabs.append(tab)



        ctx.mapping_tabs = tabs

        ctx.mapping_root_path = root_path

        if not ctx.mapping_tabs:

            logger.info("Mapping preset loaded, but no markers matched this connected slot.")

            clear_mapping_state(ctx, "No matching tabs")

            return



        load_mapping_tab(ctx, logger, 0)

        ctx.updateTracker()

        logger.info(f"Loaded mapping preset with {len(ctx.mapping_tabs)} tab(s).")

    except Exception:

        logger.error("Failed to load mapping preset archive.")

        logger.error(traceback.format_exc())





def load_mapping_tab(ctx, logger: logging.Logger, tab_index: int | str) -> None:

    if not ctx.ui or not ctx.mapping_page or not ctx.mapping_tabs:

        return

    if isinstance(tab_index, str):

        for i, tab in enumerate(ctx.mapping_tabs):

            if tab["name"] == tab_index:

                tab_index = i

                break

        else:

            logger.error("Attempted to load a mapping tab that doesn't exist.")

            return

    if tab_index < 0 or tab_index >= len(ctx.mapping_tabs):

        logger.error("Attempted to load a mapping tab that doesn't exist.")

        return



    tab = ctx.mapping_tabs[tab_index]

    _rebuild_tab_runtime(ctx, tab)

    ctx.mapping_tab_index = tab_index

    _display_tab(ctx, tab)





def mapping_tab_has_available_checks(ctx, tab: dict) -> bool:

    if not ctx.tracker_core or not ctx.tracker_core.locations_available:

        return False

    return any(location_id in ctx.tracker_core.locations_available for location_id in tab.get("location_ids", []))

