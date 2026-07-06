import { useEffect, useState } from "react";
import { getMetrics, type Metrics } from "../api";

const STAGE_ORDER = [
  "ingested", "extracted", "masking", "pii_hold", "masked", "indexed",
  "analyzed", "in_review", "approved", "rejected", "changes_requested",
  "failed_extract", "failed_mask", "failed_index", "failed_analyze",
];

export default function Dashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const refresh = () => getMetrics().then(setMetrics).catch((e) => setError(e.message));
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!metrics) return <div className="loading">Loading metrics…</div>;

  const statuses = Object.entries(metrics.documents_by_status)
    .sort(([a], [b]) => STAGE_ORDER.indexOf(a) - STAGE_ORDER.indexOf(b));

  return (
    <div>
      <h1>Pipeline dashboard</h1>
      <p className="sub">Live view — refreshes every 5 seconds.</p>
      <div className="stat-row">
        <div className="stat">
          <div className="stat-value">{metrics.total_documents}</div>
          <div className="stat-label">documents</div>
        </div>
        <div className={`stat ${metrics.open_pii_holds > 0 ? "stat-warn" : ""}`}>
          <div className="stat-value">{metrics.open_pii_holds}</div>
          <div className="stat-label">open PII holds</div>
        </div>
        <div className="stat">
          <div className="stat-value">
            {metrics.avg_analysis_latency_ms
              ? `${(metrics.avg_analysis_latency_ms / 1000).toFixed(1)}s`
              : "—"}
          </div>
          <div className="stat-label">avg AI analysis</div>
        </div>
        <div className="stat">
          <div className="stat-value">
            {Object.values(metrics.decisions_by_action).reduce((a, b) => a + b, 0)}
          </div>
          <div className="stat-label">human decisions</div>
        </div>
      </div>

      <h2>Documents by stage</h2>
      <table className="table">
        <tbody>
          {statuses.map(([status, count]) => (
            <tr key={status}>
              <td><span className={`badge badge-status-${status}`}>{status}</span></td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {Object.keys(metrics.decisions_by_action).length > 0 && (
        <>
          <h2>Decisions</h2>
          <table className="table">
            <tbody>
              {Object.entries(metrics.decisions_by_action).map(([action, count]) => (
                <tr key={action}>
                  <td><span className={`badge badge-${action}`}>{action}</span></td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
