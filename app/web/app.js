const SHOTS = [
  { field: "whole_plant_photo", prompt: "Whole plant" },
  { field: "closeup_photo", prompt: "Affected leaves close-up" },
];

const CARE_TOPICS = [
  { key: "watering", label: "watering routine", required: true },
  { key: "light_location", label: "light and location", required: true },
  { key: "drainage_soil", label: "pot drainage and soil condition", required: true },
  { key: "recent_changes_pests", label: "recent changes or pests", required: true },
];

const PLANT_CLASSES = new Set(["potted plant", "plant", "vase"]);
const STAB_THRESHOLD = 12;
const SHARP_THRESHOLD = 8;
const HOLD_FRAMES = 8;

const els = {
  authGate: document.getElementById("authGate"),
  authForm: document.getElementById("authForm"),
  accessCode: document.getElementById("accessCode"),
  authError: document.getElementById("authError"),
  appShell: document.getElementById("appShell"),
  cam: document.getElementById("cam"),
  work: document.getElementById("work"),
  fallback: document.getElementById("cameraFallback"),
  prompt: document.getElementById("prompt"),
  status: document.getElementById("status"),
  stab: document.getElementById("stab"),
  sharp: document.getElementById("sharp"),
  plant: document.getElementById("plant"),
  thumbs: document.getElementById("thumbs"),
  voiceGuideBtn: document.getElementById("voiceGuideBtn"),
  agentState: document.getElementById("agentState"),
  transcript: document.getElementById("transcript"),
  fallbackRow: document.getElementById("fallbackRow"),
  recordBtn: document.getElementById("recordBtn"),
  result: document.getElementById("result"),
  report: document.getElementById("report"),
  careAudio: document.getElementById("careAudio"),
  actions: document.getElementById("actions"),
  approve: document.getElementById("approve"),
  reject: document.getElementById("reject"),
};

const captured = {};
const careHabitAnswers = {};
let model = null;
let prevGray = null;
let shotIdx = 0;
let goodStreak = 0;
let detectorReady = false;
let mediaRecorder = null;
let audioChunks = [];
let runState = null;
let conversation = null;
let lastUserTranscript = "";
let liveAgentReady = false;
let pendingAutoStopAfterReport = false;
let finalReportMessageSeen = false;
let autoStopTimer = null;
let voiceGuideMode = "idle";
let accessCode = sessionStorage.getItem("plantDoctorAccessCode") || "";
let appStarted = false;

const FINAL_REPORT_STOP_AFTER_SPEECH_MS = 2200;
const FINAL_REPORT_STOP_FALLBACK_MS = 20000;
const SESSION_ID_KEY = "plantDoctorSessionId";

window.captured = captured;

function apiPath(path) {
  const base = String(window.PLANT_DOCTOR_API_URL || "").replace(/\/$/, "");
  return `${base}${path}`;
}

function apiHeaders(headers = {}) {
  const token = String(window.PLANT_DOCTOR_APP_TOKEN || "");
  const merged = { ...headers, "X-Session-Id": sessionId() };
  if (token) merged["X-App-Token"] = token;
  if (accessCode) merged["X-Trial-Code"] = accessCode;
  return merged;
}

async function init() {
  bindAuthForm();
  if (authRequired()) {
    const ok = accessCode ? await verifyAccessCode(accessCode, { quiet: true }) : false;
    if (!ok) {
      showAuthGate();
      return;
    }
  }
  await startApp();
}

function bindAuthForm() {
  if (!els.authForm) return;
  els.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = els.accessCode.value.trim();
    if (!code) return;
    els.authError.textContent = "";
    const ok = await verifyAccessCode(code);
    if (ok) {
      sessionStorage.setItem("plantDoctorAccessCode", code);
      accessCode = code;
      await startApp();
    }
  });
}

async function startApp() {
  if (appStarted) {
    if (els.authGate) els.authGate.hidden = true;
    if (els.appShell) els.appShell.hidden = false;
    return;
  }
  appStarted = true;
  if (els.authGate) els.authGate.hidden = true;
  if (els.appShell) els.appShell.hidden = false;
  const cameraReady = await initCamera();
  if (cameraReady) {
    await initDetector();
  }
  els.voiceGuideBtn.addEventListener("click", toggleVoiceGuide);
  els.recordBtn.addEventListener("click", recordAnswer);
  els.approve.addEventListener("click", () => decide("approve"));
  els.reject.addEventListener("click", () => decide("reject"));
  await refreshVoiceGuideStatus();
  requestAnimationFrame(loop);
}

function showAuthGate(message = "") {
  if (els.appShell) els.appShell.hidden = true;
  if (els.authGate) els.authGate.hidden = false;
  els.status.textContent = "Access code required.";
  if (els.authError) els.authError.textContent = message;
  window.requestAnimationFrame(() => els.accessCode?.focus());
}

function authRequired() {
  return window.PLANT_DOCTOR_AUTH_REQUIRED === true || window.PLANT_DOCTOR_AUTH_REQUIRED === "true";
}

async function verifyAccessCode(code, { quiet = false } = {}) {
  accessCode = code;
  try {
    const response = await fetch(apiPath("/api/auth/check"), { headers: apiHeaders() });
    const result = await response.json();
    if (response.ok && result.ok) return true;
  } catch (_) {
    // Fall through to the user-facing error below.
  }
  accessCode = "";
  sessionStorage.removeItem("plantDoctorAccessCode");
  if (!quiet && els.authError) {
    els.authError.textContent = "That code did not work. Please check it and try again.";
  }
  return false;
}

function handleUnauthorized(response) {
  if (!response || response.status !== 401) return false;
  accessCode = "";
  sessionStorage.removeItem("plantDoctorAccessCode");
  showAuthGate("Access could not be verified. Please enter the trial code again.");
  return true;
}

function sessionId() {
  let id = sessionStorage.getItem(SESSION_ID_KEY);
  if (!id) {
    id = `pd_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(SESSION_ID_KEY, id);
  }
  return id;
}

async function initCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
      audio: false,
    });
    els.cam.srcObject = stream;
    await els.cam.play();
    els.fallback.hidden = true;
    els.status.textContent = "Ready for the voice guide.";
    return true;
  } catch (error) {
    els.fallback.hidden = false;
    els.status.textContent = `Camera error: ${error.message}`;
    return false;
  }
}

async function initDetector() {
  if (!window.cocoSsd) {
    els.status.textContent = "Detector unavailable. Manual capture is available.";
    return;
  }
  try {
    model = await window.cocoSsd.load();
    detectorReady = true;
    els.status.textContent = "Detector ready. Start the voice guide.";
  } catch (error) {
    els.status.textContent = `Detector error: ${error.message}. Manual capture is available.`;
  }
}

async function refreshVoiceGuideStatus() {
  const response = await fetch(apiPath("/api/elevenlabs/session"), { headers: apiHeaders() });
  if (handleUnauthorized(response)) return;
  const session = await response.json();
  liveAgentReady = Boolean(session.enabled);
  if (liveAgentReady) {
    els.agentState.textContent = "ElevenLabs agent ready.";
    if (els.fallbackRow) els.fallbackRow.hidden = true;
    els.recordBtn.disabled = true;
  } else {
    els.agentState.textContent = session.reason || "ElevenLabs agent unavailable.";
    if (els.fallbackRow) els.fallbackRow.hidden = false;
    els.recordBtn.disabled = shotIdx < SHOTS.length;
  }
}

async function toggleVoiceGuide() {
  if (conversation) {
    clearAutoStopTimer();
    await conversation.endSession();
    conversation = null;
    els.voiceGuideBtn.textContent = "Start guide";
    els.agentState.textContent = "Voice guide stopped.";
    return;
  }
  await startVoiceGuide();
}

async function startVoiceGuide() {
  try {
    const sessionResponse = await fetch(apiPath("/api/elevenlabs/session"), { headers: apiHeaders() });
    if (handleUnauthorized(sessionResponse)) return;
    const session = await sessionResponse.json();
    if (!session.enabled) {
      els.agentState.textContent = session.reason || "ElevenLabs agent unavailable.";
      return;
    }

    await navigator.mediaDevices.getUserMedia({ audio: true });
    const { Conversation } = await import("https://esm.sh/@elevenlabs/client?bundle");
    const auth = session.conversation_token
      ? { conversationToken: session.conversation_token, connectionType: "webrtc" }
      : { agentId: session.agent_id, connectionType: "webrtc" };

    conversation = await Conversation.startSession({
      ...auth,
      dynamicVariables: {
        ...(session.dynamic_variables || {}),
        journey_state: JSON.stringify(getJourneyState()),
      },
      clientTools: {
        getPlantDoctorState: async () => getJourneyState(),
        captureWholePlantPhoto: async () => captureShot("whole_plant_photo", "agent"),
        captureCloseupPhoto: async () => captureShot("closeup_photo", "agent"),
        recordCareHabitAnswer: async (params = {}) => recordCareHabitAnswer(params),
        submitPlantDoctorRun: async (params = {}) => submitFromVoiceAgent(params),
      },
      onConnect: ({ conversationId }) => {
        els.voiceGuideBtn.textContent = "Stop guide";
        els.agentState.textContent = `Connected: ${conversationId}`;
      },
      onDisconnect: () => {
        const completed = pendingAutoStopAfterReport || finalReportMessageSeen;
        clearAutoStopTimer();
        pendingAutoStopAfterReport = false;
        finalReportMessageSeen = false;
        voiceGuideMode = "idle";
        conversation = null;
        els.voiceGuideBtn.textContent = "Start guide";
        els.agentState.textContent = completed
          ? "Guide complete. Report is ready on screen."
          : "Voice guide disconnected.";
      },
      onMessage: (message) => {
        const text = message.message || "";
        if (!text) return;
        const role = message.role || message.source || "agent";
        const isUser = String(role).toLowerCase() === "user";
        addTranscript(role, text);
        if (isUser) {
          lastUserTranscript = text;
        }
        if (pendingAutoStopAfterReport && !isUser) {
          finalReportMessageSeen = true;
          clearAutoStopTimer();
          scheduleGuideAutoStop(FINAL_REPORT_STOP_FALLBACK_MS);
        }
      },
      onStatusChange: ({ status }) => {
        els.agentState.textContent = `Voice guide ${status}.`;
      },
      onModeChange: ({ mode }) => {
        voiceGuideMode = mode || "idle";
        els.status.textContent = mode === "speaking" ? "Voice guide is speaking." : "Voice guide is listening.";
        if (finalReportMessageSeen) {
          clearAutoStopTimer();
          scheduleGuideAutoStop(
            mode === "speaking" ? FINAL_REPORT_STOP_FALLBACK_MS : FINAL_REPORT_STOP_AFTER_SPEECH_MS
          );
        }
      },
      onError: (message) => {
        els.agentState.textContent = `Voice guide error: ${message}`;
      },
    });
  } catch (error) {
    els.agentState.textContent = `Voice guide error: ${error.message}`;
  }
}

function scheduleGuideAutoStop(delayMs = 2200) {
  if (!conversation || autoStopTimer) return;
  autoStopTimer = window.setTimeout(async () => {
    autoStopTimer = null;
    if (!conversation) return;
    if (finalReportMessageSeen && voiceGuideMode === "speaking") {
      scheduleGuideAutoStop(FINAL_REPORT_STOP_AFTER_SPEECH_MS);
      return;
    }
    els.agentState.textContent = "Guide complete. Closing voice session.";
    try {
      await conversation.endSession();
    } catch (_) {
      conversation = null;
      els.voiceGuideBtn.textContent = "Start guide";
      els.agentState.textContent = "Guide complete. Report is ready on screen.";
    }
  }, delayMs);
}

function clearAutoStopTimer() {
  if (autoStopTimer) {
    window.clearTimeout(autoStopTimer);
    autoStopTimer = null;
  }
}

function grayscale(ctx, width, height) {
  const { data } = ctx.getImageData(0, 0, width, height);
  const gray = new Float32Array(width * height);
  for (let i = 0; i < gray.length; i += 1) {
    gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }
  return gray;
}

function meanAbsDiff(left, right) {
  let sum = 0;
  for (let i = 0; i < left.length; i += 1) {
    sum += Math.abs(left[i] - right[i]);
  }
  return sum / left.length;
}

function edgeEnergy(gray, width, height) {
  let sum = 0;
  let count = 0;
  for (let y = 1; y < height - 1; y += 2) {
    for (let x = 1; x < width - 1; x += 2) {
      const gx = gray[y * width + x + 1] - gray[y * width + x - 1];
      const gy = gray[(y + 1) * width + x] - gray[(y - 1) * width + x];
      sum += Math.abs(gx) + Math.abs(gy);
      count += 1;
    }
  }
  return count ? sum / count : 0;
}

async function loop() {
  if (shotIdx >= SHOTS.length || !els.cam.videoWidth) {
    requestAnimationFrame(loop);
    return;
  }

  const width = 240;
  const height = 180;
  const ctx = els.work.getContext("2d", { willReadFrequently: true });
  els.work.width = width;
  els.work.height = height;
  ctx.drawImage(els.cam, 0, 0, width, height);
  const gray = grayscale(ctx, width, height);
  const stability = prevGray ? meanAbsDiff(gray, prevGray) : 999;
  const sharpness = edgeEnergy(gray, width, height);
  prevGray = gray;

  let hasPlant = !detectorReady;
  if (detectorReady && model) {
    const predictions = await model.detect(els.cam);
    hasPlant = predictions.some(
      (prediction) => PLANT_CLASSES.has(prediction.class) && prediction.score > 0.45
    );
  }

  els.stab.textContent = stability.toFixed(0);
  els.sharp.textContent = sharpness.toFixed(0);
  els.plant.textContent = hasPlant ? "Yes" : "No";

  const good = hasPlant && stability < STAB_THRESHOLD && sharpness > SHARP_THRESHOLD;
  goodStreak = good ? goodStreak + 1 : 0;
  requestAnimationFrame(loop);
}

async function captureShot(field, mode) {
  if (!field || !els.cam.videoWidth) {
    return { ok: false, reason: "Camera frame is not available." };
  }

  const shot = SHOTS.find((item) => item.field === field);
  if (!shot) return { ok: false, reason: `Unknown shot ${field}.` };

  const canvas = document.createElement("canvas");
  canvas.width = els.cam.videoWidth;
  canvas.height = els.cam.videoHeight;
  canvas.getContext("2d").drawImage(els.cam, 0, 0);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
  captured[field] = blob;
  renderThumb(field, blob, shot.prompt);
  advanceShotPrompt();
  await notifyAgentPhotoCaptured(field, blob, mode);
  return {
    ok: true,
    shot: field,
    captured: Object.keys(captured),
    next_step: nextStepName(),
  };
}

function renderThumb(field, blob, alt) {
  let img = els.thumbs.querySelector(`img[data-field="${field}"]`);
  if (!img) {
    img = document.createElement("img");
    img.dataset.field = field;
    els.thumbs.appendChild(img);
  }
  img.alt = alt;
  img.src = URL.createObjectURL(blob);
}

function advanceShotPrompt() {
  const nextIndex = SHOTS.findIndex((shot) => !captured[shot.field]);
  shotIdx = nextIndex === -1 ? SHOTS.length : nextIndex;
  if (shotIdx < SHOTS.length) {
    els.prompt.textContent = SHOTS[shotIdx].prompt;
  } else {
    els.prompt.textContent = "Photos captured";
    els.recordBtn.disabled = liveAgentReady;
  }
}

async function notifyAgentPhotoCaptured(field, blob, mode) {
  const label = field === "whole_plant_photo" ? "whole plant" : "affected-leaf close-up";
  els.status.textContent = `${label} photo captured.`;
  if (!conversation || mode === "agent") return;
  const text = `${label} photo has been captured. Current state: ${JSON.stringify(getJourneyState())}`;
  try {
    if (conversation.uploadFile && conversation.sendMultimodalMessage) {
      const { fileId } = await conversation.uploadFile(blob);
      conversation.sendMultimodalMessage({ text, fileId });
    } else if (conversation.sendContextualUpdate) {
      conversation.sendContextualUpdate(text);
    }
  } catch (_) {
    if (conversation.sendContextualUpdate) conversation.sendContextualUpdate(text);
  }
}

function nextStepName() {
  if (!captured.whole_plant_photo) return "capture whole plant photo";
  if (!captured.closeup_photo) return "capture affected-leaf close-up photo";
  const nextCareTopic = nextRequiredCareTopic(careHabitAnswers);
  if (nextCareTopic) return `ask care question: ${nextCareTopic.label}`;
  return "submit plant doctor run";
}

function getJourneyState() {
  const nextCareTopic = nextRequiredCareTopic(careHabitAnswers);
  return {
    whole_plant_photo_taken: Boolean(captured.whole_plant_photo),
    closeup_photo_taken: Boolean(captured.closeup_photo),
    captured_fields: Object.keys(captured),
    care_routine_answers: { ...careHabitAnswers },
    answered_care_topics: Object.keys(careHabitAnswers),
    unanswered_required_care_topics: requiredCareTopics()
      .filter((topic) => !careHabitAnswers[topic.key])
      .map((topic) => topic.key),
    optional_care_topics: CARE_TOPICS
      .filter((topic) => !topic.required && !careHabitAnswers[topic.key])
      .map((topic) => topic.key),
    next_unanswered_care_topic: nextCareTopic ? nextCareTopic.key : null,
    next_unanswered_care_topic_label: nextCareTopic ? nextCareTopic.label : null,
    next_step: nextStepName(),
    report_started: Boolean(runState),
  };
}

function requiredCareTopics() {
  return CARE_TOPICS.filter((topic) => topic.required);
}

function nextRequiredCareTopic(answers) {
  return requiredCareTopics().find((topic) => !answers[topic.key]) || null;
}

function normalizeCareTopic(topic) {
  if (!topic) return "";
  const normalized = String(topic).trim().toLowerCase().replace(/[\s-]+/g, "_");
  const matched = CARE_TOPICS.find(
    (item) => item.key === normalized || item.label.toLowerCase().replace(/[\s-]+/g, "_") === normalized
  );
  return matched ? matched.key : normalized;
}

function recordCareHabitAnswer(params = {}) {
  params = params || {};
  const paramAnswers = careHabitAnswersFromParams(params);
  const inferredTopic = CARE_TOPICS.find((item) => paramAnswers[item.key] || params[item.key]);
  const topic = normalizeCareTopic(params.topic || params.care_topic || params.field || params.key || inferredTopic?.key);
  const answerValue = params.answer || params.value || params.response || (inferredTopic ? paramAnswers[inferredTopic.key] || params[inferredTopic.key] : "");
  const answer = String(answerValue || "").trim();
  const knownTopic = CARE_TOPICS.find((item) => item.key === topic);
  const expectedTopic = nextRequiredCareTopic(careHabitAnswers);

  if (!knownTopic) {
    return {
      ok: false,
      reason: "Unknown care topic.",
      accepted_topics: CARE_TOPICS.map((item) => item.key),
      next_unanswered_care_topic: expectedTopic ? expectedTopic.key : null,
    };
  }
  if (!answer) {
    return {
      ok: false,
      reason: "Care answer is empty.",
      topic: knownTopic.key,
      next_unanswered_care_topic: expectedTopic ? expectedTopic.key : null,
    };
  }
  if (
    expectedTopic &&
    knownTopic.required &&
    !careHabitAnswers[knownTopic.key] &&
    knownTopic.key !== expectedTopic.key
  ) {
    return {
      ok: false,
      reason: "Please ask and record the next unanswered care topic first.",
      expected_topic: expectedTopic.key,
      expected_topic_label: expectedTopic.label,
      received_topic: knownTopic.key,
    };
  }

  careHabitAnswers[knownTopic.key] = answer;
  return {
    ok: true,
    topic: knownTopic.key,
    answered_care_topics: Object.keys(careHabitAnswers),
    next_unanswered_care_topic: nextRequiredCareTopic(careHabitAnswers)?.key || null,
    next_step: nextStepName(),
  };
}

async function recordAnswer() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (event) => audioChunks.push(event.data);
  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    const audio = new Blob(audioChunks, { type: "audio/webm" });
    els.recordBtn.textContent = "Diagnosing";
    els.recordBtn.disabled = true;
    await runAgent({ audioBlob: audio, allowDemoData: false });
  };
  mediaRecorder.start();
  els.recordBtn.textContent = "Stop and submit";
  els.status.textContent = "Recording your care habits.";
}

async function submitFromVoiceAgent(params = {}) {
  params = params || {};
  const paramAnswers = careHabitAnswersFromParams(params);
  const mergedCareAnswers = { ...careHabitAnswers, ...paramAnswers };
  Object.assign(careHabitAnswers, paramAnswers);
  const transcript = careHabitTranscriptFromAnswers(mergedCareAnswers, params);
  const missingCareTopic = nextRequiredCareTopic(mergedCareAnswers);
  if (!captured.whole_plant_photo || !captured.closeup_photo) {
    return { ok: false, reason: "Both plant photos must be captured before submitting." };
  }
  if (missingCareTopic) {
    return {
      ok: false,
      reason: "Ask and record the next care-routine answer before submitting.",
      next_unanswered_care_topic: missingCareTopic.key,
      next_unanswered_care_topic_label: missingCareTopic.label,
      next_step: `ask care question: ${missingCareTopic.label}`,
    };
  }
  if (!transcript) {
    return { ok: false, reason: "A care-habits answer is required before submitting." };
  }
  await runAgent({
    transcript,
    careHabitsJson: {
      ...(params || {}),
      care_routine_answers: mergedCareAnswers,
    },
    allowDemoData: false,
  });
  const output = runState.drafted_output || runState.final_output || {};
  if (runState.status === "failed" || output.completed === false) {
    const guidance = failureGuidanceForAgent(output, mergedCareAnswers, transcript);
    return {
      ok: false,
      status: reportStatusForAgent(runState, output),
      reason: guidance.reason,
      failures: guidance.failures,
      next_steps: guidance.nextSteps,
      care_habits_received: guidance.careHabitsReceived,
      photo_evidence_needs_retry: guidance.photoEvidenceNeedsRetry,
      retry_photo_fields: guidance.retryPhotoFields,
      do_not_reask_care_habits: guidance.careHabitsReceived && guidance.photoEvidenceNeedsRetry,
    };
  }
  pendingAutoStopAfterReport = true;
  finalReportMessageSeen = false;
  clearAutoStopTimer();
  return {
    ok: true,
    status: reportStatusForAgent(runState, output),
    report_status: output.care_report?.status || "drafted",
    requires_review: runState.status === "interrupted",
    summary: output.summary,
    report_preview: {
      issue: output.care_report?.issue || output.symptoms?.value || "",
      root_cause: output.care_report?.root_cause || firstCause(output),
      root_cause_explanation: output.care_report?.root_cause_explanation || firstCauseBasis(output),
      care_tips: output.care_report?.care_tips || output.care_plan?.actions || [],
      monitoring: output.care_report?.monitoring || output.care_plan?.monitoring || "",
    },
    final_spoken_summary: finalSpokenSummary(output),
    message: runState.status === "interrupted"
      ? "Plant Doctor drafted an evidence-backed report and it is ready for user review."
      : "Plant Doctor completed the report.",
    end_guide_after_final_message: true,
  };
}

function finalSpokenSummary(output) {
  const report = output.care_report || {};
  const tips = report.care_tips || output.care_plan?.actions || [];
  const topTip = Array.isArray(tips) ? tips[0] : "";
  return [
    report.issue ? `Issue: ${report.issue}` : "",
    report.root_cause ? `Likely root cause: ${report.root_cause}` : "",
    topTip ? `Top care tip: ${topTip}` : "",
    "The detailed report is now displayed on your screen.",
  ].filter(Boolean).join(". ");
}

function reportStatusForAgent(state, output) {
  if (state.status === "interrupted") return output.care_report?.status || "drafted";
  return state.status;
}

function failureGuidanceForAgent(output, careAnswers = {}, transcript = "") {
  const failures = output.care_report?.failures || [];
  const nextSteps = output.care_report?.next_steps || [];
  const photoRetryText = [
    output.summary || "",
    ...nextSteps,
    ...failures.map((failure) => `${failure.field || ""} ${failure.reason || ""}`),
  ].join(" ");
  const careHabitsReceived = Boolean(
    output.care_habits?.value ||
    output.care_habits?.content?.transcript ||
    transcript ||
    Object.keys(careAnswers).length
  );
  const careHabitsFailed = failures.some((failure) =>
    /care[-_ ]?habits|audio|spoken|transcript/i.test(`${failure.field || ""} ${failure.reason || ""}`)
  );
  const photoEvidenceNeedsRetry = /photo|image|vision|whole_plant|close[_ -]?up|capture/i.test(photoRetryText);
  const retryPhotoFields = retryPhotoFieldsFromText(photoRetryText);

  let reason = output.summary || "Plant Doctor could not complete the analysis.";
  if (careHabitsReceived && photoEvidenceNeedsRetry && !careHabitsFailed) {
    reason = "Care routine answers were received. Ask the user to retry only the plant photo evidence listed in retry_photo_fields; do not re-ask care-habits questions.";
  } else if (failures[0]?.reason) {
    reason = failures[0].reason;
  }

  return {
    reason,
    failures,
    nextSteps,
    careHabitsReceived,
    photoEvidenceNeedsRetry,
    retryPhotoFields,
  };
}

function retryPhotoFieldsFromText(text) {
  const fields = new Set();
  if (/whole[_ -]?plant|full[_ -]?plant/i.test(text)) fields.add("whole_plant_photo");
  if (/close[_ -]?up|closeup|affected|leaf|leaves/i.test(text)) fields.add("closeup_photo");
  if (/photo|image|vision|capture/i.test(text) && !fields.size) {
    fields.add("whole_plant_photo");
    fields.add("closeup_photo");
  }
  return Array.from(fields);
}

function careHabitAnswersFromParams(params = {}) {
  params = params || {};
  const source = params.care_routine_answers || params.care_habits || params;
  const answers = {};
  CARE_TOPICS.forEach((topic) => {
    if (source && source[topic.key]) {
      answers[topic.key] = String(source[topic.key]).trim();
    }
  });
  if (!answers.light_location) {
    const lightLocation = [source.light, source.location]
      .filter(Boolean)
      .map((item) => String(item).trim())
      .filter(Boolean)
      .join("; ");
    if (lightLocation) answers.light_location = lightLocation;
  }
  if (!answers.drainage_soil) {
    const drainageSoil = [source.pot_drainage, source.soil]
      .filter(Boolean)
      .map((item) => String(item).trim())
      .filter(Boolean)
      .join("; ");
    if (drainageSoil) answers.drainage_soil = drainageSoil;
  }
  if (!answers.recent_changes_pests) {
    const recent = [source.recent_changes, source.pests_seen, source.pests, source.fertilizer]
      .filter(Boolean)
      .map((item) => String(item).trim())
      .filter(Boolean)
      .join("; ");
    if (recent) answers.recent_changes_pests = recent;
  }
  return answers;
}

function careHabitTranscriptFromAnswers(answers, params = {}) {
  params = params || {};
  const pieces = [];
  CARE_TOPICS.forEach((topic) => {
    if (answers[topic.key]) pieces.push(`${topic.label}: ${answers[topic.key]}`);
  });
  const structuredTranscript = pieces.join("; ");
  const freeformTranscript = params.care_habits_transcript || params.transcript || params.summary || "";
  return structuredTranscript || freeformTranscript || lastUserTranscript || "";
}

async function runAgent({ audioBlob = null, transcript = "", careHabitsJson = {}, allowDemoData = false } = {}) {
  const body = new FormData();
  if (captured.whole_plant_photo) body.append("whole_plant_photo", captured.whole_plant_photo, "whole.jpg");
  if (captured.closeup_photo) body.append("closeup_photo", captured.closeup_photo, "close.jpg");
  if (audioBlob) body.append("care_habits_audio", audioBlob, "answer.webm");
  if (transcript) body.append("care_habits_transcript", transcript);
  body.append("care_habits_json", JSON.stringify(careHabitsJson || {}));
  body.append("allow_demo_data", allowDemoData ? "true" : "false");

  const response = await fetch(apiPath("/api/run"), { method: "POST", headers: apiHeaders(), body });
  if (handleUnauthorized(response)) return;
  runState = await response.json();
  if (!response.ok) {
    showReport(runState.final_output || runState, "Run failed");
    return;
  }
  showReport(runState.drafted_output || runState.final_output, runState.status === "failed" ? "Run failed" : "Drafted report");
}

function showReport(output, title) {
  els.result.hidden = false;
  els.appShell?.classList.remove("report-empty");
  if (els.actions) {
    els.actions.hidden = !runState || runState.status !== "interrupted";
  }
  els.result.querySelector("h2").textContent = reportHeading(output, title);
  renderReport(output);
  window.requestAnimationFrame(() => {
    els.result.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  speakCarePlan(output);
}

function reportHeading(output, fallback) {
  if (!output) return fallback;
  if (output.completed === false) return "Needs more evidence";
  return output.care_report?.title || fallback;
}

function renderReport(output) {
  els.report.replaceChildren();
  if (!output) {
    els.report.appendChild(reportEmptyState("No report is available yet."));
    return;
  }

  const careReport = output.care_report || {};
  const hero = node("section", "report-hero");
  const statusRow = node("div", "report-status-row");
  statusRow.append(
    pill(careReport.status || (output.completed === false ? "incomplete" : "drafted")),
    node("span", "confidence", careReport.confidence_label || confidenceLabel(careReport.confidence))
  );
  hero.append(
    statusRow,
    node("h3", "", careReport.title || "Plant Doctor care report"),
    node("p", "report-summary", output.summary || "Plant Doctor analyzed the submitted plant evidence.")
  );
  els.report.appendChild(hero);

  if (output.completed === false || careReport.status === "incomplete") {
    renderIncompleteReport(output, careReport);
    appendRawReport(output);
    return;
  }

  const overview = node("section", "report-grid");
  overview.append(
    metricCard("Plant", careReport.plant_summary || output.plant?.value || "Plant evidence captured."),
    metricCard("Issue", careReport.issue || output.symptoms?.value || "Visible symptoms were reviewed."),
    metricCard("Likely Root Cause", careReport.root_cause || firstCause(output) || "Care stress")
  );
  els.report.appendChild(overview);

  if (Array.isArray(careReport.sections) && careReport.sections.length) {
    careReport.sections.forEach((section) => {
      const items = Array.isArray(section.items) ? section.items : [section.items];
      appendReportSection(section.title, items);
    });
  } else {
    appendReportSection(
      "Why This Is Happening",
      [careReport.root_cause_explanation || firstCauseBasis(output) || "The diagnosis is based on the captured photos and care-routine answers."]
    );
    appendReportSection("Care Plan", careReport.care_tips || output.care_plan?.actions || []);
    appendReportSection("Monitor Next", [careReport.monitoring || output.care_plan?.monitoring].filter(Boolean));
    appendReportSection("When To Escalate", [careReport.when_to_escalate].filter(Boolean));
    appendReportSection("Care Routine Shared", [careReport.care_routine_summary || output.care_habits?.value].filter(Boolean));
    appendReportSection("Evidence Used", careReport.evidence_summary || evidenceLines(output));
  }
  appendRawReport(output);
}

function renderIncompleteReport(output, careReport) {
  const failures = careReport.failures || [];
  const nextSteps = careReport.next_steps || [];
  appendReportSection(
    "What Is Blocking The Report",
    failures.map((failure) => failure.reason || String(failure)).filter(Boolean)
  );
  appendReportSection("Best Next Step", nextSteps);
  if (output.care_habits?.value) {
    appendReportSection("Care Routine Already Captured", [output.care_habits.value]);
  }
  appendReportSection("Evidence Captured", evidenceLines(output));
}

function appendReportSection(title, items) {
  const cleanItems = (items || []).filter(Boolean);
  if (!cleanItems.length) return;
  const section = node("section", "report-section");
  section.appendChild(node("h4", "", title));
  if (cleanItems.length === 1) {
    section.appendChild(node("p", "", cleanItems[0]));
  } else {
    const list = node("ul", "");
    cleanItems.forEach((item) => list.appendChild(node("li", "", item)));
    section.appendChild(list);
  }
  els.report.appendChild(section);
}

function appendRawReport(output) {
  const details = node("details", "raw-report");
  details.appendChild(node("summary", "", "Evidence JSON"));
  const pre = node("pre", "", JSON.stringify(output, null, 2));
  details.appendChild(pre);
  els.report.appendChild(details);
}

function metricCard(label, value) {
  const card = node("article", "report-card");
  card.append(node("span", "label", label), node("strong", "", value));
  return card;
}

function pill(status) {
  const value = String(status || "drafted");
  return node("span", `pill ${value.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`, value);
}

function node(tag, className = "", text = "") {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== "") el.textContent = String(text);
  return el;
}

function reportEmptyState(text) {
  return node("p", "report-summary", text);
}

function firstCause(output) {
  return output?.diagnosis?.likely_causes?.[0]?.cause || "";
}

function firstCauseBasis(output) {
  return output?.diagnosis?.likely_causes?.[0]?.basis || "";
}

function evidenceLines(output) {
  const lines = [];
  if (output?.plant?.value) lines.push(`Whole plant: ${output.plant.value}`);
  if (output?.symptoms?.value) lines.push(`Close-up: ${output.symptoms.value}`);
  if (output?.care_habits?.value) lines.push(`Care routine: ${output.care_habits.value}`);
  return lines;
}

function confidenceLabel(confidence) {
  const value = Number(confidence || 0);
  if (value >= 0.75) return "High confidence";
  if (value >= 0.55) return "Moderate confidence";
  if (value > 0) return "Low confidence";
  return "Confidence pending";
}

async function speakCarePlan(output) {
  const careReport = output && output.care_report;
  const tips = careReport?.care_tips || output?.care_plan?.actions || [];
  const text = [
    careReport?.root_cause ? `Likely root cause: ${careReport.root_cause}.` : "",
    Array.isArray(tips) ? tips.join(" ") : "",
    careReport?.monitoring || "",
  ].filter(Boolean).join(" ");
  if (!text || output.completed === false) return;

  try {
    const response = await fetch(apiPath("/api/tts"), {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text }),
    });
    if (handleUnauthorized(response)) return;
    const result = await response.json();
    if (result.audio_uri && /^(https?:|\/)/.test(result.audio_uri)) {
      els.careAudio.src = result.audio_uri;
      els.careAudio.hidden = false;
    }
  } catch (_) {
    els.careAudio.hidden = true;
  }
}

async function decide(decision) {
  if (!runState || !runState.thread_id) return;
  const response = await fetch(apiPath("/api/decision"), {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      thread_id: runState.thread_id,
      db_path: runState.db_path,
      decision,
      reviewer: "ui",
      allow_demo_data: false,
    }),
  });
  if (handleUnauthorized(response)) return;
  const final = await response.json();
  showReport(final.final_output, decision === "approve" ? "Approved report" : "Rejected");
  els.status.textContent = `Run ${final.status}.`;
}

function addTranscript(role, text) {
  const entry = document.createElement("p");
  entry.textContent = `${role}: ${text}`;
  els.transcript.appendChild(entry);
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

init().catch((error) => {
  els.status.textContent = error.message;
});
