import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useIsMobile } from "../hooks/useIsMobile";
import { cn } from "../lib/utils";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

const SIDEBAR_WIDTH_STORAGE_KEY = "ava.ui.sidebar-width";
const SIDEBAR_MIN_WIDTH = 240;
const SIDEBAR_DEFAULT_WIDTH = 272;
const SIDEBAR_MAX_WIDTH = 500;
const RESIZE_HANDLE_WIDTH = 6;
const MIN_MAIN_WIDTH = 320;

function clampSidebarWidth(width: number, maxWidth = SIDEBAR_MAX_WIDTH): number {
  return Math.min(Math.max(width, SIDEBAR_MIN_WIDTH), maxWidth);
}

function readSidebarWidth(): number {
  try {
    const stored = typeof window === "undefined"
      ? null
      : window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY);
    if (stored == null) return SIDEBAR_DEFAULT_WIDTH;
    const width = Number(stored);
    return Number.isFinite(width)
      ? clampSidebarWidth(width)
      : SIDEBAR_DEFAULT_WIDTH;
  } catch {
    return SIDEBAR_DEFAULT_WIDTH;
  }
}

function persistSidebarWidth(width: number): void {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(width));
    }
  } catch {
    // Sidebar width is a preference; blocked storage must not affect the shell.
  }
}

function scheduleFrame(callback: FrameRequestCallback): number {
  return typeof window.requestAnimationFrame === "function"
    ? window.requestAnimationFrame(callback)
    : window.setTimeout(() => callback(Date.now()), 16);
}

function cancelFrame(frameId: number): void {
  if (typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(frameId);
  } else {
    window.clearTimeout(frameId);
  }
}

export interface AppShellProps {
  headerActions?: ReactNode;
  sidebarChildren?: ReactNode;
  mainContent?: ReactNode;
  prompt?: ReactNode;
  className?: string;
  /**
   * Hides the sidebar entirely. Views that are not conversation-shaped (for
   * example Settings) pass `false` rather than rendering an unrelated sidebar.
   * Defaults to `true` so existing compositions are unaffected.
   */
  showSidebar?: boolean;
}

export function AppShell({
  headerActions,
  sidebarChildren,
  mainContent,
  prompt,
  showSidebar = true,
  className,
}: AppShellProps) {
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(readSidebarWidth);
  const sidebarWidthRef = useRef(sidebarWidth);
  const resizeActiveRef = useRef(false);
  const pendingWidthRef = useRef<number | null>(null);
  const resizeFrameRef = useRef<number | null>(null);
  const shellRowRef = useRef<HTMLDivElement>(null);

  const availableShellWidth = () => {
    const measured = shellRowRef.current?.getBoundingClientRect().width ?? 0;
    return measured > 0 ? measured : (typeof window === "undefined" ? 0 : window.innerWidth);
  };
  const maxSidebarWidth = Math.max(
    SIDEBAR_MIN_WIDTH,
    Math.min(SIDEBAR_MAX_WIDTH, availableShellWidth() - MIN_MAIN_WIDTH - RESIZE_HANDLE_WIDTH),
  );

  const applyWidth = (width: number, persist: boolean) => {
    const nextWidth = clampSidebarWidth(width, maxSidebarWidth);
    sidebarWidthRef.current = nextWidth;
    setSidebarWidth(nextWidth);
    if (persist) persistSidebarWidth(nextWidth);
  };

  const flushPendingWidth = (persist: boolean) => {
    if (resizeFrameRef.current != null) {
      cancelFrame(resizeFrameRef.current);
      resizeFrameRef.current = null;
    }
    const pending = pendingWidthRef.current;
    pendingWidthRef.current = null;
    if (pending != null) applyWidth(pending, persist);
    else if (persist) persistSidebarWidth(sidebarWidthRef.current);
  };

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    resizeActiveRef.current = true;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture is an enhancement; pointer events still resize normally.
    }
  };

  const moveResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizeActiveRef.current) return;
    event.preventDefault();
    const shellLeft = shellRowRef.current?.getBoundingClientRect().left ?? 0;
    pendingWidthRef.current = clampSidebarWidth(event.clientX - shellLeft, maxSidebarWidth);
    if (resizeFrameRef.current == null) {
      resizeFrameRef.current = scheduleFrame(() => {
        resizeFrameRef.current = null;
        const pending = pendingWidthRef.current;
        pendingWidthRef.current = null;
        if (pending != null) applyWidth(pending, false);
      });
    }
  };

  const endResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizeActiveRef.current) return;
    resizeActiveRef.current = false;
    flushPendingWidth(true);
    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    } catch {
      // Some browser engines do not expose capture state for synthetic events.
    }
  };

  const onResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const nextWidth = event.key === "Home"
      ? SIDEBAR_MIN_WIDTH
      : event.key === "End"
        ? maxSidebarWidth
        : sidebarWidthRef.current + (event.key === "ArrowRight" ? 16 : -16);
    applyWidth(nextWidth, true);
  };

  useEffect(() => {
    if (isMobile) setCollapsed(true);
  }, [isMobile]);

  useEffect(() => {
    const onWindowResize = () => {
      const measured = shellRowRef.current?.getBoundingClientRect().width ?? 0;
      const available = measured > 0 ? measured : window.innerWidth;
      const maxWidth = Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(SIDEBAR_MAX_WIDTH, available - MIN_MAIN_WIDTH - RESIZE_HANDLE_WIDTH),
      );
      if (sidebarWidthRef.current > maxWidth) {
        sidebarWidthRef.current = maxWidth;
        setSidebarWidth(maxWidth);
      }
    };
    window.addEventListener("resize", onWindowResize);
    onWindowResize();
    return () => window.removeEventListener("resize", onWindowResize);
  }, []);

  useEffect(() => () => {
    if (resizeFrameRef.current != null) cancelFrame(resizeFrameRef.current);
  }, []);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return (
    <div className={cn("flex h-dvh w-full flex-col overflow-hidden bg-background text-foreground", className)}>
      <Header actions={headerActions} />
      <div ref={shellRowRef} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {showSidebar && (
          <>
            <Sidebar collapsed={collapsed} width={sidebarWidth} onToggle={toggle} children={sidebarChildren} />
            {!collapsed && !isMobile && (
              <div
                role="separator"
                aria-label="Resize conversation sidebar"
                aria-orientation="vertical"
                aria-valuemin={SIDEBAR_MIN_WIDTH}
                aria-valuemax={maxSidebarWidth}
                aria-valuenow={sidebarWidth}
                tabIndex={0}
                data-sidebar-resize-handle=""
                className="z-10 flex w-1.5 shrink-0 cursor-col-resize touch-none select-none items-center justify-center bg-transparent transition-colors hover:bg-primary/15 focus-visible:bg-primary/15 focus-visible:outline-none"
                onPointerDown={startResize}
                onPointerMove={moveResize}
                onPointerUp={endResize}
                onPointerCancel={endResize}
                onKeyDown={onResizeKeyDown}
              />
            )}
          </>
        )}
        <main
          className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background"
        >
          <div
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            {mainContent ?? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                No conversation selected.
              </div>
            )}
          </div>
          {prompt != null && <div className="shrink-0">{prompt}</div>}
        </main>
      </div>
    </div>
  );
}
