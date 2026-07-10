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
        from .mapping import _resolve_leaf_path, _siblings_at_depth

        if not self.ctx.mapping_tabs:
            return
        leaf_path = _resolve_leaf_path(self.ctx.mapping_tabs, list(self.ctx.mapping_tab_path))
        siblings = _siblings_at_depth(self.ctx.mapping_tabs, leaf_path, depth)
        dropdown_menu = MarkupDropdown(caller=item, hor_growth="right", ver_growth="down")
        dropdown_menu.items = [
            {
                "text": self.get_mapping_tab_text(tab),
                "on_release": lambda i=i, menu=dropdown_menu, d=depth: self.mapping_dropdown_callback(menu, d, i),
            }
            for i, tab in enumerate(siblings)
        ]
        dropdown_menu.open()

    def mapping_dropdown_callback(self, menu: MDDropdownMenu, depth: int, tab_index: int):
        from .mapping import _resolve_leaf_path

        menu.dismiss()
        new_path = [*self.ctx.mapping_tab_path[:depth], tab_index]
        self.ctx.load_mapping_tab(_resolve_leaf_path(self.ctx.mapping_tabs, new_path))
        self.ctx.updateTracker()

    def get_mapping_tab_text(self, tab: dict) -> str:
        if self.ctx.mapping_tab_has_available_checks(tab):
            return f"[color={get_ut_color('in_logic')}]{tab['name']}[/color]"
        return tab["name"]

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
    manager_class.get_visual_pack_menu_text = get_visual_pack_menu_text
    manager_class._update_visual_pack_dropdown_label = _update_visual_pack_dropdown_label
    manager_class.open_visual_pack_dropdown = open_visual_pack_dropdown
    manager_class.visual_pack_dropdown_callback = visual_pack_dropdown_callback
    manager_class.load_visual_pack = load_visual_pack
    manager_class.refresh_visual_packs_list = refresh_visual_packs_list
    manager_class.repaint_visual_packs_list = repaint_visual_packs_list
