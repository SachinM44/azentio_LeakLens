import { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Switch, message } from 'antd'
import { api, connection } from '../api/client'

export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [useMocks, setUseMocks] = useState(false)
  const [analyst, setAnalyst] = useState('')
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    if (open) { setBaseUrl(connection.baseUrl); setApiKey(connection.apiKey); setUseMocks(connection.useMocks); setAnalyst(connection.analyst) }
  }, [open])

  const save = (reload = true) => {
    connection.save({ baseUrl, apiKey, useMocks, analyst })
    if (reload) window.location.reload()
  }

  const test = async () => {
    connection.save({ baseUrl, apiKey, useMocks: false })
    setTesting(true)
    try {
      const h = await api.health()
      await api.listClaims({})
      message.success(`Connected (${h.store})`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      connection.save({ baseUrl, apiKey, useMocks })
      setTesting(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} title="Connection" onOk={() => save()} okText="Save & reload">
      <div className="flex flex-col gap-4 py-2">
        <label className="flex items-center justify-between gap-3">
          <span><b>Use mock data</b><br /><span className="muted text-[13px]">Demo the screens without a backend.</span></span>
          <Switch checked={useMocks} onChange={setUseMocks} />
        </label>
        <label>
          <div className="mb-1 font-medium">Your name (analyst)</div>
          <Input value={analyst} onChange={(e) => setAnalyst(e.target.value)} placeholder="e.g. Priya Sharma" />
          <div className="muted mt-1 text-[12px]">Recorded on every decision, note and report as the user identity.</div>
        </label>
        <label>
          <div className="mb-1 font-medium">API base URL</div>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="/api  or  https://xyz.trycloudflare.com" disabled={useMocks} />
          <div className="muted mt-1 text-[12px]"><span className="mono">/api</span> uses the Vite dev proxy to http://localhost:8000.</div>
        </label>
        <label>
          <div className="mb-1 font-medium">API key (X-API-Key)</div>
          <Input.Password value={apiKey} onChange={(e) => setApiKey(e.target.value)} disabled={useMocks} />
        </label>
        <Button onClick={test} loading={testing} disabled={useMocks}>Test connection</Button>
        {useMocks && <Alert type="info" showIcon message="Mock mode: reviews and runs change in-memory data only; documents are unavailable." />}
      </div>
    </Modal>
  )
}
