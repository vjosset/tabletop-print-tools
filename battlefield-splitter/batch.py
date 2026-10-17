#!/usr/bin/env python3
"""
Batch-run BattlefieldPDFGen.py over all images in a folder.

Usage:
    python batch.py <folder> [BattlefieldPDFGen args...]

Examples:
    python batch.py ./maps --tiles 3x2
    python batch.py ./maps --tiles 3x3 --paper a4 --instructions
"""
import subprocess
import sys
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

if len(sys.argv) < 2:
    sys.exit("Usage: python batch.py <folder> [BattlefieldPDFGen args...]")

folder = Path(sys.argv[1]).resolve()
if not folder.is_dir():
    sys.exit(f"Folder not found: {folder}")

extra_args = sys.argv[2:]
images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)

if not images:
    sys.exit(f"No images found in {folder}")

print(f"Found {len(images)} image(s) in {folder.name}/\n")

failed = []
for img in images:
    print(f"--- {img.name} ---")
    result = subprocess.run(
        [sys.executable, "BattlefieldPDFGen.py", str(img)] + extra_args
    )
    if result.returncode != 0:
        failed.append(img.name)
    print()

if failed:
    print(f"Done. {len(failed)} file(s) failed: {', '.join(failed)}")
else:
    print(f"Done. All {len(images)} image(s) processed successfully.")
