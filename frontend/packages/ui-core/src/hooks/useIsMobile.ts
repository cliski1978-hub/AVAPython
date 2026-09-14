import { useEffect, useState } from "react";

export interface UseIsMobileOptions {
  /** Width in px below which the viewport is treated as mobile. */
  breakpoint?: number;
}

const DEFAULT_BREAKPOINT = 768;

function matchesQuery(query: string): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return false;
  }
  return window.matchMedia(query).matches;
}

/**
 * Tracks whether the viewport is below the mobile breakpoint.
 *
 * Safe for shared-package usage and tests: browser globals are only accessed
 * lazily (inside effects/handlers), never at module initialization, and the
 * hook falls back to `false` when `window`/`matchMedia` are unavailable.
 */
export function useIsMobile(options?: UseIsMobileOptions): boolean {
  const { breakpoint = DEFAULT_BREAKPOINT } = options ?? {};
  const query = `(max-width: ${breakpoint}px)`;

  const [isMobile, setIsMobile] = useState(() => matchesQuery(query));

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQueryList = window.matchMedia(query);
    const onChange = () => setIsMobile(mediaQueryList.matches);

    mediaQueryList.addEventListener("change", onChange);
    setIsMobile(mediaQueryList.matches);

    return () => mediaQueryList.removeEventListener("change", onChange);
  }, [query]);

  return isMobile;
}