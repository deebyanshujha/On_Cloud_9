import { useEffect, useMemo, useRef } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { Signal } from "../api";
import { scoreTier } from "../scoring";

interface Props {
  signals: Signal[];
}

// react-force-graph-2d's generics don't infer cleanly through a
// self-referencing node/link shape, so graphData is passed as `any` below —
// these interfaces still give us type safety everywhere else in this file.
interface GraphNode {
  id: string;
  label: string;
  kind: "drug" | "disease";
  x?: number;
  y?: number;
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
const DISEASE_COLOR = "#7c8ba3";

export default function NetworkGraph({ signals }: Props) {
  const fgRef = useRef<any>(null);

  const { nodes, links } = useMemo(() => {
    const nodeMap = new Map<string, GraphNode>();
    const links: GraphLink[] = [];

    for (const s of signals) {
      const drugId = `drug:${s.drug}`;
      const diseaseId = `disease:${s.disease}`;
      if (!nodeMap.has(drugId)) {
        nodeMap.set(drugId, { id: drugId, label: s.drug, kind: "drug" });
      }
      if (!nodeMap.has(diseaseId)) {
        nodeMap.set(diseaseId, { id: diseaseId, label: s.disease, kind: "disease" });
      }
      links.push({
        source: drugId,
        target: diseaseId,
        score: s.score,
        tier: scoreTier(s.score),
      });
    }

    return { nodes: Array.from(nodeMap.values()), links };
  }, [signals]);

  // Default charge/link forces cluster everything too tightly to read once
  // there are more than a handful of nodes — widen them out and frame the
  // whole graph once the layout has had a moment to settle.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-140);
    fg.d3Force("link")?.distance(70);
    const timer = setTimeout(() => fg.zoomToFit(500, 60), 400);
    return () => clearTimeout(timer);
  }, [nodes, links]);

  return (
    <div className="graph-wrap">
      <div className="graph-legend">
        <div className="graph-legend-item">
          <span className="graph-legend-swatch" style={{ background: DRUG_COLOR }} />
          drug
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
      <div className="graph-hint">scroll to zoom for disease labels · drag to pan</div>
      <ForceGraph2D
        ref={fgRef}
        graphData={{ nodes, links } as any}
        backgroundColor="#13161e"
        nodeRelSize={4}
        nodeVal={(n: any) => ((n as GraphNode).kind === "drug" ? 10 : 4)}
        nodeColor={(n: any) => ((n as GraphNode).kind === "drug" ? DRUG_COLOR : DISEASE_COLOR)}
        nodeLabel={(n: any) => (n as GraphNode).label}
        linkColor={(l: any) => TIER_COLOR[(l as GraphLink).tier] ?? "#333"}
        linkWidth={(l: any) => 0.6 + (l as GraphLink).score * 2.2}
        linkDirectionalParticles={(l: any) => ((l as GraphLink).tier === "high" ? 2 : 0)}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleSpeed={0.004}
        cooldownTicks={200}
        nodeCanvasObjectMode={() => "after"}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const n = node as GraphNode;
          // Disease labels only render once zoomed in — with hundreds of
          // disease nodes, drawing every label at the overview level is
          // unreadable clutter rather than useful detail. Drug labels
          // (there are only ever a couple) always render.
          if (n.kind === "disease" && globalScale < 2.2) return;
          const fontSize = (n.kind === "drug" ? 13 : 10) / globalScale;
          ctx.font = `${n.kind === "drug" ? "700" : "400"} ${fontSize}px "IBM Plex Mono", monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = n.kind === "drug" ? "#e7ebf3" : "#8b93a7";
          ctx.fillText(n.label, n.x ?? 0, (n.y ?? 0) + 7);
        }}
      />
    </div>
  );
}
