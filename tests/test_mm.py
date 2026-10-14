"""
Tests for Matrix Multiplication example (examples/mm.py).
"""

import pytest
from examples.mm import multiply


def test_square_matrix_multiplication():
    A = [
        [1, 2],
        [3, 4],
    ]
    B = [
        [5, 6],
        [7, 8],
    ]
    expected = [
        [19, 22],
        [43, 50],
    ]
    result = multiply(A, B)
    assert result == expected


def test_identity_matrix():
    A = [
        [2, 3],
        [4, 5],
    ]
    I = [
        [1, 0],
        [0, 1],
    ]
    assert multiply(A, I) == A
    assert multiply(I, A) == A


def test_rectangular_matrices():
    A = [
        [1, 2, 3],
        [4, 5, 6],
    ]
    B = [
        [7, 8],
        [9, 1],
        [2, 3],
    ]
    expected = [
        [31, 19],
        [85, 55],
    ]
    result = multiply(A, B)
    assert result == expected


def test_incompatible_dimensions():
    A = [[1, 2]]
    B = [[1, 2]]
    assert multiply(A, B) is None


def test_zeros_matrix():
    A = [
        [1, 2],
        [3, 4],
    ]
    Z = [
        [0, 0],
        [0, 0],
    ]
    assert multiply(A, Z) == Z
