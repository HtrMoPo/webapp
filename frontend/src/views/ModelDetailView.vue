<script setup>
import { load as loadYaml } from 'js-yaml'
import { marked } from 'marked'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'
import { useIsoNames } from '../utils/iso'
import { modelPath } from '../utils/modelUrl'

const props = defineProps({ doiSlug: { type: String, required: true } })
const { t, locale } = useI18n()
const { languageName, scriptName } = useIsoNames()
const auth = useAuth()
const baseUrl = import.meta.env.BASE_URL

const record = ref(null)
const loading = ref(true)
const citationBibtex = ref('')
const citationLoading = ref(false)

function zenodoApiBase(zenodoEnv) {
  return zenodoEnv === 'production' ? 'https://zenodo.org' : 'https://sandbox.zenodo.org'
}

async function loadZenodoCitation() {
  // Always fetched: metadata.citation is just a link to an associated paper
  // (if any), not a formatted citation for the model itself, so the BibTeX
  // block always comes from Zenodo's own auto-generated citation for the
  // record. Zenodo's public records API supports this via content
  // negotiation, no auth needed.
  const recid = latest.value?.doi?.match(/zenodo\.(\d+)/)?.[1]
  if (!recid) return
  citationLoading.value = true
  try {
    const base = zenodoApiBase(latest.value.zenodo_env)
    const resp = await fetch(`${base}/api/records/${recid}`, { headers: { Accept: 'application/x-bibtex' } })
    if (resp.ok) citationBibtex.value = await resp.text()
  } catch {
    // best-effort -- the citation card just won't show the BibTeX block
  } finally {
    citationLoading.value = false
  }
}

const citationCopied = ref(false)
async function copyCitation() {
  await navigator.clipboard.writeText(citationBibtex.value)
  citationCopied.value = true
  setTimeout(() => { citationCopied.value = false }, 1500)
}

// Vue Router reuses this component instance (rather than remounting) when
// navigating between two routes that both match `/models/:doiSlug/:titleSlug?`
// -- e.g. clicking the "Previous version(s)"/"Superseded by" links on this
// very page -- so the data load has to react to the doiSlug prop changing,
// not just run once on mount.
watch(
  () => props.doiSlug,
  async (doiSlug) => {
    loading.value = true
    citationBibtex.value = ''
    record.value = await api.getModel(doiSlug)
    loading.value = false
    await loadZenodoCitation()
  },
  { immediate: true }
)

// The API doesn't guarantee `versions` is ordered by publish date (harvested
// records can be inserted in a different order than they were published),
// so sort explicitly rather than trusting array position.
const sortedVersions = computed(() =>
  [...(record.value?.versions || [])].sort((a, b) => new Date(b.published_at) - new Date(a.published_at))
)
const latest = computed(() => sortedVersions.value[0])
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
const krakenCommand = computed(() =>
  metadata.value.software_name === 'kraken' && latest.value?.doi ? `kraken get ${latest.value.doi}` : null
)
const copied = ref(false)
async function copyKrakenCommand() {
  await navigator.clipboard.writeText(krakenCommand.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}

function metricLabel(key) {
  return key.replace(/_/g, ' ')
}

function zenodoUrl(doi) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}` : '#'
}

function paperUrl(paper) {
  return paper.scheme === 'doi' ? `https://doi.org/${paper.identifier}` : paper.identifier
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

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(locale.value, { year: 'numeric', month: 'short', day: 'numeric' })
}

const isOwner = computed(() => record.value?.is_owner ?? false)
</script>

<template>
  <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>
  <template v-else-if="record">
    <div class="pagehead">
      <h1>{{ record.title }}</h1>
      <div class="chips">
        <span class="chip chip--amber" v-if="record.schema_version === 'v0'"><span class="chip__v">{{ t('detail.legacyBadge') }}</span></span>
        <span class="chip chip--rose" v-for="l in record.language" :key="l"><span class="chip__k">lang</span><span class="chip__v">{{ languageName(l) }}</span></span>
        <span class="chip chip--rose" v-for="s in record.script" :key="s"><span class="chip__k">script</span><span class="chip__v">{{ scriptName(s) }}</span></span>
        <span class="chip chip--green"><span class="chip__k">license</span><span class="chip__v">{{ record.license }}</span></span>
      </div>
      <p>{{ record.summary }}</p>
    </div>

    <div class="detail-shell">
      <div class="detail-main">
        <div class="prose" v-html="bodyHtml"></div>

        <div class="form-section" v-if="isOwner">
          <p class="form-help" v-if="record.schema_version === 'v0'" style="margin-top:0">{{ t('detail.legacyOwnerNote') }}</p>
          <router-link
            class="btn"
            :class="record.schema_version === 'v0' ? 'btn--primary' : 'btn--olive'"
            :to="`/models/${record.id}/new-version`"
          >{{ record.schema_version === 'v0' ? t('myModels.upgrade') : t('detail.newVersion') }}</router-link>
        </div>
      </div>

      <aside class="detail-aside">
        <div class="meta-card" v-if="record.obsoleted_by">
          <h3>{{ t('detail.obsoletedBy') }}</h3>
          <router-link v-if="record.obsoleted_by.doi_slug" class="lnk" :to="modelPath(record.obsoleted_by.doi_slug, record.obsoleted_by.title)">{{ record.obsoleted_by.title }}</router-link>
          <a v-else class="lnk" :href="zenodoUrl(record.obsoleted_by.doi)" target="_blank" rel="noopener">{{ record.obsoleted_by.doi }}</a>
        </div>

        <div class="meta-card" v-if="record.variant_of">
          <h3>{{ t('detail.variantOf') }}</h3>
          <router-link v-if="record.variant_of.doi_slug" class="lnk" :to="modelPath(record.variant_of.doi_slug, record.variant_of.title)">{{ record.variant_of.title }}</router-link>
          <a v-else class="lnk" :href="zenodoUrl(record.variant_of.doi)" target="_blank" rel="noopener">{{ record.variant_of.doi }}</a>
        </div>

        <div class="meta-card" v-if="authors.length">
          <h3>{{ t('detail.authors') }}</h3>
          <ul class="author-list">
            <li v-for="(a, i) in authors" :key="i">
              <span>{{ a.name }}</span>
              <a v-if="a.orcid" :href="a.orcid" target="_blank" rel="noopener" :title="a.orcid">
                <svg class="orcid-icon"><use :href="`${baseUrl}icons.svg#orcid-icon`" /></svg>
              </a>
            </li>
          </ul>
        </div>

        <div class="meta-card" v-if="citationBibtex || citationLoading || metadata.citation">
          <h3>{{ t('detail.citation') }}</h3>
          <p class="citation-reminder">{{ t('detail.citationReminder') }}</p>
          <p class="form-help" v-if="citationLoading && !citationBibtex">{{ t('common.loading') }}</p>
          <template v-if="citationBibtex">
            <pre class="bibtex">{{ citationBibtex }}</pre>
            <button type="button" class="bibtex-copy" @click="copyCitation">{{ citationCopied ? t('detail.copied') : t('detail.copyCitation') }}</button>
          </template>
          <div class="citation-paper" v-if="metadata.citation">
            <a class="lnk" :href="metadata.citation" target="_blank" rel="noopener">
              <svg><use :href="`${baseUrl}icons.svg#external-link-icon`" /></svg>
              {{ t('detail.readPaper') }}
            </a>
          </div>
        </div>

        <div class="meta-card" v-if="metrics.length">
          <h3>{{ t('detail.metrics') }}</h3>
          <div class="stat-grid">
            <div class="stat" v-for="[key, value] in metrics" :key="key">
              <b>{{ value }}</b>
              <span>{{ metricLabel(key) }}</span>
            </div>
          </div>
        </div>

        <div class="meta-card" v-if="krakenCommand">
          <h3>{{ t('detail.downloadKraken') }}</h3>
          <div class="kraken-cmd">
            <code>{{ krakenCommand }}</code>
            <button type="button" class="kraken-cmd__copy" @click="copyKrakenCommand">{{ copied ? t('detail.copied') : t('detail.copy') }}</button>
          </div>
        </div>

        <div class="meta-card" v-if="latest?.files?.length">
          <h3>{{ t('detail.files') }}</h3>
          <ul class="file-list">
            <li v-for="f in latest.files" :key="f.filename">
              <a :href="fileUrl(latest.doi, f.filename)" target="_blank" rel="noopener" :title="f.filename">{{ f.filename }}</a>
              <span class="file-size">{{ formatSize(f.size) }}</span>
            </li>
          </ul>
        </div>

        <div class="meta-card" v-if="record.obsoletes?.length">
          <h3>{{ t('detail.previousVersions') }}</h3>
          <ul class="version-list">
            <li v-for="o in record.obsoletes" :key="o.doi_slug || o.doi">
              <router-link v-if="o.doi_slug" class="lnk" :to="modelPath(o.doi_slug, o.title)">{{ o.title }}</router-link>
              <a v-else class="lnk" :href="zenodoUrl(o.doi)" target="_blank" rel="noopener">{{ o.doi }}</a>
            </li>
          </ul>
        </div>

        <div class="meta-card" v-if="record.variants?.length">
          <h3>{{ t('detail.variants') }}</h3>
          <ul class="version-list">
            <li v-for="v in record.variants" :key="v.doi_slug || v.doi">
              <router-link v-if="v.doi_slug" class="lnk" :to="modelPath(v.doi_slug, v.title)">{{ v.title }}</router-link>
              <a v-else class="lnk" :href="zenodoUrl(v.doi)" target="_blank" rel="noopener">{{ v.doi }}</a>
            </li>
          </ul>
        </div>

        <div class="meta-card" v-if="record.documented_by?.length">
          <h3>{{ t('detail.relatedPapers') }}</h3>
          <ul class="version-list">
            <li v-for="p in record.documented_by" :key="p.identifier">
              <a class="lnk" :href="paperUrl(p)" target="_blank" rel="noopener">{{ p.title || p.identifier }}</a>
            </li>
          </ul>
        </div>

        <div class="meta-card">
          <h3>{{ t('detail.versions') }}</h3>
          <ul class="version-list">
            <li v-for="(v, i) in sortedVersions" :key="v.id">
              <div class="version-list__row">
                <a :href="zenodoUrl(v.doi)" target="_blank" rel="noopener">{{ v.doi }}</a>
                <span class="chip chip--slate" v-if="i === 0"><span class="chip__v">{{ t('detail.latest') }}</span></span>
              </div>
              <span class="version-list__date">{{ t('detail.published') }} {{ formatDate(v.published_at) }}</span>
            </li>
          </ul>
        </div>
      </aside>
    </div>
  </template>
</template>

<style scoped>
.pagehead .chips { margin: 14px 0; }

.detail-shell {
  max-width: var(--maxw); margin: 0 auto; padding: 28px 28px 80px;
  display: grid; grid-template-columns: 1fr var(--sidebar-w); gap: 30px;
  align-items: start;
}
.detail-main { min-width: 0; }
.detail-aside { position: sticky; top: 76px; display: flex; flex-direction: column; gap: 16px; }

.meta-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 20px; box-shadow: var(--shadow-sm);
}
.meta-card h3 {
  font-family: var(--serif); font-size: 15px; font-weight: 600;
  color: var(--ink); margin: 0 0 14px; padding-bottom: 10px;
  border-bottom: 1px solid var(--line); letter-spacing: -.01em;
}

.author-list { list-style: none; margin: 0; padding: 0; }
.author-list li { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 4px 0; font-size: 14px; color: var(--ink-2); }
.orcid-icon { width: 16px; height: 16px; vertical-align: middle; flex-shrink: 0; }

.citation-reminder { font-size: 12.5px; line-height: 1.55; color: var(--ink-3); font-style: italic; margin: 0 0 12px; }
.meta-card .bibtex { font-size: 10.5px; margin: 0; }
.bibtex-copy {
  display: block; margin: 8px 0 0 auto;
  font-family: var(--sans); font-size: 11px; font-weight: 600;
  background: var(--paper-2); color: var(--ink-2); border: 1px solid var(--line-2);
  border-radius: 5px; padding: 5px 9px; cursor: pointer;
}
.bibtex-copy:hover { background: var(--paper); color: var(--ink); }
.citation-paper { text-align: center; margin-top: 14px; }
.citation-paper .lnk { display: inline-flex; }

.stat-grid { display: flex; flex-wrap: wrap; gap: 16px 24px; }
.stat { display: flex; flex-direction: column; }
.stat b { font-family: var(--mono); font-size: 16px; color: var(--ink); font-weight: 600; }
.stat span { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .03em; margin-top: 2px; }

.kraken-cmd {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: #2c2e26; border-radius: 7px; padding: 8px 8px 8px 12px;
}
.kraken-cmd code {
  font-family: var(--mono); font-size: 12px; color: #c7d0b0;
  overflow-x: auto; white-space: nowrap; flex: 1;
}
.kraken-cmd__copy {
  font-family: var(--sans); font-size: 11px; font-weight: 600; flex-shrink: 0;
  background: rgba(255,255,255,.1); color: #e4e2d8; border: none;
  border-radius: 5px; padding: 5px 9px; cursor: pointer;
}
.kraken-cmd__copy:hover { background: rgba(255,255,255,.18); }

.file-list { list-style: none; margin: 0; padding: 0; }
.file-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 5px 0; font-size: 13.5px; }
.file-list a { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { color: var(--ink-3); font-size: 12px; white-space: nowrap; flex-shrink: 0; }

.version-list { list-style: none; margin: 0; padding: 0; }
.version-list li { padding: 8px 0; border-bottom: 1px solid var(--line); }
.version-list li:last-child { border-bottom: none; padding-bottom: 0; }
.version-list li:first-child { padding-top: 0; }
.version-list__row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.version-list__row a { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-list__date { display: block; font-size: 12px; color: var(--ink-3); margin-top: 2px; }

@media (max-width: 1080px) {
  .detail-shell { grid-template-columns: 1fr; }
  .detail-aside { position: static; }
}
</style>
