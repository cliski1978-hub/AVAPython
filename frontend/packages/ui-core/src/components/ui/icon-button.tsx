import type { LucideIcon } from "lucide-react";

import { cn } from "../../lib/utils";
import { Button, type ButtonProps } from "./button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

export interface IconButtonProps extends Omit<ButtonProps, "children" | "size" | "aria-label"> {
  /** Lucide icon component for this contextual action. */
  icon: LucideIcon;
  /** Required accessible name; tooltip text never substitutes for it. */
  label: string;
  /** Tooltip text, false only when a tooltip is intentionally unnecessary. Defaults to label. */
  tooltip?: string | false;
  /** Standard 36px control or compact 32px toolbar control. */
  size?: "default" | "compact";
  /** Circular is an intentional exception; rounded rectangle is the default. */
  shape?: "rounded" | "circle";
  /** Transparent, semantic treatment for contextual actions in dense rows. */
  appearance?: "default" | "row-action";
}

/** Canonical AVA icon action. Geometry and states come from the shared Button. */
export function IconButton({
  icon: Icon,
  label,
  tooltip = label,
  size = "default",
  shape = "rounded",
  appearance = "default",
  variant = "ghost",
  className,
  ...buttonProps
}: IconButtonProps) {
  const control = (
    <Button
      {...buttonProps}
      aria-label={label}
      variant={variant}
      size="icon"
      className={cn(
        size === "compact" && "h-8 w-8",
        shape === "circle" && "rounded-full",
        appearance === "row-action" &&
          "border-0 bg-transparent text-muted-foreground shadow-none hover:bg-muted hover:text-foreground aria-expanded:bg-secondary aria-expanded:text-foreground",
        className,
      )}
    >
      <Icon aria-hidden="true" focusable="false" className={size === "compact" ? "size-4" : "size-[18px]"} />
    </Button>
  );

  if (tooltip === false) return control;
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>{control}</TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
