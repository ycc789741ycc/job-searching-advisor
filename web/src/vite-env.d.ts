/// <reference types="vite/client" />

// Runtime configuration lives in src/config.ts, read from window.__APP_CONFIG__.
// There are deliberately no VITE_ variables: inlining configuration at build
// time would mean a different artifact per environment.
