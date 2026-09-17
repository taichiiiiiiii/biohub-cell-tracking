# E26 integration — ONE evidence-driven feedback within original window

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Exact Qwen Cloud qwen3.8-max/Token Plan/none, no tools/retries/fallback.
Original integration deadline remains2026-09-07 04:17:57.394095 UTC.
Parent applied your6literal replacements to frozenoriginalcell13, substituted
__BIOHUB_OUTPUT_BOUNDS_HELPER__ with acceptedhelper ENTIRE literal source,
and createdprovisionalcandidate. All6anchorsunique, helperverbatim and ASTPASS.
No Kagglepush yet. Parent measured5PASS/5FAIL plus5Ruff issues inyourtests.

There is ALSO a newly independently reviewed operational-provenance requirement:
Kaggle exact-version output canreturn404; latest-output API hasNOversion/sessionID.
Beforephysicalrun add v2-only token+artifact containing CSV/report hashes so
latestoutput cannot silently be mistaken foroldv1. This changes telemetry only.
Parent approved this design BEFOREimplementation. Keep allscience/outputCSVfixed.

DELIVER same TWO blocks, COMPLETE corrected EDITS and TESTS:
EDITS: ONE literal assignment REPLACEMENTS=[6(old,new) strtuples].
TESTS: whole tests/test_e26_bounds_notebook.py, no nonexistent imports.
Use SAME6oldanchors/current2–5new strings. ONLY1st/6thnewstrings may expand for
provenance. Preserve helper marker exactonce; parent embeds helper beforetests.
No otherapplication sourcechanges. No test weakening to forcegreen.

PROVENANCE ADDITIONS:
- After embedded helper, before DEEPCENTER runtimeinit, defineconstant
  OUTPUT_BOUNDS_RUN_TOKEN = "e26-bounds-a8d2b43e-d39549fb-20260907"
  and print("E26_BOUNDS_RUN_TOKEN=" + OUTPUT_BOUNDS_RUN_TOKEN).
- Sixthreplacement after run_stats+strictoutput_bounds_report.json:
  import hashlib as output_bounds_hashlib (only newimport, no otherhelperchange).
  Compute SHA256 of actualwritten submission.csv bytes and actualwritten
  output_bounds_report.json bytes. These are smallCSV/JSON artifacts, notimages.
  Write output_bounds_provenance.json in samefolder with exact fields:
  schema_version builtinint1
  run_token exactconstantabove
  helper_sha256 "d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5"
  submission_sha256 actualhash
  output_bounds_report_sha256 actualhash
  Use strictjson(allow_nan=False,ensure_ascii=False,indent2,UTF8).
  Print same token and CSVhash afterartifact successfullywritten.
- Anymetadata/error must propagate; no fakeeligible/successflag onfailure.
- Neverinsert actualbaddataset/node IDs orshapeconstantsinto runtime.
These token/hashbytes areprovenance ONLY; no sciencecondition dependsonthem.

FIX TESTS FROM MEASUREDFAILURES/REVIEW:
1. Kernel id lives in SEPARATE kernel-metadata.json, NOT notebook["metadata"].
   Candidate ipynb top-level+all33cells exactold JSON exceptcell13source.
   Compare full deepcopy after restoring ONLYcell13source, no partialkeylist.
   Separate kernel metadata diff must ONLYidactualslug (code_fileunchanged).
2. Parent already embedded helper. Assert MARKER NOT in candidate,
   candidate.count(helper_src)==1, compile actualcandidatecell13 asis.
   Do NOT replaceplaceholder duringtest because it isabsent.
3. No tests.test_e26_bounds_notebook_helpers module exists. Define your6
   literal REPLACEMENTS inthissame standalonetest module. Form expectedsource
   by exactunique originalanchor replacements and literalhelper substitution.
   Compare entireexpectedsource==actualsource byteforbyte, no dedent/rstrip
   normalization masking whitespacechanges. Includeprovenance additions.
4. Actualmetadata path:
   <TEST_DIR>/<dataset>.zarr/zarr.json is JSON root:
   zarr_format3,node_type"group",attributes.multiscales with
   axes [{"name":"t"},{"name":"z"},{"name":"y"},{"name":"x"}],
   datasets [{"path":"0"}].
   <TEST_DIR>/<dataset>.zarr/0/zarr.json:
   zarr_format3,node_type"array",shape[...].
   Your test wrote unrelated dataset/segmentation.zarr; fixactualstrictschema.
5. Accepted reportactualfields (do notinvent):
   dataset,shape,node_count,corrected_nodes,axis_counts{"z","y","x"},
   max_absolute_correction,samples,sample_limit20,samples_truncatedbool.
   Samplefields: dataset,row_id,node_id,t,axis,original_float,rounded_int,
   clipped_int,signed_delta,absolute_delta.
   Assert alpha C1,counts z0/y1/x0,max1, oneaxisysample float6/int6/clipped5/delta-1;
   beta C0/zeroaxes/max0/nosamples/nottruncated.
6. exec(acceptedhelper) creates a DISTINCT OutputBoundsErrorclass from imported
   module. Catch ns["OutputBoundsError"], NOT importedclass.
7. Execute ACTUALembeddedhelpertext extracted fromcandidate and actualwriter
   tailfromunique geffs = sorted anchor in SAME freshnamespace.
   Namespace must also receiveOUTPUT_BOUNDS_RUN_TOKEN for tail-only harness
   (derive from parsed literalcandidateassignment, not uncheckedtestconstant).
   Do NOT execute fullcell13 imports/modelsetup.
   Helperdef position verified viaactualsourceindex notmissingmarker find=-1.
8. Missingmetadata: newnamespace/tmpfixture, omit ONEknownalpha rootmetadata
   atfixturecreation optionally parameter, no recursivedelete. Propagateerror;
   output_bounds_report.json and output_bounds_provenance.json absent.
9. Success E2E assertALL CSVfields onALL4expectedrows including sortednode_ids,
   edge1->2/sentinels/globalids. Assert actualprovenance token/helperhash and
   filehashes match bytes, namespacecaptureor capsys contains token/hash.
10. Remove unusedsys/numpy, zipstrictTrue, lines<=120, avoiddummy _AttrRow overrides
    andunusedstubs/imports. Use modestfixtures, noextrafiles/importedtesthelpers.

ORIGINAL6DELIVERED EDlTS:
```python
REPLACEMENTS = [
    (
        "    return nodes_by_id, edges, stats\n\n\nDEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector()",
        "    return nodes_by_id, edges, stats\n\n\n__BIOHUB_OUTPUT_BOUNDS_HELPER__\n\nDEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector()",
    ),
    (
        "stats_rows: list[dict[str, object]] = []",
        "stats_rows: list[dict[str, object]] = []\noutput_bounds_reports: list[dict[str, object]] = []",
    ),
    (
        "        dataset = geff_path.stem\n        seen_datasets.add(dataset)\n        graph = graph_from_geff(geff_path)",
        "        dataset = geff_path.stem\n        seen_datasets.add(dataset)\n        output_shape = read_output_shape(TEST_DIR, dataset)\n        output_bounds_report = new_output_bounds_report(dataset, output_shape)\n        graph = graph_from_geff(geff_path)",
    ),
    (
        '        for node_id in sorted(nodes_by_id):\n            node = nodes_by_id[node_id]\n            writer.writerow({\n                "id": row_id,\n                "dataset": dataset,\n                "row_type": "node",\n                "node_id": int(node["node_id"]),\n                "t": int(node["t"]),\n                "z": max(0, int(round(float(node["z"])))),\n                "y": max(0, int(round(float(node["y"])))),\n                "x": max(0, int(round(float(node["x"])))),\n                "source_id": -1,\n                "target_id": -1,\n            })\n            row_id += 1',
        "        for node_id in sorted(nodes_by_id):\n            node = nodes_by_id[node_id]\n            bounded = bounded_output_node(node, dataset, row_id, output_shape, output_bounds_report)\n            writer.writerow(bounded)\n            row_id += 1",
    ),
    (
        "        division_sources: dict[int, int] = {}",
        "        output_bounds_reports.append(output_bounds_report)\n        division_sources: dict[int, int] = {}",
    ),
    (
        'stats.to_csv(RUN_STATS_PATH, index=False)\n\nprint(f"Wrote {SUBMISSION_PATH} with {row_id:,} rows")',
        'stats.to_csv(RUN_STATS_PATH, index=False)\n\nwith SUBMISSION_PATH.with_name("output_bounds_report.json").open("w", encoding="utf-8", newline="\\n") as f:\n    json.dump(output_bounds_reports, f, ensure_ascii=False, allow_nan=False, indent=2)\n\nprint(f"Wrote {SUBMISSION_PATH} with {row_id:,} rows")',
    ),
]
```
CURRENTFAILINGTESTS:
```python
from __future__ import annotations

import ast
import hashlib
import json
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_NB = ROOT / "notebooks" / "e26_target_motion_off" / "e26_target_motion_off.ipynb"
CANDIDATE_NB = ROOT / "notebooks" / "e26_target_motion_off_bounds" / "e26_target_motion_off.ipynb"
ACCEPTED_HELPER = ROOT / "src" / "biohub" / "output_bounds.py"

ORIGINAL_SHA = "a8d2b43e743eea8a99a128e4a2672f1ede8531dc162ebbb10dd957fc5fa7a052"
HELPER_SHA = "d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5"
MARKER = "__BIOHUB_OUTPUT_BOUNDS_HELPER__"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_nb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cell_source(cell: dict) -> str:
    src = cell.get("source", [])
    if isinstance(src, list):
        return "".join(src)
    return str(src)


def _normalize(source: str) -> str:
    return textwrap.dedent(source).rstrip("\n")


def test_original_notebook_sha_fixed():
    assert _sha256(ORIGINAL_NB) == ORIGINAL_SHA


def test_accepted_helper_sha_fixed():
    assert _sha256(ACCEPTED_HELPER) == HELPER_SHA


def test_candidate_notebook_structure_and_metadata():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)

    assert len(cand["cells"]) == 33
    assert len(orig["cells"]) == 33

    for key in ("kernelspec", "language_info"):
        assert cand["metadata"][key] == orig["metadata"][key]

    assert cand["metadata"]["id"] == "taichiiiii/biohub-e26-motion-off-exploratory"

    for idx, (o, c) in enumerate(zip(orig["cells"], cand["cells"])):
        if idx == 13:
            continue
        assert _cell_source(o) == _cell_source(c), f"cell {idx} source changed"
        assert o.get("cell_type") == c.get("cell_type")
        assert o.get("metadata") == c.get("metadata")


def test_cell13_helper_embedded_once_and_compiles():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13])
    assert source.count(MARKER) == 1
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    substituted = source.replace(MARKER, helper_src.rstrip("\n"))
    assert MARKER not in substituted
    ast.parse(substituted)


def test_cell13_reversible_to_original_via_declared_replacements():
    from tests.test_e26_bounds_notebook_helpers import build_replacements  # type: ignore

    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)
    original_source = _normalize(_cell_source(orig["cells"][13]))
    candidate_source = _normalize(_cell_source(cand["cells"][13]))

    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    working = candidate_source.replace(MARKER, helper_src.rstrip("\n"))

    replacements = build_replacements()
    for old, new in reversed(replacements):
        assert working.count(new) == 1, f"replacement target not unique: {new!r}"
        working = working.replace(new, old)

    assert _normalize(working) == original_source


def test_helper_defs_precede_runtime_initialization():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13])
    helper_end = source.find(MARKER) + len(MARKER)
    runtime_anchor = "DEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector()"
    runtime_pos = source.find(runtime_anchor)
    assert helper_end < runtime_pos


def test_sorted_node_edge_logic_unchanged_outside_writer():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)
    orig_src = _cell_source(orig["cells"][13])
    cand_src = _cell_source(cand["cells"][13])

    edge_block = '            writer.writerow({\n                "id": row_id,\n                "dataset": dataset,\n                "row_type": "edge",'
    assert edge_block in cand_src
    assert "for edge in edges:" in cand_src
    assert "division_sources[source_id] = division_sources.get(source_id, 0) + 1" in cand_src
    assert orig_src.count("for node_id in sorted(nodes_by_id):") == cand_src.count("for node_id in sorted(nodes_by_id):")


def test_no_hardcoded_actual_bad_node():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13]).lower()
    assert "badnode" not in source
    assert "actual_bad_node" not in source


class _AttrRow(dict):
    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key, default)


class _Attrs:
    def __init__(self, rows: list[dict]):
        self._rows = [_AttrRow(r) for r in rows]

    def iter_rows(self, named: bool = True):
        assert named
        return iter(self._rows)


class _FakeGraph:
    def __init__(self, nodes: list[dict], edges: list[dict]):
        self._nodes = _Attrs(nodes)
        self._edges = _Attrs(edges)

    def node_attrs(self):
        return self._nodes

    def edge_attrs(self):
        return self._edges


def _build_namespace(tmp_path: Path, helper_src: str):
    submission_path = tmp_path / "submission.csv"
    run_stats_path = tmp_path / "run_stats.csv"
    predictions_dir = tmp_path / "predictions"
    method_dir = predictions_dir / "dummy" / "METHOD" / "split_0"
    method_dir.mkdir(parents=True)
    (method_dir / "alpha.geff").write_text("")
    (method_dir / "beta.geff").write_text("")

    ns: dict[str, object] = {}
    exec(compile(helper_src, "<helper>", "exec"), ns)
    ns.update(
        {
            "TEST_DIR": tmp_path / "test",
            "REPO_DIR": tmp_path,
            "METHOD": "METHOD",
            "test_stems": ["alpha", "beta"],
            "CSV_COLUMNS": [
                "id",
                "dataset",
                "row_type",
                "node_id",
                "t",
                "z",
                "y",
                "x",
                "source_id",
                "target_id",
            ],
            "SUBMISSION_PATH": submission_path,
            "RUN_STATS_PATH": run_stats_path,
            "predict_seconds": 0.0,
            "EXPERIMENT_TAG": "test",
            "DEEPCENTER_VETO_DETECTOR": None,
            "csv": __import__("csv"),
            "pd": pd,
            "display": lambda *a, **k: None,
            "json": json,
        }
    )

    shape_alpha = (3, 4, 6, 8)
    shape_beta = (2, 3, 5, 7)
    meta_root = tmp_path / "test"
    for name, shape in (("alpha", shape_alpha), ("beta", shape_beta)):
        zarr_dir = meta_root / name / "segmentation.zarr"
        zarr_dir.mkdir(parents=True)
        (zarr_dir / "zarr.json").write_text(
            json.dumps({"zarr_format": 3, "shape": list(shape)})
        )

    graphs = {
        "alpha": _FakeGraph(
            nodes=[
                {"node_id": 2, "t": 1, "z": 0.0, "y": 2.0, "x": 2.0},
                {"node_id": 1, "t": 0, "z": 0.0, "y": float(shape_alpha[2]), "x": 1.0},
            ],
            edges=[{"source_id": 1, "target_id": 2, "edge_prob": 0.9}],
        ),
        "beta": _FakeGraph(
            nodes=[{"node_id": 5, "t": 0, "z": 0.0, "y": 1.0, "x": 1.0}],
            edges=[],
        ),
    }

    def stub_graph_from_geff(path):
        return graphs[path.stem]

    def stub_refine(nodes_by_id, dataset):
        return nodes_by_id

    def stub_filter(nodes_by_id, raw_edges, dataset=None, deepcenter_bundle=None):
        return nodes_by_id, raw_edges, {"raw_edges": len(raw_edges)}

    def stub_linefit(nodes_by_id, edges, stats):
        return nodes_by_id

    def stub_short_track(nodes_by_id, edges, stats):
        stats.setdefault("short_track_components_removed", 0)
        return nodes_by_id, edges

    ns.update(
        {
            "graph_from_geff": stub_graph_from_geff,
            "refine_all_centroids": stub_refine,
            "filter_output_graph": stub_filter,
            "linefit_smooth_output_graph": stub_linefit,
            "filter_short_track_components": stub_short_track,
        }
    )
    return ns


def _extract_tail(candidate_source: str) -> str:
    marker = "geffs = sorted((REPO_DIR / \"predictions\").glob"
    idx = candidate_source.find(marker)
    assert idx != -1
    return candidate_source[idx:]


def test_end_to_end_writer_tail_with_bounds(tmp_path):
    cand = _load_nb(CANDIDATE_NB)
    candidate_source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    tail = _extract_tail(candidate_source.replace(MARKER, helper_src.rstrip("\n")))

    ns = _build_namespace(tmp_path, helper_src)
    exec(compile(tail, "<tail>", "exec"), ns)

    submission_path = tmp_path / "submission.csv"
    rows = list(pd.read_csv(submission_path).itertuples(index=False))
    assert [r.row_type for r in rows] == ["node", "node", "edge", "node"]
    ids = [r.id for r in rows]
    assert ids == list(range(len(ids)))

    alpha_nodes = [r for r in rows if r.dataset == "alpha" and r.row_type == "node"]
    assert len(alpha_nodes) == 2
    overshoot = [r for r in alpha_nodes if r.node_id == 1][0]
    assert overshoot.y == 5  # clipped from sizeY=6 to sizeY-1

    report_path = submission_path.with_name("output_bounds_report.json")
    reports = json.loads(report_path.read_text(encoding="utf-8"))
    assert [r["dataset"] for r in reports] == ["alpha", "beta"]
    alpha_report = reports[0]
    assert alpha_report["node_count"] == 2
    assert alpha_report["corrected_count"] == 1
    assert alpha_report["y_corrected_count"] == 1
    assert alpha_report["max_y_clip"] == 1
    sample = next(s for s in alpha_report["samples"] if s["field"] == "y")
    assert sample["original_value"] == float(6)
    assert sample["rounded_value"] == 6
    assert sample["clipped_value"] == 5

    beta_report = reports[1]
    assert beta_report["node_count"] == 1
    assert beta_report["corrected_count"] == 0
    assert beta_report["samples"] == []


def test_missing_metadata_raises_output_bounds_error(tmp_path):
    cand = _load_nb(CANDIDATE_NB)
    candidate_source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    tail = _extract_tail(candidate_source.replace(MARKER, helper_src.rstrip("\n")))

    ns = _build_namespace(tmp_path, helper_src)
    meta_root = tmp_path / "test"
    for child in list(meta_root.iterdir()):
        if child.is_dir():
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink()

    from biohub.output_bounds import OutputBoundsError

    with pytest.raises(OutputBoundsError):
        exec(compile(tail, "<tail>", "exec"), ns)

    report_path = (tmp_path / "submission.csv").with_name("output_bounds_report.json")
    assert not report_path.exists()
```
ORIGINALWRITERTAIL:
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
