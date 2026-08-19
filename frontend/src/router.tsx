import { useEffect, useState } from "react";

// A tiny hash router — this app has a fixed, small set of routes (5 nav
// destinations + a case-detail/new-case form), which doesn't justify pulling
// in react-router-dom as a new dependency. `location.hash` avoids needing
// server-side route config too, since this is a static Vite build.

export function currentPath(): string {
  const hash = window.location.hash.replace(/^#/, "");
  return hash || "/";
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function useRoute(): string {
  const [path, setPath] = useState(currentPath());

  useEffect(() => {
    const onHashChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return path;
}

// Matches "/cases/42" against "/cases/:id" -> { id: "42" }, or null.
export function matchRoute(pattern: string, path: string): Record<string, string> | null {
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = path.split("/").filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;

  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i++) {
    const p = patternParts[i];
    if (p.startsWith(":")) {
      params[p.slice(1)] = decodeURIComponent(pathParts[i]);
    } else if (p !== pathParts[i]) {
      return null;
    }
  }
  return params;
}
