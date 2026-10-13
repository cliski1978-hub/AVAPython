import { describe, expect, it } from "vitest";

import { Button, buttonVariants } from "./button";

describe("shared shadcn Button", () => {
  it("keeps rounded geometry across every variant and size", () => {
    for (const variant of ["default", "secondary", "destructive", "outline", "ghost", "navigation"] as const) {
      expect(buttonVariants({ variant })).toContain("rounded-md");
    }
    for (const size of ["sm", "default", "lg", "icon"] as const) {
      expect(buttonVariants({ size })).toContain("rounded-md");
    }
  });

  it("renders disabled controls with the same shared radius", () => {
    const button = <Button disabled>Save</Button>;
    expect(button.props.disabled).toBe(true);
    expect(buttonVariants({ variant: "default", size: "default" })).toContain("rounded-md");
  });

  it("provides a transparent semantic navigation-action treatment", () => {
    const classes = buttonVariants({ variant: "navigation", size: "sm" });
    expect(classes).toContain("border-0");
    expect(classes).toContain("bg-transparent");
    expect(classes).toContain("text-foreground");
    expect(classes).toContain("hover:bg-muted");
    expect(classes).toContain("focus-visible:ring-2");
    expect(classes).toContain("h-8");
    expect(classes).not.toContain("bg-primary");
  });
});
