# Plant Doctor Mobile Trial Notes

## Product Flow Principles

- The voice guide owns the journey. The user should only need to tap `Start guide`, grant camera/mic permissions, and follow spoken prompts.
- Ask the required care questions one at a time: watering, light/location, drainage/soil, and recent changes or pests. Recent changes are often the clue that turns a generic report into a useful one.
- Do not ask users to repeat care details that were already captured. If analysis fails because evidence is weak, ask for the specific missing/low-confidence photo again.
- The final answer should be a care brief, not a generic diagnosis: issue, likely root cause, why we think that, what to do today, routine changes, what to monitor, and when to escalate.

## Extra Context Worth Collecting

- Plant identity confidence: common name/species when visible; otherwise say uncertain.
- Symptom timeline: when the issue started and whether it is spreading.
- Watering detail: frequency, amount, whether soil dries between waterings.
- Light/location: window direction or indoor/outdoor position, direct sun exposure.
- Drainage/soil: drainage holes, standing water, soil wetness/compaction.
- Recent changes: repotting, move, fertilizer, pruning, weather/temperature shift.
- Pest check: underside of leaves, sticky residue, webbing, small insects.
- Optional additional photos: soil surface, pot/drainage, underside of affected leaf, wider context near the window.

## Mobile Trial Readiness

- Host over HTTPS; camera and microphone access will not work reliably over plain HTTP on phones.
- Keep the page lightweight and voice-first; avoid controls that compete with the guide.
- Test on iOS Safari and Android Chrome for camera switching, mic permissions, WebRTC audio, and page visibility changes.
- Add visible permission recovery states: camera denied, mic denied, poor network, analysis still running.
- Persist no raw secrets in the browser. Use the server token endpoint for ElevenLabs private sessions.
- Store trial outputs server-side only if users consent; plant photos may include home interiors.
- Add observability for each step: session start, photo captured, care topic recorded, submit result, retry reason, final report shown.
