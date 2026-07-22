from __future__ import annotations

from collections import defaultdict

PACK_LOADED_COLOR = (0.2, 0.9, 0.35, 1)
PACK_MATCHING_COLOR = (1.0, 0.92, 0.2, 1)


def _rgb_to_markup_color(rgb: tuple[float, float, float, float]) -> str:
    r, g, b, _ = rgb
    return f"{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def create_mapping_tracker_class(BoxLayout, ap_location_split, ap_location_mixed):
    class MappingTracker(BoxLayout):
        def map_window_to_image_coords(self, x: float, y: float) -> tuple[int, int] | None:
            tracker_map = self.ids.tracker_map
            local_x, local_y = tracker_map.to_widget(x, y)
            norm_w, norm_h = tracker_map.norm_image_size
            tex_w, tex_h = tracker_map.texture_size
            if norm_w <= 0 or norm_h <= 0 or tex_w <= 0 or tex_h <= 0:
                return None
            offset_x = (tracker_map.width - norm_w) / 2
            offset_y = (tracker_map.height - norm_h) / 2
            if not (offset_x <= local_x <= offset_x + norm_w and offset_y <= local_y <= offset_y + norm_h):
                return None
            image_x = int((local_x - offset_x) * (tex_w / norm_w))
            image_y = int((norm_h - (local_y - offset_y)) * (tex_h / norm_h))
            return image_x, image_y

        def load_coords(
            self,
            coords: dict[tuple, tuple[list[int], int | None, str | None]],
            use_split,
            default_loc_size: int = 32,
            on_select=None,
        ) -> dict[int, list]:
            self.ids.location_canvas.clear_widgets()
            return_dict: dict[int, list] = defaultdict(list)
            for coord, (sections, size, label) in coords.items():
                ap_location_class = ap_location_split if use_split else ap_location_mixed
                loc_size = size if size is not None else default_loc_size
                temp_loc = ap_location_class(
                    sections,
                    self.ids.tracker_map,
                    label=label,
                    on_select=on_select,
                    pos=coord,
                    size=(loc_size, loc_size),
                )
                self.ids.location_canvas.add_widget(temp_loc)
                for location_id in sections:
                    return_dict[location_id].append(temp_loc)
            return return_dict

    return MappingTracker


def apply_mapping_manager_features(
    manager_class,
    *,
    MDDropdownMenu,
    MarkupDropdown,
    get_ut_color,
):
    def refresh_mapping_tab_selectors(self) -> None:
        from kivy.metrics import dp
        from kivymd.uix.dropdownitem import MDDropDownItem, MDDropDownItemText

        from .mapping import _path_to_label, _resolve_leaf_path, _siblings_at_depth

        if not self.ctx.mapping_page or not hasattr(self.ctx.mapping_page.ids, "mapping_tab_selectors"):
            return
        selectors = self.ctx.mapping_page.ids.mapping_tab_selectors
        selectors.clear_widgets()
        if not self.ctx.mapping_tabs:
            return

        leaf_path = _resolve_leaf_path(self.ctx.mapping_tabs, list(self.ctx.mapping_tab_path))
        for depth in range(len(leaf_path)):
            siblings = _siblings_at_depth(self.ctx.mapping_tabs, leaf_path, depth)
            if not siblings:
                continue
            index = leaf_path[depth]
            tab = siblings[index]
            item_text = MDDropDownItemText(markup=True)
            item = MDDropDownItem(
                item_text,
                size_hint=(None, None),
                size_hint_y=None,
                height=dp(48),
            )
            item.bind(on_release=lambda widget, d=depth: self.open_mapping_dropdown(widget, d))
            selectors.add_widget(item)
            # Set label after the item wires up MDDropDownItemText; otherwise the
            # canvas texture stays empty and the closed dropdown looks blank.
            item_text.text = self.get_mapping_tab_text(tab)
        self.mapping_current_tab = _path_to_label(self.ctx.mapping_tabs, leaf_path)

    def open_mapping_dropdown(self, item, depth: int = 0):
        from .mapping import _resolve_leaf_path, _siblings_at_depth, mapping_tab_is_listed

        if not self.ctx.mapping_tabs:
            return
        leaf_path = _resolve_leaf_path(self.ctx.mapping_tabs, list(self.ctx.mapping_tab_path))
        siblings = _siblings_at_depth(self.ctx.mapping_tabs, leaf_path, depth)
        show_out_of_logic = bool(getattr(self, "show_out_of_logic_tabs", False))
        entries = [
            (i, tab)
            for i, tab in enumerate(siblings)
            if mapping_tab_is_listed(self.ctx, tab, show_out_of_logic=show_out_of_logic)
        ]
        dropdown_menu = MarkupDropdown(caller=item, hor_growth="right", ver_growth="down")
        if not entries:
            dropdown_menu.items = [
                {
                    "text": "No in-logic / glitched tabs",
                    "on_release": lambda menu=dropdown_menu: menu.dismiss(),
                }
            ]
        else:
            dropdown_menu.items = [
                {
                    "text": self.get_mapping_tab_text(tab),
                    "on_release": lambda i=i, menu=dropdown_menu, d=depth: self.mapping_dropdown_callback(menu, d, i),
                }
                for i, tab in entries
            ]
        dropdown_menu.open()

    def mapping_dropdown_callback(self, menu: MDDropdownMenu, depth: int, tab_index: int):
        from .mapping import _resolve_leaf_path

        menu.dismiss()
        new_path = [*self.ctx.mapping_tab_path[:depth], tab_index]
        self.ctx.load_mapping_tab(_resolve_leaf_path(self.ctx.mapping_tabs, new_path))
        self.ctx.updateTracker()

    def get_mapping_tab_text(self, tab: dict) -> str:
        from .mapping import mapping_tab_has_status

        if mapping_tab_has_status(self.ctx, tab, in_logic=True):
            return f"[color={get_ut_color('in_logic')}]{tab['name']}[/color]"
        if mapping_tab_has_status(self.ctx, tab, glitched=True):
            return f"[color={get_ut_color('glitched')}]{tab['name']}[/color]"
        return tab["name"]

    def on_show_out_of_logic_tabs(self, _instance, _value) -> None:
        from worlds.tracker.TrackerClient import logger

        from .mapping import maybe_reselect_filtered_mapping_tab

        if maybe_reselect_filtered_mapping_tab(self.ctx, logger):
            self.ctx.updateTracker()
        elif hasattr(self, "refresh_mapping_tab_selectors"):
            self.refresh_mapping_tab_selectors()

    def get_visual_pack_menu_text(self, entry) -> str:
        if self.mapping_preset_path == entry.path:
            color = _rgb_to_markup_color(PACK_LOADED_COLOR)
            return f"[color={color}]{entry.game}[/color]"
        if self.ctx.game and entry.game == self.ctx.game:
            color = _rgb_to_markup_color(PACK_MATCHING_COLOR)
            return f"[color={color}]{entry.game}[/color]"
        return entry.game

    def _update_visual_pack_dropdown_label(self) -> None:
        if not hasattr(self, "vt_pack_dropdown_text"):
            return
        if self.mapping_preset_path and hasattr(self, "_cached_visual_presets"):
            for entry in self._cached_visual_presets:
                if entry.path == self.mapping_preset_path:
                    self.visual_pack_label = entry.game
                    self.vt_pack_dropdown_text.text = entry.game
                    return
        if not getattr(self, "_cached_visual_presets", None):
            self.visual_pack_label = "No packs found"
        else:
            self.visual_pack_label = "Select a pack..."
        self.vt_pack_dropdown_text.text = self.visual_pack_label

    def open_visual_pack_dropdown(self, item):
        if not getattr(self, "_cached_visual_presets", None):
            return
        dropdown_menu = MarkupDropdown(caller=item, hor_growth="right", ver_growth="down")
        dropdown_menu.items = [
            {
                "text": self.get_visual_pack_menu_text(entry),
                "on_release": lambda path=entry.path, menu=dropdown_menu: self.visual_pack_dropdown_callback(menu, path),
            }
            for entry in self._cached_visual_presets
        ]
        dropdown_menu.open()

    def visual_pack_dropdown_callback(self, menu: MDDropdownMenu, preset_path: str):
        menu.dismiss()
        self.load_visual_pack(preset_path)

    def load_visual_pack(self, preset_path: str) -> None:
        from Utils import messagebox

        from .mapping import get_mapping_preset_block_reason

        block_reason = get_mapping_preset_block_reason(self.ctx)
        if block_reason:
            messagebox("Cannot Load Preset", block_reason, error=True)
            return
        self.ctx.load_mapping_preset(preset_path)
        self.repaint_visual_packs_list()

    def refresh_visual_packs_list(self) -> None:
        from .mapping import list_visual_presets

        self._cached_visual_presets = list_visual_presets()
        self._update_visual_pack_dropdown_label()

    def repaint_visual_packs_list(self) -> None:
        if not hasattr(self, "vt_pack_dropdown_text"):
            return
        self._update_visual_pack_dropdown_label()

    manager_class.open_mapping_dropdown = open_mapping_dropdown
    manager_class.mapping_dropdown_callback = mapping_dropdown_callback
    manager_class.refresh_mapping_tab_selectors = refresh_mapping_tab_selectors
    manager_class.get_mapping_tab_text = get_mapping_tab_text
    manager_class.on_show_out_of_logic_tabs = on_show_out_of_logic_tabs
    manager_class.get_visual_pack_menu_text = get_visual_pack_menu_text
    manager_class._update_visual_pack_dropdown_label = _update_visual_pack_dropdown_label
    manager_class.open_visual_pack_dropdown = open_visual_pack_dropdown
    manager_class.visual_pack_dropdown_callback = visual_pack_dropdown_callback
    manager_class.load_visual_pack = load_visual_pack
    manager_class.refresh_visual_packs_list = refresh_visual_packs_list
    manager_class.repaint_visual_packs_list = repaint_visual_packs_list


def apply_items_manager_features(
    manager_class,
    *,
    get_ut_color,
):
    from .items import (
        ITEM_QUALITIES,
        build_inventory_entries,
        filter_inventory_entries,
        format_inventory_entry,
    )

    def _enabled_item_filters(self) -> set[str]:
        enabled = set()
        for quality in ITEM_QUALITIES:
            widget = getattr(self, "item_filter_widgets", {}).get(quality)
            if widget is None or widget.active:
                enabled.add(quality)
        return enabled

    def refresh_items_tab(self, tracker_state=None) -> None:
        if self.ctx.items_page is None:
            return
        if tracker_state is None:
            tracker_state = getattr(self.ctx, "_last_tracker_state", None)

        entries = build_inventory_entries(self.ctx, tracker_state)
        enabled = self._enabled_item_filters()
        filtered = filter_inventory_entries(entries, enabled)

        if not self.ctx.game:
            self.ctx.items_page.data = [{"text": "Connect to a slot to view received items."}]
            if hasattr(self, "vt_items_total_label"):
                self.vt_items_total_label.text = "Items: 0"
                self.vt_items_filtered_label.text = "Shown: 0"
            return

        if not entries:
            self.ctx.items_page.data = [{"text": "No items received yet."}]
        elif not filtered:
            self.ctx.items_page.data = [{"text": "No items match the selected quality filters."}]
        else:
            self.ctx.items_page.data = [
                {"text": format_inventory_entry(entry, get_ut_color)}
                for entry in filtered
            ]

        if hasattr(self, "vt_items_total_label"):
            total_count = sum(entry.count for entry in entries)
            shown_count = sum(entry.count for entry in filtered)
            self.vt_items_total_label.text = f"Items: {total_count}"
            self.vt_items_filtered_label.text = f"Shown: {shown_count}"

    manager_class._enabled_item_filters = _enabled_item_filters
    manager_class.refresh_items_tab = refresh_items_tab
