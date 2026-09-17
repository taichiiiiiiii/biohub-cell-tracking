# E26 bounds repair — direct supervised Qwen implementation, one task

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

This is a new direct user request to run the loop, not an automated goal wake.
Exact qwen3.7-plus via existing qwen_token_plan subscription-only route.
600 seconds total, retries 0, fallback 0. No tool calls, file access, network,
agents, credentials, commits or Kaggle actions. Deliver code only in the final
response; parent mechanically integrates and executes tests after full review.

Return exactly ONE valid JSON object, NO fences/prose, with exactly these keys:
- "helper_source": complete standalone Python module source.
- "test_source": complete pytest module source.
- "tail_replacements": list of {"old": exact nonempty source string, "new": replacement source string}.
JSON string newlines must be escaped normally. Complete the outer object.
Do not use any tools. Do not claim tests were run.

Targets (parent integration only):
src/biohub/output_bounds.py
tests/test_output_bounds.py
new notebooks/e26_target_motion_off_bounds/e26_target_motion_off_bounds.ipynb
and corresponding kernel metadata, handled mechanically by parent.
Old notebook, original CSV and all scientific source remain immutable.

Confirmed defect: writer below only lower-clips integer coordinates. New helper
completes the general bounds invariant. Exact upstream origin is unknown; final
linefit can extrapolate but is not proven as this instance's numerical cause.
Scientific motion-OFF settings, models, graph, IDs and order remain fixed.

Helper APIs, pure standard library (NO future import, so source can also be
embedded verbatim after existing notebook definitions):
1. read_output_shape(test_dir, dataset) -> tuple(T,Z,Y,X)
   Read only dataset.zarr/zarr.json and dataset.zarr/0/zarr.json via pathlib/json.
   Require root group and array metadata dictionaries, Zarr format3, array rank4
   with exactly positive integral JSON ints (bool/float/string not accepted).
   Confirm multiscales axes names normalized upper == ["T","Z","Y","X"] and
   dataset path "0" in the same metadata entry. Reject missing, ambiguous,
   malformed or mismatched metadata. No shape fallback or image-array reads.
2. new_output_bounds_report(dataset, shape) -> mutable JSON-serializable report
   Validate rank4 positive Python ints, keep dataset/shape, node_count0,
   corrected_nodes0, per-axis counts0, max absolute integer correction0,
   samples[], sample_limit20, samples_truncated false (or equivalently complete
   aggregate fields and deterministic bounded sample schema).
3. bounded_output_node(node, dataset, row_id, shape, report) -> complete node CSV
   dict in the original schema below. Must not mutate node or shape.
   Reject bool/nonintegral/nonfinite/negative node_id, t, row_id. Accept Python/
   numpy Integral and exactly integral finite Real values; no lossy integer
   cast, strings, sentinel or overflowing signed64bit. t must be 0<=t<T.
   IDs are exact int, range0..2**63-1. Validate report identity/shape consistency.
   Coordinates: convert numeric Real values to finite float (reject bool,
   string, NaN, infinity), Python round (ties-to-even), then clip to [0,dim-1].
   Keep exactly original fields/sentinels/order. Every valid uncorrected row
   must be identical to old writer. Do not clamp time or change graph.
   Report complete node_count, corrected_nodes (once/node), per-axis counts,
   max absolute integer correction, bounded first20 correction samples in
   invocation/axis z,y,x order. Each sample: dataset,row_id,node_id,t,axis,
   original_float,rounded_int,clipped_int,signed_delta,absolute_delta.
   Sample truncation must be explicit without truncating aggregates.
   Only update report after whole node validates; failure must not partly
   update it. Finite negative coordinates retain existing lower clipping.
   No IDs/datasets/shapes hardcoded in runtime logic.

Tail edits: produce exact small old/new replacements against the provided
original tail only. Parent embeds helper_source verbatim immediately before
that tail (no imports of repo modules on Kaggle).
- initialize reports list near stats_rows.
- inside each dataset load actual shape/new report (before node writing).
- replace old writer.writerow node block with bounded_output_node(...) call.
- append report once/dataset after nodes, preserve all other source exactly.
- after existing stats.to_csv, write output_bounds_report.json beside
  SUBMISSION_PATH using json.dumps(...,allow_nan=False,indent=2) for all reports.
No changes to raw conversion, refinement, graph pipeline, stats, edge writer,
prints, dataset list, model loading or any other settings. Validation applies
to final serializer inputs; do not pretend existing raw int casts are newly
validated. Do NOT add raw tracing or upstream changes to this repair.

Focused pytest covers all axes lower/upper and rounding, ties-to-even,
noncubic shapes, dimension1, zero-change inputs, no mutation, invalid complete
time/ID types/ranges, malformed/missing/reordered metadata, nonfinite/nonnumeric
coordinates, atomic report update on failure, multiple-axis single-node counts,
deterministic/truncated samples and zero corrections.
Use tmp_path metadata fixtures only; no real dataset/weights/network. Include
small endpoint OLS-equivalent overshoot fixture with finite starting coordinates,
show round may exceed upper bound and general output returns valid bound (not
claiming proof about real node). Tests import biohub.output_bounds.
Keep code readable and minimal, Ruff E/W/F/I/UP/B, line length120, Python3.12.

Public4 acceptance OUTSIDE runtime code:
pinned E23 CSV maps to no changes; saved invalid E26 maps to exactly one y256->255
at 44b6_0113de3b/node12069/t49. Corrected physical rerun must preserve every other
field/row/topology, otherwise NO SUBMIT. These identities never belong in helper
logic. This task does not author experiment scores, adoption or submission.

Reference actual metadata and complete original writer tail follow as data:
{
  "tail": "stats_rows: list[dict[str, object]] = []\nseen_datasets: set[str] = set()\nrow_id = 0\ntotal_nodes = 0\ntotal_edges = 0\n\nwith SUBMISSION_PATH.open(\"w\", newline=\"\") as f:\n    writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)\n    writer.writeheader()\n\n    for geff_path in geffs:\n        dataset = geff_path.stem\n        seen_datasets.add(dataset)\n        graph = graph_from_geff(geff_path)\n\n        nodes_by_id: dict[int, dict[str, object]] = {}\n        for row in graph.node_attrs().iter_rows(named=True):\n            node_id = int(row[\"node_id\"])\n            nodes_by_id[node_id] = {\n                \"node_id\": node_id,\n                \"t\": int(row[\"t\"]),\n                \"z\": float(row[\"z\"]),\n                \"y\": float(row[\"y\"]),\n                \"x\": float(row[\"x\"]),\n            }\n\n        raw_edges: list[dict[str, object]] = []\n        for row in graph.edge_attrs().iter_rows(named=True):\n            edge_prob = row.get(\"edge_prob\") if hasattr(row, \"get\") else None\n            raw_edges.append({\n                \"source_id\": int(row[\"source_id\"]),\n                \"target_id\": int(row[\"target_id\"]),\n                \"edge_prob\": None if edge_prob is None else float(edge_prob),\n            })\n\n        raw_node_count = len(nodes_by_id)\n        # НАША ФИЧА: уточняем центры всех клеток перед постобработкой\n        nodes_by_id = refine_all_centroids(nodes_by_id, dataset)\n        nodes_by_id, edges, filter_stats = filter_output_graph(nodes_by_id, raw_edges, dataset=dataset, deepcenter_bundle=DEEPCENTER_VETO_DETECTOR)\n        if not nodes_by_id:\n            raise AssertionError(f\"{dataset}: post-processing removed every node\")\n\n        for node_id in sorted(nodes_by_id):\n            node = nodes_by_id[node_id]\n            writer.writerow({\n                \"id\": row_id,\n                \"dataset\": dataset,\n                \"row_type\": \"node\",\n                \"node_id\": int(node[\"node_id\"]),\n                \"t\": int(node[\"t\"]),\n                \"z\": max(0, int(round(float(node[\"z\"])))),\n                \"y\": max(0, int(round(float(node[\"y\"])))),\n                \"x\": max(0, int(round(float(node[\"x\"])))),\n                \"source_id\": -1,\n                \"target_id\": -1,\n            })\n            row_id += 1\n\n        division_sources: dict[int, int] = {}\n        for edge in edges:\n            source_id = int(edge[\"source_id\"])\n            target_id = int(edge[\"target_id\"])\n            if source_id not in nodes_by_id or target_id not in nodes_by_id:\n                raise AssertionError(f\"{dataset}: dangling edge after filtering\")\n            writer.writerow({\n                \"id\": row_id,\n                \"dataset\": dataset,\n                \"row_type\": \"edge\",\n                \"node_id\": -1,\n                \"t\": -1,\n                \"z\": -1,\n                \"y\": -1,\n                \"x\": -1,\n                \"source_id\": source_id,\n                \"target_id\": target_id,\n            })\n            row_id += 1\n            division_sources[source_id] = division_sources.get(source_id, 0) + 1\n\n        node_count = len(nodes_by_id)\n        edge_count = len(edges)\n        total_nodes += node_count\n        total_edges += edge_count\n        stats_rows.append({\n            \"dataset\": dataset,\n            \"raw_nodes\": raw_node_count,\n            \"nodes\": node_count,\n            \"raw_edges\": filter_stats[\"raw_edges\"],\n            \"edges\": edge_count,\n            \"division_like_sources\": sum(1 for count in division_sources.values() if count >= 2),\n            \"edge_to_node_ratio\": edge_count / max(node_count, 1),\n            \"gap_added_nodes_frac\": filter_stats.get(\"gap_added_nodes\", 0) / max(raw_node_count, 1),\n            **filter_stats,\n        })\n\nexpected_datasets = set(test_stems)\nmissing_datasets = sorted(expected_datasets - seen_datasets)\nextra_datasets = sorted(seen_datasets - expected_datasets)\nif missing_datasets or extra_datasets:\n    raise AssertionError({\"missing\": missing_datasets[:10], \"extra\": extra_datasets[:10]})\nassert row_id == total_nodes + total_edges, \"Internal row counter mismatch\"\nassert total_nodes > 0, \"No node rows produced\"\n\nheader = SUBMISSION_PATH.open().readline().strip().split(\",\")\nassert header == CSV_COLUMNS, f\"Bad CSV header: {header}\"\n\nstats = pd.DataFrame(stats_rows).sort_values(\"dataset\").reset_index(drop=True)\nstats[\"predict_minutes_total\"] = predict_seconds / 60.0\nstats[\"experiment_tag\"] = EXPERIMENT_TAG\nstats.to_csv(RUN_STATS_PATH, index=False)\n\nprint(f\"Wrote {SUBMISSION_PATH} with {row_id:,} rows\")\nprint(f\"Node rows: {total_nodes:,} | edge rows: {total_edges:,}\")\nprint(f\"Wrote {RUN_STATS_PATH}\")\ndisplay(pd.read_csv(SUBMISSION_PATH, nrows=8))",
  "root_metadata": {
    "attributes": {
      "multiscales": [
        {
          "version": "0.5",
          "axes": [
            {
              "name": "T",
              "type": "time",
              "unit": "second"
            },
            {
              "name": "Z",
              "type": "space",
              "unit": "micrometer"
            },
            {
              "name": "Y",
              "type": "space",
              "unit": "micrometer"
            },
            {
              "name": "X",
              "type": "space",
              "unit": "micrometer"
            }
          ],
          "datasets": [
            {
              "path": "0",
              "coordinateTransformations": [
                {
                  "type": "scale",
                  "scale": [
                    1,
                    1.625,
                    0.40625,
                    0.40625
                  ]
                }
              ]
            }
          ],
          "name": "0"
        }
      ],
      "image_statistics": {
        "quantiles": {
          "0.0": 15,
          "0.001": 26.222222222222225,
          "0.01": 38,
          "0.1": 75,
          "0.9": 497,
          "0.99": 1478,
          "0.999": 2145.000000039654,
          "1.0": 4319
        }
      }
    },
    "zarr_format": 3,
    "consolidated_metadata": null,
    "node_type": "group"
  },
  "array_metadata": {
    "shape": [
      100,
      64,
      256,
      256
    ],
    "data_type": "uint16",
    "chunk_grid": {
      "name": "regular",
      "configuration": {
        "chunk_shape": [
          1,
          64,
          256,
          256
        ]
      }
    },
    "chunk_key_encoding": {
      "name": "default",
      "configuration": {
        "separator": "/"
      }
    },
    "fill_value": 0,
    "codecs": [
      {
        "name": "bytes",
        "configuration": {
          "endian": "little"
        }
      },
      {
        "name": "blosc",
        "configuration": {
          "typesize": 2,
          "cname": "zstd",
          "clevel": 1,
          "shuffle": "bitshuffle",
          "blocksize": 0
        }
      }
    ],
    "attributes": {},
    "zarr_format": 3,
    "node_type": "array",
    "storage_transformers": []
  }
}
