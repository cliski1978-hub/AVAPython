import { afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

/**
 * jsdom lacks the layout APIs that ProseMirror (used by Tiptap) expects.
 * Provide inert implementations so the editor can be exercised in tests.
 */

type LayoutRect = {
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
  x: number;
  y: number;
  toJSON: () => Record<string, number>;
};

function emptyRect(): LayoutRect {
  return {
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    width: 0,
    height: 0,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  };
}

function emptyRects(): DOMRectList {
  const list: unknown = [];
  Object.defineProperty(list, "item", { value: () => null });
  return list as DOMRectList;
}

function installLayout(proto: object | undefined) {
  if (proto == null) return;
  if (typeof (proto as { getBoundingClientRect?: unknown }).getBoundingClientRect !== "function") {
    Object.defineProperty(proto, "getBoundingClientRect", {
      configurable: true,
      value: emptyRect,
    });
  }
  if (typeof (proto as { getClientRects?: unknown }).getClientRects !== "function") {
    Object.defineProperty(proto, "getClientRects", {
      configurable: true,
      value: emptyRects,
    });
  }
}

beforeAll(() => {
  installLayout(globalThis.HTMLElement?.prototype);
  installLayout(globalThis.SVGElement?.prototype);
  installLayout(globalThis.Text?.prototype);
  installLayout(globalThis.Range?.prototype);
  installLayout(globalThis.Element?.prototype);
});