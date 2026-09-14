import { useState } from "react";

export interface UseInteractionResult {
  hovered: boolean;
  focused: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onFocus: () => void;
  onBlur: () => void;
}

/**
 * Tracks hover/focus for inline-style interaction states.
 * Returns inactive (all false) when `enabled` is false, so disabled controls
 * do not display hover or focus styling.
 */
export function useInteraction(enabled: boolean): UseInteractionResult {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);

  return {
    hovered: enabled && hovered,
    focused: enabled && focused,
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
  };
}