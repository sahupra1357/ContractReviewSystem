# Process Flow — end to end

Diagrams of the contract lifecycle as it is actually wired in code. Stage
chaining is by job enqueue (`backend/src/backend/jobs.py`); handlers are
registered in `backend/src/backend/worker.py`.

Source of truth for each edge:

| Edge | Code |
|---|---|
| upload → `extract` | `ingestion/core.py:76` |
| extract → `mask` | `extraction/service.py:222` |
| mask → `index` | `pii/service.py:121` |
| index → `analyze` | `knowledge/service.py:69` |
| extract-hold resolve → `extract` / `mask` | `api/extract.py:137`, `api/extract.py:159` |
| pii-hold resolve → `mask` | `api/pii.py:122` |
| `changes_requested` → `analyze` | `api/review.py:214` |

---

## 1. End-to-end pipeline

```mermaid
flowchart TD
    subgraph human1["Human — uploader"]
        U["Authenticated upload<br/>POST /ingest/upload"]
    end

    U --> DEDUP{"Content-hash<br/>already registered?"}
    DEDUP -->|yes| DUP["Rejected as duplicate<br/>audited"]
    DEDUP -->|no| REG["Register document<br/>store bytes in RAW zone<br/>status: ingested"]
    REG --> JX[["enqueue job: extract"]]

    subgraph rawzone["RAW ZONE — raw text never crosses the PII gate"]
        JX --> EXTRACT["Stage: extract<br/>classify → fast path or OCR chain<br/>→ segment into clauses"]
        EXTRACT --> EHOLD{"Extraction<br/>resolved?"}
        EHOLD -->|"all engines below threshold"| HOLD_E["status: extract_hold<br/>reason: low_confidence"]
        EHOLD -->|"page count > CRS_EXTRACT_MAX_PAGES"| HOLD_O["status: extract_hold<br/>reason: oversized"]
        EHOLD -->|ok| EXTRACTED["status: extracted"]

        HOLD_E --> RES_E{"Reviewer resolves<br/>POST /extract/holds/{id}/resolve"}
        HOLD_O --> RES_E
        RES_E -->|"accept best-effort<br/>+ rationale"| EXTRACTED
        RES_E -->|"accept oversized<br/>→ re-extract"| JX
        RES_E -->|"reject scan"| FAILED["status: failed_extract"]

        EXTRACTED --> JM[["enqueue job: mask"]]
        JM --> MASK["Stage: mask — THE PII GATE<br/>PII master table = only masking authority<br/>fuzzy / OCR-tolerant matching"]
        MASK --> TRIP{"Presidio tripwire:<br/>any unregistered entity?"}
        TRIP -->|"yes — fail closed"| HOLD_P["status: pii_hold<br/>document halts"]
        HOLD_P --> RES_P["Human resolves<br/>POST /pii/holds/{id}/resolve<br/>registers entity in master table"]
        RES_P --> JM
    end

    TRIP -->|"no unknown PII"| MASKED["Write MASKED zone<br/>status: masked"]

    subgraph maskedzone["MASKED ZONE — everything downstream reads only this"]
        MASKED --> JI[["enqueue job: index"]]
        JI --> INDEX["Stage: index<br/>BGE-M3 embeddings, hybrid retrieval<br/>Postgres graph-lite relations<br/>status: indexed"]
        INDEX --> JA[["enqueue job: analyze"]]
        JA --> ANALYZE["Stage: analyze<br/>template diff → deviations only<br/>STRONG model brief, citations mandatory<br/>FAST model key terms<br/>injection heuristics<br/>status: analyzed"]
    end

    ANALYZE --> QUEUE["Reviewer queue<br/>GET /review/queue"]

    subgraph human2["Human — reviewer, the only decision authority"]
        QUEUE --> CLAIM["Claim<br/>POST /review/contracts/{id}/claim<br/>status: in_review"]
        CLAIM --> DECIDE{"Decision + mandatory rationale<br/>POST /review/contracts/{id}/decision"}
        DECIDE -->|approve| APPROVED["status: approved"]
        DECIDE -->|reject| REJECTED["status: rejected"]
        DECIDE -->|request_changes| CHANGES["status: changes_requested"]
    end

    CHANGES --> JA

    APPROVED --> TERM["Terminal — worker skips these documents<br/>no job can overwrite a human decision"]
    REJECTED --> TERM

    AUDIT[("audit_events<br/>append-only, no UPDATE/DELETE")]
    EXTRACT -.-> AUDIT
    MASK -.-> AUDIT
    INDEX -.-> AUDIT
    ANALYZE -.-> AUDIT
    DECIDE -.-> AUDIT
    RES_E -.-> AUDIT
    RES_P -.-> AUDIT
    REG -.-> AUDIT
```

**Two structural guarantees visible above:** nothing leaves the raw zone
except through the mask stage, and no arrow reaches `approved`/`rejected`
except from the human decision endpoint.

---

## 2. Extraction detail — confidence-gated OCR chain, batched

```mermaid
flowchart TD
    START["Stage: extract"] --> CLASS{"Document type?"}
    CLASS -->|"born-digital PDF / DOCX"| FAST["Fast path — stream text<br/>no OCR, no checkpoint needed"]
    CLASS -->|"scanned PDF"| PAGES["Read page count cheaply"]

    PAGES --> CAP{"pages > CRS_EXTRACT_MAX_PAGES<br/>default 1000?"}
    CAP -->|yes| OVER["status: extract_hold<br/>reason: oversized<br/>human-routed"]
    CAP -->|no| BATCH["Split into batches of<br/>CRS_OCR_BATCH_SIZE, default 16"]

    BATCH --> SHARD{"Batch shard already in raw zone?<br/>{doc}/extract/batch-{n}.json"}
    SHARD -->|"yes — crash resume"| LOAD["Load shard, skip re-OCR"]
    SHARD -->|no| RAST["Rasterize this batch only<br/>peak memory = one batch"]

    RAST --> CHAIN["Per page: walk_chain"]

    subgraph chain["Engine chain — CRS_OCR_ENGINE_CHAIN"]
        CHAIN --> T["Tesseract<br/>confidence via image_to_data"]
        T --> C1{"conf ≥ 0.80?"}
        C1 -->|yes| WIN["Best result wins"]
        C1 -->|no| P["PaddleOCR"]
        P --> C2{"conf ≥ 0.80?"}
        C2 -->|yes| WIN
        C2 -->|no| E["EasyOCR"]
        E --> C3{"conf ≥ 0.80?"}
        C3 -->|yes| WIN
        C3 -->|no| D["Docling — last resort<br/>layout-aware rescue"]
        D --> C4{"conf ≥ 0.80?"}
        C4 -->|yes| WIN
        C4 -->|"no — every engine below"| LOW["Page unresolved"]
    end

    WIN --> CKPT["Persist batch shard<br/>checkpoint audit event"]
    LOW --> HOLD["status: extract_hold<br/>reason: low_confidence"]
    CKPT --> MORE{"More batches?"}
    MORE -->|yes| SHARD
    MORE -->|no| ASSEMBLE["Assemble ordered pages"]

    LOAD --> MORE
    FAST --> ASSEMBLE
    ASSEMBLE --> SEG["segment → clauses<br/>single extracted.json<br/>status: extracted"]
    SEG --> NEXT[["enqueue job: mask"]]

    HOLD --> RESOLVE{"POST /extract/holds/{id}/resolve"}
    OVER --> RESOLVE
    RESOLVE -->|"accept + rationale"| SEG
    RESOLVE -->|reject| FAIL["status: failed_extract"]
```

Engines whose library is not installed are skipped with an audit event — the
default image ships Tesseract only; the rest are the optional `ocr` extra.
Confidence is never fabricated: an engine that cannot report per-page
confidence reports unavailable instead.

---

## 3. Document status state machine

```mermaid
stateDiagram-v2
    [*] --> ingested: upload accepted

    ingested --> extracted: extract ok
    ingested --> extract_hold: low confidence / oversized
    extract_hold --> extracted: human accepts + rationale
    extract_hold --> failed_extract: human rejects scan
    failed_extract --> [*]

    extracted --> masking: mask job claimed
    masking --> pii_hold: unregistered entity detected
    pii_hold --> masking: entity registered, re-enqueued
    masking --> masked: deterministic masking complete

    masked --> indexed: embeddings + graph-lite
    indexed --> analyzed: AI brief with citations

    analyzed --> in_review: reviewer claims
    in_review --> approved: decision + rationale
    in_review --> rejected: decision + rationale
    in_review --> changes_requested: decision + rationale
    changes_requested --> analyzed: re-analyze

    approved --> [*]
    rejected --> [*]

    note right of approved
        Terminal. Reachable only from the
        authenticated human-decision API.
        Workers skip documents in these
        states — a failing job can never
        overwrite a human decision.
    end note
```

---

## 4. Deployment topology — local, and its AWS shape

```mermaid
flowchart LR
    subgraph local["docker-compose — the single environment definition"]
        FE["React SPA<br/>served from backend image"]
        API["FastAPI backend :8000"]
        WK["Worker<br/>claims jobs from Postgres queue"]
        PG[("Postgres + pgvector :5433<br/>documents, jobs, audit_events,<br/>PII master, embeddings")]
        S3[("MinIO :9000<br/>raw / masked / audit buckets")]
        PRES["Presidio<br/>analyzer"]
        LLM["LLM adapter<br/>CRS_LLM_PROVIDER"]
    end

    FE --> API
    API --> PG
    API --> S3
    WK --> PG
    WK --> S3
    WK --> PRES
    WK --> LLM

    local -.->|"1:1 production mapping — design doc §7"| aws

    subgraph aws["AWS target"]
        A1["API Gateway + ECS/Lambda"]
        A2["ECS/EKS workers, SQS consumers"]
        A3[("Aurora PostgreSQL + pgvector")]
        A4[("S3 + KMS")]
        A5["Presidio on ECS/EKS in-VPC"]
        A6["Bedrock"]
    end
```
