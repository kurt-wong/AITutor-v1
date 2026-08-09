"""Tests for QuestionImagesRenderer placement logic (S#174).

Verifies that placement=null images are rendered exactly once in fallback,
not duplicated across placement groups, and not lost when no placements prop.
"""


class TestQuestionImagesRendererPlacement:
    """Pure logic tests for image grouping (no React rendering)."""

    def _group(self, images, placements=None):
        """Replicate the grouping logic from QuestionImagesRenderer.tsx."""
        target = placements or ["stem", "explanation", "page_context", "associated"]

        def by_placement(p):
            return [img for img in images if img.get("placement") == p]

        null_placement = [img for img in images if not img.get("placement")]

        stem = by_placement("stem") if "stem" in target else []
        expl = by_placement("explanation") if "explanation" in target else []
        ctx = []
        if "page_context" in target:
            ctx.extend(by_placement("page_context"))
        if "associated" in target:
            ctx.extend(by_placement("associated"))

        return {
            "stem": stem,
            "explanation": expl,
            "page_context_ctx": ctx,
            "fallback": null_placement,
        }

    def test_null_placement_not_in_stem_group(self):
        """placement=null image must NOT appear in stem group."""
        images = [
            {"image_id": 1, "placement": None},
            {"image_id": 2, "placement": "stem"},
        ]
        groups = self._group(images, placements=["stem"])
        assert len(groups["stem"]) == 1
        assert groups["stem"][0]["image_id"] == 2
        assert len(groups["fallback"]) == 1
        assert groups["fallback"][0]["image_id"] == 1

    def test_null_placement_not_duplicated_across_groups(self):
        """placement=null image must appear ONLY in fallback, not in any placement group."""
        images = [
            {"image_id": 1, "placement": None},
            {"image_id": 2, "placement": "explanation"},
        ]
        groups = self._group(images, placements=["explanation", "page_context"])
        # Should NOT be in explanation group
        assert all(img["image_id"] != 1 for img in groups["explanation"])
        # Should be in fallback exactly once
        assert len(groups["fallback"]) == 1
        assert groups["fallback"][0]["image_id"] == 1

    def test_null_placement_rendered_when_no_placements_prop(self):
        """placement=null image must render in fallback even when placements is undefined."""
        images = [
            {"image_id": 1, "placement": None},
            {"image_id": 2, "placement": "stem"},
        ]
        groups = self._group(images)  # no placements prop
        assert len(groups["fallback"]) == 1
        assert groups["fallback"][0]["image_id"] == 1
        assert len(groups["stem"]) == 1
        assert groups["stem"][0]["image_id"] == 2

    def test_only_null_placement(self):
        """All images have null placement → all go to fallback."""
        images = [
            {"image_id": 1, "placement": None},
            {"image_id": 2, "placement": None},
        ]
        groups = self._group(images)
        assert len(groups["fallback"]) == 2
        assert len(groups["stem"]) == 0
        assert len(groups["explanation"]) == 0

    def test_mixed_placements_no_duplicates(self):
        """Full mix: each image appears in exactly one group."""
        images = [
            {"image_id": 1, "placement": "stem"},
            {"image_id": 2, "placement": "explanation"},
            {"image_id": 3, "placement": "page_context"},
            {"image_id": 4, "placement": None},
            {"image_id": 5, "placement": "associated"},
        ]
        groups = self._group(images)
        all_ids = set()
        for group_name in ["stem", "explanation", "page_context_ctx", "fallback"]:
            for img in groups[group_name]:
                assert img["image_id"] not in all_ids, f"Duplicate: {img['image_id']} in {group_name}"
                all_ids.add(img["image_id"])
        assert all_ids == {1, 2, 3, 4, 5}

    def test_empty_images(self):
        """Empty list → all groups empty."""
        groups = self._group([])
        assert all(len(v) == 0 for v in groups.values())

    def test_placement_filtered_out(self):
        """When placements=["stem"], explanation images are excluded entirely."""
        images = [
            {"image_id": 1, "placement": "stem"},
            {"image_id": 2, "placement": "explanation"},
        ]
        groups = self._group(images, placements=["stem"])
        assert len(groups["stem"]) == 1
        assert len(groups["explanation"]) == 0
        assert len(groups["fallback"]) == 0
