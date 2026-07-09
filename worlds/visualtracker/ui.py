from __future__ import annotations

from collections import defaultdict


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
    def load_mapping_preset_dialog(self):
        from Utils import messagebox

        from .mapping import get_mapping_preset_block_reason

        block_reason = get_mapping_preset_block_reason(self.ctx)
        if block_reason:
            messagebox("Cannot Load Preset", block_reason, error=True)
            return
        self.ctx.load_mapping_preset()

    def open_mapping_dropdown(self, item):
        if not self.ctx.mapping_tabs:
            return
        dropdown_menu = MarkupDropdown(caller=item, hor_growth="right", ver_growth="down")
        dropdown_menu.items = [
            {
                "text": self.get_mapping_tab_text(tab),
                "on_release": lambda i=i, menu=dropdown_menu: self.mapping_dropdown_callback(menu, i),
            }
            for i, tab in enumerate(self.ctx.mapping_tabs)
        ]
        dropdown_menu.open()

    def mapping_dropdown_callback(self, menu: MDDropdownMenu, tab_index: int):
        menu.dismiss()
        self.ctx.load_mapping_tab(tab_index)
        self.ctx.updateTracker()

    def get_mapping_tab_text(self, tab: dict) -> str:
        if self.ctx.mapping_tab_has_available_checks(tab):
            return f"[color={get_ut_color('in_logic')}]{tab['name']}[/color]"
        return tab["name"]

    manager_class.load_mapping_preset_dialog = load_mapping_preset_dialog
    manager_class.open_mapping_dropdown = open_mapping_dropdown
    manager_class.mapping_dropdown_callback = mapping_dropdown_callback
    manager_class.get_mapping_tab_text = get_mapping_tab_text
