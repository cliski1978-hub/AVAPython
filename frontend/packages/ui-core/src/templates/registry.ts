export const TemplateRegistry = {
  "ava-default": {
    id: "ava-default",
    label: "AVA Default",
    description: "The standard AVA workspace composition.",
  },
} as const;

export type TemplateId = keyof typeof TemplateRegistry;

export function isTemplateId(value: unknown): value is TemplateId {
  return typeof value === "string" && value in TemplateRegistry;
}
