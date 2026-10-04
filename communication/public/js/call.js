(() => {
  const params = new URLSearchParams(location.search);
  const masterToken = params.get("token");
  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  const subtitleEl = $("subtitle");
  const errorEl = $("error");
  const joinBox = $("join-box");
  const joinBtn = $("join");
  const nameInput = $("name");
  const muteBtn = $("mute");
  const endBtn = $("end");
  const remoteAudio = $("remote-audio");
  const recordingEl = $("recording");
  const timerEl = $("timer");

  let participantToken = null;
  let isOwner = false;
  let call = null;
  let pc = null;
  let localStream = null;
  let remoteStream = null;
  let recorder = null;
  let audioContext = null;
  let mixedDestination = null;
  let sequence = 0;
  let lastSignal = null;
  let pollTimer = null;
  let heartbeatTimer = null;
  let timerStarted = null;
  let timerInterval = null;
  let ending = false;
  let candidateQueue = [];
  const pendingUploads = new Set();

  const rtcConfig = {
    iceServers: [
      { urls: "stun:stun.l.google.com:19302" },
      { urls: "stun:stun.cloudflare.com:3478" }
    ]
  };

  function setStatus(text) { statusEl.textContent = text; }
  function showError(text) { errorEl.textContent = text || ""; }
  function formatDuration(sec) {
    const s = Math.max(0, Math.floor(sec));
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }
  function startTimer() {
    if (timerStarted) return;
    timerStarted = Date.now();
    timerInterval = setInterval(() => timerEl.textContent = formatDuration((Date.now() - timerStarted) / 1000), 250);
  }

  async function api(method, args = {}) {
    const body = new URLSearchParams();
    Object.entries(args).forEach(([k, v]) => {
      if (v !== undefined && v !== null) body.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    });
    const response = await fetch(`/api/method/communication.api.call.${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Frappe-CSRF-Token": window.csrf_token || "" },
      body,
      credentials: "same-origin"
    });
    const data = await response.json();
    if (!response.ok || data.exc) throw new Error(data._server_messages ? data._server_messages : (data.exc_type || "Request failed"));
    return data.message;
  }

  async function loadCall() {
    if (!masterToken) throw new Error("Missing call token");
    call = await api("get_call", { token: masterToken });
    $("title").textContent = `Call with ${call.contact}`;
    if (call.is_owner) {
      isOwner = true;
      participantToken = "owner";
      await joinCall();
    } else {
      joinBox.classList.remove("hidden");
      subtitleEl.textContent = "Enter your name to join the call.";
    }
  }

  async function joinCall() {
    const displayName = nameInput.value.trim() || "Guest";
    const result = await api("join_call", { token: masterToken, display_name: displayName });
    participantToken = result.participant_token;
    isOwner = !!result.is_owner;
    joinBox.classList.add("hidden");
    endBtn.disabled = false;
    muteBtn.disabled = false;
    recordingEl.classList.remove("hidden");
    setStatus("Connecting");
    subtitleEl.textContent = isOwner ? "Waiting for the other participant…" : "Joining…";
    await startMedia();
    await startSignaling();
    await startHeartbeat();
    if (isOwner) await createOffer();
  }

  async function startMedia() {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
    remoteStream = new MediaStream();
    remoteAudio.srcObject = remoteStream;
    try { await remoteAudio.play(); } catch (_) {}
    setupRecorder();
  }

  function setupRecorder() {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    mixedDestination = audioContext.createMediaStreamDestination();
    const localSource = audioContext.createMediaStreamSource(localStream);
    localSource.connect(mixedDestination);
    const remoteSource = audioContext.createMediaStreamSource(remoteStream);
    remoteSource.connect(mixedDestination);
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    const mime = candidates.find(x => MediaRecorder.isTypeSupported(x)) || "";
    recorder = new MediaRecorder(mixedDestination.stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = async (event) => {
      if (!event.data || !event.data.size) return;
      const upload = uploadChunk(event.data);
      pendingUploads.add(upload);
      try { await upload; } finally { pendingUploads.delete(upload); }
    };
    recorder.onerror = (event) => showError(`Recording error: ${event.error?.message || "unknown"}`);
    recorder.start(10000);
  }

  async function uploadChunk(blob) {
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) binary += String.fromCharCode(...bytes.subarray(i, i + step));
    const b64 = btoa(binary);
    try {
      await api("upload_chunk", { token: masterToken, participant_token: participantToken, sequence: sequence++, data: b64, mime_type: blob.type || "audio/webm" });
    } catch (e) {
      console.error("Chunk upload failed", e);
    }
  }

  async function createOffer() {
    pc = makePeerConnection();
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    await api("send_signal", { token: masterToken, participant_token: participantToken, kind: "offer", payload: offer });
  }

  function makePeerConnection() {
    const peer = new RTCPeerConnection(rtcConfig);
    peer.onicecandidate = async (event) => {
      if (event.candidate) {
        try { await api("send_signal", { token: masterToken, participant_token: participantToken, kind: "ice", payload: event.candidate }); } catch (e) { console.error(e); }
      }
    };
    peer.ontrack = (event) => {
      const [stream] = event.streams;
      if (stream) {
        stream.getAudioTracks().forEach(track => remoteStream.addTrack(track));
        remoteAudio.srcObject = remoteStream;
        remoteAudio.play().catch(() => {});
      }
    };
    peer.onconnectionstatechange = async () => {
      const state = peer.connectionState;
      if (state === "connected") { setStatus("Connected"); subtitleEl.textContent = "Audio call is active"; startTimer(); }
      if (state === "failed" || state === "closed") { if (!ending) await finish("connection_failed"); }
      if (state === "disconnected") { setStatus("Reconnecting…"); }
    };
    return peer;
  }

  async function processSignal(signal) {
    if (signal.sender === (isOwner ? "owner" : "guest")) return;
    if (!pc) pc = makePeerConnection();
    if (signal.kind === "offer" && !isOwner) {
      localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
      await pc.setRemoteDescription(new RTCSessionDescription(signal.payload));
      for (const c of candidateQueue) await pc.addIceCandidate(c).catch(() => {});
      candidateQueue = [];
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await api("send_signal", { token: masterToken, participant_token: participantToken, kind: "answer", payload: answer });
    } else if (signal.kind === "answer" && isOwner) {
      await pc.setRemoteDescription(new RTCSessionDescription(signal.payload));
      for (const c of candidateQueue) await pc.addIceCandidate(c).catch(() => {});
      candidateQueue = [];
    } else if (signal.kind === "ice") {
      const candidate = new RTCIceCandidate(signal.payload);
      if (pc.remoteDescription) await pc.addIceCandidate(candidate).catch(() => {});
      else candidateQueue.push(candidate);
    }
  }

  async function startSignaling() {
    pollTimer = setInterval(async () => {
      try {
        const signals = await api("poll_signals", { token: masterToken, participant_token: participantToken, after: lastSignal });
        for (const signal of signals) { lastSignal = signal.id; await processSignal(signal); }
      } catch (e) { console.error("Signaling poll", e); }
    }, 700);
  }

  async function startHeartbeat() {
    heartbeatTimer = setInterval(async () => {
      try { await api("heartbeat", { token: masterToken, participant_token: participantToken }); } catch (e) { console.error("Heartbeat", e); }
    }, 10000);
  }

  async function finish(reason = "normal") {
    if (ending) return;
    ending = true;
    setStatus(reason === "normal" ? "Ending" : "Interrupted");
    clearInterval(pollTimer); clearInterval(heartbeatTimer); clearInterval(timerInterval);
    const duration = timerStarted ? Math.floor((Date.now() - timerStarted) / 1000) : 0;
    let finalData = null;
    if (recorder && recorder.state !== "inactive") {
      await new Promise(resolve => {
        recorder.addEventListener("stop", resolve, { once: true });
        recorder.stop();
      });
      try { await Promise.all(Array.from(pendingUploads)); } catch (_) {}
    }
    try {
      await api("finalize_call", { token: masterToken, participant_token: participantToken, duration_seconds: duration, end_reason: reason, mime_type: recorder?.mimeType || "audio/webm" });
    } catch (e) { console.error("Finalize", e); showError("Call ended, but recording finalization failed. Uploaded chunks may still be available."); }
    try { pc?.close(); } catch (_) {}
    localStream?.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close().catch(() => {});
    muteBtn.disabled = true; endBtn.disabled = true;
    recordingEl.classList.add("hidden");
    subtitleEl.textContent = "Call ended";
    setStatus("Ended");
  }

  muteBtn.onclick = () => {
    const track = localStream?.getAudioTracks()?.[0];
    if (!track) return;
    track.enabled = !track.enabled;
    muteBtn.textContent = track.enabled ? "Mute" : "Unmute";
  };
  endBtn.onclick = () => finish("normal");
  joinBtn.onclick = () => joinCall().catch(e => showError(e.message));

  window.addEventListener("beforeunload", () => {
    try { navigator.sendBeacon?.(`/api/method/communication.api.call.heartbeat?token=${encodeURIComponent(masterToken)}&participant_token=${encodeURIComponent(participantToken || "")}`); } catch (_) {}
  });

  loadCall().catch(e => { setStatus("Unavailable"); showError(e.message); subtitleEl.textContent = "This call link is invalid or has expired."; });
})();
