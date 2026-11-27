// content.js - VidFetch 1.4.1
// YouTube watch page ONLY: ONE VidFetch icon beside the Like button. Click the
// icon and a menu opens with every option - Audio/Video, all qualities,
// audio format, Playlist / Thumbnail / Subtitles - then Download.
// No floating pill anywhere - not on Shorts, not on Facebook / TikTok /
// Instagram / X, not on channel pages. If there is no Like button on the
// page, there is no VidFetch icon either. The toolbar popup still works
// for pasting any link.
const VERSION = "1.4.4";
const TAG = "[VidFetch]";
const WRAP_ID = "ytg-wrap";
const MENU_ID = "ytg-menu";
const TOAST_ID = "ytg-toast";
const MARK_SVG =
  '<svg viewBox="0 0 128 128" width="20" height="20" aria-hidden="true" focusable="false">' +
  '<rect width="128" height="128" rx="28" fill="#2563eb"/>' +
  '<rect x="54" y="20" width="20" height="34" rx="4" fill="#fff"/>' +
  '<path d="M40 48 L88 48 L64 78 Z" fill="#fff"/>' +
  '<rect x="34" y="96" width="60" height="12" rx="6" fill="#fff"/>' +
  "</svg>";
// Full quality lists - every quality the helper understands.
const QUALITIES_VIDEO = [
  ["best", "Best available"], ["2160", "2160p 4K"], ["1440", "1440p"],
  ["1080", "1080p"], ["720", "720p"], ["480", "480p"],
  ["360", "360p"], ["240", "240p"], ["144", "144p"],
];
const QUALITIES_AUDIO = [
  ["320", "320 kbps (best)"], ["192", "192 kbps"],
  ["128", "128 kbps"], ["96", "96 kbps"],
];
const AUDIO_FORMATS = [["mp3", "MP3"], ["m4a", "M4A"], ["wav", "WAV"], ["flac", "FLAC"]];

let format = "mp4"; // default: video, since the menu is for picking a quality
let qualityVideo = "1080";
let qualityAudio = "320";
let audioFormat = "mp3";
let playlistMode = false;
let wantThumb = false;
let wantSubs = false;
let downloading = false;
let lastHref = "";

console.log(`${TAG} content script v${VERSION} loaded on ${location.pathname}`);
try {
  chrome.storage.local.get(
    { format: "mp4", qualityVideo: "1080", qualityAudio: "320", audioFormat: "mp3", playlist: false, thumbnail: false, subtitles: false },
    (v) => {
      if (["mp3", "mp4", "thumb"].includes(v?.format)) format = v.format;
      if (v?.qualityVideo) qualityVideo = v.qualityVideo;
      if (v?.qualityAudio) qualityAudio = v.qualityAudio;
      if (v?.audioFormat) audioFormat = v.audioFormat;
      playlistMode = !!v?.playlist; wantThumb = false; wantSubs = !!v?.subtitles;
      syncMenu();
    }
  );
} catch (e) { console.warn(TAG, "storage unavailable:", e?.message); }

function savePrefs() {
  try {
    chrome.storage.local.set({
      format, qualityVideo, qualityAudio, audioFormat,
      playlist: playlistMode, thumbnail: false, subtitles: wantSubs,
    });
  } catch (e) { console.warn(TAG, "could not save prefs:", e?.message); }
}

function isYouTube() { return /(^|\.)youtube\.com$/.test(location.hostname) || location.hostname === "youtu.be"; }
function isShorts() { return location.pathname.startsWith("/shorts/"); }
function isSocialVideoPage() {
  const h = location.hostname, p = location.pathname;
  if (h.includes("facebook.com") || h === "fb.watch")
    return /\/(videos?|watch|reel)\//.test(p) || /\/videos?\//.test(p);
  if (h.includes("instagram.com")) return /^\/(p|reel|reels|tv)\//.test(p);
  if (h.includes("tiktok.com")) return /\/video\//.test(p);
  if (h.includes("x.com") || h.includes("twitter.com")) return /\/status\//.test(p);
  return false;
}
function isChannelPage() {
  return isYouTube() && /^\/(@[^/]+|channel\/[^/]+|c\/[^/]+|user\/[^/]+)/.test(location.pathname);
}
function currentUrl() {
  try {
    if (isYouTube()) {
      const u = new URL(location.href);
      const v = u.searchParams.get("v");
      const list = u.searchParams.get("list");
      if (v) {
        if (playlistMode && list) return "https://www.youtube.com/watch?v=" + v + "&list=" + list;
        return "https://www.youtube.com/watch?v=" + v;
      }
      const s = location.pathname.match(/^\/shorts\/([\w-]{6,})/);
      if (s) return "https://www.youtube.com/shorts/" + s[1];
      if (list) return "https://www.youtube.com/playlist?list=" + list;
      if (isChannelPage()) return location.href.split("?")[0];
    }
    if (!isYouTube()) return location.href;
  } catch (e) { console.warn(TAG, "url parse failed", e); }
  return null;
}
async function send(message) {
  try {
    const res = await chrome.runtime.sendMessage(message);
    if (res === undefined) return { ok: false, error: "no reply from background - reload the extension" };
    return res;
  } catch (e) {
    const m = String(e?.message || e);
    console.warn(TAG, "sendMessage failed:", m);
    if (/context invalidated|Receiving end does not exist/i.test(m))
      return { ok: false, error: "extension was reloaded - refresh this page (F5)" };
    return { ok: false, error: m };
  }
}
function humanSize(n) {
  if (!n || n < 1024) return "";
  const units = ["KB", "MB", "GB"]; let v = n; let i = -1;
  do { v /= 1024; i++; } while (v >= 1024 && i < units.length - 1);
  return v.toFixed(v >= 10 ? 0 : 1) + " " + units[i];
}
function toast(message, kind = "info") {
  document.getElementById(TOAST_ID)?.remove();
  const el = document.createElement("div");
  el.id = TOAST_ID; el.className = "ytg-toast ytg-toast--" + kind;
  const mark = document.createElement("span");
  mark.className = "ytg-toast__mark"; mark.innerHTML = MARK_SVG;
  const text = document.createElement("span");
  text.className = "ytg-toast__text"; text.textContent = message;
  el.appendChild(mark); el.appendChild(text);
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("ytg-toast--in"));
  setTimeout(() => { el.classList.remove("ytg-toast--in"); setTimeout(() => el.remove(), 300); }, kind === "error" ? 7000 : 4000);
}

// ------------------------------------------------------------- menu ---

function currentQuality() { return format === "mp4" ? qualityVideo : qualityAudio; }
function formatLabel() {
  if (format === "thumb") return "Thumbnail";
  if (format === "mp3") return audioFormat.toUpperCase();
  return "MP4 " + qualityLabel();
}
function qualityLabel() {
  const list = format === "mp4" ? QUALITIES_VIDEO : QUALITIES_AUDIO;
  const hit = list.find((q) => q[0] === currentQuality());
  return hit ? hit[1] : currentQuality();
}
function setMenuStatus(text, kind) {
  const s = document.getElementById("ytg-menu-status");
  if (!s) return;
  s.textContent = text || "";
  s.className = "ytg-menu-status" + (kind ? " ytg-menu-status--" + kind : "");
}
function fillQualitySelect() {
  const sel = document.getElementById("ytg-menu-quality");
  if (!sel) return;
  const list = format === "mp4" ? QUALITIES_VIDEO : QUALITIES_AUDIO;
  sel.textContent = "";
  for (const [value, label] of list) {
    const opt = document.createElement("option");
    opt.value = value; opt.textContent = label; sel.appendChild(opt);
  }
  sel.value = currentQuality();
  // WAV / FLAC are lossless - there is no bitrate to pick.
  sel.disabled = format === "mp3" && (audioFormat === "wav" || audioFormat === "flac");
}
function syncMenu() {
  const menu = document.getElementById(MENU_ID);
  if (!menu) return;
  for (const b of menu.querySelectorAll(".ytg-menu-seg button")) {
    b.classList.toggle("on", b.dataset.fmt === format);
  }
  const afRow = document.getElementById("ytg-menu-audiofmt-row");
  if (afRow) afRow.style.display = format === "mp3" ? "" : "none";
  const qRow = document.getElementById("ytg-menu-quality-row");
  if (qRow) qRow.style.display = format === "thumb" ? "none" : "";
  const afSel = document.getElementById("ytg-menu-audiofmt");
  if (afSel) afSel.value = audioFormat;
  const pl = document.getElementById("ytg-menu-playlist");
  if (pl) pl.checked = playlistMode;
  const th = document.getElementById("ytg-menu-thumbnail");
  if (th) th.checked = wantThumb;
  const sb = document.getElementById("ytg-menu-subtitles");
  if (sb) sb.checked = wantSubs;
  fillQualitySelect();
}
function closeMenu() {
  const menu = document.getElementById(MENU_ID);
  if (menu) menu.classList.remove("open");
  const btn = document.querySelector(".ytg-icon-btn");
  if (btn) btn.classList.remove("open");
}
function placeMenu() {
  const menu = document.getElementById(MENU_ID);
  const btn = document.querySelector(".ytg-icon-btn");
  if (!menu || !btn) return;
  const r = btn.getBoundingClientRect();
  const w = 280;
  let left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  menu.style.left = left + "px";
  menu.style.top = (r.bottom + 8) + "px";
}
function toggleMenu() {
  const menu = ensureMenu();
  const willOpen = !menu.classList.contains("open");
  if (willOpen) { syncMenu(); setMenuStatus(""); placeMenu(); }
  menu.classList.toggle("open", willOpen);
  const btn = document.querySelector(".ytg-icon-btn");
  if (btn) btn.classList.toggle("open", willOpen);
}
function ensureMenu() {
  let menu = document.getElementById(MENU_ID);
  if (!menu) { menu = buildMenu(); document.body.appendChild(menu); syncMenu(); }
  return menu;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function buildMenu() {
  const menu = el("div", "ytg-menu");
  menu.id = MENU_ID;

  const head = el("div", "ytg-menu-head");
  const mark = el("span", "ytg-menu-mark"); mark.innerHTML = MARK_SVG;
  head.appendChild(mark);
  head.appendChild(el("strong", "", "VidFetch"));
  const close = el("button", "ytg-menu-close", "\u2715");
  close.type = "button"; close.title = "Close";
  close.addEventListener("click", (ev) => { ev.stopPropagation(); closeMenu(); });
  head.appendChild(close);
  menu.appendChild(head);

  // Format: Audio / Video
  const seg = el("div", "ytg-menu-seg");
  for (const [fmt, label] of [["mp3", "Audio"], ["mp4", "Video"], ["thumb", "Thumbnail"]]) {
    const b = el("button", "", label);
    b.type = "button"; b.dataset.fmt = fmt;
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      format = fmt; savePrefs(); syncMenu();
    });
    seg.appendChild(b);
  }
  menu.appendChild(seg);

  // Quality - full list, changes with Audio/Video
  const qRow = el("label", "ytg-menu-row");
  qRow.id = "ytg-menu-quality-row";
  qRow.appendChild(el("span", "ytg-menu-label", "Quality"));
  const qSel = el("select", "ytg-menu-select");
  qSel.id = "ytg-menu-quality";
  qSel.addEventListener("change", (ev) => {
    ev.stopPropagation();
    if (format === "mp4") qualityVideo = qSel.value; else qualityAudio = qSel.value;
    savePrefs();
  });
  qSel.addEventListener("click", (ev) => ev.stopPropagation());
  qRow.appendChild(qSel);
  menu.appendChild(qRow);

  // Audio format - only for Audio
  const aRow = el("label", "ytg-menu-row");
  aRow.id = "ytg-menu-audiofmt-row";
  aRow.appendChild(el("span", "ytg-menu-label", "Audio format"));
  const aSel = el("select", "ytg-menu-select");
  aSel.id = "ytg-menu-audiofmt";
  for (const [value, label] of AUDIO_FORMATS) {
    const opt = document.createElement("option");
    opt.value = value; opt.textContent = label; aSel.appendChild(opt);
  }
  aSel.addEventListener("change", (ev) => {
    ev.stopPropagation(); audioFormat = aSel.value; savePrefs(); syncMenu();
  });
  aSel.addEventListener("click", (ev) => ev.stopPropagation());
  aRow.appendChild(aSel);
  menu.appendChild(aRow);

  // Checkboxes
  const opts = el("div", "ytg-menu-opts");
  const checks = [
    ["ytg-menu-playlist", "Full playlist / channel", "Every video in the playlist, into its own folder"],
    ["ytg-menu-subtitles", "Also save subtitles", "English + Bangla .srt when available"],
  ];
  for (const [id, label, hint] of checks) {
    const lab = el("label", "ytg-menu-check");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.id = id;
    cb.addEventListener("change", () => {
      if (id === "ytg-menu-playlist") playlistMode = cb.checked;
      if (id === "ytg-menu-thumbnail") wantThumb = cb.checked;
      if (id === "ytg-menu-subtitles") wantSubs = cb.checked;
      savePrefs();
    });
    lab.appendChild(cb);
    const txt = el("span", "");
    txt.appendChild(el("span", "ytg-menu-check-label", label));
    txt.appendChild(el("small", "", hint));
    lab.appendChild(txt);
    opts.appendChild(lab);
  }
  menu.appendChild(opts);

  // Download button + status
  const go = el("button", "ytg-menu-go", "Download");
  go.type = "button"; go.id = "ytg-menu-download";
  go.addEventListener("click", onDownload);
  menu.appendChild(go);
  const status = el("div", "ytg-menu-status");
  status.id = "ytg-menu-status";
  menu.appendChild(status);

  return menu;
}

async function onDownload(ev) {
  ev.preventDefault(); ev.stopPropagation();
  if (downloading) return;
  const url = currentUrl();
  if (!url) { setMenuStatus("Not on a video page", "err"); return; }
  const go = document.getElementById("ytg-menu-download");
  downloading = true;
  if (go) { go.disabled = true; go.textContent = "Working…"; }
  setMenuStatus("Sending to the helper…");
  const what = formatLabel();
  console.log(`${TAG} download ${what} playlist=${playlistMode} -> ${url}`);
  const res = await send({
    type: "ytg:grab", url, format,
    quality: format === "mp4" ? qualityVideo : qualityAudio,
    audio_format: audioFormat, playlist: playlistMode,
    thumbnail: false, subtitles: wantSubs,
  });
  if (!res || !res.ok) {
    downloading = false;
    if (go) { go.disabled = false; go.textContent = "Download"; }
    setMenuStatus(res?.error || "Could not reach the helper", "err");
    toast(res?.error || "Could not reach the helper", "error");
  } else {
    setMenuStatus("Queued — " + what + (playlistMode ? " (playlist)" : ""));
    toast("Queued — " + what, "info");
    // downloading stays true until the done/error message arrives
  }
}

// -------------------------------------------------------- icon button ---

function buildWrap() {
  const wrap = el("div", "ytg-wrap");
  wrap.id = WRAP_ID;
  const btn = el("button", "ytg-icon-btn");
  btn.type = "button";
  btn.title = "VidFetch — download this video";
  btn.setAttribute("aria-label", "VidFetch — download this video");
  btn.innerHTML = MARK_SVG;
  btn.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); toggleMenu(); });
  wrap.appendChild(btn);
  return wrap;
}

// YouTube ships several layouts of the action row (old renderer tags and the
// newer *-view-model tags with round grey buttons + the "Ask" sparkle button).
// Find the Like/Dislike pill in whichever one is on screen.
function findLikeSegment() {
  const root = document.querySelector("ytd-watch-metadata") || document;
  const direct = root.querySelector(
    "segmented-like-dislike-button-view-model, ytd-segmented-like-dislike-button-renderer"
  );
  if (direct) return direct;
  // Fallback: find the Like button itself, then climb to the pill that holds
  // both Like and Dislike (the first ancestor with 2+ buttons in it).
  const like = root.querySelector(
    'like-button-view-model, button[aria-label*="like this video" i], button[title="I like this"], button[aria-label^="like" i]'
  );
  if (!like) return null;
  let node = like;
  for (let i = 0; i < 6 && node.parentElement; i++) {
    if (node.parentElement.querySelectorAll("button").length >= 2) return node.parentElement;
    node = node.parentElement;
  }
  return like;
}

function inject() {
  // ONLY YouTube watch pages, ONLY beside the Like button. Nothing floats.
  if (!isYouTube()) return;
  if (isShorts() || isChannelPage()) return;
  let v = null;
  try { v = new URL(location.href).searchParams.get("v"); } catch (e) {}
  if (!v) return; // not a video page (home, search, playlist page, ...)

  const likeSeg = findLikeSegment();
  if (!likeSeg || !likeSeg.parentElement) return;

  const existing = document.getElementById(WRAP_ID);
  if (existing && existing.isConnected && existing.previousElementSibling === likeSeg) return;
  existing?.remove();

  const wrap = buildWrap();
  const host = likeSeg.parentElement;
  // Newer layouts space buttons with flex `gap`; older ones need a margin.
  const cs = getComputedStyle(host);
  const hasGap = cs.display.includes("flex") && cs.columnGap && cs.columnGap !== "normal" && cs.columnGap !== "0px";
  wrap.style.marginLeft = hasGap ? "0" : "8px";
  host.insertBefore(wrap, likeSeg.nextSibling);
  console.log(TAG, "icon mounted beside Like");
  syncMenu();
}

function tick() {
  if (location.href !== lastHref) {
    lastHref = location.href;
    document.getElementById(WRAP_ID)?.remove();
    document.getElementById(TOAST_ID)?.remove();
    closeMenu();
  }
  inject();
}

// Close the menu on a click anywhere else, or on Escape.
document.addEventListener("click", (ev) => {
  const wrap = document.getElementById(WRAP_ID);
  const menu = document.getElementById(MENU_ID);
  if (wrap && !wrap.contains(ev.target) && !(menu && menu.contains(ev.target))) closeMenu();
}, true);
window.addEventListener("resize", () => { if (document.getElementById(MENU_ID)?.classList.contains("open")) placeMenu(); });
window.addEventListener("scroll", () => { if (document.getElementById(MENU_ID)?.classList.contains("open")) placeMenu(); }, { passive: true });
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeMenu();
});

chrome.runtime.onMessage.addListener((msg) => {
  const go = document.getElementById("ytg-menu-download");
  if (msg?.type === "ytg:progress") {
    if (typeof msg.percent === "number" && msg.percent > 0) {
      if (go) go.textContent = Math.floor(msg.percent) + "%";
      setMenuStatus(Math.floor(msg.percent) + "%" +
        (msg.speed ? "  ·  " + msg.speed : "") +
        (msg.eta ? "  ·  ETA " + msg.eta : ""));
    } else if (msg.stage === "merging") setMenuStatus("Merging video and audio…");
    else if (msg.stage === "converting") setMenuStatus("Converting…");
    else if (msg.stage === "tagging") setMenuStatus("Writing metadata…");
    else setMenuStatus("Downloading…");
  } else if (msg?.type === "ytg:done") {
    downloading = false;
    if (go) { go.disabled = false; go.textContent = "Download"; }
    setMenuStatus("Saved: " + (msg.name || "file") + (msg.bytes ? "  ·  " + humanSize(msg.bytes) : ""), "ok");
    toast("Saved: " + msg.name + (msg.bytes ? "  ·  " + humanSize(msg.bytes) : ""), "ok");
    setTimeout(closeMenu, 2500);
  } else if (msg?.type === "ytg:error") {
    downloading = false;
    if (go) { go.disabled = false; go.textContent = "Download"; }
    setMenuStatus("Failed: " + msg.error, "err");
    toast("Failed: " + msg.error, "error");
  }
});

tick();
setInterval(tick, 1000);
document.addEventListener("yt-navigate-finish", () => setTimeout(tick, 120));
