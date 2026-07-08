<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const baseUrl = import.meta.env.BASE_URL
</script>

<template>
  <section class="hero">
    <h1 v-html="t('home.title')"></h1>
    <p>{{ t('home.subtitle') }}</p>
    <div class="hero__ctas">
      <router-link to="/catalog" class="btn btn--primary btn--lg">{{ t('home.browse') }}</router-link>
      <router-link to="/upload" class="btn btn--ghost btn--lg">{{ t('home.uploadCta') }}</router-link>
    </div>
  </section>

  <section class="section-grid">
    <div class="info-card">
      <h2>{{ t('home.hosting.title') }}</h2>
      <div class="hosting-logo">
        <img :src="`${baseUrl}inria-logo.png`" alt="Inria" height="48" />
      </div>
      <p>{{ t('home.hosting.text') }}</p>
    </div>

    <div class="info-card">
      <h2>{{ t('home.funding.title') }}</h2>
      <div class="hosting-logo">
        <img
          src="https://atrium-research.eu/assets/content/en/pages/communications-kit/clay.png"
          alt="ATRIUM"
          height="48"
        />
      </div>
      <p v-html="t('home.funding.text')"></p>
    </div>

    <div class="info-card">
      <h2>{{ t('home.links.title') }}</h2>
      <p>
        <a href="https://github.com/HtrMoPo/webapp" target="_blank" rel="noopener">{{ t('home.links.repo') }}</a>
        <br />
        <a href="https://github.com/HtrMoPo/HTRMoPo" target="_blank" rel="noopener">{{ t('home.links.htrmopo') }}</a>
      </p>
    </div>
  </section>
</template>

<style scoped>
.hosting-logo {
  margin-bottom: 12px;
}
.hosting-logo img {
  display: block;
  max-width: 100%;
}
</style>
