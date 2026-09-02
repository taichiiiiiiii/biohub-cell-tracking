# External 0.933 account replay — offline staging runbook

Status: **SOURCE VERIFIED / OFFLINE STAGING ONLY / PUSH-RUN-SUBMIT HOLD**

This path prepares an account-local portability replay of the immutable public
run documented in `external_933_provenance.md`. It does not claim a new method,
does not expose the hidden scored CSV, and does not authorize a Kaggle request.
The source run/session/submission join is `345883663 -> 55877457 -> 0.933`.

The tracked preparer performs no network operation. It verifies the complete
ignored provenance bundle, pinned manifest SHA-256, exact official-pull
notebook bytes, ten-cell executable AST SHA-256, immutable view-model binding,
and ordered Kaggle source IDs. Staging copies the exact notebook bytes and
creates a private T4/no-internet kernel metadata file under a fresh ignored
directory. The receipt remains `STAGED_NOT_AUTHORIZED_TO_PUSH` and the ready
marker permits only offline review.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  scripts/prepare_external_933_replay.py --verify-only

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  scripts/prepare_external_933_replay.py \
  --output-dir outputs/local/external_933_replay/<fresh-run-id>
```

The first offline staging run completed at
`outputs/local/external_933_replay/20260902T140207JST_source_v1` without a
Kaggle request. Its hashes are:

| artifact | SHA-256 |
|---|---|
| `REPLAY_RECEIPT.json` | `1c03ee63d2e326c02c30d3a2dfd8ee3d3106ea7a269dec8d53d4ee58af031257` |
| `READY.json` | `dea907bea4ea4a25646308fb3fa9b62a1c14975251364756cf127947c56886b3` |
| exact notebook | `c7cdda0acf9dc704865165feae06d933fc85748dd4d8e9454734b91a65f0eb10` |
| kernel metadata | `7ede307ce9bb4ccc7a205fa3706d2de83462a3fe5d47163c3243c3c19f0fdae2` |

The executable AST was independently recomputed with CPython `3.14.7`
(interpreter SHA-256
`87d4df53fd91304be5bac391fb204643c36b7df2023c04a0953bcbc7d4fdf634`)
and matched the pinned scored-source AST
`0d1809e9e71ec410664ade0204b1a17896dc95954a721ea0bc46773f6fbb221d`.
The ready marker still authorizes only `OFFLINE_REVIEW_ONLY`.

Before any future `kaggle kernels push`, all of the following remain mandatory:

1. the `2026-09-02 22:40 JST` no-request boundary in
   `eval36_image_resume_runbook.md` has elapsed and a single fresh preflight
   passes without HTTP 429;
2. source reuse/license and attribution are reviewed and recorded—the staged
   bytes are a public-source replay, not original account code;
3. `READY.json`, `REPLAY_RECEIPT.json`, notebook, and metadata hashes are
   reverified, and the package contains no credential or unpinned input;
4. the operator records that this is a portability/runtime replay of an
   already verified 0.933 anchor, not evidence of a new 0.933 claim;
5. run completion, output schema, full hidden coverage, runtime, and the exact
   account submission join are inspected before any score is adopted.

Do not use the public-four CSV as the hidden output. Do not alter the source
notebook in place. Any source, dataset, environment, or metadata change creates
a separately named candidate and invalidates exact-replay language. A future
account score below 0.933 is retained as portability evidence; it is not
silently retried or tuned from the same leaderboard observation.
