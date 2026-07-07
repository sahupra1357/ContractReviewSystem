import { useEffect, useState } from "react";
import { clearSession, getRole, getToken, getUsername } from "./api";
import Contract from "./pages/Contract";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import PiiAdmin from "./pages/PiiAdmin";
import Queue from "./pages/Queue";
import Upload from "./pages/Upload";

function useHashRoute(): string {
  const [hash, setHash] = useState(window.location.hash || "#/queue");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/queue");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

const NAV = [
  { hash: "#/queue", label: "Review Queue", adminOnly: false },
  { hash: "#/upload", label: "Upload", adminOnly: false },
  { hash: "#/dashboard", label: "Dashboard", adminOnly: false },
  { hash: "#/pii", label: "PII Admin", adminOnly: true },
];

export default function App() {
  const route = useHashRoute();
  // reactive: reading localStorage during render never triggers a re-render,
  // so a successful login looked like "nothing happened"
  const [authed, setAuthed] = useState(() => Boolean(getToken()));

  if (!authed || route.startsWith("#/login")) {
    return (
      <Login
        onLogin={() => {
          setAuthed(true);
          window.location.hash = "#/queue";
        }}
      />
    );
  }

  let page = <Queue />;
  if (route.startsWith("#/upload")) page = <Upload />;
  else if (route.startsWith("#/dashboard")) page = <Dashboard />;
  else if (route.startsWith("#/pii")) page = <PiiAdmin />;
  else if (route.startsWith("#/contract/")) {
    page = <Contract documentId={route.split("/")[2]} />;
  }

  const role = getRole();
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">⎈</span>
          <div>
            <div className="brand-name">Contract Co-Pilot</div>
            <div className="brand-sub">AI-assisted review</div>
          </div>
        </div>
        <nav>
          {NAV.filter((n) => !n.adminOnly || role === "admin").map((n) => (
            <a key={n.hash} href={n.hash}
               className={route.startsWith(n.hash) ? "active" : ""}>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="user-chip">
            <strong>{getUsername()}</strong>
            <span className={`role role-${role}`}>{role}</span>
          </div>
          <button
            className="btn btn-ghost"
            onClick={() => {
              clearSession();
              setAuthed(false);
              window.location.hash = "#/login";
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">{page}</main>
    </div>
  );
}
