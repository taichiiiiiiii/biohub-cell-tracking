from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_NB = ROOT / "notebooks" / "e26_target_motion_off" / "e26_target_motion_off.ipynb"
CANDIDATE_NB = (
    ROOT / "notebooks" / "e26_target_motion_off_bounds" / "e26_target_motion_off.ipynb"
)
ACCEPTED_HELPER = ROOT / "src" / "biohub" / "output_bounds.py"

ORIGINAL_SHA = "a8d2b43e743eea8a99a128e4a2672f1ede8531dc162ebbb10dd957fc5fa7a052"
HELPER_SHA = "d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5"
MARKER = "__BIOHUB_OUTPUT_BOUNDS_HELPER__"
RUN_TOKEN = "e26-bounds-a8d2b43e-d39549fb-20260907-v3"

REPLACEMENTS = [
    (
        (
            "    return nodes_by_id, edges, stats\n\n\nD"
            "EEPCENTER_VETO_DETECTOR = load_deepcente"
            "r_veto_detector()"
        ),
        (
            "    return nodes_by_id, edges, stats\n\n\n_"
            "_BIOHUB_OUTPUT_BOUNDS_HELPER__\n\nOUTPUT_B"
            "OUNDS_RUN_TOKEN = \"e26-bounds-a8d2b43e-d"
            "39549fb-20260907-v3\"\nprint(\"E26_BOUNDS_RUN_"
            "TOKEN=\" + OUTPUT_BOUNDS_RUN_TOKEN)\n\nDEEP"
            "CENTER_VETO_DETECTOR = load_deepcenter_v"
            "eto_detector()"
        ),
    ),
    (
        (
            "stats_rows: list[dict[str, object]] = []"
        ),
        (
            "stats_rows: list[dict[str, object]] = []"
            "\noutput_bounds_reports: list[dict[str, o"
            "bject]] = []"
        ),
    ),
    (
        (
            "        dataset = geff_path.stem\n       "
            " seen_datasets.add(dataset)\n        grap"
            "h = graph_from_geff(geff_path)"
        ),
        (
            "        dataset = geff_path.stem\n       "
            " seen_datasets.add(dataset)\n        outp"
            "ut_shape = read_output_shape(TEST_DIR, d"
            "ataset)\n        output_bounds_report = n"
            "ew_output_bounds_report(dataset, output_"
            "shape)\n        graph = graph_from_geff(g"
            "eff_path)"
        ),
    ),
    (
        (
            "        for node_id in sorted(nodes_by_i"
            "d):\n            node = nodes_by_id[node_"
            "id]\n            writer.writerow({\n      "
            "          \"id\": row_id,\n                "
            "\"dataset\": dataset,\n                \"row"
            "_type\": \"node\",\n                \"node_id"
            "\": int(node[\"node_id\"]),\n               "
            " \"t\": int(node[\"t\"]),\n                \"z"
            "\": max(0, int(round(float(node[\"z\"])))),"
            "\n                \"y\": max(0, int(round(f"
            "loat(node[\"y\"])))),\n                \"x\":"
            " max(0, int(round(float(node[\"x\"])))),\n "
            "               \"source_id\": -1,\n        "
            "        \"target_id\": -1,\n            })\n"
            "            row_id += 1"
        ),
        (
            "        for node_id in sorted(nodes_by_i"
            "d):\n            node = nodes_by_id[node_"
            "id]\n            bounded = bounded_output"
            "_node(node, dataset, row_id, output_shap"
            "e, output_bounds_report)\n            wri"
            "ter.writerow(bounded)\n            row_id"
            " += 1"
        ),
    ),
    (
        (
            "        division_sources: dict[int, int]"
            " = {}"
        ),
        (
            "        output_bounds_reports.append(out"
            "put_bounds_report)\n        division_sour"
            "ces: dict[int, int] = {}"
        ),
    ),
    (
        (
            "stats.to_csv(RUN_STATS_PATH, index=False"
            ")\n\nprint(f\"Wrote {SUBMISSION_PATH} with "
            "{row_id:,} rows\")"
        ),
        (
            "stats.to_csv(RUN_STATS_PATH, index=False"
            ")\n\nimport hashlib as output_bounds_hashl"
            "ib\n\noutput_bounds_report_path = SUBMISSI"
            "ON_PATH.with_name(\"output_bounds_report."
            "json\")\nwith output_bounds_report_path.op"
            "en(\"w\", encoding=\"utf-8\", newline=\"\\n\") "
            "as f:\n    json.dump(output_bounds_report"
            "s, f, ensure_ascii=False, allow_nan=Fals"
            "e, indent=2)\n\nsubmission_bytes = SUBMISS"
            "ION_PATH.read_bytes()\nreport_bytes = out"
            "put_bounds_report_path.read_bytes()\noutp"
            "ut_bounds_provenance = {\n    \"schema_ver"
            "sion\": 1,\n    \"run_token\": OUTPUT_BOUNDS"
            "_RUN_TOKEN,\n    \"helper_sha256\": \"d39549"
            "fbaeefc9edbd6273e10c3cf96377b33b1ea6d080"
            "befec6bd12071e5df5\",\n    \"submission_sha"
            "256\": output_bounds_hashlib.sha256(submi"
            "ssion_bytes).hexdigest(),\n    \"output_bo"
            "unds_report_sha256\": output_bounds_hashl"
            "ib.sha256(report_bytes).hexdigest(),\n}\np"
            "rovenance_path = SUBMISSION_PATH.with_na"
            "me(\"output_bounds_provenance.json\")\nwith"
            " provenance_path.open(\"w\", encoding=\"utf"
            "-8\", newline=\"\\n\") as f:\n    json.dump(o"
            "utput_bounds_provenance, f, ensure_ascii"
            "=False, allow_nan=False, indent=2)\n\nprin"
            "t(\"E26_BOUNDS_RUN_TOKEN=\" + OUTPUT_BOUND"
            "S_RUN_TOKEN)\nprint(\"E26_BOUNDS_SUBMISSIO"
            "N_SHA256=\" + output_bounds_provenance[\"s"
            "ubmission_sha256\"])\nprint(f\"Wrote {SUBMI"
            "SSION_PATH} with {row_id:,} rows\")"
        ),
    ),
]

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_nb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cell_source(cell: dict) -> str:
    src = cell.get("source", [])
    if isinstance(src, list):
        return "".join(src)
    return str(src)


def test_original_notebook_sha_fixed():
    assert _sha256(ORIGINAL_NB) == ORIGINAL_SHA


def test_accepted_helper_sha_fixed():
    assert _sha256(ACCEPTED_HELPER) == HELPER_SHA


def test_candidate_notebook_structure_and_metadata():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)

    assert len(cand["cells"]) == 33
    assert len(orig["cells"]) == 33

    cloned_cand = copy.deepcopy(cand)
    cloned_cand["cells"][13]["source"] = orig["cells"][13]["source"]
    assert cloned_cand == orig

    kernel_orig = json.loads(
        (ORIGINAL_NB.parent / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    kernel_cand = json.loads(
        (CANDIDATE_NB.parent / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    assert kernel_cand["id"] == "taichiiiii/biohub-e26-motion-off-exploratory"
    kernel_cand_copy = copy.deepcopy(kernel_cand)
    kernel_cand_copy["id"] = kernel_orig["id"]
    assert kernel_cand_copy == kernel_orig


def test_cell13_helper_embedded_once_and_compiles():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13])
    assert MARKER not in source
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    assert source.count(helper_src) == 1
    ast.parse(source)


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
    assert expected.count(MARKER) == 1
    expected = expected.replace(MARKER, helper_src)

    assert candidate_source == expected


def test_helper_defs_precede_runtime_initialization():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    helper_end = source.find(helper_src) + len(helper_src)
    runtime_anchor = "DEEPCENTER_VETO_DETECTOR = load_deepcenter_veto_detector()"
    runtime_pos = source.find(runtime_anchor)
    assert helper_end < runtime_pos


def test_sorted_node_edge_logic_unchanged_outside_writer():
    orig = _load_nb(ORIGINAL_NB)
    cand = _load_nb(CANDIDATE_NB)
    orig_src = _cell_source(orig["cells"][13])
    cand_src = _cell_source(cand["cells"][13])

    edge_block = (
        '            writer.writerow({\n'
        '                "id": row_id,\n'
        '                "dataset": dataset,\n'
        '                "row_type": "edge",'
    )
    assert edge_block in cand_src
    assert "for edge in edges:" in cand_src
    assert (
        "division_sources[source_id] = division_sources.get(source_id, 0) + 1"
        in cand_src
    )
    assert orig_src.count("for node_id in sorted(nodes_by_id):") == cand_src.count(
        "for node_id in sorted(nodes_by_id):"
    )


def test_no_hardcoded_actual_bad_node():
    cand = _load_nb(CANDIDATE_NB)
    source = _cell_source(cand["cells"][13]).lower()
    assert "badnode" not in source
    assert "actual_bad_node" not in source


class _AttrRow(dict):
    pass


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


def _write_zarr_metadata(root: Path, dataset: str, shape: tuple[int, ...]):
    ds_root = root / f"{dataset}.zarr"
    ds_root.mkdir(parents=True, exist_ok=True)
    root_meta = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {
            "multiscales": [
                {
                    "axes": [
                        {"name": "t"},
                        {"name": "z"},
                        {"name": "y"},
                        {"name": "x"},
                    ],
                    "datasets": [{"path": "0"}],
                }
            ]
        },
    }
    (ds_root / "zarr.json").write_text(
        json.dumps(root_meta, ensure_ascii=False), encoding="utf-8"
    )
    array_dir = ds_root / "0"
    array_dir.mkdir(parents=True, exist_ok=True)
    array_meta = {"zarr_format": 3, "node_type": "array", "shape": list(shape)}
    (array_dir / "zarr.json").write_text(
        json.dumps(array_meta, ensure_ascii=False), encoding="utf-8"
    )


def _build_namespace(tmp_path: Path, helper_src: str, *, omit_alpha_root: bool = False):
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
            "OUTPUT_BOUNDS_RUN_TOKEN": RUN_TOKEN,
        }
    )

    shape_alpha = (3, 4, 6, 8)
    shape_beta = (2, 3, 5, 7)
    meta_root = tmp_path / "test"
    if not omit_alpha_root:
        _write_zarr_metadata(meta_root, "alpha", shape_alpha)
    _write_zarr_metadata(meta_root, "beta", shape_beta)

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
    marker = 'geffs = sorted((REPO_DIR / "predictions").glob'
    idx = candidate_source.find(marker)
    assert idx != -1
    return candidate_source[idx:]


def test_end_to_end_writer_tail_with_bounds(tmp_path, capsys):
    cand = _load_nb(CANDIDATE_NB)
    candidate_source = _cell_source(cand["cells"][13])
    helper_src = ACCEPTED_HELPER.read_text(encoding="utf-8")
    tail = _extract_tail(candidate_source)

    assert candidate_source.count(helper_src) == 1
    start = candidate_source.index(helper_src)
    embedded_helper = candidate_source[start : start + len(helper_src)]

    tree = ast.parse(candidate_source)
    token_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "OUTPUT_BOUNDS_RUN_TOKEN"
    ]
    assert len(token_nodes) == 1
    parsed_token = ast.literal_eval(token_nodes[0].value)
    assert parsed_token == RUN_TOKEN

    ns = _build_namespace(tmp_path, embedded_helper)
    ns["OUTPUT_BOUNDS_RUN_TOKEN"] = parsed_token
    exec(compile(tail, "<tail>", "exec"), ns)

    submission_path = tmp_path / "submission.csv"
    df = pd.read_csv(submission_path)
    rows = df.to_dict("records")
    assert len(rows) == 4
    assert rows[0] == {
        "id": 0,
        "dataset": "alpha",
        "row_type": "node",
        "node_id": 1,
        "t": 0,
        "z": 0,
        "y": 5,
        "x": 1,
        "source_id": -1,
        "target_id": -1,
    }
    assert rows[1] == {
        "id": 1,
        "dataset": "alpha",
        "row_type": "node",
        "node_id": 2,
        "t": 1,
        "z": 0,
        "y": 2,
        "x": 2,
        "source_id": -1,
        "target_id": -1,
    }
    assert rows[2] == {
        "id": 2,
        "dataset": "alpha",
        "row_type": "edge",
        "node_id": -1,
        "t": -1,
        "z": -1,
        "y": -1,
        "x": -1,
        "source_id": 1,
        "target_id": 2,
    }
    assert rows[3] == {
        "id": 3,
        "dataset": "beta",
        "row_type": "node",
        "node_id": 5,
        "t": 0,
        "z": 0,
        "y": 1,
        "x": 1,
        "source_id": -1,
        "target_id": -1,
    }

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
    assert sample["row_id"] == 0
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

    assert candidate_source.count(helper_src) == 1
    start = candidate_source.index(helper_src)
    embedded_helper = candidate_source[start : start + len(helper_src)]

    tree = ast.parse(candidate_source)
    token_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "OUTPUT_BOUNDS_RUN_TOKEN"
    ]
    assert len(token_nodes) == 1
    parsed_token = ast.literal_eval(token_nodes[0].value)
    assert parsed_token == RUN_TOKEN

    ns = _build_namespace(tmp_path, embedded_helper, omit_alpha_root=True)
    ns["OUTPUT_BOUNDS_RUN_TOKEN"] = parsed_token
    OutputBoundsError = ns["OutputBoundsError"]

    with pytest.raises(OutputBoundsError):
        exec(compile(tail, "<tail>", "exec"), ns)

    report_path = (tmp_path / "submission.csv").with_name(
        "output_bounds_report.json"
    )
    prov_path = (tmp_path / "submission.csv").with_name(
        "output_bounds_provenance.json"
    )
    assert not report_path.exists()
    assert not prov_path.exists()
