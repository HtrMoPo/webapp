import { ref } from 'vue'
import { api } from '../api/client'

// Codes used in this domain (HTR/OCR historical documents) skew heavily
// toward historical/liturgical languages and scripts (e.g. "grc" Ancient
// Greek, "frm" Middle French, "cu" Church Slavic) that browsers'
// Intl.DisplayNames often doesn't have full ICU data for -- it silently
// echoes the code back instead of throwing, so that API can't be trusted
// here. The backend's vendored ISO 639-3 / ISO 15924 tables (already used by
// the upload form's language/script pickers) are the reliable source.
const languageMap = ref(new Map())
const scriptMap = ref(new Map())
let loaded = false

async function ensureLoaded() {
  if (loaded) return
  loaded = true
  const [languages, scripts] = await Promise.all([api.languages(), api.scripts()])
  languageMap.value = new Map(languages.map((l) => [l.code, l.name]))
  scriptMap.value = new Map(scripts.map((s) => [s.code, s.name]))
}

export function useIsoNames() {
  ensureLoaded()
  return {
    languageName: (code) => languageMap.value.get(code) ?? code,
    scriptName: (code) => scriptMap.value.get(code) ?? code,
  }
}
