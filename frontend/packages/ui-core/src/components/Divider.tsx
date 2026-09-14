import { type CSSProperties } from "react";
import { defaultTheme } from "../theme";

export interface DividerProps {
  orientation?: "horizontal" | "vertical";
  /** Gap in px on each side of the divider. */
  spacing?: number;
}

const t = defaultTheme;

export function Divider({
  orientation = "horizontal",
  spacing = 0,
}: DividerProps) {
  const horizontal = orientation === "horizontal";

  const style: CSSProperties = {
    background: t.colors.border,
    flexShrink: 0,
  };

  if (horizontal) {
    style.height = t.border.width;
    style.width = "100%";
    style.margin = `${spacing}px 0`;
  } else {
    style.width = t.border.width;
    style.alignSelf = "stretch";
    style.margin = `0 ${spacing}px`;
  }

  return <div role="separator" style={style} />;
}