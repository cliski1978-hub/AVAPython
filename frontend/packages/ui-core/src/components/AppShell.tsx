import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { defaultTheme } from "../theme";
import { useIsMobile } from "../hooks/useIsMobile";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

export interface AppShellProps {
  headerActions?: ReactNode;
  sidebarChildren?: ReactNode;
  mainContent?: ReactNode;
  prompt?: ReactNode;
  /**
   * Hides the sidebar entirely. Views that are not conversation-shaped (for
   * example Settings) pass `false` rather than rendering an unrelated sidebar.
   * Defaults to `true` so existing compositions are unaffected.
   */
  showSidebar?: boolean;
}

const t = defaultTheme;

const rootStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100vh",
  width: "100%",
  fontFamily: t.font.family,
  background: t.colors.background,
  color: t.colors.foreground,
  margin: 0,
  padding: 0,
  overflow: "hidden",
};

const bodyStyle: CSSProperties = {
  display: "flex",
  flex: 1,
  overflow: "hidden",
};

export function AppShell({
  headerActions,
  sidebarChildren,
  mainContent,
  prompt,
  showSidebar = true,
}: AppShellProps) {
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (isMobile) setCollapsed(true);
  }, [isMobile]);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return (
    <div style={rootStyle}>
      <Header actions={headerActions} />
      <div style={bodyStyle}>
        {showSidebar && (
          <Sidebar collapsed={collapsed} onToggle={toggle} children={sidebarChildren} />
        )}
        <main
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            minWidth: 0,
          }}
        >
          <div
            style={{
              flex: 1,
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {mainContent ?? (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: t.colors.mutedText,
                  fontSize: 14,
                }}
              >
                No conversation selected.
              </div>
            )}
          </div>
          {prompt != null && <div style={{ flexShrink: 0 }}>{prompt}</div>}
        </main>
      </div>
    </div>
  );
}