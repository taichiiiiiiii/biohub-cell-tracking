Issue17 QwenCloud Max authoring-only no tools. E31 Kagglev1 ERROR after full4predictions. Strict DeepCenter manifesthash old100epoch metadata differs current500epoch metadata. Current manifest actualhash3bfe97304e9bbc3b3481a095392a1e83937315325bac8b987eb527d2951b96f3. Actual best.pt SHA8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0 unchanged, best summary/config/coordinatecontract unchanged. Only lastcheckpoint/history/name metadata differ. DO NOT loosen existingloader or change shared constants. Return ONE minimal unified diff:
1 src/biohub/public_postproc/deepcenter.py add def load_deepcenter_veto_detector_e31_target(cfg:PostprocConfig,checkpoint_path:Path,manifest_path:Path)->tuple[dict[str,object],dict[str,object]] immediately before _dc_pool_frame_xy. Copy existing strictwrapper implementation but expected_manifest_sha256 literal newhash only, all remaining expectedconstants same. Docstring explicitly E31 target ep500 package unchanged bestepoch2; neverfallback. Existing strict untouched.
2 scripts/e31_submission_runtime.py replace import from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict with 'from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_e31_target as load_deepcenter_veto_detector_strict' preserving local call andrest.
3 tests/test_e31_submission_runtime.py change monkeypatch name string only line250 from load_deepcenter_veto_detector_strict to load_deepcenter_veto_detector_e31_target. Add one pure wrapper unit test monkeypatch dc_mod._load_deepcenter_veto_detector_strict_verified fake callable captures positional and kwargs, returns sentinel tuple; call new wrapper(cfgobject,Path('best.pt'),Path('manifest.json')); assert return identical tuple, args sameobjects, expected_manifest_sha256 newliteral, expected_checkpoint_sha256 equals literal8040999..., expected_epoch2, other two modelconfig kwargs identical constants, old STRICT_DEEPCENTER_MANIFEST_SHA256 still1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911. NoGPU.
All contexts needed:
def load_deepcenter_veto_detector_strict(
    cfg: PostprocConfig,
    checkpoint_path: Path,
    manifest_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    """Load only the exact preregistered DeepCenter artifact, without fallback."""
    return _load_deepcenter_veto_detector_strict_verified(
        cfg,
        checkpoint_path,
        manifest_path,
        expected_checkpoint_sha256=STRICT_DEEPCENTER_CHECKPOINT_SHA256,
        expected_manifest_sha256=STRICT_DEEPCENTER_MANIFEST_SHA256,
        expected_epoch=STRICT_DEEPCENTER_EPOCH,
        expected_manifest_model_config=STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG,
        expected_checkpoint_model_config=STRICT_DEEPCENTER_CHECKPOINT_MODEL_CONFIG,
    )


def _dc_pool_frame_xy(volume: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return volume.astype(np.float32, copy=False)
    z, y, x = volume.shape
    y2 = (y // factor) * factor
250:    monkeypatch.setattr(dc_mod, "load_deepcenter_veto_detector_strict", lambda cfg, ckpt, mf: ({}, {"stub": True}))
model_keys ['architecture', 'best_checkpoint', 'best_checkpoint_summary', 'config', 'last_checkpoint', 'last_checkpoint_summary', 'method', 'role']
best {'bytes': 37876911, 'path': 'weights/full_frame_center/best.pt', 'sha256': '8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0'}

Test imports already Path,pytest,from biohub.public_postproc import deepcenter as dc_mod inside fixture. Test appended new independenttest with functionlocal import. Return minimaldiff no testclaims.
