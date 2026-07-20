<script setup>
import { load as loadYaml } from 'js-yaml'
import { marked } from 'marked'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'
import { useIsoNames } from '../utils/iso'

const props = defineProps({ slug: { type: String, required: true } })
const { t } = useI18n()
const { languageName, scriptName } = useIsoNames()
const auth = useAuth()
const baseUrl = import.meta.env.BASE_URL

const record = ref(null)
const loading = ref(true)

onMounted(async () => {
  record.value = await api.getModel(props.slug)
  loading.value = false
})

const latest = computed(() => record.value?.versions?.[record.value.versions.length - 1])
// card_body_md is real Markdown (the WYSIWYG editor's HTML is converted to
// Markdown before ever being sent/stored -- and harvested community records'
// README bodies are real Markdown to begin with), so render it for display.
const bodyHtml = computed(() => (latest.value?.card_body_md ? marked.parse(latest.value.card_body_md) : ''))

const metadata = computed(() => {
  const yaml = latest.value?.card_yaml
  const match = yaml?.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  return match ? loadYaml(match[1]) || {} : {}
})
const authors = computed(() => metadata.value.authors || [])
const metrics = computed(() => Object.entries(metadata.value.metrics || {}))

function metricLabel(key) {
  return key.replace(/_/g, ' ')
}

function zenodoUrl(doi) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}` : '#'
}

function fileUrl(doi, filename) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}/files/${encodeURIComponent(filename)}?download=1` : '#'
}

function formatSize(bytes) {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

const isOwner = computed(() => record.value?.is_owner ?? false)
</script>

<template>
  <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>
  <template v-else-if="record">
    <div class="pagehead">
      <h1>{{ record.title }}</h1>
      <p>{{ record.summary }}</p>
    </div>
    <div class="page-content">
      <div class="chips" style="margin-bottom: 20px">
        <span class="chip chip--amber" v-if="record.schema_version === 'v0'"><span class="chip__v">{{ t('detail.legacyBadge') }}</span></span>
        <span class="chip chip--rose" v-for="l in record.language" :key="l"><span class="chip__k">lang</span><span class="chip__v">{{ languageName(l) }}</span></span>
        <span class="chip chip--rose" v-for="s in record.script" :key="s"><span class="chip__k">script</span><span class="chip__v">{{ scriptName(s) }}</span></span>
        <span class="chip chip--green"><span class="chip__k">license</span><span class="chip__v">{{ record.license }}</span></span>
      </div>

      <div class="form-section" v-if="authors.length">
        <h2>{{ t('detail.authors') }}</h2>
        <ul class="author-list">
          <li v-for="(a, i) in authors" :key="i">
            {{ a.name }}
            <a v-if="a.orcid" :href="a.orcid" target="_blank" rel="noopener" :title="a.orcid">
              <svg class="orcid-icon"><use :href="`${baseUrl}icons.svg#orcid-icon`" /></svg>
            </a>
          </li>
        </ul>
      </div>

      <div class="form-section" v-if="metrics.length">
        <h2>{{ t('detail.metrics') }}</h2>
        <table class="metrics-table">
          <tbody>
            <tr v-for="[key, value] in metrics" :key="key">
              <td>{{ metricLabel(key) }}</td>
              <td>{{ value }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="prose" v-html="bodyHtml"></div>

      <div class="form-section" v-if="latest?.files?.length">
        <h2>{{ t('detail.files') }}</h2>
        <ul class="file-list">
          <li v-for="f in latest.files" :key="f.filename">
            <a :href="fileUrl(latest.doi, f.filename)" target="_blank" rel="noopener">{{ f.filename }}</a>
            <span class="file-size">{{ formatSize(f.size) }}</span>
          </li>
        </ul>
      </div>

      <div class="form-section" v-if="isOwner">
        <p class="form-help" v-if="record.schema_version === 'v0'" style="margin-top:0">{{ t('detail.legacyOwnerNote') }}</p>
        <router-link
          class="btn"
          :class="record.schema_version === 'v0' ? 'btn--primary' : 'btn--olive'"
          :to="`/models/${record.id}/new-version`"
        >{{ record.schema_version === 'v0' ? t('myModels.upgrade') : t('detail.newVersion') }}</router-link>
      </div>

      <div class="form-section">
        <h2>{{ t('detail.versions') }}</h2>
        <ul>
          <li v-for="v in record.versions" :key="v.id">
            <a :href="zenodoUrl(v.doi)" target="_blank" rel="noopener">{{ v.doi }}</a>
            — {{ t('detail.published') }} {{ v.published_at }}
          </li>
        </ul>
      </div>
    </div>
  </template>
</template>

<style scoped>
.author-list { list-style: none; margin: 0; padding: 0; }
.author-list li { display: flex; align-items: center; gap: 6px; padding: 3px 0; }
.orcid-icon { width: 16px; height: 16px; vertical-align: middle; }

.metrics-table { border-collapse: collapse; }
.metrics-table td { padding: 3px 16px 3px 0; text-transform: capitalize; }
.metrics-table td:last-child { text-transform: none; font-family: var(--mono); text-align: right; }

.file-list { list-style: none; margin: 0; padding: 0; }
.file-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 0; }
.file-size { color: var(--ink-3); font-size: 12.5px; white-space: nowrap; }
</style>
