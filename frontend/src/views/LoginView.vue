<script setup>
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'

const { t } = useI18n()
</script>

<template>
  <div class="pagehead">
    <h1>{{ t('nav.login') }}</h1>
    <p>{{ t('auth.loginPrompt') }}</p>
  </div>
  <div class="page-content">
    <a class="btn btn--olive btn--lg" :href="api.loginUrl()">{{ t('nav.login') }}</a>
  </div>
</template>
