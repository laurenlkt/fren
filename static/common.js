// Fren: small helpers shared by every page.

// Send a request to the Fren server and return { ok, status, data }.
// Leave out `body` for a GET request; pass an object (even {}) for a POST.
// If the server says we have no user yet, go to onboarding.
async function api(path, body) {
  const options = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };

  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));

  if (response.status === 401) {
    window.location.href = "/onboarding";
  }
  return { ok: response.ok, status: response.status, data: data };
}

// Show developer warnings (e.g. "AI classifier is OFF") in a red banner.
function showDevWarnings(warnings) {
  if (!warnings || warnings.length === 0) return;
  const banner = document.createElement("div");
  banner.className = "dev-banner";
  banner.textContent = "DEVELOPER SETTINGS ON: " + warnings.join(" ");
  document.body.prepend(banner);
}

// Turn "2026-10-14T09:00:00+00:00" into a friendly local date and time.
function formatDateTime(isoText) {
  return new Date(isoText).toLocaleString(undefined, {
    weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });
}

// Show a short message in an element (used for errors).
function showNotice(element, text) {
  element.textContent = text;
  element.hidden = !text;
}

// Describe a number of hours in words, e.g. 48 -> "2 days".
function describeHours(hours) {
  if (hours === 168) return "1 week";
  if (hours % 24 === 0) return hours / 24 + (hours === 24 ? " day" : " days");
  return hours + " hours";
}

// Fill in and show the "longer gap" suggestion card, if there is one.
// The card needs elements with ids: taper-card, taper-current, taper-suggested,
// taper-yes, taper-no, taper-done.
function setUpTaperCard(suggestion) {
  if (!suggestion) return;
  document.getElementById("taper-current").textContent = describeHours(suggestion.current_hours);
  document.getElementById("taper-suggested").textContent = describeHours(suggestion.suggested_hours);
  document.getElementById("taper-card").hidden = false;

  async function answer(accept) {
    const result = await api("/api/taper", { accept: accept });
    if (!result.ok) return;
    document.getElementById("taper-yes").disabled = true;
    document.getElementById("taper-no").disabled = true;
    const done = document.getElementById("taper-done");
    done.textContent = accept
      ? "Done. Your gap between sessions is now " + describeHours(suggestion.suggested_hours) + "."
      : "No problem. Your gap stays at " + describeHours(suggestion.current_hours) + ".";
    done.hidden = false;
    if (typeof onTaperAnswered === "function") onTaperAnswered();
  }
  document.getElementById("taper-yes").addEventListener("click", () => answer(true));
  document.getElementById("taper-no").addEventListener("click", () => answer(false));
}
