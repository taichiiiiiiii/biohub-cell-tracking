# Third-party notices

The original code in this repository is licensed under the MIT License ([`LICENSE`](LICENSE)).
The parts listed below are derived from third-party work and remain under their original licenses.

## Public Kaggle notebooks (Apache License 2.0)

Each notebook page on Kaggle states "This Notebook has been released under the Apache 2.0 open source license"
(checked 2026-10-03). A copy of the license is in [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt).

| Source notebook | Author (Kaggle) | Derived files in this repository | Changes |
|---|---|---|---|
| [`yusuketogashi/clean-approach-lightweight-local-cv-no-hack`](https://www.kaggle.com/code/yusuketogashi/clean-approach-lightweight-local-cv-no-hack) | Yusuke Togashi | `notebooks/base1_clean_unet_ilp/`; `src/biohub/public_postproc/` (`__init__`, `config`, `csv_out`, `deepcenter`, `divisions`, `frames`, `geometry`, `graph_ops`, `pipeline`) | Notebook: Lite-CV phase and cover-image cell removed. Package: post-processing cells ported into a torch-free Python package with explicit config objects |
| [`kunaldesale2408/biohub-cell-tracking`](https://www.kaggle.com/code/kunaldesale2408/biohub-cell-tracking) | Kunal Desale | `notebooks/base2_dual_seed_harmonic/`, `notebooks/eval_train_raw/` | Experiment values reverted to the author's reported LB-0.915 values; validator export added |
| [`evgendvorkin/biohub-0-923-lb`](https://www.kaggle.com/code/evgendvorkin/biohub-0-923-lb) | evgendvorkin | `notebooks/pub923_repro/` (final submission), `notebooks/e23_association_collection/`, `notebooks/e23_association_parity/`, `notebooks/e26_target_motion_off/`, `notebooks/e26_target_motion_off_bounds/`, `notebooks/e31_primary_consensus/` | Forked unmodified, then changed by the single-factor experiments recorded in `analysis/experiment_ledger.md` |
| [`haideptry/biohub-0-951-sota-deepcenter-fast-ilp-19m`](https://www.kaggle.com/code/haideptry/biohub-0-951-sota-deepcenter-fast-ilp-19m) | haideptry | Settings and code ported into `notebooks/pub923_repro/` | Density-group motion-relink overrides, rank bonus, sister-symmetry veto |
| [`beraterolelk/0-947-lb-biohub-deepcenter-ilp-tracker`](https://www.kaggle.com/code/beraterolelk/0-947-lb-biohub-deepcenter-ilp-tracker) | Berat Erol Çelik | Settings and code ported into `notebooks/pub923_repro/` | Edge-feature TTA, sister-symmetry veto, DeepCenter TTA |

The upstream notebooks above may themselves build on earlier public notebooks; see their Kaggle pages for their own
credits.

## Official metric and baseline (BSD-3-Clause)

[`royerlab/kaggle-cell-tracking-competition`](https://github.com/royerlab/kaggle-cell-tracking-competition),
Copyright (c) 2026, Thibaut Goldsborough. It is referenced as the `official/` git submodule and is not copied into
this repository. Its license is in `official/LICENSE`.

## Data and model weights (not redistributed)

- Competition data (CC0) is downloaded from Kaggle and is not included.
- Model weights and support packs are public Kaggle datasets that the notebooks reference by slug in
  `kernel-metadata.json` (for example the pilkwang `biohub-*` datasets). They are not stored in this repository;
  their licenses are those stated on their Kaggle pages.
