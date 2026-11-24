"""Enter official Income Tax calculator results into official_checks.csv, one case at a time.

Usage:  python fill_official.py
Type the old- and new-regime tax the calculator shows. Enter 's' to skip a case, 'q' to quit.
Progress is saved after every case, so you can stop and resume any time.
"""
import csv
import json
from datetime import date
from pathlib import Path

PATH = Path("project_a/tests/official_checks.csv")  # adjust if your file lives elsewhere


def save(rows, fieldnames):
    with PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


with PATH.open(newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

todo = [r for r in rows if not r["official_old"] or not r["official_new"]]
print(f"{len(todo)} of {len(rows)} cases still to check\n")

for row in todo:
    inputs = json.loads(row["input_json"])
    print("=" * 60)
    print(f"{row['id']}  ({row['description']})")
    # Show only the fields you need to type in: non-zero values, plus age
    for key, value in inputs.items():
        if key == "age" or value not in (0, False):
            print(f"   {key:<20} {value:,}" if isinstance(value, int) and not isinstance(value, bool)
                  else f"   {key:<20} {value}")
    print(f"   (expected: old {row['expected_old']}, new {row['expected_new']})")

    old = input("Official OLD regime tax: ").strip()
    if old.lower() == "q":
        break
    if old.lower() == "s":
        continue
    new = input("Official NEW regime tax: ").strip()
    if new.lower() == "q":
        break
    if new.lower() == "s":
        continue
    notes = input("Notes (Enter for none): ").strip()

    row["official_old"] = old.replace(",", "")
    row["official_new"] = new.replace(",", "")
    row["checked_on"] = date.today().isoformat()
    if notes:
        row["notes"] = notes

    match = row["official_old"] == row["expected_old"] and row["official_new"] == row["expected_new"]
    print("   MATCH" if match else "   MISMATCH: re-check what you typed into the calculator first")
    save(rows, fieldnames)

done = sum(1 for r in rows if r["official_old"] and r["official_new"])
print(f"\nSaved. {done} of {len(rows)} cases checked.")