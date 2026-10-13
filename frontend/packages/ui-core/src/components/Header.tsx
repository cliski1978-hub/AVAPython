import { type ReactNode } from "react";
import { cn } from "../lib/utils";

const avaWordmark = new URL("../assets/ava-wordmark.png", import.meta.url).href;

export interface HeaderProps {
  title?: string;
  actions?: ReactNode;
}

export function Header({ title = "AVA", actions }: HeaderProps) {
  return (
    <header
      className="flex h-[var(--ava-header-height)] shrink-0 items-center justify-between gap-4 border-b border-border bg-background px-4 text-foreground sm:px-6"
    >
      <h1
        className={cn("m-0 shrink-0 text-base font-semibold tracking-tight")}
      >
        {title === "AVA" ? (
          <img
            data-ava-brand-mark=""
            src={avaWordmark}
            alt="AVA"
            className="h-9 w-[76px] rounded-md object-cover object-center"
          />
        ) : title}
      </h1>
      {actions != null && (
        <div
          className="flex min-w-0 flex-1 items-center justify-end gap-3"
        >
          {actions}
        </div>
      )}
    </header>
  );
}
