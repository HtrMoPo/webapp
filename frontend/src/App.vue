<script setup>
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth, refreshAuth } from './composables/useAuth'
import { setLocale, SUPPORTED_LOCALES } from './i18n'
import { api } from './api/client'

const { t, locale } = useI18n()
const auth = useAuth()
// Bound dynamically (not a static src/href) so Vite's asset-URL transform
// doesn't try to resolve these public/ files as JS module imports.
const baseUrl = import.meta.env.BASE_URL

onMounted(refreshAuth)

const localeNames = { en: 'English', fr: 'Français', de: 'Deutsch', it: 'Italiano', es: 'Español' }

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
      <select class="lang-toggle" :value="locale" @change="setLocale($event.target.value)" :aria-label="t('common.language')">
        <option v-for="code in SUPPORTED_LOCALES" :key="code" :value="code">{{ localeNames[code] }}</option>
      </select>
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
      <div class="site-footer__copy">
        <p>HTRMoPo App — Kraken model catalog, built on the HTRMoPo scheme.</p>
        <ul>
          <li><a href="https://github.com/HtrMoPo/webapp" target="_blank" rel="noopener" :title="t('home.links.repo')">
                <svg class="icon"><use :href="`${baseUrl}icons.svg#github-icon`" /></svg>
                {{ t('home.links.repo') }}
              </a>
          </li>
          <li>
            <a href="https://github.com/HtrMoPo/HTRMoPo" target="_blank" rel="noopener" :title="t('home.links.htrmopo')">
              <svg class="icon"><use :href="`${baseUrl}icons.svg#github-icon`" /></svg>
              {{ t('home.links.htrmopo') }}
            </a>
          </li>
        </ul>
      </div>

      <div class="footer-meta">
        <span class="footer-meta__item">
          <img :src="`${baseUrl}inria-logo.png`" alt="Inria" />
          {{ t('home.hosting.text') }}
        </span>
        <span class="footer-meta__item">
          <img src="https://atrium-research.eu/assets/content/en/pages/communications-kit/clay.png" alt="ATRIUM" />
          <span v-html="t('home.funding.text')"></span>
        </span>
      </div>

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

.footer-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  margin-top: 14px;
  font-size: 13px;
  color: var(--ink-3);
  line-height: 1.55;
}
.footer-meta__item {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 440px;
}
.footer-meta__item img {
  height: 22px;
  width: auto;
  flex-shrink: 0;
  opacity: 0.8;
}
.footer-meta__item :deep(a) {
  color: var(--ink-3);
  text-decoration: underline;
}

.site-footer__copy ul {
  display: flex;
  gap: 16px;
  margin-top: 10px;
  padding: 0;
  list-style: none;
}
.site-footer__copy ul a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-3);
}
.site-footer__copy ul a:hover {
  color: var(--ink-2);
}
.site-footer__copy .icon {
  width: 16px;
  height: 16px;
  opacity: 0.8;
}
</style>
