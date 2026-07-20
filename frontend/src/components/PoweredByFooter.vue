<template>
  <footer class="powered-by-footer">
    <span class="powered-by-footer__text">Powered by</span>
    <a
      href="https://github.com/EeeMt/codify"
      target="_blank"
      rel="noopener noreferrer"
      class="powered-by-footer__link"
    >
      Codify
    </a>
    <span class="powered-by-footer__separator" aria-hidden="true">·</span>
    <span class="powered-by-footer__version">
      {{ shortGitCommit }}
    </span>
  </footer>
</template>

<script setup lang="ts">
const gitCommit = __GIT_COMMIT__
const shortGitCommit = gitCommit === 'unknown' ? gitCommit : gitCommit.slice(0, 7)
</script>

<style scoped>
.powered-by-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 11px;
}

.powered-by-footer__text,
.powered-by-footer__separator {
  color: rgba(15, 23, 42, 0.22);
}

.powered-by-footer__link,
.powered-by-footer__version {
  color: rgba(15, 23, 42, 0.28);
}

.powered-by-footer__link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  transition: color 0.2s ease;
}

.powered-by-footer__link:hover {
  color: rgba(15, 23, 42, 0.45);
}

.powered-by-footer__version {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
</style>
