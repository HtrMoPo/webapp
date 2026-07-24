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

// Fixed, deterministic palette for D-Fine region types -- cycles if there
// are more distinct region types on a page than colors.
const REGION_PALETTE = ['#3a6ea5', '#c75a3c', '#5a8f5a', '#a05ac7', '#c7a13a', '#3ab0a0']

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
const zoom = ref(1)
const ZOOM_MIN = 1
const ZOOM_MAX = 4
function zoomIn() { zoom.value = Math.min(ZOOM_MAX, +(zoom.value + 0.25).toFixed(2)) }
function zoomOut() { zoom.value = Math.max(ZOOM_MIN, +(zoom.value - 0.25).toFixed(2)) }
function zoomReset() { zoom.value = 1 }

// Rendering fonts for the recognized-text list -- Junicode (Latin/medieval)
// and Scheherazade New (Arabic) are specialist fonts common in this field,
// self-hosted via @font-face in src/styles/main.css.
const fontChoice = ref('default')
const FONT_FAMILIES = {
  junicode: "'Junicode', serif",
  scheherazade: "'Scheherazade New', serif",
}
const fontFamilyValue = computed(() => FONT_FAMILIES[fontChoice.value] || undefined)
function onCanvasWheel(e) {
  // Plain wheel zooms the image (no modifier needed) -- this claims
  // scrolling over the image for zoom rather than page/viewport scroll;
  // once zoomed in, the viewport's scrollbars (or dragging them) are what
  // pans around, not the wheel.
  e.preventDefault()
  zoom.value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +(zoom.value + (e.deltaY > 0 ? -0.15 : 0.15)).toFixed(2)))
}

const submitting = ref(false)
const submitError = ref('')
const jobId = ref(null)
const jobStatus = ref('') // 'queued' | 'running' | 'done' | 'error'
const queuePosition = ref(null)
const jobError = ref('')
const result = ref(null)
const hoveredLine = ref(null)
const hoveredRegionType = ref(null)

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
// kraken's own well-known general-purpose segmentation model -- used as the
// default pick whenever the current page's model isn't itself a
// segmentation model (see load()).
const defaultSegmentationOption = computed(() =>
  segmentationOptions.value.find((o) => o.label.startsWith('General segmentation model'))
)
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
    // Falls back to kraken's own well-known default segmentation model when
    // the page's own model isn't a segmentation one (e.g. viewing a
    // recognition model) -- saves searching for it by hand every time,
    // since it's a sensible default for most images.
    if (!segmentationDoi.value) {
      segmentationDoi.value = defaultSegmentationOption.value?.value || ''
    }
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
  zoom.value = 1
}
function onPreviewLoad(e) {
  imageNaturalSize.value = { width: e.target.naturalWidth, height: e.target.naturalHeight }
}

function entryFor(doi) {
  return catalog.value.find((m) => doiFor(m) === doi)
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

// Flattened, colored list of D-Fine/region polygons -- `result.regions` is
// `{ regionType: [boundary, ...] }`, keyed by whatever label the
// segmentation model(s) used (e.g. blla's own "text", D-Fine's SegmOnto
// zone names like "MainZone-Head").
const regionTypes = computed(() => Object.keys(result.value?.regions || {}))
function regionColor(type) {
  const i = regionTypes.value.indexOf(type)
  return REGION_PALETTE[i % REGION_PALETTE.length]
}
const flatRegions = computed(() => {
  const list = []
  for (const [type, boundaries] of Object.entries(result.value?.regions || {})) {
    for (const boundary of boundaries) list.push({ type, boundary })
  }
  return list
})

// Anchor point for the little "line number" bubble shown on hover --
// placed at the topmost point of the hovered line's polygon (falling back
// to its baseline) so it reads as pointing at that specific line rather
// than floating in the middle of the image.
const hoveredLineAnchor = computed(() => {
  if (hoveredLine.value === null) return null
  const line = result.value?.lines?.[hoveredLine.value]
  const points = line?.boundary?.length ? line.boundary : line?.baseline
  if (!points?.length) return null
  const top = points.reduce((best, p) => (p[1] < best[1] ? p : best), points[0])
  return { x: top[0], y: top[1] - 4 }
})
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

      <div class="playground-toolbar">
        <div class="toolbar-field">
          <label>{{ t('playground.segmentationModel') }}</label>
          <ModelAutocomplete v-model="segmentationDoi" :options="segmentationOptions" :placeholder="t('playground.selectModel')" />
        </div>

        <div class="toolbar-field">
          <label>{{ t('playground.recognitionModel') }}</label>
          <ModelAutocomplete v-model="recognitionDoi" :options="recognitionOptions" :placeholder="t('playground.selectModel')" />
        </div>

        <div class="toolbar-field">
          <label>{{ t('playground.regionModel') }} <span class="form-help">({{ t('common.optional') }})</span></label>
          <ModelAutocomplete v-model="regionDoi" :options="regionOptions" :placeholder="t('playground.none')" clearable />
        </div>

        <div class="toolbar-field toolbar-field--narrow">
          <label>{{ t('playground.direction') }}</label>
          <div class="direction-toggle">
            <label><input type="radio" value="ltr" v-model="direction" /> {{ t('playground.ltr') }}</label>
            <label><input type="radio" value="rtl" v-model="direction" /> {{ t('playground.rtl') }}</label>
          </div>
        </div>

        <div class="toolbar-field toolbar-field--narrow">
          <label>{{ t('playground.image') }}</label>
          <div class="add-row-btn playground-drop" @dragover.prevent @drop="onDrop" @click="$refs.fileInput.click()">
            <span v-if="imageFile" class="playground-filename" :title="imageFile.name">{{ imageFile.name }}</span>
            <template v-else>{{ t('playground.dropImage') }}</template>
          </div>
          <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onFileSelected" />
        </div>

        <button class="btn btn--olive playground-run" :disabled="submitting || jobStatus === 'queued' || jobStatus === 'running'" @click="submit">
          {{ t('playground.run') }}
        </button>
      </div>

      <p class="playground-error" v-if="submitError">{{ submitError }}</p>

      <div v-if="jobStatus === 'queued'" class="playground-status">
        <div class="spinner spinner--sm"></div>
        {{ t('playground.queued', { position: queuePosition }) }}
      </div>
      <div v-else-if="jobStatus === 'running'" class="playground-status">
        <div class="spinner spinner--sm"></div>
        <div>
          <div>{{ t('playground.running') }}</div>
          <p class="playground-running-warning">{{ t('playground.runningWarning') }}</p>
        </div>
      </div>
      <p class="playground-error" v-else-if="jobStatus === 'error'">{{ jobError }}</p>

      <div v-if="regionTypes.length" class="meta-card playground-region-legend">
        <h3>{{ t('playground.regions') }}</h3>
        <ul>
          <li
            v-for="type in regionTypes"
            :key="type"
            :class="{ 'is-hovered': hoveredRegionType === type }"
            @mouseenter="hoveredRegionType = type"
            @mouseleave="hoveredRegionType = null"
          >
            <span class="playground-region-swatch" :style="{ background: regionColor(type) }"></span>
            {{ type }}
          </li>
        </ul>
      </div>

      <div v-if="imagePreviewUrl" class="playground-output">
        <div class="playground-canvas-col">
          <div class="playground-zoom-controls">
            <button type="button" class="playground-zoom-btn" :disabled="zoom <= ZOOM_MIN" @click="zoomOut">&minus;</button>
            <span class="playground-zoom-level">{{ Math.round(zoom * 100) }}%</span>
            <button type="button" class="playground-zoom-btn" :disabled="zoom >= ZOOM_MAX" @click="zoomIn">+</button>
            <button type="button" class="playground-zoom-reset" v-if="zoom !== 1" @click="zoomReset">{{ t('playground.resetZoom') }}</button>
          </div>
          <div class="playground-canvas-viewport" @wheel="onCanvasWheel">
            <div class="playground-canvas" :style="{ width: zoom * 100 + '%' }">
              <img :src="imagePreviewUrl" @load="onPreviewLoad" alt="" />
              <svg
                v-if="result && imageNaturalSize"
                class="playground-overlay"
                :viewBox="`0 0 ${imageNaturalSize.width} ${imageNaturalSize.height}`"
                preserveAspectRatio="xMidYMid meet"
              >
                <polygon
                  v-for="(region, i) in flatRegions"
                  :key="`region-${i}`"
                  :points="polygonPoints(region.boundary)"
                  class="playground-region"
                  :class="{ 'is-hovered': hoveredRegionType === region.type }"
                  :style="{ stroke: regionColor(region.type), fill: hoveredRegionType === region.type ? regionColor(region.type) : 'none' }"
                />
                <polygon
                  v-for="(line, i) in result.lines"
                  :key="i"
                  :points="polygonPoints(line.boundary)"
                  class="playground-line"
                  :class="{ 'is-hovered': hoveredLine === i }"
                  @mouseenter="hoveredLine = i"
                  @mouseleave="hoveredLine = null"
                ><title>{{ line.text }}</title></polygon>

                <g v-if="hoveredLineAnchor" class="playground-line-badge" style="pointer-events: none">
                  <circle :cx="hoveredLineAnchor.x" :cy="hoveredLineAnchor.y" r="16" />
                  <text :x="hoveredLineAnchor.x" :y="hoveredLineAnchor.y" dominant-baseline="central" text-anchor="middle">{{ hoveredLine + 1 }}</text>
                </g>
              </svg>
            </div>
          </div>
        </div>

        <div v-if="result" class="playground-side">
          <div class="playground-text-controls">
            <label for="playground-font">{{ t('playground.font') }}</label>
            <select id="playground-font" v-model="fontChoice" class="playground-font-select">
              <option value="default">{{ t('playground.fontDefault') }}</option>
              <option value="junicode">Junicode</option>
              <option value="scheherazade">Scheherazade</option>
            </select>
          </div>
          <div class="meta-card playground-lines">
            <h3>{{ t('playground.recognizedText') }}</h3>
            <ol :dir="direction" :style="{ fontFamily: fontFamilyValue }">
              <li
                v-for="(line, i) in result.lines"
                :key="i"
                :class="{ 'is-hovered': hoveredLine === i }"
                @mouseenter="hoveredLine = i"
                @mouseleave="hoveredLine = null"
              >{{ line.text }}</li>
            </ol>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.playground-shell { max-width: var(--maxw); margin: 0 auto; padding: 28px 28px 80px; }

.playground-toolbar {
  display: flex; flex-wrap: wrap; align-items: end; gap: 16px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 20px; box-shadow: var(--shadow-sm); margin-bottom: 16px;
}
.toolbar-field { flex: 1 1 200px; min-width: 180px; }
.toolbar-field--narrow { flex: 1 1 160px; min-width: 150px; }
.playground-toolbar label { display: block; font-size: 13px; font-weight: 600; margin: 0 0 6px; }
.playground-drop { padding: 10px 12px; }
.playground-run { flex-shrink: 0; }

.direction-toggle { display: flex; gap: 16px; font-weight: 400; font-size: 14px; height: 38px; align-items: center; }
.direction-toggle label { display: flex; align-items: center; gap: 6px; font-weight: 400; margin: 0; }
.playground-filename { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 100%; }

.playground-status { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 16px; font-size: 14px; color: var(--ink-2); }
.playground-status .spinner--sm { margin-top: 2px; }
.spinner--sm { width: 16px; height: 16px; border-width: 2px; }
.playground-running-warning { margin: 4px 0 0; font-size: 12.5px; color: var(--ink-3); }
.playground-error {
  margin: 10px 0; padding: 10px 14px; border-radius: var(--radius-sm);
  background: var(--rose-bg); border: 1px solid var(--rose-line); color: var(--rose-ink);
  font-size: 13.5px;
}

.playground-output { display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; align-items: stretch; }

.playground-canvas-col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.playground-zoom-controls { display: flex; align-items: center; gap: 8px; }
.playground-zoom-btn {
  width: 28px; height: 28px; border-radius: 6px; border: 1px solid var(--line-2);
  background: var(--surface); color: var(--ink-2); font-size: 16px; line-height: 1; cursor: pointer;
}
.playground-zoom-btn:hover:not(:disabled) { background: var(--paper-2); color: var(--ink); }
.playground-zoom-btn:disabled { opacity: .4; cursor: default; }
.playground-zoom-level { font-size: 12.5px; color: var(--ink-3); min-width: 40px; text-align: center; }
.playground-zoom-reset {
  font-size: 12px; font-weight: 600; color: var(--accent); background: none; border: none; cursor: pointer; padding: 0 4px;
}

.playground-text-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.playground-text-controls label { font-size: 12.5px; color: var(--ink-3); }
.playground-font-select {
  font-family: var(--sans); font-size: 12.5px; color: var(--ink-2);
  border: 1px solid var(--line-2); border-radius: 6px; padding: 4px 8px;
  background: var(--surface); cursor: pointer;
}

.playground-canvas-viewport {
  /* A fixed viewport-relative height (rather than sizing to the image's own
     intrinsic height via flex-grow) keeps this deterministic -- a
     flex:1 child inside a CSS Grid row whose own height comes from
     align-items:stretch is a genuinely ambiguous sizing case across
     browsers once the image's aspect ratio varies, and in practice never
     reliably matched the text column's height. Tying it to the viewport
     (page) height instead means both columns always end up the same,
     generous height regardless of what image is loaded. */
  position: relative; overflow: auto; height: 70vh;
  border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper-2);
}
.playground-canvas { position: relative; }
.playground-canvas img { width: 100%; display: block; }
.playground-overlay { position: absolute; inset: 0; width: 100%; height: 100%; }

.playground-line {
  fill: rgba(199, 90, 60, .12); stroke: var(--accent, #c75a3c); stroke-width: 3;
  cursor: pointer; transition: fill .1s, stroke-width .1s;
}
.playground-line.is-hovered { fill: rgba(199, 90, 60, .38); stroke-width: 4; }

.playground-region { fill: none; stroke-width: 5; stroke-dasharray: 9 6; opacity: .85; transition: fill-opacity .1s; }
.playground-region.is-hovered { fill-opacity: .3; }

.playground-line-badge circle { fill: var(--ink); stroke: var(--paper); stroke-width: 2; }
.playground-line-badge text { fill: var(--paper); font-size: 15px; font-weight: 700; font-family: var(--sans); }

.playground-side { display: flex; flex-direction: column; gap: 16px; min-height: 500px; }
.meta-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 20px; box-shadow: var(--shadow-sm);
}
.meta-card h3 {
  font-family: var(--serif); font-size: 15px; font-weight: 600;
  color: var(--ink); margin: 0 0 14px; padding-bottom: 10px;
  border-bottom: 1px solid var(--line); letter-spacing: -.01em;
}
.playground-lines {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
  /* Real documents can produce far more recognized lines than fit in
     70vh (dozens, sometimes 70+) -- without a cap here the list just
     kept growing the whole page past the image and the footer. Capping
     the card and scrolling its own list internally keeps the two
     columns visually paired regardless of how much text comes back. */
  max-height: 70vh;
}
.playground-lines ol { margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.7; overflow-y: auto; min-height: 0; }
.playground-lines li { border-radius: 4px; padding: 2px 6px; margin: 0 -6px; cursor: default; transition: background .1s, box-shadow .1s; }
.playground-lines li.is-hovered { background: var(--olive-tint); box-shadow: inset 3px 0 0 var(--olive); font-weight: 600; }

/* Sits above the image/text pair, full width -- a region type applies to
   both, not to just one side. */
.playground-region-legend { margin-bottom: 16px; }
.playground-region-legend ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px 22px; }
.playground-region-legend li {
  display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-2);
  cursor: default; border-radius: 4px; padding: 3px 8px; margin: -3px -8px; transition: background .1s;
}
.playground-region-legend li.is-hovered { background: var(--paper-2); color: var(--ink); font-weight: 600; }
.playground-region-swatch { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }

@media (max-width: 1000px) {
  .playground-output { grid-template-columns: 1fr; }
}
</style>
