
# Student Result Analyzer - Intentionally Bloated Version
# The goal is to calculate student marks, percentages, grades,
# class statistics, and identify the topper.

import random
import math
import statistics

students = [
    {"name": "Ayan", "marks": [78, 85, 91, 67, 88]},
    {"name": "Riya", "marks": [92, 95, 89, 96, 94]},
    {"name": "Rahul", "marks": [56, 62, 58, 71, 60]},
    {"name": "Priya", "marks": [88, 82, 90, 85, 87]},
    {"name": "Amit", "marks": [45, 55, 49, 52, 48]},
    {"name": "Sneha", "marks": [98, 97, 96, 99, 95]},
    {"name": "Karan", "marks": [67, 73, 69, 75, 71]},
    {"name": "Neha", "marks": [81, 84, 79, 86, 83]},
]

total_marks_per_subject = 100
number_of_subjects = 5
maximum_possible_marks = total_marks_per_subject * number_of_subjects

student_results = []
all_percentages = []
all_totals = []

for student in students:
    name = student["name"]
    marks = student["marks"]

    total = 0
    for mark in marks:
        total = total + mark

    total_again = 0
    for index in range(len(marks)):
        total_again = total_again + marks[index]

    percentage = (total / maximum_possible_marks) * 100
    percentage_again = (total_again / maximum_possible_marks) * 100

    average = total / len(marks)

    if percentage >= 90:
        grade = "A+"
    elif percentage >= 80:
        grade = "A"
    elif percentage >= 70:
        grade = "B"
    elif percentage >= 60:
        grade = "C"
    elif percentage >= 50:
        grade = "D"
    else:
        grade = "F"

    passed = True
    for mark in marks:
        if mark < 40:
            passed = False

    result = {
        "name": name,
        "total": total,
        "percentage": percentage,
        "percentage_duplicate": percentage_again,
        "average": average,
        "grade": grade,
        "passed": passed,
    }

    student_results.append(result)
    all_percentages.append(percentage)
    all_totals.append(total)

print("=" * 60)
print("STUDENT RESULT ANALYSIS REPORT")
print("=" * 60)

for result in student_results:
    print("Student Name:", result["name"])
    print("Total Marks:", result["total"])
    print("Percentage:", round(result["percentage"], 2), "%")
    print("Grade:", result["grade"])
    print("Pass Status:", result["passed"])
    print("-" * 40)

topper = student_results[0]

for result in student_results:
    if result["total"] > topper["total"]:
        topper = result

print("TOPPER:", topper["name"])
print("TOPPER MARKS:", topper["total"])

class_total = 0
for total in all_totals:
    class_total = class_total + total

class_average = class_total / len(all_totals)

highest_percentage = all_percentages[0]
for percentage in all_percentages:
    if percentage > highest_percentage:
        highest_percentage = percentage

lowest_percentage = all_percentages[0]
for percentage in all_percentages:
    if percentage < lowest_percentage:
        lowest_percentage = percentage

sorted_percentages = []
temporary_percentages = all_percentages.copy()

while len(temporary_percentages) > 0:
    smallest = temporary_percentages[0]
    for value in temporary_percentages:
        if value < smallest:
            smallest = value
    sorted_percentages.append(smallest)
    temporary_percentages.remove(smallest)

print("CLASS AVERAGE:", round(class_average, 2))
print("HIGHEST PERCENTAGE:", highest_percentage)
print("LOWEST PERCENTAGE:", lowest_percentage)
print("MEDIAN PERCENTAGE:", statistics.median(all_percentages))
print("SORTED PERCENTAGES:", sorted_percentages)

passed_count = 0
failed_count = 0

for result in student_results:
    if result["passed"] == True:
        passed_count = passed_count + 1
    else:
        failed_count = failed_count + 1

print("TOTAL STUDENTS:", len(students))
print("PASSED STUDENTS:", passed_count)
print("FAILED STUDENTS:", failed_count)

pass_percentage = (passed_count / len(students)) * 100
print("CLASS PASS PERCENTAGE:", round(pass_percentage, 2), "%")

print("=" * 60)
print("REPORT GENERATION COMPLETE")
print("=" * 60)
