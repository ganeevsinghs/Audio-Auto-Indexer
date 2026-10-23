const state = {
  audio: null,
  albumName: "",
  albumArt: false,
  albumArtVersion: 0,
  artLater: false,
  albumThumbDefault: false,
  keertanis: [],
  sharedProgram: "",
  authenticated: false,
  hasKeys: false,
  user: null,
  redirectUri: "http://localhost:8000/api/auth/callback",
  pendingPublish: false,
  timestampsText: "",
};

const els = {
  audioStep: document.getElementById("audio-step"),
  audioDrop: document.getElementById("audio-drop"),
  audioInput: document.getElementById("audio-input"),
  audioChip: document.getElementById("audio-chip"),
  audioName: document.getElementById("audio-name"),
  audioMeta: document.getElementById("audio-meta"),
  replaceAudio: document.getElementById("replace-audio"),
  restart: document.getElementById("restart"),
  resetAudio: document.getElementById("reset-audio"),
  resetAlbum: document.getElementById("reset-album"),
  resetThumbs: document.getElementById("reset-thumbs"),
  resetTimestamps: document.getElementById("reset-timestamps"),
  resetKeertanis: document.getElementById("reset-keertanis"),
  programStep: document.getElementById("program-step"),
  albumName: document.getElementById("album-name"),
  artDrop: document.getElementById("art-drop"),
  artInput: document.getElementById("art-input"),
  artPreview: document.getElementById("art-preview"),
  artPlaceholder: document.getElementById("art-placeholder"),
  artLater: document.getElementById("art-later"),
  artApply: document.getElementById("art-apply"),
  artRemove: document.getElementById("art-remove"),
  thumbsStep: document.getElementById("thumbs-step"),
  thumbsDrop: document.getElementById("thumbs-drop"),
  thumbsInput: document.getElementById("thumbs-input"),
  thumbsStrip: document.getElementById("thumbs-strip"),
  timestampsStep: document.getElementById("timestamps-step"),
  timestampsText: document.getElementById("timestamps-text"),
  keertaniStep: document.getElementById("keertani-step"),
  keertaniList: document.getElementById("keertani-list"),
  addKeertani: document.getElementById("add-keertani"),
  publish: document.getElementById("publish"),
  account: document.getElementById("account"),
  accountName: document.getElementById("account-name"),
  signOut: document.getElementById("sign-out"),
  keysModal: document.getElementById("keys-modal"),
  keysForm: document.getElementById("keys-form"),
  keysCancel: document.getElementById("keys-cancel"),
  redirectUri: document.getElementById("redirect-uri"),
  signinModal: document.getElementById("signin-modal"),
  signinCancel: document.getElementById("signin-cancel"),
  signinGo: document.getElementById("signin-go"),
  progressModal: document.getElementById("progress-modal"),
  progressTitle: document.getElementById("progress-title"),
  progressBar: document.getElementById("progress-bar"),
  progressCopy: document.getElementById("progress-copy"),
  doneModal: document.getElementById("done-modal"),
  doneTitle: document.getElementById("done-title"),
  doneCopy: document.getElementById("done-copy"),
  doneTracks: document.getElementById("done-tracks"),
  doneLink: document.getElementById("done-link"),
  doneClose: document.getElementById("done-close"),
  toast: document.getElementById("toast"),
};

function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function blankKeertani() {
  return {
    id: uid(),
    honorific: "Bhai",
    name: "",
    title: "Singh Jee",
    origin: "",
    program: state.sharedProgram || state.albumName,
    start: "",
    end: "",
    thumb: false,
    useAlbumArt: state.albumThumbDefault,
  };
}

function trackTitle(k) {
  const parts = [k.honorific, k.name.trim(), k.title].filter(Boolean);
  let line = parts.join(" ");
  if (k.origin.trim()) line += ` ${k.origin.trim()}`;
  const program = (k.program || "").trim();
  if (program) line += ` - ${program}`;
  return line.trim();
}

function show(el) {
  el.hidden = false;
}

function hide(el) {
  el.hidden = true;
}

function toast(message) {
  els.toast.textContent = message;
  show(els.toast);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => hide(els.toast), 4200);
}

function bindDrop(zone, input, onFile) {
  zone.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    input.click();
  });
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("dragover");
    const file = event.dataTransfer.files[0];
    if (file) onFile(file);
  });
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (file) onFile(file);
    input.value = "";
  });
}

function bindDropMany(zone, input, onFiles) {
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("dragover");
    const files = [...event.dataTransfer.files].filter((file) => file.type.startsWith("image/"));
    if (files.length) onFiles(files);
  });
  input.addEventListener("change", () => {
    const files = [...input.files];
    if (files.length) onFiles(files);
    input.value = "";
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    let detail = (data && data.detail) || data.message || response.statusText;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join(" ");
    } else if (detail && typeof detail === "object") {
      detail = JSON.stringify(detail);
    }
    const error = new Error(detail);
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

function saveLocal() {
  const draft = {
    albumName: state.albumName,
    sharedProgram: state.sharedProgram,
    artLater: state.artLater,
    pendingPublish: state.pendingPublish,
    albumThumbDefault: state.albumThumbDefault,
    timestampsText: state.timestampsText,
    keertanis: state.keertanis.map(({ thumb, ...rest }) => rest),
  };
  localStorage.setItem("splittracks-draft", JSON.stringify(draft));
  api("/api/draft", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  }).catch(() => {});
}

function loadLocal() {
  try {
    return JSON.parse(localStorage.getItem("splittracks-draft") || "null");
  } catch {
    return null;
  }
}

function renderAudio() {
  if (!state.audio) {
    show(els.audioDrop);
    hide(els.audioChip);
    return;
  }
  hide(els.audioDrop);
  show(els.audioChip);
  els.audioName.textContent = state.audio.filename;
  els.audioMeta.textContent = state.audio.duration_label
    ? `${state.audio.duration_label} · ready to split`
    : "ready to split";
  show(els.programStep);
  show(els.thumbsStep);
  show(els.timestampsStep);
  maybeShowKeertanis();
}

function maybeShowKeertanis() {
  if (!state.audio) return;
  show(els.thumbsStep);
  show(els.timestampsStep);
  if (!state.keertanis.length) state.keertanis.push(blankKeertani());
  show(els.keertaniStep);
  renderKeertanis();
  renderTimestamps();
}

function renderTimestamps() {
  if (els.timestampsText.value !== state.timestampsText) {
    els.timestampsText.value = state.timestampsText;
  }
}

function renderArt() {
  if (state.albumArt) {
    els.artPreview.src = `/api/files/album-art${state.albumArtVersion ? `?v=${state.albumArtVersion}` : ""}`;
    show(els.artPreview);
    hide(els.artPlaceholder);
    show(els.artRemove);
    show(els.artApply);
    hide(els.artLater);
  } else {
    hide(els.artPreview);
    show(els.artPlaceholder);
    hide(els.artRemove);
    hide(els.artApply);
    show(els.artLater);
  }
}

function renderAccount() {
  if (state.authenticated && state.user) {
    show(els.account);
    els.accountName.textContent = state.user.full_name || state.user.username;
  } else {
    hide(els.account);
  }
}

function thumbSrc(k) {
  if (k.thumb) return `/api/files/thumb/${k.id}${k.thumbVersion ? `?v=${k.thumbVersion}` : ""}`;
  if (k.useAlbumArt && state.albumArt) {
    return `/api/files/album-art${state.albumArtVersion ? `?v=${state.albumArtVersion}` : ""}`;
  }
  return "";
}

function renderThumbsStrip() {
  const items = state.keertanis.filter((k) => k.thumb || (k.useAlbumArt && state.albumArt));
  if (!items.length) {
    hide(els.thumbsStrip);
    els.thumbsStrip.innerHTML = "";
    return;
  }
  els.thumbsStrip.innerHTML = items
    .map((k) => `<img src="${thumbSrc(k)}" alt="${escapeAttr(k.name || "keertani")}" />`)
    .join("");
  show(els.thumbsStrip);
}

function syncProgram(value, source) {
  state.sharedProgram = value;
  for (const k of state.keertanis) k.program = value;
  document.querySelectorAll('[data-field="program"]').forEach((input) => {
    if (input !== source && input.value !== value) input.value = value;
  });
  document.querySelectorAll(".keertani").forEach((card) => {
    const item = state.keertanis.find((k) => k.id === card.dataset.id);
    if (item) card.querySelector(".preview").textContent = trackTitle(item);
  });
  saveLocal();
}

function renderKeertanis() {
  els.keertaniList.innerHTML = "";
  state.keertanis.forEach((k, index) => {
    const src = thumbSrc(k);
    const card = document.createElement("article");
    card.className = "keertani";
    card.dataset.id = k.id;
    card.innerHTML = `
      <div class="keertani-top">
        <span class="keertani-index">${String(index + 1).padStart(2, "0")}</span>
        <div class="keertani-top-actions">
          <button type="button" class="text-btn reset-keertani">Reset</button>
          ${state.keertanis.length > 1 ? `<button type="button" class="text-btn remove-keertani">Remove</button>` : ""}
        </div>
      </div>
      <div class="keertani-body">
        <div class="thumb-drop" role="button" tabindex="0">
          <input type="file" accept="image/*" hidden />
          <img alt="" ${src ? `src="${src}"` : "hidden"} />
          <span class="thumb-placeholder"${src ? " hidden" : ""}>Thumb</span>
        </div>
        <div>
          <div class="name-row">
            <button type="button" class="stamp ${k.honorific === "Bibi" ? "bibi" : "bhai"}" data-field="honorific" title="Click to toggle">${k.honorific}</button>
            <input class="field name-input" data-field="name" value="${escapeAttr(k.name)}" placeholder="keertani" size="20" />
            <button type="button" class="stamp ${k.honorific === "Bibi" ? "bibi" : "bhai"}" data-field="title" title="Click to toggle">${k.title}</button>
            <input class="field origin-input" data-field="origin" value="${escapeAttr(k.origin)}" placeholder="Origin" />
            <input class="field program-field" data-field="program" value="${escapeAttr(k.program)}" placeholder="program" />
          </div>
          <p class="preview">${escapeHtml(trackTitle(k) || "Bhai Singh Jee")}</p>
        </div>
      </div>
      <div class="times">
        <label>
          <span>Start</span>
          <input class="field" data-field="start" value="${escapeAttr(k.start)}" />
        </label>
        <em>→</em>
        <label>
          <span>End</span>
          <input class="field" data-field="end" value="${escapeAttr(k.end)}" />
        </label>
      </div>
    `;
    els.keertaniList.appendChild(card);

    const thumbInput = card.querySelector('input[type="file"]');
    const thumbDrop = card.querySelector(".thumb-drop");
    bindDrop(thumbDrop, thumbInput, (file) => uploadThumb(k, file, card));

    card.querySelectorAll(".stamp").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleHonorific(k);
        const isBibi = k.honorific === "Bibi";
        card.querySelectorAll(".stamp").forEach((stamp) => {
          stamp.classList.toggle("bibi", isBibi);
          stamp.classList.toggle("bhai", !isBibi);
          if (stamp.dataset.field === "honorific") stamp.textContent = k.honorific;
          if (stamp.dataset.field === "title") stamp.textContent = k.title;
        });
        card.querySelector(".preview").textContent = trackTitle(k) || "Bhai Singh Jee";
        saveLocal();
      });
    });

    card.querySelectorAll("input.field").forEach((input) => {
      input.addEventListener("input", () => {
        if (input.dataset.field === "program") {
          syncProgram(input.value, input);
          return;
        }
        k[input.dataset.field] = input.value;
        card.querySelector(".preview").textContent = trackTitle(k) || "Bhai Singh Jee";
        saveLocal();
      });
    });

    card.querySelector(".reset-keertani").addEventListener("click", () => {
      resetKeertani(k).catch((err) => toast(err.message));
    });

    const remove = card.querySelector(".remove-keertani");
    if (remove) {
      remove.addEventListener("click", () => {
        state.keertanis = state.keertanis.filter((item) => item.id !== k.id);
        renderKeertanis();
        renderThumbsStrip();
        saveLocal();
      });
    }
  });
  renderThumbsStrip();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function toggleHonorific(k) {
  const toBibi = k.honorific !== "Bibi";
  k.honorific = toBibi ? "Bibi" : "Bhai";
  k.title = toBibi ? "Kaur Jee" : "Singh Jee";
}

async function uploadAudio(file) {
  const body = new FormData();
  body.append("file", file);
  toast("Uploading audio…");
  const data = await api("/api/audio", { method: "POST", body });
  state.audio = data;
  renderAudio();
  maybeShowKeertanis();
  saveLocal();
  toast("Audio ready.");
}

async function uploadArt(file) {
  const body = new FormData();
  body.append("file", file);
  await api("/api/album-art", { method: "POST", body });
  state.albumArt = true;
  state.albumArtVersion = Date.now();
  state.artLater = false;
  renderArt();
  maybeShowKeertanis();
  saveLocal();
}

async function uploadThumb(keertani, file, card) {
  const body = new FormData();
  body.append("file", file);
  await api(`/api/thumbnail/${keertani.id}`, { method: "POST", body });
  keertani.thumb = true;
  keertani.thumbVersion = Date.now();
  keertani.useAlbumArt = false;
  if (card) {
    const img = card.querySelector("img");
    const placeholder = card.querySelector(".thumb-placeholder");
    img.src = thumbSrc(keertani);
    img.hidden = false;
    placeholder.hidden = true;
  }
  renderThumbsStrip();
}

function keertaniHasContent(k) {
  return Boolean(k.name.trim() || k.origin.trim() || k.start.trim() || k.end.trim() || k.thumb);
}

async function importThumbnails(files) {
  const images = [...files].filter((file) => file.type.startsWith("image/"));
  if (!images.length) return;
  toast(`Adding ${images.length} keertani${images.length === 1 ? "" : "s"}…`);
  state.keertanis = state.keertanis.filter(keertaniHasContent);
  for (const file of images) {
    const keertani = blankKeertani();
    keertani.useAlbumArt = false;
    state.keertanis.push(keertani);
    await uploadThumb(keertani, file);
  }
  if (!state.keertanis.length) state.keertanis.push(blankKeertani());
  show(els.keertaniStep);
  renderKeertanis();
  saveLocal();
  toast(`Created ${images.length} keertani${images.length === 1 ? "" : "s"} from photos.`);
}

function parseTimestampText(text) {
  const timeRe = /^(start|end|\d+(?::\d+){1,2}(?:\.\d+)?|\d+(?:\.\d+)?)$/i;
  const rows = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const tokens = line.match(/(?:"[^"]+"|'[^']+'|\S+)/g) || [];
    const parts = tokens.map((token) => token.replace(/^['"]|['"]$/g, ""));
    if (parts.length < 2) continue;
    const end = parts[parts.length - 1];
    const start = parts[parts.length - 2];
    if (!timeRe.test(start) || !timeRe.test(end)) continue;
    rows.push({
      name: parts.slice(0, -2).join(" "),
      start,
      end,
    });
  }
  return rows;
}

function ingestTimestamps(text, { announce = false } = {}) {
  state.timestampsText = text;
  const rows = parseTimestampText(text);
  if (rows.length) applyTimestampRows(rows);
  saveLocal();
  if (announce && rows.length) {
    toast(`Filled ${rows.length} keertani${rows.length === 1 ? "" : "s"} from timestamps.`);
  }
}

function applyTimestampRows(rows) {
  rows.forEach((row, index) => {
    if (!state.keertanis[index]) state.keertanis.push(blankKeertani());
    const keertani = state.keertanis[index];
    if (row.name) keertani.name = row.name;
    keertani.start = row.start || "";
    keertani.end = row.end || "";
  });
  show(els.keertaniStep);
  renderKeertanis();
}

function applyAlbumArtToThumbs() {
  if (!state.albumArt) {
    toast("Add album art first.");
    return;
  }
  state.albumThumbDefault = true;
  for (const k of state.keertanis) {
    if (!k.thumb) k.useAlbumArt = true;
  }
  renderKeertanis();
  saveLocal();
  toast("Album art applied to empty thumbnails.");
}

async function resetKeertani(k) {
  if (k.thumb) {
    await api(`/api/thumbnail/${k.id}`, { method: "DELETE" });
  }
  k.honorific = "Bhai";
  k.title = "Singh Jee";
  k.name = "";
  k.origin = "";
  k.start = "";
  k.end = "";
  k.thumb = false;
  k.useAlbumArt = state.albumThumbDefault;
  k.program = state.sharedProgram;
  renderKeertanis();
  saveLocal();
}

async function resetAudio() {
  await api("/api/audio", { method: "DELETE" });
  state.audio = null;
  renderAudio();
  saveLocal();
}

async function resetAlbum() {
  if (state.albumArt) {
    await api("/api/album-art", { method: "DELETE" });
  }
  state.albumName = "";
  state.albumArt = false;
  state.artLater = false;
  state.albumThumbDefault = false;
  els.albumName.value = "";
  for (const k of state.keertanis) {
    if (!k.thumb) k.useAlbumArt = false;
  }
  renderArt();
  renderKeertanis();
  saveLocal();
}

function resetTimestamps() {
  state.timestampsText = "";
  renderTimestamps();
  saveLocal();
}

async function resetThumbs() {
  await api("/api/thumbnails", { method: "DELETE" });
  for (const k of state.keertanis) {
    k.thumb = false;
  }
  renderKeertanis();
  saveLocal();
}

async function resetKeertaniList() {
  await api("/api/thumbnails", { method: "DELETE" });
  state.keertanis = [blankKeertani()];
  renderKeertanis();
  saveLocal();
}

async function restartAll() {
  await api("/api/restart", { method: "POST" });
  localStorage.removeItem("splittracks-draft");
  state.audio = null;
  state.albumName = "";
  state.albumArt = false;
  state.artLater = false;
  state.albumThumbDefault = false;
  state.keertanis = [];
  state.sharedProgram = "";
  state.pendingPublish = false;
  els.albumName.value = "";
  state.timestampsText = "";
  hide(els.programStep);
  hide(els.thumbsStep);
  hide(els.timestampsStep);
  hide(els.keertaniStep);
  renderAudio();
  renderArt();
  renderThumbsStrip();
  toast("Started over.");
}

function validate() {
  if (!state.audio) return "Insert an audio file first.";
  if (!state.albumName.trim()) return "Name this album.";
  if (!state.keertanis.length) return "Add at least one keertani.";
  for (const [index, k] of state.keertanis.entries()) {
    if (!k.name.trim()) return `Add a name for keertani ${index + 1}.`;
    if (!k.start.trim() || !k.end.trim()) return `Add start and end times for ${k.name.trim() || `keertani ${index + 1}`}.`;
  }
  return null;
}

function publishPayload() {
  return {
    album_name: state.albumName.trim(),
    program: state.albumName.trim(),
    keertanis: state.keertanis.map((k) => ({
      id: k.id,
      honorific: k.honorific,
      name: k.name,
      title: k.title,
      origin: k.origin,
      program: k.program,
      start: k.start,
      end: k.end,
    })),
  };
}

async function startPublish() {
  const problem = validate();
  if (problem) {
    toast(problem);
    return;
  }
  saveLocal();
  if (!state.hasKeys) {
    els.redirectUri.textContent = state.redirectUri;
    els.keysModal.showModal();
    return;
  }
  if (!state.authenticated) {
    state.pendingPublish = true;
    saveLocal();
    els.signinModal.showModal();
    return;
  }
  await postToSoundCloud();
}

async function postToSoundCloud() {
  els.progressModal.showModal();
  els.progressTitle.textContent = "Splitting tracks…";
  els.progressCopy.textContent = "Encoding MP3s, then uploading privately to SoundCloud.";
  els.progressBar.style.width = "6%";

  const response = await fetch("/api/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(publishPayload()),
  });

  if (response.status === 401) {
    els.progressModal.close();
    state.pendingPublish = true;
    saveLocal();
    els.signinModal.showModal();
    return;
  }

  if (!response.ok) {
    els.progressModal.close();
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Could not start publish.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      let dataLine = "";
      currentEvent = "message";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) currentEvent = line.slice(6).trim();
        if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      const data = JSON.parse(dataLine);
      if (currentEvent === "progress") {
        const pct = Math.min(96, Math.round((data.index / data.total) * 90) + (data.stage === "upload" ? 6 : 0));
        els.progressBar.style.width = `${pct}%`;
        els.progressTitle.textContent = data.stage === "album" ? "Creating album" : data.title;
        els.progressCopy.textContent = data.message;
      } else if (currentEvent === "error") {
        els.progressModal.close();
        toast(data.message || "Publish failed.");
        return;
      } else if (currentEvent === "done") {
        els.progressBar.style.width = "100%";
        els.progressModal.close();
        showDone(data);
        state.pendingPublish = false;
        saveLocal();
      }
    }
  }
}

function showDone(data) {
  els.doneTitle.textContent = data.album || "Posted.";
  els.doneCopy.textContent = "Tracks are private / unlisted and grouped on this album, in order.";
  els.doneTracks.innerHTML = "";
  for (const track of data.tracks || []) {
    const li = document.createElement("li");
    if (track.permalink_url) {
      const a = document.createElement("a");
      a.href = track.permalink_url;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = track.title;
      li.appendChild(a);
    } else {
      li.textContent = track.title;
    }
    els.doneTracks.appendChild(li);
  }
  if (data.playlist_url) {
    els.doneLink.href = data.playlist_url;
    els.doneLink.hidden = false;
  } else {
    els.doneLink.hidden = true;
  }
  els.doneModal.showModal();
}

bindDrop(els.audioDrop, els.audioInput, (file) => {
  uploadAudio(file).catch((err) => toast(err.message));
});
els.replaceAudio.addEventListener("click", () => els.audioInput.click());
els.restart.addEventListener("click", () => {
  restartAll().catch((err) => toast(err.message));
});
els.resetAudio.addEventListener("click", () => {
  resetAudio().catch((err) => toast(err.message));
});
els.resetAlbum.addEventListener("click", () => {
  resetAlbum().catch((err) => toast(err.message));
});
els.resetThumbs.addEventListener("click", () => {
  resetThumbs().catch((err) => toast(err.message));
});
els.resetTimestamps.addEventListener("click", () => {
  resetTimestamps();
});
els.timestampsText.addEventListener("input", () => {
  clearTimeout(ingestTimestamps._t);
  ingestTimestamps._t = setTimeout(() => ingestTimestamps(els.timestampsText.value), 280);
});
els.timestampsText.addEventListener("paste", () => {
  clearTimeout(ingestTimestamps._t);
  setTimeout(() => ingestTimestamps(els.timestampsText.value, { announce: true }), 0);
});
els.resetKeertanis.addEventListener("click", () => {
  resetKeertaniList().catch((err) => toast(err.message));
});

bindDrop(els.artDrop, els.artInput, (file) => {
  uploadArt(file).catch((err) => toast(err.message));
});

els.albumName.addEventListener("input", () => {
  const previous = state.albumName;
  state.albumName = els.albumName.value;
  if (!state.sharedProgram || state.sharedProgram === previous) {
    syncProgram(state.albumName);
  } else {
    saveLocal();
  }
});

els.artLater.addEventListener("click", () => {
  state.artLater = true;
  maybeShowKeertanis();
  saveLocal();
});

els.artApply.addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
  applyAlbumArtToThumbs();
});

bindDropMany(els.thumbsDrop, els.thumbsInput, (files) => {
  importThumbnails(files).catch((err) => toast(err.message));
});

els.artRemove.addEventListener("click", async (event) => {
  event.preventDefault();
  event.stopPropagation();
  await api("/api/album-art", { method: "DELETE" });
  state.albumArt = false;
  renderArt();
  saveLocal();
});

els.addKeertani.addEventListener("click", () => {
  state.keertanis.push(blankKeertani());
  renderKeertanis();
  saveLocal();
});

els.publish.addEventListener("click", () => {
  startPublish().catch((err) => toast(err.message));
});

els.keysCancel.addEventListener("click", () => els.keysModal.close());
els.keysForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(els.keysForm);
  await api("/api/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: form.get("client_id"),
      client_secret: form.get("client_secret"),
      redirect_uri: state.redirectUri,
    }),
  });
  state.hasKeys = true;
  els.keysModal.close();
  toast("Keys saved. Post again to sign in.");
  startPublish().catch((err) => toast(err.message));
});

els.signinCancel.addEventListener("click", () => els.signinModal.close());
els.signinGo.addEventListener("click", () => {
  state.pendingPublish = true;
  saveLocal();
  window.location.href = "/api/auth/login";
});

els.doneClose.addEventListener("click", () => els.doneModal.close());
els.signOut.addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  state.authenticated = false;
  state.user = null;
  renderAccount();
});

async function boot() {
  const params = new URLSearchParams(window.location.search);
  const session = await api("/api/session");
  const local = loadLocal() || session.draft || {};

  state.audio = session.audio;
  state.albumArt = session.album_art;
  state.hasKeys = session.has_keys;
  state.authenticated = session.authenticated;
  state.user = session.user;
  state.redirectUri = session.redirect_uri || state.redirectUri;
  state.albumName = local.albumName || "";
  state.sharedProgram = local.sharedProgram || state.albumName;
  state.artLater = Boolean(local.artLater);
  state.albumThumbDefault = Boolean(local.albumThumbDefault);
  state.pendingPublish = Boolean(local.pendingPublish);
  state.timestampsText = local.timestampsText || "";
  state.keertanis = (local.keertanis || []).map((item) => ({
    honorific: "Bhai",
    title: "Singh Jee",
    name: "",
    origin: "",
    program: state.sharedProgram,
    start: "",
    end: "",
    useAlbumArt: false,
    ...item,
    thumb: (session.thumbnails || []).includes(item.id),
  }));

  els.albumName.value = state.albumName;
  els.redirectUri.textContent = state.redirectUri;
  renderAudio();
  renderArt();
  renderAccount();
  maybeShowKeertanis();

  if (params.get("need_keys") === "1") els.keysModal.showModal();
  if (params.get("auth_error")) toast("SoundCloud sign-in did not finish. Try posting again.");
  if (params.get("connected") === "1") {
    toast(`Signed in${state.user ? ` as ${state.user.username}` : ""}.`);
    if (state.pendingPublish) {
      postToSoundCloud().catch((err) => toast(err.message));
    }
  }
  history.replaceState({}, "", "/");
}

boot().catch((err) => toast(err.message));
