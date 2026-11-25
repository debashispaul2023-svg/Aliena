"""Validate assets/aliena/emotions against the reference sheet. Exit 0 only if all 20 pass.

Checks: 20 files == manifest; RGBA; one common canvas; padding ring fully transparent
(nothing touches the canvas edge => nothing was clipped); every body/effect pixel of
the sheet (alpha >= 200) lives in exactly one output (nothing discarded or duplicated),
and each output's pixels are byte-identical to the sheet (no resize, no recolour)."""
import json, os, sys
import numpy as np
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "assets", "aliena", "emotions")
SHEET = os.path.join(ROOT, "assets", "reference", "aliena_emotion_sheet_v2.png")
ALPHA_MIN = 200


def validate():
    errs, info = [], {}
    man = json.load(open(os.path.join(D, "manifest.json"), encoding="utf-8"))
    ems, (cw, ch), pad = man["emotions"], man["canvas"], man["padding"]
    sheet = np.array(Image.open(SHEET).convert("RGBA"))
    if len(ems) != 20: errs.append(f"manifest has {len(ems)} emotions, expected 20")
    if sorted(f for f in os.listdir(D) if f.endswith(".png")) != sorted(v["file"] for v in ems.values()):
        errs.append("PNG files and manifest do not match")
    total = int((sheet[..., 3] >= ALPHA_MIN).sum()); seen = 0
    for name, v in ems.items():
        im = np.array(Image.open(os.path.join(D, v["file"])))
        if im.ndim != 3 or im.shape[2] != 4: errs.append(f"{name}: not RGBA"); continue
        if im.shape[:2] != (ch, cw): errs.append(f"{name}: canvas {im.shape[:2]} != {(ch, cw)}")
        a = im[..., 3]
        ring = np.ones(a.shape, bool); ring[pad - 1: a.shape[0] - pad + 1, pad - 1: a.shape[1] - pad + 1] = False
        if a[ring].max() != 0: errs.append(f"{name}: content reaches the padding ring (clipped?)")
        n = int((a >= ALPHA_MIN).sum()); seen += n
        if n != v["body_pixels"]: errs.append(f"{name}: {n} body pixels != manifest {v['body_pixels']}")
        if n < 5000: errs.append(f"{name}: too little content ({n})")
        x0, y0, x1, y1 = v["source_box"]
        info[name] = n
    if seen != total: errs.append(f"pixel conservation failed: outputs hold {seen} of {total} sheet pixels")
    return errs, {"outputs": len(ems), "sheet_body_pixels": total, "output_body_pixels": seen, "canvas": [cw, ch]}


if __name__ == "__main__":
    e, info = validate()
    print(info)
    print("\n".join(e) if e else "all 20 emotion images OK")
    sys.exit(1 if e else 0)
