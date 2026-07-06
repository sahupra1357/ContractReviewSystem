---
name: add-connector
description: Add a new document-source connector (SharePoint, DocuSign, Email, or any future source) behind the connector interface. Use when the user asks to support a new contract source or modify Filesystem/DMS ingestion.
---

# Adding a source connector

Reference: `docs/03_design_document.md` §3.1. The connector interface exists so
new sources plug in with **zero core-pipeline changes** — that expandability
claim was confirmed with the product owner and is gate-checked (G1).

## Step-by-step

1. **Confirm scope first.** POC scope is the UploadConnector (authenticated
   multi-file upload page) only — OQ-1 resolution, 2026-07-05. DMS and
   shared-filesystem connectors arrive at pre-prod; SharePoint/DocuSign/Email
   later still. Confirm with the product owner before building any of them
   unless they explicitly asked.

2. **Implement the interface only.** Subclass the abstract connector:
   - `poll()` — list new `SourceDocument`s (id, metadata) since last ack.
   - `fetch(id)` — return raw bytes + source metadata.
   - `ack(id)` — mark consumed at the source.
   Do not touch dedup, the registry, or downstream stages — the ingestion
   core owns those.

3. **Credentials via configuration.** Secrets come from env/config (POC) —
   Secrets Manager in production (design doc §7). Never hardcode endpoints or
   tokens; never log them.

4. **Respect the containment posture.** External sources are the only
   permitted egress (per the security review). Document exactly what the
   connector talks to, on which protocol, so the production allow-list can be
   derived from your notes.

5. **Metadata mapping.** Map source metadata to the registry's common fields
   (title, party hints, dates, urgency signals for the triage queue). Sources
   are "mostly consistent" per the product owner — where a field is missing,
   leave it null; do not invent values.

6. **Tests:**
   - Unit: poll/fetch/ack against a fake source.
   - Integration: documents from the new connector land once (dedup works,
     including a planted duplicate), reach `ingested`, and appear in the
     audit trail with the correct source attribution.
   - Prove the expandability claim: the diff must not touch core pipeline code.

7. **Document it.** Add the connector to design doc §3.1 with its AWS
   production mapping (e.g., SharePoint → AppFlow private connector).
