import { ApiClient } from "@ava/api-client";
import { AppWorkspace, createApprovalDataSource } from "@ava/workspace";

const DEFAULT_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = new ApiClient({ baseUrl: DEFAULT_BASE_URL });
const approvalDataSource = createApprovalDataSource(client);

export function App() {
  return <AppWorkspace client={client} approvalDataSource={approvalDataSource} enableDesignSystemPreview={import.meta.env.DEV} />;
}
