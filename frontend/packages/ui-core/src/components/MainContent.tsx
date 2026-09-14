import { type ReactNode } from "react";
import { defaultTheme } from "../theme";
import { EmptyState } from "./EmptyState";

export interface MainContentProps {
  children?: ReactNode;
}

const t = defaultTheme;

export function MainContent({ children }: MainContentProps) {
  return (
    <div
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
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: t.spacing.lg,
        }}
      >
        {children ?? (
          <EmptyState
            title="AVA"
            description="Start a new conversation to begin."
          />
        )}
      </div>
    </div>
  );
}