import Disclaimer from "./components/Disclaimer";
import Sidebar from "./components/Sidebar";
import CaseDetail from "./pages/CaseDetail";
import CasesList from "./pages/CasesList";
import Dashboard from "./pages/Dashboard";
import DrugExplorer from "./pages/DrugExplorer";
import EvidenceExplorer from "./pages/EvidenceExplorer";
import NewCase from "./pages/NewCase";
import ResearchSignals from "./pages/ResearchSignals";
import { matchRoute, useRoute } from "./router";

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
  if (path === "/signals") return <ResearchSignals />;

  return <Dashboard />;
}

export default function App() {
  const path = useRoute();

  return (
    <div className="app app-shell">
      <Sidebar path={path} />
      <div className="app-content">
        <main className="main">{renderRoute(path)}</main>
        <footer className="footer">
          <Disclaimer />
        </footer>
      </div>
    </div>
  );
}
