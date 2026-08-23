"""Group every submission by the kernel that produced it, and flag the unscored ones.

Assumes a LOWER-IS-BETTER metric (RMSE, logloss, MAE): "best" means the smallest score.
For accuracy, AUC or similar, invert the min()/sorted() calls marked with
"# lower is better" before trusting the output.

Every guard below exists because the plain approach silently produced a wrong answer
in a real competition:

  * `competition_submissions` defaults to page_size=20 and silently drops the oldest
    submissions once the history grows past that — including, in our case, the best
    draw we had. Ask for 1000 and assert the result came back short of the cap;
    `page_number` is a no-op on this endpoint, so there is no pagination fallback.
  * `status` reads COMPLETE for a run that exceeded the runtime cap. The reliable test
    for "not scored" is an empty `public_score`, and the reason lives on
    `error_description`, not `errorDescription`.
  * Matching configs by description text picks up submissions that merely mention
    another config in prose. The submission's `url` carries the kernel slug, which is
    unambiguous.
  * On a tie at a kernel's best score, the ref picked was whichever the API happened to
    list first (newest-first), so a fresh replicate could silently move the recommended
    ref. Ties now resolve to the EARLIEST submission and every tied ref is printed.
  * One slug can span several `scriptVersionId`s — every edit creates one — so grouping
    by slug alone pools distinct code as one "config". The version count is reported.
  * Kaggle auto-selects if you do not, and the rules do not state the criterion.
    Observed behaviour is best-public-score, which may not match your plan, so
    `--final-check` states any divergence explicitly.

Usage:
    uv run python scripts/submission_status.py [--all]
    uv run python scripts/submission_status.py --final-check [REF1 REF2]
"""

from __future__ import annotations

import os
import re
import statistics as st
import sys
from collections import defaultdict

COMPETITION = os.environ.get("KAGGLE_COMPETITION", "")

# Asked-for page size. The endpoint returns everything up to this and never paginates,
# so a result of exactly PAGE_SIZE means we were truncated and must not be trusted.
PAGE_SIZE = 1000

# The planned final two, by immutable ref (a kernel rename changes the slug, not the ref).
# Fill these in, or pass two refs on the command line:
#     python submission_status.py --final-check 12345678 87654321
PLANNED: dict[str, tuple[str, str | None, str | None]] = {
    # "slot1": ("<ref>", "<kernel-slug or None>", "<scriptVersionId or None>"),
    # "slot2": ("<ref>", None, None),
}


def kernel_of(sub) -> str:
    m = re.search(r"/code/[^/]+/([^?]+)", str(getattr(sub, "url", "") or ""))
    return m.group(1) if m else "<unknown>"


def version_of(sub) -> str:
    m = re.search(r"scriptVersionId=(\d+)", str(getattr(sub, "url", "") or ""))
    return m.group(1) if m else "<unknown>"


def score_of(sub) -> str:
    return str(getattr(sub, "public_score", "") or "").strip()


def fetch(group=None) -> list:
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    kw = {"group": group} if group is not None else {}
    subs = list(api.competition_submissions(COMPETITION, page_size=PAGE_SIZE, **kw) or [])
    if group is not None:
        return subs
    if len(subs) >= PAGE_SIZE:
        raise SystemExit(
            f"ABORT: got exactly {len(subs)} submissions == page_size. The list is "
            f"truncated and page_number does not work on this endpoint. Raise PAGE_SIZE."
        )
    if not subs:
        raise SystemExit("ABORT: zero submissions returned -- auth or competition name wrong.")
    return subs


def resolve_plan(argv: list[str]) -> dict:
    """Decide which two submissions to verify, refusing anything ambiguous.

    Refs are numeric. Anything else typed after --final-check is a mistake -- a
    placeholder left unreplaced, a typo, the wrong count -- and must stop the run.
    Falling back to PLANNED would print a confident verdict about submissions the
    caller never named, which is worse than no check at all.
    """
    given = [a for a in argv if a != "--final-check" and not a.startswith("-")]
    if given:
        bad = [a for a in given if not a.isdigit()]
        if bad:
            raise SystemExit(
                f"ABORT: expected numeric submission refs, got {bad}. "
                f"Pass two refs, e.g. --final-check 55252809 55252812"
            )
        if len(given) != 2:
            raise SystemExit(
                f"ABORT: --final-check takes exactly two refs, got {len(given)}."
            )
        if given[0] == given[1]:
            raise SystemExit(
                f"ABORT: both refs are {given[0]}. Two distinct submissions must be "
                f"selected; a duplicate would silently verify only one slot."
            )
        return {f"slot{i}": (r, None, None) for i, r in enumerate(given, 1)}
    if not PLANNED:
        raise SystemExit(
            "ABORT: PLANNED is empty and no refs were given. Either fill in PLANNED "
            "at the top of this file, or pass two refs: --final-check REF REF"
        )
    # The same three guards, because a typo in PLANNED is exactly as dangerous as one
    # on the command line -- more so, since nobody re-reads it before the deadline.
    refs = [r for r, _, _ in PLANNED.values()]
    if len(refs) != 2:
        raise SystemExit(f"ABORT: PLANNED must hold exactly two slots, has {len(refs)}.")
    if len(set(refs)) != 2:
        raise SystemExit(
            f"ABORT: both slots in PLANNED point at ref {refs[0]}. Two distinct "
            f"submissions must be selected; a duplicate would verify only one slot."
        )
    if not all(r.isdigit() for r in refs):
        raise SystemExit(f"ABORT: PLANNED refs must be numeric, got {refs}.")
    return PLANNED


def final_check(subs: list) -> int:
    """Validate the planned final two by ref, and report anything that could change them."""
    by_ref = {str(s.ref): s for s in subs}
    by_kernel: dict[str, list] = defaultdict(list)
    for s in subs:
        if score_of(s):
            by_kernel[kernel_of(s)].append(s)

    plan = resolve_plan(sys.argv[1:])

    ok = True
    for slot, (ref, want_kernel, want_ver) in plan.items():
        s = by_ref.get(ref)
        print(f"\n=== {slot}: ref {ref} ===")
        if s is None:
            print("  FAIL: ref not present in submission history")
            ok = False
            continue
        sc, kern, ver = score_of(s), kernel_of(s), version_of(s)
        err = str(getattr(s, "error_description", "") or "")
        print(f"  public_score      : {sc or '<EMPTY = NOT SCORED>'}")
        print(f"  private_score     : {str(getattr(s, 'private_score', '') or '') or '<empty>'}")
        print(f"  kernel / version  : {kern} / {ver}")
        print(f"  date (UTC)        : {s.date}")
        print(f"  status            : {s.status}   total_bytes={s.total_bytes}")
        print(f"  error_description : {err or '<none>'}")
        if not sc:
            print("  FAIL: no public score -- this submission CANNOT be selected")
            ok = False
        if int(getattr(s, "total_bytes", 0) or 0) == 0:
            print("  FAIL: total_bytes == 0 -- the rerun produced no submission file")
            ok = False
        if want_kernel and kern != want_kernel:
            print(f"  FAIL: kernel is {kern}, expected {want_kernel}")
            ok = False
        if want_ver and ver != want_ver:
            print(f"  FAIL: scriptVersionId is {ver}, expected {want_ver}")
            ok = False

        peers = by_kernel.get(kern, [])
        vals = sorted(float(p.public_score) for p in peers)  # lower is better
        if vals and sc:
            best = vals[0]
            tied = sorted(
                (p for p in peers if float(p.public_score) == best), key=lambda p: p.date
            )
            print(f"  kernel draws      : n={len(vals)} best={best:.3f} mean={st.mean(vals):.4f}")
            if float(sc) > best:  # lower is better
                # Only meaningful when every draw under this slug is the same code.
                # Once the slug spans versions, a better score elsewhere may belong to
                # different code entirely, so this is advisory -- same reason the
                # version-count check below is a WARN.
                # Only draws of the SAME code are comparable. If the better draw
                # shares this submission's version, it really is a better draw of the
                # identical kernel and must stay a hard failure.
                multi = any(version_of(p) != ver for p in tied)
                label = "WARN" if multi else "FAIL"
                print(f"  {label}: not this kernel's best draw -- {best:.3f} is "
                      f"(ref {tied[0].ref})"
                      + ("; the slug spans several versions, so that draw may be "
                         "different code" if multi else ""))
                if not multi:
                    ok = False
            elif len(tied) > 1:
                print(f"  WARN: tie at {best:.3f} across refs {[str(t.ref) for t in tied]}; "
                      f"earliest is {tied[0].ref}")
        vers = {version_of(p) for p in peers}
        if len(vers) > 1:
            # Pooling across versions only invalidates the check when the slot does not
            # pin a scriptVersionId. A slug spanning several versions is normal --
            # every edit makes one -- so this cannot be a failure on its own. What the
            # submission reruns is fixed by its ref, which is verified above; only the
            # pooled "kernel draws" statistics are affected, and those are advisory.
            # Pin want_ver in PLANNED if you also want the version asserted.
            print(f"  WARN: slug spans {len(vers)} scriptVersionIds {sorted(vers)} "
                  f"-- the 'kernel draws' line above pools DIFFERENT code")

    pending = [s for s in subs if not score_of(s) and not str(
        getattr(s, "error_description", "") or "")]
    print(f"\n=== still-pending submissions (could out-score the plan later): {len(pending)} ===")
    for s in sorted(pending, key=lambda s: s.date):
        print(f"  {s.date:%m-%d %H:%M} UTC  {s.ref}  {kernel_of(s)}")

    # lower is better
    scored = sorted((s for s in subs if score_of(s)), key=lambda s: float(s.public_score))
    auto = scored[:2]
    chosen = {r for r, _, _ in plan.values()}
    print("\n=== Kaggle auto-selection vs the plan ===")
    # Kaggle auto-selects if the user does not, but the rules do not state the
    # criterion. Observed behaviour is best-public-score, which may not match the plan.
    print("  Auto-selection criterion is NOT in the rules; observed behaviour is best")
    print("  public score. Top 2 public are:")
    for i, s in enumerate(auto, 1):
        print(f"    #{i} {s.public_score}  ref={s.ref}  {kernel_of(s)}")
    if {str(s.ref) for s in auto} != chosen:
        print("  => AUTO-SELECTION DOES NOT MATCH THE PLAN.")
        print("     Manual selection in the Kaggle UI is MANDATORY, not optional.")
    else:
        print("  => auto-selection happens to match the plan.")

    # Selection cannot be SET from the API, but it CAN be read back: the endpoint
    # accepts group=SUBMISSION_GROUP_SELECTED. This is the only objective proof that
    # the manual UI click actually took effect.
    from kagglesdk.competitions.types.competition_enums import SubmissionGroup

    sel = fetch(group=SubmissionGroup.SUBMISSION_GROUP_SELECTED)
    print(f"\n=== currently SELECTED on Kaggle: {len(sel)} ===")
    for s in sel:
        # score_of() rather than the raw attribute: a submission that is selected but
        # still being scored has public_score=None, and formatting that would crash
        # here -- in the one section whose whole purpose is to print a verdict.
        shown = score_of(s) or "pending"
        print(f"  {shown:>7}  ref={s.ref}  {kernel_of(s)}  ({s.date:%m-%d %H:%M} UTC)")
    sel_refs = {str(s.ref) for s in sel}
    if not sel_refs:
        print("  => NOTHING SELECTED YET. The UI click has not been made (or did not save).")
        ok = False
    elif sel_refs != chosen:
        print(f"  => MISMATCH. Selected {sorted(sel_refs)} but the plan is {sorted(chosen)}.")
        ok = False
    else:
        print("  => CONFIRMED: the selection on Kaggle matches the plan exactly.")

    verdict = "PASS -- selection verified" if ok else "FAIL -- selection not yet correct"
    print("\nRESULT:", verdict)
    return 0 if ok else 1


USAGE = """usage: submission_status.py [--all] [--final-check [REF REF]]

  (no flags)     group every submission by the kernel that produced it
  --all          also list every scored submission, best first
  --final-check  verify the final selection; pass two refs, or fill in PLANNED

Set KAGGLE_COMPETITION to the competition slug first.

Note: this tool assumes a lower-is-better metric (RMSE, logloss). For accuracy or AUC,
invert every comparison marked "# lower is better" before relying on it.
"""


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if not COMPETITION:
        raise SystemExit(
            "set KAGGLE_COMPETITION first, e.g. export KAGGLE_COMPETITION=my-competition"
        )
    if "--final-check" in argv:
        resolve_plan(argv[1:])      # fail on bad arguments before any network call
    subs = fetch()
    if "--final-check" in argv:
        return final_check(subs)

    by_kernel: dict[str, list] = defaultdict(list)
    unscored: list = []
    for s in subs:
        (by_kernel[kernel_of(s)] if score_of(s) else unscored).append(s)

    print(f"{len(subs)} submissions  ({min(s.date for s in subs):%m-%d} .. "
          f"{max(s.date for s in subs):%m-%d})   scored={len(subs) - len(unscored)}")

    rows = []
    for k, ss in by_kernel.items():
        vs = sorted(float(s.public_score) for s in ss)
        best = min(vs)  # lower is better
        # Ties resolve to the EARLIEST submission, so a fresh replicate at the same
        # score cannot silently move the recommended ref.
        tied = sorted((s for s in ss if float(s.public_score) == best), key=lambda s: s.date)
        note = ""
        if len(tied) > 1:
            note += f"  [TIE x{len(tied)}: {','.join(str(t.ref) for t in tied[1:])}]"
        nver = len({version_of(s) for s in ss})
        if nver > 1:
            note += f"  [!! {nver} scriptVersionIds pooled under one slug]"
        rows.append((best, k, len(vs), str(tied[0].ref),
                     st.mean(vs), st.stdev(vs) if len(vs) > 1 else float("nan"), note))

    print(f"\n{'best':>7}  {'n':>2}  {'mean':>7}  {'sd':>6}  {'ref':>9}  kernel")
    for best, k, n, ref, mean, sd, note in sorted(rows):  # lower is better
        sd_s = f"{sd:6.4f}" if sd == sd else "     -"
        print(f"{best:7.3f}  {n:2d}  {mean:7.4f}  {sd_s}  {ref:>9}  {k}{note}")

    print(f"\nunscored ({len(unscored)}):")
    for s in sorted(unscored, key=lambda s: s.date):
        err = str(getattr(s, "error_description", "") or "")
        kind = "TIMEOUT" if "runtime" in err.lower() else ("PENDING" if not err else "ERROR")
        print(f"  {s.date:%m-%d %H:%M}  {s.ref}  {kind:7s}  {kernel_of(s)}")

    if "--all" in argv:
        print("\nall scored, best first:")
        for s in sorted(  # lower is better
            (x for x in subs if str(getattr(x, "public_score", "") or "").strip()),
            key=lambda x: float(x.public_score),
        ):
            print(f"  {float(s.public_score):7.3f}  {s.ref}  {kernel_of(s)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
