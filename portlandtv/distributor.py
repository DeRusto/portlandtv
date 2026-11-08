"""Distributor: shares the Show List out across the week's distributed cells."""


class Refused(ValueError):
    pass


def distribute(entries, left, slots):
    """Show List `entries` with `left` remaining episodes each, over `slots` distributed
    Slots -> per Slot, its 7 entries Mon..Sun. Each entry gets at least one cell, the rest
    go by remaining episodes (largest remainder, ties to the earlier entry), and entries
    take contiguous runs in list order, Slot by Slot, Mon->Sun."""
    cells = 7 * slots
    if not entries:
        raise Refused("the Show List is empty")
    if len(entries) > cells:
        raise Refused(f"{len(entries)} Show List entries for {cells} distributed cells;"
                      " each entry needs at least one cell")
    total = sum(left)
    spare = cells - len(entries)
    if not total:  # shortcut: with no episodes left anywhere, share the spare cells equally
        left, total = [1] * len(entries), len(entries)
    # whole numbers, so equal remainders tie exactly and go to the earlier entry
    quota = [divmod(spare * n, total) for n in left]
    counts = [1 + q for q, _ in quota]
    by_remainder = sorted(range(len(entries)), key=lambda i: -quota[i][1])
    for i in by_remainder[:cells - sum(counts)]:
        counts[i] += 1
    run = [e for e, n in zip(entries, counts) for _ in range(n)]
    return [run[7 * s:7 * s + 7] for s in range(slots)]
