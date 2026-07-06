import { useState } from "react";
import { login } from "../api";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand brand-lg">
          <span className="brand-mark">⎈</span>
          <div>
            <div className="brand-name">Contract Co-Pilot</div>
            <div className="brand-sub">Secure in-VPC contract review</div>
          </div>
        </div>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)}
                 autoFocus autoComplete="username" />
        </label>
        <label>
          Password
          <input type="password" value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="hint">The AI assists — people decide. Every action is audited.</p>
      </form>
    </div>
  );
}
