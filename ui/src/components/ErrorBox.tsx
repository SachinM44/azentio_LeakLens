import { Alert, Button } from 'antd'
import { Database, RefreshCw } from 'lucide-react'
import { ApiError, connection } from '../api/client'

/** A 0/5xx from the proxy means the backend is not reachable; offer the mock data instead of a dead end. */
export default function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const text = error instanceof Error ? error.message : String(error)
  const unreachable = error instanceof ApiError && (error.status === 0 || error.status >= 500)

  const useDemo = () => {
    connection.save({ baseUrl: connection.baseUrl, apiKey: connection.apiKey, useMocks: true })
    window.location.reload()
  }

  return (
    <Alert type="error" showIcon className="!rounded-2xl"
      message={unreachable ? 'The backend is not reachable' : 'Could not load data'}
      description={(
        <div>
          <div>{text}</div>
          {unreachable && <div className="muted mt-1 text-[12.5px]">Start the API on port 8000, or explore the screens with built-in demo data.</div>}
        </div>
      )}
      action={(
        <div className="flex flex-col gap-2">
          {unreachable && <Button type="primary" size="small" icon={<Database size={13} />} onClick={useDemo}>Use demo data</Button>}
          {onRetry && <Button size="small" icon={<RefreshCw size={13} />} onClick={onRetry}>Retry</Button>}
        </div>
      )} />
  )
}
