<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
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
</template>
