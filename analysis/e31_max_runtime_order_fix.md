Issue17 Max authoring only no tools. Return minimal patch ONLY scripts/e31_submission_runtime.py three additions. Previous patch applied except unsafe bundle-before-cfg and edge-endpoint -1 assertions rejected.
A after exact line 'assert len(stems) == len(set(stems))' add assert not list(TEST_DIR.glob("*.geff")).
B AFTER exact 'assert cfg.OUTPUT_MOTION_RELINK and cfg.USE_DEEPCENTER_VETO and cfg.REQUIRE_DEEPCENTER_VETO' add bundle, deepcenter_receipt = load_deepcenter_veto_detector_strict(cfg, _deepcenter_materialized_path, manifest). MUST AFTER cfg = build_config, never before. Existing run_postproc_core lambda config:bundle and final receipt variable already added.
C AFTER exact '            assert nid not in node_times.get(ds, {})' add node-only assertions int(row["source_id"]) == -1 and int(row["target_id"]) == -1. Never add in elif rt=="edge" (edges require real endpoints >=0).
Only 3 hunks. Current anchors exact.
