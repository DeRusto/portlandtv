"""Distributor: shares the Show List out across the week's distributed cells."""


class Refused(ValueError):
    pass


def distribute(entries, slots):
    """Show List `entries` over `slots` distributed Slots -> per Slot, its 7 entries Mon..Sun.
    Entries take equal shares in turn, in list order, day by day (Monday's Slots top to
    bottom, then Tuesday's, ...), so each day mixes them and a long show can't take over;
    when the cells don't divide evenly, the earlier entries get one more."""
    cells = 7 * slots
    if not entries:
        raise Refused("the Show List is empty")
    if len(entries) > cells:
        raise Refused(f"{len(entries)} Show List entries for {cells} distributed cells;"
                      " each entry needs at least one cell")
    return [[entries[(d * slots + s) % len(entries)] for d in range(7)]
            for s in range(slots)]
