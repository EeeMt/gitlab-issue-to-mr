<template>
  <n-spin :show="loading || detailLoading">
    <div class="skill-settings">
      <aside class="skill-settings__list">
        <div class="skill-settings__list-header">
          <div>
            <strong>{{ t('config.skills.title') }}</strong>
            <small>{{ t('config.skills.subtitle') }}</small>
          </div>
          <n-button size="small" type="primary" @click="startCreate">
            {{ t('config.skills.create') }}
          </n-button>
        </div>
        <div v-if="skills.length === 0" class="config-empty">
          {{ t('config.skills.empty') }}
        </div>
        <button
          v-for="skill in skills"
          :key="skill.id"
          type="button"
          class="skill-settings__item"
          :class="{ 'skill-settings__item--active': !creating && skill.id === selectedId }"
          @click="selectSkill(skill)"
        >
          <span class="skill-settings__item-title">
            <strong>{{ skill.name }}</strong>
            <n-tag
              size="small"
              :type="skill.enabled ? 'success' : 'warning'"
              :bordered="false"
            >
              {{ skill.enabled ? t('common.enabled') : t('common.disabled') }}
            </n-tag>
          </span>
          <small>{{ skill.description }}</small>
        </button>
      </aside>

      <n-card class="config-form-card skill-settings__editor" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">
                {{ creating ? t('config.skills.createTitle') : t('config.skills.editTitle') }}
              </div>
              <div class="config-card-header__subtitle">
                {{ t('config.skills.editorHint') }}
              </div>
            </div>
          </div>
        </template>

        <n-form label-placement="top">
          <n-form-item :label="t('config.skills.name')">
            <n-input
              v-model:value="draft.name"
              maxlength="64"
              :placeholder="t('config.skills.namePlaceholder')"
            />
          </n-form-item>
          <n-form-item :label="t('config.skills.skillMarkdown')">
            <n-input
              v-model:value="draft.skill_md"
              type="textarea"
              :autosize="{ minRows: 14, maxRows: 28 }"
              maxlength="100000"
              show-count
              :placeholder="t('config.skills.skillMarkdownPlaceholder')"
              class="skill-settings__instructions"
            />
            <template #feedback>{{ t('config.skills.skillMarkdownHint') }}</template>
          </n-form-item>
          <n-form-item :label="t('config.skills.supportingFiles')">
            <div class="skill-settings__files">
              <div class="skill-settings__file-toolbar">
                <small>{{ t('config.skills.supportingFilesHint') }}</small>
                <n-space :size="8" wrap>
                  <n-button size="small" secondary @click="fileInput?.click()">
                    {{ t('config.skills.addFiles') }}
                  </n-button>
                  <n-button size="small" secondary @click="chooseFolder">
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
              <div v-if="draft.files.length === 0" class="config-empty skill-settings__file-empty">
                {{ t('config.skills.noSupportingFiles') }}
              </div>
              <div
                v-for="(file, index) in draft.files"
                :key="`${index}-${file.path}`"
                class="skill-settings__file"
              >
                <n-input
                  v-model:value="file.path"
                  size="small"
                  :placeholder="t('config.skills.filePathPlaceholder')"
                />
                <n-tag size="small" :bordered="false">
                  {{ formatFileSize(decodedSize(file.content_base64)) }}
                </n-tag>
                <label class="skill-settings__executable">
                  <n-switch v-model:value="file.executable" size="small" />
                  <span>{{ t('config.skills.executable') }}</span>
                </label>
                <n-button size="small" quaternary type="error" @click="draft.files.splice(index, 1)">
                  {{ t('config.skills.removeFile') }}
                </n-button>
              </div>
            </div>
          </n-form-item>
          <n-form-item :label="t('config.skills.enabled')">
            <n-switch v-model:value="draft.enabled" />
          </n-form-item>
        </n-form>

        <div class="config-card-actions skill-settings__actions">
          <n-space :size="10" wrap>
            <n-button type="primary" :loading="saving" :disabled="!canSave" @click="save">
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              v-if="selectedSkill && !creating"
              secondary
              :loading="saving"
              @click="toggleEnabled"
            >
              {{ selectedSkill.enabled
                ? t('config.skills.disable')
                : t('config.skills.enable') }}
            </n-button>
            <n-button
              v-if="selectedSkill && !creating"
              type="error"
              secondary
              :loading="saving"
              @click="remove"
            >
              {{ t('config.skills.delete') }}
            </n-button>
          </n-space>
        </div>
      </n-card>
    </div>
  </n-spin>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'

import {
  createSkill,
  deleteSkill,
  getAdminSkill,
  getAdminSkills,
  setSkillEnabled,
  updateSkill,
  type Skill,
  type SkillFile,
  type SkillSummary,
} from '../../api'

const { t } = useI18n()
const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const detailLoading = ref(false)
const skills = ref<SkillSummary[]>([])
const selectedId = ref<number | null>(null)
const creating = ref(true)
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
let detailRequestToken = 0
const EMPTY_SKILL_MD = '---\nname: \ndescription: \n---\n\n'
const draft = reactive({
  name: '',
  skill_md: EMPTY_SKILL_MD,
  files: [] as SkillFile[],
  enabled: true,
})

const selectedSkill = computed(
  () => skills.value.find(skill => skill.id === selectedId.value) ?? null,
)
const canSave = computed(
  () => {
    const paths = draft.files.map(file => file.path.trim())
    const packageSize = encodedSize(draft.skill_md) + draft.files.reduce(
      (total, file) => total + decodedSize(file.content_base64),
      0,
    )
    return Boolean(
      draft.name.trim()
      && draft.skill_md.trim()
      && paths.every(path => path && path !== 'SKILL.md' && !path.startsWith('SKILL.md/'))
      && new Set(paths).size === paths.length
      && packageSize <= 8 * 1024 * 1024
    ) && !saving.value
  },
)

function setDraft(skill?: Skill) {
  draft.name = skill?.name ?? ''
  draft.skill_md = skill?.skill_md ?? EMPTY_SKILL_MD
  draft.files = (skill?.files ?? []).map(file => ({ ...file }))
  draft.enabled = skill?.enabled ?? true
}

async function selectSkill(skill: SkillSummary) {
  const requestToken = ++detailRequestToken
  creating.value = false
  selectedId.value = skill.id
  setDraft()
  detailLoading.value = true
  try {
    const detail = await getAdminSkill(skill.id)
    if (requestToken === detailRequestToken && selectedId.value === skill.id) {
      setDraft(detail)
    }
  } catch {
    if (requestToken === detailRequestToken) message.error(t('config.loadError'))
  } finally {
    if (requestToken === detailRequestToken) detailLoading.value = false
  }
}

function startCreate() {
  detailRequestToken += 1
  detailLoading.value = false
  creating.value = true
  selectedId.value = null
  setDraft()
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
    const payload = {
      name: draft.name.trim(),
      skill_md: draft.skill_md,
      files: draft.files.map(file => ({ ...file, path: file.path.trim() })),
      enabled: draft.enabled,
    }
    const saved = creating.value
      ? await createSkill(payload)
      : await updateSkill(selectedId.value as number, payload)
    await load(false)
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

async function toggleEnabled() {
  if (!selectedSkill.value) return
  saving.value = true
  try {
    const updated = await setSkillEnabled(selectedSkill.value.id, !selectedSkill.value.enabled)
    await load(false)
    const refreshed = skills.value.find(skill => skill.id === updated.id)
    if (refreshed) await selectSkill(refreshed)
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

function skillNameFromMarkdown(markdown: string): string | null {
  const frontmatter = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1]
  if (!frontmatter) return null
  const match = frontmatter.match(
    /(?:^|\n)name:\s*["']?([a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)["']?\s*(?:$|\n)/,
  )
  return match?.[1] ?? null
}

function chooseFolder() {
  if (!folderInput.value) return
  folderInput.value.setAttribute('webkitdirectory', '')
  folderInput.value.click()
}

async function addSelectedFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files ?? [])
  input.value = ''
  if (selected.length === 0) return

  const uploadedPaths = selected.map(file => file.webkitRelativePath || file.name)
  const firstRoot = uploadedPaths[0]?.split('/')[0]
  const packageRoot = Boolean(
    firstRoot
    && uploadedPaths.includes(`${firstRoot}/SKILL.md`)
    && uploadedPaths.every(path => path.startsWith(`${firstRoot}/`)),
  )

  try {
    const importedPackage = packageRoot && uploadedPaths.includes(`${firstRoot}/SKILL.md`)
    let nextSkillMarkdown = draft.skill_md
    let nextName = draft.name
    const nextFiles = importedPackage ? [] : draft.files.map(file => ({ ...file }))
    for (let index = 0; index < selected.length; index += 1) {
      const file = selected[index]
      if (file.size > 2 * 1024 * 1024) {
        throw new Error(t('config.skills.fileTooLarge', { name: file.name }))
      }
      const uploadedPath = uploadedPaths[index]
      const path = packageRoot ? uploadedPath.slice((firstRoot?.length ?? 0) + 1) : uploadedPath
      if (path === 'SKILL.md') {
        const skillMarkdown = await readFileAsText(file)
        if (skillMarkdown.length > 100_000) {
          throw new Error(t('config.skills.skillMarkdownTooLarge'))
        }
        nextSkillMarkdown = skillMarkdown
        nextName = skillNameFromMarkdown(nextSkillMarkdown) ?? nextName
        continue
      }
      if (path.startsWith('SKILL.md/')) {
        throw new Error(t('config.skills.skillMdManaged'))
      }
      const contentBase64 = await readFileAsBase64(file)
      const existingIndex = nextFiles.findIndex(item => item.path === path)
      const entry: SkillFile = {
        path,
        content_base64: contentBase64,
        executable: path.startsWith('scripts/') || /\.(?:sh|bash|zsh)$/.test(path),
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

async function remove() {
  if (!selectedSkill.value) return
  if (!window.confirm(t('config.skills.deleteConfirm', { name: selectedSkill.value.name }))) return
  saving.value = true
  try {
    await deleteSkill(selectedSkill.value.id)
    startCreate()
    await load()
    message.success(t('config.skills.deleted'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.skills.deleteFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.skill-settings {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.skill-settings__list {
  display: grid;
  gap: 8px;
}

.skill-settings__list-header,
.skill-settings__item-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.skill-settings__list-header > div,
.skill-settings__item {
  display: grid;
  gap: 4px;
}

.skill-settings__list-header small,
.skill-settings__item small {
  color: var(--n-text-color-3);
  font-size: 12px;
}

.skill-settings__item {
  width: 100%;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  background: var(--n-color);
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
}

.skill-settings__item--active {
  border-color: var(--n-primary-color);
  background: rgba(24, 160, 88, 0.06);
}

.skill-settings__item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-settings__editor {
  min-width: 0;
}

.skill-settings__instructions :deep(textarea) {
  font-family: var(--font-mono, ui-monospace, monospace);
}

.skill-settings__files {
  display: grid;
  width: 100%;
  gap: 8px;
}

.skill-settings__file-toolbar,
.skill-settings__file,
.skill-settings__executable {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-settings__file-toolbar {
  justify-content: space-between;
}

.skill-settings__file-toolbar small {
  color: var(--n-text-color-3);
}

.skill-settings__native-input {
  display: none;
}

.skill-settings__file {
  padding: 8px;
  background: var(--n-color-modal);
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
}

.skill-settings__file :deep(.n-input) {
  min-width: 160px;
  flex: 1;
  font-family: var(--font-mono, ui-monospace, monospace);
}

.skill-settings__executable {
  white-space: nowrap;
}

.skill-settings__file-empty {
  padding: 12px;
}

.skill-settings__actions {
  margin-top: 8px;
}

@media (max-width: 767px) {
  .skill-settings {
    grid-template-columns: minmax(0, 1fr);
  }

  .skill-settings__file-toolbar,
  .skill-settings__file {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
