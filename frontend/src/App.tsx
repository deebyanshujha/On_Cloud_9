import Disclaimer from "./components/Disclaimer";
import Sidebar from "./components/Sidebar";
import CaseDetail from "./pages/CaseDetail";
import CasesList from "./pages/CasesList";
import Dashboard from "./pages/Dashboard";
import DiscussionList from "./pages/DiscussionList";
import DiscussionThread from "./pages/DiscussionThread";
import DrugExplorer from "./pages/DrugExplorer";
import EvidenceExplorer from "./pages/EvidenceExplorer";
import NewCase from "./pages/NewCase";
import ResearchSignals from "./pages/ResearchSignals";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import ScholarProfilePage from "./pages/ScholarProfilePage";
import { AuthProvider, useAuth } from "./auth";
import { matchRoute, navigate, useRoute } from "./router";

function routeLabel(path: string): string {
  if (path === "/") return "Overview Dashboard";
  if (path === "/cases") return "Cases";
  if (path.startsWith("/cases/")) return "Case Analysis";
  if (path === "/evidence") return "Evidence Explorer";
  if (path === "/drugs") return "Drug Intelligence";
  if (path === "/signals") return "Research Signals";
  if (path === "/profile") return "Scholar Profile";
  if (path === "/discussions") return "Research Community";
  if (path.startsWith("/discussions/")) return "Discussion Thread";
  return "Clinical Intelligence";
}

function renderRoute(path: string) {
  if (path === "/") return <Dashboard />;
  if (path === "/cases") return <CasesList />;
  if (path === "/cases/new") return <NewCase />;

  const caseMatch = matchRoute("/cases/:id", path);
  if (caseMatch) {
    const id = Number(caseMatch.id);
    if (Number.isFinite(id)) return <CaseDetail caseId={id} />;
  }

  if (path === "/evidence") return <EvidenceExplorer />;
  if (path === "/drugs") return <DrugExplorer />;
  const drugMatch = matchRoute("/drugs/:name", path);
  if (drugMatch) return <DrugExplorer initialDrug={drugMatch.name} />;
  if (path === "/signals") return <ResearchSignals />;
  if (path === "/profile") return <ScholarProfilePage />;

  // --- Discussion routes ---
  if (path === "/discussions") {
    // Parse optional context query params from hash (e.g. #/discussions?drug=X)
    const hashWithQuery = window.location.hash.replace(/^#/, "");
    const qIdx = hashWithQuery.indexOf("?");
    const params = qIdx >= 0 ? new URLSearchParams(hashWithQuery.slice(qIdx + 1)) : new URLSearchParams();
    return (
      <DiscussionList
        initialDrug={params.get("drug") ?? undefined}
        initialDisease={params.get("disease") ?? undefined}
        initialSignalKey={params.get("signal_key") ?? undefined}
      />
    );
  }
  const discussionMatch = matchRoute("/discussions/:id", path);
  if (discussionMatch) {
    const id = Number(discussionMatch.id);
    if (Number.isFinite(id)) return <DiscussionThread threadId={id} />;
  }

  return <Dashboard />;
}

export default function App() {
  return <AuthProvider><AppShell /></AuthProvider>;
}

function AppShell() {
  const path = useRoute();
  const { profile, logout } = useAuth();

  if (path === "/landing") {
    return <div className="route-transition" key={path}><LandingPage /></div>;
  }
  if (path === "/login") return <LoginPage />;

  return (
    <div className="app app-shell">
      <Sidebar path={path} />
      <div className="app-content">
        <header className="platform-topbar">
          <div className="platform-breadcrumb">
            <button onClick={() => navigate("/landing")}>MedBridge</button>
            <span>/</span>
            <strong>{routeLabel(path)}</strong>
          </div>
          <div className="platform-actions">
            <label className="platform-search">
              <span aria-hidden="true">⌕</span>
              <input placeholder="Search case data..." aria-label="Search case data" />
            </label>
            <span className="platform-availability"><i /> system ready</span>
            {profile ? (
              <div className="account-control scholar">
                <button onClick={() => navigate("/profile")}>{profile.username}</button>
                <span>scholar</span>
                <button className="account-logout" onClick={logout}>sign out</button>
              </div>
            ) : (
              <button className="account-control guest" onClick={() => navigate("/login")}>
                <span className="account-mode-dot" aria-hidden="true" />
                <span>Guest mode</span>
                <strong>Sign in</strong>
              </button>
            )}
          </div>
        </header>
        <main className="main">
          <div className="route-transition" key={path}>{renderRoute(path)}</div>
        </main>
        <footer className="footer">
          <Disclaimer />
        </footer>
      </div>
    </div>
  );
}
