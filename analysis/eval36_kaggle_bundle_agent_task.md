# Eval-36 Kaggle bundle/import implementation task

## Outcome

Replace 1,487 per-file competition API downloads with an offline-prepared
Kaggle CPU job that emits one deterministic tar archive for each of the 15
incomplete eval-36 Zarr roots, plus a local fail-closed importer. This task is
implementation and local testing only. It must not make a network request,
push or run a Kaggle kernel, download an output, or submit.

The authoritative local manifest is `data/manifest.csv`: 24,887 lines,
SHA-256
`6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4`.
Each selected root has exactly 102 expected regular files. The 15 roots are:

```text
6bba_09961292 6bba_0e7c0d07 6bba_12665c0e 6bba_1d0d8384
6bba_207c6aaf 6bba_20852818 6bba_2312ac41 6bba_268e1230
6bba_2819ca14 6bba_32db13fc 6bba_337b1b3a 6bba_3abfe10a
6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
```

## Owned files

Create only these files unless a clearly necessary test fixture is added:

- `scripts/pack_eval36_zarr_bundles.py`
- `scripts/import_eval36_zarr_bundles.py`
- `tests/test_eval36_zarr_bundles.py`
- `analysis/eval36_kaggle_bundle_runbook.md`

Do not edit `official/`, `data/manifest.csv`, `scripts/download_data.py`, or
the existing resume runbook.

## Packer contract

The packer is copied into a future private Kaggle CPU kernel and reads the
competition mount plus the pinned CSV manifest. It must:

1. default to the exact 15-root set above and reject duplicates, unknown
   roots, unsafe names, and any manifest hash/row-count/file-set drift;
2. require each source ancestor to be a real directory and every source leaf
   to be a non-symlink regular file with the exact manifest size;
3. create exactly one uncompressed deterministic USTAR archive per root, with
   no overwrite/reuse of an existing output and no timestamp, owner, platform,
   or traversal-dependent bytes;
4. sort the 102 logical paths bytewise, use names relative to the data root,
   and normalize tar metadata (`mtime=0`, `uid=gid=0`, empty owner/group,
   fixed regular-file mode);
5. hash every payload while it is written and reject short reads, byte-count
   drift, source identity/stat changes, or a second-view digest mismatch;
6. include one canonical strict-JSON manifest member in the same tar. It binds
   schema version, competition slug, pinned CSV SHA, root, ordered exact file
   paths, sizes, and SHA-256 values. The tar member set is exactly those 102
   payload files plus that manifest—no directories or other members;
7. publish via a fresh same-filesystem temporary file, fsync, and a no-clobber
   final link/rename. A failure leaves no claimed final archive;
8. emit a bounded, credential-free result containing archive path, bytes, and
   SHA-256. Repeated packing of identical fixtures must yield byte-identical
   archives.

The embedded manifest need not recursively contain the archive SHA. Do not
compress: avoiding decompressor ambiguity and CPU cost is intentional.

## Local importer contract

The importer operates only on explicitly named local tar paths and `data/`.
It must:

1. independently pin the CSV SHA/row count and rebuild the exact expected root
   file map; never trust paths, counts, sizes, or hashes solely because the
   embedded manifest states them;
2. open each archive as a non-symlink, single-link regular file and retain one
   stable descriptor; reject identity/stat changes before any data mutation;
3. strict-parse the unique canonical manifest member (UTF-8, duplicate-key and
   NaN/Inf rejection), require its root to match the archive selection, and
   compare its 102 paths/sizes exactly with the CSV-derived set;
4. reject duplicate members, absolute paths, `..`, backslashes, NUL, PAX/GNU
   surprises, sparse files, links, devices, FIFOs, directories, or any member
   set/type/size mismatch;
5. complete a first full pass that hashes all 102 tar payloads against the
   embedded manifest before creating or modifying anything under `data/`;
6. acquire the same `data/.download_data.lock` protocol used by the downloader,
   then recheck the archive identity before installation;
7. reject every symlink/non-directory ancestor. For an existing destination,
   require a single-link regular file whose size and SHA match the bundle and
   skip it. Never replace an existing path, even if it is wrong;
8. write missing files through exclusive same-directory temporary regular
   files, verify bytes/hash again, fsync, and publish without clobbering. A
   crash may leave safely resumable exact files but must never expose an
   unverified final file;
9. reverify archive identity and every installed/skipped destination at the
   end, then write a canonical receipt outside the tracked data payload. The
   receipt must distinguish validated, installed, skipped, and HOLD/FAIL;
10. reject two archives claiming the same root and reject roots outside the
    exact 15-root set. Dry-run/verify-only must perform no data mutation.

Do not extract with `tarfile.extract`, `extractall`, a shell `tar`, or any API
that applies archive metadata or links to the destination tree.

## Tests and handoff

Use tiny synthetic manifests/source trees, while making manifest pins
injectable only through explicit test parameters—not permissive production
CLI flags. Required adversarial tests include traversal and alias paths,
duplicate manifest/member keys, wrong CSV pin/count/root/set/size/hash,
symlink/hardlink/special archive and destination cases, corrupt/truncated tar,
source/archive mutation, wrong existing destination, no-clobber race,
mid-write failure/resume, lock contention, deterministic two-run bytes, and
proof that validation failure makes zero data-tree mutations.

Run focused pytest, the full repository suite with `PYTHONPATH=.`, targeted
Ruff and format checks, `py_compile`, `git diff --check`, and confirm
`official/` is clean. Commit only the owned files on the isolated branch and
report hashes and residual risks. Production use remains HOLD until an
independent SOL audit, a post-cooldown Kaggle preflight, a private CPU runtime
and output-size check, and local archive verification all pass.
