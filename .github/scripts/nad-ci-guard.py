#!/usr/bin/env python3
"""Apply and validate NAD CI invariants."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parents[2]
OFF_FLAGS = {
    "ENABLE_AJA": False,
    "ENABLE_DECKLINK": False,
}
CONFIGURE_PRESETS = {"macos", "ubuntu", "windows-x64", "windows-arm64"}
FLATPAK_FLAGS = ["-DENABLE_AJA=OFF", "-DENABLE_DECKLINK=OFF"]
CONFLICT_MARKERS = re.compile(r"^(<<<<<<<|>>>>>>>)", re.MULTILINE)


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: pathlib.Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: pathlib.Path, data: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def apply_cmake_presets() -> bool:
    path = ROOT / "CMakePresets.json"
    if not path.exists():
        return False

    data = load_json(path)
    changed = False
    for preset in data.get("configurePresets", []):
        if not isinstance(preset, dict):
            continue
        cache = preset.setdefault("cacheVariables", {})
        if not isinstance(cache, dict):
            continue
        name = preset.get("name")
        should_set = name in CONFIGURE_PRESETS or any(key in cache for key in OFF_FLAGS)
        if not should_set:
            continue
        for key, value in OFF_FLAGS.items():
            if cache.get(key) != value:
                cache[key] = value
                changed = True

    if changed:
        write_json(path, data)
    return changed


def apply_flatpak_manifest() -> bool:
    path = ROOT / "build-aux" / "com.obsproject.Studio.json"
    if not path.exists():
        return False

    data = load_json(path)
    changed = False
    for module in data.get("modules", []):
        if not isinstance(module, dict) or module.get("name") not in {"obs", "obs-studio"}:
            continue
        opts = module.setdefault("config-opts", [])
        if not isinstance(opts, list):
            continue
        filtered = [
            opt
            for opt in opts
            if opt not in {"-DENABLE_AJA=ON", "-DENABLE_DECKLINK=ON"}
        ]
        for flag in FLATPAK_FLAGS:
            if flag not in filtered:
                filtered.append(flag)
        if filtered != opts:
            module["config-opts"] = filtered
            changed = True

    if changed:
        write_json(path, data)
    return changed


def apply_package_applescript() -> bool:
    path = ROOT / "cmake" / "macos" / "resources" / "package.applescript"
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    updated = text.replace('item "OBS.app"', 'item "APP_NAME_PLACEHOLDER"')
    updated = updated.replace('item "OBS Studio.app"', 'item "APP_NAME_PLACEHOLDER"')
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def iter_tracked_text_files() -> Iterable[pathlib.Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    for item in result.stdout.splitlines():
        path = ROOT / item
        if path.is_file():
            yield path


def check_conflict_markers(errors: list[str]) -> None:
    for path in iter_tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if CONFLICT_MARKERS.search(text):
            errors.append(f"{rel(path)} contains merge conflict markers")


def check_cmake_presets(errors: list[str]) -> None:
    path = ROOT / "CMakePresets.json"
    data = load_json(path)
    seen = set()
    for preset in data.get("configurePresets", []):
        if not isinstance(preset, dict):
            continue
        name = preset.get("name")
        cache = preset.get("cacheVariables", {})
        if name in CONFIGURE_PRESETS:
            seen.add(name)
            for key in OFF_FLAGS:
                if cache.get(key) is not False:
                    errors.append(f"{rel(path)} preset {name} must set {key}=false")
    missing = CONFIGURE_PRESETS - seen
    for name in sorted(missing):
        errors.append(f"{rel(path)} missing configure preset {name}")


def check_flatpak_manifest(errors: list[str]) -> None:
    path = ROOT / "build-aux" / "com.obsproject.Studio.json"
    data = load_json(path)
    obs_modules = [
        module
        for module in data.get("modules", [])
        if isinstance(module, dict) and module.get("name") in {"obs", "obs-studio"}
    ]
    if not obs_modules:
        errors.append(f"{rel(path)} missing obs module")
        return
    opts = obs_modules[0].get("config-opts", [])
    for flag in FLATPAK_FLAGS:
        if flag not in opts:
            errors.append(f"{rel(path)} missing {flag}")


def check_package_applescript(errors: list[str]) -> None:
    path = ROOT / "cmake" / "macos" / "resources" / "package.applescript"
    text = path.read_text(encoding="utf-8")
    if "APP_NAME_PLACEHOLDER" not in text:
        errors.append(f"{rel(path)} missing APP_NAME_PLACEHOLDER")


def check_cmake_options(errors: list[str]) -> None:
    option_paths = {
        "ENABLE_AJA": ROOT / "plugins" / "aja" / "CMakeLists.txt",
        "ENABLE_DECKLINK": ROOT / "plugins" / "decklink" / "CMakeLists.txt",
    }
    for option, path in option_paths.items():
        text = path.read_text(encoding="utf-8")
        if f"option({option}" not in text:
            errors.append(f"{rel(path)} missing option({option})")


def check_workflow_refs(errors: list[str]) -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    for path in sorted(workflow_dir.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"uses:\s*(\./[^\s#]+)", text):
            ref = ROOT / match.group(1)
            if not ref.exists():
                errors.append(f"{rel(path)} references missing {match.group(1)}")
        for match in re.finditer(r"(?m)^\s*(\.github/scripts/[A-Za-z0-9_.\-/]+)", text):
            ref = ROOT / match.group(1)
            if not ref.exists():
                errors.append(f"{rel(path)} references missing {match.group(1)}")


def check_zsh_syntax(errors: list[str]) -> None:
    zsh = shutil.which("zsh")
    if not zsh:
        return
    scripts = [
        ".github/scripts/.build.zsh",
        ".github/scripts/.package.zsh",
        ".github/scripts/utils.zsh/create_diskimage",
    ]
    for script in scripts:
        path = ROOT / script
        if not path.exists():
            errors.append(f"{script} is missing")
            continue
        result = subprocess.run([zsh, "-n", str(path)], cwd=ROOT)
        if result.returncode:
            errors.append(f"{script} failed zsh -n")


def apply_invariants() -> int:
    changed = [
        apply_cmake_presets(),
        apply_flatpak_manifest(),
        apply_package_applescript(),
    ]
    print("NAD invariants applied." if any(changed) else "NAD invariants already satisfied.")
    return 0


def validate() -> int:
    errors: list[str] = []
    checks = [
        check_conflict_markers,
        check_cmake_presets,
        check_flatpak_manifest,
        check_package_applescript,
        check_cmake_options,
        check_workflow_refs,
        check_zsh_syntax,
    ]
    for check in checks:
        check(errors)

    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    print("NAD CI guard validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["apply", "validate"])
    args = parser.parse_args()
    if args.command == "apply":
        return apply_invariants()
    return validate()


if __name__ == "__main__":
    sys.exit(main())
