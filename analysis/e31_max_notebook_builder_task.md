Issue16/17 active Goal QwenCloud Max authoring ONLY no tools. Return ONE fenced python complete scripts/prepare_e31_submission.py, <=220 lines. Build-only function build(repo:Path)->dict {'notebook':...,'metadata':...,'receipt':...}; no executing inference or writing files during build. stdlib only imports. __main__ print JSON build(Path(__file__).resolve().parents[1]). Parent will serialize returned notebook via apply_patch.
Use baseline notebooks/pub923_repro/pub923_repro.ipynb SHA256 08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1 mandatory. Copy code cells3,5,7,9 unchanged and cell11 prefix BEFORE exact 'def list_test_stems() -> list[str]:' (unique anchor). Do NOT copy rest cells especially13/17/19. No GT or frozen dataset names. Markdown acknowledge pilkwang CC0 packs and exploratory not privategainproof. Notebook code cells parsed ast at build, no outputs.
Embed files read from repo current: src/biohub/__init__.py,io.py,appearance_cost.py,consensus_edges.py,primary_consensus_observer.py,association_instrumentation.py,output_bounds.py,screen_output_bounds.py and public_postproc/__init__.py,config.py,csv_out.py,deepcenter.py,divisions.py,frames.py,geometry.py,graph_ops.py,pipeline.py. Put embedded content literal dict into appended setup cell which creates fresh WORKING_DIR/e31_payload via exclusive creation eachfile, sys.path.insert(0,payload/src). No other imports from biohub missingfiles; record each embedded sha in receipt. Existing setup provides WORKING_DIR,REPO_DIR,TEST_DIR,sys,os,json,_ps (reconstructed source Path),_primary_materialized_path,_deepcenter_materialized_path,SECONDARY_WEIGHTS_PATH. Need inspect via source anchors not hardcode trainids.
Appended execution code: discover sorted p.stem TEST_DIR.glob('*.zarr') nonempty, no .geff testinputs. Assert os.environ BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT==0.30, BIOHUB_SECONDARY_WEIGHTS points to existing SECONDARY_WEIGHTS_PATH, secondaryedgeweight0.15. Existing E23 prediction load_model fails if weights can't load; observer mandatorysecondaryhooks ensures no missingsecondarysilent. instrument_source(_ps.read_text()) uses pinned SOURCE_SHA256 automatic. Save patched text to fresh REPO_DIR/scripts/e31_predict.py exclusive. Set dataspec.PREDICTIONS_PATH = WORKING_DIR/'e31_predictions' fresh nonexistent root; original predict creates it. Import instrumented source using spec_from_file_location and sys.modules before exec_module. predictions return value not assumed; enumerate newroot.rglob('*.geff') verify exactstems. Write splits fresh WORKING_DIR/e31_splits.json with [{"split":0,"train":[],"test":stems}].
Call module.predict(data_dir=TEST_DIR,fold=0,splits_file=splits,weights_path=_primary_materialized_path,cfg=module.PredictConfig(det_threshold=0.96875,use_ilp=True,ilp_edge_weight=-1.0,ilp_appearance_weight=0.0,ilp_disappearance_weight=1.5,ilp_division_weight=1.0),method="unet_transformer",unet_batch_size=4,evaluate=False,association_observer=observer). Keep os.chdir(REPO_DIR) before module execution/predict; ensure REPO_DIR sys.path for dataspec.
Postprocessing: build_config(overrides four BIOHUB_DEEPCENTER_CHECKPOINT/CHECKPOINT_DEFAULT path _deepcenter_materialized_path and MANIFEST/MANIFEST_DEFAULT path _deepcenter_materialized_path.parents[2]/ARTIFACT_MANIFEST.json, test_dir=TEST_DIR,profile="e23"). Assert manifest exists; cfg.OUTPUT_MOTION_RELINK true. Only consensus_loader observer.frames_for; no other new hypothesis args. ScreenNodeSerializer shapes read_output_shape(TEST_DIR,name). run_postproc_core(geffs,WORKING_DIR/'submission.csv',cfg,run_stats_path=WORKING_DIR/'run_stats.json',predict_seconds=elapsed,node_serializer=serializer,consensus_loader=observer.frames_for,exclusive_output=True). Dump bounds receipt freshjson. Include full CSV validation using stdlib csv: exact columns ['id','dataset','row_type','node_id','t','z','y','x','source_id','target_id'] (verify actual below if mismatch), node ids unique per dataset, t/z/y/x ints finite nonnegative bounds, edge endpoints existing and t+1, no duplicateedges, every test dataset appears, nonempty nodes; validation only label-free no pandas/GT. Write receipt SHA csv, datasets, source instrumentation, payloadhashes only after validation.
metadata copied E23 updated id='taichiiiii/biohub-e31-primary-consensus-exploratory',title='Biohub E31 Primary Consensus Exploratory',code_file='e31_submission.ipynb', is_private='true',enable_gpu='true',enable_internet='false',machine_shape NvidiaTeslaT4; other competition/dataset sources unchanged.
No physicalexecution/testclaims. Scope build only, no Kaggle API/submission. acceptance source immutable, helper uses fullmatrixbefore subset, source failclosed/no invented APIs. Existing excerpts:
def run_postproc_core(
    geff_paths: Sequence[Path],
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
    *,
    deepcenter_loader: DeepCenterLoader | None = None,
    dataset_start_hook: DatasetHook | None = None,
    dataset_finish_hook: DatasetHook | None = None,
    twin_plan_hook: TwinPlanHook | None = None,
    raw_stats_hook: RawStatsHook | None = None,
    write_run_stats_output: bool = True,
    exclusive_output: bool = False,
    node_serializer: NodeSerializer | None = None,
    association_priors_by_dataset: dict[str, dict[tuple[int, int], float]] | None = None,
    appearance_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, dict]]
    | None = None,
    consensus_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    consensus_soft_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    short_track_consensus_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    bidirectional_motion_consistency: bool = False,
) -> dict[str, object]:
    """Run the full stack over an explicit GEFF sequence without reordering it.

    This is the sole full-run dataset loop.  The legacy entry point supplies a
    sorted discovery result; the ST-R3 adapter supplies its frozen literal
    order and production hooks. An optional serializer changes only the node
    CSV boundary; the default retains the legacy byte representation.

    ``association_priors_by_dataset`` is opt-in.  ``None`` (default) keeps the
    legacy behaviour exactly.  When supplied it must be an outer ``dict`` whose
    keys are exactly the unique GEFF stems; every inner mapping is validated up
    front with ``_unselected_association_priors`` and snapshotted so that later
    hook activity cannot alter what a downstream dataset consumes.
    """
    geffs = tuple(geff_paths)
    if not geffs:
        raise RuntimeError("no GEFF paths supplied")
    if any(type(path) is not type(Path()) for path in geffs):
        raise TypeError("GEFF paths must be exact pathlib.Path instances")

    if appearance_loader is not None:
        # Opt-in per-dataset appearance features; validated up front so no
        # video is ever half-featured.  No global default config is implied.
        if not callable(appearance_loader):
            raise ValueError("appearance_loader must be callable")
        if not cfg.OUTPUT_MOTION_RELINK:
            raise ValueError("appearance_loader requires OUTPUT_MOTION_RELINK")
        if association_priors_by_dataset is not None:
            raise ValueError("appearance_loader cannot be combined with association_priors_by_dataset")
        stems = tuple(path.stem for path in geffs)
        if len(set(stems)) != len(stems):
            raise ValueError("GEFF dataset stems must be unique when an appearance loader is supplied")
    for loader_name, consensus_callback in (
        ("consensus_loader", consensus_loader),
def build_config(
    overrides: dict[str, str] | None = None,
    test_dir: Path | str = Path("data/test"),
    profile: str = "base1",
) -> PostprocConfig:
    """Build a :class:`PostprocConfig` the same way the notebook builds its constants.

    Resolution order (last wins), mirroring "preset cell overwrites
    os.environ, constants cell reads os.environ.get(name, hardcoded)":
    ``CODE_DEFAULTS`` -> the named profile's preset (:data:`PROFILES`;
    ``base1`` is :data:`PRESET`, ``e23`` is :data:`E23_PRESET`) ->
    ``overrides`` (``--set``). Positional arguments are unchanged, so
    existing callers keep building the byte-for-byte ``base1`` config.

    Raises :class:`ValueError` for an unknown ``profile`` or an invalid
    ``BIOHUB_SAFE_DIV_MODE`` override, and :class:`KeyError` for unknown
    override keys.
    """
    try:
        preset = PROFILES[profile]
    except KeyError:
        raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(PROFILES)}") from None

    env: dict[str, str] = dict(CODE_DEFAULTS)
    env.update(preset)
    if overrides:
        unknown = sorted(set(overrides) - set(CODE_DEFAULTS))
        if unknown:
            raise KeyError(f"unknown BIOHUB_* override key(s): {unknown}")
        env.update(overrides)

    safe_div_mode = _get_str(env, "BIOHUB_SAFE_DIV_MODE")
    if safe_div_mode not in ("legacy", "e23"):
        raise ValueError(f"BIOHUB_SAFE_DIV_MODE must be 'legacy' or 'e23', got {safe_div_mode!r}")

    output_steal_twin_rewire = _get_bool(env, "BIOHUB_OUTPUT_STEAL_TWIN_REWIRE")
    steal_twin_values: dict[str, object] = {
        "STEAL_TWIN_MODE": _get_str(env, "BIOHUB_STEAL_TWIN_MODE"),
        "STEAL_TWIN_PARENT_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_PARENT_MAX_UM"),
        "STEAL_TWIN_EXISTING_CHILD_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM"),
        "STEAL_TWIN_SISTER_MIN_UM": _get_float(env, "BIOHUB_STEAL_TWIN_SISTER_MIN_UM"),
        "STEAL_TWIN_SISTER_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_SISTER_MAX_UM"),
        "STEAL_TWIN_DIVERGE_UM": _get_float(env, "BIOHUB_STEAL_TWIN_DIVERGE_UM"),
        "STEAL_TWIN_TWIN_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_TWIN_MAX_UM"),
        "STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": _get_bool(env, "BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS"),
        "STEAL_TWIN_REJECT_SYNTHETIC": _get_bool(env, "BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC"),
        "STEAL_TWIN_DEEPCENTER_VETO": _get_bool(env, "BIOHUB_STEAL_TWIN_DEEPCENTER_VETO"),
        "STEAL_TWIN_FRAME_CAP_ABS": _get_int(env, "BIOHUB_STEAL_TWIN_FRAME_CAP_ABS"),
        "STEAL_TWIN_VIDEO_CAP_ABS": _get_int(env, "BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS"),
        "STEAL_TWIN_DEBUG_MAX_RECORDS": _get_int(env, "BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS"),
    }
    frozen_steal_twin_values: dict[str, object] = {
        "STEAL_TWIN_MODE": "twin_only_v1",
def read_output_shape(
    test_dir: str | Path, dataset: str
) -> tuple[int, int, int, int]:
    """Return ``(T, Z, Y, X)`` for ``dataset`` from Zarr format-3 metadata.

    Reads ``<dataset>.zarr/zarr.json`` and ``<dataset>.zarr/0/zarr.json``. No
    shape fallback and no image-array reads are performed. Exactly one
    reference to the literal path ``"0"`` is required across *all* multiscales
    entries, counted before any axis filtering. Every multiscales entry must
    declare a non-empty axes list; only the selected path-0 entry is required
    to match the normalized T,Z,Y,X ordering.
    """
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    root = Path(test_dir) / f"{dataset}.zarr"

    try:
        group_meta = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
        array_meta = json.loads(
            (root / "0" / "zarr.json").read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise OutputBoundsError(
            f"missing zarr metadata for {dataset}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OutputBoundsError(
            f"malformed zarr metadata for {dataset}: {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise OutputBoundsError(
            f"malformed zarr metadata encoding for {dataset}: {exc}"
        ) from exc

    if not isinstance(group_meta, dict) or not isinstance(array_meta, dict):
        raise OutputBoundsError("zarr metadata must be JSON objects")

    group_version = group_meta.get("zarr_format")
    array_version = array_meta.get("zarr_format")
    if not _is_python_int(group_version) or group_version != 3:
        raise OutputBoundsError("only zarr format 3 metadata is supported")
    if not _is_python_int(array_version) or array_version != 3:
53:    "BIOHUB_OUTPUT_MOTION_RELINK": "1",
54:    "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
55:    "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
56:    "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT": "0.5",
57:    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "0.75",
58:    "BIOHUB_MOTION_RELINK_MAX_FRAME_NODES": "2600",
121:    "BIOHUB_DEEPCENTER_MANIFEST": "",
122:    "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": (
167:    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "1.0",
168:    "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
169:    "BIOHUB_MOTION_RELINK_RELAXED_UM": "9.5",
215:    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "1.0",
323:    OUTPUT_MOTION_RELINK: bool
324:    MOTION_RELINK_TIGHT_UM: float
325:    MOTION_RELINK_RELAXED_UM: float
326:    MOTION_RELINK_VELOCITY_WEIGHT: float
327:    MOTION_RELINK_LEARNED_BONUS: float
328:    MOTION_RELINK_MAX_FRAME_NODES: int
432:    DEEPCENTER_MANIFEST: str
433:    DEEPCENTER_MANIFEST_DEFAULT: str
517:        OUTPUT_MOTION_RELINK=_get_bool(env, "BIOHUB_OUTPUT_MOTION_RELINK"),
518:        MOTION_RELINK_TIGHT_UM=_get_float(env, "BIOHUB_MOTION_RELINK_TIGHT_UM"),
519:        MOTION_RELINK_RELAXED_UM=_get_float(env, "BIOHUB_MOTION_RELINK_RELAXED_UM"),
520:        MOTION_RELINK_VELOCITY_WEIGHT=_get_float(env, "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT"),
521:        MOTION_RELINK_LEARNED_BONUS=_get_float(env, "BIOHUB_MOTION_RELINK_LEARNED_BONUS"),
522:        MOTION_RELINK_MAX_FRAME_NODES=_get_int(env, "BIOHUB_MOTION_RELINK_MAX_FRAME_NODES"),
609:        DEEPCENTER_MANIFEST=_get_str(env, "BIOHUB_DEEPCENTER_MANIFEST"),
610:        DEEPCENTER_MANIFEST_DEFAULT=_get_str(env, "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT"),

