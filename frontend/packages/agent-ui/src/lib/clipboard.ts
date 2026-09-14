/**
 * Copy text to the clipboard where a browser clipboard API is available.
 * Returns `false` (without throwing) when unavailable or on failure, so the
 * UI can degrade gracefully outside secure contexts.
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (
      typeof navigator === "undefined" ||
      typeof navigator.clipboard?.writeText !== "function"
    ) {
      return false;
    }
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}