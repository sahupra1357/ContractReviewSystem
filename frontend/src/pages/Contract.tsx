import { useEffect, useState } from "react";
import {
  claimContract, decideContract, getAudit, getContract, getRole,
  type AuditEvent, type ClauseStatus, type ContractDetail,
} from "../api";

// Verdicts belong to the contract, never to the template — the template is
// the organization's source of truth and reads the same for every document.
// The one exception is a clause the contract omits: that fact has no contract
// clause to live on, so the template pane has to carry it.
const CONTRACT_CHIP: Record<ClauseStatus, string> = {
  standard: "matches standard",
  borderline: "differs slightly",
  deviation: "deviates from standard",
  missing: "",                       // never rendered on the contract side
  extra: "not in template",
};

const ABSENT_CHIP = "not in this contract";

/** Extraction hard-wraps lines mid-sentence; rejoin them into paragraphs so
 *  the pane fills its width instead of rendering a ragged half-empty column. */
function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean);
}

const templateDomId = (heading: string) =>
  `tpl-${heading.replace(/[^\w]+/g, "-")}`;

export default function Contract({ documentId }: { documentId: string }) {
  const [detail, setDetail] = useState<ContractDetail | null>(null);
  const [audit, setAudit] = useState<AuditEvent[] | null>(null);
  const [tab, setTab] = useState<"brief" | "audit">("brief");
  const [highlight, setHighlight] = useState<string | null>(null);
  const [templateFocus, setTemplateFocus] = useState<string | null>(null);
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = () =>
    getContract(documentId).then(setDetail).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    getAudit(documentId).then(setAudit).catch(() => setAudit([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  if (error) return <div className="error">{error}</div>;
  if (!detail) return <div className="loading">Loading contract…</div>;

  const { document: doc, analysis, reference_template: template } = detail;
  const reviewable = ["analyzed", "in_review"].includes(doc.status);
  const isReviewer = getRole() === "reviewer";

  const clauseBySection = new Map(
    (template?.clauses ?? [])
      .filter((c) => c.section_id)
      .map((c) => [c.section_id as string, c]),
  );

  /** Focus a clause in both panes at once — the standard wording on the left,
   *  the contract's version of it in the middle. */
  const focusClause = (sectionId: string | null, heading: string | null) => {
    setMessage(null);
    setHighlight(sectionId);
    setTemplateFocus(heading);
    if (sectionId) {
      document
        .getElementById(`sec-${sectionId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (heading) {
      document
        .getElementById(templateDomId(heading))
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const jumpToCitation = (citation: string) => {
    if (citation.startsWith("template:")) {
      // a missing clause has no contract text — the reference template pane
      // is the source
      const heading = citation.split(":").slice(2).join(":");
      focusClause(null, heading);
      setMessage(`Clause absent from the contract — see the standard wording: ${heading}`);
      return;
    }
    const chunk = detail.chunks.find((c) => c.chunk_id === citation);
    if (!chunk) return;
    focusClause(chunk.section_id, clauseBySection.get(chunk.section_id)?.heading ?? null);
  };

  const decide = async (action: string) => {
    setError(null);
    try {
      if (doc.status === "analyzed") await claimContract(documentId);
      await decideContract(documentId, action, rationale);
      setMessage(`Decision recorded: ${action.replace("_", " ")}`);
      setRationale("");
      refresh();
      getAudit(documentId).then(setAudit);
    } catch (e) {
      setError(e instanceof Error ? e.message : "decision failed");
    }
  };

  const renderSource = () => {
    if (!detail.masked_text) {
      return <div className="empty">Masked text not available (status: {doc.status}).</div>;
    }
    if (detail.sections.length === 0) {
      return paragraphs(detail.masked_text).map((p, i) => <p key={i}>{p}</p>);
    }
    return detail.sections.map((s) => {
      const raw = detail.masked_text!.slice(s.start, s.end).trim();
      const body = paragraphs(raw.replace(/^[^\n]*\n?/, ""));
      const clause = clauseBySection.get(s.section_id);
      return (
        <div key={s.section_id} id={`sec-${s.section_id}`}
             className={`clause ${clause && clause.status !== "standard"
               ? `clause-${clause.status}` : ""} ${
               highlight === s.section_id ? "clause-hl" : ""}`}
             onClick={() => focusClause(s.section_id, clause?.heading ?? null)}>
          <div className="clause-head">
            <span className="clause-heading">{s.heading}</span>
            {clause && (
              <span className={`chip chip-${clause.status}`}>
                {CONTRACT_CHIP[clause.status]}
                {clause.similarity !== null && ` ${Math.round(clause.similarity * 100)}%`}
              </span>
            )}
          </div>
          {body.map((p, i) => <p key={i}>{p}</p>)}
          {clause?.sent_to_llm && (
            <p className="hint-inline">→ sent to the model for review</p>
          )}
        </div>
      );
    });
  };

  const renderTemplate = () => {
    if (!template) {
      return (
        <div className="empty">
          No template baseline — the contract family was not identified, so the
          document is routed to full manual review.
        </div>
      );
    }
    return (
      <>
        <p className="hint">
          The organization's <strong>standard wording</strong> for{" "}
          <span className="mono">{template.family}</span> — the baseline every
          contract in this family is measured against.
        </p>
        <div className="source-scroll">
          {/* sections the contract adds are not part of the standard, so they
              are shown on the contract side only */}
          {template.clauses.filter((c) => c.status !== "extra").map((c) => {
            const absent = c.status === "missing";
            return (
              <div key={c.heading} id={templateDomId(c.heading)}
                   className={`clause ${absent ? "clause-missing" : ""} ${
                     templateFocus === c.heading ? "clause-hl" : ""}`}
                   onClick={() => focusClause(c.section_id, c.heading)}>
                <div className="clause-head">
                  <span className="clause-heading">{c.heading}</span>
                  {absent && <span className="chip chip-missing">{ABSENT_CHIP}</span>}
                </div>
                <p className="template-text">{c.template_text}</p>
              </div>
            );
          })}
        </div>
      </>
    );
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{doc.filename}</h1>
          <p className="sub">
            uploaded by {doc.uploaded_by} ·{" "}
            <span className={`badge badge-status-${doc.status}`}>{doc.status}</span>
            {analysis && <> · family <strong>{analysis.family}</strong></>}
          </p>
        </div>
        <a href="#/queue" className="btn btn-ghost">← Queue</a>
      </div>
      {message && <div className="notice">{message}</div>}
      {error && <div className="error">{error}</div>}

      {/* reads left to right: the standard, then this contract, then the verdict */}
      <div className="split split-3">
        <section className="pane">
          <h2>
            Reference template{" "}
            {template && <span className="hint-inline">{template.title}</span>}
          </h2>
          {renderTemplate()}
        </section>

        <section className="pane">
          <h2>Masked contract <span className="hint-inline">(PII never shown)</span></h2>
          <div className="source-scroll">{renderSource()}</div>
        </section>

        <section className="pane">
          <div className="tabs">
            <button className={tab === "brief" ? "tab active" : "tab"}
                    onClick={() => setTab("brief")}>Review brief</button>
            <button className={tab === "audit" ? "tab active" : "tab"}
                    onClick={() => setTab("audit")}>Audit trail</button>
          </div>

          {tab === "brief" && (
            <>
              {!analysis && <div className="empty">No analysis yet.</div>}
              {analysis && (
                <>
                  <div className="ai-suggests">
                    AI suggests:{" "}
                    <span className={`badge badge-${analysis.suggested_decision}`}>
                      {analysis.suggested_decision.replace("_", " ")}
                    </span>
                    <p className="rationale">{analysis.rationale}</p>
                    <p className="hint-inline">
                      models {analysis.models.strong} / {analysis.models.fast} ·{" "}
                      {(analysis.latency_ms / 1000).toFixed(1)}s
                    </p>
                  </div>
                  <h3>Findings ({analysis.findings.length})</h3>
                  {analysis.findings.length === 0 && (
                    <div className="empty">No deviations from the standard template.</div>
                  )}
                  {analysis.findings.map((f, i) => (
                    <div key={i} className={`finding finding-${f.severity}`}>
                      <div className="finding-head">
                        <span className={`badge badge-sev-${f.severity}`}>{f.severity}</span>
                        <strong>{f.title}</strong>
                      </div>
                      <p>{f.description}</p>
                      <button className="citation" onClick={() => jumpToCitation(f.citation)}>
                        ⌖ view source
                      </button>
                    </div>
                  ))}
                  {analysis.key_terms && Object.keys(analysis.key_terms).length > 0 && (
                    <>
                      <h3>Key terms</h3>
                      <table className="table table-sm">
                        <tbody>
                          {Object.entries(analysis.key_terms)
                            .filter(([k]) => !k.startsWith("_"))
                            .map(([k, v]) => (
                              <tr key={k}>
                                <td className="mono">{k}</td>
                                <td>{Array.isArray(v) ? v.join(", ") : String(v)}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </>
                  )}
                </>
              )}

              {detail.decisions.length > 0 && (
                <>
                  <h3>Decisions</h3>
                  {detail.decisions.map((d, i) => (
                    <div key={i} className="decision-log">
                      <span className={`badge badge-${d.action}`}>{d.action}</span>{" "}
                      by <strong>{d.reviewer}</strong> — {d.rationale}
                    </div>
                  ))}
                </>
              )}

              {reviewable && isReviewer && (
                <div className="decision-panel">
                  <h3>Your decision <span className="hint-inline">(rationale required — audited)</span></h3>
                  <textarea
                    placeholder="Rationale for this decision…"
                    value={rationale}
                    onChange={(e) => setRationale(e.target.value)}
                  />
                  <div className="decision-buttons">
                    <button className="btn btn-approve" disabled={!rationale.trim()}
                            onClick={() => decide("approve")}>Approve</button>
                    <button className="btn btn-changes" disabled={!rationale.trim()}
                            onClick={() => decide("request_changes")}>Request changes</button>
                    <button className="btn btn-reject" disabled={!rationale.trim()}
                            onClick={() => decide("reject")}>Reject</button>
                  </div>
                </div>
              )}
              {reviewable && !isReviewer && (
                <div className="notice">Decisions require the reviewer role.</div>
              )}
            </>
          )}

          {tab === "audit" && (
            <div className="audit-list">
              {(audit ?? []).map((e, i) => (
                <div key={i} className="audit-row">
                  <span className={`badge badge-actor-${e.actor_type}`}>{e.actor_type}</span>
                  <span className="mono">{e.actor_id}</span>
                  <strong>{e.action}</strong>
                  <span className="hint-inline">{new Date(e.created_at).toLocaleString()}</span>
                  {e.rationale && <em>— {e.rationale}</em>}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
