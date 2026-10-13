import {
  FileText,
  FolderKanban,
  MessageSquare,
  ShieldCheck,
  Settings,
  type LucideIcon,
} from "lucide-react";
import type { MouseEvent } from "react";
import { cn } from "../lib/utils";

export type PrimaryDestination = "chat" | "projects" | "documents" | "settings" | "approvals";

export interface PrimaryNavProps {
  active: PrimaryDestination;
  onSelect: (destination: PrimaryDestination) => void;
  className?: string;
}

interface PrimaryNavEntry {
  id: PrimaryDestination;
  label: string;
  href: string;
  icon: LucideIcon;
}

const ENTRIES: PrimaryNavEntry[] = [
  { id: "chat", label: "Chat", href: "/", icon: MessageSquare },
  { id: "projects", label: "Projects", href: "/projects", icon: FolderKanban },
  { id: "documents", label: "Documents", href: "/documents", icon: FileText },
  { id: "settings", label: "Settings", href: "/settings", icon: Settings },
  { id: "approvals", label: "Approvals", href: "/approvals", icon: ShieldCheck },
];

function handleNavigationClick(
  event: MouseEvent<HTMLAnchorElement>,
  destination: PrimaryDestination,
  onSelect: (destination: PrimaryDestination) => void,
) {
  if (
    event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
    event.shiftKey || event.altKey
  ) return;
  event.preventDefault();
  onSelect(destination);
}

/** Shared top-level navigation for the active ava-default application shell. */
export function PrimaryNav({ active, onSelect, className }: PrimaryNavProps) {
  return (
    <nav aria-label="Primary" className={cn("min-w-0 overflow-x-auto", className)}>
      <ul className="m-0 flex min-w-max list-none items-center gap-1 p-0">
        {ENTRIES.map(({ id, label, href, icon: Icon }) => (
          <li key={id}>
            <a
              href={href}
              aria-current={active === id ? "page" : undefined}
              onClick={(event) => handleNavigationClick(event, id, onSelect)}
              className={cn(
                "inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium no-underline",
                "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                "aria-[current=page]:bg-secondary aria-[current=page]:text-secondary-foreground",
              )}
            >
              <Icon aria-hidden="true" focusable="false" className="size-4 shrink-0" />
              <span>{label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
