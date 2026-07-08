<script setup>
import { load as loadYaml } from 'js-yaml'
import { marked } from 'marked'
import TurndownService from 'turndown'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'
import WysiwygEditor from '../components/WysiwygEditor.vue'

const turndownService = new TurndownService()

const props = defineProps({ recordId: { type: Number, default: null } })
const { t } = useI18n()
const router = useRouter()
const auth = useAuth()

const languages = ref([])
const scripts = ref([])
const licenses = ref([])
const modelTypes = ref([])

const versionId = ref(null)
const title = ref('')
const summary = ref('')
const license = ref('CC-BY-4.0')
const softwareName = ref('kraken')
const softwareHints = ref('')
const keywords = ref('')
const datasetRows = reactive([''])
const baseModelRows = reactive([''])
const citation = ref('')
// Bound to the WYSIWYG editor (rich HTML for authoring). Converted to real
// Markdown only when actually sent to the backend (see currentBodyMarkdown),
// since that's what ends up in README.md -- Zenodo's `description` field
// gets HTML rendered back from that Markdown server-side.
const bodyHtml = ref('')
const authors = reactive([{ name: '', affiliation: '', orcid: '' }])
const metrics = reactive([{ name: '', value: '' }])
const selectedLanguages = ref([])
const selectedScripts = ref([])
const selectedModelTypes = ref([])
const languageQuery = ref('')
const scriptQuery = ref('')
const baseModelQuery = ref('')
const datasetQuery = ref('')
const catalogModels = ref([])
const htrUnitedDatasets = ref([])
const files = ref([])
const isPrivate = ref(true)
const errors = ref([])
const publishing = ref(false)
const saving = ref(false)
const progress = ref('')
const publishedDoi = ref('')

onMounted(async () => {
  ;[languages.value, scripts.value, licenses.value, modelTypes.value, catalogModels.value, htrUnitedDatasets.value] =
    await Promise.all([
      api.languages(),
      api.scripts(),
      api.licenses(),
      api.modelTypes(),
      api.listModels(),
      api.htrUnitedDatasets(),
    ])

  if (props.recordId) {
    const records = await api.myModels()
    const record = records.find((r) => r.id === props.recordId)
    if (record) {
      title.value = record.title
      const draft = record.versions.find((v) => v.status === 'draft')
      const latestPublished = [...record.versions].reverse().find((v) => v.status === 'published')
      const source = draft ?? latestPublished
      if (draft) versionId.value = draft.id
      if (source) prefill(source)
    }
  }
})

function prefill(version) {
  const match = version.card_yaml.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return
  const metadata = loadYaml(match[1]) || {}
  bodyHtml.value = match[2] ? marked.parse(match[2]) : ''

  summary.value = metadata.summary ?? ''
  license.value = metadata.license ?? 'CC-BY-4.0'
  softwareName.value = metadata.software_name ?? ''
  softwareHints.value = (metadata.software_hints ?? []).join('\n')
  keywords.value = (metadata.keywords ?? metadata.tags ?? []).join('\n')
  datasetRows.splice(0, datasetRows.length, ...(metadata.datasets?.length ? metadata.datasets : ['']))
  baseModelRows.splice(0, baseModelRows.length, ...(metadata.base_model?.length ? metadata.base_model : ['']))
  citation.value = metadata.citation ?? ''
  selectedLanguages.value = [...(metadata.language ?? [])]
  selectedScripts.value = [...(metadata.script ?? [])]
  selectedModelTypes.value = [...(metadata.model_type ?? [])]

  const loadedAuthors = (metadata.authors ?? []).map((a) => ({
    name: a.name ?? '',
    affiliation: a.affiliation ?? '',
    orcid: a.orcid ?? '',
  }))
  authors.splice(0, authors.length, ...(loadedAuthors.length ? loadedAuthors : [{ name: '', affiliation: '', orcid: '' }]))

  const loadedMetrics = Object.entries(metadata.metrics ?? {}).map(([name, value]) => ({ name, value: String(value) }))
  metrics.splice(0, metrics.length, ...(loadedMetrics.length ? loadedMetrics : [{ name: '', value: '' }]))

  files.value = (version.files ?? []).map((f) => ({ name: f.filename, size: f.size, _uploaded: true, _existing: true }))
}

const languageOptions = computed(() =>
  languages.value.filter(
    (l) => l.name.toLowerCase().includes(languageQuery.value.toLowerCase()) && !selectedLanguages.value.includes(l.code)
  ).slice(0, 8)
)
const scriptOptions = computed(() =>
  scripts.value.filter(
    (s) => s.name.toLowerCase().includes(scriptQuery.value.toLowerCase()) && !selectedScripts.value.includes(s.code)
  ).slice(0, 8)
)

function addLanguage(code) {
  selectedLanguages.value.push(code)
  languageQuery.value = ''
}
function removeLanguage(code) {
  selectedLanguages.value = selectedLanguages.value.filter((c) => c !== code)
}
function addScript(code) {
  selectedScripts.value.push(code)
  scriptQuery.value = ''
}
function removeScript(code) {
  selectedScripts.value = selectedScripts.value.filter((c) => c !== code)
}
function toggleModelType(mt) {
  const idx = selectedModelTypes.value.indexOf(mt)
  if (idx === -1) selectedModelTypes.value.push(mt)
  else selectedModelTypes.value.splice(idx, 1)
}

function zenodoRecordUrl(doi) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}` : doi
}

const baseModelOptions = computed(() => {
  const q = baseModelQuery.value.trim().toLowerCase()
  return catalogModels.value
    .filter((m) => m.latest_version?.doi && m.id !== props.recordId)
    .map((m) => ({ ...m, url: zenodoRecordUrl(m.latest_version.doi) }))
    .filter((m) => !baseModelRows.includes(m.url))
    .filter((m) => !q || `${m.title} ${m.summary}`.toLowerCase().includes(q))
    .slice(0, 8)
})

function addBaseModelFromCatalog(model) {
  const emptyIdx = baseModelRows.findIndex((v) => !v.trim())
  if (emptyIdx !== -1) baseModelRows[emptyIdx] = model.url
  else baseModelRows.push(model.url)
  baseModelQuery.value = ''
}
function addBaseModelRow() {
  baseModelRows.push('')
}
function removeBaseModelRow(i) {
  baseModelRows.splice(i, 1)
}
function baseModelLabel(url) {
  const match = catalogModels.value.find((m) => zenodoRecordUrl(m.latest_version?.doi) === url)
  return match ? match.title : ''
}

const datasetOptions = computed(() => {
  const q = datasetQuery.value.trim().toLowerCase()
  return htrUnitedDatasets.value
    .filter((d) => !datasetRows.includes(d.url))
    .filter((d) => !q || d.title.toLowerCase().includes(q))
    .slice(0, 8)
})

function addDatasetFromCatalog(dataset) {
  const emptyIdx = datasetRows.findIndex((v) => !v.trim())
  if (emptyIdx !== -1) datasetRows[emptyIdx] = dataset.url
  else datasetRows.push(dataset.url)
  datasetQuery.value = ''
}
function datasetLabel(url) {
  const match = htrUnitedDatasets.value.find((d) => d.url === url)
  return match ? match.title : ''
}

function addDatasetRow() {
  datasetRows.push('')
}
function removeDatasetRow(i) {
  datasetRows.splice(i, 1)
}

function addAuthor() {
  authors.push({ name: '', affiliation: '', orcid: '' })
}
function removeAuthor(i) {
  authors.splice(i, 1)
}
function addMetric() {
  metrics.push({ name: '', value: '' })
}
function removeMetric(i) {
  metrics.splice(i, 1)
}

function onFilesSelected(e) {
  files.value.push(...Array.from(e.target.files))
}
function onDrop(e) {
  e.preventDefault()
  files.value.push(...Array.from(e.dataTransfer.files))
}
async function removeLocalFile(i) {
  const f = files.value[i]
  if (f._existing && versionId.value) {
    try {
      await api.deleteFile(versionId.value, f.name)
    } catch {
      // best-effort: still drop it from the local list below
    }
  }
  files.value.splice(i, 1)
}

function splitLines(s) {
  return s.split('\n').map((l) => l.trim()).filter(Boolean)
}

const metadata = computed(() => {
  const md = {
    summary: summary.value,
    license: license.value,
    software_name: softwareName.value,
    language: selectedLanguages.value,
    script: selectedScripts.value,
    model_type: selectedModelTypes.value,
  }
  if (softwareHints.value.trim()) md.software_hints = splitLines(softwareHints.value)
  if (keywords.value.trim()) md.keywords = splitLines(keywords.value)
  const cleanDatasets = datasetRows.map((v) => v.trim()).filter(Boolean)
  if (cleanDatasets.length) md.datasets = cleanDatasets
  const cleanBaseModels = baseModelRows.map((v) => v.trim()).filter(Boolean)
  if (cleanBaseModels.length) md.base_model = cleanBaseModels
  if (citation.value.trim()) md.citation = citation.value.trim()
  const cleanAuthors = authors.filter((a) => a.name.trim()).map((a) => {
    const out = { name: a.name.trim() }
    if (a.affiliation.trim()) out.affiliation = a.affiliation.trim()
    if (a.orcid.trim()) out.orcid = a.orcid.trim()
    return out
  })
  md.authors = cleanAuthors
  const cleanMetrics = {}
  for (const m of metrics) {
    if (m.name.trim() && m.value !== '') cleanMetrics[m.name.trim()] = Number(m.value)
  }
  if (Object.keys(cleanMetrics).length) md.metrics = cleanMetrics
  return md
})

function currentBodyMarkdown() {
  return turndownService.turndown(bodyHtml.value)
}

async function ensureDraft() {
  if (versionId.value) return versionId.value
  const payload = { metadata: metadata.value, body_md: currentBodyMarkdown(), title: title.value || summary.value }
  const res = props.recordId
    ? await api.createVersionDraft(props.recordId, payload)
    : await api.createDraft(payload)
  versionId.value = res.version_id
  return res.version_id
}

async function saveDraft() {
  progress.value = t('form.progress.savingDraft')
  const id = await ensureDraft()
  await api.updateDraft(id, { metadata: metadata.value, body_md: currentBodyMarkdown(), title: title.value })
  if (files.value.some((f) => !f._uploaded)) {
    progress.value = t('form.progress.uploadingFiles')
    for (const f of files.value) {
      if (!f._uploaded) {
        await api.uploadFile(id, f)
        f._uploaded = true
      }
    }
  }
}

async function onSaveDraftClick() {
  errors.value = []
  saving.value = true
  try {
    await saveDraft()
  } catch (e) {
    if (e.detail?.errors?.length) errors.value = e.detail.errors
    else errors.value = [e.message || 'Saving failed.']
  } finally {
    saving.value = false
    progress.value = ''
  }
}

const PUBLISH_STEP_LABELS = {
  creating_deposition: () => t('form.progress.creatingDeposition'),
  resolving_previous_version: () => t('form.progress.resolvingPreviousVersion'),
  uploading_file: (detail) => t('form.progress.uploadingFile', { detail }),
  setting_metadata: () => t('form.progress.settingMetadata'),
  publishing: () => t('form.progress.publishingToZenodo'),
}

async function pollPublishProgress(id, stopFlag) {
  while (!stopFlag.done) {
    try {
      const p = await api.publishProgress(id)
      const label = PUBLISH_STEP_LABELS[p.step]
      if (label) progress.value = label(p.detail)
    } catch {
      // ignore transient poll failures, keep showing the last known step
    }
    await new Promise((resolve) => setTimeout(resolve, 800))
  }
}

async function publish() {
  errors.value = []
  if (!files.value.length) {
    errors.value = [t('form.noFilesError')]
    return
  }
  publishing.value = true
  try {
    await saveDraft()
    const id = versionId.value
    progress.value = t('form.progress.publishing')
    const stopFlag = { done: false }
    const pollPromise = pollPublishProgress(id, stopFlag)
    try {
      const res = await api.publishDraft(id, isPrivate.value)
      publishedDoi.value = res.doi
      versionId.value = null
      router.push(`/models/${res.slug}`)
    } finally {
      stopFlag.done = true
      await pollPromise
    }
  } catch (e) {
    if (e.detail?.errors?.length) errors.value = e.detail.errors
    else errors.value = [e.message || 'Publishing failed.']
  } finally {
    publishing.value = false
    progress.value = ''
  }
}
</script>

<template>
  <div class="pagehead">
    <h1>{{ props.recordId ? t('form.titleVersion', { title }) : t('form.titleNew') }}</h1>
  </div>

  <div v-if="!auth.authenticated" class="page-content">
    <p>{{ t('auth.notAuthenticated') }}</p>
    <a class="btn btn--olive" :href="api.loginUrl()">{{ t('nav.login') }}</a>
  </div>

  <div v-else class="form-page">
    <div class="form-section">
      <h2>{{ t('form.steps.title') }}</h2>
      <div class="steps-list">
        <div class="step-item"><span class="step-badge">1</span>{{ t('form.steps.one') }}</div>
        <div class="step-item"><span class="step-badge">2</span>{{ t('form.steps.two') }}</div>
        <div class="step-item"><span class="step-badge">3</span>{{ t('form.steps.three') }}</div>
      </div>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.identity') }}</h2>
      <div class="form-group">
        <label class="form-label">{{ t('form.summary') }} <span class="req">*</span></label>
        <input class="form-input" v-model="summary" />
        <div class="form-help">{{ t('form.summaryHelp') }}</div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">{{ t('form.license') }} <span class="req">*</span></label>
          <select class="form-input form-select" v-model="license">
            <option value="">—</option>
            <option v-for="l in licenses" :key="l.id" :value="l.id">{{ l.title }}</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('form.softwareName') }} <span class="req">*</span></label>
          <input class="form-input" v-model="softwareName" />
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">{{ t('form.softwareHint') }}</label>
        <textarea class="form-input" v-model="softwareHints" rows="2"></textarea>
      </div>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.authors') }}</h2>
      <div class="author-card" v-for="(a, i) in authors" :key="i">
        <div class="author-card__header">
          <span class="author-card__title">#{{ i + 1 }}</span>
          <button class="btn btn--ghost" @click="removeAuthor(i)" v-if="authors.length > 1">{{ t('form.removeAuthor') }}</button>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">{{ t('form.authorName') }} <span class="req">*</span></label>
            <input class="form-input" v-model="a.name" />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('form.authorAffiliation') }}</label>
            <input class="form-input" v-model="a.affiliation" />
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('form.authorOrcid') }}</label>
          <input class="form-input" v-model="a.orcid" placeholder="https://orcid.org/0000-0000-0000-0000" />
        </div>
      </div>
      <button class="add-row-btn" @click="addAuthor">+ {{ t('form.addAuthor') }}</button>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.classification') }}</h2>
      <div class="form-group">
        <label class="form-label">{{ t('form.language') }} <span class="req">*</span></label>
        <div class="chips" style="margin-bottom:8px">
          <span class="chip chip--rose" v-for="code in selectedLanguages" :key="code">
            <span class="chip__k">{{ code }}</span>
            <span class="chip__v" style="cursor:pointer" @click="removeLanguage(code)">✕</span>
          </span>
        </div>
        <input class="form-input" v-model="languageQuery" placeholder="Search languages…" />
        <div class="tag-selector" style="margin-top:8px">
          <button class="tag-btn" v-for="l in languageOptions" :key="l.code" @click="addLanguage(l.code)">{{ l.name }} ({{ l.code }})</button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('form.script') }} <span class="req">*</span></label>
        <div class="chips" style="margin-bottom:8px">
          <span class="chip chip--rose" v-for="code in selectedScripts" :key="code">
            <span class="chip__k">{{ code }}</span>
            <span class="chip__v" style="cursor:pointer" @click="removeScript(code)">✕</span>
          </span>
        </div>
        <input class="form-input" v-model="scriptQuery" placeholder="Search scripts…" />
        <div class="tag-selector" style="margin-top:8px">
          <button class="tag-btn" v-for="s in scriptOptions" :key="s.code" @click="addScript(s.code)">{{ s.name }} ({{ s.code }})</button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('form.modelType') }} <span class="req">*</span></label>
        <div class="tag-selector">
          <button class="tag-btn" :class="{ 'is-on': selectedModelTypes.includes(mt) }" v-for="mt in modelTypes" :key="mt" @click="toggleModelType(mt)">{{ mt }}</button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('form.keywords') }}</label>
        <textarea class="form-input" v-model="keywords" rows="2" placeholder="one per line"></textarea>
      </div>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.training') }}</h2>
      <div class="form-group">
        <label class="form-label">{{ t('form.datasets') }}</label>
        <input class="form-input" v-model="datasetQuery" :placeholder="t('form.datasetsSearch')" />
        <div class="tag-selector" style="margin-top:8px" v-if="datasetOptions.length">
          <button class="tag-btn" v-for="d in datasetOptions" :key="d.url" @click="addDatasetFromCatalog(d)">{{ d.title }}</button>
        </div>
        <div class="form-help">{{ t('form.datasetsHelp') }}</div>
        <div class="metric-row" v-for="(row, i) in datasetRows" :key="i" style="margin-top:8px">
          <div style="flex:1">
            <input class="form-input" v-model="datasetRows[i]" placeholder="https://…" />
            <div class="form-help" v-if="datasetLabel(datasetRows[i])">→ {{ datasetLabel(datasetRows[i]) }}</div>
          </div>
          <button class="btn btn--ghost" @click="removeDatasetRow(i)" v-if="datasetRows.length > 1">{{ t('common.remove') }}</button>
        </div>
        <button class="add-row-btn" @click="addDatasetRow">+ {{ t('common.add') }}</button>
      </div>
      <div class="form-group">
        <label class="form-label">{{ t('form.baseModel') }}</label>
        <input class="form-input" v-model="baseModelQuery" :placeholder="t('form.baseModelSearch')" />
        <div class="tag-selector" style="margin-top:8px" v-if="baseModelOptions.length">
          <button class="tag-btn" v-for="m in baseModelOptions" :key="m.url" @click="addBaseModelFromCatalog(m)">{{ m.title }}</button>
        </div>
        <div class="form-help">{{ t('form.baseModelHelp') }}</div>
        <div class="metric-row" v-for="(row, i) in baseModelRows" :key="i" style="margin-top:8px">
          <div style="flex:1">
            <input class="form-input" v-model="baseModelRows[i]" placeholder="https://…" />
            <div class="form-help" v-if="baseModelLabel(baseModelRows[i])">→ {{ baseModelLabel(baseModelRows[i]) }}</div>
          </div>
          <button class="btn btn--ghost" @click="removeBaseModelRow(i)" v-if="baseModelRows.length > 1">{{ t('common.remove') }}</button>
        </div>
        <button class="add-row-btn" @click="addBaseModelRow">+ {{ t('common.add') }}</button>
      </div>
      <div class="form-group">
        <label class="form-label">{{ t('form.citation') }}</label>
        <input class="form-input" v-model="citation" />
        <div class="form-help">{{ t('form.citationHelp') }}</div>
      </div>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.metrics') }}</h2>
      <div class="form-help" style="margin-bottom:12px">{{ t('form.metricsHelp') }}</div>
      <div class="metric-row" v-for="(m, i) in metrics" :key="i">
        <input class="form-input" v-model="m.name" :placeholder="t('form.metricName')" />
        <input class="form-input" type="number" step="any" v-model="m.value" :placeholder="t('form.metricValue')" />
        <button class="btn btn--ghost" @click="removeMetric(i)" v-if="metrics.length > 1">{{ t('form.removeMetric') }}</button>
      </div>
      <button class="add-row-btn" @click="addMetric">+ {{ t('form.addMetric') }}</button>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.description') }}</h2>
      <div class="form-group">
        <label class="form-label">{{ t('form.bodyMd') }}</label>
        <WysiwygEditor v-model="bodyHtml" />
        <div class="form-help">{{ t('form.bodyMdHelp') }}</div>
      </div>
    </div>

    <div class="form-section">
      <h2>{{ t('form.section.files') }}</h2>
      <div class="add-row-btn" @dragover.prevent @drop="onDrop" @click="$refs.fileInput.click()">
        {{ t('form.dropFiles') }}
        <input ref="fileInput" type="file" multiple style="display:none" @change="onFilesSelected" />
      </div>
      <ul>
        <li v-for="(f, i) in files" :key="i">
          {{ f.name }}
          <button class="btn btn--ghost" @click="removeLocalFile(i)">{{ t('form.removeFile') }}</button>
        </li>
      </ul>
    </div>

    <div class="form-section">
      <label class="checkbox-item">
        <input type="checkbox" v-model="isPrivate" />
        {{ t('form.private') }}
      </label>
      <div class="output-actions">
        <button class="btn btn--ghost" :disabled="saving || publishing" @click="onSaveDraftClick">{{ t('form.saveDraft') }}</button>
        <button class="btn btn--primary" :disabled="saving || publishing" @click="publish">{{ t('form.publish') }}</button>
      </div>
      <div class="form-progress" v-if="saving || publishing">
        <span class="spinner spinner--sm"></span>
        {{ progress || t('common.loading') }}
      </div>
      <div class="form-errors" v-if="errors.length">
        <p><strong>{{ t('form.validationErrors') }}</strong></p>
        <ul><li v-for="(err, i) in errors" :key="i">{{ err }}</li></ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.step-item {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--ink-2);
}
.form-progress {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
  color: var(--ink-2);
}
.spinner--sm {
  width: 16px;
  height: 16px;
  border-width: 2px;
}
.form-errors {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  background: var(--rose-bg);
  border: 1px solid var(--rose-line);
  color: var(--rose-ink);
}
.form-errors p { margin: 0 0 6px; }
.form-errors ul { margin: 0; padding-left: 20px; }
</style>
