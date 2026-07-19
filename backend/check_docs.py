"""Temporary script to check actual file content on disk."""
import os

files = [
    r"d:\Project\AI Tutors\01_Product\PRD.md",
    r"d:\Project\AI Tutors\03_Data\DSD.md",
    r"d:\Project\AI Tutors\01_Product\TASK.md",
    r"d:\Project\AI Tutors\05_Development\DEVELOPMENT WORKFLOW.md",
    r"d:\Project\AI Tutors\05_Development\Project rules.md",
]

for fp in files:
    if os.path.exists(fp):
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        name = os.path.basename(fp)
        print(f"\n=== {name} ({len(lines)} lines) ===")
        print(f"First: {lines[0][:100]}")
        print(f"Last:  {lines[-1][:100]}")
        # Check for key markers
        for kw in ["DSD", "SAD", "MIS", "ACS", "Reference", "Version", "v1.1", "V1.0", "V1.1"]:
            if kw in content:
                idx = content.find(kw)
                print(f"  Found '{kw}' at pos {idx}")
    else:
        print(f"\n=== {os.path.basename(fp)}: NOT FOUND ===")
