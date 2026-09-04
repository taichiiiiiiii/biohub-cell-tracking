# Eval-36 bundle recovery loop

Updated: 2026-09-04 (Asia/Tokyo)

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

## 2. Pre-recovery cause diagnosis (2026-09-02 snapshot)

- Local eval-36 images were 21/36 roots complete and 2,185/3,672 exact files.
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

## 5. Tests and pre-run verdict

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

The independent post-change security re-review verdict was **SHIP to one
isolated private CPU run**. Installation was held until physical output,
transfer, importer, and image-verifier gates passed. Repository-wide Ruff still
reports 64
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

## 7. Physical result, residual hold, and next loop

The one permitted physical run is complete and the transport hypothesis passed:

- private CPU/internet-off kernel `taichiiiii/biohub-eval36-bundle-packer`,
  version 1, reached terminal `COMPLETE`;
- canonical PASS stdout appeared at `354.311787647` seconds and notebook export
  finished at `362.072439612` seconds; stderr contained only two third-party
  `SyntaxWarning` messages and nbconvert progress, with no user traceback;
- downloaded 2,798-byte `KERNEL_RESULT.json` has SHA-256
  `f7f4bc7759dae375283d5e32fc5f3f46a26af9dc53b84fe0d240a15b5f1f94d0`;
  the retained kernel log SHA-256 is
  `ea552c218ebc3a3f02986b1407febb241c5ec08bf90e0ff137c5843be6b6102a`;
- fresh output contains exactly the 15 fixed archives plus the receipt. An
  independent local rehash matched all 15 receipt SHA-256 values and exact
  aggregate archive bytes `6,104,616,960`;
- the importer dry-run passed with `installed=0`, `skipped=43`,
  `validated=1487`; the no-overwrite install then passed with
  `installed=1487`, `skipped=43`, `validated=1530`;
- canonical import receipt
  `eval36-import-0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570.json`
  is 248,372 bytes and its file SHA-256 is the embedded
  `0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570`;
- the exact final tree gate passed: 36 roots, 3,672 files,
  `15,932,872,938` stored bytes. A full 3,600-chunk decode covered
  `30,198,988,800` decoded bytes; the ST-R3 binding-order digest is
  `635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646`.

The Kaggle CLI 2.2.4 `kernels files` size field reported the same implausible
894/895-byte values for the large saved files, so it is not evidence for this
gate; the downloaded physical `stat`, receipt sizes, and independent hashes are
authoritative. No second kernel version was pushed because the CLI exposes only
the latest version through these status/log/file/output commands.

Independent review found and blocked a path-basis mismatch in the first
verifier draft (`data/train/...` versus image-view-relative
`<stem>.zarr/...`). The fixed verifier binds its inventory to the source
`data/train` image view, ignores rather than reads colocated non-Zarr GT trees,
and requires a later image-only copy to prove content equality rather than
inode equality. It passed 48 focused tests and independent SHIP review, then
was committed at `2877f285c084e114eb2997134f73183e4f8e8fcc` before use.

The first physical invocation emitted PASS and published a valid receipt in
49.87 seconds, but `/usr/bin/time -l` itself returned 1 because sandboxed
`sysctl kern.clockrate` is unavailable. That output is retained but is not the
authoritative latest receipt. The countermeasure was one fresh direct child
invocation without the broken wrapper; it returned 0 and canonical PASS after
about 37.25 seconds at:

`outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/`

The authoritative READY is 1,431 bytes, SHA-256
`8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e`;
its content digest is
`2211abec541bc31df2f31aacf1575c065025f0aa143147c3df07b4ece2b3214a`.
The 580,155-byte inventory SHA-256 is
`efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714`.
An independent read-only pass rehashed all `15,932,872,938` image bytes in
8.113 warm-cache seconds, matched every one of the 3,672 records and both tree
scans, and read no GT bytes. The eval-36 image prerequisite is therefore
**READY**. Creating and proving the distinct image-only execution view remains
an ST-R3 generation prerequisite, not an image-completeness hold.
