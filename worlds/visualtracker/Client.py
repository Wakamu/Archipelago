from __future__ import annotations



import asyncio

import typing

import sys



from CommonClient import gui_enabled, get_base_parser, handle_url_arg, server_loop

from worlds.tracker.TrackerClient import TrackerGameContext, CurrentTrackerState, logger

from .gui import (

    build_mapping_tab,

    load_visualtracker_kv,

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

    mapping_tab_index: int | None = None

    mapping_root_path: str | None = None



    def _prune_visualtracker_tabs(self):

        if not self.ui or not hasattr(self.ui, "tabs"):

            return



        wanted_tabs = {"Archipelago", "All", "Hints", "Mapping"}

        for tab in list(self.ui.tabs.children):

            title = getattr(tab, "text", None)

            if title and title not in wanted_tabs:

                self.ui.remove_client_tab(tab)



    def run_gui(self):

        """Start the visual tracker UI."""

        from kivy.properties import BooleanProperty, NumericProperty, StringProperty

        from kivymd.uix.menu import MDDropdownMenu

        from kvui import MarkupDropdown

        from worlds.tracker.TrackerClient import get_ut_color



        from .ui import apply_mapping_manager_features



        base_manager_class = self.make_gui()



        class VisualTrackerManager(base_manager_class):

            mapping_source = StringProperty("")

            mapping_loc_size = NumericProperty(32)

            mapping_current_tab = StringProperty("No preset loaded")

            mapping_preset_enabled = BooleanProperty(False)

            mapping_has_preset = BooleanProperty(False)

            base_title = "Archipelago Visual Tracker"



            def build(manager_self):

                from kivy.metrics import dp

                from kivymd.uix.boxlayout import MDBoxLayout

                from kivymd.uix.label import MDLabel

                from kivymd.uix.divider import MDDivider

                from kivymd.uix.scrollview import MDScrollView

                from kivy.uix.widget import Widget

                from kvui import MDButton, MDButtonText



                container = super().build()

                manager_self.show_map = False

                manager_self.ctx._prune_visualtracker_tabs()



                manager_self.main_area_container.cols = 2



                sidebar = MDBoxLayout(

                    orientation="vertical",

                    size_hint_x=None,

                    width=dp(280),

                    spacing=dp(8),

                    padding=(dp(10), dp(10), dp(10), dp(10)),

                )

                sidebar.add_widget(MDLabel(text="Visual Tracker", bold=True, adaptive_height=True))

                sidebar.add_widget(MDDivider())



                manager_self.vt_status_label = MDLabel(

                    text="Not connected",

                    adaptive_height=True,

                )

                manager_self.vt_game_label = MDLabel(

                    text="Game: -",

                    adaptive_height=True,

                )

                manager_self.vt_slot_label = MDLabel(

                    text="Slot: -",

                    adaptive_height=True,

                )

                manager_self.vt_checks_label = MDLabel(

                    text="Checks: 0/0",

                    adaptive_height=True,

                )

                manager_self.vt_logic_label = MDLabel(

                    text="In Logic: 0",

                    adaptive_height=True,

                )

                manager_self.vt_preset_label = MDLabel(

                    text="Preset: No preset loaded",

                    adaptive_height=True,

                )

                manager_self.vt_selection_title = MDLabel(

                    text="Selection: none",

                    adaptive_height=True,

                    bold=True,

                )

                manager_self.vt_selection_body = MDLabel(

                    text="Click a map pin to inspect its locations.",

                    markup=True,

                    size_hint_y=None,

                    halign="left",

                    valign="top",

                )

                manager_self.vt_selection_body.bind(

                    width=lambda instance, value: setattr(instance, "text_size", (value, None)),

                    texture_size=lambda instance, value: setattr(instance, "height", value[1]),

                )



                for widget in (

                    manager_self.vt_status_label,

                    manager_self.vt_game_label,

                    manager_self.vt_slot_label,

                    manager_self.vt_checks_label,

                    manager_self.vt_logic_label,

                    manager_self.vt_preset_label,

                ):

                    sidebar.add_widget(widget)



                sidebar.add_widget(MDDivider())

                manager_self.vt_load_preset_button = MDButton(

                    MDButtonText(text="Load Preset"),

                    style="filled",

                    on_release=lambda *_: manager_self.load_mapping_preset_dialog(),

                )

                sidebar.add_widget(manager_self.vt_load_preset_button)

                sidebar.add_widget(MDDivider())

                sidebar.add_widget(manager_self.vt_selection_title)

                selection_scroll = MDScrollView(size_hint=(1, 1), do_scroll_x=False)

                selection_box = MDBoxLayout(

                    orientation="vertical",

                    size_hint_y=None,

                    adaptive_height=True,

                )

                selection_box.add_widget(manager_self.vt_selection_body)

                selection_box.add_widget(Widget(size_hint_y=1))

                selection_scroll.add_widget(selection_box)

                sidebar.add_widget(selection_scroll)

                manager_self.main_area_container.add_widget(sidebar)

                return container



            def update_texts(manager_self, dt):

                super().update_texts(dt)

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

                manager_self.vt_load_preset_button.disabled = not manager_self.mapping_preset_enabled



            def update_mapping_selection(manager_self, title: str, body: str):

                manager_self.vt_selection_title.text = title

                manager_self.vt_selection_body.text = body



        apply_mapping_manager_features(

            VisualTrackerManager,

            MDDropdownMenu=MDDropdownMenu,

            MarkupDropdown=MarkupDropdown,

            get_ut_color=get_ut_color,

        )



        manager_class = VisualTrackerManager

        manager_class.base_title = "Archipelago Visual Tracker"

        self.ui = manager_class(self)

        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")



    def load_kv(self):

        super().load_kv()

        load_visualtracker_kv()



    def make_gui(self):

        return super().make_gui()



    def build_gui(self, manager):

        super().build_gui(manager)

        build_mapping_tab(self, manager)



    def updateTracker(self) -> CurrentTrackerState:

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

        update_mapping_pin_status(self, hints)

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

        if pin.group_label:

            title = pin.group_label

        elif len(pin.locationDict) == 1:

            title = location_id_to_name[next(iter(pin.locationDict))]

        else:

            title = f"{len(pin.locationDict)} locations"



        body_lines = []

        for location_id, status in pin.locationDict.items():

            color = self._status_color(status)

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



    def load_mapping_tab(self, tab_index: int | str):

        load_mapping_tab(self, logger, tab_index)



    def mapping_tab_has_available_checks(self, tab: dict) -> bool:

        return mapping_tab_has_available_checks(self, tab)



    async def disconnect(self, allow_autoreconnect: bool = False):

        self.game = ""

        self.selected_mapping_pin = None

        clear_mapping_state(self)

        await super().disconnect(allow_autoreconnect)



    def on_package(self, cmd: str, args: dict):

        super().on_package(cmd, args)

        if self.ui is not None:

            if hasattr(self.ui, "show_map"):

                self.ui.show_map = False

            self._prune_visualtracker_tabs()





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

