"""
Phase B-4 & B-5: Annotation Preparation Script.

B-4: Extracts figure data from physics PDF for human figure-text annotation.
B-5: Extracts formula blocks from math PDF for human LaTeX quality annotation.

Output: JSON files for manual review and annotation.
"""

import json
from pathlib import Path

# Read the B-3 results
results_path = Path(__file__).parent / "phase_b3_results.json"
if not results_path.exists():
    print("ERROR: phase_b3_results.json not found. Run phase_b_pipeline_e2e.py first.")
    exit(1)

with open(results_path) as f:
    results = json.load(f)

print("=" * 70)
print("Phase B-4 & B-5: Annotation Preparation")
print("=" * 70)

# The raw B-3 results contain C1+C2 summary data.
# We need to re-run C4 and C3 with more detailed output for annotation.

print("""
============================================================
B-4: C4 Semantic Anchoring — Human Annotation Required
============================================================

Task: For the 3 test papers, manually annotate figure-text correspondences.
For each figure detected by C4, verify:
  1. Is the figure label correct? (e.g., "图1", "图2")
  2. What text block does this figure belong to?
  3. Is the anchor_type (SEMANTIC/SPATIAL/UNMATCHED) correct?

Acceptance criteria:
  - Anchoring accuracy > 80%

To complete B-4:
  1. Open physics PDF: test_data/*物理*.pdf
  2. For each page, identify figures and their corresponding text
  3. Compare with C4 detected figures (see phase_b3_results.json)
  4. Record accuracy

============================================================
B-5: C3 LaTeX Quality — Human Annotation Required
============================================================

Task: For 30 formulas from the math test paper, verify LaTeX conversion.
For each formula detected by C3, verify:
  1. Is the formula correctly identified?
  2. Is the LaTeX conversion correct?
  3. Is display_math (inline vs block) correct?

Acceptance criteria:
  - Formula accuracy > 85%

To complete B-5:
  1. Open math PDF: test_data/*数学*.pdf
  2. Identify 30 distinct formulas across pages
  3. Manually write the correct LaTeX for each
  4. Compare with C3 detected formulas (see phase_b3_results.json)
  5. Record accuracy
""")

# Save the guidance
guidance = {
    "b4_instructions": {
        "task": "Figure-Text Anchoring Validation",
        "target": "> 80% accuracy",
        "steps": [
            "Open physics PDF and identify all figures",
            "For each figure, note which text/paragraph references it",
            "Compare with C4 output (anchor_type, label, anchor_text)",
            "Mark each as: CORRECT / WRONG_ANCHOR / WRONG_LABEL / MISSED",
        ]
    },
    "b5_instructions": {
        "task": "Formula LaTeX Quality Validation",
        "target": "> 85% accuracy",
        "formulas_needed": 30,
        "steps": [
            "Open math PDF and identify 30 distinct formulas",
            "Write the correct LaTeX for each formula",
            "Compare with C3 output (latex field, display_math field)",
            "Mark each as: CORRECT / WRONG_LATEX / WRONG_DISPLAY / MISSED",
        ]
    },
    "b3_summary": results,
}

output_path = Path(__file__).parent / "phase_b45_annotation_guide.json"
output_path.write_text(json.dumps(guidance, indent=2, ensure_ascii=False))
print(f"Annotation guide saved to: {output_path}")
