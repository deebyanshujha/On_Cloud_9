import Disclaimer from "./components/Disclaimer";
import Sidebar from "./components/Sidebar";
import CaseDetail from "./pages/CaseDetail";
import CasesList from "./pages/CasesList";
import Dashboard from "./pages/Dashboard";
import DrugExplorer from "./pages/DrugExplorer";
import EvidenceExplorer from "./pages/EvidenceExplorer";
import NewCase from "./pages/NewCase";
import ResearchSignals from "./pages/ResearchSignals";
import LandingPage from "./pages/LandingPage";
import { matchRoute, navigate, useRoute } from "./router";

function routeLabel(path: string): string {
  if (path === "/") return "Overview Dashboard";
  if (path === "/cases") return "Cases";
  if (path.startsWith("/cases/")) return "Case Analysis";
  if (path === "/signals") return "Research Signals";
  if (path.startsWith("/drugs")) return "Drug Intelligence";
  if (path === "/evidence") return "Evidence Explorer";
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

  return <Dashboard />;
}

export default function App() {
  const path = useRoute();

  if (path === "/landing") {
    return <div className="route-transition" key={path}><LandingPage /></div>;
  }

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
