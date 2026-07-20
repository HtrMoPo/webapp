<script setup>
import { load as loadYaml } from 'js-yaml'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'
import { formatAuthorList } from '../utils/authors'
import { useIsoNames } from '../utils/iso'

const { t } = useI18n()
const { languageName, scriptName } = useIsoNames()
const auth = useAuth()
const baseUrl = import.meta.env.BASE_URL

const CHIP_CAP = 4
function capChips(values) {
  const list = values || []
  return { shown: list.slice(0, CHIP_CAP), extra: Math.max(0, list.length - CHIP_CAP) }
}

const models = ref([])
const loading = ref(true)
const refreshing = ref(false)
const refreshingDatasets = ref(false)
const search = ref('')
const selected = ref({ language: new Set(), script: new Set(), model_type: new Set(), license: new Set() })
const sortBy = ref('recency')

function cardAuthorLine(model) {
  const yaml = model.latest_version?.card_yaml
  const match = yaml?.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return ''
  const metadata = loadYaml(match[1]) || {}
  return formatAuthorList(metadata.authors)
}

function zenodoUrl(doi) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}` : null
}

async function load() {
  const listed = await api.listModels()
  models.value = listed.map((m) => ({
    ...m,
    authorLine: cardAuthorLine(m),
    languageChips: capChips(m.language),
    scriptChips: capChips(m.script),
  }))
}

onMounted(async () => {
  await load()
  loading.value = false
})

async function refreshFromZenodo() {
  refreshing.value = true
  try {
    await api.triggerHarvest()
    await load()
  } catch {
    // best-effort refresh; the nightly/post-publish harvest will catch up regardless
  } finally {
    refreshing.value = false
  }
}

async function refreshDatasetsCatalog() {
  refreshingDatasets.value = true
  try {
    await api.refreshHtrUnitedDatasets()
  } catch {
    // best-effort refresh; the nightly refresh will catch up regardless
  } finally {
    refreshingDatasets.value = false
  }
}

function facetValues(field) {
  const counts = new Map()
  for (const m of models.value) {
    const values = field === 'license' ? [m.license] : m[field]
    for (const v of values || []) {
      if (!v) continue
      counts.set(v, (counts.get(v) || 0) + 1)
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
}

const languageFacet = computed(() => facetValues('language'))
const scriptFacet = computed(() => facetValues('script'))
const modelTypeFacet = computed(() => facetValues('model_type'))
const licenseFacet = computed(() => facetValues('license'))

function toggle(field, value) {
  const set = selected.value[field]
  if (set.has(value)) set.delete(value)
  else set.add(value)
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return models.value.filter((m) => {
    if (q && !(`${m.title} ${m.summary}`.toLowerCase().includes(q))) return false
    for (const field of ['language', 'script', 'model_type']) {
      const set = selected.value[field]
      if (set.size && !(m[field] || []).some((v) => set.has(v))) return false
    }
    if (selected.value.license.size && !selected.value.license.has(m.license)) return false
    return true
  })
})

const SORTERS = {
  alphabetical: (a, b) => a.title.localeCompare(b.title),
  recency: (a, b) => new Date(b.latest_version?.published_at || 0) - new Date(a.latest_version?.published_at || 0),
  downloads: (a, b) => (b.downloads || 0) - (a.downloads || 0),
}
const sorted = computed(() => [...filtered.value].sort(SORTERS[sortBy.value]))
// The masonry (column-count) layout fills top-to-bottom-then-across, which
// reads fine for an alphabetical index but scrambles a ranked order (#2
// lands below #1 in the same column while #3 sits atop the next column) --
// so ranked sorts (recency/downloads) switch to a row-major grid instead.
const isRanked = computed(() => sortBy.value !== 'alphabetical')

function formatCount(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`
  return `${n}`
}
</script>

<template>
  <div class="pagehead">
    <h1>{{ t('catalog.title') }}</h1>
    <p>{{ t('catalog.subtitle') }}</p>
  </div>

  <div class="shell">
    <aside class="sidebar">
      <div class="sidebar__scroll">
        <div class="search">
          <input v-model="search" :placeholder="t('catalog.search')" />
        </div>

        <div class="facet" v-for="[field, label, values] in [
          ['language', t('catalog.facets.language'), languageFacet],
          ['script', t('catalog.facets.script'), scriptFacet],
          ['model_type', t('catalog.facets.modelType'), modelTypeFacet],
          ['license', t('catalog.facets.license'), licenseFacet],
        ]" :key="field">
          <div class="facet__head">{{ label }}</div>
          <div class="facet__body">
            <label class="opt" :class="{ 'is-on': selected[field].has(value) }" v-for="[value, count] in values" :key="value">
              <span class="opt__box" @click="toggle(field, value)"></span>
              <span class="opt__label" @click="toggle(field, value)">{{ field === 'language' ? languageName(value) : field === 'script' ? scriptName(value) : value }}</span>
              <span class="opt__n">{{ count }}</span>
            </label>
          </div>
        </div>
      </div>
    </aside>

    <div class="results">
      <div class="toolbar">
        <div class="toolbar__count">{{ t('catalog.resultCount', { count: filtered.length }, filtered.length) }}</div>
        <div class="toolbar__spacer"></div>
        <div class="toolbar__ctrl">
          <label for="sortBy">{{ t('catalog.sort.label') }}</label>
          <select id="sortBy" class="select" v-model="sortBy">
            <option value="alphabetical">{{ t('catalog.sort.alphabetical') }}</option>
            <option value="recency">{{ t('catalog.sort.recency') }}</option>
            <option value="downloads">{{ t('catalog.sort.downloads') }}</option>
          </select>
        </div>
        <button
          v-if="auth.isAdmin"
          class="btn btn--ghost"
          :disabled="refreshing"
          @click="refreshFromZenodo"
        >
          {{ refreshing ? t('common.loading') : t('catalog.refresh') }}
        </button>
        <button
          v-if="auth.isAdmin"
          class="btn btn--ghost"
          :disabled="refreshingDatasets"
          @click="refreshDatasetsCatalog"
        >
          {{ refreshingDatasets ? t('common.loading') : t('catalog.refreshDatasets') }}
        </button>
      </div>

      <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>
      <div v-else-if="!filtered.length" class="empty"><p>{{ t('catalog.empty') }}</p></div>
      <div v-else class="grid" :class="{ 'grid--ranked': isRanked }">
        <div class="card" v-for="m in sorted" :key="m.slug">
          <div class="card__band">
            <div class="card__title">{{ m.title }}</div>
          </div>
          <div class="card__body">
            <div class="chips">
              <span class="chip chip--slate" v-if="!m.is_public"><span class="chip__v">{{ t('catalog.yoursSandboxOnly') }}</span></span>
              <span class="chip chip--amber" v-if="m.schema_version === 'v0'"><span class="chip__v">{{ t('catalog.legacy') }}</span></span>
              <span class="chip chip--rose" v-for="l in m.languageChips.shown" :key="l"><span class="chip__k">lang</span><span class="chip__v">{{ languageName(l) }}</span></span>
              <span class="chip chip--slate" v-if="m.languageChips.extra"><span class="chip__v">+{{ m.languageChips.extra }}</span></span>
              <span class="chip chip--rose" v-for="s in m.scriptChips.shown" :key="s"><span class="chip__k">script</span><span class="chip__v">{{ scriptName(s) }}</span></span>
              <span class="chip chip--slate" v-if="m.scriptChips.extra"><span class="chip__v">+{{ m.scriptChips.extra }}</span></span>
              <span class="chip chip--green"><span class="chip__k">license</span><span class="chip__v">{{ m.license }}</span></span>
            </div>
            <p class="card__authors" v-if="m.authorLine">{{ m.authorLine }}</p>
            <p class="card__desc">{{ m.summary }}</p>
            <div class="card__foot">
              <router-link class="btn btn--olive" :to="`/models/${m.slug}`">{{ t('catalog.viewRecord') }}</router-link>
              <a v-if="zenodoUrl(m.latest_version?.doi)" class="lnk" :href="zenodoUrl(m.latest_version.doi)" target="_blank" rel="noopener">
                <svg><use :href="`${baseUrl}icons.svg#external-link-icon`" /></svg>
                {{ t('detail.viewOnZenodo') }}
              </a>
              <span
                class="card__downloads"
                v-if="formatCount(m.downloads)"
                :title="t('catalog.downloads', { count: formatCount(m.downloads) }, m.downloads)"
              >
                <svg><use :href="`${baseUrl}icons.svg#download-icon`" /></svg>
                {{ formatCount(m.downloads) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
