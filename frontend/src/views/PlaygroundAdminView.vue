<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'

const { t } = useI18n()

const active = ref([])
const recentFinished = ref([])
const loading = ref(true)
const loadError = ref('')
const cancellingId = ref('')
const clearing = ref(false)

// Result JSON is fetched on demand (not with the list) since it can be
// sizeable -- keyed by job id so it's cached rather than refetched every
// time a row is toggled open, and cleared whenever a poll drops that job
// (e.g. it got pruned) so a stale result never lingers under a new job.
const expandedId = ref('')
const results = ref({})
const resultLoading = ref('')

async function load() {
  try {
    const data = await api.playgroundAdminJobs()
    active.value = data.active
    recentFinished.value = data.recent_finished
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message
  } finally {
    loading.value = false
  }
}

let poll
onMounted(() => {
  load()
  // Auto-refreshes so the queue view stays current without manual reloads --
  // this is a live operational view, not a one-shot report.
  poll = setInterval(load, 5000)
})
onBeforeUnmount(() => clearInterval(poll))

async function cancel(jobId) {
  cancellingId.value = jobId
  try {
    await api.cancelPlaygroundJob(jobId)
    await load()
  } finally {
    cancellingId.value = ''
  }
}

async function toggleResult(jobId) {
  if (expandedId.value === jobId) {
    expandedId.value = ''
    return
  }
  expandedId.value = jobId
  if (!(jobId in results.value)) {
    resultLoading.value = jobId
    try {
      const detail = await api.playgroundAdminJob(jobId)
      results.value = { ...results.value, [jobId]: detail.result }
    } finally {
      resultLoading.value = ''
    }
  }
}

async function clearQueue() {
  clearing.value = true
  try {
    await api.clearPlaygroundQueue()
    await load()
  } finally {
    clearing.value = false
  }
}
</script>

<template>
  <div class="pagehead">
    <h1>{{ t('playgroundAdmin.title') }}</h1>
  </div>
  <div class="page-content">
    <p v-if="loadError" class="playground-error">{{ loadError }}</p>

    <div v-if="loading" class="loading"><div class="spinner"></div>{{ t('common.loading') }}</div>

    <template v-else>
      <div class="toolbar">
        <h2 class="toolbar__spacer">{{ t('playgroundAdmin.queue') }} ({{ active.length }})</h2>
        <button
          class="btn btn--ghost"
          :disabled="clearing || !active.some((j) => j.status === 'queued')"
          @click="clearQueue"
        >
          {{ clearing ? t('common.loading') : t('playgroundAdmin.clearQueue') }}
        </button>
      </div>

      <table class="admin-table" v-if="active.length">
        <thead>
          <tr>
            <th>{{ t('playgroundAdmin.status') }}</th>
            <th>{{ t('playgroundAdmin.created') }}</th>
            <th>{{ t('playgroundAdmin.models') }}</th>
            <th>{{ t('playgroundAdmin.ip') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in active" :key="job.id">
            <td><span class="status-badge" :class="`status-badge--${job.status}`">{{ job.status }}</span></td>
            <td>{{ new Date(job.created_at).toLocaleString() }}</td>
            <td>
              <div>{{ job.segmentation }}</div>
              <div>{{ job.recognition }}</div>
              <div v-if="job.region">{{ job.region }}</div>
            </td>
            <td class="admin-table__ip" :title="job.ip_hash">{{ job.ip_hash.slice(0, 10) }}…</td>
            <td>
              <button class="btn btn--ghost" :disabled="cancellingId === job.id" @click="cancel(job.id)">
                {{ cancellingId === job.id ? t('common.loading') : t('playgroundAdmin.cancel') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="form-help">{{ t('playgroundAdmin.queueEmpty') }}</p>

      <h2>{{ t('playgroundAdmin.recentFinished') }}</h2>
      <table class="admin-table" v-if="recentFinished.length">
        <thead>
          <tr>
            <th>{{ t('playgroundAdmin.status') }}</th>
            <th>{{ t('playgroundAdmin.created') }}</th>
            <th>{{ t('playgroundAdmin.finished') }}</th>
            <th>{{ t('playgroundAdmin.models') }}</th>
            <th>{{ t('playgroundAdmin.ip') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="job in recentFinished" :key="job.id">
            <tr>
              <td><span class="status-badge" :class="`status-badge--${job.status}`">{{ job.status }}</span></td>
              <td>{{ new Date(job.created_at).toLocaleString() }}</td>
              <td>{{ job.finished_at ? new Date(job.finished_at).toLocaleString() : '—' }}</td>
              <td>
                <div>{{ job.segmentation }}</div>
                <div>{{ job.recognition }}</div>
                <div v-if="job.region">{{ job.region }}</div>
                <p v-if="job.error_message" class="form-help">{{ job.error_message }}</p>
              </td>
              <td class="admin-table__ip" :title="job.ip_hash">{{ job.ip_hash.slice(0, 10) }}…</td>
              <td class="admin-table__actions">
                <button v-if="job.status === 'done'" class="btn btn--ghost" @click="toggleResult(job.id)">
                  {{ expandedId === job.id ? t('playgroundAdmin.hideResult') : t('playgroundAdmin.viewResult') }}
                </button>
                <button class="btn btn--ghost" :disabled="cancellingId === job.id" @click="cancel(job.id)">
                  {{ cancellingId === job.id ? t('common.loading') : t('playgroundAdmin.remove') }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedId === job.id">
              <td colspan="6">
                <div v-if="resultLoading === job.id" class="loading"><div class="spinner spinner--sm"></div>{{ t('common.loading') }}</div>
                <pre v-else class="admin-result">{{ JSON.stringify(results[job.id], null, 2) }}</pre>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else class="form-help">{{ t('playgroundAdmin.recentFinishedEmpty') }}</p>
    </template>
  </div>
</template>

<style scoped>
.admin-table { width: 100%; border-collapse: collapse; margin: 12px 0 28px; font-size: 13.5px; }
.admin-table th, .admin-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line-2); vertical-align: top; }
.admin-table th { color: var(--ink-3); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .02em; }
.admin-table__ip { font-family: var(--mono, monospace); color: var(--ink-3); }
.admin-table__actions { display: flex; gap: 6px; flex-wrap: wrap; }

.admin-result {
  max-height: 420px; overflow: auto; margin: 6px 0; padding: 12px 14px;
  border-radius: var(--radius-sm); background: var(--paper-2); border: 1px solid var(--line-2);
  font-family: var(--mono, monospace); font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
}

.status-badge {
  display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 11.5px;
  font-weight: 700; letter-spacing: .01em; border: 1px solid var(--slate-line);
  background: var(--slate-bg); color: var(--slate-ink);
}
.status-badge--running { border-color: var(--green-line); background: var(--green-bg); color: var(--green-ink); }
.status-badge--done { border-color: var(--green-line); background: var(--green-bg); color: var(--green-ink); }
.status-badge--error { border-color: var(--rose-line); background: var(--rose-bg); color: var(--rose-ink); }
</style>
