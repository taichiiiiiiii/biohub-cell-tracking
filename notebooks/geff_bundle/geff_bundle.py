"""Bundle all train GT .geff directories into one tar for a single-shot download."""
import subprocess
from pathlib import Path

INPUT = Path("/kaggle/input")
print("input roots:", [p.name for p in INPUT.iterdir()])
for root in INPUT.iterdir():
    for sub in sorted(root.iterdir()):
        print(" ", root.name + "/" + sub.name)

geffs = sorted(INPUT.glob("*/train/*.geff"))
if not geffs:
    geffs = sorted(INPUT.glob("*/*/train/*.geff"))
print(f"{len(geffs)} geff dirs found")
assert geffs, "no geffs under /kaggle/input"
src = geffs[0].parent
subprocess.run(
    ["tar", "-czf", "/kaggle/working/train_geffs.tar.gz", "-C", str(src)]
    + [g.name for g in geffs],
    check=True,
)
out = Path("/kaggle/working/train_geffs.tar.gz")
print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")
