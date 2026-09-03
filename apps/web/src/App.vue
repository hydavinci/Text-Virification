<script setup lang="ts">
import WorkspaceView from './views/WorkspaceView.vue'
</script>

<template>
  <WorkspaceView />
</template>

<style>
@media (prefers-reduced-motion: reduce) {
  #app *,
  #app *::before,
  #app *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    transition-delay: 0ms !important;
    scroll-behavior: auto !important;
  }
}
</style>
