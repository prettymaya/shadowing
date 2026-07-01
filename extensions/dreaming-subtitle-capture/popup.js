const startButton = document.getElementById("start");
const stopButton = document.getElementById("stop");
const captureButton = document.getElementById("capture");
const clearButton = document.getElementById("clear");
const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");

async function activeDreamingTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.startsWith("https://app.dreaming.com/")) {
    throw new Error("Dreaming video sayfasında değilsin.");
  }
  return tab;
}

async function sendCommand(command) {
  const tab = await activeDreamingTab();
  const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return new Promise(async (resolve, reject) => {
    const results = [];
    const timer = setTimeout(() => {
      chrome.runtime.onMessage.removeListener(listener);
      if (results.length) {
        resolve(mergeResults(results));
      } else {
        reject(new Error("Yanıt gelmedi. Sayfayı yenileyip tekrar dene."));
      }
    }, 4000);

    function listener(message) {
      if (message?.type !== "DS_SUBTITLE_CAPTURE_RESULT") return;
      if (message.requestId !== requestId) return;
      results.push(message);
    }

    chrome.runtime.onMessage.addListener(listener);
    try {
      await chrome.tabs.sendMessage(tab.id, { type: command, requestId }).catch(() => {});
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        func: (type, id) => window.postMessage({ type, requestId: id }, "*"),
        args: [command, requestId],
      });
    } catch (error) {
      clearTimeout(timer);
      chrome.runtime.onMessage.removeListener(listener);
      reject(error);
    }
  });
}

function mergeResults(results) {
  const best = [...results].sort((a, b) => (b.text || "").length - (a.text || "").length)[0] || {};
  const lines = [];
  const seen = new Set();
  for (const result of results) {
    for (const line of String(result.text || "").split("\n")) {
      const text = line.trim();
      const key = text.toLowerCase();
      if (!text || seen.has(key)) continue;
      seen.add(key);
      lines.push(text);
    }
  }
  return {
    ...best,
    youtubeVideoId: results.find((result) => result.youtubeVideoId)?.youtubeVideoId || best.youtubeVideoId || "",
    youtubeUrl: results.find((result) => result.youtubeUrl)?.youtubeUrl || best.youtubeUrl || "",
    count: lines.length,
    text: lines.join("\n"),
    sources: results.reduce((acc, result) => ({
      textTracks: acc.textTracks + (result.sources?.textTracks || 0),
      network: acc.network + (result.sources?.network || 0),
      youtube: acc.youtube + (result.sources?.youtube || 0),
      recorded: acc.recorded + (result.sources?.recorded || 0),
      visible: acc.visible + (result.sources?.visible || 0),
    }), { textTracks: 0, network: 0, youtube: 0, recorded: 0, visible: 0 }),
    recording: results.some((result) => result.recording),
  };
}

async function renderResult(message, copy) {
  outputEl.value = message.text || message.youtubeUrl || "";
  if (copy && message.text) await navigator.clipboard.writeText(message.text);
  const copied = copy && message.text ? " kopyalandı" : "";
  const state = message.recording ? "Kayıt açık." : "Kayıt kapalı.";
  statusEl.textContent = message.text
    ? `${state} ${message.count} satır${copied}. Kaynaklar: YouTube ${message.sources.youtube || 0}, textTrack ${message.sources.textTracks}, network ${message.sources.network}, kayıt ${message.sources.recorded}, görünür ${message.sources.visible}.`
    : message.youtubeUrl
      ? `${state} Subtitle bulunamadı ama YouTube URL bulundu. Bunu yt-dlp scriptiyle deneyebilirsin.`
    : `${state} Subtitle bulunamadı. Altyazıyı açıp video oynarken kayda başla.`;
}

async function run(command, label, copy = false) {
  try {
    statusEl.textContent = label;
    const message = await sendCommand(command);
    await renderResult(message, copy);
  } catch (error) {
    statusEl.textContent = error.message || "Bir hata oldu.";
  }
}

startButton.addEventListener("click", () => run("DS_SUBTITLE_CAPTURE_START", "Kayıt başladı. Videoyu oynat.", false));
stopButton.addEventListener("click", () => run("DS_SUBTITLE_CAPTURE_STOP", "Kayıt durduruluyor...", true));
captureButton.addEventListener("click", () => run("DS_SUBTITLE_CAPTURE_COLLECT", "Altyazı aranıyor...", true));
clearButton.addEventListener("click", () => run("DS_SUBTITLE_CAPTURE_CLEAR", "Kayıt temizleniyor...", false));
