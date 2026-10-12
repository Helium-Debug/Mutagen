"""
MUTAGEN Benchmark Target: Bubble Sort.

Baseline: Slow O(n^2) nested comparison sorting.
Target: Optimized O(n log n) sorting algorithm or adaptive sort.
"""

def bubble_sort(arr: list[int]) -> list[int]:
    """Sort a list of integers using bubble sort."""
    data = list(arr)
    n = len(data)
    for i in range(n):
        for j in range(0, n - i - 1):
            if data[j] > data[j + 1]:
                data[j], data[j + 1] = data[j + 1], data[j]
    return data


if __name__ == "__main__":
    import random
    rng = random.Random(42)
    sample = [rng.randint(1, 10000) for _ in range(500)]
    sorted_sample = bubble_sort(sample)
    print(f"Sorted {len(sorted_sample)} elements, first 5: {sorted_sample[:5]}")
