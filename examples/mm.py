# Unoptimised Matrix Multiplication
# Plain triple nested loop, no NumPy, no shortcuts.

def read_matrix(name):
    rows = int(input("Number of rows in " + name + ": "))
    cols = int(input("Number of columns in " + name + ": "))
    matrix = []
    for i in range(rows):
        row = []
        for j in range(cols):
            value = int(input(name + "[" + str(i) + "][" + str(j) + "] = "))
            row.append(value)
        matrix.append(row)
    return matrix


def multiply(A, B):
    rows_A = len(A)
    cols_A = len(A[0])
    rows_B = len(B)
    cols_B = len(B[0])

    if cols_A != rows_B:
        print("Cannot multiply: columns of A must equal rows of B")
        return None

    # create result matrix filled with zeros
    C = []
    for i in range(rows_A):
        row = []
        for j in range(cols_B):
            row.append(0)
        C.append(row)

    # triple loop
    for i in range(rows_A):
        for j in range(cols_B):
            for k in range(cols_A):
                C[i][j] += A[i][k] * B[k][j]
    return C


def print_matrix(M):
    for i in range(len(M)):
        line = ""
        for j in range(len(M[i])):
            line = line + str(M[i][j]) + "\t"
        print(line)


if __name__ == "__main__":
    import sys
    # If running interactively in terminal, prompt user for matrices
    if sys.stdin.isatty():
        try:
            print("Enter Matrix A")
            A = read_matrix("A")
            print("Enter Matrix B")
            B = read_matrix("B")
        except (EOFError, KeyboardInterrupt):
            A = [[1, 2], [3, 4]]
            B = [[5, 6], [7, 8]]
    else:
        # Non-interactive / sandbox test fallback
        A = [[1, 2], [3, 4]]
        B = [[5, 6], [7, 8]]

    C = multiply(A, B)
    if C is not None:
        print("Matrix A:")
        print_matrix(A)
        print("Matrix B:")
        print_matrix(B)
        print("Result A x B:")
        print_matrix(C)