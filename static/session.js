// Fren session page.
//
// IMPORTANT: this page only DISPLAYS the session. The server decides the
// stage, the time left and the messages left, and refuses anything that
// breaks the limits. The countdown here is just for show.

const STAGE_NAMES = {
  checkin: "Check-in",
  focus: "Focus",
  reflection: "Reflect",
  plan: "Plan",
  human_step: "Reach out",
  close: "Close",
};

let secondsLeft = 0;
let timer = null;
let busy = false;  // true while waiting for the server, to stop double-sends

const errorBox = document.getElementById("error");

// Ask the server for the current state and redraw the page.
async function refresh() {
  const result = await api("/api/status");
  if (!result.ok) return;

  const session = result.data.open_session;
  if (!session) {
    window.location.href = "/close";  // the session has ended
    return;
  }
  draw(session);
}

function draw(session) {
  // Progress bar
  const progress = document.getElementById("progress");
  progress.innerHTML = "";
  session.stages.forEach((stage, index) => {
    const item = document.createElement("li");
    item.textContent = STAGE_NAMES[stage] || stage;
    if (index + 1 < session.stage_number) item.className = "done";
    if (index + 1 === session.stage_number) {
      item.className = "current";
      item.setAttribute("aria-current", "step");
    }
    progress.append(item);
  });

  // Limits
  document.getElementById("messages-left").textContent = session.messages_left;
  startCountdown(session.seconds_left);

  // Chat transcript. textContent (not innerHTML) so typed text can't run as code.
  const transcript = document.getElementById("transcript");
  transcript.innerHTML = "";
  for (const message of session.transcript) {
    const bubble = document.createElement("div");
    bubble.className = "bubble " + message.role;
    bubble.textContent = message.text;
    transcript.append(bubble);
  }
  transcript.lastElementChild?.scrollIntoView({ block: "end" });

  // Plan box from the plan stage onwards
  const planStageNumber = session.stages.indexOf("plan") + 1;
  document.getElementById("plan-panel").hidden = session.stage_number < planStageNumber;
  const planText = document.getElementById("plan-text");
  if (session.plan_text && !planText.value) planText.value = session.plan_text;

  // Reach-out panel: only during the human_step stage
  document.getElementById("reach-out-panel").hidden = session.stage !== "human_step";
  document.getElementById("drafts-left").textContent =
    session.drafts_left + (session.drafts_left === 1 ? " draft left" : " drafts left");
  document.getElementById("make-draft").disabled = session.drafts_left <= 0;
  if (session.human_step_choice) {
    const radio = document.querySelector(`input[name=human-step][value=${session.human_step_choice}]`);
    if (radio) radio.checked = true;
  }

  // On the last stage, "Move on" finishes the session
  document.getElementById("move-on").textContent =
    session.stage === "close" ? "Finish session" : "Move on";
}

function startCountdown(seconds) {
  secondsLeft = seconds;
  clearInterval(timer);
  showTime();
  timer = setInterval(() => {
    secondsLeft -= 1;
    showTime();
    if (secondsLeft <= 0) {
      clearInterval(timer);
      refresh();  // the server will close the session and we'll go to /close
    }
  }, 1000);
}

function showTime() {
  const s = Math.max(0, secondsLeft);
  const minutes = Math.floor(s / 60);
  const seconds = String(s % 60).padStart(2, "0");
  document.getElementById("time-left").textContent = `${minutes}:${seconds}`;
}

// Show the fixed crisis message instead of the chat.
function showCrisis(html) {
  clearInterval(timer);
  document.getElementById("chat-area").hidden = true;
  document.getElementById("progress").hidden = true;
  document.querySelector(".limits").hidden = true;
  const box = document.getElementById("crisis");
  box.innerHTML = html;  // trusted: comes from content/crisis_message.html
  box.hidden = false;
}

// Run a server action, then redraw. Handles errors in one place.
async function act(path, body) {
  if (busy) return null;
  busy = true;
  showNotice(errorBox, "");
  try {
    const result = await api(path, body);
    if (!result.ok) {
      showNotice(errorBox, result.data.message || "Something went wrong.");
    }
    await refresh();
    return result;
  } finally {
    busy = false;
  }
}

document.getElementById("message-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("message");
  const text = input.value.trim();
  if (!text || busy) return;

  // Show a "checking" state while the safety check and reply run.
  busy = true;
  document.getElementById("send").disabled = true;
  showNotice(errorBox, "");
  try {
    const result = await api("/api/session/message", { text: text });
    if (result.ok && result.data.status === "crisis") {
      showCrisis(result.data.crisis_html);
      return;
    }
    if (result.ok) input.value = "";
    else showNotice(errorBox, result.data.message || "Something went wrong.");
    await refresh();
  } finally {
    busy = false;
    document.getElementById("send").disabled = false;
  }
});

document.getElementById("move-on").addEventListener("click", () => act("/api/session/next", {}));

document.getElementById("save-plan").addEventListener("click", async () => {
  const text = document.getElementById("plan-text").value;
  const result = await act("/api/session/plan", { plan_text: text });
  document.getElementById("plan-saved").hidden = !(result && result.ok);
});

// --- Reach-out step ---------------------------------------------------------
document.getElementById("make-draft").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  const button = document.getElementById("make-draft");
  button.disabled = true;
  button.textContent = "Drafting...";
  showNotice(errorBox, "");
  try {
    const result = await api("/api/session/draft", {
      recipient: document.getElementById("recipient").value,
      what_to_say: document.getElementById("what-to-say").value,
    });
    if (result.ok && result.data.status === "crisis") {
      showCrisis(result.data.crisis_html);
      return;
    }
    if (result.ok) {
      // The draft only lives here, on the page. Fren doesn't save it.
      document.getElementById("draft").value = result.data.draft;
      document.getElementById("draft-area").hidden = false;
      document.getElementById("copied").hidden = true;
    } else {
      showNotice(errorBox, result.data.message || "Something went wrong.");
    }
    await refresh();
  } finally {
    busy = false;
    button.textContent = "Help me draft it";
  }
});

document.getElementById("copy-draft").addEventListener("click", async () => {
  const draft = document.getElementById("draft");
  try {
    await navigator.clipboard.writeText(draft.value);
  } catch {
    draft.select();  // if copying isn't allowed, select the text so it's easy to copy by hand
    document.execCommand("copy");
  }
  document.getElementById("copied").hidden = false;
});

for (const radio of document.querySelectorAll("input[name=human-step]")) {
  radio.addEventListener("change", async () => {
    const result = await act("/api/session/human-step", { choice: radio.value });
    document.getElementById("choice-saved").hidden = !(result && result.ok);
  });
}

// Start: show dev warnings once, then draw the session.
api("/api/status").then((result) => {
  if (result.ok) showDevWarnings(result.data.dev_warnings);
});
refresh();
