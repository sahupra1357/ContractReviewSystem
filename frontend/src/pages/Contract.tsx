import { useEffect, useState } from "react";
import {
  claimContract, decideContract, getAudit, getContract, getRole,
  type AuditEvent, type ContractDetail,
} from "../api";

export default function Contract({ documentId }: { documentId: string }) {
  const [detail, setDetail] = useState<ContractDetail | null>(null);
  const [audit, setAudit] = useState<AuditEvent[] | null>(null);
  const [tab, setTab] = useState<"brief" | "audit">("brief");
  const [highlight, setHighlight] = useState<string | null>(null);
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

  const { document: doc, analysis } = detail;
  const reviewable = ["analyzed", "in_review"].includes(doc.status);
  const isReviewer = getRole() === "reviewer";

  const jumpToCitation = (citation: string) => {
    if (citation.startsWith("template:")) {
      setHighlight(null);
      setMessage(`Missing clause — standard reference: ${citation.split(":")[2]}`);
      return;
    }
    const chunk = detail.chunks.find((c) => c.chunk_id === citation);
    if (!chunk) return;
    setMessage(null);
    setHighlight(chunk.section_id);
    document
      .getElementById(`sec-${chunk.section_id}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
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
    if (detail.sections.length === 0) return <pre>{detail.masked_text}</pre>;
    return detail.sections.map((s) => (
      <div key={s.section_id} id={`sec-${s.section_id}`}
           className={`clause ${highlight === s.section_id ? "clause-hl" : ""}`}>
        <pre>{detail.masked_text!.slice(s.start, s.end).trim()}</pre>
      </div>
    ));
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

      <div className="split">
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
