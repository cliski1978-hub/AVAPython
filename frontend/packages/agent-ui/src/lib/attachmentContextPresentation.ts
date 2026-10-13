import type { AttachmentContextItem } from "@ava/contracts";

export function attachmentContextPresentation(item?: AttachmentContextItem) {
  if (!item) return { label: "Stored · context not checked", detail: "Draft a message to check whether this file can contribute text to the resolved model context." };
  switch (item.status) {
    case "included": return { label: item.included ? "Ready for context" : "Not included", detail: "Complete extracted text fits this preview. Inclusion is checked again when the run starts." };
    case "unsupported": return { label: "Stored · text unsupported", detail: "Text content cannot currently be included in model context. The file remains stored." };
    case "extraction_failed": return { label: "Stored · extraction failed", detail: "AVA could not extract text from this attachment. The file remains stored." };
    case "excluded_context_limit": return { label: "Stored · context limit", detail: "Complete file text does not fit the available model context. It is excluded without truncation." };
  }
}

export function attachmentContextSummary(items: AttachmentContextItem[]) {
  const included = items.filter(item => item.included).length;
  return `${included} included · ${items.length - included} not included`;
}
