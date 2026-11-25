# Claude Integration

Grok Part B consumes, and does not modify:

- jarvis/config.py
- jarvis/logger.py
- jarvis/core/**
- jarvis/memory/**
- jarvis/ai/**
- jarvis/dev/**
- jarvis/skills/**

Dependencies needed from Claude:

- memory API for research/productivity notes
- orchestrator task delegation
- provider router for future summaries
- shared config and logging

No contract mismatch was patched by editing Claude files.
