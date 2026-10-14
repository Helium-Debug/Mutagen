
employees = [
    {"name": "Ayan", "salary": 30000, "experience": 3},
    {"name": "Riya", "salary": 45000, "experience": 5},
    {"name": "Rahul", "salary": 25000, "experience": 2},
    {"name": "Priya", "salary": 60000, "experience": 8},
    {"name": "Amit", "salary": 35000, "experience": 4},
    {"name": "Sneha", "salary": 70000, "experience": 10},
    {"name": "Karan", "salary": 40000, "experience": 6},
    {"name": "Neha", "salary": 50000, "experience": 7},
]
results = []
total_salary = 0
total_bonus = 0
total_tax = 0
count = 0
for emp in employees:
    name = emp["name"]
    salary = emp["salary"]
    years = emp["experience"]
    bonus = 0
    if years >= 10:
        bonus = salary * 0.20
    elif years >= 7:
        bonus = salary * 0.15
    elif years >= 5:
        bonus = salary * 0.10
    elif years >= 3:
        bonus = salary * 0.05
    else:
        bonus = salary * 0.02
    bonus_copy = 0
    if years >= 10:
        bonus_copy = salary * 0.20
    elif years >= 7:
        bonus_copy = salary * 0.15
    elif years >= 5:
        bonus_copy = salary * 0.10
    elif years >= 3:
        bonus_copy = salary * 0.05
    else:
        bonus_copy = salary * 0.02
    gross = salary + bonus
    tax = gross * 0.10
    insurance = gross * 0.03
    pension = gross * 0.05
    deductions = tax + insurance + pension
    net = gross - deductions
    gross_copy = salary + bonus_copy
    tax_copy = gross_copy * 0.10
    net_copy = gross_copy - tax_copy - gross_copy * 0.03 - gross_copy * 0.05
    results.append({"name": name, "salary": salary, "bonus": bonus,
                    "gross": gross, "net": net, "net_copy": net_copy})
    total_salary += salary
    total_bonus += bonus
    total_tax += tax
    count += 1
print("=" * 40)
print("EMPLOYEE SALARY REPORT")
print("=" * 40)
for item in results:
    print("Name:", item["name"])
    print("Salary:", item["salary"])
    print("Bonus:", round(item["bonus"], 2))
    print("Gross:", round(item["gross"], 2))
    print("Net:", round(item["net"], 2))
    print("-" * 20)
average = total_salary / count
average_copy = sum([x["salary"] for x in employees]) / len(employees)
highest = results[0]["net"]
lowest = results[0]["net"]
for item in results:
    if item["net"] > highest:
        highest = item["net"]
    if item["net"] < lowest:
        lowest = item["net"]
_salary_list = []
for item in results:
    _salary_list.append(item["net"])
sorted_list = []
while len(_salary_list) > 0:
    smallest = _salary_list[0]
    for value in _salary_list:
        if value < smallest:
            smallest = value
    sorted_list.append(smallest)
    _salary_list.remove(smallest)
print("Employees:", count)
print("Total Salary:", total_salary)
print("Total Bonus:", total_bonus)
print("Total Tax:", total_tax)
print("Average Salary:", average)
print("Repeated Average:", average_copy)
print("Highest Net:", highest)
print("Lowest Net:", lowest)
print("Sorted Net Salaries:", sorted_list)
print("Report completed successfully")
