import { defaultTheme } from "@ava/ui-core";

export interface UserMessageProps {
  content: string;
}

const t = defaultTheme;

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div
      data-message-role="user"
      style={{
        display: "flex",
        justifyContent: "flex-end",
        minWidth: 0,
      }}
    >
      <div
        data-message-bubble="user"
        style={{
          width: "fit-content",
          maxWidth: "68%",
          minWidth: 0,
          boxSizing: "border-box",
          background: "hsl(var(--primary))",
          color: "hsl(var(--primary-foreground))",
          borderRadius: t.radius.lg,
          padding: "10px 14px",
          whiteSpace: "pre-wrap",
          lineHeight: 1.5,
          fontSize: t.font.sizeMd,
          overflowWrap: "break-word",
        }}
      >
        {content}
      </div>
    </div>
  );
}
