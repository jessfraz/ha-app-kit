"""Check or sync native Home Assistant icons from the locked Kit catalog."""

import argparse
import hashlib
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

from ha_app_kit.bundle import resolve_locked_kit


def sync_brand(catalog: Path, app: Path, integration: Path, *, check: bool) -> str:
    """Use the sidebar glyph for both native raster surfaces and their logos."""
    config = app / "config.yaml"
    settings = yaml.safe_load(config.read_text())
    icon = settings.get("panel_icon") if isinstance(settings, dict) else None
    if not isinstance(icon, str) or not re.fullmatch(r"mdi:[a-z0-9-]+", icon):
        raise ValueError(f"{config}: expected an MDI panel_icon")
    name = icon.removeprefix("mdi:")
    source = catalog / "svg" / f"{name}.svg"
    if not source.is_file():
        raise ValueError(f"{config}: {icon} is missing from the locked Kit catalog")
    provenance = tomllib.loads((catalog / "glyphs.toml").read_text())
    glyph = provenance["glyphs"][name]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != glyph["sha256"]:
        raise ValueError(f"{source}: pinned upstream checksum differs")

    brand = integration / "brand"
    if brand.is_symlink() or (brand.exists() and not brand.is_dir()):
        raise ValueError(f"{brand}: expected a regular directory")
    rendered = catalog / "png" / name
    files = {app / "icon.png": "app-icon.png"}
    for prefix in ("", "dark_"):
        for density in ("", "@2x"):
            icon_file = f"{prefix}icon{density}.png"
            files[brand / icon_file] = icon_file
            logo = brand / f"{prefix}logo{density}.png"
            if logo.exists() or logo.is_symlink():
                files[logo] = icon_file
    app_logo = app / "logo.png"
    if app_logo.exists() or app_logo.is_symlink():
        files[app_logo] = "icon@2x.png"

    notice = (
        f"Material Design Icons glyph: {icon}\n"
        f"Upstream author: {glyph['author']}\n"
        f"Original SVG SHA-256: {source_hash}\n"
        "The PNGs are adapted from the original SVG with padding and color.\n\n"
    ).encode()
    notice += (catalog / "SOURCE.txt").read_bytes()
    notice += b"\n" + (catalog / "UPSTREAM-LICENSE.txt").read_bytes()
    notice += b"\n" + (catalog / "APACHE-2.0.txt").read_bytes()
    expected = {
        path: (rendered / filename).read_bytes() for path, filename in files.items()
    }
    expected[app / "ICON-LICENSE.txt"] = notice
    expected[integration / "ICON-LICENSE.txt"] = notice

    differing: list[Path] = []
    for path, data in expected.items():
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"{path}: expected a regular file")
        if not path.is_file() or path.read_bytes() != data:
            differing.append(path)
    if check and differing:
        paths = "\n".join(f"  {path}" for path in differing)
        raise ValueError(f"{icon} has missing or mismatched files:\n{paths}")
    if not check:
        brand.mkdir(exist_ok=True)
        for path in differing:
            path.write_bytes(expected[path])
    return icon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=Path("Cargo.toml"))
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    try:
        kit = resolve_locked_kit(args.manifest_path)
        icon = sync_brand(
            kit.root / "icons",
            args.app.resolve(strict=True),
            args.integration.resolve(strict=True),
            check=args.check,
        )
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.exit(1, f"{error}\n")
    print(f"{icon} matches {kit.tag} ({kit.revision})")


if __name__ == "__main__":
    main()
