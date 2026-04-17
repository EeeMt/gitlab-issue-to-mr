<template>
  <n-modal :show="show" :mask-closable="false" :close-on-esc="true" @close="emit('close')">
    <div
      ref="shellRef"
      class="onboarding-modal-shell"
      :style="shellStyle"
      @transitionend="handleShellTransitionEnd"
    >
      <div ref="contentRef" class="onboarding-modal-shell__content">
        <n-card
          class="onboarding-modal"
          :bordered="false"
          role="dialog"
          aria-modal="true"
        >
          <div class="onboarding-modal__background" aria-hidden="true">
            <Transition name="onboarding-motif-fade" mode="out-in">
              <div :key="activeStep.number" class="onboarding-modal__background-set">
                <div
                  v-for="motif in activeMotifs"
                  :key="motif.key"
                  :class="['onboarding-modal__motif', motif.className]"
                  data-testid="onboarding-background-motif"
                  aria-hidden="true"
                >
                  <n-icon class="onboarding-modal__motif-icon">
                    <component :is="motif.icon" />
                  </n-icon>
                </div>
              </div>
            </Transition>
          </div>
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

            <n-button quaternary circle class="onboarding-modal__close" :aria-label="t('onboarding.actions.closeOnboarding')" @click="emit('close')">
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
          <Transition name="onboarding-step" mode="out-in" @before-leave="handleBeforeStepLeave" @enter="handleStepEnter">
            <div :key="activeStep.number" class="onboarding-modal__step-content">
              <template v-if="activeStep.number === 1">
                <div class="onboarding-modal__hero">
                  <div class="onboarding-modal__hero-copy">
                    <h3 class="onboarding-modal__section-title">{{ t('onboarding.welcome.heading') }}</h3>
                    <p class="onboarding-modal__section-text">
                      <template v-for="segment in welcomeBodySegments" :key="segment.key">
                        <strong v-if="segment.emphasized" class="onboarding-modal__section-emphasis">{{ segment.text }}</strong>
                        <template v-else>{{ segment.text }}</template>
                      </template>
                    </p>
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
                    class="onboarding-modal__concept-card onboarding-modal__surface"
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
                    class="onboarding-modal__workflow-item onboarding-modal__surface"
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
          </Transition>
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
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NButton, NCard, NIcon, NModal, NStep, NSteps, NThing } from 'naive-ui'
import { SparklesOutline, GitMergeOutline, CalendarClearOutline, DocumentTextOutline, LayersOutline, CheckmarkDoneCircleOutline, PlayCircleOutline } from '@vicons/ionicons5'
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

interface OnboardingMotif {
  key: string
  icon: unknown
  className: string
}

const props = defineProps<{
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
const shellRef = ref<HTMLElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const shellHeight = ref<string | null>(null)
const pendingShellHeight = ref<string | null>(null)

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

const stepMotifs: Record<number, OnboardingMotif[]> = {
  1: [
    {
      key: 'ai',
      icon: SparklesOutline,
      className: 'onboarding-modal__motif--ai',
    },
    {
      key: 'merge',
      icon: GitMergeOutline,
      className: 'onboarding-modal__motif--merge',
    },
    {
      key: 'request',
      icon: DocumentTextOutline,
      className: 'onboarding-modal__motif--request',
    },
  ],
  2: [
    {
      key: 'request',
      icon: DocumentTextOutline,
      className: 'onboarding-modal__motif--request',
    },
    {
      key: 'layers',
      icon: LayersOutline,
      className: 'onboarding-modal__motif--layers',
    },
    {
      key: 'result',
      icon: CheckmarkDoneCircleOutline,
      className: 'onboarding-modal__motif--result',
    },
  ],
  3: [
    {
      key: 'schedule',
      icon: CalendarClearOutline,
      className: 'onboarding-modal__motif--schedule',
    },
    {
      key: 'run',
      icon: PlayCircleOutline,
      className: 'onboarding-modal__motif--run',
    },
    {
      key: 'merge',
      icon: GitMergeOutline,
      className: 'onboarding-modal__motif--merge',
    },
  ],
}

const activeStep = computed(() => steps[currentStep.value])
const activeMotifs = computed(() => stepMotifs[activeStep.value.number] ?? [])
const welcomeBodySegments = computed(() => {
  const template = t('onboarding.welcome.body')
  const replacements = {
    scheduling: t('onboarding.welcome.bodyScheduling'),
    code: t('onboarding.welcome.bodyCode'),
    mr: t('onboarding.welcome.bodyMr'),
  }

  return template.split(/(\[\[scheduling\]\]|\[\[code\]\]|\[\[mr\]\])/g)
    .filter(Boolean)
    .map((segment, index) => {
      const match = segment.match(/^\[\[(scheduling|code|mr)\]\]$/)
      if (!match) {
        return {
          key: `text-${index}`,
          text: segment,
          emphasized: false,
        }
      }

      return {
        key: `${match[1]}-${index}`,
        text: replacements[match[1] as keyof typeof replacements],
        emphasized: true,
      }
    })
})
const isLastStep = computed(() => currentStep.value === steps.length - 1)
const shellStyle = computed(() => (
  shellHeight.value ? { height: shellHeight.value } : undefined
))

async function measureContentHeight() {
  await nextTick()
  return contentRef.value?.scrollHeight ?? 0
}

async function initializeShellHeight() {
  const height = await measureContentHeight()
  shellHeight.value = height > 0 ? `${height}px` : null
  pendingShellHeight.value = null
}

function animateShellHeight(stepUpdater: () => void) {
  const fromHeight = shellRef.value?.offsetHeight ?? 0

  if (fromHeight > 0) {
    shellHeight.value = `${fromHeight}px`
    void shellRef.value?.offsetHeight
  }

  pendingShellHeight.value = null
  stepUpdater()
}

watch(
  () => props.show,
  async (isVisible, wasVisible) => {
    if (isVisible && !wasVisible) {
      currentStep.value = 0
      await initializeShellHeight()
    }
  },
)

function handleBeforeStepLeave() {
  const height = shellRef.value?.offsetHeight ?? 0
  if (height > 0) {
    shellHeight.value = `${height}px`
  }
}

function handleStepEnter() {
  requestAnimationFrame(async () => {
    const height = await measureContentHeight()
    const nextHeight = height > 0 ? `${height}px` : null
    pendingShellHeight.value = nextHeight

    if (pendingShellHeight.value === nextHeight) {
      shellHeight.value = nextHeight
    }
  })
}

function handleShellTransitionEnd(event: TransitionEvent) {
  if (event.target !== shellRef.value || event.propertyName !== 'height') {
    return
  }

  shellHeight.value = null
  pendingShellHeight.value = null
}

function goToNext() {
  if (currentStep.value < steps.length - 1) {
    animateShellHeight(() => {
      currentStep.value += 1
    })
  }
}

function goToPrevious() {
  if (currentStep.value > 0) {
    animateShellHeight(() => {
      currentStep.value -= 1
    })
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
.onboarding-modal-shell {
  width: min(880px, calc(100vw - 32px));
  overflow: hidden;
  transition: height 220ms ease;
}

.onboarding-modal-shell__content {
  width: 100%;
}

.onboarding-modal {
  position: relative;
  isolation: isolate;
  width: 100%;
  border-radius: 24px;
  overflow: hidden;
  background: var(--n-card-color, #fff);
}

.onboarding-modal > :deep(.n-card-header),
.onboarding-modal > :deep(.n-card__content),
.onboarding-modal > :deep(.n-card__action) {
  position: relative;
  z-index: 1;
}

.onboarding-modal__background {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.onboarding-modal__background-set {
  position: absolute;
  inset: 0;
}

.onboarding-motif-fade-enter-active,
.onboarding-motif-fade-leave-active {
  transition: opacity 280ms ease;
}

.onboarding-motif-fade-enter-from,
.onboarding-motif-fade-leave-to {
  opacity: 0;
}

.onboarding-motif-fade-enter-to,
.onboarding-motif-fade-leave-from {
  opacity: 1;
}

.onboarding-modal__motif {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  color: color-mix(in srgb, var(--n-primary-color, #18a058) 34%, transparent);
  opacity: 0.11;
  filter: saturate(0.9);
  transform: translateZ(0);
}
.onboarding-modal__motif-icon {
  width: 100%;
  height: 100%;
  font-size: inherit;
}

.onboarding-modal__motif-icon :deep(svg) {
  width: 100%;
  height: 100%;
}

.onboarding-modal__motif--ai {
  top: -54px;
  right: -36px;
  width: clamp(220px, 30vw, 320px);
  height: clamp(220px, 30vw, 320px);
  transform: rotate(-10deg);
}

.onboarding-modal__motif--merge {
  top: 34%;
  left: -92px;
  width: clamp(230px, 32vw, 330px);
  height: clamp(230px, 32vw, 330px);
  opacity: 0.085;
  color: color-mix(in srgb, var(--n-text-color-3, #64748b) 40%, transparent);
  transform: translateY(-50%) rotate(-18deg);
}

.onboarding-modal__motif--request {
  top: 12%;
  right: 14%;
  width: clamp(210px, 28vw, 300px);
  height: clamp(210px, 28vw, 300px);
  opacity: 0.08;
  color: color-mix(in srgb, var(--n-primary-color, #18a058) 24%, transparent);
  transform: rotate(14deg);
}

.onboarding-modal__motif--layers {
  top: 30%;
  left: -70px;
  width: clamp(220px, 30vw, 320px);
  height: clamp(220px, 30vw, 320px);
  opacity: 0.08;
  color: color-mix(in srgb, var(--n-text-color-3, #64748b) 46%, transparent);
  transform: translateY(-50%) rotate(-10deg);
}

.onboarding-modal__motif--result {
  right: 6%;
  bottom: -108px;
  width: clamp(230px, 31vw, 330px);
  height: clamp(230px, 31vw, 330px);
  opacity: 0.072;
  color: color-mix(in srgb, var(--n-primary-color, #18a058) 34%, transparent);
  transform: rotate(8deg);
}

.onboarding-modal__motif--run {
  top: 10%;
  right: -34px;
  width: clamp(220px, 29vw, 310px);
  height: clamp(220px, 29vw, 310px);
  opacity: 0.09;
  color: color-mix(in srgb, var(--n-primary-color, #18a058) 30%, transparent);
  transform: rotate(-8deg);
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
  margin-bottom: 6px;
  color: var(--n-text-color-3, rgba(15, 23, 42, 0.56));
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.onboarding-modal__title {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
  font-weight: 600;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__description {
  margin: 10px 0 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.7));
  max-width: 60ch;
}

.onboarding-modal__close {
  flex-shrink: 0;
}

.onboarding-modal__steps {
  margin-top: 18px;
}

.onboarding-modal__body {
  padding: 8px 0 4px;
}

.onboarding-modal__step-content {
  min-height: 100%;
}

.onboarding-step-enter-active,
.onboarding-step-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.onboarding-step-enter-from,
.onboarding-step-leave-to {
  opacity: 0;
  transform: translateX(10px);
}

.onboarding-step-enter-to,
.onboarding-step-leave-from {
  opacity: 1;
  transform: translateX(0);
}

.onboarding-modal__hero {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(260px, 1fr);
  gap: 20px;
  align-items: stretch;
  
}

.onboarding-modal__hero-copy {
  padding: 20px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.onboarding-modal__summary-card,
.onboarding-modal__concept-card,
.onboarding-modal__workflow-item {
  border: 1px solid var(--n-border-color, rgba(148, 163, 184, 0.25));
  border-radius: 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
}

.onboarding-modal__surface {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.78), rgba(255, 255, 255, 0.62));
  backdrop-filter: blur(14px);
}

.onboarding-modal__summary-card {
  padding: 20px;
}

.onboarding-modal__summary-label,
.onboarding-modal__workflow-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(24, 160, 88, 0.12);
  color: var(--n-primary-color, #18a058);
  font-size: 14px;
  font-weight: 600;
}

.onboarding-modal__summary-title {
  display: block;
  margin-top: 14px;
  font-size: 16px;
  font-weight: 600;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__summary-text {
  margin: 10px 0 0;
  font-size: 14px;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.72));
  line-height: 1.55;
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
  font-size: 16px;
  line-height: 1.35;
  font-weight: 600;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__section-text {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--n-text-color-2, rgba(15, 23, 42, 0.72));
}

.onboarding-modal__section-emphasis,
.onboarding-modal__summary-text strong {
  font-weight: 700;
  color: var(--n-text-color-1, #0f172a);
}

.onboarding-modal__section-text :deep(u),
.onboarding-modal__summary-text :deep(u) {
  text-decoration-thickness: 1.5px;
  text-underline-offset: 0.16em;
  text-decoration-color: rgba(24, 160, 88, 0.45);
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
  .onboarding-modal-shell {
    width: min(720px, calc(100vw - 24px));
  }

  .onboarding-modal__hero,
  .onboarding-modal__concept-grid {
    grid-template-columns: 1fr;
  }

  .onboarding-modal__motif--ai {
    right: -56px;
    width: 220px;
    height: 220px;
  }

  .onboarding-modal__motif--merge {
    left: -82px;
    width: 220px;
    height: 220px;
  }

  .onboarding-modal__motif--schedule {
    right: -12px;
    bottom: -108px;
    width: 240px;
    height: 240px;
  }
}

@media (max-width: 640px) {
  .onboarding-modal-shell {
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
    font-size: 22px;
  }

  .onboarding-modal__motif--ai {
    top: -36px;
    right: -72px;
    width: 180px;
    height: 180px;
  }

  .onboarding-modal__motif--merge {
    top: 44%;
    left: -86px;
    width: 180px;
    height: 180px;
  }

  .onboarding-modal__motif--schedule {
    right: -36px;
    bottom: -84px;
    width: 200px;
    height: 200px;
  }
}
</style>

