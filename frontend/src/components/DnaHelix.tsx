import { useEffect, useRef } from "react";

interface DnaHelixProps {
  className?: string;
}

interface Point {
  x: number;
  y: number;
  z: number;
}

const PAIRS = 34;
const SPACING = 18;
const HELIX_RADIUS = 72;

export default function DnaHelix({ className = "" }: DnaHelixProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rotation = useRef({ x: -0.08, y: 0.36 });
  const targetRotation = useRef({ x: -0.08, y: 0.36 });
  const highlighted = useRef<number | null>(null);
  const pointer = useRef({ x: 0, y: 0, down: false });
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    const resize = () => {
      const bounds = parent.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = bounds.width * ratio;
      canvas.height = bounds.height * ratio;
      canvas.style.width = `${bounds.width}px`;
      canvas.style.height = `${bounds.height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(parent);
    resize();

    const rotatePoint = (point: Point, rx: number, ry: number): Point => {
      const y1 = point.y * Math.cos(rx) - point.z * Math.sin(rx);
      const z1 = point.y * Math.sin(rx) + point.z * Math.cos(rx);
      const x2 = point.x * Math.cos(ry) + z1 * Math.sin(ry);
      const z2 = -point.x * Math.sin(ry) + z1 * Math.cos(ry);
      return { x: x2, y: y1, z: z2 };
    };

    const project = (point: Point, width: number, height: number) => {
      const depth = 1 + point.z / 560;
      return {
        x: width / 2 + point.x * depth,
        y: height / 2 + point.y * depth,
        scale: depth,
        depth,
      };
    };

    const draw = (time: number) => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      context.clearRect(0, 0, width, height);

      if (!pointer.current.down) {
        targetRotation.current.y += 0.0024;
      }
      rotation.current.x += (targetRotation.current.x - rotation.current.x) * 0.08;
      rotation.current.y += (targetRotation.current.y - rotation.current.y) * 0.08;

      const pairs: Array<{ left: ReturnType<typeof project>; right: ReturnType<typeof project>; index: number }> = [];
      for (let index = 0; index < PAIRS; index += 1) {
        const y = (index - (PAIRS - 1) / 2) * SPACING;
        const angle = index * 0.48 + time * 0.00022;
        const left = rotatePoint({ x: Math.cos(angle) * HELIX_RADIUS, y, z: Math.sin(angle) * HELIX_RADIUS }, rotation.current.x, rotation.current.y);
        const right = rotatePoint({ x: -Math.cos(angle) * HELIX_RADIUS, y, z: -Math.sin(angle) * HELIX_RADIUS }, rotation.current.x, rotation.current.y);
        pairs.push({ left: project(left, width, height), right: project(right, width, height), index });
      }

      for (const pair of pairs) {
        const opacity = 0.15 + Math.max(0, pair.left.depth) * 0.32;
        context.strokeStyle = highlighted.current === pair.index ? "rgba(13, 148, 136, .9)" : `rgba(71, 83, 80, ${opacity})`;
        context.lineWidth = highlighted.current === pair.index ? 2.4 : 1;
        context.beginPath();
        context.moveTo(pair.left.x, pair.left.y);
        context.lineTo(pair.right.x, pair.right.y);
        context.stroke();
      }

      for (const pair of pairs) {
        for (const node of [pair.left, pair.right]) {
          const radius = highlighted.current === pair.index ? 7 : 4.5;
          const fill = highlighted.current === pair.index ? "#0d9488" : node.depth > 1 ? "#e2a64d" : "#111b19";
          context.fillStyle = fill;
          context.globalAlpha = Math.max(0.35, Math.min(1, node.depth));
          context.beginPath();
          context.arc(node.x, node.y, radius * node.scale, 0, Math.PI * 2);
          context.fill();
        }
      }
      context.globalAlpha = 1;
      frame.current = requestAnimationFrame(draw);
    };

    frame.current = requestAnimationFrame(draw);

    const onPointerDown = (event: PointerEvent) => {
      pointer.current = { x: event.clientX, y: event.clientY, down: true };
      canvas.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!pointer.current.down) return;
      const dx = event.clientX - pointer.current.x;
      targetRotation.current.y += dx * 0.008;
      pointer.current.x = event.clientX;
      pointer.current.y = event.clientY;
    };
    const onPointerUp = () => {
      pointer.current.down = false;
    };
    const onWheel = (event: WheelEvent) => event.preventDefault();
    const onClick = (event: MouseEvent) => {
      const bounds = canvas.getBoundingClientRect();
      const x = event.clientX - bounds.left;
      const y = event.clientY - bounds.top;
      let closest: { index: number; distance: number } | null = null;
      for (let index = 0; index < PAIRS; index += 1) {
        const baseY = bounds.height / 2 + (index - (PAIRS - 1) / 2) * SPACING;
        const distance = Math.abs(y - baseY) + Math.abs(x - bounds.width / 2) * 0.08;
        if (!closest || distance < closest.distance) closest = { index, distance };
      }
      highlighted.current = closest && closest.distance < 42 ? closest.index : null;
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("click", onClick);

    return () => {
      observer.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("click", onClick);
    };
  }, []);

  return <canvas ref={canvasRef} className={`dna-helix ${className}`} aria-label="Interactive DNA helix visualization" />;
}
