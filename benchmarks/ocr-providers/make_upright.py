"""Generate the `upright` image set from the raw originals.

The benchmark scores two sets, and the difference between them is the point.

`corpus/` holds the photos exactly as the camera wrote them: EXIF
orientation = 6, meaning a *landscape* pixel buffer plus a "rotate 90 CW to
display" tag. Every viewer honours that tag, so the photos look correct on a
phone — but nothing in the OCR pipeline did, so every provider used to receive
them sideways. That is the `sideways` set.

`upright/` is those same photos with the rotation baked into the pixels, which
is what providers see now that `resolve_image()` normalises centrally. It is
derived rather than stored, so the repo carries one copy of each photo instead
of two.

    python make_upright.py corpus upright
"""

import glob
import os
import sys

# The benchmark deliberately uses the service's own normaliser rather than a
# local copy: if _normalize_orientation regresses, the "upright" set regresses
# with it and the numbers move, which is the signal you want.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.image_resolver import _normalize_orientation  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)

    src_dir, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    paths = sorted(glob.glob(os.path.join(src_dir, "*.jpeg")))
    if not paths:
        raise SystemExit(f"no .jpeg files in {src_dir}")

    for path in paths:
        with open(path, "rb") as fh:
            raw = fh.read()
        out = _normalize_orientation(raw, "image/jpeg")
        with open(os.path.join(out_dir, os.path.basename(path)), "wb") as fh:
            fh.write(out)
        note = "rotated" if out != raw else "already upright, copied unchanged"
        print(f"  {os.path.basename(path):18s} {len(raw):>9,} -> {len(out):>9,} bytes  ({note})")


if __name__ == "__main__":
    main()
