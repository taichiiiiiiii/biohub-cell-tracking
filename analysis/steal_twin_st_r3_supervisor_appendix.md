# ST-R3 production supervisor appendix

Updated: 2026-09-02 (Asia/Tokyo)

Status: **`FIXED_FOR_REAUDIT_LOCAL_ONLY`** for the implemented local
child-process, event, staging-validation, sealing, and no-replace publication
surface described here. This is not an ST-R3 generation, feasibility, metric,
adoption, or submission pass. The binding contract remains
[`steal_twin_st_r3_eval_contract.md`](steal_twin_st_r3_eval_contract.md), and
the child remains the interface pinned by
[`steal_twin_st_r3_adapter_appendix.md`](steal_twin_st_r3_adapter_appendix.md).

## Implemented local interface evidence

The supervisor implementation is
`src/biohub/public_postproc/production_supervisor.py`. It deliberately imports
neither the production adapter/pipeline nor evaluator, metric, scorer, or GT
code. Its frozen public types and only runner are:

```text
SupervisorSpec(
  arm_name, geff_dir, test_dir, deepcenter_checkpoint,
  deepcenter_manifest, expected_effective_config_sha256,
  final_dir, timeout_seconds,
)

SupervisorResult(
  success, arm_name, child_pid, staging_dir, final_dir,
  duration_monotonic_ns, exit_code, term_signal,
  ru_maxrss_raw, ru_maxrss_unit, ru_maxrss_bytes,
  failure_type, failure_message, receipt_path,
  failure_evidence_state, failure_evidence_errors, success_scope, holds,
)

supervise_arm(spec: SupervisorSpec) -> SupervisorResult
```

The sole CLI is `scripts/st_r3_supervise_arm.py`. It accepts exactly
`--arm-name`, `--geff-dir`, `--test-dir`, `--deepcenter-checkpoint`,
`--deepcenter-manifest`, `--expected-effective-config-sha256`, `--final-dir`,
and `--timeout-seconds`. It exposes no dataset selector, free profile,
override, child path, output filename, event path, GT, evaluator, score, or
gate input. All three arm names execute the same fixed
`scripts/st_r3_postproc_arm.py` child CLI with the literal ordered EVAL36
sequence.

For each attempt the supervisor creates a unique, never-before-used staging
directory beside an absent final directory and verifies their filesystem
identity. It uses the native `subprocess.Popen` spawn helper with
`close_fds=True`, the event descriptor as the sole `pass_fds` entry, a fresh
session, fixed standard input/output/error, and a fixed allowlisted environment
and argv. It does not call Python-level `os.fork`, including from a
multithreaded parent. The spawned PID is still the direct authoritative exec
PID consumed by `wait4`. Three
concurrent drains prevent stdout, stderr, and the event pipe from blocking the
child. The event bytes must be exactly 72 canonical JSON lines with the child
PID, exact field set, literal dataset order, START/FINISH alternation, sequence,
arm, and strictly increasing monotonic timestamps.

The parent records a monotonic integer child-wall interval and obtains status,
signal, and resource use from `os.wait4`. `ru_maxrss` is recorded as bytes on
macOS and normalized from KiB to bytes on Linux; unknown platforms fail. The
receipt marks this process-only value non-authoritative for the RSS gate
because descendant absence has not yet been audited.

Before publication the supervisor validates canonical `child_result.json`,
the exact registered child artifact set, each regular nonsymlink file's bytes
and SHA-256, and absence of unregistered child files. It checks the fixed
submission essentials (exact UTF-8/LF physical encoding without quoting or
CR/blank lines, header, canonical integers/sentinels, literal dataset
blocks, explicit image bounds, node/edge order and graph integrity), exactly
one stats row for every frozen dataset and the complete child-side raw-stats
conservation contract with the same exact physical encoding, all plan
envelopes and the exact plan manifest, the
complete nested plain `TwinPlan` schema and its graph/decision/counter/debug
invariants, frozen distance/sister/divergence/DeepCenter boundaries,
P/Q-pool and mutual-nearest semantics, the 101-field effective-config
envelope, and the complete strict
DeepCenter receipt. DeepCenter file-stat identity, per-file and aggregate open
counts, registered/chosen basenames, pinned hashes, verified typed configs,
device/dtype, and discrepancy record are bound independently; production
supervision also binds the registered basenames to the two paths in
`SupervisorSpec`. Every accepted SHA-256 spelling is an exact 64-character
lowercase hexadecimal string. The supervisor-owned stdout/stderr partial logs
are explicitly separated from child artifacts.

The six eligibility limits are held in one supervisor map and must equal the
canonical float64 bit tags in every effective config: twin `5.0`, existing
child `10.0`, parent-to-B `8.0`, sister range `[5.5, 11.0]`, and divergence
growth `2.25` micrometres. The DeepCenter `0.12` threshold is likewise bound
to the frozen effective-config value. Candidate geometry uses those same
bindings; the parent limit accepts exactly `8.0` and rejects its next
representable larger float.

Before success, both captured logs and every per-dataset plan/debug JSON byte
pass one explicit safe-text policy: strict UTF-8; printable characters plus LF
and TAB; no case-insensitive credential/auth/bearer/cookie vocabulary; no
standalone NaN/Inf spelling; no Windows path or registered absolute host,
secret, data, or GT prefix; and no dataset-shaped token or GEFF/Zarr basename
outside literal EVAL36. The held-FD publication seal scans the final bytes
again. Unsafe child text is never published. Failed text artifacts are replaced
by a fixed safe marker, unsafe inventory names are digest-redacted, and failure
receipt messages are policy-checked and capped at 512 UTF-8 bytes rather than
copying untrusted text. Stdout and stderr are independently capped at exactly
1,048,576 bytes; overflow closes the drain, causes the parent to kill a
still-running child, fails the run, and replaces both logs with the fixed safe
marker.

The frozen-value decoder independently enforces the producer's bit-exact
special-float labels, complex components, collection uniqueness, dtype and
object-content flags, scalar/array/buffer byte lengths, and structured-field
uniqueness. Per-dataset plan counters are cross-bound to the typed raw-stats
rows for all 36 datasets: baseline requires zero twin/R2 state, dry-run
requires the exact pre-mutation plan counters and no applied/R2 state, and
candidate requires the same pre-mutation counters plus exact accepted
remove/add/mutation counts and plan-snapshot pure node/edge counts.

Every staged regular file is opened with no-follow semantics and must have
`st_nlink == 1`; path identity and FD device/inode/mode/link-count/size/mtime/
ctime are equal before and after each read. Promotion's temporary internal
hard link is immediately reduced back to one link and rechecked. Child hashes
are reverified before and after promotion. After exact event bytes and the
canonical `arm_receipt.json` are fsynced, the supervisor holds an FD for every
file, hashes the complete tree, removes all write bits (`0400` files, `0500`
directories), and rechecks membership, identities, link counts, bytes, child
digests, and receipt inventory immediately before the real no-replace rename.
After rename, it changes the seal's path to the final name and repeats the
held-FD and final-path tree verification before returning success. A failed
postcondition is rolled back with the same no-replace primitive to a fresh
unpredictable `.failed.<uuid>` staging name. If rollback itself fails, the run
still returns failure and truthfully records that the final name remains; it
never claims successful publication. The successful names are:

```text
submission.csv
run_stats.csv
effective_config.json
deepcenter_receipt.json
twin_plans/<sequence>.<dataset>.json
twin_plan_manifest.json
child_result.json
dataset_events.jsonl
arm_receipt.json
supervisor_stdout.log.partial
supervisor_stderr.log.partial
```

The whole directory is published only with Linux
`renameat2(RENAME_NOREPLACE)` or macOS `renameatx_np(RENAME_EXCL)`. An absent or
unsupported no-replace primitive is an explicit publication HOLD/failure; the
implementation does not fall back to an overwriting rename. A child error,
signal, timeout, pipe/event error, validation failure, collision, or publication
failure normally leaves no final directory. A post-rename verification failure
is moved to a fresh failure-staging name; if that no-replace rollback fails,
the receipt explicitly records `final_present=true` and
`rollback_succeeded=false`. The retained tree contains canonical
`failure_receipt.json` and a hash/byte partial inventory marked
`FAILED_NOT_GENERATION_INPUT`; unsafe text is replaced only for secret-safe
failure evidence. Removal of the invalid pre-publication `arm_receipt.json`
records attempted/present-before/removed/present-after/directory-fsync/taint
fields rather than silently claiming success. A failed tree is never a success
input even if an I/O failure prevents removal. No successful output is deleted,
overwritten, resumed, or reused by this layer.

The final verification is an observation, not an exclusion lock. An unrelated
same-UID process can add a hard link, chmod, or change a file after the final
check and before the Python call returns. Therefore every local result and
receipt retains `HOLD_PUBLICATION_CONCURRENCY_UNPROVEN`; `success=true` means
only that the local checks passed at their observation points and is never a
production permission. A consuming generation/scoring layer must reject every
nonempty hold set and, immediately before and after consuming each referenced
file, open with `O_NOFOLLOW`, require `st_nlink == 1`, bind FD/path device and
inode plus the complete stat signature, and verify the registered byte count
and SHA-256. It must also reject a failure receipt, an extra file, or an
incomplete/tainted recovery state.

Failure cleanup never replaces the original child/publication failure with a
diagnostic-cleanup exception. If the canonical failure receipt cannot be
written, one unpredictable fallback failure receipt is attempted. If that also
fails, the returned result has `receipt_path=null` and
`failure_evidence_state=FAILURE_RECEIPT_UNWRITABLE`.

The supervisor receipt schemas are `biohub.st_r3.arm_receipt.v2` and
`biohub.st_r3.failure_receipt.v2`. Existing child schemas and filenames are
unchanged.

## Unresolved holds, explicitly not claimed

Every locally validated success receipt retains all of the following:

- `HOLD_GT_VISIBLE`: this phase does not construct or prove the required
  container/mount namespace, network disablement, GT sentinel negatives, host
  path nonvisibility, or `/proc` audit. Descriptor closure and an allowlisted
  environment alone do not prove GT nonvisibility.
- `HOLD_PROCESS_TREE_UNPROVEN` and `HOLD_RSS_UNMEASURABLE`: this phase does not
  supply the binding process-creation audit or a whole-tree/cgroup sampler.
  The local direct-child `wait4.ru_maxrss` value is recorded but cannot clear
  the RSS feasibility gate.
- `HOLD_PUBLICATION_CONCURRENCY_UNPROVEN`: no local check-return sequence can
  exclude a concurrent same-UID updater. No success boolean or local arm
  receipt may be consumed without the downstream checks specified above.
- `HOLD_TARGET_RUNTIME_UNCALIBRATED`: no target-class equivalence receipt,
  conservative multiplier, prehash/cache/gap binding, or charged integrity-I/O
  evidence is supplied.
- `HOLD_TARGET_MEMORY_UNCALIBRATED`: no target whole-job/cgroup measurement
  includes the supervisor, runtime/container, descendants, and quota-charged
  page cache.
- `HOLD_DATA_NOT_READY`: this code does not manufacture or validate the latest
  complete eval36 data/verifier receipt, immutable snapshot/exclusive lock, or
  pre/post full input-content inventories.
- `HOLD_SCORING_NOT_RUN`: the supervisor accepts no GT/scorer/evaluator input,
  imports none of those implementations, reads no metric, and performs no
  state-machine score transition.

Accordingly, local `success=true` means only that a conforming
child's local interface artifacts can be independently validated and sealed.
It does not authorize ST-R4, GT access, feasibility PASS, hidden-200 claims,
candidate adoption, Kaggle execution, or submission.

The final local regression evidence for this hardening pass is 224 supervisor
tests, 65 child-interface tests, and the remaining 585 repository tests all
passing (650 non-supervisor tests; 874 total), plus Ruff format/check and Python
byte-compilation of the supervisor core and CLI. The official gitlink remains
clean at `075fc5f5a52d11077f9dc2b074644618f26939e2`.
