"""Check the two skipped files."""
import os

# Check PRD.md for references section
path = r"d:\Project\AI Tutors\01_Product\PRD.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print("=== PRD.md: Looking for references/version section ===")
for kw in ["DSD", "SAD", "MIS", "ACS", "Reference", "v1.", "v2.", "Version"]:
    if kw in content:
        idx = content.find(kw)
        ctx = content[max(0, idx - 20) : idx + 60]
        print(f"  Found '{kw}': ...{repr(ctx)}...")

# Check WORKFLOW for V1.1
path = r"d:\Project\AI Tutors\05_Development\DEVELOPMENT WORKFLOW.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print("\n=== WORKFLOW: Looking for version references ===")
for kw in ["V1.0", "V1.1", "V2.0", "TASK.md"]:
    if kw in content:
        idx = content.find(kw)
        ctx = content[max(0, idx - 20) : idx + 60]
        print(f"  Found '{kw}': ...{repr(ctx)}...")

# Check PRD for version references that need fixing
path = r"d:\Project\AI Tutors\01_Product\PRD.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print("\n=== PRD.md: All version-like patterns ===")
import re
for m in re.finditer(r"v\d+\.\d+|V\d+\.\d+", content):
    ctx = content[max(0, m.start() - 10) : m.end() + 30]
    print(f"  {repr(ctx)}")
