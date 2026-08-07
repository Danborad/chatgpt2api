export type ReleaseInfo = {
  version: string
  date: string
  items: { type: string; content: string }[]
}

export type ReleaseInlineSegment = {
  kind: 'text' | 'code'
  content: string
}

function parseReleaseItem(line: string): ReleaseInfo['items'][number] | null {
  const match = line.trim().match(/^[+*-]\s+\[(.+?)]\s+(.+)$/)
  return match ? { type: match[1], content: match[2] } : null
}

function parseReleaseItems(lines: string[]): ReleaseInfo['items'] {
  const items: ReleaseInfo['items'] = []
  for (const rawLine of lines) {
    const line = rawLine.trim()
    const item = parseReleaseItem(line)
    if (item) {
      items.push(item)
      continue
    }
    if (line && items.length && !line.startsWith('#') && !line.startsWith('>')) {
      items[items.length - 1].content += ' ' + line
    }
  }
  return items
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
        items: parseReleaseItems(lines),
      }
    })
    .filter((release) => release.items.length)
}

export function normalizeVersionTag(value: string): string {
  const clean = value.trim()
  if (!clean) return ''
  return clean.startsWith('v') ? clean : `v${clean}`
}
