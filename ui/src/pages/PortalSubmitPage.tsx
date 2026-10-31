import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, DatePicker, Input, InputNumber, Select, Upload, message } from 'antd'
import type { UploadFile } from 'antd/es/upload'
import type { Dayjs } from 'dayjs'
import { CloudUpload, FileSearch } from 'lucide-react'
import { api } from '../api/client'

const CLAIM_TYPES = [
  { value: 'inpatient', label: 'Inpatient (hospital stay)' }, { value: 'daycare', label: 'Day care' },
  { value: 'outpatient', label: 'Outpatient' }, { value: 'pharmacy', label: 'Pharmacy' },
]

export function PortalShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-8 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl text-brand" style={{ background: 'linear-gradient(135deg, #55ffbe, #2ed88e)' }}>
          <FileSearch size={18} />
        </span>
        <div className="leading-tight"><div className="text-[17px] font-semibold">Claims</div><div className="muted text-[11.5px]">Customer portal</div></div>
      </header>
      <main className="mx-auto max-w-[760px] px-6 py-8">{children}</main>
    </div>
  )
}

const day = (d: Dayjs | null) => (d ? d.format('YYYY-MM-DD') : '')

export default function PortalSubmitPage() {
  const nav = useNavigate()
  const [v, setV] = useState({ policy_number: '', member_id: '', claim_type: 'inpatient', provider_name: '', diagnosis: '', phone: '' })
  const [dates, setDates] = useState<{ incident: Dayjs | null; admission: Dayjs | null; discharge: Dayjs | null }>({ incident: null, admission: null, discharge: null })
  const [amount, setAmount] = useState<number | null>(null)
  const [files, setFiles] = useState<UploadFile[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  const ready = v.policy_number && v.member_id && v.provider_name && dates.incident && amount !== null && files.length > 0

  const submit = async () => {
    const form = new FormData()
    Object.entries(v).forEach(([k, val]) => { if (val) form.append(k, val) })
    form.append('incident_date', day(dates.incident))
    if (dates.admission) form.append('admission_date', day(dates.admission))
    if (dates.discharge) form.append('discharge_date', day(dates.discharge))
    form.append('amount_claimed', String(amount ?? 0))
    files.forEach((f) => form.append('files', f.originFileObj as File, f.name))
    setBusy(true); setError(null)
    try {
      const res = await api.portalSubmit(form)
      message.success(`Claim ${res.claim_id} received`)
      nav(`/submit/${encodeURIComponent(res.claim_id)}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const field = (label: string, node: React.ReactNode, required = false) => (
    <label className="block">
      <div className="mb-1 text-[13px] font-medium">{label}{required && <span className="text-red-500"> *</span>}</div>
      {node}
    </label>
  )

  return (
    <PortalShell>
      <h1 className="m-0 text-[26px] font-semibold tracking-tight">Submit a claim</h1>
      <p className="muted mt-1 text-[14px]">Tell us about the treatment and attach the hospital bill and discharge summary. You will see each step as we process it.</p>
      <div className="card mt-5 grid gap-4 p-6 md:grid-cols-2">
        {field('Policy number', <Input value={v.policy_number} onChange={set('policy_number')} />, true)}
        {field('Member id', <Input value={v.member_id} onChange={set('member_id')} />, true)}
        {field('Claim type', <Select className="!w-full" value={v.claim_type} options={CLAIM_TYPES} onChange={(x) => setV({ ...v, claim_type: x })} />, true)}
        {field('Incident date', <DatePicker className="!w-full" value={dates.incident} onChange={(d) => setDates({ ...dates, incident: d })} />, true)}
        {field('Admission date', <DatePicker className="!w-full" value={dates.admission} onChange={(d) => setDates({ ...dates, admission: d })} />)}
        {field('Discharge date', <DatePicker className="!w-full" value={dates.discharge} onChange={(d) => setDates({ ...dates, discharge: d })} />)}
        {field('Hospital', <Input value={v.provider_name} onChange={set('provider_name')} />, true)}
        {field('Amount claimed', <InputNumber className="!w-full" min={0} value={amount} onChange={setAmount} />, true)}
        {field('Diagnosis', <Input value={v.diagnosis} onChange={set('diagnosis')} />)}
        {field('Phone', <Input value={v.phone} onChange={set('phone')} />)}
        <div className="md:col-span-2">
          {field('Documents', (
            <Upload.Dragger multiple accept=".pdf,.jpg,.jpeg,.png" fileList={files} beforeUpload={() => false}
              onChange={({ fileList }) => setFiles(fileList.slice(0, 10))} className="!bg-white">
              <p className="flex justify-center text-accent"><CloudUpload size={32} /></p>
              <p className="text-[15px] font-medium">Drop the bill and discharge summary here</p>
              <p className="muted text-[12.5px]">PDF, JPG or PNG · up to 10 files · 10 MB each</p>
            </Upload.Dragger>
          ), true)}
        </div>
        {error && <Alert className="md:col-span-2" type="error" showIcon message="The claim could not be submitted" description={error} />}
        <div className="md:col-span-2">
          <Button type="primary" size="large" loading={busy} disabled={!ready} onClick={submit}>Submit claim</Button>
        </div>
      </div>
    </PortalShell>
  )
}
