<script setup>
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth, refreshAuth } from './composables/useAuth'
import { setLocale } from './i18n'
import { api } from './api/client'

const { t, locale } = useI18n()
const auth = useAuth()

onMounted(refreshAuth)

function toggleLocale() {
  setLocale(locale.value === 'en' ? 'fr' : 'en')
}

async function logout() {
  await api.logout()
  await refreshAuth()
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__inner">
      <router-link to="/" class="brand"><b>HTR</b>MoPo</router-link>
      <nav class="nav">
        <router-link to="/catalog">{{ t('nav.catalog') }}</router-link>
        <router-link v-if="auth.authenticated" to="/mine">{{ t('nav.myModels') }}</router-link>
        <router-link v-if="auth.authenticated" to="/upload">{{ t('nav.upload') }}</router-link>
      </nav>
      <button class="lang-toggle" @click="toggleLocale">{{ locale === 'en' ? 'FR' : 'EN' }}</button>
      <a v-if="!auth.authenticated" class="btn btn--olive" :href="api.loginUrl()">{{ t('nav.login') }}</a>
      <button v-else class="btn btn--ghost" @click="logout">{{ t('nav.logout') }}</button>
    </div>
  </header>

  <div v-if="auth.loaded && auth.zenodoEnv === 'sandbox'" class="sandbox-banner">
    {{ t('auth.sandboxBanner') }}
  </div>

  <router-view />

  <footer class="site-footer">
    <div class="site-footer__inner">
      <div class="site-footer__copy">HTRMoPo App — Kraken model catalog, built on the HTRMoPo scheme.</div>
    </div>
  </footer>
</template>

<style scoped>
.sandbox-banner {
  background: var(--rose-bg);
  color: var(--rose-ink);
  border-bottom: 1px solid var(--rose-line);
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
}
</style>
