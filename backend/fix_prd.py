"""Check and fix PRD.md references."""
import os

path = r"d:\Project\AI Tutors\01_Product\PRD.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print(f"Total chars: {len(content)}")
print(f"Total lines: {len(content.splitlines())}")

# Check for old version references
old_refs = {
    "DSD v2.0": "DSD (see 03_Data/DSD.md)",
    "SAD v1.1": "SAD (see 02_Architecture/SAD.md)",
    "TDD v1.4": "TDD consolidated into SAD V3.0",
    "MIS v1.3": "MIS (see 02_Architecture/MIS.md)",
    "ACS v1.1": "ACS (see 02_Architecture/ACS.md)",
    "TASK v1.1": "TASK (see 01_Product/TASK.md)",
    "Project Rules v1.1": "Project Rules (see 05_Development/Project rules.md)",
}

changed = False
for old, new in old_refs.items():
    if old in content:
        content = content.replace(old, new)
        changed = True
        print(f"Fixed: {old} -> {new}")

if changed:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("PRD.md updated")
else:
    print("No old references found - checking what version refs exist...")
    import re
    for m in re.finditer(r"v\d+\.\d+|V\d+\.\d+|MIS v\d+", content):
        ctx = content[max(0, m.start() - 15) : m.end() + 15]
        print(f"  Found: {repr(ctx)}")
