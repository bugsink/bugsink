import datetime
import math
import random


# a way to generate some bursty streams of points-in-time.
# I'm sure there's a 100 things wrong with this, but at least it's
#
# * not simply distributed at random
# * has some form of periodic pattern in it as real data surely has
# * has bursts (errors come in bursts!)
#
# this will give us at least some base to test in somewhat natural settings.


def generate_bursty_data(nr_of_waves=1, base_amplitude=1, expected_nr_of_bursts=1, burst_amplitude=5, num_buckets=1000):
    """returns `num_buckets` histogram-like buckets"""

    burst_prob = expected_nr_of_bursts / num_buckets
    period = num_buckets / nr_of_waves

    buckets = [0] * num_buckets

    for i in range(num_buckets):
        # We pick math.sin as an arbitrary periodic pattern. Normalize for period and >0
        periodic_pattern = (1 + math.sin(i / period * 2 * math.pi)) / 2

        # Introduce burst with probability 'burst_prob'
        if random.random() < burst_prob:
            burst = abs(random.gauss(0, burst_amplitude))
            buckets[i] = periodic_pattern + burst
        else:
            buckets[i] = periodic_pattern

    return buckets


def buckets_to_points_in_time(buckets, begin, end, total_points):
    """given:

    * histogram-like list of 'buckets', where each bucket is a float that is a relative business of that period
    * a begin and an end (both datetime)
    * a total amount of points

    generates a list of points of length `total_points` that conforms to the distribution denoted by the buckets, and
    where the points-in-time are distributed at random within the buckets.
    """

    total_weight = sum(buckets)

    time_range_size = end - begin
    bucket_size = time_range_size.total_seconds() / len(buckets)

    points = []

    rounding_difference = 0

    for i, bucket_weight in enumerate(buckets):
        bucket_points = (bucket_weight / total_weight) * total_points + rounding_difference
        rounding_difference = bucket_points - round(bucket_points)
        bucket_points = round(bucket_points)

        for j in range(bucket_points):
            points.append(begin + datetime.timedelta(seconds=bucket_size * (i + random.uniform(0, 1))))

    return sorted(points)
