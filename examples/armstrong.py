
import math
import sys
import time
import datetime


class ArmstrongNumberDetectionSystem:

    def __init__(self):
        self.number = 0
        self.original_number = 0
        self.digit_count = 0
        self.armstrong_sum = 0
        self.digits = []
        self.execution_status = False
        self.start_time = None
        self.end_time = None

    def display_welcome_message(self):
        print("=" * 60)
        print("      ADVANCED ARMSTRONG NUMBER DETECTION SYSTEM")
        print("=" * 60)
        print("Initializing mathematical computation engine...")
        time.sleep(0.2)
        print("System initialized successfully!\n")

    def take_input(self):
        while True:
            try:
                user_input = input("Enter an integer: ")
                self.number = int(user_input)
                self.original_number = self.number
                break
            except ValueError:
                print("ERROR: Invalid input detected.")
                print("Please enter a valid integer.\n")

    def validate_number(self):
        if self.number < 0:
            print("Negative numbers are not supported.")
            return False

        if isinstance(self.number, int):
            return True

        return False

    def count_digits(self):
        if self.number == 0:
            self.digit_count = 1
        else:
            self.digit_count = len(str(abs(self.number)))

        return self.digit_count

    def extract_digits(self):
        temporary_number = abs(self.number)
        self.digits = []

        if temporary_number == 0:
            self.digits.append(0)

        while temporary_number > 0:
            extracted_digit = temporary_number % 10
            self.digits.insert(0, extracted_digit)
            temporary_number //= 10

        return self.digits

    def calculate_digit_power(self, digit):
        result = math.pow(digit, self.digit_count)
        return int(result)

    def calculate_armstrong_sum(self):
        self.armstrong_sum = 0

        for digit in self.digits:
            digit_power = self.calculate_digit_power(digit)

            print(
                f"Digit: {digit} | "
                f"Power: {self.digit_count} | "
                f"Result: {digit_power}"
            )

            self.armstrong_sum += digit_power

        return self.armstrong_sum

    def perform_redundant_checks(self):
        check_one = self.armstrong_sum == self.original_number
        check_two = not (self.armstrong_sum != self.original_number)
        check_three = (
            str(self.armstrong_sum) == str(self.original_number)
        )

        return check_one and check_two and check_three

    def generate_report(self):
        print("\n" + "=" * 60)
        print("             MATHEMATICAL ANALYSIS REPORT")
        print("=" * 60)

        print(f"Original Number       : {self.original_number}")
        print(f"Number of Digits      : {self.digit_count}")
        print(f"Extracted Digits      : {self.digits}")
        print(f"Calculated Power Sum  : {self.armstrong_sum}")

        if self.perform_redundant_checks():
            print("Final Classification  : ARMSTRONG NUMBER")
        else:
            print("Final Classification  : NOT AN ARMSTRONG NUMBER")

        print("=" * 60)

    def display_execution_statistics(self):
        elapsed_time = self.end_time - self.start_time

        print("\nEXECUTION STATISTICS")
        print("-" * 40)
        print(f"Python Version : {sys.version.split()[0]}")
        print(f"Execution Time : {elapsed_time:.8f} seconds")
        print(f"System Time    : {datetime.datetime.now()}")
        print("-" * 40)

    def run(self):
        self.start_time = time.perf_counter()

        self.display_welcome_message()
        self.take_input()

        if self.validate_number():
            self.count_digits()
            self.extract_digits()
            self.calculate_armstrong_sum()
            self.execution_status = True
            self.generate_report()
        else:
            print("Program terminated due to invalid input.")

        self.end_time = time.perf_counter()
        self.display_execution_statistics()


def main():
    application = ArmstrongNumberDetectionSystem()
    application.run()


if __name__ == "__main__":
    main()
