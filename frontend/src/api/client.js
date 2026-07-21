const API_BASE = import.meta.env.VITE_API_BASE_PATH ?? '/api'

async function request(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail
    try {
      detail = await resp.json()
    } catch {
      detail = { detail: resp.statusText }
    }
    let message = 'request_failed'
    if (typeof detail.detail === 'string') message = detail.detail
    else if (detail.detail?.errors?.length) message = detail.detail.errors.join('; ')
    const err = new Error(message)
    err.status = resp.status
    err.detail = detail.detail
    throw err
  }
  if (resp.status === 204) return null
  return resp.json()
}

export const api = {
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  loginUrl: () => `${API_BASE}/auth/zenodo/login`,

  config: () => request('/meta/config'),
  languages: () => request('/meta/languages'),
  scripts: () => request('/meta/scripts'),
  licenses: () => request('/meta/licenses'),
  modelTypes: () => request('/meta/model-types'),
  htrUnitedDatasets: () => request('/meta/datasets'),
  refreshHtrUnitedDatasets: () => request('/meta/datasets/refresh', { method: 'POST' }),

  listModels: () => request('/models'),
  myModels: () => request('/models/mine'),
  syncMine: () => request('/models/mine/sync', { method: 'POST' }),
  getModel: (doiSlug) => request(`/models/${doiSlug}`),

  createDraft: (payload) => request('/models/drafts', { method: 'POST', body: JSON.stringify(payload) }),
  createVersionDraft: (recordId, payload) =>
    request(`/models/${recordId}/versions/draft`, { method: 'POST', body: JSON.stringify(payload) }),
  updateDraft: (versionId, payload) =>
    request(`/models/versions/${versionId}`, { method: 'PUT', body: JSON.stringify(payload) }),
  uploadFile: (versionId, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/models/versions/${versionId}/files`, { method: 'POST', body: form })
  },
  deleteFile: (versionId, filename) =>
    request(`/models/versions/${versionId}/files/${encodeURIComponent(filename)}`, { method: 'DELETE' }),
  discardDraft: (versionId) => request(`/models/versions/${versionId}/discard`, { method: 'POST' }),
  publishDraft: (versionId, priv, version) =>
    request(`/models/versions/${versionId}/publish`, {
      method: 'POST',
      body: JSON.stringify({ private: priv, version: version || '' }),
    }),
  publishProgress: (versionId) => request(`/models/versions/${versionId}/publish/progress`),
  triggerHarvest: () => request('/models/harvest', { method: 'POST' }),
}
