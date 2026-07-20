import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import fr from './locales/fr.json'
import de from './locales/de.json'
import it from './locales/it.json'
import es from './locales/es.json'

const STORAGE_KEY = 'htrmopo-locale'
export const SUPPORTED_LOCALES = ['en', 'fr', 'de', 'it', 'es']

function detectLocale() {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && SUPPORTED_LOCALES.includes(stored)) return stored
  const nav = navigator.language?.slice(0, 2)
  return SUPPORTED_LOCALES.includes(nav) ? nav : 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'en',
  messages: { en, fr, de, it, es },
})

export function setLocale(locale) {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.setAttribute('lang', locale)
}
