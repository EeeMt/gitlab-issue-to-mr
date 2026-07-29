<template>
  <div class="config-layout__main skill-settings">
    <n-card class="config-form-card skill-settings__catalog" :bordered="false">
      <template #header>
        <div class="skill-settings__catalog-header">
          <div class="skill-settings__catalog-title-row">
            <div class="config-card-header__title">{{ t('config.skills.title') }}</div>
            <n-button
              size="small"
              type="primary"
              :disabled="saving || detailLoading"
              data-testid="skill-create-button"
              @click="requestStartCreate"
            >
              <template #icon><n-icon :component="AddOutline" /></template>
              {{ t('config.skills.create') }}
            </n-button>
          </div>
          <div class="config-card-header__subtitle">{{ t('config.skills.subtitle') }}</div>
        </div>
      </template>

      <div class="skill-settings__catalog-summary">
        <n-tag size="small" round :bordered="false">
          {{ t('config.skills.totalCount', { count: skills.length }) }}
        </n-tag>
        <n-tag size="small" round type="success" :bordered="false">
          {{ t('config.skills.enabledCount', { count: enabledSkillCount }) }}
        </n-tag>
      </div>

      <n-input
        v-model:value="searchQuery"
        class="skill-settings__search"
        data-testid="skill-search-input"
        size="small"
        clearable
        :placeholder="t('config.skills.searchPlaceholder')"
      >
        <template #prefix><n-icon :component="SearchOutline" /></template>
      </n-input>

      <n-spin :show="loading" size="small">
        <div class="skill-settings__list">
          <div
            v-if="creating"
            class="skill-settings__item skill-settings__item--draft skill-settings__item--active"
            role="status"
          >
            <span class="skill-settings__item-icon">
              <n-icon :component="AddOutline" :size="18" />
            </span>
            <span class="skill-settings__item-content">
              <span class="skill-settings__item-title">
                <strong>{{ t('config.skills.createTitle') }}</strong>
                <n-tag size="tiny" type="info" :bordered="false">
                  {{ t('config.skills.draft') }}
                </n-tag>
              </span>
              <small>{{ t('config.skills.newSkillHint') }}</small>
            </span>
          </div>

          <div v-if="!loading && skills.length === 0" class="config-empty skill-settings__empty">
            <span class="skill-settings__empty-icon">
              <n-icon :component="SparklesOutline" :size="22" />
            </span>
            <strong>{{ t('config.skills.emptyTitle') }}</strong>
            <span>{{ t('config.skills.empty') }}</span>
          </div>
          <div
            v-else-if="!loading && filteredSkills.length === 0"
            class="config-empty skill-settings__empty"
          >
            <strong>{{ t('config.skills.noSearchResults') }}</strong>
            <span>{{ t('config.skills.noSearchResultsHint') }}</span>
          </div>

          <button
            v-for="skill in filteredSkills"
            :key="skill.id"
            type="button"
            class="skill-settings__item"
            :class="{ 'skill-settings__item--active': !creating && skill.id === selectedId }"
            :aria-current="!creating && skill.id === selectedId ? 'true' : undefined"
            :disabled="saving || detailLoading"
            :data-testid="`skill-list-item-${skill.id}`"
            @click="requestSelectSkill(skill)"
          >
            <span class="skill-settings__item-icon-slot" aria-hidden="true">
              <span
                class="skill-settings__status-dot"
                :class="{ 'skill-settings__status-dot--disabled': !skill.enabled }"
              />
            </span>
            <span class="skill-settings__item-content">
              <span class="skill-settings__item-title">
                <n-ellipsis
                  class="skill-settings__item-name"
                  :data-testid="`skill-name-${skill.id}`"
                  :tooltip="{
                    placement: 'top-start',
                    showArrow: false,
                    contentStyle: {
                      maxWidth: '320px',
                      fontSize: '12px',
                      overflowWrap: 'anywhere',
                    },
                  }"
                >
                  {{ skill.name }}
                  <template #tooltip>{{ skill.name }}</template>
                </n-ellipsis>
                <n-tag
                  size="tiny"
                  round
                  :type="skill.enabled ? 'success' : 'default'"
                  :bordered="false"
                >
                  {{ skill.enabled ? t('common.enabled') : t('common.disabled') }}
                </n-tag>
              </span>
              <small>{{ skill.description }}</small>
            </span>
          </button>
        </div>
      </n-spin>
    </n-card>

    <n-spin :show="detailLoading">
      <n-card class="config-form-card skill-settings__editor" :bordered="false">
        <template #header>
          <div class="config-card-header skill-settings__editor-header">
            <div>
              <div class="skill-settings__eyebrow">
                {{ creating ? t('config.skills.createMode') : t('config.skills.editMode') }}
              </div>
              <div class="config-card-header__title">
                {{ creating ? t('config.skills.createTitle') : draft.name || t('config.skills.editTitle') }}
              </div>
              <div class="config-card-header__subtitle">
                {{ t('config.skills.editorHint') }}
              </div>
            </div>
            <n-tag
              size="small"
              round
              :type="draft.enabled ? 'success' : 'default'"
              :bordered="false"
            >
              {{ draft.enabled ? t('common.enabled') : t('common.disabled') }}
            </n-tag>
          </div>
        </template>

        <n-form :disabled="saving || detailLoading" label-placement="top" class="skill-settings__form">
          <section class="skill-settings__section">
            <div class="skill-settings__section-header">
              <div>
                <div class="skill-settings__section-title">{{ t('config.skills.basicInfo') }}</div>
                <div class="skill-settings__section-hint">{{ t('config.skills.basicInfoHint') }}</div>
              </div>
            </div>
            <div class="skill-settings__basic-grid">
              <n-form-item :label="t('config.skills.name')" required>
                <n-input
                  v-model:value="draft.name"
                  data-testid="skill-name-input"
                  maxlength="64"
                  :placeholder="t('config.skills.namePlaceholder')"
                />
                <template #feedback>{{ t('config.skills.nameHint') }}</template>
              </n-form-item>
              <n-form-item
                class="skill-settings__availability"
                :label="t('config.skills.enabled')"
              >
                <div class="skill-settings__availability-control">
                  <n-switch
                    v-model:value="draft.enabled"
                    :aria-label="t('config.skills.enabled')"
                  />
                  <span>{{ draft.enabled ? t('common.enabled') : t('common.disabled') }}</span>
                </div>
                <template #feedback>{{ t('config.skills.enabledHint') }}</template>
              </n-form-item>
            </div>
          </section>

          <section class="skill-settings__section">
            <div class="skill-settings__section-header">
              <div>
                <div class="skill-settings__section-title">
                  <n-icon :component="DocumentTextOutline" />
                  {{ t('config.skills.skillMarkdown') }}
                </div>
                <div class="skill-settings__section-hint">{{ t('config.skills.skillMarkdownHint') }}</div>
              </div>
              <n-tag size="small" :bordered="false">SKILL.md</n-tag>
            </div>
            <n-form-item :show-label="false">
              <n-input
                v-model:value="draft.skill_md"
                data-testid="skill-markdown-input"
                type="textarea"
                :autosize="{ minRows: 16, maxRows: 28 }"
                maxlength="100000"
                show-count
                :placeholder="t('config.skills.skillMarkdownPlaceholder')"
                class="skill-settings__instructions"
              />
            </n-form-item>
          </section>

          <section class="skill-settings__section">
            <div class="skill-settings__section-header skill-settings__section-header--files">
              <div>
                <div class="skill-settings__section-title">
                  <n-icon :component="FolderOpenOutline" />
                  {{ t('config.skills.supportingFiles') }}
                </div>
                <div class="skill-settings__section-hint">{{ t('config.skills.supportingFilesHint') }}</div>
              </div>
              <n-space :size="8" wrap>
                <n-button size="small" secondary :disabled="saving" @click="fileInput?.click()">
                  <template #icon><n-icon :component="DocumentAttachOutline" /></template>
                  {{ t('config.skills.addFiles') }}
                </n-button>
                <n-button size="small" secondary :disabled="saving" @click="chooseFolder">
                  <template #icon><n-icon :component="FolderOpenOutline" /></template>
                  {{ t('config.skills.addFolder') }}
                </n-button>
              </n-space>
            </div>
            <input
              ref="fileInput"
              class="skill-settings__native-input"
              type="file"
              multiple
              @change="addSelectedFiles"
            />
            <input
              ref="folderInput"
              class="skill-settings__native-input"
              type="file"
              multiple
              @change="addSelectedFiles"
            />

            <div class="skill-settings__package-summary">
              <span>{{ t('config.skills.directoryCount', { count: directoryCount }) }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ t('config.skills.fileCount', { count: draft.files.length }) }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ t('config.skills.packageSize', { size: formatFileSize(packageSize) }) }}</span>
            </div>

            <div class="skill-settings__files">
              <div v-if="draft.files.length === 0" class="config-empty skill-settings__file-empty">
                <span class="skill-settings__empty-icon">
                  <n-icon :component="FolderOpenOutline" :size="20" />
                </span>
                <span>{{ t('config.skills.noSupportingFiles') }}</span>
              </div>
              <div
                v-for="(file, index) in draft.files"
                :key="file.clientId"
                class="skill-settings__file"
              >
                <span class="skill-settings__file-icon">
                  <n-icon :component="DocumentOutline" :size="18" />
                </span>
                <div class="skill-settings__file-path">
                  <n-input
                    v-model:value="file.path"
                    size="small"
                    :status="filePathErrors.has(index) ? 'error' : undefined"
                    :placeholder="t('config.skills.filePathPlaceholder')"
                  />
                  <small
                    v-if="filePathErrors.has(index)"
                    class="skill-settings__file-path-error"
                    :data-testid="`skill-file-path-error-${index}`"
                  >
                    {{ filePathErrorMessage(index) }}
                  </small>
                </div>
                <n-tag size="small" :bordered="false">
                  {{ formatFileSize(decodedSize(file.content_base64)) }}
                </n-tag>
                <label class="skill-settings__executable">
                  <n-switch v-model:value="file.executable" size="small" />
                  <span>{{ t('config.skills.executable') }}</span>
                </label>
                <n-button
                  size="small"
                  quaternary
                  type="error"
                  :disabled="saving"
                  :aria-label="t('config.skills.removeFile')"
                  @click="draft.files.splice(index, 1)"
                >
                  <template #icon><n-icon :component="TrashOutline" /></template>
                </n-button>
              </div>
            </div>
          </section>
        </n-form>

        <div class="config-card-actions skill-settings__actions">
          <n-space v-if="selectedSkill && !creating" :size="8" wrap>
            <n-button
              secondary
              data-testid="skill-download-button"
              :loading="downloading"
              :disabled="saving || downloading || detailLoading || isDirty"
              :title="isDirty ? t('config.skills.downloadSaveFirst') : undefined"
              @click="downloadPackage"
            >
              <template #icon><n-icon :component="DownloadOutline" /></template>
              {{ t('config.skills.download') }}
            </n-button>
            <n-popconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="remove"
            >
              <template #trigger>
                <n-button
                  type="error"
                  secondary
                  :loading="saving"
                  :disabled="saving || downloading || detailLoading"
                >
                  <template #icon><n-icon :component="TrashOutline" /></template>
                  {{ t('config.skills.delete') }}
                </n-button>
              </template>
              {{ t('config.skills.deleteConfirm', { name: selectedSkill.name }) }}
            </n-popconfirm>
          </n-space>
          <span v-else />

          <div class="skill-settings__action-main">
            <span
              class="skill-settings__save-state"
              :class="{ 'skill-settings__save-state--dirty': isDirty }"
            >
              <span class="skill-settings__save-dot" />
              {{ isDirty ? t('config.unsavedChanges') : t('config.skills.noUnsavedChanges') }}
            </span>
            <n-space :size="8" wrap>
              <n-button
                data-testid="skill-reset-button"
                :disabled="!isDirty || saving || detailLoading"
                @click="resetDraft"
              >
                {{ t('config.skills.reset') }}
              </n-button>
              <n-button
                type="primary"
                data-testid="skill-save-button"
                :loading="saving"
                :disabled="!canSave"
                @click="save"
              >
                {{ creating ? t('config.skills.create') : t('config.saveChanges') }}
              </n-button>
            </n-space>
          </div>
        </div>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NEllipsis,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NPopconfirm,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave } from 'vue-router'
import {
  AddOutline,
  DocumentAttachOutline,
  DocumentOutline,
  DocumentTextOutline,
  DownloadOutline,
  FolderOpenOutline,
  SearchOutline,
  SparklesOutline,
  TrashOutline,
} from '@vicons/ionicons5'

import {
  createSkill,
  deleteSkill,
  downloadSkill,
  getAdminSkill,
  getAdminSkills,
  updateSkill,
  type Skill,
  type SkillFile,
  type SkillSummary,
} from '../../api'
import {
  countSkillDirectories,
  getSkillFilePathErrors,
  type SkillFilePathError,
} from './skillPackagePaths'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const saving = ref(false)
const downloading = ref(false)
const detailLoading = ref(false)
const skills = ref<SkillSummary[]>([])
const searchQuery = ref('')
const selectedId = ref<number | null>(null)
const creating = ref(true)
const loadedSkill = ref<Skill | null>(null)
const savedDraftSnapshot = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
let detailRequestToken = 0
const EMPTY_SKILL_MD = '---\nname: \ndescription: \n---\n\n'
const SKILL_NAME_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/
type SkillFileDraft = SkillFile & { clientId: number }
let nextSkillFileClientId = 0
const draft = reactive({
  name: '',
  skill_md: EMPTY_SKILL_MD,
  files: [] as SkillFileDraft[],
  enabled: true,
})

const selectedSkill = computed(
  () => skills.value.find(skill => skill.id === selectedId.value) ?? null,
)
const enabledSkillCount = computed(() => skills.value.filter(skill => skill.enabled).length)
const filteredSkills = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return skills.value
  return skills.value.filter(skill =>
    skill.name.toLocaleLowerCase().includes(query)
    || skill.description.toLocaleLowerCase().includes(query),
  )
})
const packageSize = computed(
  () => encodedSize(draft.skill_md) + draft.files.reduce(
    (total, file) => total + decodedSize(file.content_base64),
    0,
  ),
)
const filePathErrors = computed(
  () => getSkillFilePathErrors(draft.files.map(file => file.path)),
)
const directoryCount = computed(
  () => countSkillDirectories(draft.files.map(file => file.path)),
)
const isDirty = computed(() => serializeDraft() !== savedDraftSnapshot.value)
const canSave = computed(
  () => {
    return Boolean(
      draft.name.trim()
      && draft.skill_md.trim()
      && filePathErrors.value.size === 0
      && packageSize.value <= 8 * 1024 * 1024
    ) && isDirty.value && !saving.value && !detailLoading.value
  },
)

function serializeDraft() {
  return JSON.stringify({
    name: draft.name,
    skill_md: draft.skill_md,
    files: draft.files.map(file => ({
      path: file.path,
      content_base64: file.content_base64,
      executable: file.executable,
    })),
    enabled: draft.enabled,
  })
}

function packagePayload() {
  return {
    name: draft.name.trim(),
    skill_md: draft.skill_md,
    files: draft.files.map(file => ({
      path: file.path.trim(),
      content_base64: file.content_base64,
      executable: file.executable,
    })),
  }
}

function createSkillFileDraft(file: SkillFile): SkillFileDraft {
  return { ...file, clientId: nextSkillFileClientId++ }
}

function setDraft(skill?: Skill) {
  draft.name = skill?.name ?? ''
  draft.skill_md = skill?.skill_md ?? EMPTY_SKILL_MD
  draft.files = (skill?.files ?? []).map(createSkillFileDraft)
  draft.enabled = skill?.enabled ?? true
  loadedSkill.value = skill ? { ...skill, files: skill.files.map(file => ({ ...file })) } : null
  savedDraftSnapshot.value = serializeDraft()
}

async function selectSkill(skill: SkillSummary) {
  const requestToken = ++detailRequestToken
  detailLoading.value = true
  try {
    const detail = await getAdminSkill(skill.id)
    if (requestToken === detailRequestToken) {
      creating.value = false
      selectedId.value = skill.id
      setDraft(detail)
    }
  } catch {
    if (requestToken === detailRequestToken) message.error(t('config.loadError'))
  } finally {
    if (requestToken === detailRequestToken) detailLoading.value = false
  }
}

function confirmDiscard(action: () => void) {
  if (!isDirty.value) {
    action()
    return
  }
  dialog.warning({
    title: t('config.skills.discardTitle'),
    content: t('config.skills.discardHint'),
    positiveText: t('config.skills.discard'),
    negativeText: t('common.cancel'),
    onPositiveClick: action,
  })
}

function requestSelectSkill(skill: SkillSummary) {
  if (saving.value || detailLoading.value) return
  if (!creating.value && selectedId.value === skill.id) return
  confirmDiscard(() => void selectSkill(skill))
}

function requestStartCreate() {
  if (saving.value || detailLoading.value) return
  if (creating.value && !isDirty.value) return
  confirmDiscard(startCreate)
}

function startCreate() {
  detailRequestToken += 1
  detailLoading.value = false
  creating.value = true
  selectedId.value = null
  setDraft()
}

function resetDraft() {
  setDraft(loadedSkill.value ?? undefined)
}

function upsertSkillSummary(skill: Skill) {
  const summary: SkillSummary = {
    id: skill.id,
    name: skill.name,
    description: skill.description,
    enabled: skill.enabled,
    created_at: skill.created_at,
    updated_at: skill.updated_at,
  }
  const existingIndex = skills.value.findIndex(item => item.id === skill.id)
  if (existingIndex >= 0) skills.value.splice(existingIndex, 1, summary)
  else skills.value.push(summary)
  skills.value.sort((left, right) => left.name.localeCompare(right.name))
}

async function load(refreshSelection = true) {
  loading.value = true
  try {
    skills.value = await getAdminSkills()
    if (selectedId.value !== null) {
      const refreshed = skills.value.find(skill => skill.id === selectedId.value)
      if (refreshed) {
        if (refreshSelection) await selectSkill(refreshed)
      } else startCreate()
    }
  } catch {
    message.error(t('config.loadError'))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  try {
    const nextPackage = packagePayload()
    const packageChanged = !loadedSkill.value || JSON.stringify(nextPackage) !== JSON.stringify({
      name: loadedSkill.value.name,
      skill_md: loadedSkill.value.skill_md,
      files: loadedSkill.value.files.map(file => ({
        path: file.path,
        content_base64: file.content_base64,
        executable: file.executable,
      })),
    })
    const saved = creating.value
      ? await createSkill({ ...nextPackage, enabled: draft.enabled })
      : await updateSkill(
          selectedId.value as number,
          packageChanged ? { ...nextPackage, enabled: draft.enabled } : { enabled: draft.enabled },
        )
    searchQuery.value = ''
    upsertSkillSummary(saved)
    creating.value = false
    selectedId.value = saved.id
    setDraft(saved)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    saving.value = false
  }
}

function decodedSize(contentBase64: string): number {
  if (!contentBase64) return 0
  const padding = contentBase64.endsWith('==') ? 2 : contentBase64.endsWith('=') ? 1 : 0
  return Math.max(0, Math.floor(contentBase64.length * 3 / 4) - padding)
}

function encodedSize(value: string): number {
  return new TextEncoder().encode(value).length
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

function filePathErrorMessage(index: number): string {
  const error = filePathErrors.value.get(index)
  if (!error) return ''
  const keys: Record<SkillFilePathError, string> = {
    blank: 'config.skills.filePathBlank',
    tooLong: 'config.skills.filePathTooLong',
    invalid: 'config.skills.filePathInvalid',
    reserved: 'config.skills.skillMdManaged',
    duplicate: 'config.skills.filePathDuplicate',
    fileDirectoryConflict: 'config.skills.filePathConflict',
  }
  return t(keys[error], { max: 240, path: draft.files[index]?.path ?? '' })
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error)
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string' || !result.includes(',')) {
        reject(new Error('Could not encode file'))
        return
      }
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.readAsDataURL(file)
  })
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error)
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('Could not read SKILL.md'))
        return
      }
      resolve(reader.result)
    }
    reader.readAsText(file)
  })
}

async function skillNameFromMarkdown(markdown: string): Promise<string | null> {
  const frontmatter = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1]
  if (!frontmatter) return null
  try {
    const { parse } = await import('yaml')
    const parsed = parse(frontmatter, { version: '1.1' })
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const rawName = (parsed as Record<string, unknown>).name
    if (typeof rawName !== 'string') return null
    const name = rawName.trim()
    return SKILL_NAME_PATTERN.test(name) ? name : null
  } catch {
    return null
  }
}

function chooseFolder() {
  if (!folderInput.value) return
  folderInput.value.setAttribute('webkitdirectory', '')
  folderInput.value.click()
}

async function addSelectedFiles(event: Event) {
  const input = event.target as HTMLInputElement
  if (saving.value) {
    input.value = ''
    return
  }
  const selected = Array.from(input.files ?? [])
  input.value = ''
  if (selected.length === 0) return

  const uploadedPaths = selected.map(
    file => (file.webkitRelativePath || file.name).replace(/^\.\/+/, ''),
  )
  const firstRoot = uploadedPaths[0]?.split('/')[0]
  const importsCompletePackage = Boolean(
    firstRoot
    && uploadedPaths.includes(`${firstRoot}/SKILL.md`)
    && uploadedPaths.every(path => path.startsWith(`${firstRoot}/`)),
  )

  try {
    let nextSkillMarkdown = draft.skill_md
    let nextName = draft.name
    const previousFilesByPath = new Map(draft.files.map(file => [file.path, file]))
    const nextFiles: SkillFileDraft[] = importsCompletePackage
      ? []
      : draft.files.map(file => ({ ...file }))
    for (let index = 0; index < selected.length; index += 1) {
      const file = selected[index]
      if (file.size > 2 * 1024 * 1024) {
        throw new Error(t('config.skills.fileTooLarge', { name: file.name }))
      }
      const uploadedPath = uploadedPaths[index]
      const path = importsCompletePackage
        ? uploadedPath.slice((firstRoot?.length ?? 0) + 1)
        : uploadedPath
      if (path === 'SKILL.md') {
        const skillMarkdown = await readFileAsText(file)
        if (skillMarkdown.length > 100_000) {
          throw new Error(t('config.skills.skillMarkdownTooLarge'))
        }
        nextSkillMarkdown = skillMarkdown
        nextName = (await skillNameFromMarkdown(nextSkillMarkdown)) ?? nextName
        continue
      }
      if (path.startsWith('SKILL.md/')) {
        throw new Error(t('config.skills.skillMdManaged'))
      }
      const contentBase64 = await readFileAsBase64(file)
      const existingIndex = nextFiles.findIndex(item => item.path === path)
      const existingFile = existingIndex >= 0
        ? nextFiles[existingIndex]
        : previousFilesByPath.get(path)
      const entry: SkillFileDraft = {
        path,
        content_base64: contentBase64,
        executable: existingFile?.executable
          ?? (
            path.startsWith('scripts/')
            || path.startsWith('bin/')
            || /\.(?:sh|bash|zsh)$/.test(path)
          ),
        clientId: existingFile?.clientId ?? nextSkillFileClientId++,
      }
      if (existingIndex >= 0) nextFiles.splice(existingIndex, 1, entry)
      else nextFiles.push(entry)
    }
    const totalBytes = encodedSize(nextSkillMarkdown) + nextFiles.reduce(
      (total, file) => total + decodedSize(file.content_base64),
      0,
    )
    if (nextFiles.length > 128) throw new Error(t('config.skills.tooManyFiles'))
    if (totalBytes > 8 * 1024 * 1024) throw new Error(t('config.skills.packageTooLarge'))
    draft.skill_md = nextSkillMarkdown
    draft.name = nextName
    draft.files = nextFiles.sort((left, right) => left.path.localeCompare(right.path))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('config.skills.fileReadFailed'))
  }
}

async function downloadPackage() {
  if (!selectedSkill.value || creating.value) return
  const skillId = selectedSkill.value.id
  const archiveName = `${selectedSkill.value.name}.zip`
  downloading.value = true
  try {
    const blob = await downloadSkill(skillId)
    const url = URL.createObjectURL(blob)
    try {
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = archiveName
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } finally {
      URL.revokeObjectURL(url)
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.skills.downloadFailed'))
  } finally {
    downloading.value = false
  }
}

async function remove() {
  if (!selectedSkill.value) return
  const skillId = selectedSkill.value.id
  saving.value = true
  try {
    await deleteSkill(skillId)
    skills.value = skills.value.filter(skill => skill.id !== skillId)
    startCreate()
    message.success(t('config.skills.deleted'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.skills.deleteFailed'))
  } finally {
    saving.value = false
  }
}

function confirmDiscardNavigation(): boolean | Promise<boolean> {
  if (saving.value) return false
  if (!isDirty.value) return true
  return new Promise((resolve) => {
    let settled = false
    const finish = (allowNavigation: boolean) => {
      if (settled) return
      settled = true
      resolve(allowNavigation)
    }
    dialog.warning({
      title: t('config.skills.discardTitle'),
      content: t('config.skills.discardHint'),
      positiveText: t('config.skills.discard'),
      negativeText: t('common.cancel'),
      onPositiveClick: () => finish(true),
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
    })
  })
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!isDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(confirmDiscardNavigation)
defineExpose({ hasUnsavedChanges: () => isDirty.value })
setDraft()
onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  void load()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<style scoped>
.skill-settings {
  display: grid;
  grid-template-columns: minmax(250px, 300px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.skill-settings__catalog {
  position: sticky;
  top: 16px;
  min-width: 0;
}

.skill-settings__catalog :deep(.n-card__content) {
  display: grid;
  gap: 12px;
}

.skill-settings__catalog-header {
  display: grid;
}

.skill-settings__catalog-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.skill-settings__catalog-summary,
.skill-settings__item-title,
.skill-settings__section-header,
.skill-settings__package-summary,
.skill-settings__actions,
.skill-settings__action-main,
.skill-settings__availability-control,
.skill-settings__file,
.skill-settings__executable {
  display: flex;
  align-items: center;
}

.skill-settings__catalog-summary {
  flex-wrap: wrap;
  gap: 6px;
}

.skill-settings__search {
  width: 100%;
  margin: 4px 0 6px;
}

.skill-settings__list {
  display: grid;
  max-height: min(62vh, 620px);
  gap: 6px;
  overflow-y: auto;
  padding: 2px;
  scrollbar-width: thin;
}

.skill-settings__item-title {
  justify-content: space-between;
  gap: 6px;
}

.skill-settings__item small {
  display: block;
  overflow: hidden;
  color: rgba(15, 23, 42, 0.55);
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-settings__item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 11px 12px;
  text-align: left;
  cursor: pointer;
  color: #0f172a;
  background: rgba(248, 250, 252, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  transition: border-color 0.16s ease, background-color 0.16s ease, box-shadow 0.16s ease;
}

.skill-settings__item:not(:disabled):hover {
  border-color: rgba(24, 160, 88, 0.28);
  background: rgba(248, 250, 252, 0.98);
}

.skill-settings__item:disabled {
  cursor: wait;
  opacity: 0.62;
}

.skill-settings__item:focus-visible {
  outline: 2px solid rgba(24, 160, 88, 0.28);
  outline-offset: 2px;
}

.skill-settings__item--active {
  border-color: rgba(24, 160, 88, 0.42);
  background: linear-gradient(135deg, rgba(24, 160, 88, 0.1), rgba(240, 253, 244, 0.56));
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.05);
}

.skill-settings__item--draft {
  cursor: default;
}

.skill-settings__item-icon,
.skill-settings__empty-icon,
.skill-settings__file-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #18a058;
  background: rgba(24, 160, 88, 0.1);
}

.skill-settings__item-icon {
  width: 28px;
  height: 28px;
  border-radius: 9px;
}

.skill-settings__item-icon-slot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
}

.skill-settings__item-content {
  min-width: 0;
  flex: 1;
}

.skill-settings__item-title :deep(.n-tooltip) {
  display: contents;
}

.skill-settings__item-title strong,
.skill-settings__item-name {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-settings__item-name {
  display: block;
  flex: 1;
}

.skill-settings__status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: #18a058;
  box-shadow: 0 0 0 4px rgba(24, 160, 88, 0.1);
}

.skill-settings__status-dot--disabled {
  background: #94a3b8;
  box-shadow: 0 0 0 4px rgba(148, 163, 184, 0.12);
}

.skill-settings__empty {
  display: grid;
  place-items: center;
  gap: 5px;
  padding: 22px 16px;
  font-size: 12px;
}

.skill-settings__empty strong {
  color: rgba(15, 23, 42, 0.72);
  font-size: 13px;
}

.skill-settings__empty-icon {
  width: 34px;
  height: 34px;
  margin-bottom: 2px;
  border-radius: 11px;
}

.skill-settings__editor {
  min-width: 0;
}

.skill-settings__editor-header {
  align-items: center;
}

.skill-settings__eyebrow {
  margin-bottom: 5px;
  color: #18a058;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  line-height: 1;
  text-transform: uppercase;
}

.skill-settings__form {
  display: grid;
}

.skill-settings__section {
  display: grid;
  gap: 14px;
  padding: 8px 0 24px;
}

.skill-settings__section + .skill-settings__section {
  padding-top: 24px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.skill-settings__section:last-child {
  padding-bottom: 0;
}

.skill-settings__section-header {
  justify-content: space-between;
  gap: 16px;
}

.skill-settings__section-header > div:first-child {
  min-width: 0;
}

.skill-settings__section-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 650;
}

.skill-settings__section-title .n-icon {
  color: #18a058;
}

.skill-settings__section-hint {
  max-width: 760px;
  margin-top: 4px;
  color: rgba(15, 23, 42, 0.54);
  font-size: 12px;
  line-height: 1.55;
}

.skill-settings__basic-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(230px, 0.42fr);
  gap: 16px;
  align-items: stretch;
}

.skill-settings__basic-grid :deep(.n-form-item) {
  margin-bottom: 0;
}

.skill-settings__availability {
  min-width: 0;
}

.skill-settings__availability-control {
  gap: 8px;
  min-height: 34px;
}

.skill-settings__availability-control span {
  color: rgba(15, 23, 42, 0.52);
  font-size: 12px;
}

.skill-settings__section :deep(.n-form-item) {
  margin-bottom: 0;
}

.skill-settings__instructions :deep(textarea) {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
  font-size: 12px;
  line-height: 1.6;
}

.skill-settings__files {
  display: grid;
  width: 100%;
  gap: 8px;
}

.skill-settings__native-input {
  display: none;
}

.skill-settings__package-summary {
  justify-content: flex-end;
  gap: 7px;
  margin-top: -5px;
  color: rgba(15, 23, 42, 0.48);
  font-size: 11px;
}

.skill-settings__file {
  gap: 8px;
  padding: 9px 10px;
  background: rgba(248, 250, 252, 0.78);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
}

.skill-settings__file-icon {
  width: 28px;
  height: 28px;
  color: #64748b;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
}

.skill-settings__file-path {
  min-width: 160px;
  flex: 1;
  display: grid;
  gap: 4px;
}

.skill-settings__file-path :deep(.n-input) {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}

.skill-settings__file-path-error {
  color: #d03050;
  font-size: 11px;
  line-height: 1.4;
}

.skill-settings__executable {
  gap: 6px;
  color: rgba(15, 23, 42, 0.62);
  font-size: 12px;
  white-space: nowrap;
}

.skill-settings__file-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 72px;
  padding: 14px;
  text-align: left;
}

.skill-settings__actions {
  position: sticky;
  z-index: 2;
  bottom: 0;
  justify-content: space-between;
  gap: 16px;
  margin: 24px -24px -24px;
  padding: 14px 24px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.04);
  backdrop-filter: blur(12px);
}

.skill-settings__action-main {
  justify-content: flex-end;
  gap: 16px;
}

.skill-settings__save-state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: rgba(15, 23, 42, 0.48);
  font-size: 12px;
  white-space: nowrap;
}

.skill-settings__save-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #94a3b8;
}

.skill-settings__save-state--dirty {
  color: #b45309;
}

.skill-settings__save-state--dirty .skill-settings__save-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.12);
}

@media (max-width: 960px) {
  .skill-settings {
    grid-template-columns: minmax(0, 1fr);
  }

  .skill-settings__catalog {
    position: static;
  }

  .skill-settings__list {
    max-height: 320px;
  }
}

@media (max-width: 767px) {
  .skill-settings__editor-header,
  .skill-settings__section-header--files,
  .skill-settings__file {
    align-items: stretch;
    flex-direction: column;
  }

  .skill-settings__section-header--files :deep(.n-space),
  .skill-settings__section-header--files :deep(.n-button) {
    width: 100%;
  }

  .skill-settings__basic-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .skill-settings__file-icon {
    display: none;
  }

  .skill-settings__actions,
  .skill-settings__action-main {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .skill-settings__actions {
    margin-right: -16px;
    margin-left: -16px;
    padding-right: 16px;
    padding-left: 16px;
  }

  .skill-settings__action-main {
    gap: 10px;
  }

  .skill-settings__save-state {
    justify-content: center;
  }

  .skill-settings__action-main :deep(.n-space),
  .skill-settings__action-main :deep(.n-button) {
    width: 100%;
  }
}
</style>
