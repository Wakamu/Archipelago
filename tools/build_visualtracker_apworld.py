#!/usr/bin/env python3
"""Build visualtracker.apworld for distribution via custom_worlds.

Requires official Universal Tracker (tracker.apworld) to be installed separately.
Visual Tracker is a client-only add-on that adds the Mapping tab on top of UT.

Usage:
    python tools/build_visualtracker_apworld.py
    python tools/build_visualtracker_apworld.py --install
    python tools/build_visualtracker_apworld.py --output dist
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORLD_DIR_NAME = "visualtracker"
CONTAINER_VERSION = 7
GLOBAL_IGNORE_NAMES = {
    "__MACOSX",
    ".DS_Store",
    "__pycache__",
    "archipelago.json",
    ".apignore",
    ".git",
    ".gitignore",
}
REQUIRED_FILES = (
    "__init__.py",
    "Client.py",
    "mapping.py",
    "items.py",
    "ui.py",
    "gui.py",
    "widgets.py",
    "visualtracker.kv",
    "icon.png",
    "archipelago.json",
)


def _validate_world_directory(world_directory: pathlib.Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (world_directory / name).is_file()]
    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(f"Missing required visualtracker files: {missing_list}")


def _iter_world_files(world_directory: pathlib.Path) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in world_directory.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(world_directory)
        if rel.name in GLOBAL_IGNORE_NAMES:
            continue
        if any(part in GLOBAL_IGNORE_NAMES for part in rel.parts):
            continue
        files.append(rel)
    return sorted(files)


def build_visualtracker_apworld(output_dir: pathlib.Path) -> pathlib.Path:
    world_directory = ROOT / "worlds" / WORLD_DIR_NAME
    _validate_world_directory(world_directory)

    manifest_path = world_directory / "archipelago.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    if "game" not in manifest:
        raise ValueError("archipelago.json must define a \"game\" field")

    manifest["version"] = CONTAINER_VERSION
    manifest["compatible_version"] = CONTAINER_VERSION

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{WORLD_DIR_NAME}.apworld"
    manifest_in_zip = pathlib.Path(WORLD_DIR_NAME, "archipelago.json")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel_path in _iter_world_files(world_directory):
            archive.write(world_directory / rel_path, pathlib.Path(WORLD_DIR_NAME, rel_path))
        archive.writestr(str(manifest_in_zip), json.dumps(manifest))

    return zip_path


def _custom_worlds_dir() -> pathlib.Path:
    custom_worlds = ROOT / "custom_worlds"
    custom_worlds.mkdir(parents=True, exist_ok=True)
    return custom_worlds


def install_apworld(apworld_path: pathlib.Path) -> pathlib.Path:
    destination = _custom_worlds_dir() / apworld_path.name
    shutil.copy2(apworld_path, destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build visualtracker.apworld")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=ROOT / "build" / "apworlds",
        help="Output directory (default: build/apworlds)",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy the built apworld into custom_worlds after building",
    )
    args = parser.parse_args(argv)

    try:
        apworld_path = build_visualtracker_apworld(args.output.resolve())
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Built {apworld_path}")

    if args.install:
        try:
            installed_path = install_apworld(apworld_path)
        except Exception as exc:
            print(f"Install failed: {exc}", file=sys.stderr)
            return 1
        print(f"Installed to {installed_path}")

    print()
    print("Distribution notes:")
    print("- Install visualtracker.apworld via the launcher or copy it to custom_worlds")
    print("- Users also need official Universal Tracker (tracker.apworld)")
    print("- Launch 'Archipelago Visual Tracker' from the launcher after both are installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
