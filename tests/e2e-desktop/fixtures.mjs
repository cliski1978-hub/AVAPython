const apiBase = process.env.AVA_TEST_API_URL;

if (!apiBase) throw new Error("AVA_TEST_API_URL must point at the isolated E2E backend.");

export async function api(path, init = {}) {
  const response = await fetch(new URL(path, apiBase), init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`AVA fixture request ${init.method ?? "GET"} ${path} failed (${response.status}): ${body}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function json(method, value) {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(value) };
}

async function createFolder(name) {
  return api("/conversation-folders", json("POST", { name }));
}

async function createProject(name) {
  return api("/projects", json("POST", {
    name,
    description: `${name} description`,
    instructions: `${name} instructions`,
  }));
}

async function createConversation(title, { folderId = null, projectId = null, transcript = `${title} transcript` } = {}) {
  const conversation = projectId == null
    ? await api("/conversations", json("POST", { title, folder_id: folderId }))
    : await api(`/projects/${encodeURIComponent(projectId)}/conversations`, json("POST", { title }));
  await api(`/conversations/${encodeURIComponent(conversation.conversation_id)}/messages`, json("POST", {
    content: transcript,
    role: "user",
  }));
  return conversation;
}

async function uploadFile(path, name, contents, mediaType = "text/plain") {
  const form = new FormData();
  form.append("file", new Blob([contents], { type: mediaType }), name);
  return api(path, { method: "POST", body: form });
}

export async function createFixtures() {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const names = {
    conversationA: `R43 E2E Conversation A ${suffix}`,
    conversationB: `R43 E2E Conversation B ${suffix}`,
    folderAConversation: `R43 E2E Folder A Conversation ${suffix}`,
    folderBConversation: `R43 E2E Folder B Conversation ${suffix}`,
    projectAConversation: `R43 E2E Project A Conversation ${suffix}`,
    projectBConversation: `R43 E2E Project B Conversation ${suffix}`,
    moveConversation: `R43 E2E Move Conversation ${suffix}`,
    archiveConversation: `R43 E2E Archive Conversation ${suffix}`,
  };
  const folderA = await createFolder(`R43 E2E Folder A ${suffix}`);
  const folderB = await createFolder(`R43 E2E Folder B ${suffix}`);
  const projectA = await createProject(`R43 E2E Project A ${suffix}`);
  const projectB = await createProject(`R43 E2E Project B ${suffix}`);

  const conversationA = await createConversation(names.conversationA, { transcript: `Transcript A ${suffix}` });
  const conversationB = await createConversation(names.conversationB, { transcript: `Transcript B ${suffix}` });
  const folderAConversation = await createConversation(names.folderAConversation, { folderId: folderA.id });
  const folderBConversation = await createConversation(names.folderBConversation, { folderId: folderB.id });
  const projectAConversation = await createConversation(names.projectAConversation, { projectId: projectA.id, transcript: `Project A conversation ${suffix}` });
  const projectBConversation = await createConversation(names.projectBConversation, { projectId: projectB.id, transcript: `Project B conversation ${suffix}` });
  const moveConversation = await createConversation(names.moveConversation, { folderId: folderA.id });
  const archiveConversation = await createConversation(names.archiveConversation);

  const attachment = await uploadFile(
    `/conversations/${encodeURIComponent(conversationA.conversation_id)}/attachments`,
    `R43-A-${suffix}.txt`,
    `Attachment for Conversation A ${suffix}`,
  );
  const projectAFile = await uploadFile(`/projects/${encodeURIComponent(projectA.id)}/files`, `R43-A-${suffix}.txt`, `Project A file ${suffix}`);
  const projectBFile = await uploadFile(`/projects/${encodeURIComponent(projectB.id)}/files`, `R43-B-${suffix}.txt`, `Project B file ${suffix}`);
  const corePrompt = await api("/core-prompts", json("POST", {
    name: `R43 E2E Prompt ${suffix}`,
    description: `Disposable theme fixture ${suffix}`,
    prompt_text: `Disposable CORE prompt ${suffix}`,
    category: "general",
  }));

  return {
    suffix,
    names,
    folderA,
    folderB,
    projectA,
    projectB,
    conversationA,
    conversationB,
    folderAConversation,
    folderBConversation,
    projectAConversation,
    projectBConversation,
    moveConversation,
    archiveConversation,
    attachment,
    projectAFile,
    projectBFile,
    corePrompt,
  };
}

export async function getConversation(conversationId) {
  return api(`/conversations/${encodeURIComponent(conversationId)}`);
}

export async function listRuns(conversationId) {
  return api(`/runs?conversation_id=${encodeURIComponent(conversationId)}`);
}

export async function getRun(runId) {
  return api(`/runs/${encodeURIComponent(runId)}`);
}
