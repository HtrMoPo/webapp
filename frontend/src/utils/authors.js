export function familyName(name) {
  if (!name) return ''
  const commaIdx = name.indexOf(',')
  if (commaIdx !== -1) return name.slice(0, commaIdx).trim()
  const parts = name.trim().split(/\s+/)
  return parts[parts.length - 1]
}

function givenName(name) {
  if (!name) return ''
  const commaIdx = name.indexOf(',')
  if (commaIdx !== -1) return name.slice(commaIdx + 1).trim()
  const parts = name.trim().split(/\s+/)
  return parts.slice(0, -1).join(' ')
}

export function formatAuthorList(authors) {
  const names = (authors || []).map((a) => a.name).filter(Boolean)
  if (!names.length) return ''
  if (names.length === 1) {
    const given = givenName(names[0])
    return given ? `${familyName(names[0])}, ${given}` : familyName(names[0])
  }
  if (names.length === 2) return `${familyName(names[0])}, and ${familyName(names[1])}`
  return `${familyName(names[0])}, et al.`
}
