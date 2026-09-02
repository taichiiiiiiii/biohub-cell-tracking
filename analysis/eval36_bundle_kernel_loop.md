# Eval-36 bundle recovery loop

Updated: 2026-09-03 (Asia/Tokyo)

This is the live record for the prerequisite recovery loop. It follows the
binding order in `analysis/gold_loop_protocol.md`:

`hypothesis freeze -> cause diagnosis -> independent review -> minimal
implementation -> tests -> sequential physical evaluation -> failure/countermeasure
record -> next-loop design`.

## 1. Frozen hypothesis

A private CPU Kaggle script can replace the rate-limited 1,487-file download
tail with 15 deterministic, uncompressed USTAR archives. Embedding the exact
reviewed packer and exact CRLF manifest in the single uploaded script should
preserve the existing manifest/security contract while staying below the
documented Kaggle saved-output quota.

This loop changes recovery transport only. It does not change model weights,
tracking logic, metric code, or a submission candidate, and it does not make a
leaderboard claim.

## 2. Cause diagnosis

- Local eval-36 images: 21/36 roots complete, 2,185/3,672 exact files.
- Exact shortfall: 1,487 files and 5,930,937,781 bytes; mismatch, extra,
  symlink, and partial counts are all zero.
- The prior individual-file recovery stopped on HTTP 429.
- Complete raw GEFF predictions already exist for all 36 roots (1,188 files,
  10,090,215 bytes), but official paired scoring remains gated on exact images.
- The 15 complete archive roots contain 1,530 manifest payloads and
  6,103,118,971 payload bytes. Exact USTAR total is 6,104,616,960 bytes.
- Kaggle CLI 2.2.4 uploads only the UTF-8 text named by metadata `code_file`;
  sibling packer/manifest files are not uploaded.
- Prior real kernel logs establish the competition mount as
  `/kaggle/input/competitions/biohub-cell-tracking-during-development`.

## 3. Independent pre-change reviews

Three read-only SOL reviews were completed before implementation:

1. roadmap audit: image readiness is the first hard prerequisite; there is no
   evidence-grade new candidate to submit before it clears;
2. threat review: require exact byte embedding, unique normalized self-hash,
   no CLI overrides or mount fallback, stable no-follow output sealing, bounded
   failure output, and PASS receipt last;
3. package/CLI review: require one script plus exact private-CPU metadata,
   module registration before executing the embedded dataclass packer, fresh
   staging, and a physical quota/runtime/export proof.

The reviews left physical Kaggle output persistence as the principal unresolved
risk; that risk cannot be closed by more local reasoning.

## 4. Minimal implementation

Owned changes:

- `scripts/prepare_eval36_bundle_kernel.py`
- `tests/test_prepare_eval36_bundle_kernel.py`
- this loop record and the corrected bundle runbook/protocol

The preparer pins the exact packer and CRLF manifest, uses reviewed zlib-9
streams, emits one 254,096-byte Python script with a normalized self-hash, and
emits a closed-schema private CPU `kernel-metadata.json`. The generated kernel
has one fixed source mount, one fixed output directory, no argument override,
an 8,252,100,608-byte free-space gate, exact 15-archive rehash/seal, and a
canonical `KERNEL_RESULT.json` written only after PASS conditions hold.

Local staging is fresh/no-clobber under ignored
`outputs/local/eval36_kernel/<run-id>/`; `READY.json` is published last and
binds the two-file package and staging receipt.

## 5. Tests and current verdict

Final local results before staging:

- new preparer suite: `22 passed`;
- preparer plus existing bundle/importer suite: `114 passed`;
- complete repository suite: `1,189 passed, 5 skipped`;
- targeted Ruff, format, `py_compile`, and `git diff --check`: PASS;
- `official/` pointer unchanged at
  `075fc5f5a52d11077f9dc2b074644618f26939e2`;
- generated code raw SHA-256
  `aaef03ea29d8fa2692c42041ca54023b529d12a5f5ba5171e4f1b3c49cd30ccb`;
- generated normalized self SHA-256
  `9ed21a22c15a2ddd1052a9608ac3f7ef5c6c02cb33a05dbba175d8e524e03271`;
- metadata: 381 bytes, SHA-256
  `ed5500fc5564368d82d7c9c4664df4961b52d89509c31f011ac55270baeda876`.

The preparer tests cover
exact embedded-byte round trip, self-hash/newline/BOM/append drift, a resealed
payload mutation, fixed paths/no argv override, closed metadata, fresh staging,
symlink/hardlink input rejection, package/receipt/output membership replacement,
failed PASS/READY publication, bounded secret-free failure output, the generated
`_run()` success path, output schema/type/extra-file rejection, and an offline
Kaggle client request capture proving exact script text and private CPU flags.

Independent post-change security re-review verdict: **SHIP to one isolated
private CPU run**. Installation remains HOLD until physical output, transfer,
importer, and image-verifier gates pass. Repository-wide Ruff still reports 64
pre-existing findings in untouched exploratory notebooks/scripts; the owned
change set is clean and this unrelated baseline debt is not rewritten here.

## 6. Sequential physical evaluation gate

After the offline verdict changes to SHIP, execute strictly in this order:

1. stage from a clean committed feature branch and independently rehash
   `READY.json`, receipt, script, and metadata;
2. push one private CPU/internet-off kernel with the competition as its only
   source; do not pass an accelerator override;
3. wait for terminal status and retain status/log/runtime evidence;
4. require `COMPLETE`, exactly 15 fixed-size tar files plus one canonical PASS
   receipt, aggregate 6,104,616,960 archive bytes, and no temp/quarantine/extra;
5. download into fresh ignored staging, then independently match every receipt
   SHA-256;
6. run the local importer `--dry-run` with all 15 explicit paths;
7. install only after dry-run PASS, then rerun the exact image verifier;
8. proceed to ST-R3 generation/scoring only after the image receipt is READY.

Timeout, disk exhaustion, mount drift, incomplete saved output, missing PASS
receipt, hash mismatch, or importer failure is HOLD. Do not silently split the
15 roots; a split job is a new contract requiring another review.

## 7. Failure record and next loop

No physical result exists yet. After the run, record the exact kernel version,
session/status, code/metadata/receipt hashes, runtime, output byte inventory,
transfer hashes, importer counts, image-verifier receipt, failure mechanism if
any, the countermeasure, and the next frozen hypothesis here and in
`analysis/experiment_ledger.md`.
