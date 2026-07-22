from __future__ import annotations

import asyncio
import typing
import sys

from CommonClient import gui_enabled, get_base_parser, handle_url_arg, server_loop
from worlds.tracker.TrackerClient import TrackerGameContext, CurrentTrackerState, logger
from .gui import (
    build_items_tab,
    build_mapping_tab,
    load_visualtracker_kv,
    update_items_tab,
    update_mapping_pin_status,
)
from .mapping import (
    can_load_mapping_preset,
    clear_mapping_state,
    load_mapping_preset,
    load_mapping_tab,
    mapping_tab_has_available_checks,
)


class VisualTrackerContext(TrackerGameContext):
    game = ""
    tags = TrackerGameContext.tags
    selected_mapping_pin = None
    mapping_coord_dict: dict[int, list] = {}
    mapping_page = None
    mapping_tabs: list[dict] = []
    mapping_tab_path: list[int] = []
    mapping_tab_index: int | None = None
    mapping_root_path: str | None = None
    mapping_preset_path: str | None = None
    items_page = None
    _last_tracker_state = None
    # Visual Tracker skips UT's Map Page GUI (see build_gui). UT's default
    # map_page_coords_func returns {}, which crashes load_map with
    # "not enough values to unpack (expected 3, got 0)". Provide a safe
    # no-op that matches the 3-tuple load_map expects.
    map_page_coords_func = staticmethod(lambda *args: ({}, {}, {}))

    def make_gui(self):
        base_manager_class = super().make_gui()

        from kivy.properties import BooleanProperty, NumericProperty, StringProperty
        from kivymd.uix.menu import MDDropdownMenu
        from kvui import MarkupDropdown, MDButton, MDButtonText
        from worlds.tracker.TrackerClient import get_ut_color

        from .ui import apply_items_manager_features, apply_mapping_manager_features

        class VisualTrackerManager(base_manager_class):
            mapping_source = StringProperty("")
            mapping_loc_size = NumericProperty(32)
            mapping_current_tab = StringProperty("No preset loaded")
            mapping_preset_path = StringProperty("")
            mapping_preset_enabled = BooleanProperty(False)
            mapping_has_preset = BooleanProperty(False)
            visual_pack_label = StringProperty("Select a pack...")
            show_out_of_logic_tabs = BooleanProperty(False)
            base_title = "Archipelago Visual Tracker"

            def build(manager_self):
                from kivy.clock import Clock

                container = super().build()
                manager_self._cached_visual_presets = []
                Clock.schedule_once(manager_self._deferred_startup, 0)
                return container

            def _deferred_startup(manager_self, _dt):
                from kivy.clock import Clock
                from kivy.metrics import dp
                from kivymd.uix.boxlayout import MDBoxLayout
                from kivymd.uix.label import MDLabel
                from kivymd.uix.divider import MDDivider
                from kivymd.uix.dropdownitem import MDDropDownItem, MDDropDownItemText
                from kivymd.uix.scrollview import MDScrollView

                if manager_self.ctx.mapping_page is None:
                    build_mapping_tab(manager_self.ctx, manager_self)
                if manager_self.ctx.items_page is None:
                    build_items_tab(manager_self.ctx, manager_self)
                if manager_self.ctx.mapping_page is not None:
                    startup_tab = manager_self.screens.current_tab
                    if startup_tab is not None:
                        for tab in manager_self.tabs.children:
                            if getattr(tab, "text", None) == "Mapping":
                                tab.active = False
                        startup_tab.active = True
                        startup_tab.on_release()

                sidebar = MDBoxLayout(
                    orientation="vertical",
                    size_hint_x=None,
                    width=dp(280),
                    size_hint_y=1,
                )
                sidebar_scroll = MDScrollView(size_hint=(1, 1), do_scroll_x=False)
                sidebar_content = MDBoxLayout(
                    orientation="vertical",
                    size_hint_y=None,
                    spacing=dp(8),
                    padding=(dp(10), dp(10), dp(10), dp(10)),
                )
                sidebar_content.bind(minimum_height=sidebar_content.setter("height"))

                sidebar_content.add_widget(MDLabel(text="Visual Tracker", bold=True, adaptive_height=True))
                sidebar_content.add_widget(MDDivider())

                manager_self.vt_status_label = MDLabel(text="Not connected", adaptive_height=True)
                manager_self.vt_game_label = MDLabel(text="Game: -", adaptive_height=True)
                manager_self.vt_slot_label = MDLabel(text="Slot: -", adaptive_height=True)
                manager_self.vt_checks_label = MDLabel(text="Checks: 0/0", adaptive_height=True)
                manager_self.vt_logic_label = MDLabel(text="In Logic: 0", adaptive_height=True)
                manager_self.vt_preset_label = MDLabel(text="Preset: No preset loaded", adaptive_height=True)
                manager_self.vt_selection_title = MDLabel(
                    text="Selection: none",
                    adaptive_height=True,
                    bold=True,
                )
                manager_self.vt_selection_body = MDLabel(
                    text="Click a map pin to inspect its locations.",
                    markup=True,
                    adaptive_height=True,
                    halign="left",
                )

                for widget in (
                    manager_self.vt_status_label,
                    manager_self.vt_game_label,
                    manager_self.vt_slot_label,
                    manager_self.vt_checks_label,
                    manager_self.vt_logic_label,
                    manager_self.vt_preset_label,
                ):
                    sidebar_content.add_widget(widget)

                sidebar_content.add_widget(MDDivider())
                packs_section = MDBoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
                packs_header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(32), spacing=dp(8))
                packs_header.add_widget(MDLabel(text="Visual Packs", bold=True, size_hint_x=1, halign="left"))
                packs_header.add_widget(
                    MDButton(
                        MDButtonText(text="Refresh"),
                        style="text",
                        size_hint_x=None,
                        on_release=lambda *_: manager_self.refresh_visual_packs_list(),
                    )
                )
                packs_section.add_widget(packs_header)

                manager_self.vt_pack_dropdown = MDDropDownItem(size_hint_x=1, size_hint_y=None, height=dp(48))
                manager_self.vt_pack_dropdown_text = MDDropDownItemText(text=manager_self.visual_pack_label)
                manager_self.vt_pack_dropdown.add_widget(manager_self.vt_pack_dropdown_text)
                manager_self.vt_pack_dropdown.bind(on_release=manager_self.open_visual_pack_dropdown)
                packs_section.add_widget(manager_self.vt_pack_dropdown)
                packs_section.bind(minimum_height=packs_section.setter("height"))
                sidebar_content.add_widget(packs_section)

                sidebar_content.add_widget(MDDivider())
                from .gui import ItemQualityFilter

                ool_filter = ItemQualityFilter(
                    text="Show out-of-logic tabs",
                    filter_key="out_of_logic_tabs",
                    active=False,
                )

                def _on_ool_filter(_instance, value):
                    manager_self.show_out_of_logic_tabs = bool(value)

                ool_filter.bind(active=_on_ool_filter)
                manager_self.bind(show_out_of_logic_tabs=manager_self.on_show_out_of_logic_tabs)
                sidebar_content.add_widget(ool_filter)

                sidebar_content.add_widget(MDDivider())
                sidebar_content.add_widget(manager_self.vt_selection_title)
                sidebar_content.add_widget(manager_self.vt_selection_body)

                sidebar_scroll.add_widget(sidebar_content)
                sidebar.add_widget(sidebar_scroll)
                manager_self.main_area_container.add_widget(sidebar)
                Clock.schedule_once(lambda _dt: manager_self.refresh_visual_packs_list(), 0)
                Clock.schedule_once(lambda _dt: manager_self.refresh_items_tab(), 0)

            def update_texts(manager_self, dt):
                super().update_texts(dt)
                if not hasattr(manager_self, "vt_status_label"):
                    return
                connected = bool(manager_self.ctx.server)
                manager_self.vt_status_label.text = "Connected" if connected else "Not connected"
                manager_self.vt_game_label.text = f"Game: {manager_self.ctx.game or '-'}"
                slot_name = manager_self.ctx.player_names.get(manager_self.ctx.slot, "-") if manager_self.ctx.slot else "-"
                manager_self.vt_slot_label.text = f"Slot: {slot_name}"
                manager_self.vt_checks_label.text = (
                    f"Checks: {len(manager_self.ctx.checked_locations)}/{manager_self.ctx.total_locations or 0}"
                )
                in_logic_count = len(manager_self.ctx.tracker_core.locations_available) if manager_self.ctx.tracker_core else 0
                manager_self.vt_logic_label.text = f"In Logic: {in_logic_count}"
                manager_self.vt_preset_label.text = f"Preset: {manager_self.mapping_current_tab}"
                manager_self.mapping_preset_enabled = can_load_mapping_preset(manager_self.ctx)
                manager_self.mapping_has_preset = bool(manager_self.ctx.mapping_tabs)

            def update_mapping_selection(manager_self, title: str, body: str):
                if not hasattr(manager_self, "vt_selection_title"):
                    return
                manager_self.vt_selection_title.text = title
                manager_self.vt_selection_body.text = body

        apply_mapping_manager_features(
            VisualTrackerManager,
            MDDropdownMenu=MDDropdownMenu,
            MarkupDropdown=MarkupDropdown,
            get_ut_color=get_ut_color,
        )
        apply_items_manager_features(
            VisualTrackerManager,
            get_ut_color=get_ut_color,
        )

        VisualTrackerManager.base_title = "Archipelago Visual Tracker"
        return VisualTrackerManager

    def load_kv(self):
        super().load_kv()
        load_visualtracker_kv()

    def build_gui(self, manager):
        # Mapping/Items tabs are created after the main window finishes building.
        # Skip UT's Map Page GUI; Visual Tracker uses its own Mapping tab instead.
        # Keep a safe coords fallback in case UT connect logic still calls load_map.
        self.map_page_coords_func = lambda *args: ({}, {}, {})
        return

    def load_map(self, map_id: typing.Union[int, str, None] = None):
        # UT Map Page is not used by Visual Tracker. Skipping avoids the UT crash
        # when map_page_coords_func is still the empty-dict fallback.
        return

    def load_pack(self):
        # Same as load_map: VT does not host UT poptracker map packs.
        self.tracker_world = None

    def update_location_icon_coords(self):
        return

    def updateTracker(self) -> CurrentTrackerState:
        from .mapping import (
            ensure_preferred_mapping_tab,
            find_preferred_mapping_tab_path,
            maybe_reselect_filtered_mapping_tab,
        )

        hints = {}
        if f"_read_hints_{self.team}_{self.slot}" in self.stored_data:
            from NetUtils import HintStatus

            hints = {
                hint["location"]: hint["status"]
                for hint in self.stored_data[f"_read_hints_{self.team}_{self.slot}"]
                if hint["status"] not in [HintStatus.HINT_FOUND, HintStatus.HINT_AVOID]
                and self.slot_concerns_self(hint["finding_player"])
            }
        result = super().updateTracker()
        if getattr(self, "_prefer_in_logic_tab", False):
            if ensure_preferred_mapping_tab(self, logger):
                self._prefer_in_logic_tab = False
            elif find_preferred_mapping_tab_path(self, allow_glitched_fallback=False) is not None:
                self._prefer_in_logic_tab = False
            elif self.tracker_core and self.tracker_core.multiworld:
                # Tracker logic is ready and no in-logic tabs exist yet.
                self._prefer_in_logic_tab = False
        maybe_reselect_filtered_mapping_tab(self, logger)
        update_mapping_pin_status(self, hints)
        update_items_tab(self, result)
        if self.ui and hasattr(self.ui, "refresh_mapping_tab_selectors"):
            self.ui.refresh_mapping_tab_selectors()
        if self.selected_mapping_pin:
            self.select_mapping_pin(self.selected_mapping_pin)
        return result

    def load_mapping_preset(self, preset_path: str | None = None):
        load_mapping_preset(self, logger, preset_path)

    def select_mapping_pin(self, pin) -> None:
        self.selected_mapping_pin = pin
        if not self.ui or not self.game:
            return
        location_id_to_name = self.location_names[self.game]
        location_count = len(pin.locationDict)
        if pin.group_label:
            title = pin.group_label
        elif location_count == 1:
            title = location_id_to_name[next(iter(pin.locationDict))]
        else:
            title = f"{location_count} locations"

        body_lines = []
        for location_id, status in pin.locationDict.items():
            color = self._status_color(status)
            if location_count == 1 and not pin.group_label:
                body_lines.append(f"[color={color}]{status}[/color]")
            else:
                body_lines.append(f"- {location_id_to_name[location_id]}: [color={color}]{status}[/color]")
        self.ui.update_mapping_selection(title, "\n".join(body_lines))

    @staticmethod
    def _status_color(status: str) -> str:
        from worlds.tracker.TrackerClient import get_ut_color

        if status in {"in_logic", "out_of_logic", "glitched", "hinted_in_logic", "hinted_out_of_logic", "hinted_glitched"}:
            return get_ut_color(status)
        return get_ut_color("collected_light")

    async def send_connect(self, **kwargs: typing.Any) -> None:
        kwargs["game"] = ""
        await super().send_connect(**kwargs)

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TrackerGameContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect(game="")

    def load_mapping_tab(self, tab_path: list[int] | int | str):
        load_mapping_tab(self, logger, tab_path)

    def mapping_tab_has_available_checks(self, tab: dict) -> bool:
        return mapping_tab_has_available_checks(self, tab)

    async def disconnect(self, allow_autoreconnect: bool = False):
        self.game = ""
        self.selected_mapping_pin = None
        clear_mapping_state(self)
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: dict):
        super().on_package(cmd, args)
        if self.ui is not None and cmd == "Connected" and hasattr(self.ui, "repaint_visual_packs_list"):
            self.ui.repaint_visual_packs_list()


async def main(args):
    ctx = VisualTrackerContext(args.connect, args.password, print_count=args.count, print_list=args.list)
    ctx.auth = args.name
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    ctx.run_generator()

    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()

    await ctx.exit_event.wait()
    await ctx.shutdown()


def launch(*args):
    parser = get_base_parser(description="Archipelago Visual Tracker client.")
    parser.add_argument("--name", default=None, help="Slot Name to connect as.")
    if sys.stdout:
        parser.add_argument("--count", default=False, action="store_true", help="just return a count of in logic checks")
        parser.add_argument("--list", default=False, action="store_true", help="just return a list of in logic checks")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    args = handle_url_arg(parser.parse_args(args))

    if args.nogui and (args.count or args.list):
        if not args.name or not args.connect:
            logger.error("You need a valid URL when running in CLI mode")
            return
        from logging import ERROR
        logger.setLevel(ERROR)

    asyncio.run(main(args))


if __name__ == "__main__":
    launch(*sys.argv[1:])
