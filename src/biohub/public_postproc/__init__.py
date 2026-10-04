# Derived from the public Kaggle notebook "Clean Approach + Lightweight Local CV | No Hack"
# by Yusuke Togashi (https://www.kaggle.com/code/yusuketogashi/clean-approach-lightweight-local-cv-no-hack),
# licensed under the Apache License 2.0 (LICENSES/Apache-2.0.txt).
# Modified: ported from notebook cells into a torch-free package; see THIRD_PARTY_NOTICES.md.
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
