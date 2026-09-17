Issue17 authoring only, no tools. Return ONLY this one corrected test function, no extra tests. Earlier output invented WORKER_TAG, receipt.json, splits.json, predictor_0.txt and omitted cfg. These are wrong. Below is a nearly correct earlier output. ONLY fix tag parameter values from integers to strings and extend success to subset b with EXACT paths below. Do not rename ANY variables, keys or file paths.

@pytest.mark.parametrize("tag,expected_name", [(0, "e31_predict_0.py"), (1, "e31_predict_1.py")])
def test_worker_tag_selects_predictor_filename(tag, expected_name, runtime_env, monkeypatch):
    from biohub.public_postproc import pipeline

    def fake_run_postproc_core(geffs, out_csv, cfg, **kwargs):
        _write_csv(out_csv, "success", [p.stem for p in geffs])

    monkeypatch.setattr(pipeline, "run_postproc_core", fake_run_postproc_core)
    globals_dict = dict(runtime_env)
    globals_dict["E31_WORKER_TAG"] = tag
    code = compile(RUNTIME_SOURCE, "<e31_submission_runtime>", "exec")
    exec(code, globals_dict)

    assert (runtime_env["REPO_DIR"] / "scripts" / expected_name).exists()
    assert not (runtime_env["REPO_DIR"] / "scripts" / "e31_predict.py").exists()

Add b.zarr and c.zarr directories inside runtime_env['TEST_DIR']; existing a.zarr remains. globals_dict['E31_ASSIGNED_STEMS']=['b']. mock must assert [p.stem for p in geffs]==['b']. After exec verify json.load of WORKING_DIR/'e31_submission_receipt.json' field stems ['b'] and WORKING_DIR/'e31_splits.json' exact [{'split':0,'train':[],'test':['b']}]. These exact filenames are REQUIRED. No tmp_path fixture needed. Existing pytest/json imports and helper available.
