from __future__ import annotations

import pkgutil

# kvui must be imported before kivy so frozen installs get KIVY_DATA_DIR.
from kvui import MDRecycleView
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout


class ItemQualityFilter(BoxLayout):
    text = StringProperty("")
    filter_key = StringProperty("")
    active = BooleanProperty(True)


class ItemsView(MDRecycleView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.data = []


def load_visualtracker_kv() -> None:
    from kivy.factory import Factory
    from kivy.lang import Builder
    from worlds.tracker.TrackerKivy import SomethingNeatJustToMakePythonHappy  # noqa: F401 - registers ap:zip image loader

    from .widgets import MapScatter, ZoomableMapHost

    SomethingNeatJustToMakePythonHappy()
    Factory.register("ItemQualityFilter", cls=ItemQualityFilter)
    Factory.register("ItemsView", cls=ItemsView)
    Factory.register("ZoomableMapHost", cls=ZoomableMapHost)
    Factory.register("MapScatter", cls=MapScatter)
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


def build_items_tab(ctx, manager) -> None:
    from kivy.metrics import dp
    from kivy.uix.boxlayout import BoxLayout
    from kvui import MDLabel, MDDivider

    from .items import ITEM_QUALITIES, QUALITY_LABELS

    items_layout = BoxLayout(orientation="vertical")

    header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36))
    manager.vt_items_total_label = MDLabel(text="Items: 0", halign="center")
    manager.vt_items_filtered_label = MDLabel(text="Shown: 0", halign="center")
    header.add_widget(manager.vt_items_total_label)
    header.add_widget(manager.vt_items_filtered_label)

    filter_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8), padding=(dp(8), 0))
    manager.item_quality_filters = {quality: True for quality in ITEM_QUALITIES}
    manager.item_filter_widgets = {}

    def on_filter_changed(_instance, _value) -> None:
        if hasattr(manager, "refresh_items_tab"):
            manager.refresh_items_tab()

    for quality in ITEM_QUALITIES:
        widget = ItemQualityFilter(text=QUALITY_LABELS[quality], filter_key=quality, active=True)
        widget.bind(active=on_filter_changed)
        manager.item_filter_widgets[quality] = widget
        filter_row.add_widget(widget)

    items_view = ItemsView()
    items_view.data = [{"text": "Connect to a slot to view received items."}]

    items_layout.add_widget(header)
    items_layout.add_widget(MDDivider(size_hint_y=None, height=dp(1)))
    items_layout.add_widget(filter_row)
    items_layout.add_widget(MDDivider(size_hint_y=None, height=dp(1)))
    items_layout.add_widget(items_view)

    manager.add_client_tab("Items", items_layout)
    ctx.items_page = items_view


def update_items_tab(ctx, tracker_state) -> None:
    ctx._last_tracker_state = tracker_state
    if ctx.ui and hasattr(ctx.ui, "refresh_items_tab"):
        ctx.ui.refresh_items_tab(tracker_state)


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
