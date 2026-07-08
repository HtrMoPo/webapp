import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import fr from './locales/fr.json'

const STORAGE_KEY = 'htrmopo-locale'

function detectLocale() {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) return stored
  const nav = navigator.language?.slice(0, 2)
  return nav === 'fr' ? 'fr' : 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'en',
  messages: { en, fr },
})

export function setLocale(locale) {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.setAttribute('lang', locale)
}
