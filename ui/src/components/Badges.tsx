import { Tag } from 'antd'
import { CircleDot, Calculator, HelpCircle } from 'lucide-react'
import type { AmountKind, FindingStatus, Severity } from '../api/types'
import { CATEGORY_COLOR, CATEGORY_LABEL, SEVERITY_COLOR, STATUS_COLOR, STATUS_LABEL, titleCase } from '../lib/format'
import type { CheckCategory } from '../api/types'

export function SeverityBadge({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return <span className="muted">—</span>
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] font-medium" style={{ color: SEVERITY_COLOR[severity] }}>
      <CircleDot size={13} /> {titleCase(severity)}
    </span>
  )
}

/** The brief insists a calculated discrepancy is never confused with a suspected one. */
export function AmountKindBadge({ kind }: { kind: AmountKind }) {
  return kind === 'calculated' ? (
    <Tag color="green" className="!m-0 inline-flex items-center gap-1"><Calculator size={12} /> Calculated</Tag>
  ) : (
    <Tag color="orange" className="!m-0 inline-flex items-center gap-1"><HelpCircle size={12} /> Suspected</Tag>
  )
}

export function StatusTag({ status }: { status: FindingStatus }) {
  return <Tag color={STATUS_COLOR[status]} className="!m-0">{STATUS_LABEL[status]}</Tag>
}

export function CategoryTag({ category }: { category: CheckCategory }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]">
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: CATEGORY_COLOR[category] }} />
      {CATEGORY_LABEL[category] ?? titleCase(category)}
    </span>
  )
}
