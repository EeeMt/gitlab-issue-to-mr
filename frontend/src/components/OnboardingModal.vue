<template>
  <n-modal :show="show" :mask-closable="false" :close-on-esc="true" @close="emit('close')">
    <n-card class="onboarding-modal" :bordered="false" role="dialog" aria-modal="true">
      <template #header>
        <div class="onboarding-modal__header">
          <div class="onboarding-modal__header-main">
            <span class="onboarding-modal__eyebrow">{{ t('onboarding.progressLabel', { current: activeStep.number, total: steps.length }) }}</span>
            <h2 class="onboarding-modal__title" data-testid="onboarding-step-title">
              {{ t(activeStep.titleKey) }}
            </h2>
            <p class="onboarding-modal__description">
              {{ t(activeStep.descriptionKey) }}
            </p>
          </div>

          <n-button quaternary circle class="onboarding-modal__close" aria-label="Close onboarding" @click="emit('close')">
            <span aria-hidden="true">×</span>
          </n-button>
        </div>

        <n-steps :current="currentStep + 1" size="small" class="onboarding-modal__steps">
          <n-step
            v-for="step in steps"
            :key="step.number"
            :title="t(step.shortTitleKey)"
            :description="t(step.captionKey)"
          />
        </n-steps>
      </template>

      <div class="onboarding-modal__body">
        <template v-if="activeStep.number === 1">
          <div class="onboarding-modal__hero">
            <div class="onboarding-modal__hero-copy">
              <h3 class="onboarding-modal__section-title">{{ t('onboarding.welcome.heading') }}</h3>
              <p class="onboarding-modal__section-text">{{ t('onboarding.welcome.body') }}</p>
            </div>
            <div class="onboarding-modal__summary-card">
              <span class="onboarding-modal__summary-label">{{ t('onboarding.welcome.summaryLabel') }}</span>
              <strong class="onboarding-modal__summary-title">{{ t('onboarding.welcome.summaryTitle') }}</strong>
              <p class="onboarding-modal__summary-text">{{ t('onboarding.welcome.summaryBody') }}</p>
            </div>
          </div>
        </template>

        <template v-else-if="activeStep.number === 2">
          <div class="onboarding-modal__concept-grid">
            <n-thing
              v-for="item in conceptItems"
              :key="item.titleKey"
              class="onboarding-modal__concept-card"
              :title="t(item.titleKey)"
            >
              <p class="onboarding-modal__section-text">{{ t(item.bodyKey) }}</p>
            </n-thing>
          </div>
        </template>

        <template v-else>
          <div class="onboarding-modal__workflow-list">
            <div
              v-for="item in workflowItems"
              :key="item.stepKey"
              class="onboarding-modal__workflow-item"
            >
              <div class="onboarding-modal__workflow-index">{{ t(item.stepKey) }}</div>
              <div>
                <h3 class="onboarding-modal__section-title">{{ t(item.titleKey) }}</h3>
                <p class="onboarding-modal__section-text">{{ t(item.bodyKey) }}</p>
              </div>
            </div>
          </div>
        </template>
      </div>

      <template #action>
        <div class="onboarding-modal__footer">
          <div class="onboarding-modal__footer-start">
            <n-button v-if="!isLastStep" text data-testid="onboarding-skip" @click="emit('close')">
              {{ t('onboarding.actions.skip') }}
            </n-button>
            <n-button v-else text data-testid="onboarding-skip" @click="emit('close')">
              {{ t('onboarding.actions.close') }}
            </n-button>
          </div>

          <div class="onboarding-modal__footer-end">
            <n-button
              v-if="currentStep > 0"
              data-testid="onboarding-previous"
              @click="goToPrevious"
            >
              {{ t('onboarding.actions.previous') }}
            </n-button>

            <template v-if="!isLastStep">
              <n-button type="primary" data-testid="onboarding-next" @click="goToNext">
                {{ t('onboarding.actions.next') }}
              </n-button>
            </template>
            <template v-else>
              <n-button data-testid="onboarding-create-issue" @click="handleCreateIssue">
                {{ t('onboarding.actions.createIssue') }}
              </n-button>
              <n-button type="primary" data-testid="onboarding-view-dashboard" @click="handleViewDashboard">
                {{ t('onboarding.actions.viewDashboard') }}
              </n-button>
            </template>
          </div>
        </div>
      </template>
    </n-card>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCard, NModal, NStep, NSteps, NThing } from 'naive-ui'
import { useI18n } from 'vue-i18n'

interface OnboardingStep {
  number: number
  titleKey: string
  shortTitleKey: string
  captionKey: string
  descriptionKey: string
}

interface OnboardingContentItem {
  stepKey?: string
  titleKey: string
  bodyKey: string
}

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'complete'): void
  (event: 'view-dashboard'): void
  (event: 'create-issue'): void
}>()

const { t } = useI18n()

const currentStep = ref(0)

const steps: OnboardingStep[] = [
  {
    number: 1,
    titleKey: 'onboarding.welcome.title',
    shortTitleKey: 'onboarding.welcome.shortTitle',
    captionKey: 'onboarding.welcome.caption',
    descriptionKey: 'onboarding.welcome.description',
  },
  {
    number: 2,
    titleKey: 'onboarding.concepts.title',
    shortTitleKey: 'onboarding.concepts.shortTitle',
    captionKey: 'onboarding.concepts.caption',
    descriptionKey: 'onboarding.concepts.description',
  },
  {
    number: 3,
    titleKey: 'onboarding.workflow.title',
    shortTitleKey: 'onboarding.workflow.shortTitle',
    captionKey: 'onboarding.workflow.caption',
    descriptionKey: 'onboarding.workflow.description',
  },
]

const conceptItems: OnboardingContentItem[] = [
  {
    titleKey: 'onboarding.concepts.codifyIssue.title',
    bodyKey: 'onboarding.concepts.codifyIssue.body',
  },
  {
    titleKey: 'onboarding.concepts.tasks.title',
    bodyKey: 'onboarding.concepts.tasks.body',
  },
  {
    titleKey: 'onboarding.concepts.results.title',
    bodyKey: 'onboarding.concepts.results.body',
  },
]

const workflowItems: OnboardingContentItem[] = [
  {
    stepKey: 'onboarding.workflow.steps.first.step',
    titleKey: 'onboarding.workflow.steps.first.title',
    bodyKey: 'onboarding.workflow.steps.first.body',
  },
  {
    stepKey: 'onboarding.workflow.steps.second.step',
    titleKey: 'onboarding.workflow.steps.second.title',
    bodyKey: 'onboarding.workflow.steps.second.body',
  },
  {
    stepKey: 'onboarding.workflow.steps.third.step',
    titleKey: 'onboarding.workflow.steps.third.title',
    bodyKey: 'onboarding.workflow.steps.third.body',
  },
]

const activeStep = computed(() => steps[currentStep.value])
const isLastStep = computed(() => currentStep.value === steps.length - 1)

function goToNext() {
  if (currentStep.value < steps.length - 1) {
    currentStep.value += 1
  }
}

function goToPrevious() {
  if (currentStep.value > 0) {
    currentStep.value -= 1
  }
}

function handleViewDashboard() {
  emit('complete')
  emit('view-dashboard')
}

function handleCreateIssue() {
  emit('complete')
  emit('create-issue')
}
</script>

<style scoped>
.onboarding-modal {
  width: min(880px, calc(100vw - 32px));
  border-radius: 24px;
  overflow: hidden;
  background: var(--n-card-color, #fff);
}

.onboarding-modal__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.onboarding-modal__header-main {
  min-width: 0;
}

.onboarding-modal__eyebrow {
  display: inline-flex;
  margin-bottom: 8px;
  color: var(--n-text-color-3, rgba(15, 23, 42, 0.6));
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.onboarding-modal__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__description {
  margin: 12px 0 0;
  font-size: 15px;
  line-height: 1.6;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.75));
  max-width: 60ch;
}

.onboarding-modal__close {
  flex-shrink: 0;
}

.onboarding-modal__steps {
  margin-top: 20px;
}

.onboarding-modal__body {
  padding: 8px 0 4px;
}

.onboarding-modal__hero {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(260px, 1fr);
  gap: 20px;
  align-items: stretch;
}

.onboarding-modal__summary-card,
.onboarding-modal__concept-card,
.onboarding-modal__workflow-item {
  border: 1px solid var(--n-border-color, rgba(148, 163, 184, 0.25));
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(255, 255, 255, 0.98));
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
}

.onboarding-modal__summary-card {
  padding: 20px;
}

.onboarding-modal__summary-label,
.onboarding-modal__workflow-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  height: 40px;
  border-radius: 999px;
  background: rgba(24, 160, 88, 0.12);
  color: var(--n-primary-color, #18a058);
  font-weight: 700;
}

.onboarding-modal__summary-title {
  display: block;
  margin-top: 16px;
  font-size: 18px;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__summary-text {
  margin: 12px 0 0;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.75));
  line-height: 1.6;
}

.onboarding-modal__concept-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.onboarding-modal__concept-card {
  padding: 20px;
}

.onboarding-modal__workflow-list {
  display: grid;
  gap: 16px;
}

.onboarding-modal__workflow-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 16px;
  padding: 18px 20px;
}

.onboarding-modal__section-title {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__section-text {
  margin: 10px 0 0;
  font-size: 15px;
  line-height: 1.6;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.75));
}

.onboarding-modal__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.onboarding-modal__footer-start,
.onboarding-modal__footer-end {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .onboarding-modal {
    width: min(720px, calc(100vw - 24px));
  }

  .onboarding-modal__hero,
  .onboarding-modal__concept-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .onboarding-modal {
    width: calc(100vw - 16px);
  }

  .onboarding-modal__header,
  .onboarding-modal__footer,
  .onboarding-modal__footer-start,
  .onboarding-modal__footer-end {
    flex-direction: column;
    align-items: stretch;
  }

  .onboarding-modal__workflow-item {
    grid-template-columns: 1fr;
  }

  .onboarding-modal__close {
    align-self: flex-end;
  }

  .onboarding-modal__title {
    font-size: 24px;
  }
}
</style>
