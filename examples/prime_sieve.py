"""
MUTAGEN Benchmark Target: Prime Number Finder.

Baseline: Inefficient trial division algorithm.
Target: Sieve of Eratosthenes or segmented sieve.
"""

def count_primes(limit: int) -> int:
    """Count number of primes below limit using trial division."""
    count = 0
    for num in range(2, limit):
        is_prime = True
        for i in range(2, num):
            if num % i == 0:
                is_prime = False
                break
        if is_prime:
            count += 1
    return count


if __name__ == "__main__":
    result = count_primes(2000)
    print(f"Number of primes below 2000 = {result}")
