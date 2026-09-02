# E17 ranker artifact/source acquisition runbook

Updated: 2026-09-02 (Asia/Tokyo)

Status: **HOLD — acquisition is forbidden during the active Kaggle HTTP 429 cooldown; no local artifact has been verified**

This is the fail-closed acquisition and publication procedure for the frozen E17
association-ranker input to `e23_e17_ranker_tiebreak_v1`. It does not authorize a
Kaggle request, download, kernel run, submission, implementation, inference, or
metric readout. In particular, every network/API/download command below is a
**future command proposal**, not a command executed while preparing this document.

The evidence boundary is the frozen E17 design, the experiment ledger, the public
ranker entry in the candidate landscape, and the sealed integrity cell in
`notebooks/pub923_repro/pub923_repro.ipynb`. Values not present in those sources
are not filled in from memory.

## Frozen identities and exact payload allowlist

The only acceptable ranker dataset identity is:

| Field | Required value |
|---|---|
| owner/slug | `pilkwang/biohub-local-association-ranker-unet300-v1` |
| Kaggle dataset ID | `11102521` |
| immutable dataset-version source ID | `17840600` |

The downloaded payload allowlist is exactly these three relative regular files.
Names are case-sensitive; directories are permitted only as parents. Any fourth
file, archive member, symlink, hardlink, device, FIFO, socket, path traversal,
absolute path, duplicate normalized path, or case-fold collision is a hard HOLD.

| Relative file | Required SHA256 |
|---|---|
| `ASSOCIATION_RANKER_MANIFEST.json` | `b1f80944ea02ad103bb938eedc7126c050e9ce345327dc33df677440be14f407` |
| `model/local_association_ranker.pt` | `b49a9ab4228daba63d31056ae5beef9fd3e8bcd3ba26d9f57a45ef828d4fb4b8` |
| `model/model_info.json` | `ba8d338f4eb0b8cfa9bcffc71f3619353ed3dc297b091eebaff23e5d266a96a7` |

The repository does not record authoritative byte sizes for these three files.
Do not invent them. Before download, obtain the file list and byte sizes from the
same metadata response proven to identify dataset `11102521` and source version
`17840600`; pin that response by SHA256 in the acquisition record. Each staged
file must be non-empty and must equal both its metadata byte size and the SHA256
above. Hash agreement does not waive a size mismatch, and size agreement does not
waive a hash mismatch.

## Version pinning is a two-identifier gate

The installed Kaggle CLI 2.2.4 help does not advertise a version option. Its local
implementation nevertheless accepts the dataset string
`owner/slug/<dataset_version_number>` and sends the final component as
`dataset_version_number`. The known immutable value `17840600` is documented in
this repository as a **dataset-version source ID**, not as that CLI version
number. Their equality is not established and must not be assumed.

Therefore all of the following are required before acquisition:

1. A trusted Kaggle metadata/API response must bind owner/slug, dataset ID
   `11102521`, immutable source version ID `17840600`, and the CLI/API dataset
   version number in one unambiguous record.
2. Save the redacted raw response, its SHA256, retrieval UTC timestamp, CLI/API
   version, and the three exact file sizes. The response must contain no token,
   cookie, authorization header, signed download URL, or query credential.
3. Set `KAGGLE_DATASET_VERSION_NUMBER` only from that record. It must be a decimal
   integer and must never be populated with `17840600` merely because that value
   is available.
4. List files using the version-qualified dataset string and require the exact
   three-file allowlist and metadata sizes before downloading anything.

If the available endpoint cannot return the dataset ID and source version ID, if
the CLI version-number mapping cannot be proven, or if the response describes
`latest` rather than the pinned source, the result is HOLD. Hashes remain a final
identity gate, but they are not permission to bypass provenance/version checks.

After the active 429 cooldown has ended and a fresh authorization has been given,
the proposed version-qualified commands are:

```zsh
SLUG='pilkwang/biohub-local-association-ranker-unet300-v1'
: "${KAGGLE_DATASET_VERSION_NUMBER:?set only from verified source-ID metadata}"
PINNED_DATASET="$SLUG/$KAGGLE_DATASET_VERSION_NUMBER"

.venv/bin/kaggle datasets files "$PINNED_DATASET" --format json
.venv/bin/kaggle datasets download "$PINNED_DATASET" \
  -f ASSOCIATION_RANKER_MANIFEST.json -p "$FRESH_PAYLOAD"
.venv/bin/kaggle datasets download "$PINNED_DATASET" \
  -f model/local_association_ranker.pt -p "$FRESH_PAYLOAD"
.venv/bin/kaggle datasets download "$PINNED_DATASET" \
  -f model/model_info.json -p "$FRESH_PAYLOAD"
```

`FRESH_PAYLOAD` must be an absolute, newly created directory under the intended
publish filesystem. Do not use `--unzip`, `--force`, a pre-existing directory,
the final path, or an unqualified `owner/slug`. Capture stdout/stderr only after
redaction. If this CLI flattens a requested nested filename or returns an archive,
stop and use a fresh staging directory with an explicitly reviewed extractor; do
not rename a surprising result into compliance.

## Ordered acquisition and atomic publication

The transaction order is fixed. Skipping or reordering a gate gives HOLD.

1. **Cooldown and authority.** During the 2026-09-02 HTTP 429 cooldown recorded in
   `eval36_image_resume_runbook.md`, send no Kaggle request at all, including a
   metadata call, file-list call, or single-file probe. After cooldown, require
   explicit authority for the network operation, no other downloader/Kaggle
   child, and a fresh preflight. A new 429 immediately stops all requests and
   restarts cooldown; no automatic retry is allowed.
2. **Fresh same-filesystem staging.** Create a unique wrapper beside the intended
   publish parent, with `payload/`, `evidence/`, and `RECEIPT.json.tmp`. Record the
   staging path without placing secrets in its name. It must not exist before this
   attempt. Never reuse a failed staging tree.
3. **Path/type gate before and after each write.** Walk from the staging wrapper
   with `lstat`, not path-following queries. Reject symlink ancestors and reject
   every non-directory parent or non-regular payload leaf. Resolve each lexical
   relative path and require it to remain below `payload/`. Reject special files,
   links (including any regular file with `st_nlink != 1`), traversal, duplicates,
   extras, and unexpected archive members before opening payload bytes.
4. **Size then hash.** Require the exact allowlist, non-zero sizes, equality to the
   pinned metadata sizes, then the three fixed SHA256 values above. Hash files by
   streaming bytes from regular-file descriptors; reject a type/inode/size change
   between pre-hash and post-hash `fstat` checks.
5. **Canonical receipt.** Only after every audit below passes, write a UTF-8 JSON
   receipt with duplicate keys impossible, `sort_keys=True`, separators `(',',
   ':')`, and one trailing newline. Required fields are receipt schema version,
   verdict `READY`, owner/slug, dataset ID, source version ID, verified dataset
   version number, redacted metadata SHA256 and retrieval time, CLI/API version,
   exact file path/size/SHA256 triples, license evidence, manifest/model-info
   schema results, feature-contract result, state-dict result, support-source
   results, verifier source SHA256, staging filesystem/device, and timestamps.
   Hash the completed receipt and record that digest in the operator log; do not
   make the receipt self-referential.
6. **Atomic publish.** `fsync` each file, both payload parent directories, the
   receipt, the staging wrapper, and the final publish parent. The final publication unit is the wrapper
   containing `payload/`, `evidence/`, and `RECEIPT.json`; atomically rename that
   wrapper within the same filesystem to:
   `outputs/kaggle/e17_artifacts/pilkwang/biohub-local-association-ranker-unet300-v1/17840600/`.
   After rename, `fsync` the final publish parent again before recording success.
   The consumer artifact root is its `payload/` child. The final path and every
   ancestor must be real directories, not symlinks.

The final path must be absent immediately before rename. If it already exists,
do not overwrite, merge, delete, move, or repair it. Validate it independently:
an identical READY receipt and all gates permit read-only reuse; any difference is
HOLD and requires a new versioned destination chosen by a reviewed runbook change.
Atomic rename failure leaves the old published state untouched and is HOLD.

## License, manifest, schema, and state-dict audit gates

All gates are conjunctive. “Not stated”, “not found”, parse failure, warning-only
fallback, or a verifier exception means HOLD.

- **License:** record the pinned Kaggle metadata license and any license/provenance
  fields in both JSON payloads. Require them to agree where both speak, retain the
  license text/reference in redacted evidence, and obtain the project’s explicit
  acceptance for the intended local evaluation/Kaggle use. No license value is
  asserted by this runbook because none is present in the inspected repository.
- **Strict JSON:** parse both JSON files as UTF-8 with duplicate-key rejection.
  Reject trailing content, non-finite numbers, unknown schema/model versions,
  missing required fields, and any manifest/model-info disagreement. Do not add
  permissive defaults.
- **Feature contract:** copy the manifest-declared feature list verbatim. Require
  exactly 22 unique ordered names and validate every declared dtype, unit,
  transform, normalization statistic, missing-value rule, coordinate convention,
  candidate-radius convention, architecture, and scalar-output semantics. The
  repository currently has none of these locally verified; absence is HOLD.
- **State dict:** load through the safe weights-only path on CPU. Require the exact
  manifest-declared architecture and exact keys, tensor shapes, and dtypes with
  strict loading. Prove the first layer consumes 22 values and the output has the
  declared scalar shape/semantics. `strict=False`, pickle-capable fallback,
  renamed/dropped keys, reshaping, inferred architecture, or invented imputation
  is forbidden. Reject NaN/Inf and outputs outside the declared domain.
- **Test vectors:** run manifest-provided vectors if present. If absent, record
  that provenance limitation and use locally constructed vectors only for
  shape/order/finiteness; they cannot establish semantic calibration.

## Exact support source and Python-manifest verifier

The ranker payload alone does not authorize feature extraction. The inference
support source must be acquired independently from the same pinned support-pack
provenance used by `pub923_repro`; it is not a fourth ranker payload file. Before
any dynamic patch or feature extraction, require:

```text
scripts/predict_unet_transformer.py
SHA256 c44e771ba5980b820f93091e03a303c25dfe8f3232e501f54dc9565731c234b9
```

The sealed notebook also defines the complete support-repository Python allowlist:

| Relative Python source | SHA256 |
|---|---|
| `scripts/augmentations.py` | `13db09817bf492f8d0f710a0a4d09776320b262060167055090a303fc6057f4e` |
| `scripts/dataspec.py` | `e69bf952fb985477ac50ff8598a35020c95d20a035a09b81ab4056e655dd311f` |
| `scripts/evaluate.py` | `614813cc51c3581c6ccda4bb20725a19da8ecac4a27620654bfca58319cffa3c` |
| `scripts/predict_unet_transformer.py` | `c44e771ba5980b820f93091e03a303c25dfe8f3232e501f54dc9565731c234b9` |
| `scripts/train_unet_transformer.py` | `c4f6317736bb3bb1ec8f3f6e9a6d935a463e3f0f1f685481b2d13218d35dc9ea` |
| `src/biohub_tracking/__init__.py` | `26a18d8da84e40da73281a48ebc3017d847a2e57431ab63e8629d2109e6e8571` |
| `src/biohub_tracking/division_metrics.py` | `d1cf1e0a43009d02174f1699ce2aa28458a2220ac4b521731d3bcf31cf8c76be` |
| `src/biohub_tracking/img_proc.py` | `00e8ef0adc8b39f1aaaa547ea6197b906bf9e8c009e339d3e95f8f8dbf31be3f` |
| `src/biohub_tracking/io.py` | `efae135b088cecaab463d889f16c885ef6da3ad27b0747327d8ddc28d866b7bd` |
| `src/biohub_tracking/metrics.py` | `31baf45b54c78f68bab4f65dd8f4b38bca702abb644171c6df7c46cdeef55d83` |
| `src/biohub_tracking/models/__init__.py` | `ab7587ef79856bae50d24b62e5805092d0459ee1c586522b763f9ef70c093e1d` |
| `src/biohub_tracking/models/simple_node_transformer.py` | `b97209edeb03840e80d903e3e2a8c81c520641c8ef343f6ca2904d0f80db064e` |
| `src/biohub_tracking/models/temporal_unet.py` | `d809c35d42f504161074ddeaaa7aee5b407e5bca7f9b4e1d5f9b2ff345666cac` |

Require the materialized `*.py` relative-name set to equal this set exactly and
each digest to match. Then construct the Python-manifest bytes by sorting relative
paths lexicographically and concatenating one line per file exactly as:

```text
<lowercase_sha256><two ASCII spaces><POSIX relative path><LF>
```

The SHA256 of those bytes must be exactly:

```text
978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029
```

The verifier itself must be hash-pinned in the canonical receipt. It must use
`lstat`/`fstat`, reject symlinks and special files, compare the exact name set
before hashing, and run before any sealed dynamic inference patch. Acquiring only
`predict_unet_transformer.py`, reproducing a semantically similar file, or
recomputing a new expected manifest is HOLD.

## Pipeline boundary: what this artifact cannot do

READY means only “identity and contracts are safe to consume”; it does not mean
the experiment is ready. E23 Phase 3/4 parity and off/dry-run identity remain
separate mandatory gates.

The ranker may run only after unchanged E23 bidirectional association probability
conversion and candidate thresholding have produced the complete pre-ILP
candidate rows, and before unchanged graph construction and ILP. It must not run
on solved GEFF edges, in `src/biohub/public_postproc/`, during motion relink,
after safe division, or after any other post-GEFF stage. Existing GEFFs contain
only selected solved edges and cannot reconstruct rejected candidates or the 22
features. No feature inference, reverse engineering, downstream approximation,
global rescore, candidate add/delete, or global veto is allowed.

## READY/HOLD decision matrix

| Condition | Verdict |
|---|---|
| Active 429 cooldown, or any new 429 | HOLD; zero further requests |
| Missing authority, auth/DNS/API ambiguity, or secret-bearing evidence | HOLD |
| Dataset ID/source version ID/version-number binding absent or inconsistent | HOLD |
| File-list version not pinned, allowlist mismatch, or authoritative size absent | HOLD |
| Path escape, symlink, hardlink, special file, duplicate, extra, or type race | HOLD |
| Any size/SHA256 mismatch | HOLD |
| License absent, inconsistent, or not accepted for intended use | HOLD |
| JSON/schema/22-feature/model-info/state-dict/test-vector gate fails | HOLD |
| Support Python name/hash set or manifest SHA differs | HOLD |
| Existing destination differs, or atomic/fsync operation fails | HOLD |
| Every acquisition, audit, receipt, and publish gate passes | Artifact **READY** only |
| Artifact READY but E23 parity/off/dry-run boundary gate is open | Experiment HOLD |

There is no WARN-and-continue state and no partial READY.

## Secret redaction and recovery semantics

Never print or persist `KAGGLE_KEY`, OAuth/access/refresh tokens, cookies,
`Authorization` headers, credential files, signed URLs, query strings, or full
environment dumps. Do not use `set -x`, `env`, `printenv`, `kaggle config view`,
or `cat` on credential/config files. Logs may retain only command shape, redacted
endpoint identity, HTTP class/status, timestamps, byte counts, and content hashes.
Apply redaction before writing evidence; if uncertain, discard the log and HOLD.

Failures are recoverable only by preservation and a new attempt:

- Stop the current attempt on the first failed gate. Do not load the model or run
  feature extraction from a failed/partial tree.
- Do not delete, move, truncate, overwrite, merge, or repair existing staging or
  published files. Mark a failed staging wrapper read-only if safe, record its
  path and failure class outside the payload, and create a distinct fresh staging
  wrapper for a later authorized attempt.
- A transport interruption, timeout, DNS/auth failure, or 429 never resumes into
  the same staging wrapper. 429 additionally forbids even probes until cooldown
  and fresh preflight.
- A crash before atomic rename leaves no published version. A crash after rename
  is recovered by read-only verification of the final wrapper, receipt, exact
  payload, and directory fsync evidence. Missing or inconsistent evidence is
  HOLD; never “complete” publication by copying loose remnants into place.
- The immutable production fallback remains exact E23. Artifact HOLD or experiment
  HOLD must not be converted into a fallback model, inferred features, permissive
  state load, or post-GEFF ranker.

## Sources rechecked

- `analysis/e17_ranker_e23_design.md`: artifact identity/hashes, strict feature
  and state-dict contract, pre-ILP boundary, and current HOLD.
- `analysis/gold_candidate_landscape.md`: dataset `11102521`, source version
  `17840600`, exact three hashes, and public-ranker provenance.
- `analysis/experiment_ledger.md`: E17 preregistration and same-weight pipeline
  A/B boundary.
- `notebooks/pub923_repro/pub923_repro.ipynb`: exact support source hash, complete
  13-file Python allowlist, and canonical Python-manifest hash/construction.
- `scripts/download_data.py` and `analysis/eval36_image_resume_runbook.md`:
  regular-file/symlink/atomic-staging precedent, failure classes, secret hygiene,
  and the active 2026-09-02 HTTP 429 safe-stop state.
- installed Kaggle CLI 2.2.4 local help/source: unadvertised third dataset-string
  component is sent as `dataset_version_number`; it does not prove equivalence to
  the recorded source version ID.
