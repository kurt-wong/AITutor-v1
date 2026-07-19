"""Fix all 5 document issues."""
import os


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# Fix 1: PRD.md - update references
path = r"d:\Project\AI Tutors\01_Product\PRD.md"
content = read_file(path)

# Find and replace old version references
replacements = {
    "DSD v2.0": "- DSD (see 03_Data/DSD.md)",
    "SAD v1.1": "- SAD (see 02_Architecture/SAD.md)",
    "TDD v1.4": "> TDD v1.4 consolidated into SAD V3.0",
    "MIS v1.3": "- MIS (see 02_Architecture/MIS.md)",
    "ACS v1.1": "- ACS (see 02_Architecture/ACS.md)",
    "TASK v1.1": "- TASK (see 01_Product/TASK.md)",
    "Project Rules v1.1": "- Project Rules (see 05_Development/Project rules.md)",
}

changed = False
for old, new in replacements.items():
    if old in content:
        content = content.replace(old, new)
        changed = True

if changed:
    write_file(path, content)
    print("Fix 1 OK: PRD references updated")
else:
    print("Fix 1 SKIP: no old references found in PRD.md")


# Fix 2: DSD.md - align Repository interfaces with table definitions
path = r"d:\Project\AI Tutors\03_Data\DSD.md"
content = read_file(path)

# Fix document_page_id -> document_id in QuestionRepo
if "document_page_id" in content:
    content = content.replace("document_page_id", "document_id")
    write_file(path, content)
    print("Fix 2 OK: DSD document_page_id -> document_id")
else:
    print("Fix 2 SKIP: document_page_id not found")


# Fix 3: TASK.md - add Phase 0 DoD
path = r"d:\Project\AI Tutors\01_Product\TASK.md"
content = read_file(path)

phase0_marker = "# 1. Phase 0"
if phase0_marker in content and "Phase 0 Definition of Done" not in content:
    phase0_dod = """
# 1. Phase 0 — Infrastructure Foundation

> **Phase 0 Definition of Done (relaxed):**
> - Service starts successfully
> - Connection to infra verified
> - Configuration loads from env
> - No MCP Integration Test required (no business logic yet)

"""
    content = content.replace(
        "# 1. Phase 0 — Infrastructure Foundation\n",
        phase0_dod,
    )
    write_file(path, content)
    print("Fix 3 OK: Phase 0 DoD added to TASK.md")
else:
    print("Fix 3 SKIP: Phase 0 DoD already exists or marker not found")


# Fix 4: DEVELOPMENT WORKFLOW.md - fix V1.1 reference
path = r"d:\Project\AI Tutors\05_Development\DEVELOPMENT WORKFLOW.md"
content = read_file(path)

if "TASK.md V1.1" in content:
    content = content.replace("TASK.md V1.1", "TASK.md V1.0")
    write_file(path, content)
    print("Fix 4 OK: WORKFLOW V1.1 -> V1.0")
elif "V1.1" in content:
    # Check context
    idx = content.find("V1.1")
    context = content[max(0, idx - 30) : idx + 30]
    print(f"Fix 4: Found V1.1 in context: {repr(context)}")
    content = content.replace("V1.1", "V1.0")
    write_file(path, content)
    print("Fix 4 OK: All V1.1 -> V1.0")
else:
    print("Fix 4 SKIP: V1.1 not found")


# Fix 5: Project rules.md - relax MCP tool composition rule
path = r"d:\Project\AI Tutors\05_Development\Project rules.md"
content = read_file(path)

old_rule = "MCP tools MUST NOT call other MCP tools internally"
new_rule = """MCP tools within the SAME Server MUST NOT call each other (avoid circular dependency).
Cross-Server MCP tool calls are allowed ONLY through Service-layer orchestration."""

if old_rule in content:
    content = content.replace(old_rule, new_rule)
    write_file(path, content)
    print("Fix 5 OK: MCP composition rule relaxed")
else:
    print("Fix 5 SKIP: rule text not found")

print("\nAll fixes applied.")
