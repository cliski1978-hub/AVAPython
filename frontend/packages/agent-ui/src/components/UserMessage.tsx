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
          maxWidth: "68%",
          minWidth: 0,
          boxSizing: "border-box",
          background: t.colors.primary,
          color: t.colors.onPrimary,
          borderRadius: 999,
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