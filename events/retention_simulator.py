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

    for outcome in [nonzero_leading_bits(round(random() * (total_till_now + 1 + n) * 2)) for n in range(how_many)]:  # +1 for the new one
        if outcome not in d:
            d[outcome] = 0
        d[outcome] += 1


def evict_at(epoch, threshold):
    if epoch < 0:
        return

    for at_epoch in range(epoch + 1):
        d = db[at_epoch]

        for (t, n) in list(d.items()):
            if t >= threshold:  # TODO CHECK: >= or > ?
                del d[t]


def evict(threshold, current_epoch):
    for an_irrelevance_threshold in range(threshold + 1):
        budget_for_age = threshold - an_irrelevance_threshold  # budgets in the range [0, threshold]
        age_of_death = pow(2, budget_for_age) - 1  # ages in the range [0, 2^threshold - 1]  # -1 is to enable clean-at-current
        evict_at(current_epoch - age_of_death, an_irrelevance_threshold)


def evict_until(max_size, current_epoch):
    total_size = sum(sum(d.values()) for d in db.values())
    if total_size <= max_size:
        print("No need to evict, already at %d" % total_size)
        return

    threshold = 20  # arbitrary starting point; TODO, start from something that makes sense (e.g. the max irrelevance)
    while total_size > max_size:
        evict(threshold, current_epoch)
        total_size = sum(sum(d.values()) for d in db.values())
        threshold -= 1
        if threshold < 0:
            raise Exception("Threshold went negative")

    print("Evicted down to %d with a threshold of %d" % (total_size, threshold + 1))


def main():
    from random import seed
    seed(0)

    epoch = 0
    while True:
        print("INFLOW\n")
        simulate_epoch(epoch, HOW_MANY)
        print_db()

        evict_until(10_000, epoch)  # or epoch +1 ?
        print("\nAFTER CLEANUP\n")
        print_db()

        epoch += 1
        input("next?> ")


# TODO NEXT PART OF THE SIMULATION: automating the threshold, based on capacity


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
