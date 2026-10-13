import assert from "node:assert/strict";
import { createFixtures, getConversation, getRun, listRuns } from "../fixtures.mjs";

const primaryLink = (route) => $(`nav[aria-label="Primary"] a[href="${route}"]`);
const conversationRow = (title) => $(`button[data-conversation-item][title="${title}"]`);
const waitForText = async (selector, text) => {
  const element = $(selector);
  await element.waitForDisplayed({ timeout: 15_000 });
  await browser.waitUntil(async () => (await element.getText()).includes(text), { timeout: 15_000 });
  return element;
};

async function openChat() {
  await primaryLink("/").click();
  await $("button=New Chat").waitForDisplayed();
  const activeView = $('[data-conversation-view="active"]');
  if (await activeView.getAttribute("aria-pressed") !== "true") await activeView.click();
}

async function selectConversation(title) {
  const row = conversationRow(title);
  await row.waitForDisplayed({ timeout: 15_000 });
  await row.click();
  await browser.waitUntil(async () => (await row.getAttribute("aria-current")) === "true", { timeout: 15_000 });
  return row;
}

async function assertTranscript(title, transcript, notTranscript) {
  const row = await selectConversation(title);
  assert.equal(await row.getAttribute("aria-current"), "true");
  await browser.waitUntil(async () => {
    const messages = await $('[data-message-scroll]').getText();
    return messages.includes(transcript) && !messages.includes(notTranscript);
  }, { timeout: 15_000, timeoutMsg: `Expected only ${title}'s transcript in the conversation view.` });
  const messages = await $('[data-message-scroll]').getText();
  assert.ok(messages.includes(transcript));
  assert.ok(!messages.includes(notTranscript));
}

async function clickConversationAction(title, action) {
  await selectConversation(title);
  await $(`button[aria-label="Conversation actions for ${title}"]`).click();
  await $('[role="menu"]').waitForDisplayed();
  await $(`[role="menuitem"]=${action}`).click();
}

async function moveFromUi(title, destinationType, destinationName) {
  await clickConversationAction(title, "Move");
  const dialog = $('[role="dialog"]');
  await dialog.waitForDisplayed();
  if (destinationType === "Project") {
    await dialog.$('input[name="conversation-move-type"][value="project"]').click();
  } else {
    await dialog.$('input[name="conversation-move-type"][value="folder"]').click();
  }
  const destination = dialog.$('select[aria-label="Move destination"]');
  await destination.selectByVisibleText(destinationName);
  await dialog.$("button=Move").click();
  await dialog.waitForDisplayed({ reverse: true });
}

async function sendPrompt(conversationId, prompt) {
  const composer = $('textarea[aria-label="Message"]');
  await composer.waitForDisplayed();
  await composer.setValue(prompt);
  await $('button[aria-label="Send"]').click();
  await browser.waitUntil(async () => (await listRuns(conversationId)).length > 0, {
    timeout: 30_000,
    timeoutMsg: "The Desktop composer did not create a run.",
  });
  let runs = await listRuns(conversationId);
  const run = runs.at(-1);
  await browser.waitUntil(async () => {
    const current = await getRun(run.run_id);
    return ["completed", "failed", "cancelled"].includes(current.status);
  }, { timeout: 45_000, timeoutMsg: `Run ${run.run_id} did not reach a terminal state.` });
  const result = await getRun(run.run_id);
  assert.equal(result.status, "completed", `Mock-backed E2E run failed: ${JSON.stringify(result)}`);
  return result;
}

async function selectInspectorRun(runId) {
  const selector = $('select[aria-label="Select run"]');
  await selector.waitForDisplayed();
  await selector.selectByAttribute("value", runId);
  await browser.waitUntil(async () => await selector.getValue() === runId, { timeout: 15_000 });
}

async function assertInspectorRequest(runId, marker) {
  await selectInspectorRun(runId);
  await $('[role="tab"]=Request').click();
  await browser.waitUntil(async () => {
    const text = await $('[role="complementary"][aria-label="Run Inspector"]').getText();
    return text.includes(marker);
  }, { timeout: 15_000, timeoutMsg: `Inspector request did not show ${marker}.` });
  const text = await $('[role="complementary"][aria-label="Run Inspector"]').getText();
  assert.ok(text.includes(marker));
}

async function openProject(project) {
  await primaryLink("/projects").click();
  await $("h1=Projects").waitForDisplayed();
  await $(`button=${project.name}`).click();
  await $(`h1=${project.name}`).waitForDisplayed();
}

async function assertNoHorizontalOverflow() {
  const overflow = await browser.execute(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  assert.equal(overflow, false, "Desktop page has blocking horizontal overflow.");
}

let fixtures;

describe("AVA Desktop Phase 5 acceptance", function () {
  this.timeout(120_000);

  before(async () => {
    fixtures = await createFixtures();
    await browser.refresh();
    await openChat();
  });

  it("switches Conversation A → B → A without leaking transcript, draft, attachment, or Inspector state", async () => {
    const { names, conversationA, conversationB, attachment } = fixtures;
    await assertTranscript(names.conversationA, `Transcript A ${fixtures.suffix}`, "Transcript B");
    const composer = $('textarea[aria-label="Message"]');
    await composer.setValue("Disposable draft for Conversation A");
    await $(`[aria-label="Conversation attachments"]`).waitForDisplayed();
    assert.match(await $('[aria-label="Conversation attachments"]').getText(), /R43-A-/);

    await assertTranscript(names.conversationB, "Transcript B", "Transcript A");
    assert.equal(await composer.getValue(), "", "Conversation A draft leaked into Conversation B.");
    assert.equal(await $('[aria-label="Conversation attachments"]').isExisting(), false, "Conversation A attachment leaked into Conversation B.");

    await assertTranscript(names.conversationA, "Transcript A", "Transcript B");
    assert.equal(await composer.getValue(), "Disposable draft for Conversation A");
    assert.ok((await $('[aria-label="Conversation attachments"]').getText()).includes(attachment.file_name));

    // Rapid back-and-forth exercises the native app's selection transitions without waiting between clicks.
    await conversationRow(names.conversationB).click();
    await conversationRow(names.conversationA).click();
    await browser.waitUntil(async () => (await conversationRow(names.conversationA).getAttribute("aria-current")) === "true", { timeout: 15_000 });
    await browser.waitUntil(async () => (await $('[data-message-scroll]').getText()).includes("Transcript A"), { timeout: 15_000 });
    assert.ok(!(await $('[data-message-scroll]').getText()).includes("Transcript B"));
    assert.ok(await getConversation(conversationA.conversation_id));
    assert.ok(await getConversation(conversationB.conversation_id));
  });

  it("switches Folder A → its conversation → Folder B and verifies exclusive membership", async () => {
    const { folderA, folderB, folderAConversation, folderBConversation, names } = fixtures;
    await openChat();
    const folderAButton = $(`[data-folder-toggle="${folderA.id}"]`);
    const folderBButton = $(`[data-folder-toggle="${folderB.id}"]`);
    await folderAButton.waitForDisplayed();
    await folderBButton.waitForDisplayed();
    assert.equal(await folderAButton.getAttribute("aria-expanded"), "true");
    assert.equal(await folderBButton.getAttribute("aria-expanded"), "true");
    await assertTranscript(names.folderAConversation, `${names.folderAConversation} transcript`, names.folderBConversation);
    assert.ok(await conversationRow(names.folderAConversation).isDisplayed());
    assert.equal((await getConversation(folderAConversation.conversation_id)).folder_id, folderA.id);

    await assertTranscript(names.folderBConversation, `${names.folderBConversation} transcript`, names.folderAConversation);
    assert.ok(await conversationRow(names.folderBConversation).isDisplayed());
    assert.equal((await getConversation(folderBConversation.conversation_id)).folder_id, folderB.id);
    await folderAButton.click();
    await conversationRow(names.folderAConversation).waitForDisplayed({ reverse: true });
    await folderAButton.click();
    await conversationRow(names.folderAConversation).waitForDisplayed();
  });

  it("switches Project A → Project B → Project A and keeps title, instructions, conversations, and files isolated", async () => {
    const { projectA, projectB, names, projectAConversation, projectBConversation, projectAFile, projectBFile } = fixtures;
    await openProject(projectA);
    assert.ok((await $('[role="tabpanel"]').getText()).includes(`${projectA.name} description`));
    await $('[role="tab"][aria-controls="project-section-conversations"]').click();
    await waitForText('[role="tabpanel"]:not([hidden])', names.projectAConversation);
    assert.ok(!(await $('[role="tabpanel"]:not([hidden])').getText()).includes(names.projectBConversation));

    await $('[role="tab"][aria-controls="project-section-files"]').click();
    await waitForText('[role="tabpanel"]:not([hidden])', projectAFile.file_name);
    assert.ok(!(await $('[role="tabpanel"]:not([hidden])').getText()).includes(projectBFile.file_name));
    await $('[role="tab"][aria-controls="project-section-instructions"]').click();
    assert.equal(await $('[aria-label="Project instructions"]').getValue(), projectA.instructions);

    await $('button[aria-label="Back to Projects"]').click();
    await $(`button=${projectB.name}`).waitForDisplayed();
    await $(`button=${projectB.name}`).click();
    await $(`h1=${projectB.name}`).waitForDisplayed();
    assert.ok((await $('[role="tabpanel"]').getText()).includes(`${projectB.name} description`));
    await $('[role="tab"][aria-controls="project-section-conversations"]').click();
    await waitForText('[role="tabpanel"]:not([hidden])', names.projectBConversation);
    assert.ok(!(await $('[role="tabpanel"]:not([hidden])').getText()).includes(names.projectAConversation));
    await $('[role="tab"][aria-controls="project-section-files"]').click();
    await waitForText('[role="tabpanel"]:not([hidden])', projectBFile.file_name);
    assert.ok(!(await $('[role="tabpanel"]:not([hidden])').getText()).includes(projectAFile.file_name));
    await $('[role="tab"][aria-controls="project-section-instructions"]').click();
    assert.equal(await $('[aria-label="Project instructions"]').getValue(), projectB.instructions);

    await $('button[aria-label="Back to Projects"]').click();
    await $(`button=${projectA.name}`).click();
    await $(`h1=${projectA.name}`).waitForDisplayed();
    await $('[role="tab"][aria-controls="project-section-conversations"]').click();
    await waitForText('[role="tabpanel"]:not([hidden])', names.projectAConversation);
    assert.equal((await getConversation(projectAConversation.conversation_id)).project_id, projectA.id);
    assert.equal((await getConversation(projectBConversation.conversation_id)).project_id, projectB.id);
  });

  it("navigates Models → Runtimes → Providers → CORE Prompts and returns to a valid conversation", async () => {
    await primaryLink("/settings").click();
    await $('[role="tablist"]').waitForDisplayed();
    for (const section of ["Models", "Runtimes", "Providers", "System Prompts"]) {
      const tab = $(`[role="tab"][aria-label="${section}"]`);
      if (!(await tab.isExisting())) await $(`[role="tab"]=${section}`).click();
      else await tab.click();
      await browser.waitUntil(async () => {
        const selected = $('[role="tab"][aria-selected="true"]');
        return (await selected.getText()).includes(section);
      }, { timeout: 15_000 });
      await $('[role="tabpanel"]:not([hidden])').waitForDisplayed();
      assert.ok((await $('[role="tabpanel"]:not([hidden])').getText()).length > 0, `${section} rendered no current content.`);
    }
    await waitForText('[data-core-prompt]', fixtures.corePrompt.name);
    await primaryLink("/").click();
    await assertTranscript(fixtures.names.conversationA, "Transcript A", "Transcript B");
  });

  it("switches Run Inspector Run A → B → A and checks prompts, requests, responses, metadata, events, and attachments", async () => {
    const { conversationA, names, attachment } = fixtures;
    await openChat();
    await selectConversation(names.conversationA);
    const runA = await sendPrompt(conversationA.conversation_id, "R43 inspector run A unique marker");
    const runB = await sendPrompt(conversationA.conversation_id, "R43 inspector run B unique marker");
    const runs = await listRuns(conversationA.conversation_id);
    assert.ok(runs.some((item) => item.run_id === runA.run_id));
    assert.ok(runs.some((item) => item.run_id === runB.run_id));

    const toggle = $('[aria-label="Toggle Run Inspector"]');
    if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
    const inspector = $('[role="complementary"][aria-label="Run Inspector"]');
    await inspector.waitForDisplayed();
    await assertInspectorRequest(runA.run_id, "R43 inspector run A unique marker");
    assert.ok((await inspector.getText()).includes("Normalized AVA Request"));
    await $('[role="tab"]=Prompts').click();
    await waitForText('[role="complementary"][aria-label="Run Inspector"]', "Current User Message");
    await $('[role="tab"]=Response').click();
    await waitForText('[role="complementary"][aria-label="Run Inspector"]', "Final Assistant Message");
    await $('[role="tab"]=Run').click();
    await waitForText('[role="complementary"][aria-label="Run Inspector"]', attachment.file_name);
    assert.ok((await inspector.getText()).includes(runA.run_id));
    await $('[role="tab"]=Events').click();
    await browser.waitUntil(async () => (await inspector.getText()).includes("event"), { timeout: 15_000 });

    await assertInspectorRequest(runB.run_id, "R43 inspector run B unique marker");
    assert.ok(!(await inspector.getText()).includes("R43 inspector run A unique marker"));
    await assertInspectorRequest(runA.run_id, "R43 inspector run A unique marker");
    assert.ok(!(await inspector.getText()).includes("R43 inspector run B unique marker"));

    await selectConversation(names.conversationB);
    await browser.waitUntil(async () => (await $('select[aria-label="Select run"]').getValue()) === "", { timeout: 15_000 });
    await assertTranscript(names.conversationB, "Transcript B", "Transcript A");
    await selectConversation(names.conversationA);
    await browser.waitUntil(async () => (await $$('select[aria-label="Select run"] option')).length >= 3, { timeout: 15_000 });
    await assertInspectorRequest(runA.run_id, "R43 inspector run A unique marker");
  });

  it("renders Light, Dark, and System across the sidebar, conversation, composer, settings, prompt cards, and Inspector", async () => {
    const { names, corePrompt } = fixtures;
    await primaryLink("/settings").click();
    for (const theme of ["light", "dark", "system"]) {
      await $('[role="tab"]=Appearance').click();
      const mode = $('select[aria-label="Appearance mode"]');
      await mode.selectByAttribute("value", theme);
      await browser.waitUntil(async () => {
        const dark = await browser.execute(() => document.documentElement.classList.contains("dark"));
        if (theme === "light") return dark === false;
        if (theme === "dark") return dark === true;
        return dark === await browser.execute(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
      }, { timeout: 15_000 });
      assert.equal((await $('[role="tab"][aria-selected="true"]').getText()).trim(), "Appearance");
      assert.equal(await $('select[aria-label="Appearance mode"]').isDisplayed(), true);
      await primaryLink("/").click();
      await selectConversation(names.conversationA);
      assert.ok((await $('aside[aria-label="Conversation sidebar"]').getAttribute("class")).includes("bg-card"));
      assert.ok((await $('aside[aria-label="Conversation sidebar"]').getAttribute("class")).includes("text-card-foreground"));
      assert.ok((await $('[data-prompt-composer]').getAttribute("class")).includes("bg-card"));
      assert.ok((await $('[data-prompt-composer]').getAttribute("class")).includes("text-card-foreground"));
      assert.ok((await $('[data-message-role="user"]').getText()).includes("Transcript A"));
      const toggle = $('[aria-label="Toggle Run Inspector"]');
      if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
      assert.ok((await $('[role="complementary"][aria-label="Run Inspector"]').getAttribute("class")).includes("text-foreground"));
      await primaryLink("/settings").click();
      await $('[role="tab"]=System Prompts').click();
      const card = $(`[data-core-prompt="${corePrompt.id}"]`);
      await card.waitForDisplayed();
      const cardClass = await card.getAttribute("class");
      assert.ok(cardClass.includes("bg-card") && cardClass.includes("text-card-foreground") && cardClass.includes("border-border"));
      assert.ok((await card.getText()).includes(corePrompt.name));
      await assertNoHorizontalOverflow();
    }
  });

  it("resizes the native window narrow → default → wide while navigation and Settings controls remain usable", async function () {
    const { names, conversationA } = fixtures;
    await openChat();
    await selectConversation(names.conversationA);
    const run = (await listRuns(conversationA.conversation_id)).at(-1);
    assert.ok(run, "Resize smoke requires a historical run from the preceding Inspector scenario.");
    const toggle = $('[aria-label="Toggle Run Inspector"]');
    if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
    await selectInspectorRun(run.run_id);

    const original = await browser.getWindowRect();
    const wideWidth = Math.min(1240, Math.max(1200, original.width + 100));
    const sizes = [
      { label: "narrow", width: 820, height: Math.min(original.height, 720) },
      { label: "default", width: original.width, height: original.height },
      { label: "wide", width: wideWidth, height: original.height },
    ];
    try {
      for (const size of sizes) {
        await browser.setWindowRect({ x: original.x, y: original.y, width: size.width, height: size.height });
        await browser.waitUntil(async () => {
          const rect = await browser.getWindowRect();
          return Math.abs(rect.width - size.width) <= 40 && rect.height > 0;
        }, { timeout: 10_000, timeoutMsg: `Tauri window did not reach the ${size.label} size.` });

        await openChat();
        await selectConversation(names.conversationA);
        assert.equal(await $('[data-prompt-composer]').isDisplayed(), true);
        const inspector = $('[role="complementary"][aria-label="Run Inspector"]');
        await inspector.waitForDisplayed();
        await selectInspectorRun(run.run_id);
        assert.ok((await inspector.getText()).includes(run.run_id));
        const layout = await browser.execute(() => {
          const sidebar = document.querySelector("[data-conversation-list]")?.getBoundingClientRect();
          const composer = document.querySelector("[data-prompt-composer]")?.getBoundingClientRect();
          const inspectorPanel = document.querySelector('[aria-label="Run Inspector"]')?.getBoundingClientRect();
          return {
            width: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            sidebarWidth: sidebar?.width ?? 0,
            composerRight: composer?.right ?? 0,
            inspectorRight: inspectorPanel?.right ?? 0,
          };
        });
        assert.ok(layout.sidebarWidth > 100, `Sidebar unusable at ${size.label} width.`);
        assert.ok(layout.composerRight > 0 && layout.composerRight <= layout.width + 1, `Composer clipped at ${size.label} width.`);
        assert.ok(layout.inspectorRight > 0 && layout.inspectorRight <= layout.width + 1, `Inspector clipped at ${size.label} width.`);
        assert.ok(layout.scrollWidth <= layout.width + 1, `Horizontal overflow at ${size.label} width.`);

        await primaryLink("/settings").click();
        await $('[role="tab"]=Models').click();
        assert.equal(await $('[role="tabpanel"]:not([hidden])').isDisplayed(), true);
        await $('[role="tab"]=Appearance').click();
        assert.equal(await $('select[aria-label="Appearance mode"]').isDisplayed(), true);
        await openChat();
        await selectConversation(names.conversationA);
      }
    } finally {
      await browser.setWindowRect({ x: original.x, y: original.y, width: original.width, height: original.height });
    }
  });

  it("archives the selected disposable conversation, verifies fallback, then restores it", async () => {
    const { names, archiveConversation } = fixtures;
    await openChat();
    await clickConversationAction(names.archiveConversation, "Archive");
    await browser.waitUntil(async () => (await getConversation(archiveConversation.conversation_id)).is_archived === true, { timeout: 15_000 });
    await conversationRow(names.archiveConversation).waitForDisplayed({ reverse: true });
    const activeSelection = $('[data-conversation-item][aria-current="true"]');
    await activeSelection.waitForDisplayed();
    assert.notEqual(await activeSelection.getAttribute("title"), names.archiveConversation);

    await $('[data-conversation-view="archived"]').click();
    const archivedRow = await conversationRow(names.archiveConversation);
    await archivedRow.waitForDisplayed();
    await archivedRow.click();
    await $(`button[aria-label="Conversation actions for ${names.archiveConversation}"]`).click();
    await $('[role="menuitem"]=Restore').click();
    await browser.waitUntil(async () => (await getConversation(archiveConversation.conversation_id)).is_archived === false, { timeout: 15_000 });
  });

  it("permanently deletes only R43 Desktop Delete Test and keeps a valid selection after reload", async () => {
    const title = "R43 Desktop Delete Test";
    const conversation = await (await import("../fixtures.mjs")).api("/conversations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    });
    await browser.refresh();
    await openChat();
    const row = await selectConversation(title);
    assert.ok(row);
    await clickConversationAction(title, "Delete");
    const dialog = $('[role="dialog"]');
    await dialog.waitForDisplayed();
    assert.ok((await dialog.getText()).includes(`Delete “${title}” permanently?`));
    await dialog.$("button=Delete permanently").click();
    await dialog.waitForDisplayed({ reverse: true });
    await conversationRow(title).waitForDisplayed({ reverse: true });
    await $('[data-conversation-item][aria-current="true"]').waitForDisplayed();
    await browser.refresh();
    await openChat();
    assert.equal(await conversationRow(title).isExisting(), false);
    await $('[data-conversation-item][aria-current="true"]').waitForDisplayed();
    const response = await fetch(new URL(`/conversations/${encodeURIComponent(conversation.conversation_id)}`, process.env.AVA_TEST_API_URL));
    assert.equal(response.status, 404);
  });

  it("moves a disposable conversation Folder A → Project A → Folder B → Ungrouped", async () => {
    const { names, folderA, folderB, projectA, moveConversation } = fixtures;
    await openChat();
    await moveFromUi(names.moveConversation, "Project", projectA.name);
    let snapshot = await getConversation(moveConversation.conversation_id);
    assert.equal(snapshot.folder_id, null);
    assert.equal(snapshot.project_id, projectA.id);
    assert.equal(await conversationRow(names.moveConversation).isExisting(), false, "Conversation remained in its old folder after relocation.");

    const projectToggle = $(`[data-project-toggle="${projectA.id}"]`);
    if (await projectToggle.getAttribute("aria-expanded") !== "true") await projectToggle.click();
    await selectConversation(names.moveConversation);
    await moveFromUi(names.moveConversation, "Folder", folderB.name);
    snapshot = await getConversation(moveConversation.conversation_id);
    assert.equal(snapshot.project_id, null);
    assert.equal(snapshot.folder_id, folderB.id);
    assert.ok(await conversationRow(names.moveConversation).isDisplayed());

    await moveFromUi(names.moveConversation, "Folder", "Ungrouped");
    snapshot = await getConversation(moveConversation.conversation_id);
    assert.equal(snapshot.folder_id, null);
    assert.equal(snapshot.project_id, null);
    assert.ok(await conversationRow(names.moveConversation).isDisplayed());
    assert.notEqual(folderA.id, folderB.id);
  });
});
