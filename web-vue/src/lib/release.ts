export type ReleaseInfo = {
  version: string
  date: string
  items: { type: string; content: string }[]
}

export type ReleaseInlineSegment = {
  kind: 'text' | 'code'
  content: string
}

export function splitReleaseInlineCode(value: string): ReleaseInlineSegment[] {
  const source = String(value || '')
  const segments: ReleaseInlineSegment[] = []
  const pattern = /`([^`\n]+)`/g
  let cursor = 0

  for (const match of source.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) {
      segments.push({ kind: 'text', content: source.slice(cursor, index) })
    }
    segments.push({ kind: 'code', content: match[1] })
    cursor = index + match[0].length
  }

  if (cursor < source.length) {
    segments.push({ kind: 'text', content: source.slice(cursor) })
  }
  return segments.length ? segments : [{ kind: 'text', content: source }]
}

export function parseChangelog(content: string): ReleaseInfo[] {
  return content
    .split(/^## /m)
    .slice(1)
    .map((block) => {
      const [title = '', ...lines] = block.trim().split('\n')
      const releaseTitle = title.trim().match(/^(.+?)\s+-\s+(.+)$/)
      const version = releaseTitle?.[1] || title.trim()
      const date = releaseTitle?.[2] || ''
      return {
        version: version.trim(),
        date: date.trim(),
        items: lines
          .map((line) => line.trim().match(/^\+\s+\[(.+?)]\s+(.+)$/))
          .filter((match): match is RegExpMatchArray => Boolean(match))
          .map((match) => ({ type: match[1], content: match[2] })),
      }
    })
    .filter((release) => release.items.length)
}

export function parseReleaseNotes(version: string, publishedAt: string, content: string): ReleaseInfo[] {
  const items: ReleaseInfo['items'] = []
  for (const rawLine of String(content || '').split('\n')) {
    const line = rawLine.trim()
    const match = line.match(/^\+\s+\[(.+?)]\s+(.+)$/)
    if (match) {
      items.push({ type: match[1], content: match[2] })
      continue
    }
    if (line && items.length && !line.startsWith('#') && !line.startsWith('>')) {
      items[items.length - 1].content += ` ${line}`
    }
  }
  if (!items.length) return []
  const date = /^\d{4}-\d{2}-\d{2}/.exec(String(publishedAt || '').trim())?.[0] || ''
  return [{ version: normalizeVersionTag(version), date, items }]
}

export function normalizeVersionTag(value: string): string {
  const clean = value.trim()
  if (!clean) return ''
  return clean.startsWith('v') ? clean : `v${clean}`
}
