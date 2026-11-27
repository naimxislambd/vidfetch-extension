// background.js - service worker. Owns all network calls to the local helper,
// because content-script fetch is subject to the page CSP.

const HELPER = "http://127.0.0.1:8766";
const POLL_MS = 1200;
const MAX_POLLS = 1500; // ~30 min ceiling
const TAG = "[VidFetch]";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function safeBadge(text, color) {
  // chrome.action is undefined unless manifest declares "action"
  try {
    chrome.action.setBadgeText({ text });
    if (color) chrome.action.setBadgeBackgroundColor({ color });
  } catch (e) {
    console.warn(TAG, "badge unavailable:", e.message);
  }
}

function tell(tabId, message) {
  if (tabId == null) return;
  chrome.tabs.sendMessage(tabId, message).catch((e) =>
    console.warn(TAG, "could not message tab:", e.message)
  );
}

async function api(path, options) {
  const res = await fetch(HELPER + path, options);
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

// Self-heal: if the helper is not running, ask the native host (installed once
// by setup) to start it, then wait until it answers.
function startViaNative() {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage("com.vidfetch.helper", { cmd: "start" }, (resp) => {
        if (chrome.runtime.lastError) {
          console.warn(TAG, "native host:", chrome.runtime.lastError.message);
          resolve(false);
        } else {
          resolve(!!resp?.ok);
        }
      });
    } catch (e) {
      console.warn(TAG, "native host unavailable:", e.message);
      resolve(false);
    }
  });
}

async function ensureHelper() {
  try { await api("/health"); return true; } catch {}
  if (!(await startViaNative())) return false;
  for (let i = 0; i < 20; i++) {
    try { await api("/health"); return true; } catch {}
    await sleep(500);
  }
  return false;
}

async function grab({ url, format, quality, tabId, playlist, audio_format, thumbnail, subtitles }) {
  let job;
  const post = () => api("/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, format, quality, playlist: !!playlist, audio_format: audio_format || "mp3", thumbnail: !!thumbnail, subtitles: !!subtitles })
  });
  try {
    try {
      job = await post();
    } catch (first) {
      if (!/Failed to fetch|NetworkError|refused|load failed/i.test(String(first?.message || first))) throw first;
      if (!(await ensureHelper())) throw first;
      job = await post();
    }
  } catch (err) {
    const msg = String(err?.message || err);
    console.warn(TAG, "POST failed:", msg);
    const hint = /Failed to fetch|NetworkError|refused|load failed/i.test(msg)
      ? "helper could not be started - run setup.bat once"
      : msg;
    return { ok: false, error: hint };
  }

  console.log(TAG, "job queued", job.id, format, quality, url);
  watch(job.id, tabId);
  return { ok: true, id: job.id };
}

async function watch(id, tabId) {
  safeBadge("...", "#555");
  for (let i = 0; i < MAX_POLLS; i++) {
    await sleep(POLL_MS);
    let job;
    try {
      job = await api("/jobs/" + id);
    } catch (e) {
      safeBadge("?", "#b00");
      tell(tabId, { type: "ytg:error", error: "lost contact with helper" });
      return;
    }

    if (job.status === "running") {
      if (job.stage || job.percent) {
        safeBadge(job.percent ? Math.floor(job.percent) + "%" : "...", "#555");
        tell(tabId, {
          type: "ytg:progress",
          percent: job.percent,
          speed: job.speed,
          eta: job.eta,
          stage: job.stage
        });
      }
      continue;
    }

    if (job.status === "done") {
      safeBadge("OK", "#1a7f37");
      tell(tabId, {
        type: "ytg:done",
        name: job.name || "saved",
        bytes: job.bytes || 0,
      });
      setTimeout(() => safeBadge("", null), 6000);
      return;
    }
    if (job.status === "error") {
      safeBadge("!", "#c00");
      tell(tabId, { type: "ytg:error", error: job.error || "download failed" });
      setTimeout(() => safeBadge("", null), 9000);
      return;
    }
  }
  safeBadge("!", "#c00");
  tell(tabId, { type: "ytg:error", error: "timed out" });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "ytg:grab") {
    grab({
      url: msg.url,
      format: ["mp3", "mp4", "thumb"].includes(msg.format) ? msg.format : "mp3",
      quality: msg.quality || "1080",
      tabId: sender.tab?.id,
      playlist: msg.playlist, audio_format: msg.audio_format,
      thumbnail: msg.thumbnail, subtitles: msg.subtitles
    }).then(sendResponse);
    return true; // async response
  }

  if (msg?.type === "ytg:ping") {
    ensureHelper().then(() => api("/health"))
      .then((h) => sendResponse({ ok: true, version: h.version, inbox: h.inbox }))
      .catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));
    return true;
  }

  // The popup polls through the worker rather than fetching directly, so the
  // helper keeps a single origin allowlist and the popup needs no host access.
  if (msg?.type === "ytg:job") {
    api("/jobs/" + encodeURIComponent(msg.id))
      .then(sendResponse)
      .catch((e) => sendResponse({ error: String(e?.message || e) }));
    return true;
  }

  if (msg?.type === "ytg:active") {
    // The popup is destroyed on close but the download keeps going, so it asks
    // what is still running and reattaches to it.
    api("/jobs")
      .then((d) => {
        const live = (d.jobs || []).find(
          (j) => j.status === "pending" || j.status === "running"
        );
        sendResponse(live || null);
      })
      .catch((e) => sendResponse({ error: String(e?.message || e) }));
    return true;
  }

  if (msg?.type === "ytg:history") {
    api("/history").then(sendResponse).catch((e) => sendResponse({ error: String(e?.message || e) }));
    return true;
  }
  if (msg?.type === "ytg:open-folder") {
    api("/open-folder", { method: "POST" }).then(sendResponse).catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));
    return true;
  }
  if (msg?.type === "ytg:clear-history") {
    api("/history/clear", { method: "POST" }).then(sendResponse).catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));
    return true;
  }

  return false;
});

// Bring the helper up whenever the browser starts or the extension is (re)loaded.
chrome.runtime.onStartup.addListener(() => { ensureHelper(); });
chrome.runtime.onInstalled.addListener(() => { ensureHelper(); });

console.log(TAG, "service worker up");
