import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { CandidateOut } from "../api";
import { worstConflictState } from "../scoring";

interface Props {
  patientLabel: string;
  primaryCondition: string;
  comorbidities: string[];
  candidates: CandidateOut[];
}

// Same rendering library as the existing Research Signals network view
// (react-force-graph-2d) — reused rather than a second graph integration,
// per the brief. This is a rendering of the relational Case/Candidate data
// already returned by the Phase 1 API; no graph database involved.
interface GraphNode {
  id: string;
  label: string;
  kind: "patient" | "condition" | "drug";
  flagged?: boolean;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

interface GraphLink {
  source: string;
  target: string;
  flagged: boolean;
}

const PATIENT_COLOR = "#e7ebf3";
const CONDITION_COLOR = "#7c8ba3";
const DRUG_COLOR = "#35e0a1";
const DRUG_FLAGGED_COLOR = "#ff6b6b";
const LINK_COLOR = "#323a52";
const LINK_FLAGGED_COLOR = "#ff6b6b";

const CONDITION_RADIUS = 130;
const DRUG_RADIUS = 260;

// A deterministic radial layout (patient at center, conditions on an inner
// ring, candidate drugs on an outer ring) rather than a physics simulation.
// With only a handful of nodes and a fixed hub-and-spoke shape (per the
// brief: "patient at center, branching to conditions, branching to
// candidate drugs"), a force layout's settle time/position is nondeterministic
// run to run and was landing at inconsistent, sometimes illegibly small
// zoom levels. Fixed angles make the fit — and the picture — stable and
// degrade gracefully whether there's 1 candidate or 20 (evenly spaced
// around the outer ring either way).
function layout(
  patientLabel: string,
  primaryCondition: string,
  comorbidities: string[],
  candidates: CandidateOut[]
): { nodes: GraphNode[]; links: GraphLink[] } {
  const nodeMap = new Map<string, GraphNode>();
  const links: GraphLink[] = [];

  const patientId = "patient";
  nodeMap.set(patientId, { id: patientId, label: patientLabel, kind: "patient", fx: 0, fy: 0 });

  const conditionId = (name: string) => `condition:${name}`;
  const primaryId = conditionId(primaryCondition);
  const conditions = [primaryCondition, ...comorbidities];

  conditions.forEach((name, i) => {
    const id = conditionId(name);
    if (nodeMap.has(id)) return;
    const angle = (i / conditions.length) * 2 * Math.PI - Math.PI / 2;
    nodeMap.set(id, {
      id,
      label: name,
      kind: "condition",
      fx: Math.cos(angle) * CONDITION_RADIUS,
      fy: Math.sin(angle) * CONDITION_RADIUS,
    });
    links.push({ source: patientId, target: id, flagged: false });
  });

  const drugNames = [...new Set(candidates.map((c) => c.drug))];
  drugNames.forEach((drug, i) => {
    const id = `drug:${drug}`;
    const drugCandidates = candidates.filter((c) => c.drug === drug);
    const flagged = drugCandidates.some(
      (c) => worstConflictState(c.comorbidity_checks.map((ck) => ck.status)) === "conflict_detected"
    );
    const angle = (i / drugNames.length) * 2 * Math.PI - Math.PI / 2;
    nodeMap.set(id, {
      id,
      label: drug,
      kind: "drug",
      flagged,
      fx: Math.cos(angle) * DRUG_RADIUS,
      fy: Math.sin(angle) * DRUG_RADIUS,
    });
    links.push({ source: primaryId, target: id, flagged: false });

    for (const candidate of drugCandidates) {
      for (const check of candidate.comorbidity_checks) {
        if (check.status !== "conflict_detected") continue;
        links.push({ source: conditionId(check.comorbidity), target: id, flagged: true });
      }
    }
  });

  return { nodes: Array.from(nodeMap.values()), links };
}

export default function CaseGraph({ patientLabel, primaryCondition, comorbidities, candidates }: Props) {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);

  const { nodes, links } = useMemo(
    () => layout(patientLabel, primaryCondition, comorbidities, candidates),
    [patientLabel, primaryCondition, comorbidities, candidates]
  );

  // react-force-graph-2d auto-detects its container size via
  // ResizeObserver, which can race with mount and hand it a stale (or
  // zero) size on the first paint — leading zoomToFit to compute against
  // the wrong canvas dimensions and land oddly zoomed. Measuring the
  // container ourselves and passing width/height explicitly sidesteps
  // that race entirely.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !size) return;
    // Positions are fixed (fx/fy) — no need to wait for a simulation to
    // settle before fitting.
    const timer = setTimeout(() => fg.zoomToFit(300, 70), 50);
    return () => clearTimeout(timer);
  }, [nodes, links, size]);

  return (
    <div className="graph-wrap case-graph-wrap" ref={containerRef}>
      <div className="graph-legend">
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: PATIENT_COLOR }} />
          patient
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: CONDITION_COLOR }} />
          condition
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: DRUG_COLOR }} />
          candidate drug
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: DRUG_FLAGGED_COLOR }} />
          flagged conflict
        </div>
      </div>
      {size && (
      <ForceGraph2D
        ref={fgRef}
        graphData={{ nodes, links } as any}
        width={size.width}
        height={size.height}
        backgroundColor="#13161e"
        cooldownTicks={0}
        nodeRelSize={5}
        nodeVal={(n: any) => ((n as GraphNode).kind === "patient" ? 14 : (n as GraphNode).kind === "drug" ? 9 : 6)}
        nodeColor={(n: any) => {
          const node = n as GraphNode;
          if (node.kind === "patient") return PATIENT_COLOR;
          if (node.kind === "condition") return CONDITION_COLOR;
          return node.flagged ? DRUG_FLAGGED_COLOR : DRUG_COLOR;
        }}
        nodeLabel={(n: any) => (n as GraphNode).label}
        linkColor={(l: any) => ((l as GraphLink).flagged ? LINK_FLAGGED_COLOR : LINK_COLOR)}
        linkWidth={(l: any) => ((l as GraphLink).flagged ? 2.4 : 1)}
        linkDirectionalParticles={(l: any) => ((l as GraphLink).flagged ? 3 : 0)}
        linkDirectionalParticleWidth={2.5}
        linkDirectionalParticleColor={() => LINK_FLAGGED_COLOR}
        linkDirectionalParticleSpeed={0.005}
        enableNodeDrag={false}
        nodeCanvasObjectMode={() => "after"}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const n = node as GraphNode;
          const fontSize = (n.kind === "patient" ? 14 : n.kind === "drug" ? 12 : 10) / globalScale;
          ctx.font = `${n.kind === "patient" ? "700" : "600"} ${fontSize}px "IBM Plex Mono", monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = n.kind === "condition" ? "#8b93a7" : n.flagged ? DRUG_FLAGGED_COLOR : "#e7ebf3";
          ctx.fillText(n.kind === "drug" && n.flagged ? `⚠ ${n.label}` : n.label, n.x ?? 0, (n.y ?? 0) + 8);
        }}
      />
      )}
    </div>
  );
}
