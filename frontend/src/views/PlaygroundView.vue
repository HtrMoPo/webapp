<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import ModelAutocomplete from '../components/ModelAutocomplete.vue'
import { modelPath } from '../utils/modelUrl'

const props = defineProps({ doiSlug: { type: String, required: true } })
const { t } = useI18n()

// Scripts/languages conventionally written right-to-left -- used only to
// pick a sensible default for the direction toggle; the user can always
// override it.
const RTL_SCRIPTS = new Set(['Arab', 'Hebr', 'Syrc', 'Thaa', 'Nkoo'])

const record = ref(null)
const catalog = ref([])
const loading = ref(true)
const loadError = ref('')

const segmentationDoi = ref('')
const recognitionDoi = ref('')
const regionDoi = ref('')
const direction = ref('ltr')

const imageFile = ref(null)
const imagePreviewUrl = ref('')
const imageNaturalSize = ref(null)

const submitting = ref(false)
const submitError = ref('')
const jobId = ref(null)
const jobStatus = ref('') // 'queued' | 'running' | 'done' | 'error'
const queuePosition = ref(null)
const jobError = ref('')
const result = ref(null)

// Picks the actual model weights out of a version's attached files --
// published records often also carry a metadata.json/model_card.md (legacy
// v0 schema) or stray files (e.g. ".README.md.swp") alongside the real
// .mlmodel/.safetensors weights, so files[0] isn't reliably the model file.
// If several weight files are attached, the first one is used; there's no
// per-model file picker in this first pass of the playground.
function primaryFile(entry) {
  const files = entry.latest_version?.files || []
  return files.find((f) => /\.(mlmodel|safetensors)$/i.test(f.filename))?.filename || null
}

function optionsFor(type) {
  return catalog.value.filter((m) => m.model_type?.includes(type) && primaryFile(m))
}
function toOptions(entries) {
  return entries.map((m) => ({ value: doiFor(m), label: m.title }))
}
const segmentationOptions = computed(() => toOptions(optionsFor('segmentation')))
const recognitionOptions = computed(() => toOptions(optionsFor('recognition')))
// D-Fine region models are also tagged "segmentation" in this catalog (no
// dedicated "region" model_type exists yet) -- offered as a distinct,
// optional slot regardless.
const regionOptions = computed(() => toOptions(optionsFor('segmentation')))

function doiFor(entry) {
  return entry.latest_version?.doi
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [rec, all] = await Promise.all([api.getModel(props.doiSlug), api.listModels()])
    record.value = rec
    catalog.value = all

    if (rec.model_type?.includes('segmentation')) segmentationDoi.value = doiFor(rec) || ''
    if (rec.model_type?.includes('recognition')) recognitionDoi.value = doiFor(rec) || ''
    direction.value = rec.script?.some((s) => RTL_SCRIPTS.has(s)) ? 'rtl' : 'ltr'
  } catch (e) {
    loadError.value = e.message || 'Failed to load'
  } finally {
    loading.value = false
  }
}
watch(() => props.doiSlug, load, { immediate: true })

function onFileSelected(e) {
  setImageFile(e.target.files?.[0])
}
function onDrop(e) {
  e.preventDefault()
  setImageFile(e.dataTransfer.files?.[0])
}
function setImageFile(file) {
  if (!file) return
  imageFile.value = file
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  imagePreviewUrl.value = URL.createObjectURL(file)
  imageNaturalSize.value = null
  result.value = null
}
function onPreviewLoad(e) {
  imageNaturalSize.value = { width: e.target.naturalWidth, height: e.target.naturalHeight }
}

function entryFor(doi) {
  return catalog.value.find((m) => doiFor(m) === doi)
}

function stopPolling() {
  jobId.value = null
}

async function poll(id) {
  while (jobId.value === id) {
    let job
    try {
      job = await api.playgroundJob(id)
    } catch {
      await new Promise((r) => setTimeout(r, 1500))
      continue
    }
    if (jobId.value !== id) return
    jobStatus.value = job.status
    if (job.status === 'queued') {
      queuePosition.value = job.queue_position
    } else if (job.status === 'done') {
      result.value = job.result
      return
    } else if (job.status === 'error') {
      jobError.value = job.error_message || t('playground.unknownError')
      return
    }
    await new Promise((r) => setTimeout(r, 1500))
  }
}

async function submit() {
  submitError.value = ''
  jobError.value = ''
  result.value = null
  if (!imageFile.value) {
    submitError.value = t('playground.needImage')
    return
  }
  const seg = entryFor(segmentationDoi.value)
  const reco = entryFor(recognitionDoi.value)
  if (!seg || !reco) {
    submitError.value = t('playground.needModels')
    return
  }
  const region = regionDoi.value ? entryFor(regionDoi.value) : null

  submitting.value = true
  try {
    const res = await api.submitPlaygroundJob({
      image: imageFile.value,
      direction: direction.value,
      segmentationDoi: doiFor(seg),
      segmentationFilename: primaryFile(seg),
      recognitionDoi: doiFor(reco),
      recognitionFilename: primaryFile(reco),
      regionDoi: region ? doiFor(region) : null,
      regionFilename: region ? primaryFile(region) : null,
    })
    jobId.value = res.id
    jobStatus.value = res.status
    queuePosition.value = res.queue_position
    poll(res.id)
  } catch (e) {
    const KNOWN_ERRORS = {
      rate_limit_exceeded: t('playground.rateLimitExceeded'),
      queue_full: t('playground.queueFull'),
    }
    submitError.value = KNOWN_ERRORS[e.message] || e.message || t('playground.submitFailed')
  } finally {
    submitting.value = false
  }
}

function polygonPoints(coords) {
  return (coords || []).map((p) => p.join(',')).join(' ')
}
</script>

<template>
  <div class="playground-shell">
    <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>
    <template v-else-if="loadError">
      <p class="playground-error">{{ loadError }}</p>
    </template>
    <template v-else>
      <div class="pagehead">
        <h1>{{ t('playground.title') }}</h1>
        <p>
          {{ t('playground.subtitle') }}
          <router-link class="lnk" :to="modelPath(doiSlug, record?.title)">{{ record?.title }}</router-link>
        </p>
      </div>

      <div class="playground-grid">
        <div class="form-section">
          <label>{{ t('playground.segmentationModel') }}</label>
          <ModelAutocomplete
            v-model="segmentationDoi"
            :options="segmentationOptions"
            :placeholder="t('playground.selectModel')"
          />

          <label>{{ t('playground.recognitionModel') }}</label>
          <ModelAutocomplete
            v-model="recognitionDoi"
            :options="recognitionOptions"
            :placeholder="t('playground.selectModel')"
          />

          <label>{{ t('playground.regionModel') }} <span class="form-help">({{ t('common.optional') }})</span></label>
          <ModelAutocomplete
            v-model="regionDoi"
            :options="regionOptions"
            :placeholder="t('playground.none')"
            clearable
          />

          <label>{{ t('playground.direction') }}</label>
          <div class="direction-toggle">
            <label><input type="radio" value="ltr" v-model="direction" /> {{ t('playground.ltr') }}</label>
            <label><input type="radio" value="rtl" v-model="direction" /> {{ t('playground.rtl') }}</label>
          </div>

          <label>{{ t('playground.image') }}</label>
          <div class="add-row-btn" @dragover.prevent @drop="onDrop" @click="$refs.fileInput.click()">
            <span v-if="imageFile" class="playground-filename" :title="imageFile.name">{{ imageFile.name }}</span>
            <template v-else>{{ t('playground.dropImage') }}</template>
          </div>
          <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onFileSelected" />

          <p class="playground-error" v-if="submitError">{{ submitError }}</p>
          <button class="btn btn--olive" :disabled="submitting || jobStatus === 'queued' || jobStatus === 'running'" @click="submit">
            {{ t('playground.run') }}
          </button>
        </div>

        <div class="playground-result">
          <div v-if="jobStatus === 'queued'" class="playground-status">
            <div class="spinner spinner--sm"></div>
            {{ t('playground.queued', { position: queuePosition }) }}
          </div>
          <div v-else-if="jobStatus === 'running'" class="playground-status">
            <div class="spinner spinner--sm"></div>
            {{ t('playground.running') }}
          </div>
          <p class="playground-error" v-else-if="jobStatus === 'error'">{{ jobError }}</p>

          <div v-if="imagePreviewUrl" class="playground-canvas">
            <img :src="imagePreviewUrl" @load="onPreviewLoad" alt="" />
            <svg
              v-if="result && imageNaturalSize"
              class="playground-overlay"
              :viewBox="`0 0 ${imageNaturalSize.width} ${imageNaturalSize.height}`"
              preserveAspectRatio="xMidYMid meet"
            >
              <polygon
                v-for="(line, i) in result.lines"
                :key="i"
                :points="polygonPoints(line.boundary)"
                class="playground-line"
              />
            </svg>
          </div>

          <div v-if="result" class="meta-card playground-lines">
            <h3>{{ t('playground.recognizedText') }}</h3>
            <ol>
              <li v-for="(line, i) in result.lines" :key="i">{{ line.text }}</li>
            </ol>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.playground-shell { max-width: var(--maxw); margin: 0 auto; padding: 28px 28px 80px; }
.playground-grid { display: grid; grid-template-columns: 320px 1fr; gap: 30px; align-items: start; }
.playground-grid label { display: block; font-size: 13px; font-weight: 600; margin: 14px 0 6px; }
.playground-grid label:first-child { margin-top: 0; }
.direction-toggle { display: flex; gap: 16px; font-weight: 400; font-size: 14px; }
.direction-toggle label { display: flex; align-items: center; gap: 6px; font-weight: 400; margin: 0; }
.playground-filename { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 100%; }

.playground-status { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; font-size: 14px; color: var(--ink-2); }
.spinner--sm { width: 16px; height: 16px; border-width: 2px; }
.playground-error {
  margin: 10px 0; padding: 10px 14px; border-radius: var(--radius-sm);
  background: var(--rose-bg); border: 1px solid var(--rose-line); color: var(--rose-ink);
  font-size: 13.5px;
}

.playground-canvas { position: relative; max-width: 100%; }
.playground-canvas img { max-width: 100%; display: block; border-radius: var(--radius); border: 1px solid var(--line); }
.playground-overlay { position: absolute; inset: 0; width: 100%; height: 100%; }
.playground-line { fill: rgba(199, 90, 60, .18); stroke: var(--accent, #c75a3c); stroke-width: 3; }

.playground-lines { margin-top: 20px; }
.playground-lines ol { margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.7; }

@media (max-width: 900px) {
  .playground-grid { grid-template-columns: 1fr; }
}
</style>
