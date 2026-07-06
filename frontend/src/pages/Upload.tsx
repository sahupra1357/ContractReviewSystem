import { useRef, useState } from "react";
import { uploadFiles, type UploadResult } from "../api";

export default function Upload() {
  const input = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const files = input.current?.files;
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const response = await uploadFiles(files);
      setResults(response.results);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1>Upload contracts</h1>
      <p className="sub">
        Documents land in the encrypted raw zone, are deduplicated, and enter the
        pipeline: extract → PII gate → index → AI analysis → human review.
      </p>
      <div className="card upload-card">
        <input ref={input} type="file" multiple
               accept=".pdf,.docx,.txt" data-testid="file-input" />
        <button className="btn btn-primary" onClick={submit} disabled={busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {results && (
        <table className="table">
          <thead>
            <tr><th>File</th><th>Document</th><th>Result</th></tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.sha256 + r.filename}>
                <td>{r.filename}</td>
                <td className="mono">{r.document_id.slice(0, 12)}…</td>
                <td>
                  {r.duplicate
                    ? <span className="badge badge-warn">duplicate — skipped</span>
                    : <span className="badge badge-ok">accepted</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
