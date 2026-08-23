"""Local, torch-free port of the public Kaggle notebook's post-processing stack.

Ports (near-verbatim) the notebook cells that turn raw UNet+transformer+ILP
prediction graphs (``*.geff``) into the competition submission CSV: motion
relink, gap close (+ density-adaptive threshold, synthetic-midpoint
refinement), single-parent repair, safe-division post-linking, short-track
filter/rescue, and linefit smoothing. See ``scripts/postproc_geffs.py`` for
the CLI entry point and ``config.py`` for the preset that reproduces
``outputs/kaggle/base1_v1/submission.csv``.
"""
from __future__ import annotations
