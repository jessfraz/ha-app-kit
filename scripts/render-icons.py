"""Render the pinned MDI catalog using the Kit Nix shell's resvg."""

import argparse
import hashlib
import subprocess
import tempfile
import tomllib
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "packages/ha/icons"
RASTERS = (
    # Supervisor has one tile for both themes.
    ("app-icon.png", 128, "#4e80a8"),
    ("icon.png", 256, "#24364b"),
    ("icon@2x.png", 512, "#24364b"),
    ("dark_icon.png", 256, "#dce7f2"),
    ("dark_icon@2x.png", 512, "#dce7f2"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    differing: list[Path] = []
    pins = tomllib.loads((CATALOG / "glyphs.toml").read_text())["glyphs"]
    sources = sorted((CATALOG / "svg").glob("*.svg"))
    if {source.stem for source in sources} != set(pins):
        parser.exit(1, "Catalog SVG files do not match the pinned set\n")
    with tempfile.TemporaryDirectory() as workdir:
        staged_svg = Path(workdir) / "icon.svg"
        staged_png = Path(workdir) / "icon.png"
        for source in sources:
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != pins[source.stem]["sha256"]:
                parser.exit(1, f"Upstream SVG checksum differs for {source}\n")
            viewport = b'viewBox="0 0 24 24"'
            if data.count(viewport) != 1:
                parser.exit(1, f"Expected a 24x24 upstream SVG viewport in {source}\n")
            output = CATALOG / "png" / source.stem
            if not args.check:
                output.mkdir(parents=True, exist_ok=True)
            for filename, size, color in RASTERS:
                # The upstream glyph's path stays intact. Add breathing room
                # around the original viewport and set the theme color.
                svg = data.replace(
                    viewport, f'viewBox="-2 -2 28 28" fill="{color}"'.encode()
                )
                staged_svg.write_bytes(svg)
                subprocess.run(
                    [
                        "resvg",
                        "--width",
                        str(size),
                        "--height",
                        str(size),
                        str(staged_svg),
                        str(staged_png),
                    ],
                    check=True,
                )
                target = output / filename
                png = staged_png.read_bytes()
                if not target.is_file() or target.read_bytes() != png:
                    if args.check:
                        differing.append(target)
                    else:
                        target.write_bytes(png)
    if differing:
        paths = "\n".join(f"  {path}" for path in differing)
        parser.exit(1, f"Catalog PNGs differ from the pinned SVG renders:\n{paths}\n")


if __name__ == "__main__":
    main()
