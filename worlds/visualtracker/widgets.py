from __future__ import annotations

from collections import Counter
from typing import Callable

import kvui  # noqa: F401 - frozen: set KIVY_DATA_DIR before kivy imports
from kivy.graphics.transformation import Matrix
from kivy.uix.scatter import Scatter
from kivy.uix.stencilview import StencilView


class MapScatter(Scatter):
    """Transform-only scatter. Never grabs — all do_* stay False."""

    def __init__(self, **kwargs):
        kwargs.setdefault("do_rotation", False)
        kwargs.setdefault("do_scale", False)
        kwargs.setdefault("do_translation", False)
        kwargs.setdefault("auto_bring_to_front", False)
        super().__init__(**kwargs)
        self.scale_min = 1.0
        self.scale_max = 8.0

    def on_touch_down(self, touch):
        # Forward to children in local space; never run Scatter's grab/transform path.
        touch.push()
        touch.apply_transform_2d(self.to_local)
        handled = False
        for child in self.children[:]:
            if child.dispatch("on_touch_down", touch):
                handled = True
                break
        touch.pop()
        return handled

    def on_touch_move(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        handled = False
        for child in self.children[:]:
            if child.dispatch("on_touch_move", touch):
                handled = True
                break
        touch.pop()
        return handled

    def on_touch_up(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        handled = False
        for child in self.children[:]:
            if child.dispatch("on_touch_up", touch):
                handled = True
                break
        touch.pop()
        return handled


class ZoomableMapHost(StencilView):
    """Clipped viewport. Zooms via MapScatter matrix (not child resize)."""

    ZOOM_STEP = 1.15

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(size=self._sync_scatter, pos=self._sync_scatter, children=self._sync_scatter)

    def _scatter(self):
        return self.children[0] if self.children else None

    def _content(self):
        scatter = self._scatter()
        if scatter is None or not scatter.children:
            return None
        return scatter.children[0]

    def _sync_scatter(self, *_args) -> None:
        scatter = self._scatter()
        if scatter is None or self.width <= 0 or self.height <= 0:
            return
        scatter.size = self.size
        content = self._content()
        if content is not None:
            content.size_hint = (None, None)
            content.size = self.size
            content.pos = (0, 0)
        if scatter.scale <= 1.0 + 1e-6:
            scatter.transform = Matrix()

    def reset_view(self) -> None:
        scatter = self._scatter()
        if scatter is None:
            return
        # Identity transform (don't use scale=1 — that scales around center).
        scatter.transform = Matrix()
        self._sync_scatter()

    def zoom_at(self, parent_x: float, parent_y: float, new_scale: float) -> None:
        """Zoom so the point (parent_x, parent_y) in host coords stays fixed."""
        scatter = self._scatter()
        if scatter is None or self.width <= 0 or self.height <= 0:
            return
        old_scale = float(scatter.scale)
        new_scale = max(float(scatter.scale_min), min(float(scatter.scale_max), float(new_scale)))
        factor = new_scale / old_scale if old_scale > 1e-9 else 1.0
        if abs(factor - 1.0) < 1e-9:
            return

        # CRITICAL: do not assign scatter.scale — that always anchors at the
        # scatter center. apply_transform with an explicit local anchor zooms
        # toward the cursor.
        anchor_x, anchor_y = scatter.to_local(parent_x, parent_y)
        scatter.apply_transform(
            Matrix().scale(factor, factor, 1.0),
            post_multiply=True,
            anchor=(anchor_x, anchor_y),
        )

        if scatter.scale <= 1.0 + 1e-6:
            scatter.transform = Matrix()
            self._sync_scatter()

    def on_touch_down(self, touch):
        if getattr(touch, "is_mouse_scrolling", False):
            if self.width <= 0 or self.height <= 0:
                return False
            scatter = self._scatter()
            if scatter is None:
                return False
            anchor = self._scroll_anchor(touch)
            if anchor is None:
                # Cursor is not over the map — don't steal scroll from selectors/UI.
                return False
            cx, cy = anchor
            if touch.button == "scrolldown":
                self.zoom_at(cx, cy, scatter.scale * self.ZOOM_STEP)
                return True
            if touch.button == "scrollup":
                self.zoom_at(cx, cy, scatter.scale / self.ZOOM_STEP)
                return True
            return False
        return super().on_touch_down(touch)

    @staticmethod
    def _offset_in_touch_space(widget) -> tuple[float, float]:
        """Bottom-left of widget in the coordinate space touches use.

        Touches under an MDScreen/RelativeLayout are in that layout's local
        space. Widget.x/y are only immediate-parent relative, so walk up to
        (but not including) the RelativeLayout and sum positions.
        """
        from kivy.uix.relativelayout import RelativeLayout

        ox = oy = 0.0
        current = widget
        while current is not None:
            ox += float(current.x)
            oy += float(current.y)
            parent = current.parent
            if parent is None or isinstance(parent, RelativeLayout):
                break
            current = parent
        return ox, oy

    def _scroll_anchor(self, touch) -> tuple[float, float] | None:
        """Host-local zoom point, or None if the cursor isn't over this widget.

        Never Window.bind. Never clamp — clamping made top/bottom zooms feel
        like they targeted a point under the cursor.
        """
        from kivy.core.window import Window

        ox, oy = self._offset_in_touch_space(self)
        lx = float(touch.x) - ox
        ly = float(touch.y) - oy
        if 0.0 <= lx <= self.width and 0.0 <= ly <= self.height:
            return lx, ly

        # Wheel events can arrive with a dead/stale touch.pos; use mouse_pos.
        mx, my = float(Window.mouse_pos[0]), float(Window.mouse_pos[1])
        if abs(mx) < 1.0 and abs(my) < 1.0:
            return None
        wx, wy = self.to_window(0.0, 0.0, initial=False, relative=True)
        lx, ly = mx - wx, my - wy
        if 0.0 <= lx <= self.width and 0.0 <= ly <= self.height:
            return lx, ly
        return None


def create_pin_widget_classes(get_ut_color: Callable[[str], str]):
    from kivy.app import App
    from kivy.properties import ColorProperty, DictProperty
    from kivy.uix.widget import Widget
    from kvui import HoverBehavior
    from worlds import AutoWorld

    class ApLocation(HoverBehavior, Widget):
        locationDict = DictProperty()
        hover_padding = 8

        def __init__(self, sections, parent, label=None, on_select=None, **kwargs):
            for location_id in sections:
                self.locationDict[location_id] = "none"
                self.tracker_page = parent
            self.group_label = label
            self.on_select_callback = on_select
            self.bind(locationDict=self.update_color)
            super().__init__(**kwargs)

        def collide_point(self, x, y):
            return (
                self.x - self.hover_padding <= x <= self.right + self.hover_padding
                and self.y - self.hover_padding <= y <= self.top + self.hover_padding
            )

        def on_enter(self, *_args):
            pass

        def on_leave(self, *_args):
            pass

        def transform_to_pop_coords(self, x, y):
            x2 = x
            y2 = self.tracker_page.height - y
            x3 = x2 - (self.tracker_page.x + (self.tracker_page.width - self.tracker_page.norm_image_size[0]) / 2)
            y3 = y2 + (self.tracker_page.y - (self.tracker_page.height - self.tracker_page.norm_image_size[1]) / 2)
            x4 = x3 / (
                (self.tracker_page.norm_image_size[0] / self.tracker_page.texture_size[0])
                if self.tracker_page.texture_size[0] > 0
                else 1
            )
            y4 = y3 / (
                (self.tracker_page.norm_image_size[1] / self.tracker_page.texture_size[1])
                if self.tracker_page.texture_size[0] > 0
                else 1
            )
            x5 = x4 + self.width / 2
            y5 = y4 + self.width / 2
            return (x5, y5)

        def on_mouse_pos(self, window, pos):
            return super().on_mouse_pos(window, pos)

        def to_window(self, x, y):
            if isinstance(self.border_point, (tuple, list)) and len(self.border_point) >= 2:
                return self.border_point
            return self.tracker_page.to_window(x, y)

        def to_widget(self, x, y):
            return self.transform_to_pop_coords(*self.tracker_page.to_widget(x, y))

        def update_status(self, location, status):
            if location in self.locationDict:
                if self.locationDict[location] != status:
                    self.locationDict[location] = status

        def get_text(self):
            ctx = App.get_running_app().ctx
            location_id_to_name = AutoWorld.AutoWorldRegister.world_types[ctx.game].location_id_to_name
            s_return = []
            if self.group_label:
                s_return.append(f"[b]{self.group_label}[/b]")
            for loc, status in self.locationDict.items():
                color = get_ut_color("collected_light")
                if status in [
                    "in_logic",
                    "out_of_logic",
                    "glitched",
                    "hinted_in_logic",
                    "hinted_out_of_logic",
                    "hinted_glitched",
                ]:
                    color = get_ut_color(status)
                s_return.append(f"{location_id_to_name[loc]} : [color={color}]{status}[/color]")
            return "\n".join(s_return)

        def on_touch_down(self, touch):
            if super().on_touch_down(touch):
                return True
            button = getattr(touch, "button", "left")
            if button == "left" and self.hovered:
                if self.on_select_callback:
                    self.on_select_callback(self)
                    return True
            return False

        def update_color(self, locationDict):
            return

    class APLocationMixed(ApLocation):
        color = ColorProperty("#" + get_ut_color("error"))

        def __init__(self, sections, parent, label=None, on_select=None, **kwargs):
            super().__init__(sections, parent, label=label, on_select=on_select, **kwargs)

        @staticmethod
        def update_color(self, locationDict):
            glitches = any(status.endswith("glitched") for status in locationDict.values())
            in_logic = any(status.endswith("in_logic") for status in locationDict.values())
            out_of_logic = any(status.endswith("out_of_logic") for status in locationDict.values())
            hinted = any(status.startswith("hinted") for status in locationDict.values())

            if in_logic and (out_of_logic or (glitches and hinted)):
                self.color = "#" + get_ut_color("mixed_logic")
            elif glitches and hinted:
                self.color = "#" + get_ut_color("hinted_glitched")
            elif hinted and out_of_logic:
                self.color = "#" + get_ut_color("hinted_out_of_logic")
            elif hinted:
                self.color = "#" + get_ut_color("hinted")
            elif glitches and in_logic:
                self.color = "#" + get_ut_color("in_logic_glitched")
            elif glitches and out_of_logic:
                self.color = "#" + get_ut_color("out_of_logic_glitched")
            elif in_logic:
                self.color = "#" + get_ut_color("in_logic")
            elif out_of_logic:
                self.color = "#" + get_ut_color("out_of_logic")
            elif glitches:
                self.color = "#" + get_ut_color("glitched")
            else:
                self.color = "#" + get_ut_color("collected")

    class APLocationSplit(ApLocation):
        color_1 = ColorProperty("#" + get_ut_color("error"))
        color_2 = ColorProperty("#" + get_ut_color("error"))
        color_3 = ColorProperty("#" + get_ut_color("error"))
        color_4 = ColorProperty("#" + get_ut_color("error"))

        def __init__(self, sections, parent, label=None, on_select=None, **kwargs):
            super().__init__(sections, parent, label=label, on_select=on_select, **kwargs)

        @staticmethod
        def update_color(self, locationDict):
            color_list = Counter()

            def sort_status(pair) -> float:
                if pair[0] == "out_of_logic":
                    return 0
                if pair[0] == "in_logic":
                    return 999999999
                if pair[0] == "hinted_in_logic":
                    return 8888888
                return pair[1] + (ord(pair[0][0]) / 10)

            for status in locationDict.values():
                if status == "collected":
                    continue
                color_list[status] += 1

            color_list = [k for k, v in sorted(color_list.items(), key=sort_status, reverse=True)]
            if color_list:
                color_list = (color_list * max(2, (4 // len(color_list))))[:4]
                self.color_1 = "#" + get_ut_color(color_list[0])
                self.color_2 = "#" + get_ut_color(color_list[1])
                self.color_3 = "#" + get_ut_color(color_list[2])
                self.color_4 = "#" + get_ut_color(color_list[3])
            else:
                self.color_1 = "#" + get_ut_color("collected")
                self.color_2 = "#" + get_ut_color("collected")
                self.color_3 = "#" + get_ut_color("collected")
                self.color_4 = "#" + get_ut_color("collected")

    return APLocationMixed, APLocationSplit
