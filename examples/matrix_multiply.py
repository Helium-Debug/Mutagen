"""
MUTAGEN Benchmark Target: Matrix Multiplication.

Baseline: Inefficient triple nested loops O(n^3).
Target: Cache-friendly transposed loop, list comprehensions, or vectorized algorithm.
"""

def matrix_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Multiply two NxN square matrices."""
    n = len(a)
    result = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                result[i][j] += a[i][k] * b[k][j]
    return result


if __name__ == "__main__":
    n = 30
    mat_a = [[float(i + j) for j in range(n)] for i in range(n)]
    mat_b = [[float(i * j) for j in range(n)] for i in range(n)]
    out = matrix_multiply(mat_a, mat_b)
    print(f"Computed matrix product of size {n}x{n}, top-left = {out[0][0]}")
