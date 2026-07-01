(() => {
  const state = {
    networkItems: [],
    youtubeItems: [],
    visibleHistory: [],
    recording: false,
    recorderTimer: null,
    observer: null,
  };

  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    tryCaptureResponse(args[0], response);
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function open(method, url, ...rest) {
    this.__dsSubtitleUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function send(...args) {
    this.addEventListener("load", () => {
      try {
        const contentType = this.getResponseHeader("content-type") || "";
        if (looksLikeSubtitleUrl(this.__dsSubtitleUrl) || looksLikeSubtitleType(contentType)) {
          rememberNetworkText(String(this.__dsSubtitleUrl || ""), String(this.responseText || ""));
        }
      } catch (_) {}
    });
    return originalSend.apply(this, args);
  };

  function tryCaptureResponse(input, response) {
    const url = typeof input === "string" ? input : input?.url || "";
    const contentType = response.headers?.get?.("content-type") || "";
    if (!looksLikeSubtitleUrl(url) && !looksLikeSubtitleType(contentType)) return;
    response.clone().text().then((text) => rememberNetworkText(url, text)).catch(() => {});
  }

  function looksLikeSubtitleUrl(url) {
    return /\.(vtt|srt|ttml|dfxp)(\?|$)/i.test(String(url || ""));
  }

  function looksLikeSubtitleType(contentType) {
    return /text\/vtt|application\/x-subrip|ttml|dfxp/i.test(contentType || "");
  }

  function rememberNetworkText(url, text) {
    const parsed = parseSubtitleText(text);
    if (!parsed.length) return;
    state.networkItems.push({ url, cues: parsed });
    state.networkItems = state.networkItems.slice(-20);
  }

  function collectTextTracks() {
    const cues = [];
    for (const video of document.querySelectorAll("video")) {
      for (const track of Array.from(video.textTracks || [])) {
        if (!["captions", "subtitles"].includes(track.kind)) continue;
        const previousMode = track.mode;
        try {
          track.mode = "hidden";
          for (const cue of Array.from(track.cues || [])) {
            const text = cleanCueText(cue.text || "");
            if (text) cues.push({ start: cue.startTime, end: cue.endTime, text });
          }
        } catch (_) {
        } finally {
          try {
            track.mode = previousMode;
          } catch (_) {}
        }
      }
    }
    return cues;
  }

  function collectVisibleCaptions() {
    const selectors = [
      ".shaka-text-container",
      ".shaka-text-container *",
      "[class*='caption']",
      "[class*='subtitle']",
      "[class*='Caption']",
      "[class*='Subtitle']",
      "[class*='cue']",
      "[class*='Cue']",
      ".ytp-caption-segment",
      ".caption-window",
      ".ytp-caption-window-container",
      ".ytp-caption-window-container *",
      "[aria-live]",
    ];
    const texts = [];
    for (const node of queryAllDeep(selectors.join(","))) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const text = cleanCueText(node.textContent || "");
      if (text && text.length > 1) texts.push(text);
    }
    return [...new Set(texts)].map((text, index) => ({ start: index, end: index, text }));
  }

  function queryAllDeep(selector, root = document) {
    const results = [];
    try {
      results.push(...root.querySelectorAll(selector));
      for (const element of root.querySelectorAll("*")) {
        if (element.shadowRoot) results.push(...queryAllDeep(selector, element.shadowRoot));
      }
    } catch (_) {}
    return results;
  }

  function parseSubtitleText(text) {
    const raw = String(text || "").replace(/\r/g, "");
    if (/^\s*\{/.test(raw)) return parseJsonSubtitle(raw);
    if (/^\s*</.test(raw)) return parseXmlSubtitle(raw);
    if (raw.includes("WEBVTT")) return parseVtt(raw);
    if (/^\d+\n\d\d:\d\d:\d\d[,\.]\d+ -->/m.test(raw)) return parseSrt(raw);
    return [];
  }

  function parseVtt(raw) {
    return raw
      .split(/\n{2,}/)
      .map((block) => block.split("\n").filter(Boolean))
      .filter((lines) => lines.some((line) => line.includes("-->")))
      .map((lines) => {
        const timingIndex = lines.findIndex((line) => line.includes("-->"));
        return cleanCueText(lines.slice(timingIndex + 1).join(" "));
      })
      .filter(Boolean)
      .map((text, index) => ({ start: index, end: index, text }));
  }

  function parseSrt(raw) {
    return raw
      .split(/\n{2,}/)
      .map((block) => block.split("\n").filter(Boolean))
      .filter((lines) => lines.some((line) => line.includes("-->")))
      .map((lines) => cleanCueText(lines.slice(2).join(" ")))
      .filter(Boolean)
      .map((text, index) => ({ start: index, end: index, text }));
  }

  function parseJsonSubtitle(raw) {
    try {
      const data = JSON.parse(raw);
      return (data.events || [])
        .map((event, index) => ({
          start: (event.tStartMs || 0) / 1000,
          end: ((event.tStartMs || 0) + (event.dDurationMs || 0)) / 1000,
          text: cleanCueText((event.segs || []).map((seg) => seg.utf8 || "").join("")),
          index,
        }))
        .filter((cue) => cue.text);
    } catch (_) {
      return [];
    }
  }

  function parseXmlSubtitle(raw) {
    try {
      const doc = new DOMParser().parseFromString(raw, "text/xml");
      return Array.from(doc.querySelectorAll("text, p"))
        .map((node, index) => ({
          start: Number(node.getAttribute("start") || node.getAttribute("t") || index),
          end: Number(node.getAttribute("dur") || node.getAttribute("d") || index),
          text: cleanCueText(node.textContent || ""),
        }))
        .filter((cue) => cue.text);
    } catch (_) {
      return [];
    }
  }

  function cleanCueText(text) {
    return String(text || "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function dedupeCues(cues) {
    const seen = new Set();
    const out = [];
    for (const cue of cues) {
      const key = cue.text.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(cue);
    }
    return out;
  }

  function rememberVisibleNow() {
    const visible = collectVisibleCaptions();
    for (const cue of visible) {
      const text = cleanCueText(cue.text);
      if (!text) continue;
      const last = state.visibleHistory[state.visibleHistory.length - 1];
      if (last?.text === text) continue;
      state.visibleHistory.push({ ...cue, text, capturedAt: Date.now() });
    }
    state.visibleHistory = state.visibleHistory.slice(-5000);
  }

  function startRecording() {
    state.recording = true;
    rememberVisibleNow();
    clearInterval(state.recorderTimer);
    state.recorderTimer = setInterval(rememberVisibleNow, 350);
    if (!state.observer) {
      state.observer = new MutationObserver(() => {
        if (state.recording) rememberVisibleNow();
      });
      state.observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }
    return collect();
  }

  function stopRecording() {
    state.recording = false;
    clearInterval(state.recorderTimer);
    state.recorderTimer = null;
    rememberVisibleNow();
    return collect();
  }

  function clearRecording() {
    state.visibleHistory = [];
    return collect();
  }

  async function collect(requestId = "") {
    const youtubeCues = await collectYouTubeCaptionTracks();
    const textTrackCues = collectTextTracks();
    const networkCues = state.networkItems.flatMap((item) => item.cues);
    const storedYoutubeCues = state.youtubeItems.flatMap((item) => item.cues);
    const visibleCues = collectVisibleCaptions();
    const recordedCues = state.visibleHistory;
    const cues = dedupeCues([...youtubeCues, ...storedYoutubeCues, ...textTrackCues, ...networkCues, ...recordedCues, ...visibleCues]);
    const title = document.title.replace(/\s+-\s+Dreaming.*$/i, "").trim();
    const youtubeVideoId = findYouTubeVideoId();
    return {
      type: "DS_SUBTITLE_CAPTURE_RESULT",
      requestId,
      title,
      url: location.href,
      youtubeVideoId,
      youtubeUrl: youtubeVideoId ? `https://www.youtube.com/watch?v=${youtubeVideoId}` : "",
      count: cues.length,
      text: cues.map((cue) => cue.text).join("\n"),
      sources: {
        textTracks: textTrackCues.length,
        network: networkCues.length,
        youtube: Math.max(youtubeCues.length, storedYoutubeCues.length),
        recorded: recordedCues.length,
        visible: visibleCues.length,
      },
      recording: state.recording,
    };
  }

  async function collectYouTubeCaptionTracks() {
    const tracks = findYouTubeCaptionTracks();
    const selected = selectCaptionTrack(tracks);
    if (!selected?.baseUrl) return [];
    const url = withCaptionFormat(selected.baseUrl, "vtt");
    try {
      const response = await fetch(url);
      const text = await response.text();
      const cues = parseSubtitleText(text);
      if (cues.length) state.youtubeItems = [{ url, cues }];
      return cues;
    } catch (_) {
    return [];
  }

  function findYouTubeVideoId() {
    const detailId = window.ytInitialPlayerResponse?.videoDetails?.videoId;
    if (detailId) return detailId;
    const locationMatch = location.href.match(/(?:\/embed\/|\/shorts\/|[?&]v=)([\w-]{11})/);
    if (locationMatch) return locationMatch[1];
    for (const iframe of document.querySelectorAll("iframe[src*='youtube']")) {
      const match = iframe.src.match(/(?:\/embed\/|\/shorts\/|[?&]v=)([\w-]{11})/);
      if (match) return match[1];
    }
    return "";
  }
  }

  function findYouTubeCaptionTracks() {
    const responses = [];
    if (window.ytInitialPlayerResponse) responses.push(window.ytInitialPlayerResponse);
    try {
      const playerResponse = window.ytplayer?.config?.args?.player_response;
      if (playerResponse) responses.push(JSON.parse(playerResponse));
    } catch (_) {}
    for (const script of document.scripts) {
      const text = script.textContent || "";
      const marker = "ytInitialPlayerResponse";
      const markerIndex = text.indexOf(marker);
      if (markerIndex === -1) continue;
      const braceIndex = text.indexOf("{", markerIndex);
      if (braceIndex === -1) continue;
      const json = extractBalancedJson(text, braceIndex);
      if (!json) continue;
      try {
        responses.push(JSON.parse(json));
      } catch (_) {}
    }
    return responses.flatMap((response) => response?.captions?.playerCaptionsTracklistRenderer?.captionTracks || []);
  }

  function extractBalancedJson(text, start) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < text.length; i += 1) {
      const char = text[i];
      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === "\"") {
          inString = false;
        }
        continue;
      }
      if (char === "\"") {
        inString = true;
      } else if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) return text.slice(start, i + 1);
      }
    }
    return "";
  }

  function withCaptionFormat(baseUrl, format) {
    try {
      const url = new URL(baseUrl);
      url.searchParams.set("fmt", format);
      return url.toString();
    } catch (_) {
      const join = String(baseUrl || "").includes("?") ? "&" : "?";
      return `${baseUrl}${join}fmt=${format}`;
    }
  }

  function selectCaptionTrack(tracks) {
    return [...tracks].sort((a, b) => captionScore(b) - captionScore(a))[0];
  }

  function captionScore(track) {
    const language = String(track.languageCode || "").toLowerCase();
    const vssId = String(track.vssId || "").toLowerCase();
    const name = JSON.stringify(track.name || {}).toLowerCase();
    return (
      (language.startsWith("es") ? 100 : 0) +
      (vssId.includes(".es") ? 50 : 0) +
      (name.includes("spanish") || name.includes("español") ? 30 : 0) +
      (String(track.kind || "").toLowerCase() === "asr" ? 10 : 0)
    );
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const requestId = event.data?.requestId || "";
    if (event.data?.type === "DS_SUBTITLE_CAPTURE_COLLECT") collect(requestId).then((result) => window.postMessage(result, "*"));
    if (event.data?.type === "DS_SUBTITLE_CAPTURE_START") startRecording().then((result) => window.postMessage({ ...result, requestId }, "*"));
    if (event.data?.type === "DS_SUBTITLE_CAPTURE_STOP") stopRecording().then((result) => window.postMessage({ ...result, requestId }, "*"));
    if (event.data?.type === "DS_SUBTITLE_CAPTURE_CLEAR") clearRecording().then((result) => window.postMessage({ ...result, requestId }, "*"));
  });
})();
