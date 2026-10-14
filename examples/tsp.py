"""
Travelling Salesman Problem - Brute Force (deliberately unoptimised)

Tries every possible ordering of cities, computes the full tour length for
each one from scratch, and keeps the shortest. Time complexity is O(n!),
so it is only practical for roughly 10 cities or fewer.
"""

import math
from itertools import permutations


def distance(a, b):
    """Euclidean distance between two (x, y) points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def tour_length(tour, cities):
    """Total length of a closed tour, recomputed from scratch every time."""
    total = 0
    for i in range(len(tour)):
        city_a = cities[tour[i]]
        city_b = cities[tour[(i + 1) % len(tour)]]  # wrap back to the start
        total += distance(city_a, city_b)
    return total


def tsp_brute_force(cities):
    """Check every permutation of all cities (no pruning, no fixed start)."""
    n = len(cities)
    best_tour = None
    best_length = float("inf")

    for perm in permutations(range(n)):
        length = tour_length(perm, cities)
        if length < best_length:
            best_length = length
            best_tour = perm

    return best_tour, best_length


if __name__ == "__main__":
    # City name -> (x, y) coordinates
    city_names = ["A", "B", "C", "D", "E", "F", "G", "H"]
    cities = [
        (0, 0),
        (2, 6),
        (5, 2),
        (6, 6),
        (8, 3),
        (1, 9),
        (9, 9),
        (4, 5),
    ]

    tour, length = tsp_brute_force(cities)

    route = " -> ".join(city_names[i] for i in tour)
    route += " -> " + city_names[tour[0]]

    print("Best route:", route)
    print("Total distance:", round(length, 2))