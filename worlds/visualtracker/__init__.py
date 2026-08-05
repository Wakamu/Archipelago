from worlds.LauncherComponents import Component, components, Type, launch as launch_component, icon_paths
from worlds.AutoWorld import World


def launch_client(*args):
    try:
        # Frozen installs need kvui to set KIVY_DATA_DIR before any kivy import.
        # Desktop shortcuts launch this component without the launcher GUI having
        # already imported kvui, so do it here first.
        import kvui  # noqa: F401
        from .Client import launch
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("worlds.tracker"):
            from Utils import messagebox

            messagebox(
                "Missing Universal Tracker",
                "Archipelago Visual Tracker requires Universal Tracker (tracker.apworld) to be installed.",
                error=True,
            )
            return
        raise
    launch_component(launch, name="Archipelago Visual Tracker", args=args)


icon_paths["visual_tracker"] = f"ap:{__name__}/icon.png"
components.append(
    Component(
        "Archipelago Visual Tracker",
        None,
        func=launch_client,
        component_type=Type.CLIENT,
        icon="visual_tracker",
    )
)


class VisualTrackerWorld(World):
    game = "Archipelago Visual Tracker"
    hidden = True
    item_name_to_id = {}
    location_name_to_id = {}
