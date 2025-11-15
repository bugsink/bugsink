from bugsink.utils import nc_rnd


PRETTY_RANDOM_TAGS = {
    "os": ["Windows", "Linux", "MacOS", "Android", "iOS"],
    "os.version": ["10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20"],
    "cpu": ["x86", "x64", "ARM", "ARM64", "MIPS"],
    "browser": ["Chrome", "Firefox", "Safari", "Edge", "Opera"],
    "device": ["Desktop", "Laptop", "Tablet", "Smartphone"],
    "environment": ["production", "staging", "development", "testing"],
    "release": ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0"],
    "feature_flag": ["new-ui", "beta-feature", "dark-mode", "performance-improvements"],
}


def random_postfix():
    # avoids numbers, because when used in the type I imagine numbers may at some point be ignored in the grouping.
    random_number = nc_rnd.random()

    if random_number < 0.1:
        # 10% of the time we simply sample from 1M to create a "fat tail".
        unevenly_distributed_number = int(nc_rnd.random() * 1_000_000)
    else:
        unevenly_distributed_number = int(1 / random_number)

    return "".join([chr(ord("A") + int(c)) for c in str(unevenly_distributed_number)])


def random_for_RANDOM(k, v):
    if v != "RANDOM":
        return v

    if k in PRETTY_RANDOM_TAGS:
        options = PRETTY_RANDOM_TAGS[k]
        random_number = nc_rnd.random()
        unevenly_distributed_number = int(1 / random_number)

        if unevenly_distributed_number > len(options) - 1:
            return options[0]

        return options[unevenly_distributed_number]

    return "value-" + random_postfix()
