# Eval-36 Zarr bundle runbook

Status: **kernel, transfer, installation, and sealed image READY all PASS**.
Version 1 passed the independent archive/importer gates on 2026-09-04, and the
committed verifier then passed a direct full-data run plus independent complete
inventory rehash. ST-R3 generation retains its separate sandbox, image-only
view, provenance, runtime, and memory gates.

This workflow replaces 1,487 individual competition downloads with 15
uncompressed deterministic USTAR files. It does not replace or relax the
competition manifest. Never upload credentials, `data/`, or a receipt.

## Fixed production contract

- Competition: `biohub-cell-tracking-during-development`
- `data/manifest.csv` SHA-256:
  `6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4`
- CSV physical line count, including its header: `24887`
- Each selected root: exactly `102` regular payload files
- All 15 roots: `1530` payload files and `6,103,118,971` payload bytes
- Exact aggregate USTAR size from the pinned manifest and canonical packer:
  `6,104,616,960` bytes
- Output: one uncompressed `<root>.tar` per root, with 102 payload members and
  exactly one `__eval36_bundle_manifest__.json` member
- Publication and installation are no-overwrite. Existing wrong files are a
  `HOLD`; they are never repaired or replaced by these scripts.
- Source payloads, archives, destination files, temporaries, and receipts must
  be single-link regular files. Every path component is traversed from a held
  directory descriptor with no-follow semantics; a symlink or membership swap
  fails closed.
- The pinned CSV is likewise opened as a stable, bounded, single-link regular
  file through a held parent descriptor before its exact hash and line count
  are accepted.

The archive payload total is intentionally larger than the 1,487-file local
shortfall: the 15 complete roots contain 1,530 files, including 43 already
present locally. Packing complete roots keeps the CSV-derived member contract
simple and independently verifiable; the importer hashes and skips those 43
only when their bytes already match exactly.

The fixed roots are:

```text
6bba_09961292 6bba_0e7c0d07 6bba_12665c0e 6bba_1d0d8384
6bba_207c6aaf 6bba_20852818 6bba_2312ac41 6bba_268e1230
6bba_2819ca14 6bba_32db13fc 6bba_337b1b3a 6bba_3abfe10a
6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
```

The exact expected tar sizes in that same root order are:

```text
400179200 432660480 358236160 420177920 392263680
379023360 389611520 339527680 329328640 477716480
459724800 539504640 364922880 443351040 378388480
```

These sizes include canonical USTAR headers, the per-root canonical embedded
manifest (expected JSON payload size `14,458` bytes), the two end blocks, and
the unique minimal padding to a 10,240-byte USTAR record boundary. Any archive
or aggregate size mismatch is `FAIL`, even if all extra bytes are zero.

## Private Kaggle CPU preparation

The user has standing authority for a necessary gate-passing private run. The
only accepted package is generated from a clean committed feature branch:

```bash
.venv/bin/python scripts/prepare_eval36_bundle_kernel.py \
  --output-dir outputs/local/eval36_kernel/<fresh-run-id>
```

The fresh staging directory must contain `READY.json`,
`STAGING_RECEIPT.json`, and a `package/` directory containing exactly:

```text
eval36_bundle_kernel.py
kernel-metadata.json
```

The script embeds zlib-compressed byte-exact copies of the reviewed packer and
the CRLF manifest. Kaggle CLI 2.2.4 uploads only this single UTF-8 code file;
there is no sibling input dataset. Metadata is fixed to private CPU, internet,
GPU, and TPU disabled, one competition source, and no dataset/kernel/model
sources. Do not pass `--accelerator` or otherwise override metadata.

The only accepted competition mount is the path established by prior physical
kernel logs:

```text
/kaggle/input/competitions/biohub-cell-tracking-during-development
```

The generated script has no arguments, mount discovery, fallback, or root
selection. It creates fresh `/tmp/eval36-runtime` and
`/kaggle/working/eval36-bundles`, requires at least 8,252,100,608 free bytes,
loads the embedded packer under a non-main registered module, and invokes all
15 production roots once.

Before push, independently parse and rehash READY, receipt, script, and
metadata. Their hashes, feature-branch HEAD, exact two-file package inventory,
tool versions, and fixed metadata must agree. Then push the package directory
without an accelerator override. Record returned kernel version and URL.

A successful run requires all of the following, not merely a PASS file:

- terminal Kaggle state `COMPLETE` and no user traceback/stderr failure;
- stdout is the same one-line canonical PASS JSON as saved
  `eval36-bundles/KERNEL_RESULT.json`;
- saved output contains exactly the fixed 15 `.tar` files and that receipt;
- every root byte count equals the ordered values above and their sum is
  `6,104,616,960`;
- no pending, temporary, quarantine, missing, duplicate, or extra output;
- every downloaded tar SHA-256 matches the ordered receipt record.

The kernel writes the receipt to a non-PASS pending name, validates it and all
archives, rechecks script and output membership, then uses one atomic
no-replace rename as the PASS commit point. A missing final receipt remains
HOLD. If packing fails synchronously, the packer rolls back archives it owns;
a SIGKILL, timeout, disk error, or output-save failure can still leave partial
bytes and is always HOLD. Do not silently split roots or weaken checks.

## Local verification and installation (after verified transfer)

Place only the explicitly named downloaded `.tar` files in a staging
directory outside `data/`. Do not rename an archive: its basename must be the
embedded root plus `.tar`. Confirm the repository manifest pin independently:

```bash
shasum -a 256 data/manifest.csv
wc -l data/manifest.csv
```

First perform a non-mutating verification. This does not create the downloader
lock, destination directories, files, or receipts:

```bash
PYTHONPATH=. python scripts/import_eval36_zarr_bundles.py \
  --dry-run \
  /absolute/staging/6bba_09961292.tar \
  /absolute/staging/6bba_0e7c0d07.tar
```

List all 15 archive paths for the complete import. Never use a glob whose
expansion was not printed and reviewed. A successful dry run returns canonical
JSON with `status: "PASS"`, `installed: 0`, `receipt: null`, and counts of
validated missing and skipped exact files.

For installation, first create a dedicated receipt directory outside `data/`
and ensure it and all ancestors are real directories. Then remove `--dry-run`
and add the receipt directory:

```bash
mkdir -p artifacts/eval36_bundle_receipts
PYTHONPATH=. python scripts/import_eval36_zarr_bundles.py \
  --receipt-dir artifacts/eval36_bundle_receipts \
  /absolute/staging/6bba_09961292.tar \
  /absolute/staging/6bba_0e7c0d07.tar
```

Again, list all 15 explicitly for the complete import. The importer first
validates every archive and payload, then takes `data/.download_data.lock`,
rechecks archive identity, and installs missing files through verified
same-directory temporaries and no-clobber links. A crash can leave only exact
published files and can be resumed with the same command. Preserve the
canonical receipt and stdout result.

Validation requires the exact payload order from the pinned CSV, the embedded
manifest last, zero member padding, two zero terminator blocks, and the unique
minimal 10,240-byte record padding. Archive, data-root, destination-parent, and
receipt directory membership are rechecked through held descriptors around
publication. An fsync failure after an exact destination rename is `HOLD`, not
`FAIL`; the exact file is left for a later hash check and parent-directory fsync.
Receipt publication instead rolls its claimed PASS name back (or quarantines
it) before reporting a durability ambiguity.
Production archive sizes are rejected before parsing unless they are one of the
15 pinned sizes; all modes also cap archive bytes and member count before any
payload copy, so sparse/oversize and excessive-member inputs fail without
expansion.

## Version 1 physical receipt (2026-09-04)

- Kernel: `taichiiiii/biohub-eval36-bundle-packer`, version 1, private CPU,
  internet/GPU/TPU disabled, terminal `COMPLETE`.
- Canonical PASS stdout time: `354.311787647` seconds; notebook export complete:
  `362.072439612` seconds.
- `KERNEL_RESULT.json` SHA-256:
  `f7f4bc7759dae375283d5e32fc5f3f46a26af9dc53b84fe0d240a15b5f1f94d0`.
- Retained log SHA-256:
  `ea552c218ebc3a3f02986b1407febb241c5ec08bf90e0ff137c5843be6b6102a`.
- Downloaded archive count/bytes: 15 / `6,104,616,960`; every physical size
  and SHA-256 matched the receipt in an independent full rehash.
- Dry-run: `installed=0`, `skipped=43`, `validated=1487`.
- Install: `installed=1487`, `skipped=43`, `validated=1530`.
- Import receipt: 248,372 bytes, SHA-256
  `0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570`.
- Final path/size tree gate: 36 roots / 3,672 files /
  `15,932,872,938` bytes. Independent full decode: 3,600 chunks /
  `30,198,988,800` bytes, binding-order SHA-256
  `635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646`.

Do not use the Kaggle CLI 2.2.4 `kernels files` reported size field as evidence:
for this run it returned anomalous 894/895-byte values for every saved output.
Use downloaded physical sizes plus the receipt and rehashes. Do not push a
second kernel version merely to inspect history; these CLI endpoints are
latest-version views.

## Image READY receipt (2026-09-04)

The authoritative latest direct run is:

```text
outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/
```

- verifier commit: `2877f285c084e114eb2997134f73183e4f8e8fcc`;
- verifier bytes/SHA-256: 46,060 /
  `fa69202ed0438ea74bd5f0ec4768653de31d53d11590c1b90974b7e81dd3e6b4`;
- READY bytes/SHA-256: 1,431 /
  `8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e`;
- READY content digest:
  `2211abec541bc31df2f31aacf1575c065025f0aa143147c3df07b4ece2b3214a`;
- inventory bytes/SHA-256: 580,155 /
  `efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714`;
- direct verifier exit: 0; observed wall about 37.25 seconds on a warm cache;
- independent inventory rehash: all 3,672 files and `15,932,872,938` bytes,
  8.113 seconds warm-cache, with exact SHA/size/identity and start/end tree
  equality; no GT `.geff` content was opened.

An earlier valid PASS receipt is retained in the sibling
`20260904T220629+0900_2877f28` directory, but its `/usr/bin/time -l` parent
returned 1 after child completion because sandboxed `sysctl kern.clockrate`
was unavailable. Do not use that wrapper exit as the final run. The direct
receipt above is the authoritative latest verifier evidence.

## Stop conditions

- `FAIL`: archive, manifest, pin, path, member, payload, or argument validation
  failed. Do not retry with weakened checks.
- `HOLD`: local state needs review (lock contention, unsafe ancestor, existing
  wrong/special/multiply-linked destination, publication race, or unsafe
  receipt path), including any post-rename fsync ambiguity. Do not delete or
  replace the affected path as part of this workflow.
- Any mismatch between the Kaggle packer result, transferred archive hashes,
  importer result, receipt, or the fixed root list remains `HOLD`.

Escalate with the exact canonical result, archive hash, path, and immutable job
metadata. Do not make a network request, rerun Kaggle, publish, or modify a
destination until the discrepancy has been independently reviewed.
