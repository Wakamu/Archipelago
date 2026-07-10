from __future__ import annotations

import pkgutil


def load_visualtracker_kv() -> None:
    from kivy.lang import Builder
    from worlds.tracker.TrackerKivy import SomethingNeatJustToMakePythonHappy  # noqa: F401 - registers ap:zip image loader

    SomethingNeatJustToMakePythonHappy()
    data = pkgutil.get_data("worlds.visualtracker", "visualtracker.kv").decode()
    Builder.load_string(data)


def build_mapping_tab(ctx, manager) -> None:
    from kivy.uix.boxlayout import BoxLayout
    from worlds.tracker.TrackerClient import get_ut_color

    from .ui import create_mapping_tracker_class
    from .widgets import create_pin_widget_classes

    ap_location_mixed, ap_location_split = create_pin_widget_classes(get_ut_color)
    mapping_tracker = create_mapping_tracker_class(BoxLayout, ap_location_split, ap_location_mixed)
    mapping_content = mapping_tracker()
    manager.add_client_tab("Mapping", mapping_content)
    ctx.mapping_page = mapping_content


def update_mapping_pin_status(ctx, hints: dict[int, object]) -> None:
    if not ctx.ui or not ctx.mapping_coord_dict:
        return
    for location in ctx.server_locations:
        relevant_coords = ctx.mapping_coord_dict.get(location, [])
        if not relevant_coords:
            continue

        if location in ctx.checked_locations or location in ctx.tracker_core.ignored_locations:
            status = "collected"
        elif location in ctx.tracker_core.locations_available:
            status = "in_logic"
        elif location in ctx.tracker_core.glitched_locations:
            status = "glitched"
        else:
            status = "out_of_logic"
        if location in hints:
            status = "hinted_" + status
        for coord in relevant_coords:
            coord.update_status(location, status)
