"""Local entry point for the official trainer on non-CUDA machines.

The official script synchronizes CUDA unconditionally for timing.  On a local
CPU/MPS runtime those calls are invalid, so this wrapper supplies a no-op
synchronization hook and then executes the unchanged official trainer.
"""

import runpy
from pathlib import Path

import torch


def main() -> None:
    if not torch.cuda.is_available():
        torch.cuda.synchronize = lambda: None
    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "official" / "scripts" / "train_unet_transformer.py"),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
