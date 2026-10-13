import type { FontFamilyId } from "./types";

export const FontFamilyRegistry: Record<FontFamilyId, { label: string; family: string }> = {
  system: {
    label: "System UI",
    family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  lato: { label: "Lato", family: '"Lato", sans-serif' },
  "noto-serif": { label: "Noto Serif", family: '"Noto Serif", Georgia, serif' },
  "noto-sans": { label: "Noto Sans", family: '"Noto Sans", Arial, sans-serif' },
  "dejavu-sans": { label: "DejaVu Sans", family: '"DejaVu Sans", Arial, sans-serif' },
  "liberation-serif": { label: "Liberation Serif", family: '"Liberation Serif", Georgia, serif' },
};

export function isFontFamilyId(value: string | null): value is FontFamilyId {
  return value != null && Object.prototype.hasOwnProperty.call(FontFamilyRegistry, value);
}
