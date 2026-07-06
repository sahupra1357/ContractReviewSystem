"""Gate G4 eval — hybrid retrieval quality on labeled golden queries.

Usage (from backend/, after index_golden):
    CRS_DATABASE_URL=postgresql+psycopg://crs:crs@localhost:5433/crs \
        uv run python -m backend.eval.retrieval_eval [--rerank]

recall@10 ≥ 0.85: a query counts as satisfied when any top-10 hit lands in
the expected (documents × section) target. Queries target planted
deviations (unique docs) and standard clauses (document sets).
"""

import sys
from dataclasses import dataclass

from sqlalchemy import select

from backend.db import get_sessionmaker
from backend.knowledge.embedder import get_embedder
from backend.knowledge.retrieval import BgeReranker, search
from backend.models import Document

RECALL_AT_10_THRESHOLD = 0.85

LEASES = ["gs-0001", "gs-0002", "gs-0003", "gs-0004", "gs-0013", "gs-0016",
          "gs-0017", "gs-0018"]
PURCHASES = ["gs-0005", "gs-0006", "gs-0007", "gs-0008", "gs-0014",
             "gs-0019", "gs-0020"]
VENDORS = ["gs-0009", "gs-0010", "gs-0011", "gs-0012", "gs-0015",
           "gs-0021", "gs-0022"]


@dataclass
class EvalQuery:
    query: str
    docs: list[str]      # any of these …
    section: str         # … with this section id satisfies the query


QUERIES = [
    # planted deviations (specific documents)
    EvalQuery("lease renews automatically for 36 month periods without notice",
              ["gs-0003"], "sec-3"),
    EvalQuery("landlord liability is unlimited and uncapped",
              ["gs-0001", "gs-0013"], "sec-8"),
    EvalQuery("earnest money non-refundable under all circumstances",
              ["gs-0005", "gs-0019"], "sec-4"),
    EvalQuery("buyer waives all inspection rights and accepts as-is",
              ["gs-0007"], "sec-7"),
    EvalQuery("vendor may terminate at any time without notice",
              ["gs-0011", "gs-0021"], "sec-9"),
    # standard clauses (document families)
    EvalQuery("monthly rent due first of month with late fee grace period",
              LEASES, "sec-4"),
    EvalQuery("security deposit refundable within 30 days of lease end",
              LEASES, "sec-5"),
    EvalQuery("renter's insurance liability coverage 100,000 dollars",
              ["gs-0001", "gs-0002", "gs-0003", "gs-0013", "gs-0016", "gs-0018"],
              "sec-7"),
    EvalQuery("commercial general liability insurance 1,000,000 per occurrence",
              VENDORS, "sec-6"),
    EvalQuery("purchase price payable at closing by wire transfer to escrow",
              PURCHASES, "sec-3"),
    EvalQuery("seller conveys good and marketable title by warranty deed",
              PURCHASES, "sec-6"),
    EvalQuery("buyer may seek specific performance if seller defaults",
              PURCHASES, "sec-8"),
    EvalQuery("indemnify owner against claims arising from negligence",
              ["gs-0009", "gs-0010", "gs-0012", "gs-0015", "gs-0021", "gs-0022"],
              "sec-7"),
    EvalQuery("risk of loss remains with seller until closing",
              PURCHASES, "sec-9"),
    EvalQuery("services performed in professional workmanlike manner",
              VENDORS, "sec-5"),
    EvalQuery("tenant keeps premises clean landlord structural repairs",
              LEASES, "sec-6"),
]


def evaluate(use_rerank: bool) -> int:
    embedder = get_embedder()
    reranker = BgeReranker() if use_rerank else None
    satisfied_10 = satisfied_5 = 0

    with get_sessionmaker()() as session:
        gs_by_docid = {
            d.id: d.filename.rsplit(".", 1)[0]
            for d in session.execute(select(Document)).scalars()
        }
        for q in QUERIES:
            hits = search(session, embedder, q.query, k=10, reranker=reranker)
            match_rank = next(
                (i for i, h in enumerate(hits)
                 if gs_by_docid.get(h.document_id) in q.docs
                 and h.section_id == q.section),
                None,
            )
            if match_rank is not None:
                satisfied_10 += 1
                if match_rank < 5:
                    satisfied_5 += 1
            top = hits[0]
            print(f"  {'HIT ' if match_rank is not None else 'MISS'} "
                  f"@{match_rank if match_rank is not None else '-':<2} "
                  f"{q.query[:58]:58s} top: {gs_by_docid.get(top.document_id)}"
                  f"/{top.section_id}")

    n = len(QUERIES)
    r10, r5 = satisfied_10 / n, satisfied_5 / n
    ok = r10 >= RECALL_AT_10_THRESHOLD
    print(f"\n== Gate G4 results ({n} queries, rerank={'on' if use_rerank else 'off'}) ==")
    print(f"  {'PASS' if ok else 'FAIL'}  recall@10: {r10:.3f} (>= {RECALL_AT_10_THRESHOLD})")
    print(f"  info  recall@5:  {r5:.3f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(evaluate(use_rerank="--rerank" in sys.argv))
