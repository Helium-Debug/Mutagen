# Unoptimised Merge Sort
# Uses list slicing (creates new lists every time) and simple loops.

def merge(left, right):
    result = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i = i + 1
        else:
            result.append(right[j])
            j = j + 1
    # copy whatever is left, one item at a time
    while i < len(left):
        result.append(left[i])
        i = i + 1
    while j < len(right):
        result.append(right[j])
        j = j + 1
    return result


def merge_sort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left_half = arr[0:mid]          # slicing makes a copy
    right_half = arr[mid:len(arr)]  # slicing makes another copy
    left_sorted = merge_sort(left_half)
    right_sorted = merge_sort(right_half)
    return merge(left_sorted, right_sorted)


# Main program
numbers = []
n = int(input("How many numbers? "))
for k in range(n):
    value = int(input("Enter number " + str(k + 1) + ": "))
    numbers.append(value)

print("Original list:", numbers)
sorted_numbers = merge_sort(numbers)
print("Sorted list:  ", sorted_numbers)
