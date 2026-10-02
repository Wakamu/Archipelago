from __future__ import annotations

import asyncio
import typing
import sys
import urllib.parse

from CommonClient import gui_enabled, get_base_parser, handle_url_arg, server_loop
from worlds.tracker.TrackerClient import (
    TrackerCommandProcessor,
    TrackerGameContext,
    CurrentTrackerState,
    logger,
)
import kvui  # noqa: F401 - frozen: set KIVY_DATA_DIR before .gui imports kivy
from .gui import (
    build_items_tab,
    build_mapping_tab,
    load_visualtracker_kv,
    update_items_tab,
    update_mapping_pin_status,
)
from .mapping import (
    _tab_at_path,
    _tab_auto_tab_keys,
    can_load_mapping_preset,
    clear_mapping_state,
    find_mapping_tab_path_for_auto_tab,
    load_mapping_preset,
    load_mapping_tab,
    mapping_tab_has_available_checks,
    resolve_visual_pack,
)


class VisualTrackerCommandProcessor(TrackerCommandProcessor):
    ctx: "VisualTrackerContext"

    def _cmd_slot_data(self, filter_text: str = ""):
        """Print the Connected slot_data from the server (optional key filter)"""
        import json

        ctx = self.ctx
        data = getattr(ctx, "slot_data", None)
        if not ctx.slot:
            logger.info("Not connected.")
            return
        if not data:
            logger.info("No slot_data stored. Connect to a slot first.")
            return

        logger.info(f"Slot {ctx.slot} ({ctx.game}) team={ctx.team}")
        if filter_text:
            matches = {k: v for k, v in data.items() if filter_text.lower() in str(k).lower()}
            if not matches:
                logger.info(f"No slot_data keys matching {filter_text!r}")
                logger.info(f"Available keys: {sorted(data)}")
                return
            data = matches
        else:
            logger.info(f"Keys: {sorted(data)}")

        try:
            text = json.dumps(data, indent=2, sort_keys=True, default=str)
        except TypeError:
            text = repr(data)
        for line in text.splitlines():
            logger.info(line)

    def _cmd_current_map(self):
        """Print Current Map datastorage + Visual Tracker auto-tab match status"""
        from worlds.tracker.TrackerClient import UT_MAP_TAB_KEY

        ctx = self.ctx
        stored = ctx.stored_data or {}
        key = ctx.get_auto_tab_setting_key()

        logger.info(f"Auto-tab: {'Enabled' if ctx.auto_tab else 'Disabled'}")
        logger.info(f"tracker_world loaded: {bool(ctx.tracker_world)}")
        logger.info(f"Datastorage key: {key}")
        if key is None:
            logger.info("Not connected.")
            return
        if key not in stored:
            logger.info("Raw value: <not retrieved yet>")
            map_keys = [k for k in stored if "map" in str(k).lower() or str(k).endswith(UT_MAP_TAB_KEY)]
            if map_keys:
                logger.info(f"Other map-like stored_data keys: {map_keys}")
                for extra in map_keys:
                    logger.info(f"  {extra}: {stored[extra]!r}")
        else:
            raw = stored[key]
            logger.info(f"Raw value: {raw!r} ({type(raw).__name__})")

        raw = stored.get(key, None)
        indexed = None
        if ctx.tracker_world and ctx.tracker_world.map_page_index and raw not in (None, ""):
            try:
                indexed = ctx.tracker_world.map_page_index(raw)
            except Exception as exc:
                indexed = f"<error: {exc}>"
            logger.info(f"map_page_index(raw): {indexed!r}")
        logger.info(f"ctx.map_id (last applied): {getattr(ctx, 'map_id', None)!r}")

        maps = getattr(ctx, "maps", None) or []
        if maps and isinstance(indexed, int) and 0 <= indexed < len(maps):
            logger.info(f"maps.json[{indexed}].name: {maps[indexed].get('name')!r}")
        elif maps:
            logger.info(f"maps.json names: {[m.get('name') for m in maps]}")

        ui_tab = getattr(ctx.ui, "mapping_current_tab", None) if ctx.ui else None
        logger.info(f"Mapping UI tab: {ui_tab!r}")
        logger.info(f"Mapping path: {list(getattr(ctx, 'mapping_tab_path', []) or [])}")
        current = _tab_at_path(ctx.mapping_tabs, list(getattr(ctx, "mapping_tab_path", []) or []))
        if current is not None:
            logger.info(
                f"Mapping tab name={current.get('name')!r} "
                f"map_page_keys={_tab_auto_tab_keys(current)!r}"
            )
        if isinstance(raw, str) and raw and not raw.isdecimal() and ctx.mapping_tabs:
            exact = find_mapping_tab_path_for_auto_tab(ctx.mapping_tabs, raw)
            folded = find_mapping_tab_path_for_auto_tab(
                ctx.mapping_tabs, raw, case_insensitive=True
            )
            logger.info(f"Match path (exact): {exact}")
            logger.info(f"Match path (casefold): {folded}")
            if exact is None and folded is None:
                logger.info(f"No Mapping tab matches raw value {raw!r}")


class VisualTrackerContext(TrackerGameContext):
    game = ""
    tags = TrackerGameContext.tags
    command_processor = VisualTrackerCommandProcessor
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
    pending_visual_pack: str | None = None
    slot_data: dict = {}
    # Visual Tracker skips UT's Map Page GUI (see build_gui). UT's default
    # map_page_coords_func returns {}, which crashes load_map with
    # "not enough values to unpack (expected 3, got 0)". Provide a safe
    # no-op that matches the 3-tuple load_map expects.
    map_page_coords_func = staticmethod(lambda *args: ({}, {}, {}))

    def make_gui(self):
        base_manager_class = super().make_gui()

        from kivy.properties import BooleanProperty, NumericProperty, StringProperty
        from kivymd.uix.button import MDIconButton
        from kivymd.uix.menu import MDDropdownMenu
        from kivymd.uix.tooltip import MDTooltip
        from kvui import HoverBehavior, MarkupDropdown, MDButton, MDButtonText, ToolTip
        from worlds.tracker.TrackerClient import get_ut_color

        from .ui import apply_items_manager_features, apply_mapping_manager_features

        class CreateShortcutIconButton(HoverBehavior, MDIconButton, MDTooltip):
            tooltip_display_delay = 0.1

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                # Clear pos_hint so KivyMD does not center the tooltip in the window.
                self._tooltip = ToolTip(text="Create Shortcut", pos_hint={})

            def to_window(self, x, y, relative=False):
                # Anchor tooltip to the cursor (HoverBehavior.border_point), matching UT pins.
                if self.border_point:
                    return self.border_point
                return super().to_window(x, y)

            def on_enter(self):
                if self.disabled or self.opacity <= 0:
                    return
                self._tooltip.text = "Create Shortcut"
                self.display_tooltip()

            def on_leave(self):
                self.animation_tooltip_dismiss()

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

                status_row = MDBoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=dp(32),
                    spacing=dp(8),
                )
                manager_self.vt_status_label = MDLabel(text="Not connected", adaptive_height=True, size_hint_x=1)
                status_row.add_widget(manager_self.vt_status_label)
                manager_self.vt_shortcut_button = CreateShortcutIconButton(
                    icon="open-in-new",
                    style="standard",
                    size_hint=(None, None),
                    size=(dp(32), dp(32)),
                    pos_hint={"center_y": 0.5},
                    disabled=True,
                    opacity=0,
                )
                manager_self.vt_shortcut_button.bind(
                    on_release=lambda *_: manager_self.create_connection_shortcut()
                )
                status_row.add_widget(manager_self.vt_shortcut_button)
                sidebar_content.add_widget(status_row)

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

                packs_row = MDBoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=dp(48),
                    spacing=dp(8),
                )
                manager_self.vt_pack_dropdown = MDDropDownItem(size_hint_x=1, size_hint_y=None, height=dp(48))
                manager_self.vt_pack_dropdown_text = MDDropDownItemText(text=manager_self.visual_pack_label)
                manager_self.vt_pack_dropdown.add_widget(manager_self.vt_pack_dropdown_text)
                manager_self.vt_pack_dropdown.bind(on_release=manager_self.open_visual_pack_dropdown)
                packs_row.add_widget(manager_self.vt_pack_dropdown)
                packs_row.add_widget(
                    MDButton(
                        MDButtonText(text="Open Folder"),
                        style="text",
                        size_hint_x=None,
                        on_release=lambda *_: manager_self.open_visual_packs_folder(),
                    )
                )
                packs_section.add_widget(packs_row)
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

                auto_tab_filter = ItemQualityFilter(
                    text="Auto-tab",
                    filter_key="auto_tab",
                    active=bool(getattr(manager_self.ctx, "auto_tab", True)),
                )

                def _on_auto_tab_filter(_instance, value):
                    manager_self.ctx.auto_tab = bool(value)

                auto_tab_filter.bind(active=_on_auto_tab_filter)
                manager_self.vt_auto_tab_filter = auto_tab_filter
                sidebar_content.add_widget(auto_tab_filter)

                sidebar_content.add_widget(MDDivider())
                sidebar_content.add_widget(manager_self.vt_selection_title)
                sidebar_content.add_widget(manager_self.vt_selection_body)
                manager_self.vt_missing_box = MDBoxLayout(
                    orientation="vertical",
                    size_hint_y=None,
                    spacing=dp(4),
                )
                manager_self.vt_missing_button = MDButton(
                    MDButtonText(text="Show missing"),
                    style="text",
                    size_hint_x=None,
                    on_release=lambda *_: manager_self.ctx.show_selected_pin_missing(),
                )
                manager_self.vt_missing_label = MDLabel(
                    text="",
                    markup=True,
                    adaptive_height=True,
                    halign="left",
                )
                manager_self.vt_missing_box.bind(
                    minimum_height=manager_self.vt_missing_box.setter("height")
                )
                sidebar_content.add_widget(manager_self.vt_missing_box)

                sidebar_scroll.add_widget(sidebar_content)
                sidebar.add_widget(sidebar_scroll)
                manager_self.main_area_container.add_widget(sidebar)
                Clock.schedule_once(lambda _dt: manager_self.refresh_visual_packs_list(), 0)
                Clock.schedule_once(lambda _dt: manager_self.refresh_items_tab(), 0)
                Clock.schedule_once(lambda _dt: manager_self.ctx.try_autoload_visual_pack(), 0)

            def update_texts(manager_self, dt):
                super().update_texts(dt)
                if not hasattr(manager_self, "vt_status_label"):
                    return
                from .mapping import loaded_pack_is_compatible

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
                if hasattr(manager_self, "vt_shortcut_button"):
                    show_shortcut = loaded_pack_is_compatible(manager_self.ctx)
                    manager_self.vt_shortcut_button.disabled = not show_shortcut
                    manager_self.vt_shortcut_button.opacity = 1 if show_shortcut else 0
                if hasattr(manager_self, "vt_auto_tab_filter"):
                    desired_auto_tab = bool(getattr(manager_self.ctx, "auto_tab", True))
                    if manager_self.vt_auto_tab_filter.active != desired_auto_tab:
                        manager_self.vt_auto_tab_filter.active = desired_auto_tab

            def update_mapping_selection(
                manager_self,
                title: str,
                body: str,
                *,
                show_missing_button: bool = False,
                missing_text: str = "",
            ):
                if not hasattr(manager_self, "vt_selection_title"):
                    return
                manager_self.vt_selection_title.text = title
                manager_self.vt_selection_body.text = body
                manager_self._set_mapping_missing_panel(
                    show_button=show_missing_button,
                    missing_text=missing_text,
                )

            def _set_mapping_missing_panel(
                manager_self,
                *,
                show_button: bool = False,
                missing_text: str = "",
            ):
                box = getattr(manager_self, "vt_missing_box", None)
                button = getattr(manager_self, "vt_missing_button", None)
                label = getattr(manager_self, "vt_missing_label", None)
                if box is None or button is None or label is None:
                    return
                if button.parent is box:
                    box.remove_widget(button)
                if label.parent is box:
                    box.remove_widget(label)
                button.disabled = False
                if show_button:
                    for child in getattr(button, "children", []):
                        if hasattr(child, "text"):
                            child.text = "Show missing"
                    box.add_widget(button)
                if missing_text:
                    label.text = missing_text
                    box.add_widget(label)
                else:
                    label.text = ""

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

    def get_auto_tab_setting_key(self) -> str | None:
        """Data-storage key the game client publishes the current map into.

        Worlds with a UT map pack use ``tracker_world.map_page_setting_key``.
        Worlds that only publish (no pack — so they must not declare
        ``tracker_world``) use slot_data ``map_page_setting_key`` or the
        conventional ``Slot:{player}:Current Map``.
        """
        if not self.slot:
            return None
        from worlds.tracker.TrackerClient import UT_MAP_TAB_KEY

        tw = getattr(self, "tracker_world", None)
        if tw is not None:
            return tw.map_page_setting_key or f"{self.slot}_{self.team}_{UT_MAP_TAB_KEY}"
        raw_key = (getattr(self, "slot_data", None) or {}).get("map_page_setting_key")
        if isinstance(raw_key, str) and raw_key:
            try:
                return raw_key.format(player=self.slot, team=self.team)
            except (KeyError, IndexError, ValueError):
                return raw_key
        return f"Slot:{self.slot}:Current Map"

    def watch_auto_tab_key(self) -> None:
        """Subscribe to the current-map key even when UT has no tracker_world."""
        key = self.get_auto_tab_setting_key()
        if key:
            self.set_notify(key)

    def load_map(self, map_id: typing.Union[int, str, None] = None):
        """UT-compatible auto-tab: map datastorage → Visual Tracker Mapping tab."""
        from .mapping import apply_ut_auto_tab_to_mapping

        if not self.ui:
            return
        if not self.mapping_tabs:
            return

        if map_id is None:
            key = self.get_auto_tab_setting_key()
            if not key:
                return
            raw = self.stored_data.get(key, "")
            if not self.auto_tab:
                return
            # Prefer the raw datastorage value (map name / map_page_key). Games often
            # publish strings that are not in maps.json order; collapsing through
            # map_page_index first turns unknown names into 0 and would wrongly
            # switch to the first Visual Tracker tab.
            if isinstance(raw, str) and raw and not raw.isdecimal():
                if self.map_id is not None and self.map_id == raw:
                    return
                if apply_ut_auto_tab_to_mapping(self, logger, raw):
                    self.map_id = raw
                # Unknown key → leave the current tab alone (do not fall back via index 0).
                return
            if raw in ("", None):
                return
            if not self.tracker_world:
                return
            map_id = self.tracker_world.map_page_index(raw)
            if isinstance(map_id, int) and map_id < 0:
                return
            maps = getattr(self, "maps", None) or []
            if maps and isinstance(map_id, int) and map_id >= len(maps):
                return

        if self.map_id is not None and self.map_id == map_id:
            return

        if apply_ut_auto_tab_to_mapping(self, logger, map_id):
            self.map_id = map_id

    def load_pack(self):
        """Keep tracker_world for UT auto-tab; do not build UT Map Page UI."""
        self.maps = []
        self.locs = []
        self.layouts = []
        self.map_id = None
        if not self.tracker_world:
            return
        try:
            self._load_ut_map_names_for_autotab()
        except Exception:
            logger.warning("Could not load UT map names for auto-tabbing.", exc_info=True)

    def _load_ut_map_names_for_autotab(self) -> None:
        """Load maps.json entries (names) so map_page_index ints can resolve to tab names."""
        from zipfile import is_zipfile

        from worlds.tracker.TrackerClient import load_json, load_json_zip

        tw = self.tracker_world
        current_world = self.tracker_core.get_current_world() if self.tracker_core else None
        if not tw or not current_world:
            return

        maps: list = []
        if tw.map_page_folder and tw.map_page_maps:
            pack_name = current_world.__class__.__module__
            for map_page in tw.map_page_maps:
                maps += load_json(pack_name, f"/{tw.map_page_folder}/{map_page}")
        elif tw.external_pack_key and getattr(current_world, "settings", None) is not None:
            try:
                pack_ref = current_world.settings[tw.external_pack_key]
            except Exception:
                pack_ref = None
            # Do not prompt for a pack here — only use a preconfigured path.
            if pack_ref and is_zipfile(pack_ref):
                for map_page in tw.map_page_maps:
                    maps += load_json_zip(pack_ref, f"{map_page}")

        self.maps = maps

    def update_location_icon_coords(self):
        return

    def _mapping_hints(self) -> dict[int, object]:
        key = f"_read_hints_{self.team}_{self.slot}"
        if key not in self.stored_data:
            return {}
        from NetUtils import HintStatus

        return {
            hint["location"]: hint["status"]
            for hint in self.stored_data[key]
            if hint["status"] not in [HintStatus.HINT_FOUND, HintStatus.HINT_AVOID]
            and self.slot_concerns_self(hint["finding_player"])
        }

    def refresh_mapping_pins(self) -> None:
        """Paint logic colors onto the pins of the currently displayed tab."""
        update_mapping_pin_status(self, self._mapping_hints())

    def updateTracker(self) -> CurrentTrackerState:
        from .mapping import (
            ensure_preferred_mapping_tab,
            find_preferred_mapping_tab_path,
            maybe_reselect_filtered_mapping_tab,
        )

        hints = self._mapping_hints()
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

    def try_autoload_visual_pack(self) -> bool:
        """Load pending_visual_pack once connected and Mapping UI is ready.

        Returns True when the pending request was consumed (loaded or failed
        permanently). Returns False when we should retry later.
        """
        query = self.pending_visual_pack
        if not query:
            return True
        if not self.game:
            return False
        if not self.ui or self.mapping_page is None:
            return False

        path, error = resolve_visual_pack(query, preferred_game=self.game or None)
        if error:
            logger.error(f"Could not auto-load visual pack '{query}': {error}")
            self.pending_visual_pack = None
            return True

        assert path is not None
        logger.info(f"Auto-loading visual pack: {path}")
        self.load_mapping_preset(path)
        if self.ui and hasattr(self.ui, "repaint_visual_packs_list"):
            self.ui.repaint_visual_packs_list()
        # Keep pending on soft failure (e.g. world not ready yet) so Connected
        # / deferred startup can retry. Clear once a preset path is set.
        if self.mapping_preset_path == path:
            self.pending_visual_pack = None
            if self.ui and hasattr(self.ui, "show_mapping_tab"):
                from kivy.clock import Clock

                # Slight delay so we win over other frame-0 UI tab resets.
                Clock.schedule_once(lambda _dt: self.ui.show_mapping_tab(), 0.05)
            return True
        block = None
        from .mapping import get_mapping_preset_block_reason

        block = get_mapping_preset_block_reason(self)
        if block:
            # Still connecting / world missing — retry later.
            return False
        # Load attempted but produced no usable tabs; don't loop forever.
        self.pending_visual_pack = None
        return True

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
        missing_text = getattr(pin, "missing_info", None) or ""
        show_button = not missing_text and self._pin_has_locked_locations(pin)
        self.ui.update_mapping_selection(
            title,
            "\n".join(body_lines),
            show_missing_button=show_button,
            missing_text=missing_text,
        )

    @staticmethod
    def _pin_has_locked_locations(pin) -> bool:
        for status in getattr(pin, "locationDict", {}).values():
            if status == "collected":
                continue
            if status in {"in_logic", "hinted_in_logic"}:
                continue
            return True
        return False

    def show_selected_pin_missing(self) -> None:
        pin = self.selected_mapping_pin
        if not pin or not self.ui:
            return
        button = getattr(self.ui, "vt_missing_button", None)
        if button is not None:
            button.disabled = True
            for child in getattr(button, "children", []):
                if hasattr(child, "text"):
                    child.text = "Checking..."
        pin.missing_info = self._missing_items_text_for_pin(pin)
        self.select_mapping_pin(pin)

    def _missing_items_text_for_pin(self, pin) -> str:
        core = self.tracker_core
        if not core or not core.multiworld or core.player_id is None:
            return "[b]Missing:[/b] tracker logic not ready"
        if self.stored_data and self.stored_data.get("_read_race_mode"):
            return "[b]Missing:[/b] disabled during Race Mode"

        locked = [
            location_id
            for location_id, status in pin.locationDict.items()
            if location_id not in core.locations_available
            and location_id not in self.checked_locations
            and location_id not in core.ignored_locations
        ]
        if not locked:
            return "[b]Missing:[/b] already reachable"

        items_to_check = {
            item.name
            for item in core.multiworld.get_items()
            if item.player == core.player_id and item.advancement
        }
        unlocks: list[str] = []
        try:
            for item_name in sorted(items_to_check):
                core.manual_items.append(item_name)
                try:
                    core.updateTracker()
                    if any(location_id in core.locations_available for location_id in locked):
                        unlocks.append(item_name)
                finally:
                    core.manual_items.pop()
        finally:
            core.updateTracker()

        if not unlocks:
            return "[b]Missing:[/b] no single item unlocks this"
        return "[b]Missing:[/b]\n" + "\n".join(unlocks)

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
        self.slot_data = {}
        self.selected_mapping_pin = None
        clear_mapping_state(self)
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            self.slot_data = dict(args.get("slot_data") or {})
        super().on_package(cmd, args)
        if cmd == "Connected":
            # UT only SetNotify's this key when tracker_world exists. Worlds that
            # publish Current Map without a pack never get that hook — do it here.
            self.watch_auto_tab_key()
            if self.ui is not None and hasattr(self.ui, "repaint_visual_packs_list"):
                self.ui.repaint_visual_packs_list()
            if self.pending_visual_pack:
                if not self.try_autoload_visual_pack() and self.ui is not None:
                    from kivy.clock import Clock

                    Clock.schedule_once(lambda _dt: self.try_autoload_visual_pack(), 0.25)
            return
        if cmd not in ("SetReply", "Retrieved"):
            return
        key = self.get_auto_tab_setting_key()
        if not key:
            return
        keys = args.get("keys")
        if args.get("key") == key or (isinstance(keys, dict) and key in keys) or (
            isinstance(keys, list) and key in keys
        ):
            self.load_map(None)
            self.updateTracker()


async def main(args):
    ctx = VisualTrackerContext(args.connect, args.password, print_count=args.count, print_list=args.list)
    ctx.auth = args.name
    ctx.pending_visual_pack = getattr(args, "pack", None) or None
    if ctx.pending_visual_pack:
        logger.info(f"Will auto-load visual pack after connect: {ctx.pending_visual_pack}")
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    ctx.run_generator()

    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()

    await ctx.exit_event.wait()
    await ctx.shutdown()


def _pack_from_url(url) -> str | None:
    if url is None:
        return None
    query = getattr(url, "query", None)
    if not query and isinstance(url, str):
        query = urllib.parse.urlparse(url).query
    if not query:
        return None
    values = urllib.parse.parse_qs(query).get("pack") or []
    return values[0] if values else None


def launch(*args):
    parser = get_base_parser(description="Archipelago Visual Tracker client.")
    parser.add_argument("--name", default=None, help="Slot Name to connect as.")
    parser.add_argument(
        "--pack",
        default=None,
        help="Visual pack to load after connecting (game name, zip filename/stem, or path).",
    )
    if sys.stdout:
        parser.add_argument("--count", default=False, action="store_true", help="just return a count of in logic checks")
        parser.add_argument("--list", default=False, action="store_true", help="just return a list of in logic checks")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    parsed = handle_url_arg(parser.parse_args(args))
    if not parsed.pack:
        parsed.pack = _pack_from_url(getattr(parsed, "url", None))

    if parsed.nogui and (parsed.count or parsed.list):
        if not parsed.name or not parsed.connect:
            logger.error("You need a valid URL when running in CLI mode")
            return
        from logging import ERROR
        logger.setLevel(ERROR)

    asyncio.run(main(parsed))


if __name__ == "__main__":
    launch(*sys.argv[1:])
