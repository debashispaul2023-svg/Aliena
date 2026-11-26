# Architecture

- Modular `jarvis/` package with memory, multi-agent, AI router, resources, voice, desktop, research, productivity, plugins, freelancer.
- Feature 8 desktop layers: engine → permissions/approval/validator → controller → platform adapter.
- Platform adapters: mock (tests), unsupported (fail closed). Future Windows/Linux/macOS drivers plug in without core coupling.
- Generated-code execution remains BLOCKED.
