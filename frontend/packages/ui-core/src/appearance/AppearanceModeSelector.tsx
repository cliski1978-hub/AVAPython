import { useAppearance } from "./AppearanceProvider";

/** A native, keyboard-first mode selector shared by Settings and the preview. */
export function AppearanceModeSelector() {
  const { themeMode, setThemeMode } = useAppearance();
  return (
    <label className="inline-flex items-center gap-2 text-sm text-foreground">
      <span className="sr-only">Appearance mode</span>
      <select
        aria-label="Appearance mode"
        value={themeMode}
        onChange={(event) => setThemeMode(event.currentTarget.value as typeof themeMode)}
        className="h-9 min-w-40 rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}
