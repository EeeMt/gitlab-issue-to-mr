<template>
  <section :class="['page-header', rootClass]">
    <div class="page-header__main">
      <div class="page-header__headline">
        <slot name="title">
          <h2 :class="['page-header__title', titleClass]">{{ title }}</h2>
        </slot>
      </div>

      <slot name="subtitle">
        <p v-if="subtitle" :class="['page-header__subtitle', subtitleClass]">
          {{ subtitle }}
        </p>
      </slot>
    </div>

    <div v-if="$slots.actions" :class="['page-header__actions', actionsClass]">
      <slot name="actions" />
    </div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  subtitle?: string
  rootClass?: string
  titleClass?: string
  subtitleClass?: string
  actionsClass?: string
}>()
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--app-page-header-gap, 16px);
}

.page-header__main {
  min-width: 0;
}

.page-header__headline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.page-header__title {
  margin: 0;
  font-size: var(--app-page-title-size, 28px);
  line-height: 1.2;
  color: var(--app-page-title-color, #0f172a);
}

.page-header__subtitle {
  margin: 8px 0 0;
  max-width: var(--app-page-subtitle-max-width, 760px);
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.68));
  line-height: 1.5;
}

.page-header__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 767px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .page-header__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .page-header__title {
    font-size: var(--app-page-title-size-mobile, 24px);
  }
}
</style>
