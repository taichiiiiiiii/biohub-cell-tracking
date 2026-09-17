# E26 accepted output-bounds notebook integration

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Direct user requested Qwen Cloud exact qwen3.8-max to advance project.
Existing Token Plan subscription only/effort none/no tools/retry/fallback.
Parent owns design/adoption/Kaggle. Do not run tools, claimtests, or accessfiles.
This new bounded integration task depends on an ALREADY ACCEPTED helper; do not
rewrite helper or tests already in canonical. Only writer integration and new
synthetic/static tests. One response cap600sec, at most1 evidence-driven feedback
within original totalwindow. No scientific knob/graph/weights/assets changes.

Fixed original notebook:
notebooks/e26_target_motion_off/e26_target_motion_off.ipynb
SHA256 a8d2b43e743eea8a99a128e4a2672f1ede8531dc162ebbb10dd957fc5fa7a052
33 cells. Only cell13 source may change. Parent keeps old directory immutable.
New destination: notebooks/e26_target_motion_off_bounds/e26_target_motion_off.ipynb
Accepted standalonehelper: src/biohub/output_bounds.py
SHA d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5.
No futureimport. Publicfunctions:
read_output_shape(TEST_DIR,dataset)->(T,Z,Y,X), validates Zarr3 actualmetadata.
new_output_bounds_report(dataset,shape)->mutable dict
bounded_output_node(node,dataset,row_id,shape,report)->complete10field CSVnode dict
including sentinels-1. Preserves caller dict. Round+clip at serializer; report capped20.
Do not cast/clip coordinates before callinghelper; its telemetry must see originalfloat.
RawGEFFint/floatcasts upstream remain exactlyunchanged.
Fullhelper NOT in prompt deliberately; insert exact placeholder once and parent
replaces it VERBATIM using frozen acceptedmodule; do not implement helper again.

DELIVER EXACTLY TWO labeled literalPython blocks with no extra text:
EDITS
```python
REPLACEMENTS = [
    ("exact old source anchor", "complete new source for this anchor"),
    ...
]
```
TESTS
```python
<complete tests/test_e26_bounds_notebook.py>
```
REPLACEMENTS is ONE assignment to a literal list of6 tuples ofstr; no execution,
imports, dynamic fstrings, functions, omittedstrings. Triplequotedliteralstrings
allowed. Eacholdanchor must appear exactlyonce in originalcell13 and be disjoint.
Newhelpermarker text __BIOHUB_OUTPUT_BOUNDS_HELPER__ appears exactlyonce in allnew.
This exact token spelling is mandatory: parent counts it once, substitutes only
that literal token with accepted helper bytes, then asserts zero tokens remain.
Parent ast.literal_eval only; eachanchorreplace once; JSONwrite via apply_patch.
Parent metadata copiesold exactly except id actual
taichiiiii/biohub-e26-motion-off-exploratory; code_file basename unchanged,
private=true,GPU T4,internet=false,competition+3dataset sources unchanged.
No README/AGENTS/official changes.

EXACT SIX modifications:
1. Insert helper text with marker at column0 after finalfunction return and
   before DEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector().
   Use existing two-line runtime anchor so no ambiguous earlier return.
2. Add ordered list output_bounds_reports adjacent stats_rows declaration.
3. Immediately after dataset = geff_path.stem load actualshape and freshreport;
   output_shape=read_output_shape(TEST_DIR,dataset),
   output_bounds_report=new_output_bounds_report(dataset,output_shape).
4. Replace ONLY node writer.writerow({...}) dict block with bounded_output_node
   call; retain exact sortednode loop, nodeassignment,row_id increment and edgewriter.
5. Append output_bounds_report once afternode loop before division_sources.
6. After stats.to_csv(RUN_STATS_PATH,index=False) write ordered JSON
   to SUBMISSION_PATH.with_name("output_bounds_report.json"), ensure_ascii=False,
   allow_nan=False, indent2,UTF8 newline. Keep all existingprints/checks/stats.
No explicitdatasetid/nodeid/imageshape in runtime; no fallback. JSONerror=>runinvalid.
No changing writeCSVtransport, edge logic, retainedgraph or unrelatednotebookcells.

TESTS:
Ruff config targetpy312,line120,E/W/F/I/UP/B. Normalcanonical biohub imports are
first-party separateblankafterpytest. Available numpy,pandas,pytest plusstdlib.
Root locate Path(__file__).resolve().parents[1].
Read pinned original and candidate notebooks; normalize source list/string.
- All33cells and entirejsonmetadata/top-level fields unchanged exceptcell13source.
  For cell13, helperexactsource embeddedonce; strip helper and reverse ONLY declared
  integration replacements to exactlyrestore frozenoriginalsource (or equivalent
  strict fullsource comparison, not only fieldname checks).
- Originalnb file SHA fixed; acceptedhelper SHA fixed? Prefer compare actual source
  string, guardstub placeholder absent, compile cell13 viaast.parse.
- Metadata candidate matches original dict EXCEPT actualid.
- Verify helperdefs precede runtime initialization, sortednode/edge code/config
  untouched using fullsourceparity, no hardcoded forbiddenactualbadnode.
- Tiny end-to-end execution of actual NEW writer TAIL ONLY (starting at geffs=sorted),
  with compiled acceptedhelper injected intoisolatednamespace and mockgraph/refine/
  filter/deepcenter, tmpmetadata using real helper; no models/GPU/fullimages/realGT.
  Stub graph_from_geff returns tiny testgraphs; fake graph exposes
  node_attrs().iter_rows(named=True) / edge_attrs().iter_rows(named=True).
  Create tmp dummyGEFFpaths under pattern predictions/*/METHOD/split_0/*.geff.
  Keep alpha.geff/beta.geff under the SAME dummy parent so sorting followsstems.
  Use dataset alpha,beta sortednames, deliberately unsortednodeidinput.
  Samplealpha node1,t0,y=sizeY (upperovershoot1),node2,t1 valid,edge1->2;
  beta onevalidnode. Use small noncubic TZYXshape so hardcoded256wouldfail.
  Stub refine returnsnodes, filter returnsnodes/edges plus {"raw_edges":len(edges)};
  keep namespace required TEST_DIR,REPO_DIR,METHOD,test_stems,CSV_COLUMNS,
  SUBMISSION_PATH,RUN_STATS_PATH,predict_seconds,EXPERIMENT_TAG,
  DEEPCENTER_VETO_DETECTOR, csv,pd,display.
  Mock graph/model functions are testfixtures only, not applicationedits.
  Assert fullCSV rows exact sortednodes thenedge, globalconsecutiveids/sentinels.
  Assert ordered reports alpha,beta; alphaexactnodecount2/corrected1/ycount1/max1,
  originalfloat=sizeY,rounded=sizeY,clipped=sizeY-1; beta zero/nontruncated.
  Test missingmetadata raises OutputBoundsError; outputs aren'tsubmissioneligible.
  Missingmetadata uses a fresh namespace/fresh tmp paths; error must propagate,
  with no successful output_bounds_report.json even if partialCSV wasopened.
  Keep tests modest and directly tied to changedpaths, no broad framework.
No actualKaggle/HTTP/modelcalls/filesoutside tmp.

SOURCE TAIL (source-cell line1610 through EOF):
```python
    print(f"  [{dataset}] after division-geometry-filter+prune-isolated: {len(nodes_by_id)} nodes, {len(edges)} edges")
    nodes_by_id, edges = filter_short_track_components(nodes_by_id, edges, stats)
    print(f"  [{dataset}] after short-track filtering: {len(nodes_by_id)} nodes, {len(edges)} edges"
          f" (components_removed={stats['short_track_components_removed']})")
    nodes_by_id = linefit_smooth_output_graph(nodes_by_id, edges, stats)
    print(f"  [{dataset}] FINAL: {len(nodes_by_id)} nodes, {len(edges)} edges")

    return nodes_by_id, edges, stats


DEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector()

geffs = sorted((REPO_DIR / "predictions").glob(f"*/{METHOD}/split_0/*.geff"))
print(f"Found {len(geffs)} prediction graphs")
if len(geffs) != len(test_stems):
    found = {path.stem for path in geffs}
    missing = sorted(set(test_stems) - found)
    raise RuntimeError(f"Expected {len(test_stems)} graphs, found {len(geffs)}. Missing: {missing[:10]}")

stats_rows: list[dict[str, object]] = []
seen_datasets: set[str] = set()
row_id = 0
total_nodes = 0
total_edges = 0

with SUBMISSION_PATH.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for geff_path in geffs:
        dataset = geff_path.stem
        seen_datasets.add(dataset)
        graph = graph_from_geff(geff_path)

        nodes_by_id: dict[int, dict[str, object]] = {}
        for row in graph.node_attrs().iter_rows(named=True):
            node_id = int(row["node_id"])
            nodes_by_id[node_id] = {
                "node_id": node_id,
                "t": int(row["t"]),
                "z": float(row["z"]),
                "y": float(row["y"]),
                "x": float(row["x"]),
            }

        raw_edges: list[dict[str, object]] = []
        for row in graph.edge_attrs().iter_rows(named=True):
            edge_prob = row.get("edge_prob") if hasattr(row, "get") else None
            raw_edges.append({
                "source_id": int(row["source_id"]),
                "target_id": int(row["target_id"]),
                "edge_prob": None if edge_prob is None else float(edge_prob),
            })

        raw_node_count = len(nodes_by_id)
        # НАША ФИЧА: уточняем центры всех клеток перед постобработкой
        nodes_by_id = refine_all_centroids(nodes_by_id, dataset)
        nodes_by_id, edges, filter_stats = filter_output_graph(nodes_by_id, raw_edges, dataset=dataset, deepcenter_bundle=DEEPCENTER_VETO_DETECTOR)
        if not nodes_by_id:
            raise AssertionError(f"{dataset}: post-processing removed every node")

        for node_id in sorted(nodes_by_id):
            node = nodes_by_id[node_id]
            writer.writerow({
                "id": row_id,
                "dataset": dataset,
                "row_type": "node",
                "node_id": int(node["node_id"]),
                "t": int(node["t"]),
                "z": max(0, int(round(float(node["z"])))),
                "y": max(0, int(round(float(node["y"])))),
                "x": max(0, int(round(float(node["x"])))),
                "source_id": -1,
                "target_id": -1,
            })
            row_id += 1

        division_sources: dict[int, int] = {}
        for edge in edges:
            source_id = int(edge["source_id"])
            target_id = int(edge["target_id"])
            if source_id not in nodes_by_id or target_id not in nodes_by_id:
                raise AssertionError(f"{dataset}: dangling edge after filtering")
            writer.writerow({
                "id": row_id,
                "dataset": dataset,
                "row_type": "edge",
                "node_id": -1,
                "t": -1,
                "z": -1,
                "y": -1,
                "x": -1,
                "source_id": source_id,
                "target_id": target_id,
            })
            row_id += 1
            division_sources[source_id] = division_sources.get(source_id, 0) + 1

        node_count = len(nodes_by_id)
        edge_count = len(edges)
        total_nodes += node_count
        total_edges += edge_count
        stats_rows.append({
            "dataset": dataset,
            "raw_nodes": raw_node_count,
            "nodes": node_count,
            "raw_edges": filter_stats["raw_edges"],
            "edges": edge_count,
            "division_like_sources": sum(1 for count in division_sources.values() if count >= 2),
            "edge_to_node_ratio": edge_count / max(node_count, 1),
            "gap_added_nodes_frac": filter_stats.get("gap_added_nodes", 0) / max(raw_node_count, 1),
            **filter_stats,
        })

expected_datasets = set(test_stems)
missing_datasets = sorted(expected_datasets - seen_datasets)
extra_datasets = sorted(seen_datasets - expected_datasets)
if missing_datasets or extra_datasets:
    raise AssertionError({"missing": missing_datasets[:10], "extra": extra_datasets[:10]})
assert row_id == total_nodes + total_edges, "Internal row counter mismatch"
assert total_nodes > 0, "No node rows produced"

header = SUBMISSION_PATH.open().readline().strip().split(",")
assert header == CSV_COLUMNS, f"Bad CSV header: {header}"

stats = pd.DataFrame(stats_rows).sort_values("dataset").reset_index(drop=True)
stats["predict_minutes_total"] = predict_seconds / 60.0
stats["experiment_tag"] = EXPERIMENT_TAG
stats.to_csv(RUN_STATS_PATH, index=False)

print(f"Wrote {SUBMISSION_PATH} with {row_id:,} rows")
print(f"Node rows: {total_nodes:,} | edge rows: {total_edges:,}")
print(f"Wrote {RUN_STATS_PATH}")
display(pd.read_csv(SUBMISSION_PATH, nrows=8))
```
