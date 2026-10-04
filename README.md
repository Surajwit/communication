# Communication for Frappe v16

A Frappe v16 app for a simple 1-to-1 browser audio communication thread with WebRTC and browser-side recording.

## MVP
- One `Communication Thread` per `Contact`.
- A thread can contain many standard Frappe `Communication` records.
- `Call Session` stores 1-to-1 browser calls.
- Browser-to-browser audio uses WebRTC; no telephony provider is required.
- Signaling is implemented with authenticated HTTP polling, so no custom Node service is required for the MVP.
- Audio is mixed in the browser with the Web Audio API and recorded with `MediaRecorder`.
- Recording chunks are uploaded while the call is active.
- On a normal end, the browser uploads the final combined recording.
- If the browser disappears, the server heartbeat expires the session and the uploaded chunks remain available as a partial recovery recording.
- Calls create a standard Frappe `Communication` record linked to the thread.

## Important MVP limitation
The server-side recovery path concatenates uploaded MediaRecorder WebM chunks. Browser MediaRecorder implementations generally emit chunks intended to form one continuous recording, but exact container behavior varies by browser. For production-grade crash-proof finalization, add a media-processing worker (for example FFmpeg) to remux/rebuild the final WebM. The app does not require FFmpeg for normal calls.

## Install
From the Frappe bench directory:

```bash
bench get-app /path/to/communication
bench --site site1.local install-app communication
bench --site site1.local migrate
bench --site site1.local clear-cache
```

Or package/host the app in git and use the normal `bench get-app` flow.

## Usage
1. Open a Contact.
2. Save the Contact so its Communication Thread is created.
3. Click **Start Browser Call**.
4. Share the generated join URL with the other participant.
5. Both participants allow microphone access.
6. The call starts when both sides are connected.
7. Recording is on automatically and visibly indicated.
8. End the call normally to finalize the recording and create a Communication record.

## TURN
For users behind restrictive NAT/firewalls, configure TURN in **Communication Settings**. The MVP defaults to public STUN servers. Do not rely on public STUN-only connectivity for production.
