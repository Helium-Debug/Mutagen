"""
MUTAGEN Benchmark Target: Fibonacci Calculation.

Baseline: Inefficient exponential recursive implementation O(2^n).
Target: O(n) iterative, memoized, or closed-form implementation.
"""

def fibonacci(n: int) -> int:
    """Calculate the n-th Fibonacci number."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n - 1) + fibonacci(n - 2)


if __name__ == "__main__":
    result = fibonacci(25)
    print(f"fibonacci(25) = {result}")