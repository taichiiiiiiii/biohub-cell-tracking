"""Bundle all train GT .geff directories into one tar for a single-shot download."""
import subprocess
from pathlib import Path

SRC = Path("/kaggle/input/biohub-cell-tracking-during-development/train")
geffs = sorted(SRC.glob("*.geff"))
print(f"{len(geffs)} geff dirs")
subprocess.run(
    ["tar", "-czf", "/kaggle/working/train_geffs.tar.gz", "-C", str(SRC)]
    + [g.name for g in geffs],
    check=True,
)
out = Path("/kaggle/working/train_geffs.tar.gz")
print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")
