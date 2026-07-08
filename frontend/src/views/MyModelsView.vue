<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'

const { t } = useI18n()
const records = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  records.value = await api.myModels()
  loading.value = false
}

onMounted(load)

async function discard(versionId) {
  await api.discardDraft(versionId)
  await load()
}
</script>

<template>
  <div class="pagehead">
    <h1>{{ t('nav.myModels') }}</h1>
  </div>
  <div class="page-content">
    <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>
    <div v-else class="form-section" v-for="r in records" :key="r.id">
      <h2>{{ r.title || r.slug }}</h2>
      <ul>
        <li v-for="v in r.versions" :key="v.id">
          <template v-if="v.status === 'draft'">
            draft —
            <router-link :to="`/models/${r.id}/new-version?version=${v.id}`">continue</router-link>
            —
            <button class="btn btn--ghost" @click="discard(v.id)">{{ t('form.discard') }}</button>
          </template>
          <template v-else>
            {{ v.doi }} — {{ t('detail.published') }} {{ v.published_at }}
            <span class="chip chip--slate" v-if="v.zenodo_env === 'sandbox'">
              <span class="chip__v">sandbox — not in public catalog</span>
            </span>
          </template>
        </li>
      </ul>
      <router-link class="btn btn--olive" :to="`/models/${r.id}/new-version`">{{ t('detail.newVersion') }}</router-link>
    </div>
  </div>
</template>
