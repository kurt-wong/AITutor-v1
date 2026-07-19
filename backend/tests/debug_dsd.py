from pathlib import Path
src = Path("alembic/versions/001_initial_schema.py").read_text(encoding="utf-8")
# Find solutions table block
idx = src.find('"solutions"')
print(f"First '\"solutions\"' found at index: {idx}")
print(f"Context: {repr(src[idx:idx+50])}")
# Find next occurrence after the first
idx2 = src.find('"solutions"', idx+1)
print(f"Second '\"solutions\"' at: {idx2}")
# Find solution_versions
sv_idx = src.find('"solution_versions"')
print(f"First '\"solution_versions\"' at: {sv_idx}")
# Check what's between them
section = src[idx:sv_idx]
print(f"Section length: {len(section)}")
print(f"Contains CASCADE: {'CASCADE' in section}")
# Print the section
print("--- Section ---")
print(section[:500])
