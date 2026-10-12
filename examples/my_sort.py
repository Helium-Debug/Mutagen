def my_sort(arr: list[int]) -> list[int]:
    """Algorithm you want MUTAGEN to optimize."""
    return sorted(arr)


if __name__ == "__main__":
    # Benchmark payload executed inside the sandbox
    import random
    rng = random.Random(42)
    sample = [rng.randint(1, 10000) for _ in range(500)]
    sorted_sample = my_sort(sample)
    print(f"Sorted {len(sorted_sample)} elements.")