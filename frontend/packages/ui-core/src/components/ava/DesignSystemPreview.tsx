import { useState } from "react";
import {
  Archive, ArrowUp, Copy, Download, Ellipsis, Pencil, Plus, RefreshCw, Search,
  Settings, Square, Trash2, Upload, X, type LucideIcon,
} from "lucide-react";

import { useAppearance } from "../../appearance";
import { AppearanceModeSelector } from "../../appearance/AppearanceModeSelector";
import * as ui from "../ui";

const actionIcons: Array<{ icon: LucideIcon; label: string }> = [
  { icon: Plus, label: "Add" }, { icon: Search, label: "Search" },
  { icon: Pencil, label: "Rename" }, { icon: Copy, label: "Copy" },
  { icon: RefreshCw, label: "Retry" }, { icon: Archive, label: "Archive" },
  { icon: Trash2, label: "Delete" }, { icon: Download, label: "Download" },
  { icon: Upload, label: "Upload" }, { icon: Settings, label: "Settings" },
  { icon: Ellipsis, label: "More actions" }, { icon: X, label: "Close" },
  { icon: ArrowUp, label: "Send" }, { icon: Square, label: "Stop" },
];

const swatches = ["background", "foreground", "card", "primary", "secondary", "muted", "accent", "destructive", "border", "chart-1", "chart-2", "chart-3", "chart-4", "chart-5"];
const swatchClass: Record<string, string> = {
  background: "bg-background", foreground: "bg-foreground", card: "bg-card", primary: "bg-primary",
  secondary: "bg-secondary", muted: "bg-muted", accent: "bg-accent", destructive: "bg-destructive",
  border: "bg-border", "chart-1": "bg-chart-1", "chart-2": "bg-chart-2", "chart-3": "bg-chart-3",
  "chart-4": "bg-chart-4", "chart-5": "bg-chart-5",
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <ui.Card><ui.CardHeader><ui.CardTitle>{title}</ui.CardTitle></ui.CardHeader><ui.CardContent className="space-y-4">{children}</ui.CardContent></ui.Card>;
}

export function DesignSystemPreview() {
  const appearance = useAppearance();
  const [checked, setChecked] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  return (
    <main className="min-h-screen space-y-6 bg-background p-6 text-foreground md:p-10">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div><h1 className="text-3xl font-semibold">AVA Design System Preview</h1><p className="text-muted-foreground">Shared UI primitives and semantic theme tokens.</p></div>
        <AppearanceModeSelector />
      </header>
      <ui.Card><ui.CardContent className="grid gap-2 p-4 text-sm sm:grid-cols-4">
        <div>Template: <strong>{appearance.templateId}</strong></div><div>Theme: <strong>{appearance.themeName}</strong></div>
        <div>Mode: <strong>{appearance.themeMode}</strong></div><div>Resolved Mode: <strong>{appearance.resolvedThemeMode}</strong></div>
      </ui.CardContent></ui.Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Buttons">
          <p className="text-sm text-muted-foreground">AVA Button Standard — rounded shared geometry, independent of theme mode.</p>
          <div className="flex flex-wrap gap-2"><ui.Button>Primary</ui.Button><ui.Button variant="secondary">Secondary</ui.Button><ui.Button variant="destructive">Destructive</ui.Button><ui.Button variant="outline">Outline</ui.Button><ui.Button variant="ghost">Ghost</ui.Button><ui.Button disabled>Disabled</ui.Button></div>
          <div className="flex flex-wrap items-center gap-2"><ui.Button size="sm">Small</ui.Button><ui.Button>Default size</ui.Button><ui.Button size="lg">Large</ui.Button><ui.Button size="icon" aria-label="Add"><Plus aria-hidden="true" className="size-[18px]" /></ui.Button></div>
          <div className="flex gap-2"><ui.Badge>Default</ui.Badge><ui.Badge variant="secondary">Secondary</ui.Badge><ui.Badge variant="outline">Outline</ui.Badge></div>
        </Panel>
        <Panel title="Icon Actions">
          <p className="text-sm text-muted-foreground">AVA Action Standard — Lucide icon-first controls for familiar contextual actions.</p>
          <div className="flex flex-wrap gap-2">{actionIcons.map(({ icon, label }) => <ui.IconButton key={label} icon={icon} label={label} />)}</div>
          <ui.Separator />
          <div className="flex flex-wrap items-center gap-2">
            <ui.IconButton icon={Plus} label="Add item" tooltip="Add item" />
            <ui.IconButton icon={Search} label="Compact search" size="compact" />
            <ui.IconButton icon={Copy} label="Copy item" variant="ghost" />
            <ui.IconButton icon={Upload} label="Upload file" variant="outline" />
            <ui.IconButton icon={Trash2} label="Delete item" variant="destructive" />
            <ui.IconButton icon={Trash2} label="Unavailable delete" variant="ghost" disabled />
            <ui.IconButton icon={ArrowUp} label="Send message" shape="circle" variant="default" />
            <ui.Button><Plus aria-hidden="true" className="size-4" />Create Project</ui.Button>
          </div>
          <p className="text-xs text-muted-foreground">Icon-only actions keep an accessible name; tooltips add context. Circular geometry is an intentional exception, not the default.</p>
        </Panel>
        <Panel title="Form controls">
          <ui.Input aria-label="Input" placeholder="Input" /><ui.Input aria-label="Disabled input" placeholder="Disabled input" disabled />
          <ui.Textarea aria-label="Textarea" placeholder="Textarea" />
          <ui.Select defaultValue="one"><ui.SelectTrigger aria-label="Preview select"><ui.SelectValue /></ui.SelectTrigger><ui.SelectContent><ui.SelectItem value="one">Option one</ui.SelectItem><ui.SelectItem value="two">Option two</ui.SelectItem></ui.SelectContent></ui.Select>
          <div className="flex flex-wrap gap-5">
            <label className="flex items-center gap-3 text-sm">Checked <ui.Switch checked={checked} onCheckedChange={setChecked} aria-label="Preview switch" /></label>
            <label className="flex items-center gap-3 text-sm">Unchecked <ui.Switch aria-label="Unchecked preview switch" /></label>
          </div>
        </Panel>
        <Panel title="Interactive components">
          <ui.DropdownMenu><ui.DropdownMenuTrigger asChild><ui.Button variant="outline">Open menu</ui.Button></ui.DropdownMenuTrigger><ui.DropdownMenuContent><ui.DropdownMenuItem>Menu item</ui.DropdownMenuItem></ui.DropdownMenuContent></ui.DropdownMenu>
          <ui.TooltipProvider><ui.Tooltip><ui.TooltipTrigger asChild><ui.Button variant="secondary">Hover or focus</ui.Button></ui.TooltipTrigger><ui.TooltipContent>AVA shared tooltip</ui.TooltipContent></ui.Tooltip></ui.TooltipProvider>
          <ui.Button onClick={() => setDialogOpen(true)}>Open dialog</ui.Button>
          <ui.Dialog open={dialogOpen} onOpenChange={setDialogOpen}><ui.DialogContent><ui.DialogHeader><ui.DialogTitle>Dialog preview</ui.DialogTitle><ui.DialogDescription>Shared Radix dialog primitive.</ui.DialogDescription></ui.DialogHeader><ui.DialogFooter><ui.DialogClose asChild><ui.Button variant="outline">Close</ui.Button></ui.DialogClose></ui.DialogFooter></ui.DialogContent></ui.Dialog>
          <ui.Tabs defaultValue="first"><ui.TabsList><ui.TabsTrigger value="first">First</ui.TabsTrigger><ui.TabsTrigger value="second">Second</ui.TabsTrigger></ui.TabsList><ui.TabsContent value="first">First tab content</ui.TabsContent><ui.TabsContent value="second">Second tab content</ui.TabsContent></ui.Tabs>
        </Panel>
        <Panel title="Semantic tokens and loading shapes">
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">{swatches.map((name) => <div key={name} className="space-y-1 text-xs"><div className={`h-8 rounded border ${swatchClass[name]}`} /><span>{name}</span></div>)}</div>
          <ui.Separator />
          <div className="flex items-center gap-3"><ui.Skeleton className="size-10 rounded-full" /><ui.Skeleton className="h-4 w-40" /></div>
          <ui.Card><ui.CardContent className="space-y-3 p-4"><ui.Skeleton className="h-4 w-2/3" /><ui.Skeleton className="h-3 w-full" /><ui.Skeleton className="h-3 w-4/5" /></ui.CardContent></ui.Card>
          <ui.ScrollArea className="h-36 rounded border p-3"><div className="space-y-4">{Array.from({ length: 5 }, (_, i) => <div key={i} className="flex items-start gap-3"><ui.Skeleton className="size-8 shrink-0 rounded-full" /><div className="flex flex-1 flex-col gap-2"><ui.Skeleton className="h-3 w-1/3" /><ui.Skeleton className="h-3 w-full" /><ui.Skeleton className="h-3 w-4/5" /></div></div>)}</div></ui.ScrollArea>
        </Panel>
      </div>
    </main>
  );
}
