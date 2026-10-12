"""
MUTAGEN Benchmark Target: Armstrong (Narcissistic) Number Verification.

Baseline: String conversion with generator exponentiation.
Target: Pure integer arithmetic, precomputed digit powers, or vectorized checks.
"""

def is_armstrong(num: int) -> bool:
    # Convert to string to find the total number of digits
    num_str = str(num)
    n = len(num_str)
    
    # Calculate the sum of digits raised to the power of n
    total = sum(int(digit) ** n for digit in num_str)
    
    # Return True if they match, otherwise False
    return total == num


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1].lstrip('-').isdigit():
        number = int(sys.argv[1])
        if is_armstrong(number):
            print(f"{number} is an Armstrong number!")
        else:
            print(f"{number} is not an Armstrong number.")
    else:
        # Benchmark and verification workload
        armstrongs = [i for i in range(1, 100_000) if is_armstrong(i)]
        print(f"Found {len(armstrongs)} Armstrong numbers under 100,000: {armstrongs}")
