from random import random
from random import seed

HOW_MANY = 100_000
QUOTA = 10_000


def nonzero_leading_bits(n):
    """
    Return the non-roundness of a number when represented in binary, i.e. the number of leading bits until the last 1.
    """

    s = format(n, 'b')
    return len(s.rstrip('0'))


# dict of epochs => irrelevance => count
db = {}


def simulate_epoch(epoch, how_many, max_total_irrelevance):
    total_till_now = sum(sum(d.values()) for d in db.values())

    if epoch not in db:
        db[epoch] = {}
    d = db[epoch]

    # +1 for the new one, i.e. the base for the calculation is the 1-based index of the item / the total number of items
    # after adding the new one
    for outcome in [nonzero_leading_bits(round(random() * (total_till_now + 1 + n) * 2)) for n in range(how_many)]:
        if max_total_irrelevance is not None and outcome > max_total_irrelevance:
            continue

        if outcome not in d:
            d[outcome] = 0
        d[outcome] += 1


def evict_at(max_epoch, max_irrelevance):
    # evicting "at", based on the total irrelevance split out into 2 parts: max item irrelevance, and an epoch as
    # implied by the age-based irrelevance.
    #
    # think of it as a dict equivalent of SQL that says
    # "delete from db where epoch <= epoch and predetermined_irrelevance > max_irrelevance"
    #
    # (max_epoch is _inclusive_, max_irrelevance is _exclusive_)

    assert max_irrelevance >= 0
    assert max_epoch >= 0

    for epoch in range(max_epoch + 1):  # +1 for inclusivity
        d = db[epoch]

        for (irrelevance, n) in list(d.items()):
            if irrelevance > max_irrelevance:
                del d[irrelevance]


def evict(max_total_irrelevance, current_epoch):
    # max_total_irrelevance, i.e. the total may not exceed this (but it may equal it)

    # age based irrelevance is defined as `log(age + 1, 2)`
    #
    # (This is what we chose because we want 0-aged to have an age-based irrelevance of 0); i.e. that's where the +1
    # comes from.
    #
    # at the integer values for irrelevance this works out like so:
    # age = 0 => irrelevance = 0
    # age = 1 => irrelevance = 1
    # age = 2 => irrelevance = 1.58
    # age = 3 => irrelevance = 2
    # ...
    # age = 7 => irrelevance = 3
    #
    # to work back from a given integer "budget" of irrelevance (after the (integer) item-based irrelevance has been
    # subtracted from the total max), we can simply take `2^budget - 1` to get the 'age of eviction', the number of
    # epochs we must go back. The following code helps me understand this:
    #
    # >>> for budget in range(8):
    # ...     age = pow(2, budget) - 1
    # ...     print("budget: %s, age: %s" % (budget, age))

    for max_item_irrelevance in range(max_total_irrelevance + 1):
        budget_for_age = max_total_irrelevance - max_item_irrelevance  # budgets in the range [0, max_total_irrelevance]
        age_of_eviction = pow(2, budget_for_age) - 1  # ages in the range [0, 2^budget_for_age - 1]

        target_epoch = current_epoch - age_of_eviction

        if target_epoch >= 0:
            evict_at(target_epoch, max_item_irrelevance)


def evict_for_size(max_size, current_epoch):
    observed_size = sum(sum(d.values()) for d in db.values())
    if observed_size <= max_size:
        print("No need to evict, already at %d" % observed_size)
        return None

    # i.e. the highest irrelevance; +1 to correct for -= 1 at the beginning of the loop
    # NOTE WRONG: this takes the max event-irrelevance, but does not include age-based irrelevance. This means we'd
    # prune too much in scenarios where the high values for event-irrelevance are some while back
    max_total_irrelevance = max(max(d.keys(), default=0) for d in db.values()) + 1

    while observed_size > max_size:
        max_total_irrelevance -= 1
        evict(max_total_irrelevance, current_epoch)
        observed_size = sum(sum(d.values()) for d in db.values())
        if max_total_irrelevance < 0:
            # could still happen ('in theory') if there's max_size items of irrelevance 0 (in the real impl. we'll have
            # to separately deal with that, i.e. evict-and-warn)
            raise Exception("Threshold went negative")

    print("Evicted down to %d with a max_total_irrelevance of %d" % (observed_size, max_total_irrelevance))
    return max_total_irrelevance


def main():
    current_max_total_irrelevance = None
    how_many = HOW_MANY
    seed(0)

    epoch = 0
    while True:
        this_how_many = input("how many next (%s)> " % how_many)
        if this_how_many:
            how_many = int(this_how_many)

        # NOTE the simulator does one cleanup per epoch, but the real thing does it on-demand as the max size is reached
        # For now I'm not updating the simulator, because I have the real thing to play around with.
        print("INFLOW (with max %s)\n" % current_max_total_irrelevance)
        simulate_epoch(epoch, how_many, current_max_total_irrelevance)
        print_db()

        resulting_thingie = evict_for_size(QUOTA, epoch)
        if resulting_thingie is None:
            current_max_total_irrelevance = None
        else:
            current_max_total_irrelevance = resulting_thingie + 1

        print("\nAFTER CLEANUP\n")
        print_db()

        epoch += 1


def print_db():
    MAX_COLS = 30

    max_irrelevance = max(max(d.keys(), default=0) for d in db.values())
    max_epoch = max(db.keys())
    max_count = max(max(d.values(), default=0) for d in db.values())

    foo = "%" + str(len(str(max_count)) + 2) + "d"  # +2: let it breathe

    # epochs: headers
    print("".join([" " * 6] + [foo % e for e in range(max(0, max_epoch + 1 - MAX_COLS), max_epoch + 1)]))

    for irrelevance in range(max_irrelevance + 1):
        print("%6d" % irrelevance, end="")
        for epoch in range(max(0, max_epoch + 1 - MAX_COLS), max_epoch + 1):
            if epoch in db and irrelevance in db[epoch]:
                print(foo % db[epoch][irrelevance], end="")
            else:
                print(foo % 0, end="")
        print()

    print("total ", end="")
    for epoch in range(max(0, max_epoch + 1 - MAX_COLS), max_epoch + 1):
        print(foo % sum(db[epoch].values()), end="")
    print()


main()


# Notes on 'just drop', put here for lack of a better place.
# While designing the eviction algorithm I also considered the idea of "just drop", i.e. to just never store certain
# events if the calculated irrelvance exceeds some threshold. Such a threshold would typically be: the total threshold
# of the last eviction, with some "cool down" algorithm (the threshold should increase over time) The idea: don't do
# expensive stuff that you know is useless.  This idea is fine (even though eviction is cheap when amortized, the actual
# add is still expensive), but the implementation is hardish: the annoying bit is that we need lots of conditionals in
# our code, because we cannot deal with unsaved and saved Django objects in the same way (FKs). And in some paths
# (basically, the never_evict ones) we still would need to do the save anyway.
