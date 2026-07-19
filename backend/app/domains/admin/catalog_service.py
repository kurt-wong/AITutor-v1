"""
Admin Catalog Service — T11-06: Catalog tree query.

Builds hierarchical tree: subject → grade → category.
Integrates with documents table's subject/grade/category fields.

Architecture rules:
- No direct DB access (uses DocumentRepository)
- No real LLM calls
"""

from typing import Any

from app.core.logging import get_logger
from app.domains.document.repository import DocumentRepository

logger = get_logger("admin.catalog")


class CatalogService:
    """Builds hierarchical catalog tree from document classifications.

    Tree structure:
    {
        "subjects": [
            {
                "name": "数学",
                "grades": [
                    {
                        "name": "初一",
                        "categories": [
                            {"name": "试卷", "document_count": 5},
                            {"name": "练习", "document_count": 3},
                        ],
                        "document_count": 8
                    }
                ],
                "document_count": 20
            }
        ],
        "total_documents": 50
    }
    """

    def __init__(self, session):
        self.session = session
        self.doc_repo = DocumentRepository(session)

    async def get_catalog_tree(self) -> list[dict[str, Any]]:
        """Build and return the full catalog tree as a list of subjects.

        Delegates SQL aggregation to repository (per ARCH-01 fix).
        """
        rows = await self.doc_repo.count_by_catalog()

        # Build nested dict structure
        tree: dict[str, dict] = {}  # subject -> grade -> category

        for subject, grade, category, count in rows:
            subj = subject or "未分类"
            grd = grade or "未分类"
            cat = category or "未分类"

            if subj not in tree:
                tree[subj] = {}
            if grd not in tree[subj]:
                tree[subj][grd] = {}
            tree[subj][grd][cat] = count

        # Convert to list hierarchy
        subjects_list = []
        total_docs = 0

        for subj_name in sorted(tree.keys()):
            grades_dict = tree[subj_name]
            grades_list = []
            subj_total = 0

            for grade_name in sorted(grades_dict.keys()):
                cats_dict = grades_dict[grade_name]
                cats_list = []
                grade_total = 0

                for cat_name in sorted(cats_dict.keys()):
                    count = cats_dict[cat_name]
                    cats_list.append({"name": cat_name, "document_count": count})
                    grade_total += count

                grades_list.append({
                    "name": grade_name,
                    "categories": cats_list,
                    "document_count": grade_total,
                })
                subj_total += grade_total

            subjects_list.append({
                "name": subj_name,
                "grades": grades_list,
                "document_count": subj_total,
            })
            total_docs += subj_total

        return subjects_list
