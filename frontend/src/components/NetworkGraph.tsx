import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { Signal } from "../api";
import { scoreTier } from "../scoring";

interface Props {
  signals: Signal[];
}

interface GraphNode {
  id: string;
  label: string;
  kind: "drug" | "disease";
  expanded?: boolean;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

interface GraphLink {
  source: string;
  target: string;
  score: number;
  tier: string;
}

const TIER_COLOR: Record<string, string> = {
  high: "#35e0a1",
  medium: "#f5b342",
  low: "#6f8bd4",
};

const DRUG_COLOR = "#e7ebf3";
const DRUG_COLLAPSED_COLOR = "#7c8ba3";
const DISEASE_COLOR = "#a9b3c8";

// A network overview is useful only if its labels can be read. Ten hubs fit
// comfortably around the ring at normal dashboard widths; users can inspect
// the rest via search/filters rather than starting with a wall of text.
const MAX_HUBS = 10;
const HUB_RADIUS = 270;
const DISEASE_RADIUS_STEP = 90;
const MAX_VISIBLE_LABEL_LENGTH = 20;

function visibleLabel(label: string) {
  return label.length > MAX_VISIBLE_LABEL_LENGTH
    ? `${label.slice(0, MAX_VISIBLE_LABEL_LENGTH - 1)}…`
    : label;
}

// Rendering every drug-disease edge in the dataset at once (the previous
// version) produces hundreds of overlapping labels — unreadable regardless
// of zoom-based label hiding. Instead: show only the top drug hubs by
// default (fixed radial layout, same deterministic-positioning approach
// CaseGraph.tsx already uses successfully), and reveal one drug's disease
// connections only when the user clicks that drug — so the graph never has
// to render more than a handful of nodes at a time.
export default function NetworkGraph({ signals }: Props) {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);

  const drugHubs = useMemo(() => {
    const byDrug = new Map<string, { count: number; topScore: number }>();
    for (const s of signals) {
      const existing = byDrug.get(s.drug);
      if (existing) {
        existing.count += 1;
        existing.topScore = Math.max(existing.topScore, s.score);
      } else {
        byDrug.set(s.drug, { count: 1, topScore: s.score });
      }
    }
    return [...byDrug.entries()]
      .sort((a, b) => b[1].topScore - a[1].topScore || b[1].count - a[1].count)
      .slice(0, MAX_HUBS)
      .map(([drug, stats]) => ({ drug, ...stats }));
  }, [signals]);

  const hubDrugNames = useMemo(() => new Set(drugHubs.map((h) => h.drug)), [drugHubs]);

  const { nodes, links } = useMemo(() => {
    const nodeMap = new Map<string, GraphNode>();
    const links: GraphLink[] = [];

    drugHubs.forEach((h, i) => {
      const id = `drug:${h.drug}`;
      const angle = (i / drugHubs.length) * 2 * Math.PI - Math.PI / 2;
      nodeMap.set(id, {
        id,
        label: h.drug,
        kind: "drug",
        expanded: expanded.has(h.drug),
        fx: Math.cos(angle) * HUB_RADIUS,
        fy: Math.sin(angle) * HUB_RADIUS,
      });
    });

    for (const drugName of expanded) {
      const drugId = `drug:${drugName}`;
      const hub = nodeMap.get(drugId);
      if (!hub) continue;
      const drugSignals = signals.filter((s) => s.drug === drugName);
      const baseAngle = Math.atan2(hub.fy ?? 0, hub.fx ?? 0);
      drugSignals.forEach((s, i) => {
        const diseaseId = `disease:${drugName}:${s.disease}`;
        if (nodeMap.has(diseaseId)) return;
        const spread = Math.min(drugSignals.length, 8);
        const offset = (i % spread) - (spread - 1) / 2;
        const angle = baseAngle + offset * 0.28;
        const r = (hub.fx! ** 2 + hub.fy! ** 2) ** 0.5 + DISEASE_RADIUS_STEP;
        nodeMap.set(diseaseId, {
          id: diseaseId,
          label: s.disease,
          kind: "disease",
          fx: Math.cos(angle) * r,
          fy: Math.sin(angle) * r,
        });
        links.push({ source: drugId, target: diseaseId, score: s.score, tier: scoreTier(s.score) });
      });
    }

    return { nodes: Array.from(nodeMap.values()), links };
  }, [drugHubs, expanded, signals]);

  // ForceGraph's automatic measurement can observe a zero/stale size while
  // this tab is becoming visible. That leaves the canvas at the wrong scale
  // and collapses otherwise fixed radial positions into a dense label pile.
  // Measure the visible graph panel ourselves and refit whenever its graph
  // data changes.
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
    const timer = setTimeout(() => fg.zoomToFit(400, 70), 60);
    return () => clearTimeout(timer);
  }, [nodes, links, size]);

  function toggleDrug(drug: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(drug)) next.delete(drug);
      else next.add(drug);
      return next;
    });
  }

  return (
    <div className="graph-wrap" ref={containerRef}>
      <div className="graph-legend">
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: DRUG_COLOR }} />
          drug (click to expand)
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: DISEASE_COLOR }} />
          disease
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: TIER_COLOR.high }} />
          high confidence
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: TIER_COLOR.medium }} />
          medium
        </div>
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: TIER_COLOR.low }} />
          low
        </div>
      </div>
      <div className="graph-hint">
        showing the top {drugHubs.length} drugs by evidence strength · hover for full names · click a drug to
        reveal its studied diseases
      </div>
      {size && <ForceGraph2D
        ref={fgRef}
        graphData={{ nodes, links } as any}
        width={size.width}
        height={size.height}
        backgroundColor="#13161e"
        cooldownTicks={0}
        nodeRelSize={4}
        nodeVal={(n: any) => ((n as GraphNode).kind === "drug" ? 10 : 4)}
        nodeColor={(n: any) => {
          const node = n as GraphNode;
          if (node.kind === "disease") return DISEASE_COLOR;
          return node.expanded ? DRUG_COLOR : DRUG_COLLAPSED_COLOR;
        }}
        nodeLabel={(n: any) => (n as GraphNode).label}
        onNodeClick={(n: any) => {
          const node = n as GraphNode;
          if (node.kind === "drug" && hubDrugNames.has(node.label)) toggleDrug(node.label);
        }}
        linkColor={(l: any) => TIER_COLOR[(l as GraphLink).tier] ?? "#333"}
        linkWidth={(l: any) => 0.8 + (l as GraphLink).score * 2.2}
        linkDirectionalParticles={(l: any) => ((l as GraphLink).tier === "high" ? 2 : 0)}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleSpeed={0.004}
        enableNodeDrag={false}
        nodeCanvasObjectMode={() => "after"}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const n = node as GraphNode;
          const fontSize = (n.kind === "drug" ? 13 : 10) / globalScale;
          ctx.font = `${n.kind === "drug" ? "700" : "400"} ${fontSize}px "IBM Plex Mono", monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = n.kind === "drug" ? "#e7ebf3" : "#8b93a7";
          ctx.fillText(visibleLabel(n.label), n.x ?? 0, (n.y ?? 0) + 7);
        }}
      />}
    </div>
  );
}
