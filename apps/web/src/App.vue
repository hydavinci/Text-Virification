<script setup lang="ts">
import WorkspaceView from './views/WorkspaceView.vue'
</script>

<template>
  <WorkspaceView />
</template>

<style>
:root {
  color: #172033;
  background: #f4f7fb;
  font-family:
    Inter, "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 50% 0%, rgba(77, 110, 255, 0.1), transparent 32rem),
    #f4f7fb;
}

button,
input {
  font: inherit;
}

:where(a, button, input, select, textarea):focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
