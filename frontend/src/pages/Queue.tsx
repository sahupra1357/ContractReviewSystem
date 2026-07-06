import { useEffect, useState } from "react";
import { getQueue, type QueueItem } from "../api";

export default function Queue() {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    getQueue().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!items) return <div className="loading">Loading queue…</div>;

  return (
    <div>
      <h1>Review queue</h1>
      <p className="sub">
        {items.length} contract{items.length === 1 ? "" : "s"} awaiting human
        decision — the AI only proposes.
      </p>
      {items.length === 0 ? (
        <div className="card empty">Queue is empty. Upload contracts to begin.</div>
      ) : (
        <table className="table table-click">
          <thead>
            <tr>
              <th>Contract</th><th>Family</th><th>Findings</th>
              <th>AI suggests</th><th>Status</th><th>Uploaded by</th>
            </tr>
          </thead>
          <tbody>
            {items.map((q) => (
              <tr key={q.document_id}
                  onClick={() => (window.location.hash = `#/contract/${q.document_id}`)}>
                <td><strong>{q.filename}</strong></td>
                <td>{q.family ?? "—"}</td>
                <td>
                  {q.finding_count ?? "—"}
                  {q.high_severity ? (
                    <span className="badge badge-high"> {q.high_severity} high</span>
                  ) : null}
                </td>
                <td>
                  {q.suggested_decision && (
                    <span className={`badge badge-${q.suggested_decision}`}>
                      {q.suggested_decision.replace("_", " ")}
                    </span>
                  )}
                </td>
                <td><span className={`badge badge-status-${q.status}`}>{q.status}</span></td>
                <td>{q.uploaded_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
