Issue17 QwenCloud Max authoring only no tools. Parent reviewing previous merge_shards, not yet applied. Return ONLY 3 corrected snippets labeled A/B/C. No whole function.
A replace these two assignment checks to require exact list and exact str (not subclasses), original order sortedunique (not sorted on both sides):
if not isinstance(assignments, list) or len(assignments) not in (1, 2):
    raise ValueError("assignments must be a list of length 1 or 2")

B replace inside loop:
        if not isinstance(assigned, list) or not assigned:
            raise ValueError(f"assignment[{i}] must be a non-empty list of str")
        if any(not isinstance(a, str) for a in assigned):
            raise TypeError(f"assignment[{i}] contains non-str elements")
        if sorted(set(assigned)) != sorted(assigned):
            raise ValueError(f"assignment[{i}] must be sorted and unique")

C previous code incorrectly read stems/shapes from BOUNDS (bounds lacks those fields). Existing all_assigned is flattened list; receipts is tuple of verified dicts each with shapes dict. Need all_stems=sorted(all_assigned); all_shapes a dict mapping ds->shape from receipts, ordered sorted by ds. Replace wrong lines:
    all_stems = sorted({s for b in bounds_list for s in b.get("stems", [])})
    all_shapes = sorted({sh for b in bounds_list for sh in b.get("shapes", [])}, key=str)
