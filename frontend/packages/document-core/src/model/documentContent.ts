/** Serializable, editor-neutral content owned by AVA. */
export interface DocumentContent {
  format: "html";
  value: string;
}

export function htmlContent(value: string): DocumentContent {
  return { format: "html", value };
}
