const SPACE_CHARS = /[\s\u00A0\u202F]+/g

type ParseNumberOptions = {
  baseValue?: number | null
}

class ExprParser {
  private readonly src: string
  private i = 0

  constructor(input: string) {
    this.src = input
  }

  parse(): number | null {
    const v = this.parseExpr()
    if (v == null) return null
    if (this.i !== this.src.length) return null
    if (!Number.isFinite(v)) return null
    return v
  }

  private parseExpr(): number | null {
    let left = this.parseTerm()
    if (left == null) return null
    while (this.i < this.src.length) {
      const op = this.src[this.i]
      if (op !== "+" && op !== "-") break
      this.i += 1
      const right = this.parseTerm()
      if (right == null) return null
      left = op === "+" ? left + right : left - right
    }
    return left
  }

  private parseTerm(): number | null {
    let left = this.parseUnary()
    if (left == null) return null
    while (this.i < this.src.length) {
      const op = this.src[this.i]
      if (op !== "*" && op !== "/") break
      this.i += 1
      const right = this.parseUnary()
      if (right == null) return null
      if (op === "*") {
        left *= right
      } else {
        if (right === 0) return null
        left /= right
      }
    }
    return left
  }

  private parseUnary(): number | null {
    if (this.i < this.src.length && (this.src[this.i] === "+" || this.src[this.i] === "-")) {
      const op = this.src[this.i]
      this.i += 1
      const value = this.parseUnary()
      if (value == null) return null
      return op === "-" ? -value : value
    }
    return this.parsePrimary()
  }

  private parsePrimary(): number | null {
    if (this.src[this.i] === "(") {
      this.i += 1
      const inner = this.parseExpr()
      if (inner == null || this.src[this.i] !== ")") return null
      this.i += 1
      return inner
    }
    return this.parseNumber()
  }

  private parseNumber(): number | null {
    const start = this.i
    let seenDigit = false
    let seenDot = false
    while (this.i < this.src.length) {
      const ch = this.src[this.i]
      if (ch >= "0" && ch <= "9") {
        seenDigit = true
        this.i += 1
        continue
      }
      if (ch === ".") {
        if (seenDot) break
        seenDot = true
        this.i += 1
        continue
      }
      break
    }
    if (!seenDigit) return null
    const parsed = Number(this.src.slice(start, this.i))
    return Number.isFinite(parsed) ? parsed : null
  }
}

function evalMathExpression(raw: string): number | null {
  if (!raw) return null
  if (!/^[0-9+\-*/().]+$/.test(raw)) return null
  return new ExprParser(raw).parse()
}

export function normalizeNumberText(raw: string): string {
  return raw.trim().replace(SPACE_CHARS, "").replace(",", ".")
}

export function parseInputNumber(raw: string, options?: ParseNumberOptions): number | null {
  const normalized = normalizeNumberText(raw)
  if (!normalized) return null
  const base = Number(options?.baseValue)
  const first = normalized[0]
  const withBase =
    (first === "+" || first === "-" || first === "*" || first === "/") && Number.isFinite(base)
      ? `${base}${normalized}`
      : normalized
  const parsed = evalMathExpression(withBase)
  return parsed != null && Number.isFinite(parsed) ? parsed : null
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
