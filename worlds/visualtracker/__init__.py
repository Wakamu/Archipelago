from worlds.LauncherComponents import Component, components, Type, launch as launch_component, icon_paths
from worlds.AutoWorld import World


def launch_client(*args):
    try:
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
