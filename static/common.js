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
