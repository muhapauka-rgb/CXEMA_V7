const SPACE_CHARS = /[\s\u00A0\u202F]+/g

export function normalizeNumberText(raw: string): string {
  return raw.trim().replace(SPACE_CHARS, "").replace(",", ".")
}

export function parseInputNumber(raw: string): number | null {
  const normalized = normalizeNumberText(raw)
  if (!normalized) return null
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

function groupThousands(intPart: string): string {
  const clean = intPart.replace(/^0+(?=\d)/, "") || "0"
  return clean.replace(/\B(?=(\d{3})+(?!\d))/g, " ")
}

export function formatNumberForInput(raw: string): string {
  const normalized = normalizeNumberText(raw)
  if (!normalized) return ""
  if (!/^-?\d+(\.\d+)?$/.test(normalized)) return raw.trim()

  const sign = normalized.startsWith("-") ? "-" : ""
  const plain = sign ? normalized.slice(1) : normalized
  const [intPart, fracPart] = plain.split(".")
  const grouped = groupThousands(intPart)
  if (fracPart == null || fracPart.length === 0) return `${sign}${grouped}`
  return `${sign}${grouped},${fracPart}`
}

export function formatNumberValueForInput(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ""
  return formatNumberForInput(String(value))
}
