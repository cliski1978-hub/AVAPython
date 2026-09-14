export function isMeaningfulPrompt(text: string): boolean {
  return text.trim().length > 0;
}

export function rowsForPrompt(
  text: string,
  minRows = 1,
  maxRows = 6,
): number {
  const lines = text.split(/\r\n|\r|\n/).length;
  return Math.min(Math.max(lines, minRows), maxRows);
}

export interface EnterKeyInfo {
  key: string;
  shiftKey?: boolean;
  isComposing?: boolean;
}

export function enterShouldSubmit(info: EnterKeyInfo): boolean {
  return info.key === "Enter" && !info.shiftKey && !info.isComposing;
}