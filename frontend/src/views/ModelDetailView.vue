<script setup>
import { marked } from 'marked'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'

const props = defineProps({ slug: { type: String, required: true } })
const { t } = useI18n()
const auth = useAuth()

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

function zenodoUrl(doi) {
  const recid = doi?.match(/zenodo\.(\d+)/)?.[1]
  return recid ? `${auth.zenodoBaseUrl}/records/${recid}` : '#'
}

const isOwner = computed(() => auth.authenticated)
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
        <span class="chip chip--rose" v-for="l in record.language" :key="l"><span class="chip__k">lang</span><span class="chip__v">{{ l }}</span></span>
        <span class="chip chip--rose" v-for="s in record.script" :key="s"><span class="chip__k">script</span><span class="chip__v">{{ s }}</span></span>
        <span class="chip chip--green"><span class="chip__k">license</span><span class="chip__v">{{ record.license }}</span></span>
      </div>

      <div class="prose" v-html="bodyHtml"></div>

      <div class="form-section" v-if="isOwner">
        <router-link class="btn btn--olive" :to="`/models/${record.id}/new-version`">{{ t('detail.newVersion') }}</router-link>
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
