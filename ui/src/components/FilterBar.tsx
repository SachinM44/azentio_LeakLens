import { Button, DatePicker, InputNumber, Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { FilterX } from 'lucide-react'
import { api } from '../api/client'
import { CATEGORY_LABEL, CLAIM_STATUSES, CLAIM_TYPES, titleCase } from '../lib/format'
import { useFilters } from '../lib/filters'

/** Filters from the brief: claim type, provider, leakage category, amount range, date range (+ claim status). */
export default function FilterBar({ showStatus = true }: { showStatus?: boolean }) {
  const { filters, patch, clear, activeCount } = useFilters()
  // Provider choices come from the unfiltered dashboard so the list does not shrink as other filters apply.
  const providers = useQuery({ queryKey: ['dashboard', {}], queryFn: () => api.dashboard({}), staleTime: 30_000 })

  return (
    <div data-tour="filters" className="card flex flex-wrap items-center gap-2 p-3">
      <Select allowClear placeholder="Claim type" className="w-36" value={filters.type} onChange={(v) => patch({ type: v })}
        options={CLAIM_TYPES.map((t) => ({ value: t, label: titleCase(t) }))} />
      <Select allowClear showSearch optionFilterProp="label" placeholder="Provider" className="w-48" value={filters.provider}
        onChange={(v) => patch({ provider: v })}
        options={(providers.data?.by_provider ?? []).map((p) => ({ value: p.provider_id, label: p.provider_name }))} />
      <Select allowClear placeholder="Leakage category" className="w-48" value={filters.category} onChange={(v) => patch({ category: v })}
        options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))} />
      {showStatus && (
        <Select allowClear placeholder="Claim status" className="w-36" value={filters.status} onChange={(v) => patch({ status: v })}
          options={CLAIM_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} />
      )}
      <InputNumber min={0} placeholder="Min amount" className="w-32" value={filters.min_amount ?? null}
        onChange={(v) => patch({ min_amount: v ?? undefined })} />
      <InputNumber min={0} placeholder="Max amount" className="w-32" value={filters.max_amount ?? null}
        onChange={(v) => patch({ max_amount: v ?? undefined })} />
      <DatePicker.RangePicker
        value={filters.from || filters.to ? [filters.from ? dayjs(filters.from) : null, filters.to ? dayjs(filters.to) : null] : null}
        onChange={(range) => patch({ from: range?.[0]?.format('YYYY-MM-DD'), to: range?.[1]?.format('YYYY-MM-DD') })}
        placeholder={['Incident from', 'Incident to']} />
      <Button icon={<FilterX size={14} />} onClick={clear} disabled={!activeCount}>Clear{activeCount ? ` (${activeCount})` : ''}</Button>
    </div>
  )
}
