import { useEffect, useState } from "react";
import {
  addMaster, getHolds, getMaster, resolveHold,
  type MasterEntity, type PiiHold,
} from "../api";

const ENTITY_TYPES = ["PERSON", "ORG", "ACCOUNT", "ADDRESS", "EMAIL", "PHONE", "OTHER"];

export default function PiiAdmin() {
  const [holds, setHolds] = useState<PiiHold[] | null>(null);
  const [master, setMaster] = useState<MasterEntity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newValue, setNewValue] = useState("");
  const [newType, setNewType] = useState("ORG");

  const refresh = () => {
    getHolds().then(setHolds).catch((e) => setError(e.message));
    getMaster().then(setMaster).catch((e) => setError(e.message));
  };
  useEffect(refresh, []);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "action failed");
    }
  };

  return (
    <div>
      <h1>PII administration</h1>
      <p className="sub">
        The master table is the only masking authority. The tripwire halts any
        document with a possible unregistered entity — nothing unknown flows
        downstream until a human decides here.
      </p>
      {error && <div className="error">{error}</div>}

      <h2>Hold queue {holds && <span className="hint-inline">({holds.length} open)</span>}</h2>
      {holds && holds.length === 0 && (
        <div className="card empty">No documents held — the pipeline is clean.</div>
      )}
      {holds?.map((h) => <HoldRow key={h.id} hold={h} act={act} />)}

      <h2>PII master table {master && <span className="hint-inline">({master.length} entities)</span>}</h2>
      <div className="card master-add">
        <input placeholder="Register entity value (e.g. new counterparty name)"
               value={newValue} onChange={(e) => setNewValue(e.target.value)} />
        <select value={newType} onChange={(e) => setNewType(e.target.value)}>
          {ENTITY_TYPES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <button className="btn btn-primary" disabled={!newValue.trim()}
                onClick={() => act(async () => {
                  await addMaster(newValue.trim(), newType);
                  setNewValue("");
                })}>
          Register
        </button>
      </div>
      {master && (
        <table className="table">
          <thead><tr><th>Value</th><th>Type</th><th>Registered by</th></tr></thead>
          <tbody>
            {master.map((m) => (
              <tr key={m.id}>
                <td>{m.value}</td>
                <td><span className="badge">{m.entity_type}</span></td>
                <td>{m.created_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HoldRow({ hold, act }: { hold: PiiHold; act: (fn: () => Promise<unknown>) => void }) {
  const [entityType, setEntityType] = useState("PERSON");
  const [rationale, setRationale] = useState("");
  return (
    <div className="card hold-card">
      <div>
        <span className="badge badge-high">{hold.flag_type}</span>{" "}
        <strong className="mono">“{hold.span_text}”</strong>
        <div className="hint-inline">
          detector {hold.detector}
          {hold.score != null && ` · score ${hold.score.toFixed(2)}`} · doc{" "}
          <a href={`#/contract/${hold.document_id}`} className="mono">
            {hold.document_id.slice(0, 12)}…
          </a>
        </div>
      </div>
      <div className="hold-actions">
        <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
          {ENTITY_TYPES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <button className="btn btn-primary"
                onClick={() => act(() => resolveHold(hold.id, "add_to_master",
                                                     { entity_type: entityType }))}>
          Add to master
        </button>
        <input placeholder="Dismissal rationale (required)" value={rationale}
               onChange={(e) => setRationale(e.target.value)} />
        <button className="btn btn-ghost" disabled={!rationale.trim()}
                onClick={() => act(() => resolveHold(hold.id, "dismiss", { rationale }))}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
