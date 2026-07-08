import { reactive } from 'vue'
import { api } from '../api/client'

const state = reactive({
  loaded: false,
  authenticated: false,
  displayName: '',
  isAdmin: false,
  zenodoEnv: 'sandbox',
  zenodoBaseUrl: 'https://sandbox.zenodo.org',
})

export async function refreshAuth() {
  const [me, config] = await Promise.all([api.me(), api.config()])
  state.authenticated = me.authenticated
  state.displayName = me.display_name ?? ''
  state.isAdmin = me.is_admin ?? false
  state.zenodoEnv = config.zenodo_env
  state.zenodoBaseUrl = config.zenodo_base_url
  state.loaded = true
}

export function useAuth() {
  return state
}
