import { navigate } from "../router";

interface NavItem {
  path: string;
  label: string;
  match: (path: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Dashboard", match: (p) => p === "/" },
  { path: "/cases", label: "Cases", match: (p) => p === "/cases" || p.startsWith("/cases/") },
  { path: "/evidence", label: "Evidence Explorer", match: (p) => p === "/evidence" },
  { path: "/drugs", label: "Drug Intelligence", match: (p) => p === "/drugs" },
  { path: "/signals", label: "Research Radar", match: (p) => p === "/signals" },
];

interface Props {
  path: string;
}

export default function Sidebar({ path }: Props) {
  return (
    <nav className="sidebar">
      <div className="brand">
        <span className="bracket">[</span>MEDBRIDGE<span className="bracket">]</span>
      </div>
      <div className="brand-sub">biomedical research intelligence</div>

      <button className="new-case-cta" onClick={() => navigate("/cases/new")}>
        + New Case
      </button>

      <div className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.path}
            className={`sidebar-link ${item.match(path) ? "active" : ""}`}
            onClick={() => navigate(item.path)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="sidebar-footer">
        <span>data: ClinicalTrials.gov · openFDA · Europe PMC</span>
        <span>no LLM APIs used — deterministic scoring, local NER</span>
      </div>
    </nav>
  );
}
