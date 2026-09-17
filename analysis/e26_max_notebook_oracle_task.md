# E26 notebook oracle-only closure unit

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Latest direct user request selects exact qwen3.8-max and project progress.
Existing subscription-only TokenPlan/none/no tools. One response cap300seconds,
no feedback, no retry/fallback. This is a NEW isolated TEST-ONLY unit in same
directly supervised coding turn; priorintegrationauthorunit isclosedHOLDtests.
DO NOT change notebook/application/helper/runtime/constants/otherfunctions.
No science/metadata routing/token changes. Parent retains all files/logs.

Parent measured application tinywriter succeeds,7testsPASS/3FAIL; RuffPASS
after mechanical literalstring linewrapping withASTvalueequality. Four target
testdefs only; source testmoduleSHA f390964e3bdf3cb98aa4782c642a31a22627d93b24c5be7e5c6eca00c5b13c21.

DELIVER EXACTLY ONE literalPython block, no text/labels:
```python
<the FOUR complete def declarations below, in same order, no otherdefs/imports>
```
Parent mechanically replaces only these4 ASTfunctionspans and verifies allother
bytesunchanged. No rewritewholemodule. Existing imports/constants/helpers:
ast,copy,hashlib,json,Path,pd,pytest.
ORIGINAL_NB,CANDIDATE_NB,ACCEPTED_HELPER paths,HELPER_SHA,MARKER,RUN_TOKEN.
REPLACEMENTS exact6literal pairs (alreadycorrect andformatted; do NOT redefine).
_load_nb(path),_cell_source(cell),_sha256(path),
_extract_tail(source) returnsactualtailstartinggeffs=sorted.
_build_namespace(tmp_path,helper_src,omit_alpha_root=False) compileshelper_src
into ONE dict and supplies tinyalpha/beta fixtures+namespace. Its
ns["OutputBoundsError"] is the exceptionclass of THE SAME execnamespace.
It also supplies testRUN_TOKEN; overwrite it with candidate's parsed literal
OUTPUT_BOUNDS_RUN_TOKEN assignment before actualtail execution.
No need to recreatefixture, noimportedmoduleclass/no secondexecnamespace.

Corrections:
1. structure+metadata:
   clonecandidateJSON, restore ONLYcell13["source"] fromoriginal, thenassert
   entireclonedcandidate==original (allmetadata,cellfields,outputs,ordering).
   Assert both33cells. Separatekernel-metadata.json comparewholeobjects after
   verifyingcandidate id==actualslug and replacingonlycandidateid withoriginalid.
   No popignore ofnotebookmetadata keys.
2. exactsourceparity:
   applyeach REPLACEMENTS oldanchoronce to originalsource withuniqueassert.
   markeronce. Substitutehelper source EXACTLY including trailingnewline:
   do NOT .rstrip/.dedent/.strip. Assertactualcandidate==expected.
3. E2E:
   canonicalhelperstring isalreadyembeddedwithnewline. Assertcandidate contains
   itexactlyonce thenSLICE the actualembeddedbytesfromcandidate andpassslice to
   _build_namespace. Parse asttree ofcandidate tofindexactone plainassignment
   OUTPUT_BOUNDS_RUN_TOKEN, ast.literal_evalvalue, equalsRUN_TOKEN; assignnsvalue.
   Do not executefullcell13/modelimports. Execute actualtail in ns.
   FullCSV must EXACTLY these4rows in order (list dicts isfine):
   columns id,dataset,row_type,node_id,t,z,y,x,source_id,target_id.
   row0 alpha,node,node_id1,t0,z0,y5,x1,source-1,target-1.
   row1 alpha,node,node_id2,t1,z0,y2,x2,source-1,target-1.
   row2 alpha,edge,node_id-1,t-1,z-1,y-1,x-1,source1,target2.
   row3 beta,node,node_id5,t0,z0,y1,x1,source-1,target-1.
   Why sample.row_id MUST0 not1: sortednodeid1 is FIRST row, CSVid starts0.
   Retain all currentreport/provenancehash/token/log assertions below.
   Verify fullfield rows BEFORE report, no merelysortednodeidassert.
4. Missingmetadata:
   actualembeddedhelperbytes+parsedtoken samepattern asE2E, freshns/tmp.
   _build_namespace(...omit_alpha_root=True).
   pytest.raises(ns["OutputBoundsError"]) (NOT secondhelper_ns class).
   Actualtail mustraise; both report/provenancepathsabsent.
   No recursive removal of files.

Python3.12/Ruffline120/EWF IUPB. AlltestlogicQwen-authored. No testsclaimedrun.
Current targetdefs:
```python
def test_candidate_notebook_structure_and_metadata():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)

    assert len(cand["cells"]) == 33
    assert len(orig["cells"]) == 33

    orig_meta = copy.deepcopy(orig["metadata"])
    cand_meta = copy.deepcopy(cand["metadata"])
    orig_meta.pop("id", None)
    cand_meta.pop("id", None)
    assert cand_meta == orig_meta

    kernel_orig = json.loads(
        (ORIGINAL_NB.parent / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    kernel_cand = json.loads(
        (CANDIDATE_NB.parent / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    assert kernel_cand["id"] == "taichiiiii/biohub-e26-motion-off-exploratory"
    kernel_orig_copy = copy.deepcopy(kernel_orig)
    kernel_cand_copy = copy.deepcopy(kernel_cand)
    kernel_orig_copy.pop("id", None)
    kernel_cand_copy.pop("id", None)
    assert kernel_orig_copy == kernel_cand_copy

    for idx, (o, c) in enumerate(zip(orig["cells"], cand["cells"], strict=True)):
        if idx == 13:
            continue
        assert _cell_source(o) == _cell_source(c), f"cell {idx} source changed"
        assert o.get("cell_type") == c.get("cell_type")
        assert o.get("metadata") == c.get("metadata")


def test_cell13_matches_declared_replacements_byte_for_byte():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)
    original_source = _cell_source(orig["cells"][13])
    candidate_source = _cell_source(cand["cells"][13])

    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    expected = original_source
    for old, new in REPLACEMENTS:
        assert expected.count(old) == 1, f"anchor not unique: {old!r}"
        expected = expected.replace(old, new)
    expected = expected.replace(MARKER, helper_src.rstrip("\n"))

    assert candidate_source == expected


def test_end_to_end_writer_tail_with_bounds(tmp_path, capsys):
    cand = _load_nb(CANDIDATE_NB)
    candidate_source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    tail = _extract_tail(candidate_source)

    token_assignment = "OUTPUT_BOUNDS_RUN_TOKEN = \"e26-bounds-a8d2b43e-d39549fb-20260907\""
    assert token_assignment in candidate_source

    ns = _build_namespace(tmp_path, helper_src)
    exec(compile(tail, "<tail>", "exec"), ns)

    submission_path = tmp_path / "submission.csv"
    df = pd.read_csv(submission_path)
    rows = list(df.itertuples(index=False))
    assert [r.row_type for r in rows] == ["node", "node", "edge", "node"]
    ids = [r.id for r in rows]
    assert ids == list(range(len(ids)))

    alpha_nodes = [
        r for r in rows if r.dataset == "alpha" and r.row_type == "node"
    ]
    assert len(alpha_nodes) == 2
    alpha_node_ids = sorted(r.node_id for r in alpha_nodes)
    assert alpha_node_ids == [1, 2]
    overshoot = next(r for r in alpha_nodes if r.node_id == 1)
    assert overshoot.y == 5

    edge_rows = [r for r in rows if r.row_type == "edge"]
    assert len(edge_rows) == 1
    edge = edge_rows[0]
    assert edge.source_id == 1
    assert edge.target_id == 2
    assert edge.node_id == -1
    assert edge.t == -1
    assert edge.z == -1
    assert edge.y == -1
    assert edge.x == -1

    report_path = submission_path.with_name("output_bounds_report.json")
    reports = json.loads(report_path.read_text(encoding="utf-8"))
    assert [r["dataset"] for r in reports] == ["alpha", "beta"]

    alpha_report = reports[0]
    assert alpha_report["shape"] == [3, 4, 6, 8]
    assert alpha_report["node_count"] == 2
    assert alpha_report["corrected_nodes"] == 1
    assert alpha_report["axis_counts"] == {"z": 0, "y": 1, "x": 0}
    assert alpha_report["max_absolute_correction"] == 1
    assert alpha_report["sample_limit"] == 20
    assert alpha_report["samples_truncated"] is False
    samples = alpha_report["samples"]
    assert len(samples) == 1
    sample = samples[0]
    assert sample["dataset"] == "alpha"
    assert sample["row_id"] == 1
    assert sample["node_id"] == 1
    assert sample["t"] == 0
    assert sample["axis"] == "y"
    assert sample["original_float"] == 6.0
    assert sample["rounded_int"] == 6
    assert sample["clipped_int"] == 5
    assert sample["signed_delta"] == -1
    assert sample["absolute_delta"] == 1

    beta_report = reports[1]
    assert beta_report["node_count"] == 1
    assert beta_report["corrected_nodes"] == 0
    assert beta_report["axis_counts"] == {"z": 0, "y": 0, "x": 0}
    assert beta_report["max_absolute_correction"] == 0
    assert beta_report["samples"] == []
    assert beta_report["samples_truncated"] is False

    prov_path = submission_path.with_name("output_bounds_provenance.json")
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["schema_version"] == 1
    assert prov["run_token"] == RUN_TOKEN
    assert prov["helper_sha256"] == HELPER_SHA
    expected_sub_hash = hashlib.sha256(submission_path.read_bytes()).hexdigest()
    expected_rep_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert prov["submission_sha256"] == expected_sub_hash
    assert prov["output_bounds_report_sha256"] == expected_rep_hash

    captured = capsys.readouterr().out
    assert f"E26_BOUNDS_RUN_TOKEN={RUN_TOKEN}" in captured
    assert f"E26_BOUNDS_SUBMISSION_SHA256={expected_sub_hash}" in captured


def test_missing_metadata_raises_output_bounds_error(tmp_path):
    cand = _load_nb(CANDIDATE_NB)
    candidate_source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    tail = _extract_tail(candidate_source)

    ns = _build_namespace(tmp_path, helper_src, omit_alpha_root=True)
    helper_ns: dict[str, object] = {}
    exec(compile(helper_src, "<helper>", "exec"), helper_ns)
    OutputBoundsError = helper_ns["OutputBoundsError"]

    with pytest.raises(OutputBoundsError):
        exec(compile(tail, "<tail>", "exec"), ns)

    report_path = (tmp_path / "submission.csv").with_name("output_bounds_report.json")
    prov_path = (tmp_path / "submission.csv").with_name("output_bounds_provenance.json")
    assert not report_path.exists()
    assert not prov_path.exists()
```
