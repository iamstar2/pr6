#!/usr/bin/env python3
"""Installs an Edge Impulse "Arduino library" export zip into esp32/lib/.

esp32/lib/ is gitignored (the Edge Impulse SDK is ~24MB, too big for the repo) —
run this once after cloning, pointing it at the zip you downloaded from Edge
Impulse Studio (Deployment -> Create Library -> Arduino library).

Usage:
    python esp32/scripts/install_ei_model.py path/to/downloaded-model.zip

What it does:
    1. Extracts the zip to a temp dir.
    2. Finds the single top-level "<ProjectName>_inferencing" folder inside it.
    3. Copies that folder into esp32/lib/ (replacing any existing copy).
    4. Deletes its examples/ subfolder (not needed, saves space).
    5. Prints the header filename to #include in esp32/src/main.cpp, and warns if
       it doesn't match what main.cpp currently includes.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ESP32_DIR = Path(__file__).resolve().parent.parent
LIB_DIR = ESP32_DIR / "lib"
MAIN_CPP = ESP32_DIR / "src" / "main.cpp"


def main() -> None:
    # Windows terminals often default to cp949/cp1252, which can't encode every
    # character used below — force UTF-8 so this doesn't crash on non-UTF-8 consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("zip_path", help="Path to the Edge Impulse Arduino library zip")
    args = ap.parse_args()

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        sys.exit(f"File not found: {zip_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)

        top_level = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(top_level) != 1:
            sys.exit(
                f"Expected exactly one top-level folder in the zip, found {len(top_level)}: "
                f"{[p.name for p in top_level]}"
            )
        library_dir = top_level[0]
        library_name = library_dir.name

        dest = LIB_DIR / library_name
        if dest.exists():
            print(f"Removing existing {dest} ...")
            shutil.rmtree(dest)

        LIB_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Copying {library_name} -> {dest} ...")
        shutil.copytree(library_dir, dest)

    examples_dir = dest / "examples"
    if examples_dir.exists():
        shutil.rmtree(examples_dir)
        print("Removed examples/ (not needed, saves space)")

    header_candidates = list((dest / "src").glob("*.h"))
    header_name = next((h.name for h in header_candidates if h.stem == library_name), None)
    if header_name is None and header_candidates:
        header_name = header_candidates[0].name

    print(f"\nInstalled to {dest}")
    if header_name:
        expected_include = f'#include <{header_name}>'
        print(f"Header to include in esp32/src/main.cpp: {expected_include}")

        if MAIN_CPP.exists():
            main_src = MAIN_CPP.read_text(encoding="utf-8")
            match = re.search(r'#include\s*<([^>]+_inferencing\.h)>', main_src)
            if match and match.group(1) != header_name:
                print(
                    f"\n[WARNING] esp32/src/main.cpp currently includes <{match.group(1)}>, "
                    f"but the installed library's header is <{header_name}>.\n"
                    f"    Update that #include line to match, or the build will fail."
                )
            elif match:
                print("main.cpp's #include already matches - no changes needed.")

    print("\nDone. Next: cd esp32 && pio run")


if __name__ == "__main__":
    main()
