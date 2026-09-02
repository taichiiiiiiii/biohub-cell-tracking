# Eval-36 Zarr bundle runbook

Status: **HOLD for production use**. This implementation is locally tested,
but an independent SOL audit, a post-cooldown Kaggle preflight, a private CPU
runtime/output-size check, transfer, and local verification must all pass
before installation is authorized.

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

## Private Kaggle CPU preparation (future authorized action)

Create a new private CPU notebook only after explicit approval. Attach the
competition data and a private, hash-checked input containing the pinned CSV
and the reviewed `pack_eval36_zarr_bundles.py`. Do not add a Kaggle API token.
Do not enable internet. Record the exact script git blob/hash and every input
dataset version in the experiment log.

Before packing, confirm the mount paths in the private notebook. Then run the
packer once, with a fresh empty output directory:

```bash
python /kaggle/input/eval36-packer/pack_eval36_zarr_bundles.py \
  --manifest /kaggle/input/eval36-packer/manifest.csv \
  --source-data /kaggle/input/biohub-cell-tracking-during-development \
  --output-dir /kaggle/working/eval36-bundles
```

Do not pass `--root` for the production job: the default is the exact fixed
15-root set. A successful stdout value is one canonical JSON object with
`status: "PASS"`, bounded archive paths, byte counts, and SHA-256 values.
Any stderr `FAIL`, traceback, missing archive, extra archive, or reused output
directory stops the workflow. Preserve the JSON result alongside the Kaggle
job metadata, but do not edit it.

Before saving output, check that there are exactly 15 `.tar` files, no `.tmp`
files, every byte count equals the ordered values above, their sum is exactly
`6,104,616,960`, and every SHA-256 equals the packer result. Record CPU
runtime, peak disk use, and total output bytes. Saving or downloading the
private output is a separate explicitly authorized step.

## Local verification and installation (after authorized transfer)

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

## Stop conditions

- `FAIL`: archive, manifest, pin, path, member, payload, or argument validation
  failed. Do not retry with weakened checks.
- `HOLD`: local state needs review (lock contention, unsafe ancestor, existing
  wrong/special/multiply-linked destination, publication race, or unsafe
  receipt path). Do not delete or replace the reported path as part of this
  workflow.
- Any mismatch between the Kaggle packer result, transferred archive hashes,
  importer result, receipt, or the fixed root list remains `HOLD`.

Escalate with the exact canonical result, archive hash, path, and immutable job
metadata. Do not make a network request, rerun Kaggle, publish, or modify a
destination until the discrepancy has been independently reviewed.
