// Model detail page URLs are DOI-based: /models/<doi-slug>/<title-slug>.
// The DOI slug (Zenodo's concept DOI with "/" swapped for "-", mirroring
// backend/app/slugs.py's doi_to_url_slug) is the canonical, stable part --
// it's what the backend actually looks up. The title slug afterwards is
// purely cosmetic/SEO (readability in the URL bar); it's never read back.
const COMBINING_DIACRITICS = /[̀-ͯ]/g

export function titleSlug(title) {
  return (
    (title || '')
      .normalize('NFKD')
      .replace(COMBINING_DIACRITICS, '')
      .replace(/[^a-zA-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .toLowerCase() || 'model'
  )
}

export function modelPath(doiSlug, title) {
  return doiSlug ? `/models/${doiSlug}/${titleSlug(title)}` : null
}
