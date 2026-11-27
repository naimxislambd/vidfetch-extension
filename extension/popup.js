// popup.js - VidFetch 1.4.0
// Audio formats: MP3 / M4A / WAV / FLAC. Playlist, thumbnail and subtitle
// options are sent to the helper with every job and remembered.
const QUALITIES_VIDEO = [
  ["best", "Best available"], ["2160", "2160p 4K"], ["1440", "1440p"],
  ["1080", "1080p"], ["720", "720p"], ["480", "480p"],
  ["360", "360p (small)"], ["240", "240p (smaller)"], ["144", "144p (smallest)"],
];
const QUALITIES_AUDIO = [
  ["320", "320 kbps (best)"], ["192", "192 kbps"],
  ["128", "128 kbps (small)"], ["96", "96 kbps (smallest)"],
];
const VIDEO_HINT = new RegExp([
  "youtube\\.com/(watch|shorts|live|playlist|channel|@)",
  "youtu\\.be/",
  "instagram\\.com/(p|reel|reels|tv)/",
  "facebook\\.com/.+/videos?/", "facebook\\.com/(watch|reel)/",
  "fb\\.watch/",
  "tiktok\\.com/.+/video/", "tiktok\\.com/@",
  "vimeo\\.com/\\d",
  "(twitter|x)\\.com/.+/status/",
  "soundcloud\\.com/", "dailymotion\\.com/video/", "twitch\\.tv/videos/",
].join("|"), "i");

const $ = (id) => document.getElementById(id);
let format = "mp3";
let quality = "320";
let qualityVideo = "1080";
let qualityAudio = "320";
let audioFormat = "mp3";
let pollTimer = null;

function savePrefs() {
  try {
    chrome.storage.local.set({
      format, qualityVideo, qualityAudio, audioFormat,
      playlist: $("playlist").checked,
      thumbnail: $("thumbnail").checked,
      subtitles: $("subtitles").checked,
    });
  } catch (e) { console.warn("[VidFetch] could not save prefs:", e?.message); }
}

function fillQualities() {
  if (format === "thumb") { $("quality").disabled = true; return; }
  const list = format === "mp4" ? QUALITIES_VIDEO : QUALITIES_AUDIO;
  const sel = $("quality");
  sel.textContent = "";
  for (const [value, label] of list) {
    const opt = document.createElement("option");
    opt.value = value; opt.textContent = label; sel.appendChild(opt);
  }
  if (!list.some(([v]) => v === quality)) {
    quality = list[0][0];
    if (format === "mp4") qualityVideo = quality; else qualityAudio = quality;
  }
  sel.value = quality;
  // WAV / FLAC are lossless - there is no bitrate to pick.
  sel.disabled = format === "mp3" && (audioFormat === "wav" || audioFormat === "flac");
}

function syncFormatUI() {
  for (const b of document.querySelectorAll("#seg button")) {
    b.classList.toggle("on", b.dataset.fmt === format);
  }
  $("audiofmt").style.display = format === "mp3" ? "" : "none";
  $("audiofmt").value = audioFormat;
  $("quality").style.display = format === "thumb" ? "none" : "";
  $("quality").disabled = format === "thumb";
}

function showStatus(kind, text, indeterminate) {
  const box = $("status"); const bar = $("bar"); const fill = $("fill");
  box.hidden = false;
  $("msg").className = kind === "ok" ? "ok" : kind === "err" ? "err" : "";
  $("msg").textContent = text; $("msg").title = "";
  bar.classList.toggle("indeterminate", !!indeterminate);
  fill.style.width = indeterminate ? "" : "0%";
}

function showProgress(job) {
  const bar = $("bar"); const fill = $("fill");
  $("status").hidden = false; $("msg").className = "";
  if (typeof job.percent === "number" && job.percent > 0) {
    bar.classList.remove("indeterminate");
    fill.style.width = Math.min(100, job.percent) + "%";
    const bits = [Math.floor(job.percent) + "%"];
    if (job.speed) bits.push(job.speed);
    if (job.size) bits.push(job.size);
    if (job.eta) bits.push("ETA " + job.eta);
    if (String(job.stage || "").toLowerCase() === "retrying") bits.push("retrying");
    $("msg").textContent = bits.join("  ·  ");
    return;
  }
  bar.classList.add("indeterminate");
  if (typeof job.ahead === "number" && job.ahead > 0) {
    $("msg").textContent = "Queued — " + job.ahead + (job.ahead === 1 ? " job" : " jobs") + " ahead";
    return;
  }
  const stage = String(job.stage || "").toLowerCase();
  const label = stage === "retrying" ? "Connection dropped — retrying…"
    : stage === "merging" ? "Merging video and audio…"
    : stage === "converting" ? (format === "thumb" ? "Saving thumbnail…" : "Converting to " + audioFormat.toUpperCase() + "…")
    : stage === "tagging" ? "Writing metadata…"
    : stage === "downloading" ? "Downloading…"
    : "Reading the link…";
  const secs = typeof job.elapsed === "number" ? Math.floor(job.elapsed) : 0;
  $("msg").textContent = secs > 0 ? label + "  " + secs + "s" : label;
}

function humanSize(n) {
  if (!n || n < 1024) return "";
  const units = ["KB", "MB", "GB"]; let v = n; let i = -1;
  do { v /= 1024; i++; } while (v >= 1024 && i < units.length - 1);
  return v.toFixed(v >= 10 ? 0 : 1) + " " + units[i];
}

function setBusy(busy) {
  $("go").disabled = busy;
  $("go").textContent = busy ? "Working…" : "Grab";
}

function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

function poll(id) {
  stopPolling();
  let ticks = 0, misses = 0;
  pollTimer = setInterval(async () => {
    if (++ticks > 1800) {
      stopPolling(); setBusy(false);
      showStatus("err", "Timed out after 30 minutes."); return;
    }
    let job;
    try { job = await chrome.runtime.sendMessage({ type: "ytg:job", id }); } catch { return; }
    if (!job || !job.status) {
      if (++misses < 4) return;
      stopPolling(); setBusy(false);
      const why = String(job?.error || "");
      showStatus("err", /no such job/i.test(why) ? "The helper was restarted — the job is gone. Try again."
        : why ? "Helper not responding — is the black window still open?"
        : "Lost contact with the helper. Try again.");
      return;
    }
    misses = 0;
    if (job.status === "pending" || job.status === "running") { showProgress(job); return; }
    if (job.status === "done") {
      stopPolling(); setBusy(false);
      showStatus("ok", "Saved — " + (job.name || "file") + (job.bytes ? "  ·  " + humanSize(job.bytes) : ""));
      $("bar").classList.remove("indeterminate"); $("fill").style.width = "100%";
      loadHistory(); return;
    }
    if (job.status === "error") {
      stopPolling(); setBusy(false);
      showStatus("err", job.error || "Download failed.");
      $("msg").title = job.error_raw || "";
    }
  }, 1000);
}

async function onGrab() {
  const url = $("url").value.trim();
  if (!/^https?:\/\//i.test(url)) {
    showStatus("err", "Paste a full link — it should start with http:// or https://");
    return;
  }
  stopPolling(); setBusy(true);
  showStatus("info", format === "thumb" ? "Getting the thumbnail…" : "Sending to the helper…", true);
  let res;
  try {
    res = await chrome.runtime.sendMessage({
      type: "ytg:grab", url, format, quality,
      audio_format: audioFormat,
      playlist: $("playlist").checked,
      thumbnail: $("thumbnail").checked,
      subtitles: $("subtitles").checked,
    });
  } catch (e) { res = { ok: false, error: String(e?.message || e) }; }
  if (!res || !res.ok) {
    setBusy(false);
    showStatus("err", res?.error || "Could not reach the helper. Is it running?");
    return;
  }
  poll(res.id);
}

// ---- history ----
async function loadHistory() {
  let data = null;
  try { data = await chrome.runtime.sendMessage({ type: "ytg:history" }); } catch { /* helper down */ }
  const ul = $("history");
  ul.textContent = "";
  const items = (data && data.history) || [];
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "hempty"; li.textContent = "No downloads yet.";
    ul.appendChild(li); return;
  }
  for (const h of items.slice(0, 8)) {
    const li = document.createElement("li");
    const name = document.createElement("div");
    name.textContent = h.name || "file";
    const meta = document.createElement("div");
    meta.className = "hmeta";
    meta.textContent = [h.time || "", h.bytes ? humanSize(h.bytes) : ""].filter(Boolean).join("  ·  ");
    li.appendChild(name); li.appendChild(meta); ul.appendChild(li);
  }
}

async function init() {
  let prefs = { format: "mp3", qualityVideo: "1080", qualityAudio: "320", audioFormat: "mp3", playlist: false, thumbnail: false, subtitles: false };
  try { prefs = await chrome.storage.local.get(prefs); } catch (e) { console.warn("[VidFetch] storage unavailable:", e?.message); }
  format = ["mp3", "mp4", "thumb"].includes(prefs.format) ? prefs.format : "mp3";
  qualityVideo = prefs.qualityVideo || "1080";
  qualityAudio = prefs.qualityAudio || "320";
  audioFormat = ["mp3", "m4a", "wav", "flac"].includes(prefs.audioFormat) ? prefs.audioFormat : "mp3";
  quality = format === "mp4" ? qualityVideo : qualityAudio;
  $("playlist").checked = !!prefs.playlist;
  $("thumbnail").checked = false; // thumbnail only via the Thumbnail button
  $("subtitles").checked = !!prefs.subtitles;

  $("quality").addEventListener("change", () => {
    quality = $("quality").value;
    if (format === "mp4") qualityVideo = quality; else qualityAudio = quality;
    savePrefs();
  });
  $("audiofmt").addEventListener("change", () => { audioFormat = $("audiofmt").value; fillQualities(); savePrefs(); });
  for (const id of ["playlist", "thumbnail", "subtitles"]) {
    $(id).addEventListener("change", savePrefs);
  }
  fillQualities(); syncFormatUI();
  for (const b of document.querySelectorAll("#seg button")) {
    b.addEventListener("click", () => {
      format = b.dataset.fmt;
      quality = format === "mp4" ? qualityVideo : qualityAudio;
      fillQualities(); syncFormatUI(); savePrefs();
    });
  }
  $("go").addEventListener("click", onGrab);
  $("url").addEventListener("keydown", (e) => { if (e.key === "Enter") onGrab(); });
  $("openfolder").addEventListener("click", async () => {
    try {
      const r = await chrome.runtime.sendMessage({ type: "ytg:open-folder" });
      if (!r || r.ok === false) showStatus("err", "Could not open the folder: " + (r?.error || "helper not running"));
    } catch (e) { showStatus("err", "Could not open the folder."); }
  });
  $("clearhist").addEventListener("click", async () => {
    try { await chrome.runtime.sendMessage({ type: "ytg:clear-history" }); } catch { /* ignore */ }
    loadHistory();
  });

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url && VIDEO_HINT.test(tab.url)) { $("url").value = tab.url; $("go").focus(); }
  } catch { /* no activeTab grant */ }

  loadHistory();
  try {
    const live = await chrome.runtime.sendMessage({ type: "ytg:active" });
    if (live?.id && live.status) { setBusy(true); showProgress(live); poll(live.id); return; }
  } catch { /* helper down */ }
  $("url").focus();
}
document.addEventListener("DOMContentLoaded", init);
