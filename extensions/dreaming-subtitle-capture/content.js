(() => {
  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("injected.js");
  script.onload = () => script.remove();
  (document.documentElement || document.head).appendChild(script);

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.type !== "DS_SUBTITLE_CAPTURE_RESULT") return;
    chrome.runtime.sendMessage(event.data);
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (!String(message?.type || "").startsWith("DS_SUBTITLE_CAPTURE_")) return;
    window.postMessage({ type: message.type, requestId: message.requestId }, "*");
  });
})();
