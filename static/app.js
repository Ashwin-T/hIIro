// ── hIIro Web Client ────────────────────────────────────────────────────────

let ws = null;
let mode = "voice";
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
// Persist device ID across reloads so the server doesn't see duplicates
let deviceId = localStorage.getItem("hiro-device-id");
if (!deviceId) {
  deviceId = `web-${crypto.randomUUID().slice(0, 8)}`;
  localStorage.setItem("hiro-device-id", deviceId);
}

const chat = document.getElementById("chat");
const statusEl = document.getElementById("status");
const msgInput = document.getElementById("msg-input");

// ── WebSocket ───────────────────────────────────────────────────────────────

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  setStatus("connecting");

  ws.onopen = () => {
    setStatus("connected");
    document.getElementById("self-id").textContent = deviceId;
    ws.send(JSON.stringify({
      type: "register",
      device_id: deviceId,
      room: "",
      name: "Web Browser",
      mode: mode,
    }));
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    setStatus("disconnected");
    if (!ws._intentionalClose) {
      setTimeout(connect, 3000);
    }
  };

  ws.onerror = () => {
    ws.close();
  };
}

function setStatus(s) {
  statusEl.textContent = s;
  statusEl.className = `status ${s}`;
}

// ── Message handling ────────────────────────────────────────────────────────

function handleMessage(msg) {
  switch (msg.type) {
    case "registered":
      console.log("Registered as", msg.device_id);
      break;

    case "transcript":
      // Show what was heard (for voice mode)
      addBubble("user", msg.text);
      break;

    case "response":
      removeThinking();
      addBubble("assistant", msg.text);
      break;

    case "audio":
      playAudio(msg.data);
      break;

    case "debug":
      handleDebug(msg.event, msg.data);
      break;

    case "devices":
      updateDeviceList(msg.devices);
      break;

    case "error":
      removeThinking();
      addBubble("assistant", `Error: ${msg.message}`);
      break;

    case "pong":
      break;
  }
}

// ── Chat UI ─────────────────────────────────────────────────────────────────

function addBubble(role, text, meta) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addThinking() {
  const div = document.createElement("div");
  div.className = "bubble assistant thinking";
  div.id = "thinking";
  div.textContent = "Thinking...";
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function removeThinking() {
  const el = document.getElementById("thinking");
  if (el) el.remove();
}

// ── Mode switching ──────────────────────────────────────────────────────────

function setMode(m) {
  mode = m;
  document.getElementById("btn-voice").classList.toggle("active", m === "voice");
  document.getElementById("btn-text").classList.toggle("active", m === "text");
  document.getElementById("voice-input").classList.toggle("hidden", m !== "voice");
  document.getElementById("text-input").classList.toggle("hidden", m !== "text");
  if (m === "text") {
    msgInput.focus();
  }
  // Tell the server so it skips TTS in text mode
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "mode", mode: m }));
  }
}

// ── Text input ──────────────────────────────────────────────────────────────

function sendText() {
  const text = msgInput.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

  addBubble("user", text);
  addThinking();
  ws.send(JSON.stringify({ type: "text", content: text }));
  msgInput.value = "";
  document.getElementById("btn-send").classList.remove("has-text");
}

msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendText();
  }
});

msgInput.addEventListener("input", () => {
  document.getElementById("btn-send").classList.toggle("has-text", msgInput.value.trim().length > 0);
});

// ── Voice input ─────────────────────────────────────────────────────────────

async function startRecording() {
  if (isRecording) return;
  isRecording = true;

  const btn = document.getElementById("btn-mic");
  btn.classList.add("recording");

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      }
    });

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm",
    });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      if (audioChunks.length === 0) return;

      const blob = new Blob(audioChunks, { type: "audio/webm" });
      sendAudio(blob);
    };

    mediaRecorder.start();
  } catch (err) {
    console.error("Mic error:", err);
    isRecording = false;
    btn.classList.remove("recording");
  }
}

function stopRecording() {
  if (!isRecording || !mediaRecorder) return;
  isRecording = false;

  const btn = document.getElementById("btn-mic");
  btn.classList.remove("recording");

  if (mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
}

async function sendAudio(blob) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const buf = await blob.arrayBuffer();
  const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));

  addThinking();
  ws.send(JSON.stringify({
    type: "audio",
    format: "webm-opus",
    data: b64,
  }));
}

// ── Audio playback ──────────────────────────────────────────────────────────

function playAudio(b64Data) {
  const bytes = Uint8Array.from(atob(b64Data), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "audio/wav" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play().catch(err => console.warn("Audio playback failed:", err));
}

// ── Debug panel ─────────────────────────────────────────────────────────────

function toggleDebug() {
  document.getElementById("debug-panel").classList.toggle("hidden");
}

function handleDebug(event, data) {
  switch (event) {
    case "stt_done":
      document.getElementById("lat-stt").textContent = `${data.latency_ms}ms`;
      break;
    case "llm_done":
    case "request_done":
      document.getElementById("lat-llm").textContent = `${data.llm_ms || data.latency_ms}ms`;
      break;
    case "tts_done":
      document.getElementById("lat-tts").textContent = `${data.latency_ms}ms`;
      break;
    case "tool_call":
      addToolEntry(data.name, data.args);
      break;
    case "tool_result":
      updateToolResult(data.name, data.result, data.latency_ms);
      break;
  }
}

function addToolEntry(name, args) {
  const log = document.getElementById("tool-log");
  const div = document.createElement("div");
  div.className = "tool-entry";
  div.id = `tool-${name}`;
  div.innerHTML = `<span class="tool-name">${name}</span> <span class="tool-time">running...</span>`;
  log.prepend(div);
}

function updateToolResult(name, result, ms) {
  const div = document.getElementById(`tool-${name}`);
  if (div) {
    div.querySelector(".tool-time").textContent = `${ms}ms`;
    const res = document.createElement("div");
    res.className = "tool-result";
    res.textContent = result.slice(0, 100);
    div.appendChild(res);
  }
}

function updateDeviceList(devices) {
  const el = document.getElementById("device-list");
  if (!devices.length) {
    el.textContent = "No devices";
    return;
  }
  el.innerHTML = devices.map(d =>
    `<div class="device-item">
      <div class="device-name">${d.name || d.device_id}</div>
      <div class="device-room">${d.room || "no room"} &middot; ${d.device_id}</div>
    </div>`
  ).join("");
}

// ── Keepalive ───────────────────────────────────────────────────────────────

setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 30000);

// ── Clean disconnect on page unload ─────────────────────────────────────────

window.addEventListener("beforeunload", () => {
  if (ws) {
    ws._intentionalClose = true;
    ws.close();
  }
});

// ── Theme ───────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("icon-sun").style.display = theme === "light" ? "block" : "none";
  document.getElementById("icon-moon").style.display = theme === "dark" ? "block" : "none";
}

function toggleTheme() {
  const current = localStorage.getItem("hiro-theme") || "light";
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem("hiro-theme", next);
  applyTheme(next);
}

// Apply saved theme on load (default: light)
applyTheme(localStorage.getItem("hiro-theme") || "light");

// ── Init ────────────────────────────────────────────────────────────────────

connect();
