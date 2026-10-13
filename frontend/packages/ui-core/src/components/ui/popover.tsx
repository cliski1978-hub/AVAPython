import {
  Children,
  cloneElement,
  createContext,
  forwardRef,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type MutableRefObject,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "../../lib/utils";

interface PopoverContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  rootRef: MutableRefObject<HTMLDivElement | null>;
  triggerRef: MutableRefObject<HTMLButtonElement | null>;
  contentId: string;
}

const PopoverContext = createContext<PopoverContextValue | null>(null);

function usePopoverContext() {
  const context = useContext(PopoverContext);
  if (context == null) throw new Error("Popover components must be used inside Popover.");
  return context;
}

export interface PopoverProps {
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** AVA's lightweight, non-modal popover surface for contextual controls. */
export function Popover({ children, open: openProp, defaultOpen = false, onOpenChange }: PopoverProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = openProp ?? uncontrolledOpen;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const contentId = useId();
  const setOpen = (next: boolean) => {
    if (openProp === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  };

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <PopoverContext.Provider value={{ open, setOpen, rootRef, triggerRef, contentId }}>
      <div ref={rootRef} className="relative inline-flex" data-popover-root="">
        {children}
      </div>
    </PopoverContext.Provider>
  );
}

export interface PopoverTriggerProps {
  asChild: true;
  children: ReactElement<ButtonHTMLAttributes<HTMLButtonElement>>;
}

export function PopoverTrigger({ children }: PopoverTriggerProps) {
  const { open, setOpen, triggerRef, contentId } = usePopoverContext();
  const child = Children.only(children);

  return cloneElement(child, {
    type: "button",
    "aria-haspopup": "dialog",
    "aria-expanded": open,
    "aria-controls": open ? contentId : undefined,
    onClick: (event) => {
      triggerRef.current = event.currentTarget;
      child.props.onClick?.(event);
      if (!event.defaultPrevented) setOpen(!open);
    },
    onFocus: (event) => {
      triggerRef.current = event.currentTarget;
      child.props.onFocus?.(event);
    },
  });
}

export const PopoverContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => {
    const { open, contentId } = usePopoverContext();
    if (!open) return null;
    return (
      <div
        {...props}
        ref={ref}
        id={contentId}
        role="dialog"
        data-state="open"
        className={cn(
          "absolute bottom-[calc(100%+0.5rem)] left-0 z-50 rounded-xl border border-border bg-popover text-popover-foreground shadow-lg",
          className,
        )}
      />
    );
  },
);
PopoverContent.displayName = "PopoverContent";
