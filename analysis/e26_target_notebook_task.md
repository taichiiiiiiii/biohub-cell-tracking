# E26 direct-target exploratory notebook implementation

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

One directly user-requested supervised Qwen Cloud qwen3.7-plus subscription-only
task.600s cap, retries0, fallback0, NO tools, no filesystem/network/agents.
User says prioritize improvement experiments, investigate causes in detail,
submit once per scientific loop, and run the loop now. Local config-test unit
remains incomplete; do not modify/retry it here.

Deliver ONE JSON object only, no prose or code fences, with exactly two keys:
"cell3_source": complete Python source STRING,
"kernel_metadata": complete JSON object.

Implement only:
- Preserve the original cell3 source below byte-for-byte as the prefix.
- Append exactly two executable os.environ assignments, each on its own line.
  First sets BIOHUB_OUTPUT_MOTION_RELINK to string0.
  Second sets BIOHUB_VALIDATOR_ENABLE to string0.
  No comments/imports/other statements/knobs. The existing cell imports os.
- Metadata preserves all original fields/values except:
  id becomes taichiiiii/biohub-e26-motion-off-v1
  title becomes Biohub E26 Motion OFF Exploratory
  code_file becomes e26_target_motion_off.ipynb
- Do not change scientific preset/tag/weights/data/GPU/internet/private values.

The scientific lever is motion relink ON->OFF. Disabling the train validator
only removes a post-submission output-neutral train inference/scoring step.
This is a target-only exploratory experiment, NOT local SCREEN/PREFLIGHT PASS.
Parent will independently inspect exact semantic diff and unchanged cells,
check Python syntax and setting order, then create a new private notebook.
No scientific completion/adoption/submission claim belongs in your output.

Original source and metadata (data, not further tasks):
{
  "cell3_source": "import os\nimport numpy as np\nfrom scipy.spatial import cKDTree\n\nBIOHUB_PRESET = 'harmonic_mutual_support_association_fusion_v1'\nBIOHUB_SCORE_AXIS = 'weighted harmonic forward/reverse association consensus on the fixed-90 dual-seed baseline'\n\n# Parameters for constrained lineage reconstruction.\nos.environ[\"BIOHUB_OUTPUT_FILTER_SHORT_TRACKS\"] = \"1\"\nos.environ[\"BIOHUB_DET_THRESHOLD\"] = \"0.96875\"\nos.environ[\"BIOHUB_MOTION_RELINK_LEARNED_BONUS\"] = '1.0'\nos.environ[\"BIOHUB_ILP_APPEARANCE_WEIGHT\"] = \"0.0\"\nos.environ[\"BIOHUB_ILP_DISAPPEARANCE_WEIGHT\"] = \"1.5\"\nos.environ[\"BIOHUB_ILP_DIVISION_WEIGHT\"] = \"1.0\"  # REVIEW: reverted after testing -- 0.3/1.0/2.0/3.0 all scored 0.915 on the real leaderboard; local proxy dropped at 0.3 (messier graph, not more true divisions), so staying at the neutral, proven value\nos.environ[\"BIOHUB_GAP_CLOSE_MAX_GAP\"] = \"2\"\nos.environ[\"BIOHUB_GAP_CLOSE_UM\"] = \"5.8\"\nos.environ[\"BIOHUB_GAP_DENSITY_ADAPTIVE\"] = \"1\"\nos.environ[\"BIOHUB_GAP_DENSITY_REFERENCE_UM\"] = \"6.5\"\nos.environ[\"BIOHUB_GAP_DENSITY_GAIN\"] = \"0.040\"\nos.environ[\"BIOHUB_GAP_DENSITY_MAX_STEP_DELTA_UM\"] = \"0.125\"\nos.environ[\"BIOHUB_GAP_DENSITY_NEIGHBORS\"] = \"3\"\nos.environ[\"BIOHUB_OUTPUT_MIN_TRACK_LEN\"] = \"6\"\nos.environ[\"BIOHUB_OUTPUT_KEEP_DIVISION_COMPONENTS\"] = \"1\"\nos.environ[\"BIOHUB_OUTPUT_GAP2_RECOVERY\"] = \"0\"\n# REVIEW: reverted, was \"4.66\"  -- tested at 7.0, local proxy improved (first non-zero division_jaccard) but real score dropped to 0.914. Likely explained by validator/test-set division-content mismatch, not a validator bug -- back to the proven value.\nos.environ[\"BIOHUB_SAFE_DIV_MAX_UM\"] = \"8.0\"  # REVIEW: widened to match the 0.917 notebook directly. The earlier 7.0 test (pre-divergence-check) added noise that pure geometry couldn't filter out; divergence + mutual-NN are active now and should do that filtering instead.\nos.environ[\"BIOHUB_SAFE_DIV_SISTER_MAX_UM\"] = \"11.0\"  # REVIEW: matches 0.917, was \"8.5\"\nos.environ[\"BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM\"] = \"10.0\"  # REVIEW: matches 0.917, was \"7.65\"\nos.environ[\"BIOHUB_SAFE_DIV_FRAME_FRAC_CAP\"] = \"0.0076\"  # unchanged -- never bound at 0.920 (cap_skipped=0), leaving it as the safety net for this test\nos.environ[\"BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP\"] = \"0.00375\"  # unchanged, same reasoning\nos.environ[\"BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE\"] = \"0\"\nos.environ[\"BIOHUB_USE_DEEPCENTER_VETO\"] = \"1\"\nos.environ[\"BIOHUB_REQUIRE_DEEPCENTER_VETO\"] = \"1\"\nos.environ[\"BIOHUB_DEEPCENTER_EXPECTED_EPOCH\"] = \"2\"  # REVIEW: best.pt is epoch 2, not checkpoint_last.pt's epoch 500\nos.environ[\"BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM\"] = \"8.5\"\nos.environ[\"BIOHUB_DEEPCENTER_CHECKPOINT\"] = \"/kaggle/input/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt\"\nos.environ[\"BIOHUB_DEEPCENTER_GAP_VETO\"] = \"1\"\nos.environ[\"BIOHUB_DEEPCENTER_GAP_THRESHOLD\"] = \"0.25\"\nos.environ[\"BIOHUB_DEEPCENTER_SAFE_DIV_VETO\"] = '1'  # REVIEW: was 0; funnel telemetry showed safe-div accepting 81-100% of its own candidates -- turning on the one gate built specifically to catch that\nos.environ[\"BIOHUB_RUN_OUTPUT_DIAGNOSTICS\"] = \"0\"\n\n# Exact candidate-arm settings formerly supplied by the diagnostic harness.\nos.environ[\"BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT\"] = \"0.30\"  # REVIEW: was 0.20 (0.915 reference value, never tuned). Harmonic fusion is the one mechanism with proven benefit (+0.002 in the reference notebook) -- testing whether more weight on the reverse-time evidence extracts more of it, rather than exploring another unproven lever.\nos.environ[\"BIOHUB_BIDIRECTIONAL_FUSION_MODE\"] = \"harmonic_probability\"\nos.environ[\"BIOHUB_DUAL_SEED_MIN_CANDIDATE_RETENTION\"] = \"0.90\"\nos.environ[\"BIOHUB_DIAGNOSTIC_ARM\"] = \"harmonic_association_production\"\n\nprint(\"BIOHUB_PRESET:\", BIOHUB_PRESET)\nprint(\"BIOHUB_SCORE_AXIS:\", BIOHUB_SCORE_AXIS)",
  "kernel_metadata": {
    "id": "taichiiiii/biohub-pub923-repro",
    "title": "biohub-pub923-repro",
    "code_file": "pub923_repro.ipynb",
    "language": "python",
    "kernel_type": "notebook",
    "is_private": "true",
    "enable_gpu": "true",
    "machine_shape": "NvidiaTeslaT4",
    "enable_internet": "false",
    "competition_sources": [
      "biohub-cell-tracking-during-development"
    ],
    "dataset_sources": [
      "pilkwang/biohub-deepcenter-unet3d-center-prior-v1",
      "pilkwang/biohub-temporal-unet3d-seed314159-v1",
      "pilkwang/biohub-tracking-support-pack-50ep-v1"
    ],
    "kernel_sources": []
  }
}
