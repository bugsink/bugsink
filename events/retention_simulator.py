from random import random

HOW_MANY = 100_000


def nonzero_leading_bits(n):
    """
    Return the non-roundness of a number when represented in binary, i.e. the number of leading bits until the last 1.
    """

    s = format(n, 'b')
    return len(s.rstrip('0'))


# dict of epochs => irrelevance => count
db = {}


def simulate_epoch(epoch, how_many):
    total_till_now = sum(sum(d.values()) for d in db.values())

    if epoch not in db:
        db[epoch] = {}
    d = db[epoch]

    # +1 for the new one, i.e. the base for the calculation is the 1-based index of the item / the total number of items
    # after adding the new one
    for outcome in [nonzero_leading_bits(round(random() * (total_till_now + 1 + n) * 2)) for n in range(how_many)]:
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
        return

    # i.e. the highest irrelevance; +1 to correct for -= 1 at the beginning of the loop
    max_total_irrelevance = max(max(d.keys()) for d in db.values()) + 1
    while observed_size > max_size:
        max_total_irrelevance -= 1
        evict(max_total_irrelevance, current_epoch)
        observed_size = sum(sum(d.values()) for d in db.values())
        if max_total_irrelevance < 0:
            raise Exception("Threshold went negative")

    print("Evicted down to %d with a threshold of %d" % (observed_size, max_total_irrelevance))


def main():
    from random import seed
    seed(0)

    epoch = 0
    while True:
        print("INFLOW\n")
        simulate_epoch(epoch, HOW_MANY)
        print_db()

        evict_for_size(10_000, epoch)  # or epoch +1 ?
        print("\nAFTER CLEANUP\n")
        print_db()

        epoch += 1
        input("next?> ")


def print_db():
    max_irrelevance = max(max(d.keys()) for d in db.values())
    max_epoch = max(db.keys())
    max_count = max(max(d.values()) for d in db.values())

    foo = "%" + str(len(str(max_count)) + 2) + "d"  # +2: let it breathe

    # epochs: headers
    print("".join([" " * 6] + [foo % e for e in range(max_epoch + 1)]))

    for irrelevance in range(max_irrelevance + 1):
        print("%6d" % irrelevance, end="")
        for epoch in range(max_epoch + 1):
            if epoch in db and irrelevance in db[epoch]:
                print(foo % db[epoch][irrelevance], end="")
            else:
                print(foo % 0, end="")
        print()

    print("total ", end="")
    for epoch in range(max_epoch + 1):
        print(foo % sum(db[epoch].values()), end="")
    print()


main()
