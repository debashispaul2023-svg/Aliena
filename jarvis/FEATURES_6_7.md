# Features 6 and 7

## Feature 6 — Resource Discovery & Download
Status: PARTIAL

Existing registry, finder, and downloader remain. Added:
- Host blocking for localhost/private IPs
- Safe zip extract that rejects path traversal
- Downloaded files are never executed

## Feature 7 — Voice Intelligence
Status: PARTIAL

Added:
- Voice state machine
- Mock STT/TTS providers
- Pipeline: audio → transcript → reply → audio

Live microphone, live STT, and live TTS were not verified.
