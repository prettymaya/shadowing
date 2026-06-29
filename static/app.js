const state = {
  categories: [],
  catalogCategories: [],
  lessons: [],
  catalogLessons: [],
  progress: {},
  sessions: [],
  selected: null,
  loop: false,
  startedAt: null,
  mode: "api",
  playbackRate: 1,
  youtubePlayer: null,
  youtubeApiPromise: null,
};

const $ = (id) => document.getElementById(id);
const isStaticHost = !["localhost", "127.0.0.1"].includes(location.hostname);
const progressKey = "shadowing-progress-v1";
const sessionsKey = "shadowing-sessions-v1";
const themeKey = "shadowing-theme-v1";
const speedKey = "shadowing-speed-v1";
const languageKey = "shadowing-language-v1";
const defaultTheme = { mode: "system", accent: "teal" };
const defaultLanguage = "english";

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Bir hata oldu");
  return data;
}

async function loadData(path, options = {}) {
  if (state.mode === "api" && currentLanguage() === "english") {
    return api(path, options);
  }
  if (path === "/api/categories") return staticCategories();
  if (path === "/api/stats") return staticStats();
  if (path.startsWith("/api/lessons?")) return staticLessons();
  if (path === "/api/sessions") return staticSessions();
  const detailMatch = path.match(/^\/api\/lessons\/([^/]+)$/);
  if (detailMatch) return staticLessonDetail(decodeURIComponent(detailMatch[1]));
  const completeMatch = path.match(/^\/api\/lessons\/([^/]+)\/complete$/);
  if (completeMatch) return staticComplete(decodeURIComponent(completeMatch[1]), JSON.parse(options.body || "{}"));
  const resetMatch = path.match(/^\/api\/lessons\/([^/]+)\/reset$/);
  if (resetMatch) return staticReset(decodeURIComponent(resetMatch[1]));
  throw new Error("Statik modda bu işlem yok");
}

function loadLocalState() {
  state.progress = JSON.parse(localStorage.getItem(progressKey) || "{}");
  state.sessions = JSON.parse(localStorage.getItem(sessionsKey) || "[]");
  state.playbackRate = Number(localStorage.getItem(speedKey) || "1");
}

function saveLocalState() {
  localStorage.setItem(progressKey, JSON.stringify(state.progress));
  localStorage.setItem(sessionsKey, JSON.stringify(state.sessions.slice(-500)));
}

function savePlaybackRate(rate) {
  state.playbackRate = Number(rate) || 1;
  localStorage.setItem(speedKey, String(state.playbackRate));
}

function currentLanguage() {
  return $("languageFilter")?.value || localStorage.getItem(languageKey) || defaultLanguage;
}

function saveLanguage(language) {
  localStorage.setItem(languageKey, language || defaultLanguage);
}

function loadTheme() {
  try {
    return { ...defaultTheme, ...JSON.parse(localStorage.getItem(themeKey) || "{}") };
  } catch (_) {
    return { ...defaultTheme };
  }
}

function saveTheme(theme) {
  localStorage.setItem(themeKey, JSON.stringify(theme));
}

function applyTheme(theme = loadTheme()) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolvedMode = theme.mode === "system" ? (prefersDark ? "dark" : "light") : theme.mode;
  document.documentElement.dataset.theme = resolvedMode;
  document.documentElement.dataset.accent = theme.accent;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", resolvedMode === "dark" ? "#0b1220" : getAccentColor(theme.accent));

  document.querySelectorAll(".themeMode").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === theme.mode);
  });
  document.querySelectorAll(".swatch").forEach((button) => {
    button.classList.toggle("active", button.dataset.accent === theme.accent);
  });
}

function updateTheme(partial) {
  const next = { ...loadTheme(), ...partial };
  saveTheme(next);
  applyTheme(next);
}

function getAccentColor(accent) {
  return {
    teal: "#0f766e",
    blue: "#2563eb",
    violet: "#7c3aed",
    rose: "#e11d48",
    amber: "#d97706",
    slate: "#475569",
  }[accent] || "#0f766e";
}

function currentFilters() {
  return {
    language: currentLanguage(),
    category: $("categoryFilter").value,
    status: $("statusFilter").value,
    q: $("searchInput").value.trim().toLowerCase(),
    level: $("levelFilter").value,
  };
}

async function loadStats() {
  const data = await loadData("/api/stats");
  $("statTodo").textContent = data.totals.todo || 0;
  $("statDone").textContent = data.totals.done || 0;
  $("statToday").textContent = data.today || 0;
}

async function loadHistory() {
  const sessions = await loadData("/api/sessions");
  const selectedDate = $("historyDate").value || localDateKey(new Date());
  const selected = sessions.filter((session) => localDateKey(session.created_at) === selectedDate);
  $("historyList").innerHTML = selected.length ? selected.map((session) => `
    <button class="historyItem" type="button" data-id="${session.lesson_id}">
      <strong>${escapeHtml(session.title || "Ders")}</strong>
      <span>${escapeHtml(session.category_name || "")}${session.seconds ? ` · ${formatSeconds(session.seconds)}` : ""}</span>
      ${session.notes ? `<small>${escapeHtml(session.notes)}</small>` : ""}
    </button>
  `).join("") : `<p class="hint">Bu gün için kayıt yok.</p>`;
  document.querySelectorAll(".historyItem").forEach((button) => {
    button.addEventListener("click", () => openLesson(button.dataset.id));
  });
}

async function loadCategories() {
  state.categories = await loadData("/api/categories");
  renderLevelOptions();
  $("categoryFilter").innerHTML = [
    `<option value="">Tüm kategoriler</option>`,
    ...state.categories.map((c) => `<option value="${c.slug}">${c.name} (${c.lesson_count})</option>`),
  ].join("");
}

function renderLevelOptions() {
  const language = currentLanguage();
  const selected = $("levelFilter").value;
  const fallback = language === "spanish"
    ? ["Beginner Spanish", "Intermediate Spanish", "Advanced Spanish"]
    : ["A1", "A2", "B1", "B2", "C1", "C2"];
  const levels = [...new Set(
    state.catalogLessons
      .filter((lesson) => (lesson.language || "english") === language)
      .map((lesson) => lesson.level)
      .filter(Boolean)
  )];
  const options = levels.length ? levels : fallback;
  $("levelFilter").innerHTML = [
    `<option value="">Tümü</option>`,
    ...options.map((level) => `<option value="${escapeHtml(level)}">${escapeHtml(level)}</option>`),
  ].join("");
  if (options.includes(selected)) $("levelFilter").value = selected;
}

async function loadLessons() {
  state.lessons = await loadData(`/api/lessons?${new URLSearchParams(currentFilters()).toString()}`);
  $("listCount").textContent = `${state.lessons.length} ders`;
  const html = state.lessons.map((lesson) => `
    <button class="lesson ${lesson.completed_at ? "done" : ""} ${state.selected?.id === lesson.id ? "active" : ""}" data-id="${lesson.id}">
      <strong>${escapeHtml(lesson.title)}</strong>
      <small>${escapeHtml(lesson.category_name)}${lesson.subtitle ? " · " + escapeHtml(lesson.subtitle) : ""}</small>
      <span class="chips">
        ${lesson.level ? `<span class="chip">${lesson.level}</span>` : ""}
        ${lesson.parts ? `<span class="chip">${lesson.parts} parts</span>` : ""}
        ${lesson.completed_at ? `<span class="chip">yapıldı</span>` : ""}
      </span>
    </button>
  `).join("");
  $("lessons").innerHTML = html || `<div class="empty"><h2>Liste boş</h2><p>Filtreleri genişlet veya import çalıştır.</p></div>`;
  document.querySelectorAll(".lesson").forEach((el) => {
    el.addEventListener("click", () => openLesson(el.dataset.id));
  });
}

async function openLesson(id) {
  $("emptyState").classList.add("hidden");
  $("lessonView").classList.remove("hidden");
  $("lessonTitle").textContent = "Yükleniyor...";
  const lesson = await loadData(`/api/lessons/${id}`);
  state.selected = lesson;
  state.startedAt = Date.now();
  $("lessonCategory").textContent = lesson.category_name;
  $("lessonTitle").textContent = lesson.title;
  $("lessonMeta").textContent = [lesson.level, lesson.parts ? `${lesson.parts} parts` : "", lesson.completed_at ? `Yapıldı: ${lesson.completed_at}` : ""].filter(Boolean).join(" · ");
  $("notes").value = lesson.notes || "";
  renderMedia(lesson);
  $("challengeCount").textContent = `${lesson.challenges.length} satır`;
  $("transcript").innerHTML = lesson.challenges.map((line) => `
    <div class="line">
      <button class="jumpLine" data-start="${line.time_start ?? ""}" title="Bu satıra git">${line.position}</button>
      <div>${escapeHtml(line.content)}</div>
      <button class="copyLine secondary" data-copy="${escapeHtml(line.content)}" title="Satırı kopyala">Kopyala</button>
    </div>
  `).join("") || `<p class="hint">Transcript bulunamadı.</p>`;
  document.querySelectorAll(".jumpLine").forEach((button) => {
    button.addEventListener("click", () => {
      const start = Number(button.dataset.start);
      if (!Number.isNaN(start)) {
        seekToLine(start);
      }
    });
  });
  document.querySelectorAll(".copyLine").forEach((button) => {
    button.addEventListener("click", () => copyText(button.dataset.copy || "", button, "Satır kopyalandı"));
  });
  await loadLessons();
  focusPlayerOnSmallScreen();
}

function renderMedia(lesson) {
  const audio = $("audio");
  const videoWrap = $("videoWrap");
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  videoWrap.innerHTML = "";
  videoWrap.classList.add("hidden");

  if (lesson.audio_url) {
    audio.classList.remove("hidden");
    audio.src = lesson.audio_url;
    audio.playbackRate = state.playbackRate;
    return;
  }

  audio.classList.add("hidden");
  if (lesson.youtube_video_id) {
    videoWrap.classList.remove("hidden");
    renderYouTubePlayer(lesson.youtube_video_id, lesson.title);
    return;
  }

  if (lesson.vimeo_video_id) {
    videoWrap.classList.remove("hidden");
    videoWrap.innerHTML = vimeoIframe(lesson.vimeo_video_id, lesson.title);
  }
}

function seekToLine(start) {
  if (state.selected?.audio_url) {
    $("audio").currentTime = start;
    $("audio").play();
    return;
  }
  if (state.selected?.youtube_video_id) {
    if (state.youtubePlayer?.seekTo) {
      state.youtubePlayer.setPlaybackRate?.(state.playbackRate);
      state.youtubePlayer.seekTo(Math.max(0, Number(start) || 0), true);
      state.youtubePlayer.playVideo?.();
    } else {
      renderYouTubePlayer(state.selected.youtube_video_id, state.selected.title, start, true);
    }
  }
}

function seekRelative(seconds) {
  if (state.selected?.audio_url) {
    $("audio").currentTime = Math.max(0, $("audio").currentTime + seconds);
    return;
  }
  if (state.selected?.youtube_video_id && state.youtubePlayer?.getCurrentTime) {
    const next = Math.max(0, state.youtubePlayer.getCurrentTime() + seconds);
    state.youtubePlayer.seekTo(next, true);
  }
}

function renderYouTubePlayer(videoId, title, start = 0, autoplay = false) {
  state.youtubePlayer = null;
  $("videoWrap").innerHTML = `<div id="youtubePlayer" title="${escapeHtml(title)}"></div>`;
  loadYouTubeApi()
    .then(() => {
      state.youtubePlayer = new YT.Player("youtubePlayer", {
        videoId,
        playerVars: {
          start: Math.max(0, Math.floor(Number(start) || 0)),
          rel: 0,
          playsinline: 1,
          autoplay: autoplay ? 1 : 0,
        },
        events: {
          onReady: (event) => {
            event.target.setPlaybackRate?.(state.playbackRate);
            if (autoplay) event.target.playVideo?.();
          },
        },
      });
    })
    .catch(() => {
      $("videoWrap").innerHTML = youtubeIframe(videoId, title, start, autoplay);
    });
}

function loadYouTubeApi() {
  if (window.YT?.Player) return Promise.resolve();
  if (state.youtubeApiPromise) return state.youtubeApiPromise;
  state.youtubeApiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return state.youtubeApiPromise;
}

function youtubeIframe(videoId, title, start = 0, autoplay = false) {
  const params = new URLSearchParams({
    start: String(Math.max(0, Math.floor(Number(start) || 0))),
    rel: "0",
    playsinline: "1",
  });
  if (autoplay) params.set("autoplay", "1");
  return `
    <iframe
      src="https://www.youtube.com/embed/${encodeURIComponent(videoId)}?${params.toString()}"
      title="${escapeHtml(title)}"
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
      allowfullscreen></iframe>
  `;
}

function vimeoIframe(videoId, title) {
  const params = new URLSearchParams({
    playsinline: "1",
    title: "0",
    byline: "0",
    portrait: "0",
  });
  return `
    <iframe
      src="https://player.vimeo.com/video/${encodeURIComponent(videoId)}?${params.toString()}"
      title="${escapeHtml(title)}"
      allow="autoplay; fullscreen; picture-in-picture"
      allowfullscreen></iframe>
  `;
}

function applyPlaybackRate(rate) {
  savePlaybackRate(rate);
  $("speedSelect").value = String(state.playbackRate);
  $("audio").playbackRate = state.playbackRate;
  if (state.youtubePlayer?.setPlaybackRate) {
    state.youtubePlayer.setPlaybackRate(state.playbackRate);
  }
}

function focusPlayerOnSmallScreen() {
  if (window.matchMedia("(max-width: 980px)").matches) {
    requestAnimationFrame(() => {
      window.scrollTo({ top: $("playerSection").offsetTop, behavior: "auto" });
    });
  }
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[ch]));
}

async function copyText(text, source, message = "Kopyalandı") {
  const value = String(text || "").trim();
  if (!value) {
    showCopyStatus("Kopyalanacak metin yok");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
  } catch (_) {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  showCopyStatus(message);
  if (source) {
    const previous = source.textContent;
    source.textContent = "Kopyalandı";
    setTimeout(() => {
      source.textContent = previous;
    }, 900);
  }
}

function fullTranscriptText() {
  if (!state.selected?.challenges?.length) return "";
  return state.selected.challenges.map((line) => line.content).join("\n");
}

function showCopyStatus(message) {
  $("copyStatus").textContent = message;
  clearTimeout(state.copyStatusTimer);
  state.copyStatusTimer = setTimeout(() => {
    $("copyStatus").textContent = "";
  }, 1600);
}

function localDateKey(value) {
  if (value instanceof Date) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  }
  return String(value || "").slice(0, 10);
}

function localDateTime(date = new Date()) {
  return `${localDateKey(date)}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function formatSeconds(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return minutes ? `${minutes} dk ${rest} sn` : `${rest} sn`;
}

async function copySelectedDaySummary() {
  const sessions = await loadData("/api/sessions");
  const selectedDate = $("historyDate").value || localDateKey(new Date());
  const selected = sessions.filter((session) => localDateKey(session.created_at) === selectedDate);
  if (!selected.length) {
    showCopyStatus("Kayıt yok");
    return;
  }
  const lines = [
    `${selectedDate} shadowing özeti`,
    ...selected.map((session, index) => {
      const duration = session.seconds ? ` (${formatSeconds(session.seconds)})` : "";
      const note = session.notes ? ` - ${session.notes}` : "";
      return `${index + 1}. ${session.title || "Ders"} - ${session.category_name || ""}${duration}${note}`;
    }),
  ];
  await copyText(lines.join("\n"), $("copyDayBtn"), "Gün özeti kopyalandı");
}

async function completeSelected() {
  if (!state.selected) return;
  const seconds = state.startedAt ? Math.round((Date.now() - state.startedAt) / 1000) : 0;
  await loadData(`/api/lessons/${state.selected.id}/complete`, {
    method: "POST",
    body: JSON.stringify({ seconds, notes: $("notes").value }),
  });
  await loadStats();
  await loadLessons();
  await loadHistory();
  $("lessonView").classList.add("hidden");
  $("emptyState").classList.remove("hidden");
}

async function resetSelected() {
  if (!state.selected) return;
  await loadData(`/api/lessons/${state.selected.id}/reset`, { method: "POST", body: "{}" });
  await loadStats();
  await openLesson(state.selected.id);
}

function mergeProgress(lesson) {
  const progress = state.progress[lesson.id] || {};
  return {
    ...lesson,
    completed_at: progress.completed_at || null,
    notes: progress.notes || "",
  };
}

function staticStats() {
  const lessons = catalogLessonsForLanguage();
  const total = lessons.length;
  const done = lessons.filter((lesson) => state.progress[lesson.id]?.completed_at).length;
  const todayIso = localDateKey(new Date());
  const today = state.sessions.filter((session) => {
    const lesson = lessonById(session.lesson_id);
    return localDateKey(session.created_at) === todayIso && (lesson.language || "english") === currentLanguage();
  }).length;
  return { totals: { total, done, todo: total - done }, today };
}

function staticCategories() {
  const language = currentLanguage();
  return state.catalogCategories.filter((category) => (category.language || "english") === language);
}

function catalogLessonsForLanguage() {
  const language = currentLanguage();
  return state.catalogLessons.filter((lesson) => (lesson.language || "english") === language);
}

function lessonById(id) {
  const lessonId = String(id);
  return state.catalogLessons.find((lesson) => String(lesson.id) === lessonId) || {};
}

function staticLessons() {
  const filters = currentFilters();
  return catalogLessonsForLanguage()
    .map(mergeProgress)
    .filter((lesson) => {
      if (filters.category && lesson.category_slug !== filters.category) return false;
      if (filters.status === "todo" && lesson.completed_at) return false;
      if (filters.status === "done" && !lesson.completed_at) return false;
      if (filters.level && lesson.level !== filters.level) return false;
      if (filters.q) {
        const text = `${lesson.title} ${lesson.subtitle} ${lesson.category_name}`.toLowerCase();
        if (!text.includes(filters.q)) return false;
      }
      return true;
    })
    .slice(0, 500);
}

function staticSessions() {
  return [...state.sessions]
    .reverse()
    .map((session) => {
      const lesson = lessonById(session.lesson_id);
      return {
        ...session,
        title: session.title || lesson.title || "",
        category_name: session.category_name || lesson.category_name || "",
      };
    })
    .filter((session) => (lessonById(session.lesson_id).language || "english") === currentLanguage())
    .slice(0, 200);
}

async function staticLessonDetail(id) {
  const base = lessonById(id);
  if (!base.id) throw new Error("Ders bulunamadı");
  let detail = { ...base, challenges: [] };
  try {
    const res = await fetch(`data/lessons/${encodeURIComponent(id)}.json`);
    if (res.ok) detail = await res.json();
  } catch (_) {
    // Statik export'ta detay yoksa transcript boş kalır.
  }
  return mergeProgress({ ...detail, challenges: detail.challenges || [] });
}

function staticComplete(id, payload) {
  const now = localDateTime();
  const lesson = lessonById(id);
  state.progress[id] = {
    completed_at: state.progress[id]?.completed_at || now,
    notes: String(payload.notes || ""),
  };
  state.sessions.push({
    lesson_id: id,
    created_at: now,
    seconds: payload.seconds || 0,
    notes: String(payload.notes || ""),
    title: lesson.title || "",
    category_name: lesson.category_name || "",
  });
  saveLocalState();
  return { ok: true, completed_at: state.progress[id].completed_at };
}

function staticReset(id) {
  state.progress[id] = { notes: "" };
  saveLocalState();
  return { ok: true };
}

async function bootstrapData() {
  loadLocalState();
  $("languageFilter").value = localStorage.getItem(languageKey) || defaultLanguage;
  const res = await fetch("data/catalog.json");
  if (res.ok) {
    const catalog = await res.json();
    state.catalogCategories = catalog.categories.map((category) => ({ language: "english", ...category }));
    state.catalogLessons = catalog.lessons.map((lesson) => ({ language: "english", ...lesson }));
  }

  if (!isStaticHost) {
    try {
      await api("/api/stats");
      state.mode = "api";
      $("modeHint").textContent = "Mac local server modunda SQLite kullanılıyor.";
      return;
    } catch (_) {
      state.mode = "static";
    }
  } else {
    state.mode = "static";
  }

  if (!state.catalogLessons.length) throw new Error("Statik katalog bulunamadı. python3 export_static.py çalıştır.");
  $("modeHint").textContent = "GitHub/iPhone modunda kayıtlar bu cihazın tarayıcı depolamasında tutulur.";
}

function wire() {
  applyTheme();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (loadTheme().mode === "system") applyTheme();
  });
  document.querySelectorAll(".themeMode").forEach((button) => {
    button.addEventListener("click", () => updateTheme({ mode: button.dataset.mode }));
  });
  document.querySelectorAll(".swatch").forEach((button) => {
    button.addEventListener("click", () => updateTheme({ accent: button.dataset.accent }));
  });
  $("languageFilter").addEventListener("change", async () => {
    saveLanguage(currentLanguage());
    $("categoryFilter").value = "";
    $("levelFilter").value = "";
    $("lessonView").classList.add("hidden");
    $("emptyState").classList.remove("hidden");
    await loadCategories();
    await loadStats();
    await loadLessons();
    await loadHistory();
  });
  ["categoryFilter", "statusFilter", "levelFilter"].forEach((id) => $(id).addEventListener("change", loadLessons));
  $("searchInput").addEventListener("input", () => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(loadLessons, 180);
  });
  $("refreshBtn").addEventListener("click", loadLessons);
  $("historyDate").value = localDateKey(new Date());
  $("historyDate").addEventListener("change", loadHistory);
  $("copyDayBtn").addEventListener("click", copySelectedDaySummary);
  $("completeBtn").addEventListener("click", completeSelected);
  $("resetBtn").addEventListener("click", resetSelected);
  $("copyTranscriptBtn").addEventListener("click", () => copyText(fullTranscriptText(), $("copyTranscriptBtn"), "Transcript kopyalandı"));
  $("backBtn").addEventListener("click", () => seekRelative(-5));
  $("forwardBtn").addEventListener("click", () => seekRelative(5));
  $("speedSelect").value = String(state.playbackRate);
  $("speedSelect").addEventListener("change", () => applyPlaybackRate($("speedSelect").value));
  $("loopBtn").addEventListener("click", () => {
    state.loop = !state.loop;
    $("audio").loop = state.loop;
    $("loopBtn").textContent = state.loop ? "Loop açık" : "Loop kapalı";
  });
}

async function init() {
  loadLocalState();
  wire();
  await bootstrapData();
  await loadCategories();
  await loadStats();
  await loadLessons();
  await loadHistory();
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

init().catch((err) => {
  $("lessons").innerHTML = `<div class="empty"><h2>Başlatılamadı</h2><p>${escapeHtml(err.message)}</p></div>`;
});
