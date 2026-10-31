import { useEffect, useState } from 'react'
import { Alert, Button, Input, Select, Skeleton, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { api } from '../api/client'
import type { ProductConfig } from '../api/types'
import ErrorBox from '../components/ErrorBox'

export default function ConfigPage() {
  const qc = useQueryClient()
  const products = useQuery({ queryKey: ['config'], queryFn: api.listConfig })
  const [productId, setProductId] = useState<string>()
  const current = products.data?.find((p) => p.product_id === productId)
  const [text, setText] = useState('')

  useEffect(() => {
    if (!productId && products.data?.length) setProductId(products.data[0].product_id)
  }, [products.data, productId])
  useEffect(() => { if (current) setText(JSON.stringify(current, null, 2)) }, [current])

  let parsed: ProductConfig | null = null
  let parseError = ''
  try { parsed = JSON.parse(text) as ProductConfig } catch (e) { parseError = (e as Error).message }
  const dirty = !!current && text !== JSON.stringify(current, null, 2)

  const save = useMutation({
    mutationFn: () => api.putConfig(productId!, parsed!),
    onSuccess: () => { message.success('Configuration saved. New runs use it; re-run a claim to apply it.'); qc.invalidateQueries({ queryKey: ['config'] }) },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <div className="flex flex-col gap-4">
      <section className="hero rise p-7">
        <div className="eyebrow">Rule book</div>
        <h1 className="mb-1 mt-1.5 text-[26px] font-semibold tracking-tight text-white">Product configuration</h1>
        <p className="m-0 max-w-2xl text-[13.5px] text-white/65">
          Currency, non-payable items, repeatable service codes, near-duplicate tolerances, required documents and the auto-triage threshold.
          Every save is written to the audit log.
        </p>
      </section>

      {products.isError ? <ErrorBox error={products.error} onRetry={() => products.refetch()} /> : products.isLoading ? <Skeleton active /> : (
        <>
          {!products.data?.length && (
            <Alert type="info" showIcon message="No product configuration stored yet"
              description="Products are created when claims are ingested; ingest a claims file first." />
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Select className="w-72" value={productId} onChange={setProductId} placeholder="Product"
              options={(products.data ?? []).map((p) => ({ value: p.product_id, label: `${p.name} (${p.product_id})` }))} />
            <Button type="primary" icon={<Save size={14} />} loading={save.isPending} disabled={!dirty || !parsed} onClick={() => save.mutate()}>Save</Button>
            <Button disabled={!dirty} onClick={() => current && setText(JSON.stringify(current, null, 2))}>Revert</Button>
          </div>
          <Input.TextArea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} rows={26} className="mono !text-[13px]" />
          {parseError && <Alert type="error" showIcon message="Not valid JSON" description={parseError} />}
        </>
      )}
    </div>
  )
}
