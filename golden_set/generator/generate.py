"""Deterministic golden-set generator (seeded — same corpus every run).

Usage (from backend/):  uv run python ../golden_set/generator/generate.py

Writes golden_set/docs/<doc-id>/{document.*, labels.yaml, source.txt} and
golden_set/master_table_seed.yaml. Never edit generated docs by hand —
regenerate with a new plan instead (freeze rule in golden_set/README.md).
"""

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from docx import Document as DocxDocument
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from templates import FAMILIES  # noqa: E402

OUT = Path(__file__).parent.parent
SEED = 42

# ---------------------------------------------------------------- entities
# Registered = present in the PII master table seed (deterministic layer
# masks these). Novel = NOT registered; the tripwire must halt these docs.
REGISTERED = {
    "org": ["Acme Property Holdings LLC", "Globex Maintenance Inc",
            "Sunrise Realty Partners LP", "Cascade Property Group LLC"],
    "person": ["Jordan Rivera", "Maria Chen", "Samuel Okafor", "Priya Nair"],
    "account": ["4471-3920-0011", "8830-1276-5544"],
    "address": ["1200 Harbor View Drive, Seattle, WA",
                "88 Juniper Lane, Portland, OR"],
}
NOVEL = {
    "org": ["Bluefin Restoration Co", "Northgate Elevator Services Ltd"],
    "person": ["Tobias Lindqvist", "Amara Diallo"],
    "account": ["7719-4402-8873"],
    "address": ["47 Old Mill Road, Spokane, WA"],
}

ISSUES = {
    "lease-uncapped-liability": dict(
        section="8. LIABILITY", severity="high",
        text="Landlord's liability under this Lease is unlimited and Tenant "
             "waives no claims of any kind.",
        description="Uncapped landlord liability — deviates from lease-v1 12-month rent cap"),
    "lease-missing-insurance": dict(
        section="7. INSURANCE", severity="medium", remove=True,
        description="Insurance clause missing entirely (template requires renter's insurance)"),
    "lease-long-autorenew": dict(
        section="3. TERM", severity="medium",
        text="The initial term of this Lease is {term_months} months. This "
             "Lease renews automatically for successive 36-month periods "
             "without notice to Tenant.",
        description="Auto-renewal of 36 months without notice — deviates from 12-month/60-day-notice standard"),
    "purchase-nonrefundable-earnest": dict(
        section="4. EARNEST MONEY", severity="high",
        text="Buyer shall deposit {deposit_amount} as earnest money, which is "
             "non-refundable under all circumstances including failed contingencies.",
        description="Earnest money non-refundable even on failed contingency — deviates from purchase-v1"),
    "purchase-inspection-waiver": dict(
        section="7. INSPECTION", severity="medium",
        text="Buyer waives all rights of inspection and accepts the Property "
             "strictly as-is.",
        description="Inspection rights waived — deviates from 10-day inspection standard"),
    "vendor-no-liability-cap": dict(
        section="8. LIABILITY CAP", severity="high", remove=True,
        description="Liability cap section missing — vendor-services-v1 requires mutual 12-month cap"),
    "vendor-unilateral-termination": dict(
        section="9. TERMINATION", severity="medium",
        text="Vendor may terminate this Agreement at any time without notice; "
             "Owner may terminate only after a 180-day cure period.",
        description="One-sided termination favoring Vendor — deviates from mutual 30-day standard"),
    "vendor-missing-indemnity": dict(
        section="7. INDEMNIFICATION", severity="medium", remove=True,
        description="Indemnification clause missing (template requires vendor indemnity)"),
}

# ------------------------------------------------------------------- plan
@dataclass
class DocPlan:
    doc_id: str
    family: str
    fmt: str                      # born-digital-pdf | docx | scanned-pdf
    issues: list[str] = field(default_factory=list)
    novel_pii: bool = False
    poor_scan: bool = False


PLAN = [
    # 12 born-digital PDFs
    DocPlan("gs-0001", "lease-v1", "born-digital-pdf", ["lease-uncapped-liability"]),
    DocPlan("gs-0002", "lease-v1", "born-digital-pdf", []),
    DocPlan("gs-0003", "lease-v1", "born-digital-pdf", ["lease-long-autorenew"], novel_pii=True),
    DocPlan("gs-0004", "lease-v1", "born-digital-pdf", ["lease-missing-insurance"]),
    DocPlan("gs-0005", "purchase-v1", "born-digital-pdf", ["purchase-nonrefundable-earnest"]),
    DocPlan("gs-0006", "purchase-v1", "born-digital-pdf", []),
    DocPlan("gs-0007", "purchase-v1", "born-digital-pdf", ["purchase-inspection-waiver"], novel_pii=True),
    DocPlan("gs-0008", "purchase-v1", "born-digital-pdf", []),
    DocPlan("gs-0009", "vendor-services-v1", "born-digital-pdf", ["vendor-no-liability-cap"]),
    DocPlan("gs-0010", "vendor-services-v1", "born-digital-pdf", []),
    DocPlan("gs-0011", "vendor-services-v1", "born-digital-pdf",
            ["vendor-unilateral-termination", "vendor-missing-indemnity"], novel_pii=True),
    DocPlan("gs-0012", "vendor-services-v1", "born-digital-pdf", []),
    # 4 DOCX
    DocPlan("gs-0013", "lease-v1", "docx", ["lease-uncapped-liability"]),
    DocPlan("gs-0014", "purchase-v1", "docx", [], novel_pii=True),
    DocPlan("gs-0015", "vendor-services-v1", "docx", ["vendor-no-liability-cap"]),
    DocPlan("gs-0016", "lease-v1", "docx", []),
    # 6 scanned (2 per family; 2 poor quality)
    DocPlan("gs-0017", "lease-v1", "scanned-pdf", ["lease-missing-insurance"]),
    DocPlan("gs-0018", "lease-v1", "scanned-pdf", [], novel_pii=True, poor_scan=True),
    DocPlan("gs-0019", "purchase-v1", "scanned-pdf", ["purchase-nonrefundable-earnest"]),
    DocPlan("gs-0020", "purchase-v1", "scanned-pdf", []),
    DocPlan("gs-0021", "vendor-services-v1", "scanned-pdf",
            ["vendor-unilateral-termination"], novel_pii=True, poor_scan=True),
    DocPlan("gs-0022", "vendor-services-v1", "scanned-pdf", []),
]


# ------------------------------------------------------------- generation
def build_slots(rng: random.Random, family: str, novel: bool) -> tuple[dict, list[dict]]:
    """Fill template slots; return (slots, pii labels)."""
    pick = lambda pool: rng.choice(pool)  # noqa: E731
    org_pool = REGISTERED["org"] if not novel else NOVEL["org"]
    person_pool = REGISTERED["person"] if not novel else NOVEL["person"]
    account = pick(NOVEL["account"] if novel else REGISTERED["account"])
    address = pick(NOVEL["address"] if novel else REGISTERED["address"])

    org_a = pick(REGISTERED["org"])
    org_b = pick(org_pool)
    while org_b == org_a:
        org_b = pick(org_pool if novel else REGISTERED["org"])
    person_a = pick(REGISTERED["person"])
    person_b = pick(person_pool)

    common = dict(
        effective_date=f"2026-0{rng.randint(1, 6)}-1{rng.randint(0, 5)}",
        closing_date=f"2026-1{rng.randint(0, 1)}-0{rng.randint(1, 9)}",
        term_months=str(rng.choice([12, 24, 36])),
        monthly_amount=f"USD {rng.randint(2, 9)},{rng.randint(100, 999)}",
        deposit_amount=f"USD {rng.randint(3, 20)},000",
        purchase_price=f"USD {rng.randint(400, 950)},000",
        state=rng.choice(["Washington", "Oregon"]),
        service_type=rng.choice(["landscaping", "HVAC maintenance", "janitorial"]),
        account=account, address=address,
    )
    if family == "lease-v1":
        slots = dict(common, landlord=org_a, tenant=person_b, landlord_signer=person_a)
        parties = [org_a, person_b, person_a]
    elif family == "purchase-v1":
        slots = dict(common, seller=org_a, buyer=person_b, seller_signer=person_a)
        parties = [org_a, person_b, person_a]
    else:
        slots = dict(common, owner=org_a, vendor=org_b,
                     owner_signer=person_a, vendor_signer=person_b)
        parties = [org_a, org_b, person_a, person_b]

    registered_flat = {v for pool in REGISTERED.values() for v in pool}
    pii = []
    seen = set()
    for text, typ in (
        [(p, "ORG" if p.endswith(("LLC", "Inc", "LP", "Co", "Ltd")) else "PERSON")
         for p in parties]
        + [(account, "ACCOUNT"), (address, "ADDRESS")]
    ):
        if text not in seen:
            seen.add(text)
            pii.append(dict(text=text, type=typ, registered=text in registered_flat))
    return slots, pii


def render_text(family: str, slots: dict, issue_ids: list[str]) -> tuple[str, list[dict], list[str]]:
    """Return (full text, known_issues labels, section headings present)."""
    template = FAMILIES[family]
    issues = [dict(ISSUES[i], id=i) for i in issue_ids]
    by_section = {i["section"]: i for i in issues}
    lines = [template["title"], ""]
    headings = []
    known = []
    for heading, body in template["sections"]:
        issue = by_section.get(heading)
        if issue and issue.get("remove"):
            known.append(dict(id=issue["id"], clause_ref=heading,
                              description=issue["description"], severity=issue["severity"]))
            continue
        text = (issue["text"] if issue else body).format(**slots)
        if issue:
            known.append(dict(id=issue["id"], clause_ref=heading,
                              description=issue["description"], severity=issue["severity"]))
        lines.append(heading)
        lines.append(text)
        lines.append("")
        headings.append(heading)
    return "\n".join(lines).strip() + "\n", known, headings


def write_pdf(path: Path, text: str) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    for line in text.split("\n"):
        pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def write_docx(path: Path, text: str) -> None:
    doc = DocxDocument()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.save(str(path))


def write_scanned_pdf(path: Path, text: str, rng: random.Random, poor: bool) -> None:
    """Render text to images (no text layer) and save as an image-only PDF."""
    font = ImageFont.load_default(size=28)
    lines = text.split("\n")
    per_page = 55
    pages = []
    for start in range(0, len(lines), per_page):
        img = Image.new("L", (1700, 2200), 255)
        draw = ImageDraw.Draw(img)
        y = 60
        for line in lines[start:start + per_page]:
            draw.text((90, y), line, font=font, fill=20)
            y += 38
        if poor:
            img = img.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=255)
            img = img.filter(ImageFilter.GaussianBlur(radius=0.9))
            noise = [(rng.randint(0, 1699), rng.randint(0, 2199)) for _ in range(4000)]
            px = img.load()
            for x, y2 in noise:
                px[x, y2] = rng.randint(0, 255)
        pages.append(img.convert("RGB"))
    pages[0].save(str(path), save_all=True, append_images=pages[1:], format="PDF")


def main() -> None:
    rng = random.Random(SEED)
    docs_dir = OUT / "docs"
    docs_dir.mkdir(exist_ok=True)

    for plan in PLAN:
        slots, pii = build_slots(rng, plan.family, plan.novel_pii)
        text, known_issues, headings = render_text(plan.family, slots, plan.issues)
        doc_dir = docs_dir / plan.doc_id
        doc_dir.mkdir(exist_ok=True)

        if plan.fmt == "born-digital-pdf":
            filename = "document.pdf"
            write_pdf(doc_dir / filename, text)
        elif plan.fmt == "docx":
            filename = "document.docx"
            write_docx(doc_dir / filename, text)
        else:
            filename = "document.pdf"
            write_scanned_pdf(doc_dir / filename, text, rng, plan.poor_scan)

        (doc_dir / "source.txt").write_text(text)
        labels = dict(
            doc_id=plan.doc_id,
            family=plan.family,
            format=plan.fmt,
            poor_scan=plan.poor_scan,
            filename=filename,
            pii=pii,
            has_novel_pii=plan.novel_pii,
            key_terms={k: v for k, v in slots.items()
                       if k in ("effective_date", "term_months", "monthly_amount",
                                "deposit_amount", "purchase_price", "closing_date")},
            expected_sections=headings,
            known_issues=known_issues,
            expected_clean=not known_issues,
        )
        (doc_dir / "labels.yaml").write_text(yaml.safe_dump(labels, sort_keys=False))
        print(f"  {plan.doc_id}  {plan.family:20s} {plan.fmt:16s} "
              f"issues={len(known_issues)} novel_pii={plan.novel_pii}")

    seed = {typ: values for typ, values in REGISTERED.items()}
    (OUT / "master_table_seed.yaml").write_text(yaml.safe_dump(seed, sort_keys=False))
    print(f"\nWrote {len(PLAN)} documents + master_table_seed.yaml under {OUT}")


if __name__ == "__main__":
    main()
