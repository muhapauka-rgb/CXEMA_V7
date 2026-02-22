import { useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { apiDelete, apiGet, apiPatch, apiPost } from "../api"
import { openNativePicker } from "../datePicker"
import { formatNumberForInput, formatNumberValueForInput, parseInputNumber } from "../numberInput"

type ItemMode = "SINGLE_TOTAL" | "QTY_PRICE"
type AdjustmentType = "DISCOUNT" | "CREDIT_FROM_PREV" | "CARRY_TO_NEXT"
type TabKey = "expenses" | "payments" | "sheets"

type Project = {
  id: number
  title: string
  client_name?: string | null
  client_email?: string | null
  client_phone?: string | null
  google_drive_url?: string | null
  google_drive_folder?: string | null
  agency_fee_percent: number
  agency_fee_include_in_estimate: boolean
  project_price_total: number
  expected_from_client_total: number
  closed_at?: string | null
}

type Computed = {
  project_id: number
  expenses_total: number
  agency_fee: number
  extra_profit_total: number
  usn_tax?: number
  in_pocket: number
  diff: number
}

type AppSettings = {
  id: number
  usn_mode: "LEGAL" | "OPERATIONAL"
  usn_rate_percent: number
  created_at: string
  updated_at: string
}

type Group = {
  id: number
  project_id: number
  name: string
  sort_order: number
}

type Item = {
  id: number
  stable_item_id: string
  project_id: number
  group_id: number
  parent_item_id?: number | null
  title: string
  mode: ItemMode
  qty?: number | null
  unit_price_base?: number | null
  base_total: number
  include_in_estimate: boolean
  extra_profit_enabled: boolean
  extra_profit_amount: number
  discount_enabled: boolean
  discount_amount: number
  planned_pay_date?: string | null
}

type BillingAdjustment = {
  expense_item_id: number
  unit_price_full: number
  unit_price_billable: number
  adjustment_type: AdjustmentType
  reason: string
}

type PaymentPlan = {
  id: number
  stable_pay_id: string
  project_id: number
  pay_date: string
  amount: number
  note: string
}

type PaymentFact = {
  id: number
  project_id: number
  pay_date: string
  amount: number
  note: string
}

type SheetsStatus = {
  mode: string
  spreadsheet_id?: string | null
  sheet_tab_name?: string | null
  sheet_url?: string | null
  mock_file_path?: string | null
  last_published_at?: string | null
  last_imported_at?: string | null
}

type SheetsPublish = {
  status: string
  spreadsheet_id: string
  sheet_url?: string | null
  mock_file_path?: string | null
  last_published_at: string
  estimate_rows: number
  payments_plan_rows: number
}

type SheetsPreview = {
  preview_token: string
  items_updated: Array<{ item_id: string; title: string; changes: Record<string, { from: unknown; to: unknown }> }>
  payments_updated: Array<{ pay_id: string; changes: Record<string, { from: unknown; to: unknown }> }>
  payments_new: Array<{ pay_date: string; amount: number; note: string }>
  errors: string[]
}

type SheetsApply = {
  applied_items: number
  applied_payments_updated: number
  applied_payments_new: number
  errors: string[]
  imported_at?: string | null
}

type GoogleAuthStatus = {
  mode: string
  connected: boolean
  client_secret_configured: boolean
  redirect_uri: string
  token_file_path: string
  last_error?: string | null
}

type GoogleAuthStart = {
  auth_url: string
  state: string
}

type ItemFormState = {
  group_id: string
  title: string
  mode: ItemMode
  qty: string
  unit_price_base: string
  base_total: string
  extra_profit_enabled: boolean
  extra_profit_amount: string
  planned_pay_date: string
}

type PaymentDraft = {
  pay_date: string
  amount: string
  note: string
}

type ItemSheetDraft = {
  title: string
  planned_pay_date: string
  qty: string
  unit_price_base: string
  base_total: string
  include_in_estimate: boolean
  extra_profit_enabled: boolean
  extra_profit_amount: string
  discount_enabled: boolean
  discount_amount: string
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h16" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9 7V5h6v2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 7l.8 11h6.4L16 7" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path
        d="M19.4 13.5c.04-.33.1-.67.1-1s-.06-.67-.1-1l2.12-1.66a.52.52 0 0 0 .12-.65l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.23 7.23 0 0 0-1.73-1l-.38-2.65A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.49.42l-.38 2.65c-.62.25-1.2.58-1.73 1l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.5.5 0 0 0 .12.65L4.6 11.5c-.04.33-.1.67-.1 1s.06.67.1 1L2.48 15.16a.52.52 0 0 0-.12.65l2 3.46a.5.5 0 0 0 .6.22l2.49-1c.53.42 1.11.76 1.73 1l.38 2.65A.5.5 0 0 0 10 22h4a.5.5 0 0 0 .49-.42l.38-2.65c.62-.25 1.2-.58 1.73-1l2.49 1a.5.5 0 0 0 .6-.22l2-3.46a.5.5 0 0 0-.12-.65l-2.17-1.1ZM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z"
      />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.1" />
    </svg>
  )
}

function todayISO() {
  const d = new Date()
  const z = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}

function toMoney(n: number): string {
  return Number(n || 0).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function toMoneyInt(n: number): string {
  return Number(n || 0).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function toMoneyIntSigned(n: number): string {
  const value = Number(n || 0)
  if (!Number.isFinite(value) || value === 0) return "0"
  const abs = Math.abs(value).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return value > 0 ? `+${abs}` : `-${abs}`
}

function itemInternalTotal(item: Item): number {
  const base = item.mode === "QTY_PRICE"
    ? (() => {
      const qty = Number(item.qty ?? 0)
      const unit = Number(item.unit_price_base ?? 0)
      return qty === 0 ? unit : qty * unit
    })()
    : Number(item.base_total || 0)
  return base + (item.extra_profit_enabled ? Number(item.extra_profit_amount || 0) : 0)
}

function parseNonNegative(raw: string, field: string, optional = false): number | undefined {
  const value = raw.trim()
  if (optional && value === "") return undefined
  const n = parseInputNumber(value)
  if (n == null || n < 0) {
    throw new Error(`${field}: невалидное число`)
  }
  return n
}

function parseSigned(raw: string, field: string, optional = false): number | undefined {
  const value = raw.trim()
  if (optional && value === "") return undefined
  const n = parseInputNumber(value)
  if (n == null) {
    throw new Error(`${field}: невалидное число`)
  }
  return n
}

function parseDraftNumber(raw: string): number {
  const n = parseInputNumber(raw)
  return n != null && n >= 0 ? n : 0
}

function parseDraftSignedNumber(raw: string): number {
  const n = parseInputNumber(raw)
  return n != null ? n : 0
}

function itemDraftTotal(draft: ItemSheetDraft): number {
  const base = parseDraftNumber(draft.base_total)
  const extra = draft.extra_profit_enabled ? parseDraftNumber(draft.extra_profit_amount) : 0
  const discount = draft.discount_enabled ? parseDraftSignedNumber(draft.discount_amount) : 0
  return base + extra - discount
}

function formatDateParts(year: number, month: number, day: number): string | null {
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
  if (year < 1900 || year > 2100) return null
  if (month < 1 || month > 12) return null
  if (day < 1 || day > 31) return null
  const dt = new Date(Date.UTC(year, month - 1, day))
  if (dt.getUTCFullYear() !== year || dt.getUTCMonth() !== month - 1 || dt.getUTCDate() !== day) return null
  const y = String(year).padStart(4, "0")
  const m = String(month).padStart(2, "0")
  const d = String(day).padStart(2, "0")
  return `${y}-${m}-${d}`
}

function parseFlexibleDate(raw: string): string | null {
  const value = raw.trim()
  if (!value) return null

  const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (iso) {
    return formatDateParts(Number(iso[1]), Number(iso[2]), Number(iso[3]))
  }

  const ru = value.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2,4})$/)
  if (ru) {
    const day = Number(ru[1])
    const month = Number(ru[2])
    const yearRaw = Number(ru[3])
    const year = ru[3].length === 2 ? 2000 + yearRaw : yearRaw
    return formatDateParts(year, month, day)
  }

  const ymd = value.match(/^(\d{4})[.\/](\d{1,2})[.\/](\d{1,2})$/)
  if (ymd) {
    return formatDateParts(Number(ymd[1]), Number(ymd[2]), Number(ymd[3]))
  }

  return null
}

function normalizeDateDraftInput(raw: string): string {
  const value = raw.trim()
  if (!value) return ""
  return parseFlexibleDate(value) || value
}

function normalizeNumberDraftInput(raw: string): string {
  const value = raw.trim()
  if (!value) return ""
  return formatNumberForInput(value)
}

function isZeroLikeDraftNumber(raw: string): boolean {
  const compact = raw.trim().replace(/\s+/g, "")
  if (!compact) return false
  return /^0([.,]0+)?$/.test(compact)
}

function displayDraftNumber(raw: string): string {
  return isZeroLikeDraftNumber(raw) ? "" : raw
}

function displayNumberValue(value: number): string {
  return displayDraftNumber(formatNumberValueForInput(value))
}

function normalizeNumberDraftInputKeepingZero(raw: string, previousRaw: string): string {
  if (!raw.trim() && isZeroLikeDraftNumber(previousRaw)) {
    return normalizeNumberDraftInput(previousRaw)
  }
  return normalizeNumberDraftInput(raw)
}

function parseOptionalDate(raw: string, field: string): string | null {
  const value = raw.trim()
  if (!value) return null
  const parsed = parseFlexibleDate(value)
  if (!parsed) {
    throw new Error(`${field}: невалидная дата`)
  }
  return parsed
}

function toCalendarDateValue(raw: string): string {
  return parseFlexibleDate(raw) || ""
}

function parsePhones(raw: string | null | undefined): string[] {
  if (!raw) return [""]
  const list = raw
    .split(/[\n,;]/)
    .map((v) => v.trim())
    .filter(Boolean)
  return list.length > 0 ? list : [""]
}

function serializePhones(values: string[]): string | null {
  const cleaned = values.map((v) => v.trim()).filter(Boolean)
  return cleaned.length > 0 ? cleaned.join(", ") : null
}

function toPercentLabel(value: number | undefined): string {
  if (!Number.isFinite(value)) return "0"
  const n = Number(value)
  if (Number.isInteger(n)) return String(n)
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 2 })
}

function symmetricPercentPart(total: number, percent: number): number {
  const gross = Number(total || 0)
  const p = Number(percent || 0)
  if (!Number.isFinite(gross) || !Number.isFinite(p) || gross <= 0 || p <= 0) return 0
  return gross * (p / 100)
}

function emptyItemForm(groupId?: number): ItemFormState {
  return {
    group_id: groupId ? String(groupId) : "",
    title: "",
    mode: "SINGLE_TOTAL",
    qty: "",
    unit_price_base: "",
    base_total: "0",
    extra_profit_enabled: false,
    extra_profit_amount: "0",
    planned_pay_date: "",
  }
}

function itemToForm(item: Item): ItemFormState {
  return {
    group_id: String(item.group_id),
    title: item.title,
    mode: item.mode,
    qty: item.qty == null ? "" : formatNumberValueForInput(item.qty),
    unit_price_base: item.unit_price_base == null ? "" : formatNumberValueForInput(item.unit_price_base),
    base_total: formatNumberValueForInput(item.base_total),
    extra_profit_enabled: item.extra_profit_enabled,
    extra_profit_amount: formatNumberValueForInput(item.extra_profit_amount),
    planned_pay_date: item.planned_pay_date || "",
  }
}

function itemToSheetDraft(item: Item): ItemSheetDraft {
  return {
    title: item.title,
    planned_pay_date: item.planned_pay_date || "",
    qty: item.qty == null ? "" : formatNumberValueForInput(item.qty),
    unit_price_base: item.unit_price_base == null ? "" : formatNumberValueForInput(item.unit_price_base),
    base_total: formatNumberValueForInput(item.base_total),
    include_in_estimate: item.include_in_estimate ?? true,
    extra_profit_enabled: item.extra_profit_enabled,
    extra_profit_amount: formatNumberValueForInput(item.extra_profit_amount),
    discount_enabled: item.discount_enabled ?? false,
    discount_amount: formatNumberValueForInput(item.discount_amount || 0),
  }
}

function tryCalcBaseTotal(qtyRaw: string, unitRaw: string): string | null {
  if (unitRaw.trim() === "") return null
  const u = parseInputNumber(unitRaw)
  if (u == null || u < 0) return null
  if (qtyRaw.trim() === "") return formatNumberForInput(String(u))
  const q = parseInputNumber(qtyRaw)
  if (q == null || q < 0) return null
  if (q === 0) return formatNumberForInput(String(u))
  return formatNumberForInput(String(q * u))
}

function shouldAutoCalcFromQty(qtyRaw: string): boolean {
  const value = qtyRaw.trim()
  if (!value) return false
  const q = parseInputNumber(value)
  if (q == null || q < 0) return false
  return true
}

export default function ProjectPage() {
  const { id } = useParams()
  const projectId = id ? Number(id) : NaN

  const [tab, setTab] = useState<TabKey>("expenses")
  const [project, setProject] = useState<Project | null>(null)
  const [computed, setComputed] = useState<Computed | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [planPayments, setPlanPayments] = useState<PaymentPlan[]>([])
  const [factPayments, setFactPayments] = useState<PaymentFact[]>([])
  const [sheetStatus, setSheetStatus] = useState<SheetsStatus | null>(null)
  const [sheetPreview, setSheetPreview] = useState<SheetsPreview | null>(null)
  const [sheetPreviewToken, setSheetPreviewToken] = useState<string | null>(null)
  const [googleAuth, setGoogleAuth] = useState<GoogleAuthStatus | null>(null)
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null)
  const [projectPriceDraft, setProjectPriceDraft] = useState("0")
  const [savingProjectPrice, setSavingProjectPrice] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsForm, setSettingsForm] = useState({
    title: "",
    client_name: "",
    google_drive_url: "",
    google_drive_folder: "",
    agency_fee_percent: "10",
    phones: [""],
  })

  const [groupName, setGroupName] = useState("")
  const [isGroupCreateOpen, setIsGroupCreateOpen] = useState(false)
  const [creatingGroup, setCreatingGroup] = useState(false)
  const [deletingGroupId, setDeletingGroupId] = useState<number | null>(null)
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null)
  const [editingGroupName, setEditingGroupName] = useState("")
  const [savingGroupId, setSavingGroupId] = useState<number | null>(null)
  const [itemDrafts, setItemDrafts] = useState<Record<number, ItemSheetDraft>>({})
  const [creatingInGroup, setCreatingInGroup] = useState<number | null>(null)
  const [savingItemId, setSavingItemId] = useState<number | null>(null)
  const [isCommonAgencyOpen, setIsCommonAgencyOpen] = useState(false)
  const [groupAgencyEnabled, setGroupAgencyEnabled] = useState<Record<number, boolean>>({})
  const [newItemForm, setNewItemForm] = useState<ItemFormState>(emptyItemForm())
  const [editItemForm, setEditItemForm] = useState<ItemFormState>(emptyItemForm())
  const [adjustmentForm, setAdjustmentForm] = useState({
    unit_price_full: "0",
    unit_price_billable: "0",
    adjustment_type: "DISCOUNT" as AdjustmentType,
    reason: "",
  })
  const [hasAdjustment, setHasAdjustment] = useState(false)

  const [planDrafts, setPlanDrafts] = useState<Record<number, PaymentDraft>>({})
  const [factDrafts, setFactDrafts] = useState<Record<number, PaymentDraft>>({})

  const selectedItem = useMemo(
    () => items.find((it) => it.id === selectedItemId) || null,
    [items, selectedItemId],
  )
  const groupsMap = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups])
  const sheetsReady = sheetStatus?.mode !== "real" || !!googleAuth?.connected
  const paymentRows = useMemo(
    () => ([
      ...planPayments.map((p) => ({ kind: "plan" as const, id: p.id, pay_date: p.pay_date, amount: p.amount, note: p.note || "" })),
      ...factPayments.map((p) => ({ kind: "fact" as const, id: p.id, pay_date: p.pay_date, amount: p.amount, note: p.note || "" })),
    ]).sort((a, b) => a.pay_date.localeCompare(b.pay_date) || a.id - b.id),
    [planPayments, factPayments],
  )
  const allItemIds = useMemo(() => new Set(items.map((it) => it.id)), [items])
  const topLevelItems = useMemo(
    () => items.filter((it) => it.parent_item_id == null || !allItemIds.has(Number(it.parent_item_id))),
    [items, allItemIds],
  )
  const childItemsByParent = useMemo(() => {
    const out = new Map<number, Item[]>()
    for (const it of items) {
      if (it.parent_item_id == null) continue
      const key = Number(it.parent_item_id)
      const list = out.get(key) || []
      list.push(it)
      out.set(key, list)
    }
    out.forEach((list) => list.sort((a, b) => a.id - b.id))
    return out
  }, [items])
  const itemMathById = useMemo(() => {
    const out: Record<number, { base: number; extra: number; discount: number; totalBeforeDiscount: number; total: number }> = {}
    for (const it of items) {
      const draft = itemDrafts[it.id] || itemToSheetDraft(it)
      let base = parseDraftNumber(draft.base_total)
      if (shouldAutoCalcFromQty(draft.qty)) {
        const qty = parseInputNumber(draft.qty)
        const unit = parseInputNumber(draft.unit_price_base)
        if (qty != null && qty >= 0 && unit != null && unit >= 0) {
          base = qty === 0 ? unit : qty * unit
        }
      }
      const extra = draft.extra_profit_enabled ? parseDraftNumber(draft.extra_profit_amount) : 0
      const discount = draft.discount_enabled ? parseDraftSignedNumber(draft.discount_amount) : 0
      const totalBeforeDiscount = base + extra
      out[it.id] = { base, extra, discount, totalBeforeDiscount, total: totalBeforeDiscount - discount }
    }
    return out
  }, [items, itemDrafts])
  const projectPriceDisplayValue = useMemo(() => {
    const parsed = parseInputNumber(projectPriceDraft)
    if (parsed == null || parsed < 0) return Number(project?.project_price_total || 0)
    return parsed
  }, [projectPriceDraft, project?.project_price_total])
  const expensesDisplay = useMemo(
    () => topLevelItems.reduce((acc, it) => acc + (itemMathById[it.id]?.total ?? itemInternalTotal(it)), 0),
    [topLevelItems, itemMathById],
  )
  const extraProfitDisplay = useMemo(
    () => topLevelItems.reduce((acc, it) => acc + (itemMathById[it.id]?.extra ?? (it.extra_profit_enabled ? Number(it.extra_profit_amount || 0) : 0)), 0),
    [topLevelItems, itemMathById],
  )
  const discountDisplay = useMemo(
    () => topLevelItems.reduce((acc, it) => acc + (itemMathById[it.id]?.discount ?? (it.discount_enabled ? Number(it.discount_amount || 0) : 0)), 0),
    [topLevelItems, itemMathById],
  )
  const paymentsTotal = useMemo(
    () => paymentRows.reduce((acc, row) => {
      const draft = row.kind === "plan" ? planDrafts[row.id] : factDrafts[row.id]
      const parsed = parseInputNumber(draft?.amount ?? "")
      if (parsed != null && parsed >= 0) return acc + parsed
      return acc + Number(row.amount || 0)
    }, 0),
    [paymentRows, planDrafts, factDrafts],
  )
  const paymentsDiff = useMemo(
    () => paymentsTotal - projectPriceDisplayValue,
    [paymentsTotal, projectPriceDisplayValue],
  )
  const paymentsDiffIsAccent = Math.abs(paymentsDiff) >= 0.005
  const agencyPercent = Number(project?.agency_fee_percent || 0)
  const groupAgencyTotal = useMemo(
    () => groups.reduce((acc, g) => {
      if (!groupAgencyEnabled[g.id]) return acc
      const groupItemIds = new Set(items.filter((it) => it.group_id === g.id).map((it) => it.id))
      const groupTopLevel = items.filter((it) => it.group_id === g.id && (it.parent_item_id == null || !groupItemIds.has(Number(it.parent_item_id))))
      const groupTotal = groupTopLevel
        .reduce((sum, it) => sum + (itemMathById[it.id]?.total ?? itemInternalTotal(it)), 0)
      return acc + symmetricPercentPart(groupTotal, agencyPercent)
    }, 0),
    [groups, items, groupAgencyEnabled, agencyPercent, itemMathById],
  )
  const commonAgencyAmount = useMemo(
    () => (isCommonAgencyOpen ? symmetricPercentPart(projectPriceDisplayValue, agencyPercent) : 0),
    [isCommonAgencyOpen, projectPriceDisplayValue, agencyPercent],
  )
  const agencyTotalFromExpenses = groupAgencyTotal + commonAgencyAmount
  const usnMode = appSettings?.usn_mode || "OPERATIONAL"
  const usnRate = Number(appSettings?.usn_rate_percent || 6)
  const usnBaseForProject = usnMode === "LEGAL"
    ? paymentsTotal
    : (expensesDisplay + agencyTotalFromExpenses)
  const usnAmount = usnBaseForProject > 0 ? (usnBaseForProject * usnRate) / 100 : 0
  const expensesDisplayWithUsn = expensesDisplay + usnAmount
  const inPocketDisplay = agencyTotalFromExpenses + extraProfitDisplay - discountDisplay
  const diffDisplay = projectPriceDisplayValue - (expensesDisplay + agencyTotalFromExpenses + usnAmount)
  const groupAgencyStorageKey = useMemo(
    () => `cxema-v7:project:${projectId}:group-agency`,
    [projectId],
  )

  async function loadAll() {
    if (!Number.isFinite(projectId)) return
    setLoading(true)
    setError(null)
    try {
      const [p, c, gs, its, plan, fact, sheet, auth, settings] = await Promise.all([
        apiGet<Project>(`/api/projects/${projectId}`),
        apiGet<Computed>(`/api/projects/${projectId}/computed`),
        apiGet<Group[]>(`/api/projects/${projectId}/groups`),
        apiGet<Item[]>(`/api/projects/${projectId}/items`),
        apiGet<PaymentPlan[]>(`/api/projects/${projectId}/payments/plan`),
        apiGet<PaymentFact[]>(`/api/projects/${projectId}/payments/fact`),
        apiGet<SheetsStatus>(`/api/projects/${projectId}/sheets/status`),
        apiGet<GoogleAuthStatus>(`/api/google/auth/status`),
        apiGet<AppSettings>("/api/settings"),
      ])
      setProject(p)
      setComputed(c)
      setGroups(gs)
      setItems(its)
      setPlanPayments(plan)
      setFactPayments(fact)
      setSheetStatus(sheet)
      setGoogleAuth(auth)
      setAppSettings(settings)
      setSettingsForm({
        title: p.title,
        client_name: p.client_name || "",
        google_drive_url: p.google_drive_url || "",
        google_drive_folder: p.google_drive_folder || "",
        agency_fee_percent: formatNumberValueForInput(p.agency_fee_percent ?? 10),
        phones: parsePhones(p.client_phone),
      })
      setProjectPriceDraft(formatNumberValueForInput(p.project_price_total || 0))
      setNewItemForm((prev) => ({ ...prev, group_id: prev.group_id || (gs[0] ? String(gs[0].id) : "") }))
      if (selectedItemId && !its.find((it) => it.id === selectedItemId)) {
        setSelectedItemId(null)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  async function loadAdjustmentForItem(itemId: number) {
    if (!Number.isFinite(projectId)) return
    try {
      const adj = await apiGet<BillingAdjustment>(`/api/projects/${projectId}/items/${itemId}/adjustment`)
      setAdjustmentForm({
        unit_price_full: String(adj.unit_price_full),
        unit_price_billable: String(adj.unit_price_billable),
        adjustment_type: adj.adjustment_type,
        reason: adj.reason || "",
      })
      setHasAdjustment(true)
    } catch (e) {
      if (String(e).includes("ADJUSTMENT_NOT_FOUND")) {
        setAdjustmentForm({
          unit_price_full: "0",
          unit_price_billable: "0",
          adjustment_type: "DISCOUNT",
          reason: "",
        })
        setHasAdjustment(false)
      } else {
        setError(String(e))
      }
    }
  }

  function itemPayloadFromForm(form: ItemFormState) {
    const qty = parseNonNegative(form.qty, "qty", true)
    const unitPrice = parseNonNegative(form.unit_price_base, "unit_price_base", true)
    const base = parseNonNegative(form.base_total, "base_total") || 0
    const extra = parseNonNegative(form.extra_profit_amount, "extra_profit_amount") || 0
    const groupIdParsed = Number(form.group_id)
    if (!Number.isFinite(groupIdParsed) || groupIdParsed <= 0) {
      throw new Error("group_id: выбери группу")
    }

    return {
      group_id: groupIdParsed,
      title: form.title.trim(),
      mode: form.mode,
      qty: qty ?? null,
      unit_price_base: unitPrice ?? null,
      base_total: base,
      extra_profit_enabled: form.extra_profit_enabled,
      extra_profit_amount: extra,
      planned_pay_date: form.planned_pay_date || null,
    }
  }

  async function refreshGoogleAuthStatus() {
    try {
      const auth = await apiGet<GoogleAuthStatus>(`/api/google/auth/status`)
      setGoogleAuth(auth)
    } catch (e) {
      setError(String(e))
    }
  }

  async function saveProjectSettings() {
    if (!project) return
    const nextTitle = settingsForm.title.trim()
    if (!nextTitle) {
      setError("Название проекта не может быть пустым")
      return
    }
    try {
      setError(null)
      setSettingsSaving(true)
      await apiPatch<Project>(`/api/projects/${projectId}`, {
        title: nextTitle,
        client_name: settingsForm.client_name.trim() || null,
        client_phone: serializePhones(settingsForm.phones),
        google_drive_url: settingsForm.google_drive_url.trim() || null,
        google_drive_folder: settingsForm.google_drive_folder.trim() || null,
        agency_fee_percent: parseNonNegative(settingsForm.agency_fee_percent, "agency_fee_percent"),
        agency_fee_include_in_estimate: true,
      })
      setIsSettingsOpen(false)
      await loadAll()
    } catch (e) {
      setError(String(e))
    } finally {
      setSettingsSaving(false)
    }
  }

  function startGroupRename(group: Group) {
    setEditingGroupId(group.id)
    setEditingGroupName(group.name)
  }

  function cancelGroupRename() {
    setEditingGroupId(null)
    setEditingGroupName("")
  }

  async function saveGroupRename(groupId: number) {
    const name = editingGroupName.trim()
    if (!name) {
      setError("Название группы не может быть пустым")
      return
    }
    try {
      setError(null)
      setSavingGroupId(groupId)
      const updated = await apiPatch<Group>(`/api/projects/${projectId}/groups/${groupId}`, { name })
      setGroups((prev) => prev.map((g) => (g.id === groupId ? updated : g)))
      cancelGroupRename()
    } catch (e) {
      setError(String(e))
    } finally {
      setSavingGroupId(null)
    }
  }

  async function createGroup() {
    const name = groupName.trim()
    if (!name) {
      setError("Укажи название группы")
      return
    }
    try {
      setError(null)
      setCreatingGroup(true)
      const created = await apiPost<Group>(`/api/projects/${projectId}/groups`, {
        name,
        sort_order: groups.length,
      })
      setGroups((prev) => [...prev, created].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id))
      setGroupName("")
      setIsGroupCreateOpen(false)
    } catch (e) {
      setError(String(e))
    } finally {
      setCreatingGroup(false)
    }
  }

  async function deleteGroup(group: Group) {
    const groupItems = items.filter((it) => it.group_id === group.id)
    const confirmed = window.confirm(
      groupItems.length > 0
        ? `Удалить группу "${group.name}" и все её позиции (${groupItems.length})?`
        : `Удалить группу "${group.name}"?`,
    )
    if (!confirmed) return
    try {
      setError(null)
      setDeletingGroupId(group.id)
      await apiDelete(`/api/projects/${projectId}/groups/${group.id}`)
      if (editingGroupId === group.id) cancelGroupRename()
      await loadAll()
    } catch (e) {
      setError(String(e))
    } finally {
      setDeletingGroupId(null)
    }
  }

  async function createItemInGroup(groupId: number, preset?: { title?: string; parent_item_id?: number | null }) {
    try {
      setError(null)
      setCreatingInGroup(groupId)
      const created = await apiPost<Item>(`/api/projects/${projectId}/items`, {
        group_id: groupId,
        parent_item_id: preset?.parent_item_id ?? null,
        title: preset?.title || "",
        mode: "SINGLE_TOTAL",
        qty: null,
        unit_price_base: null,
        base_total: 0,
        include_in_estimate: preset?.parent_item_id ? false : true,
        extra_profit_enabled: false,
        extra_profit_amount: 0,
        discount_enabled: false,
        discount_amount: 0,
        planned_pay_date: null,
      })
      setItems((prev) => {
        const next = [...prev, created]
        next.sort((a, b) => a.group_id - b.group_id || a.id - b.id)
        return next
      })
      setItemDrafts((prev) => ({ ...prev, [created.id]: itemToSheetDraft(created) }))
    } catch (e) {
      setError(String(e))
    } finally {
      setCreatingInGroup(null)
    }
  }

function payloadFromDraft(draft: ItemSheetDraft): Record<string, unknown> {
    const title = draft.title.trim()
    const qty = parseNonNegative(draft.qty, "qty", true)
    const unitPrice = parseNonNegative(draft.unit_price_base, "unit_price_base", true)
    const baseTotal = parseNonNegative(draft.base_total, "base_total", true)
  const extraProfit = draft.extra_profit_enabled
    ? (parseNonNegative(draft.extra_profit_amount, "extra_profit_amount") || 0)
    : 0
  const discountAmount = draft.discount_enabled
    ? (parseSigned(draft.discount_amount, "discount_amount") || 0)
    : 0

  const common: Record<string, unknown> = {
    title,
    include_in_estimate: draft.include_in_estimate,
    extra_profit_enabled: draft.extra_profit_enabled,
    extra_profit_amount: extraProfit,
    discount_enabled: draft.discount_enabled,
    discount_amount: discountAmount,
    planned_pay_date: parseOptionalDate(draft.planned_pay_date, "planned_pay_date"),
  }

    if (qty !== undefined) {
      if (unitPrice === undefined) {
        throw new Error("Если указаны штуки, заполни цену за ед.")
      }
      return {
        ...common,
        mode: "QTY_PRICE",
        qty,
        unit_price_base: unitPrice,
        base_total: qty === 0 ? unitPrice : qty * unitPrice,
      }
    }

    return {
      ...common,
      mode: "SINGLE_TOTAL",
      qty: qty ?? null,
      unit_price_base: unitPrice ?? null,
      base_total: baseTotal ?? unitPrice ?? 0,
    }
  }

  async function persistItemRow(item: Item, draftOverride?: ItemSheetDraft) {
    const draft = draftOverride || itemDrafts[item.id]
    if (!draft) return

    try {
      setError(null)
      setSavingItemId(item.id)
      const payload = payloadFromDraft(draft)
      const updated = await apiPatch<Item>(`/api/projects/${projectId}/items/${item.id}`, payload)
      setItems((prev) => prev.map((it) => (it.id === item.id ? updated : it)))
      setItemDrafts((prev) => ({ ...prev, [item.id]: itemToSheetDraft(updated) }))
    } catch (e) {
      setError(String(e))
    } finally {
      setSavingItemId(null)
    }
  }

  function commitItemDraft(item: Item, next: ItemSheetDraft) {
    setItemDrafts((prev) => ({ ...prev, [item.id]: next }))
    void persistItemRow(item, next)
  }

  function handleZeroFocus(target: HTMLInputElement) {
    const n = parseInputNumber(target.value)
    if (Number.isFinite(n) && n === 0) {
      target.select()
    }
  }

  async function deleteItemRow(itemId: number) {
    try {
      setError(null)
      const childIdsToDelete = new Set(
        items.filter((it) => it.parent_item_id === itemId).map((it) => it.id),
      )
      await apiDelete(`/api/projects/${projectId}/items/${itemId}`)
      if (selectedItemId === itemId) setSelectedItemId(null)
      setItems((prev) => prev.filter((it) => it.id !== itemId && it.parent_item_id !== itemId))
      setItemDrafts((prev) => {
        const next = { ...prev }
        delete next[itemId]
        childIdsToDelete.forEach((childId) => {
          delete next[childId]
        })
        return next
      })
    } catch (e) {
      setError(String(e))
    }
  }

  async function createPaymentRow() {
    try {
      setError(null)
      await apiPost(`/api/projects/${projectId}/payments/fact`, {
        pay_date: todayISO(),
        amount: 0,
        note: "",
      })
      await loadAll()
    } catch (e) {
      setError(String(e))
    }
  }

  async function saveProjectPrice(raw?: string) {
    if (!project) return
    const source = raw ?? projectPriceDraft
    try {
      setError(null)
      setSavingProjectPrice(true)
      const next = parseNonNegative(source, "project_price_total") || 0
      const updated = await apiPatch<Project>(`/api/projects/${projectId}`, {
        project_price_total: next,
      })
      const c = await apiGet<Computed>(`/api/projects/${projectId}/computed`)
      setProject(updated)
      setComputed(c)
      setProjectPriceDraft(formatNumberValueForInput(updated.project_price_total || 0))
    } catch (e) {
      setError(String(e))
    } finally {
      setSavingProjectPrice(false)
    }
  }

  async function persistPaymentRow(kind: "plan" | "fact", id: number, draft: PaymentDraft) {
    try {
      setError(null)
      const payDate = parseOptionalDate(draft.pay_date, "pay_date")
      if (!payDate) throw new Error("pay_date: укажи дату оплаты")
      const amount = parseNonNegative(draft.amount, "amount")
      const targetKind: "plan" | "fact" = payDate > todayISO() ? "plan" : "fact"

      if (targetKind === kind) {
        const endpoint = kind === "plan" ? "plan" : "fact"
        await apiPatch(`/api/projects/${projectId}/payments/${endpoint}/${id}`, {
          pay_date: payDate,
          amount,
          note: draft.note || "",
        })
      } else {
        await apiPost(`/api/projects/${projectId}/payments/${targetKind}`, {
          pay_date: payDate,
          amount,
          note: draft.note || "",
        })
        const sourceEndpoint = kind === "plan" ? "plan" : "fact"
        await apiDelete(`/api/projects/${projectId}/payments/${sourceEndpoint}/${id}`)
      }
      await loadAll()
    } catch (e) {
      setError(String(e))
    }
  }

  async function deletePaymentRow(kind: "plan" | "fact", id: number) {
    try {
      setError(null)
      const endpoint = kind === "plan" ? "plan" : "fact"
      await apiDelete(`/api/projects/${projectId}/payments/${endpoint}/${id}`)
      await loadAll()
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    const drafts: Record<number, PaymentDraft> = {}
    for (const p of planPayments) {
      drafts[p.id] = { pay_date: p.pay_date, amount: formatNumberValueForInput(p.amount), note: p.note || "" }
    }
    setPlanDrafts(drafts)
  }, [planPayments])

  useEffect(() => {
    const drafts: Record<number, PaymentDraft> = {}
    for (const p of factPayments) {
      drafts[p.id] = { pay_date: p.pay_date, amount: formatNumberValueForInput(p.amount), note: p.note || "" }
    }
    setFactDrafts(drafts)
  }, [factPayments])

  useEffect(() => {
    const drafts: Record<number, ItemSheetDraft> = {}
    for (const it of items) {
      drafts[it.id] = itemToSheetDraft(it)
    }
    setItemDrafts(drafts)
  }, [items])

  useEffect(() => {
    if (!selectedItem) return
    setEditItemForm(itemToForm(selectedItem))
    void loadAdjustmentForItem(selectedItem.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItem?.id])

  useEffect(() => {
    if (!isSettingsOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !settingsSaving) {
        setIsSettingsOpen(false)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [isSettingsOpen, settingsSaving])

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(groupAgencyStorageKey)
      if (!raw) {
        setGroupAgencyEnabled({})
        return
      }
      const parsed = JSON.parse(raw) as Record<string, unknown>
      const next: Record<number, boolean> = {}
      Object.entries(parsed).forEach(([key, value]) => {
        const idNum = Number(key)
        if (Number.isFinite(idNum) && value === true) next[idNum] = true
      })
      setGroupAgencyEnabled(next)
    } catch {
      setGroupAgencyEnabled({})
    }
  }, [groupAgencyStorageKey])

  useEffect(() => {
    try {
      window.localStorage.setItem(groupAgencyStorageKey, JSON.stringify(groupAgencyEnabled))
    } catch {
      // ignore storage write errors
    }
  }, [groupAgencyStorageKey, groupAgencyEnabled])

  useEffect(() => {
    if (!groups.length) return
    const ids = new Set(groups.map((g) => g.id))
    setGroupAgencyEnabled((prev) => {
      const next: Record<number, boolean> = {}
      Object.entries(prev).forEach(([key, value]) => {
        const idNum = Number(key)
        if (value && ids.has(idNum)) next[idNum] = true
      })
      const same = Object.keys(next).length === Object.keys(prev).length
        && Object.keys(next).every((k) => prev[Number(k)] === true)
      return same ? prev : next
    })
  }, [groups])

  useEffect(() => {
    if (!editingGroupId) return
    if (groups.some((g) => g.id === editingGroupId)) return
    cancelGroupRename()
  }, [groups, editingGroupId])

  if (!Number.isFinite(projectId)) return <div className="panel">PROJECT_ID_INVALID</div>
  if (loading && !project) return <div className="panel">Загрузка…</div>
  if (!project) return <div className="panel">{error || "PROJECT_NOT_FOUND"}</div>

  return (
    <>
    <div className={`grid ${isSettingsOpen ? "page-content-muted" : ""}`}>
      <div className="sticky-stack">
        <div className="panel top-panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div className="h1" style={{ marginBottom: 4 }}>{project.title}</div>
            </div>
            <div className="row">
              <button className="btn" onClick={() => void loadAll()}>Обновить</button>
              <button className={`btn icon-btn ${isSettingsOpen ? "tab-active" : ""}`} onClick={() => setIsSettingsOpen((prev) => !prev)}>
                <GearIcon />
              </button>
            </div>
          </div>
        </div>

        <div className="dashboard-strip">
          <div className="kpi-card">
            <div className="muted">Стоимость проекта</div>
            <input
              className="kpi-value-input"
              value={projectPriceDraft}
              disabled={savingProjectPrice}
              onFocus={(e) => handleZeroFocus(e.currentTarget)}
              onChange={(e) => setProjectPriceDraft(e.target.value)}
              onBlur={(e) => {
                const next = normalizeNumberDraftInput(e.currentTarget.value)
                setProjectPriceDraft(next)
                void saveProjectPrice(next)
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return
                e.preventDefault()
                const next = normalizeNumberDraftInput(e.currentTarget.value)
                setProjectPriceDraft(next)
                void saveProjectPrice(next)
              }}
            />
          </div>
          <div className="kpi-card">
            <div className="muted">Расходы</div>
            <div className="kpi-value">{toMoneyInt(expensesDisplayWithUsn)}</div>
          </div>
          <div className="kpi-card">
            <div className="muted">Агентские ({toPercentLabel(project.agency_fee_percent)}%)</div>
            <div className="kpi-value">{toMoneyInt(agencyTotalFromExpenses)}</div>
          </div>
          <div className="kpi-card">
            <div className="muted">Доп прибыль</div>
            <div className="kpi-value">{toMoneyInt(extraProfitDisplay)}</div>
          </div>
          <div className="kpi-card">
            <div className="muted">Скидка</div>
            <div className="kpi-value">{toMoneyIntSigned(discountDisplay)}</div>
          </div>
          <div className="kpi-card">
            <div className="muted">В кармане</div>
            <div className="kpi-value">{toMoneyInt(inPocketDisplay)}</div>
          </div>
          <div className="kpi-card">
            <div className="muted">Разница</div>
            <div className="kpi-value diff-value">{toMoneyInt(diffDisplay)}</div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="row tab-row">
          <button className={`btn ${tab === "expenses" ? "tab-active" : ""}`} onClick={() => setTab("expenses")}>Расходы</button>
          <button className={`btn ${tab === "payments" ? "tab-active" : ""}`} onClick={() => setTab("payments")}>Оплаты</button>
          <button className={`btn ${tab === "sheets" ? "tab-active" : ""}`} onClick={() => setTab("sheets")}>Google Sheets</button>
        </div>
      </div>

      {tab === "expenses" && (
        <div className="grid expense-sheet">
          <div className="row expense-group-controls">
            <button
              className="btn"
              disabled={creatingGroup}
              onClick={() => {
                setIsGroupCreateOpen(true)
              }}
            >
              + группа
            </button>
            {isGroupCreateOpen && (
              <input
                className="input expense-group-create-input"
                placeholder="Название группы"
                value={groupName}
                autoFocus
                onChange={(e) => setGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    void createGroup()
                  }
                  if (e.key === "Escape") {
                    e.preventDefault()
                    setIsGroupCreateOpen(false)
                    setGroupName("")
                  }
                }}
              />
            )}
          </div>

          {groups.map((g) => {
            const gItems = items.filter((it) => it.group_id === g.id)
            const gItemIds = new Set(gItems.map((it) => it.id))
            const topLevelItems = gItems
              .filter((it) => it.parent_item_id == null || !gItemIds.has(Number(it.parent_item_id)))
              .sort((a, b) => a.id - b.id)
            const orderedRows: Item[] = []
            for (const parent of topLevelItems) {
              orderedRows.push(parent)
              const children = childItemsByParent.get(parent.id) || []
              for (const child of children) orderedRows.push(child)
            }
            const showExtraProfitColumns = gItems.some((it) => {
              const draft = itemDrafts[it.id] || itemToSheetDraft(it)
              return !!draft.extra_profit_enabled
            })
            const showDiscountColumns = topLevelItems.some((it) => {
              const draft = itemDrafts[it.id] || itemToSheetDraft(it)
              return !!draft.discount_enabled
            })
            const showRowTotalColumn = showExtraProfitColumns || showDiscountColumns
            const baseTotal = topLevelItems
              .reduce((acc, it) => acc + (itemMathById[it.id]?.total ?? itemInternalTotal(it)), 0)
            const agencyEnabled = !!groupAgencyEnabled[g.id]
            const agencyPercent = Number(project.agency_fee_percent || 0)
            const agencyAmount = agencyEnabled ? symmetricPercentPart(baseTotal, agencyPercent) : 0
            const total = baseTotal + agencyAmount

            return (
              <div key={g.id} className="sheet-group">
                <div className="sheet-group-head">
                  {editingGroupId === g.id ? (
                    <input
                      className="input sheet-group-name-input"
                      value={editingGroupName}
                      autoFocus
                      onChange={(e) => setEditingGroupName(e.target.value)}
                      onBlur={() => void saveGroupRename(g.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          void saveGroupRename(g.id)
                        }
                        if (e.key === "Escape") {
                          e.preventDefault()
                          cancelGroupRename()
                        }
                      }}
                    />
                  ) : (
                    <button
                      className="title-btn sheet-group-title"
                      onClick={() => startGroupRename(g)}
                    >
                      {g.name}
                    </button>
                  )}
                  <div className="row">
                    <span>{toMoney(total)}</span>
                    <button
                      className="btn sheet-plus-btn"
                      disabled={creatingInGroup === g.id || savingGroupId === g.id || deletingGroupId === g.id}
                      onClick={() => void createItemInGroup(g.id)}
                    >
                      +
                    </button>
                    <button
                      className="btn icon-btn"
                      aria-label="Удалить группу"
                      disabled={creatingInGroup === g.id || savingGroupId === g.id || deletingGroupId === g.id}
                      onClick={() => void deleteGroup(g)}
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </div>

                {gItems.length > 0 && (
                  <div className="table-wrap">
                    <table className="table expense-table">
                      <thead>
                        <tr>
                          <th className="col-title">Статья</th>
                          <th className="col-date">Дата<br />оплаты</th>
                          <th className="col-qty">Шт</th>
                          <th className="col-unit">Цена<br />за ед</th>
                          <th className="col-sum">Сумма</th>
                          {showRowTotalColumn && <th className="col-row-total">Итог<br />строки</th>}
                          {showExtraProfitColumns && <th className="col-extra-amount">Доп<br />прибыль</th>}
                          <th className="col-extra-toggle">Доп<br />прибыль</th>
                          {showDiscountColumns && <th className="col-discount-amount">Скидка</th>}
                          <th className="col-discount-toggle">Скидка</th>
                          <th className="col-estimate">В<br />смету</th>
                          <th className="col-actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {orderedRows.map((it) => {
                          const draft = itemDrafts[it.id] || itemToSheetDraft(it)
                          const rowMath = itemMathById[it.id]
                          const rowTotal = rowMath?.total ?? itemDraftTotal(draft)
                          const isSubitem = it.parent_item_id != null
                          const childRows = childItemsByParent.get(it.id) || []
                          const hasSubitems = childRows.length > 0
                          const latestChildDate = childRows.reduce((maxDate, child) => {
                            const childDraft = itemDrafts[child.id] || itemToSheetDraft(child)
                            const parsed = parseFlexibleDate(childDraft.planned_pay_date || "")
                            if (!parsed) return maxDate
                            return parsed > maxDate ? parsed : maxDate
                          }, "")
                          const displayDate = hasSubitems ? (draft.planned_pay_date || latestChildDate) : draft.planned_pay_date
                          return (
                            <tr key={it.id} className={isSubitem ? "expense-row-subitem" : ""}>
                              <td className={`col-title ${isSubitem ? "subitem-title-cell" : ""}`}>
                                <div className={isSubitem ? "subitem-title-wrap" : undefined}>
                                  {isSubitem && <span className="subitem-marker">↳</span>}
                                  <input
                                    className="input"
                                    value={draft.title}
                                    placeholder="Название"
                                    onDoubleClick={() => {
                                      if (isSubitem) return
                                      void createItemInGroup(g.id, { parent_item_id: it.id })
                                    }}
                                    onChange={(e) => setItemDrafts((prev) => ({ ...prev, [it.id]: { ...draft, title: e.target.value } }))}
                                    onBlur={(e) => {
                                      const next = { ...draft, title: e.currentTarget.value }
                                      setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                      void persistItemRow(it, next)
                                    }}
                                    onKeyDown={(e) => {
                                      if (e.key !== "Enter") return
                                      e.preventDefault()
                                      const next = { ...draft, title: e.currentTarget.value }
                                      commitItemDraft(it, next)
                                    }}
                                  />
                                </div>
                              </td>
                              <td className="col-date">
                                <div className="date-cell">
                                  <input
                                    className="input"
                                    value={displayDate}
                                    placeholder="дд.мм.гггг"
                                    onChange={(e) => setItemDrafts((prev) => ({ ...prev, [it.id]: { ...draft, planned_pay_date: e.target.value } }))}
                                    onClick={(e) => {
                                      const picker = e.currentTarget.nextElementSibling as HTMLInputElement | null
                                      openNativePicker(picker, true)
                                    }}
                                    onFocus={(e) => {
                                      const picker = e.currentTarget.nextElementSibling as HTMLInputElement | null
                                      openNativePicker(picker, true)
                                    }}
                                    onBlur={(e) => {
                                      const next = { ...draft, planned_pay_date: normalizeDateDraftInput(e.currentTarget.value) }
                                      setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                      void persistItemRow(it, next)
                                    }}
                                    onKeyDown={(e) => {
                                      if (e.key !== "Enter") return
                                      e.preventDefault()
                                      const next = { ...draft, planned_pay_date: normalizeDateDraftInput(e.currentTarget.value) }
                                      commitItemDraft(it, next)
                                    }}
                                  />
                                  <input
                                    className="date-picker-hidden"
                                    type="date"
                                    tabIndex={-1}
                                    aria-hidden="true"
                                    value={toCalendarDateValue(displayDate)}
                                    onChange={(e) => {
                                      const next = { ...draft, planned_pay_date: e.target.value }
                                      commitItemDraft(it, next)
                                    }}
                                  />
                                </div>
                              </td>
                              <td className="col-qty">
                                <input
                                  className="input"
                                  value={displayDraftNumber(draft.qty)}
                                  placeholder=""
                                  onChange={(e) => {
                                    const nextQty = e.target.value
                                    const autoTotal = shouldAutoCalcFromQty(nextQty)
                                      ? tryCalcBaseTotal(nextQty, draft.unit_price_base)
                                      : null
                                    setItemDrafts((prev) => ({
                                      ...prev,
                                      [it.id]: {
                                        ...draft,
                                        qty: nextQty,
                                        base_total: autoTotal ?? draft.base_total,
                                      },
                                    }))
                                  }}
                                  onBlur={(e) => {
                                    const nextQty = normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.qty)
                                    const autoTotal = shouldAutoCalcFromQty(nextQty)
                                      ? tryCalcBaseTotal(nextQty, draft.unit_price_base)
                                      : null
                                    const next = { ...draft, qty: nextQty, base_total: autoTotal ?? draft.base_total }
                                    setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                    void persistItemRow(it, next)
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key !== "Enter") return
                                    e.preventDefault()
                                    const nextQty = normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.qty)
                                    const autoTotal = shouldAutoCalcFromQty(nextQty)
                                      ? tryCalcBaseTotal(nextQty, draft.unit_price_base)
                                      : null
                                    const next = { ...draft, qty: nextQty, base_total: autoTotal ?? draft.base_total }
                                    commitItemDraft(it, next)
                                  }}
                                />
                              </td>
                              <td className="col-unit">
                                <input
                                  className="input"
                                  value={displayDraftNumber(draft.unit_price_base)}
                                  placeholder=""
                                  onChange={(e) => {
                                    const nextUnit = e.target.value
                                    const autoTotal = shouldAutoCalcFromQty(draft.qty)
                                      ? tryCalcBaseTotal(draft.qty, nextUnit)
                                      : null
                                    setItemDrafts((prev) => ({
                                      ...prev,
                                      [it.id]: {
                                        ...draft,
                                        unit_price_base: nextUnit,
                                        base_total: autoTotal ?? draft.base_total,
                                      },
                                    }))
                                  }}
                                  onBlur={(e) => {
                                    const nextUnit = normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.unit_price_base)
                                    const autoTotal = shouldAutoCalcFromQty(draft.qty)
                                      ? tryCalcBaseTotal(draft.qty, nextUnit)
                                      : null
                                    const next = { ...draft, unit_price_base: nextUnit, base_total: autoTotal ?? draft.base_total }
                                    setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                    void persistItemRow(it, next)
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key !== "Enter") return
                                    e.preventDefault()
                                    const nextUnit = normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.unit_price_base)
                                    const autoTotal = shouldAutoCalcFromQty(draft.qty)
                                      ? tryCalcBaseTotal(draft.qty, nextUnit)
                                      : null
                                    const next = { ...draft, unit_price_base: nextUnit, base_total: autoTotal ?? draft.base_total }
                                    commitItemDraft(it, next)
                                  }}
                                />
                              </td>
                              <td className="col-sum">
                                <input
                                  className="input"
                                  value={displayDraftNumber(draft.base_total)}
                                  placeholder=""
                                  readOnly={shouldAutoCalcFromQty(draft.qty)}
                                  onChange={(e) => setItemDrafts((prev) => ({ ...prev, [it.id]: { ...draft, base_total: e.target.value } }))}
                                  onFocus={(e) => handleZeroFocus(e.currentTarget)}
                                  onBlur={(e) => {
                                    const next = { ...draft, base_total: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.base_total) }
                                    setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                    void persistItemRow(it, next)
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key !== "Enter") return
                                    e.preventDefault()
                                    const next = { ...draft, base_total: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.base_total) }
                                    commitItemDraft(it, next)
                                  }}
                                />
                              </td>
                              {showRowTotalColumn && (
                                <td className="col-row-total">
                                  <input
                                    className="input"
                                    value={displayNumberValue(rowTotal)}
                                    readOnly
                                  />
                                </td>
                              )}
                              {showExtraProfitColumns && (
                                <td className="col-extra-amount">
                                  {draft.extra_profit_enabled ? (
                                    <input
                                      className="input"
                                      value={displayDraftNumber(draft.extra_profit_amount)}
                                      onChange={(e) => setItemDrafts((prev) => ({ ...prev, [it.id]: { ...draft, extra_profit_amount: e.target.value } }))}
                                      onFocus={(e) => handleZeroFocus(e.currentTarget)}
                                      onBlur={(e) => {
                                        const next = { ...draft, extra_profit_amount: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.extra_profit_amount) }
                                        setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                        void persistItemRow(it, next)
                                      }}
                                      onKeyDown={(e) => {
                                        if (e.key !== "Enter") return
                                        e.preventDefault()
                                        const next = { ...draft, extra_profit_amount: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.extra_profit_amount) }
                                        commitItemDraft(it, next)
                                      }}
                                    />
                                  ) : hasSubitems ? (
                                    <input
                                      className="input"
                                      value={displayNumberValue(rowMath?.extra ?? 0)}
                                      readOnly
                                    />
                                  ) : (
                                    <span className="muted" />
                                  )}
                                </td>
                              )}
                              <td className="col-extra-toggle">
                                <input
                                  type="checkbox"
                                  checked={draft.extra_profit_enabled}
                                  onChange={(e) => {
                                    const checked = e.target.checked
                                    const next = {
                                      ...draft,
                                      extra_profit_enabled: checked,
                                      extra_profit_amount: checked ? draft.extra_profit_amount : "0",
                                    }
                                    setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                    void persistItemRow(it, next)
                                  }}
                                />
                              </td>
                              {showDiscountColumns && (
                                <td className="col-discount-amount">
                                  {isSubitem ? (
                                    <span className="muted" />
                                  ) : draft.discount_enabled ? (
                                    <input
                                      className="input"
                                      value={displayDraftNumber(draft.discount_amount)}
                                      onChange={(e) => setItemDrafts((prev) => ({ ...prev, [it.id]: { ...draft, discount_amount: e.target.value } }))}
                                      onFocus={(e) => handleZeroFocus(e.currentTarget)}
                                      onBlur={(e) => {
                                        const next = { ...draft, discount_amount: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.discount_amount) }
                                        setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                        void persistItemRow(it, next)
                                      }}
                                      onKeyDown={(e) => {
                                        if (e.key !== "Enter") return
                                        e.preventDefault()
                                        const next = { ...draft, discount_amount: normalizeNumberDraftInputKeepingZero(e.currentTarget.value, draft.discount_amount) }
                                        commitItemDraft(it, next)
                                      }}
                                    />
                                  ) : (
                                    <span className="muted" />
                                  )}
                                </td>
                              )}
                              <td className="col-discount-toggle">
                                {isSubitem ? (
                                  <span className="muted" />
                                ) : (
                                  <input
                                    type="checkbox"
                                    checked={draft.discount_enabled}
                                    onChange={(e) => {
                                      const checked = e.target.checked
                                      const next = {
                                        ...draft,
                                        discount_enabled: checked,
                                        discount_amount: checked ? draft.discount_amount : "0",
                                      }
                                      setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                      void persistItemRow(it, next)
                                    }}
                                  />
                                )}
                              </td>
                              <td className="col-estimate">
                                <input
                                  type="checkbox"
                                  checked={draft.include_in_estimate}
                                  onChange={(e) => {
                                    const next = { ...draft, include_in_estimate: e.target.checked }
                                    setItemDrafts((prev) => ({ ...prev, [it.id]: next }))
                                    void persistItemRow(it, next)
                                  }}
                                />
                              </td>
                              <td className="col-actions">
                                <button
                                  className="btn icon-btn"
                                  aria-label="Удалить строку"
                                  disabled={savingItemId === it.id}
                                  onClick={() => void deleteItemRow(it.id)}
                                >
                                  <TrashIcon />
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="panel agency-line group-agency-line">
                  <div className="agency-row">
                    <div className="agency-title">Агентские ({toPercentLabel(project.agency_fee_percent)}%)</div>
                    {agencyEnabled && (
                      <div className="agency-amount">{toMoney(agencyAmount)}</div>
                    )}
                    <button
                      className="btn sheet-plus-btn agency-add-btn"
                      aria-label={agencyEnabled ? "Убрать агентские в группе" : "Добавить агентские в группе"}
                      disabled={creatingInGroup === g.id || savingGroupId === g.id || deletingGroupId === g.id}
                      onClick={() => setGroupAgencyEnabled((prev) => {
                        const next = { ...prev }
                        if (next[g.id]) {
                          delete next[g.id]
                        } else {
                          next[g.id] = true
                        }
                        return next
                      })}
                    >
                      {agencyEnabled ? "-" : "+"}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}

          <div className="panel agency-line common-agency-line">
            <div className="agency-row">
              <div className="agency-title">Агентские ({toPercentLabel(project.agency_fee_percent)}%)</div>
              {isCommonAgencyOpen && (
                <div className="agency-amount">{toMoney(commonAgencyAmount)}</div>
              )}
              <button
                className="btn sheet-plus-btn agency-add-btn"
                aria-label={isCommonAgencyOpen ? "Убрать агентские на весь проект" : "Добавить агентские на весь проект"}
                onClick={() => setIsCommonAgencyOpen((prev) => !prev)}
              >
                {isCommonAgencyOpen ? "-" : "+"}
              </button>
            </div>
          </div>

          <div className="panel agency-line">
            <div className="agency-row">
              <div className="agency-title">УСН ({toPercentLabel(usnRate)}%)</div>
              <div className="agency-amount">{toMoney(usnAmount)}</div>
            </div>
          </div>
        </div>
      )}

      {tab === "payments" && (
        <div className="grid income-sheet payments-layout">
          <div className="row payments-add-row">
            <button
              className="btn sheet-plus-btn"
              aria-label="Добавить оплату"
              onClick={() => void createPaymentRow()}
            >
              +
            </button>
            <div className="payments-summary-field">
              <div className="muted">Сумма оплат</div>
              <div className="payments-summary-value">{toMoneyInt(paymentsTotal)}</div>
            </div>
            <div className={`payments-summary-field ${paymentsDiffIsAccent ? "accent" : ""}`}>
              <div className="muted">Разница</div>
              <div className="payments-summary-value">
                {paymentsDiff > 0 ? "+" : ""}
                {toMoneyInt(paymentsDiff)}
              </div>
            </div>
          </div>

          {paymentRows.length > 0 && (
            <div className="panel payments-rows-panel">
              <div className="payments-list-wrap">
                {paymentRows.map((row) => {
                  const draft = row.kind === "plan"
                    ? (planDrafts[row.id] || { pay_date: row.pay_date, amount: formatNumberValueForInput(row.amount), note: row.note || "" })
                    : (factDrafts[row.id] || { pay_date: row.pay_date, amount: formatNumberValueForInput(row.amount), note: row.note || "" })
                  return (
                    <div className="payments-line" key={`${row.kind}-${row.id}`}>
                      <div className="date-cell">
                        <input
                          className="input payments-date-input"
                          value={draft.pay_date}
                          placeholder="дд.мм.гггг"
                          onChange={(e) => {
                            const next = { ...draft, pay_date: e.target.value }
                            if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                            else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                          }}
                          onClick={(e) => {
                            const picker = e.currentTarget.nextElementSibling as HTMLInputElement | null
                            openNativePicker(picker, true)
                          }}
                          onFocus={(e) => {
                            const picker = e.currentTarget.nextElementSibling as HTMLInputElement | null
                            openNativePicker(picker, true)
                          }}
                          onBlur={(e) => {
                            const next = { ...draft, pay_date: normalizeDateDraftInput(e.currentTarget.value) }
                            if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                            else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                            void persistPaymentRow(row.kind, row.id, next)
                          }}
                          onKeyDown={(e) => {
                            if (e.key !== "Enter") return
                            e.preventDefault()
                            const next = { ...draft, pay_date: normalizeDateDraftInput(e.currentTarget.value) }
                            if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                            else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                            void persistPaymentRow(row.kind, row.id, next)
                          }}
                        />
                        <input
                          className="date-picker-hidden"
                          type="date"
                          tabIndex={-1}
                          aria-hidden="true"
                          value={toCalendarDateValue(draft.pay_date)}
                          onChange={(e) => {
                            const next = { ...draft, pay_date: e.target.value }
                            if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                            else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                            void persistPaymentRow(row.kind, row.id, next)
                          }}
                        />
                      </div>
                      <input
                        className="input payments-amount-input"
                        value={draft.amount}
                        maxLength={15}
                        placeholder="Сумма"
                        onFocus={(e) => handleZeroFocus(e.currentTarget)}
                        onChange={(e) => {
                          const next = { ...draft, amount: e.target.value }
                          if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                          else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                        }}
                        onBlur={(e) => {
                          const next = { ...draft, amount: normalizeNumberDraftInput(e.currentTarget.value) }
                          if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                          else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                          void persistPaymentRow(row.kind, row.id, next)
                        }}
                        onKeyDown={(e) => {
                          if (e.key !== "Enter") return
                          e.preventDefault()
                          const next = { ...draft, amount: normalizeNumberDraftInput(e.currentTarget.value) }
                          if (row.kind === "plan") setPlanDrafts((prev) => ({ ...prev, [row.id]: next }))
                          else setFactDrafts((prev) => ({ ...prev, [row.id]: next }))
                          void persistPaymentRow(row.kind, row.id, next)
                        }}
                      />
                      <button
                        className="btn icon-btn"
                        aria-label="Удалить оплату"
                        onClick={() => void deletePaymentRow(row.kind, row.id)}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "sheets" && (
        <div className="classic-layout">
          <div className="panel">
            <div className="h1">Google Sheets ({sheetStatus?.mode || "unknown"})</div>
            {sheetStatus?.mode === "real" && (
              <div className="panel" style={{ marginBottom: 12 }}>
                <div className="muted">OAuth connected: {googleAuth?.connected ? "yes" : "no"}</div>
                <div className="muted">client_secret: {googleAuth?.client_secret_configured ? "configured" : "missing"}</div>
                <div className="muted">redirect_uri: {googleAuth?.redirect_uri || "—"}</div>
                <div className="row">
                  <button className="btn" onClick={() => void refreshGoogleAuthStatus()}>Refresh Auth</button>
                  <button
                    className="btn"
                    onClick={() => void (async () => {
                      try {
                        const start = await apiGet<GoogleAuthStart>(`/api/google/auth/start`)
                        window.open(start.auth_url, "_blank", "noopener,noreferrer")
                      } catch (e) {
                        setError(String(e))
                      }
                    })()}
                  >
                    Connect Google
                  </button>
                </div>
              </div>
            )}

            <div className="muted">spreadsheet_id: {sheetStatus?.spreadsheet_id || "—"}</div>
            <div className="muted">tab: {sheetStatus?.sheet_tab_name || "PROJECT"}</div>
            <div className="muted">last_published_at: {sheetStatus?.last_published_at || "—"}</div>
            <div className="muted">last_imported_at: {sheetStatus?.last_imported_at || "—"}</div>
            <div className="muted">mock_file: {sheetStatus?.mock_file_path || "—"}</div>
            {sheetStatus?.sheet_url && (
              <div className="muted">
                sheet_url: <a href={sheetStatus.sheet_url} target="_blank" rel="noreferrer">{sheetStatus.sheet_url}</a>
              </div>
            )}

            <div className="row" style={{ marginTop: 10 }}>
              <button
                className="btn"
                disabled={!sheetsReady}
                onClick={() => void (async () => {
                  try {
                    const out = await apiPost<SheetsPublish>(`/api/projects/${projectId}/sheets/publish`, {})
                    setSheetPreview(null)
                    setSheetPreviewToken(null)
                    setSheetStatus((prev) => ({
                      ...(prev || { mode: "mock" }),
                      spreadsheet_id: out.spreadsheet_id,
                      sheet_url: out.sheet_url || null,
                      mock_file_path: out.mock_file_path || null,
                      last_published_at: out.last_published_at,
                    }))
                    await loadAll()
                  } catch (e) {
                    setError(String(e))
                  }
                })()}
              >
                Publish
              </button>
              <button
                className="btn"
                disabled={!sheetsReady}
                onClick={() => void (async () => {
                  try {
                    const preview = await apiPost<SheetsPreview>(`/api/projects/${projectId}/sheets/import/preview`, {})
                    setSheetPreview(preview)
                    setSheetPreviewToken(preview.preview_token)
                  } catch (e) {
                    setError(String(e))
                  }
                })()}
              >
                Import Preview
              </button>
              <button
                className="btn"
                disabled={!sheetsReady || !sheetPreviewToken}
                onClick={() => void (async () => {
                  try {
                    if (!sheetPreviewToken) throw new Error("PREVIEW_TOKEN_REQUIRED")
                    await apiPost<SheetsApply>(`/api/projects/${projectId}/sheets/import/apply`, { preview_token: sheetPreviewToken })
                    setSheetPreview(null)
                    setSheetPreviewToken(null)
                    await loadAll()
                  } catch (e) {
                    setError(String(e))
                  }
                })()}
              >
                Import Apply
              </button>
            </div>
          </div>

          <div className="panel">
            <div className="h1">Diff Preview</div>
            {sheetPreview && (
              <div className="grid">
                <div className="muted">preview_token: {sheetPreview.preview_token}</div>
                <div className="muted">items_updated: {sheetPreview.items_updated.length}</div>
                <div className="muted">payments_updated: {sheetPreview.payments_updated.length}</div>
                <div className="muted">payments_new: {sheetPreview.payments_new.length}</div>
                <div className="muted">errors: {sheetPreview.errors.length}</div>

                {sheetPreview.items_updated.map((row) => (
                  <div className="project-tile" key={row.item_id}>
                    <div className="project-tile-title">{row.title}</div>
                    {Object.entries(row.changes).map(([key, change]) => (
                      <div className="muted" key={`${row.item_id}-${key}`}>{key}: {String(change.from)} → {String(change.to)}</div>
                    ))}
                  </div>
                ))}
                {sheetPreview.payments_updated.map((row) => (
                  <div className="project-tile" key={row.pay_id}>
                    <div className="project-tile-title">Payment {row.pay_id}</div>
                    {Object.entries(row.changes).map(([key, change]) => (
                      <div className="muted" key={`${row.pay_id}-${key}`}>{key}: {String(change.from)} → {String(change.to)}</div>
                    ))}
                  </div>
                ))}
                {sheetPreview.payments_new.map((row, i) => (
                  <div className="project-tile" key={`new-${i}`}>
                    <div className="project-tile-title">Новый платёж</div>
                    <div className="muted">{row.pay_date} • {toMoney(row.amount)}</div>
                    <div className="muted">{row.note || "—"}</div>
                  </div>
                ))}
                {sheetPreview.errors.map((e, i) => (
                  <div className="project-tile" key={`err-${i}`}>
                    <div className="muted" style={{ color: "#ff9a9a" }}>{e}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="panel">
          <div className="muted" style={{ color: "#ff9a9a" }}>{error}</div>
        </div>
      )}
    </div>
    {isSettingsOpen && (
      <div
        className="modal-backdrop"
        onClick={() => {
          if (!settingsSaving) setIsSettingsOpen(false)
        }}
      >
        <div className="panel project-settings-panel project-settings-modal" onClick={(e) => e.stopPropagation()}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="h1">Настройки проекта</div>
          </div>

          <div className="project-settings-grid">
            <label className="settings-field">
              <span className="settings-label">Название проекта</span>
              <input
                className="input"
                value={settingsForm.title}
                onChange={(e) => setSettingsForm((prev) => ({ ...prev, title: e.target.value }))}
                placeholder="Название проекта"
              />
            </label>

            <label className="settings-field">
              <span className="settings-label">Название фирмы</span>
              <input
                className="input"
                value={settingsForm.client_name}
                onChange={(e) => setSettingsForm((prev) => ({ ...prev, client_name: e.target.value }))}
                placeholder="Название фирмы"
              />
            </label>

            <label className="settings-field">
              <span className="settings-label">Google Drive URL</span>
              <input
                className="input"
                value={settingsForm.google_drive_url}
                onChange={(e) => setSettingsForm((prev) => ({ ...prev, google_drive_url: e.target.value }))}
                placeholder="https://drive.google.com/..."
              />
            </label>

            <label className="settings-field">
              <span className="settings-label">Папка сметы (ID / имя)</span>
              <input
                className="input"
                value={settingsForm.google_drive_folder}
                onChange={(e) => setSettingsForm((prev) => ({ ...prev, google_drive_folder: e.target.value }))}
                placeholder="ID папки или название"
              />
            </label>

            <label className="settings-field">
              <span className="settings-label">Агентские, %</span>
              <input
                className="input"
                value={settingsForm.agency_fee_percent}
                onChange={(e) => setSettingsForm((prev) => ({ ...prev, agency_fee_percent: e.target.value }))}
                onBlur={(e) => setSettingsForm((prev) => ({ ...prev, agency_fee_percent: normalizeNumberDraftInput(e.currentTarget.value) }))}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return
                  e.preventDefault()
                  setSettingsForm((prev) => ({ ...prev, agency_fee_percent: normalizeNumberDraftInput(e.currentTarget.value) }))
                }}
                placeholder="10"
              />
            </label>

            <div className="settings-field settings-phones">
              <span className="settings-label">Телефоны контакта</span>
              <div className="phones-stack">
                {settingsForm.phones.map((phone, idx) => (
                  <div className="row phone-row" key={`phone-${idx}`}>
                    <input
                      className="input"
                      value={phone}
                      onChange={(e) => setSettingsForm((prev) => ({
                        ...prev,
                        phones: prev.phones.map((p, i) => (i === idx ? e.target.value : p)),
                      }))}
                      placeholder="+7..."
                    />
                    <button
                      className="btn icon-btn"
                      disabled={settingsForm.phones.length <= 1}
                      onClick={() => setSettingsForm((prev) => ({
                        ...prev,
                        phones: prev.phones.length <= 1 ? prev.phones : prev.phones.filter((_, i) => i !== idx),
                      }))}
                    >
                      <TrashIcon />
                    </button>
                  </div>
                ))}
                <button
                  className="btn add-phone-btn"
                  onClick={() => setSettingsForm((prev) => ({ ...prev, phones: [...prev.phones, ""] }))}
                >
                  <PlusIcon /> Телефон
                </button>
              </div>
            </div>
          </div>

          <div className="row">
            <button className="btn" disabled={settingsSaving} onClick={() => void saveProjectSettings()}>Сохранить настройки</button>
            <button className="btn icon-btn modal-close-btn" aria-label="Закрыть окно" disabled={settingsSaving} onClick={() => setIsSettingsOpen(false)}>×</button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
