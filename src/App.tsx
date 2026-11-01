import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleGauge,
  CircleStop,
  Clock3,
  Cpu,
  Database,
  Download,
  Gauge,
  HardDrive,
  Hash,
  Info,
  Network,
  Play,
  Power,
  Radar,
  RefreshCw,
  Server,
  ShieldCheck,
  Signal,
  Sparkles,
  Target,
  Terminal,
  Thermometer,
  Wallet,
  Waves,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type {
  MinerConfiguration,
  MinerEvent,
  MinerForm,
  MinerTelemetry,
  MiningMode,
} from './types'

type ApiState = 'connecting' | 'online' | 'offline'

type HistoryPoint = {
  timestamp: number
  hashrate: number
  power: number
  temperature: number
}

const defaultForm: MinerForm = {
  mode: 'pool',
  wallet: '',
  worker: 'blockhunter',
  pool: 'pearl-eu2.luckypool.io:3360',
  soloGateway: '127.0.0.1:8337',
}

const activeStates = new Set(['starting', 'syncing', 'running', 'stopping'])

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { error?: string }
  if (!response.ok) throw new Error(payload.error || `BlockHunter returned ${response.status}`)
  return payload
}

function formatDuration(startedAt: string | null | undefined): string {
  if (!startedAt) return '00:00:00'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return [hours, minutes, remainder].map((value) => value.toString().padStart(2, '0')).join(':')
}

function formatEventTime(timestamp: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestamp))
}

function shortHash(value: string | undefined, length = 12): string {
  if (!value) return '—'
  return value.length <= length ? value : `${value.slice(0, length)}…`
}

function clamp(value: number, minimum = 0, maximum = 100): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function MetricCard({
  icon,
  label,
  value,
  unit,
  detail,
  tone = 'standard',
}: {
  icon: ReactNode
  label: string
  value: string
  unit?: string
  detail: string
  tone?: 'standard' | 'accent' | 'warning'
}) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__header">
        <span>{label}</span>
        {icon}
      </div>
      <strong>
        {value} {unit && <small>{unit}</small>}
      </strong>
      <p>{detail}</p>
    </article>
  )
}

function PerformanceChart({ history }: { history: HistoryPoint[] }) {
  const width = 760
  const height = 240
  const chartTop = 20
  const chartBottom = 204
  const maxHashrate = Math.max(60, ...history.map((point) => point.hashrate))
  const points = history.map((point, index) => {
    const x = history.length <= 1 ? 0 : (index / (history.length - 1)) * width
    const y = chartBottom - (point.hashrate / maxHashrate) * (chartBottom - chartTop)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const area = points.length ? `0,${chartBottom} ${points.join(' ')} ${width},${chartBottom}` : ''
  const latest = history.at(-1)

  return (
    <article className="panel performance-panel" id="performance">
      <div className="panel-heading">
        <div>
          <span className="eyebrow"><Activity size={13} /> Effective performance</span>
          <h2>Compute signal</h2>
        </div>
        <div className="chart-legend">
          <span><i /> Hashrate</span>
          <strong>{latest?.hashrate.toFixed(2) ?? '—'} TH/s</strong>
        </div>
      </div>
      <div className="chart-wrap">
        {history.length < 2 && (
          <div className="chart-empty">
            <Waves size={24} />
            <span>Performance history appears when telemetry begins.</span>
          </div>
        )}
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Recent Pearl mining hashrate">
          <defs>
            <linearGradient id="hash-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#72f0c4" stopOpacity="0.34" />
              <stop offset="1" stopColor="#72f0c4" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 1, 2, 3, 4].map((line) => {
            const y = chartTop + ((chartBottom - chartTop) / 4) * line
            return <line className="chart-grid-line" key={line} x1="0" x2={width} y1={y} y2={y} />
          })}
          {area && <polygon className="chart-area" points={area} />}
          {points.length > 1 && <polyline className="chart-line" points={points.join(' ')} />}
        </svg>
      </div>
      <div className="chart-footer">
        <span><Power size={14} /> {latest?.power.toFixed(0) ?? '—'} W draw</span>
        <span><Thermometer size={14} /> {latest?.temperature.toFixed(0) ?? '—'} °C</span>
        <span><Clock3 size={14} /> Rolling local session</span>
      </div>
    </article>
  )
}

function CandidateRadar({ telemetry }: { telemetry: MinerTelemetry | null }) {
  const mode = telemetry?.mode === 'solo' ? 'solo' : 'pool'
  const candidateEvents = (telemetry?.events ?? []).filter(
    (event) => event.kind === 'share' || event.kind === 'block',
  )
  const visibleBlips = candidateEvents.slice(0, 8)
  const candidateCount = mode === 'solo'
    ? telemetry?.blockCandidates ?? 0
    : telemetry?.proofCandidates ?? 0

  return (
    <article className="panel radar-panel" id="candidates">
      <div className="panel-heading">
        <div>
          <span className="eyebrow"><Radar size={13} /> Candidate telemetry</span>
          <h2>{mode === 'solo' ? 'Block candidate radar' : 'Potential block radar'}</h2>
        </div>
        <span className={`mode-chip mode-chip--${mode}`}>{mode}</span>
      </div>
      <div className="radar-layout">
        <div className="radar-stage" aria-label={`${candidateCount} candidates detected`}>
          <svg viewBox="0 0 240 240" role="img">
            <circle className="radar-ring" cx="120" cy="120" r="92" />
            <circle className="radar-ring" cx="120" cy="120" r="62" />
            <circle className="radar-ring" cx="120" cy="120" r="32" />
            <line className="radar-axis" x1="120" y1="22" x2="120" y2="218" />
            <line className="radar-axis" x1="22" y1="120" x2="218" y2="120" />
            <path className="radar-sweep-fill" d="M120 120 L120 26 A94 94 0 0 1 206 82 Z" />
            <line className="radar-sweep" x1="120" y1="120" x2="120" y2="26" />
            {visibleBlips.map((event, index) => {
              const angle = ((event.id * 137.5) % 360) * (Math.PI / 180)
              const radius = 30 + ((event.id * 19) % 58)
              const x = 120 + Math.cos(angle) * radius
              const y = 120 + Math.sin(angle) * radius
              return (
                <g key={event.id} className={`radar-blip radar-blip--${event.kind}`}>
                  <circle cx={x} cy={y} r={index === 0 ? 5 : 3.5} />
                  {index === 0 && <circle className="radar-blip-pulse" cx={x} cy={y} r="9" />}
                </g>
              )
            })}
          </svg>
          <div className="radar-core">
            <strong>{candidateCount}</strong>
            <span>candidates</span>
          </div>
        </div>
        <div className="radar-summary">
          <div>
            <span>{mode === 'solo' ? 'Proofs submitted' : 'Shares accepted'}</span>
            <strong>
              {mode === 'solo'
                ? telemetry?.submittedBlockProofs ?? 0
                : telemetry?.acceptedUserShares ?? 0}
            </strong>
          </div>
          <div>
            <span>{mode === 'solo' ? 'Network confirmations' : 'Rejected shares'}</span>
            <strong>{mode === 'solo' ? 'External' : telemetry?.rejectedShares ?? 0}</strong>
          </div>
          <div>
            <span>Current target</span>
            <strong>{telemetry?.targetExponent ? `2^${telemetry.targetExponent}` : 'Waiting'}</strong>
          </div>
        </div>
      </div>
      <div className="radar-disclosure">
        <Info size={15} />
        <p>
          {mode === 'solo'
            ? 'A radar hit is a potential block proof. The local gateway still has to build and submit the block, and the network must accept it.'
            : 'Pool hits are qualifying share proofs. Only the pool can determine whether a share also satisfies the live network block target.'}
        </p>
      </div>
    </article>
  )
}

function VitalBar({ label, value, detail, tone }: {
  label: string
  value: number
  detail: string
  tone?: 'safe' | 'warm'
}) {
  return (
    <div className="vital-bar">
      <div><span>{label}</span><strong>{detail}</strong></div>
      <div className="vital-bar__track"><i className={tone ? `vital-bar__fill--${tone}` : ''} style={{ width: `${clamp(value)}%` }} /></div>
    </div>
  )
}

function EventRow({ event }: { event: MinerEvent }) {
  const icon = event.kind === 'block'
    ? <Target size={15} />
    : event.kind === 'share'
      ? <Hash size={15} />
      : event.kind === 'guardrail' || event.kind === 'warning'
        ? <AlertTriangle size={15} />
        : event.kind === 'network'
          ? <Network size={15} />
          : <Activity size={15} />
  return (
    <div className={`event-row event-row--${event.severity}`}>
      <span className="event-row__icon">{icon}</span>
      <div>
        <strong>{event.title}</strong>
        <p>{event.detail || 'No additional detail'}</p>
      </div>
      <time>{formatEventTime(event.timestamp)}</time>
    </div>
  )
}

function App() {
  const [telemetry, setTelemetry] = useState<MinerTelemetry | null>(null)
  const [configuration, setConfiguration] = useState<MinerConfiguration | null>(null)
  const [form, setForm] = useState<MinerForm>(defaultForm)
  const [sessionToken, setSessionToken] = useState('')
  const [apiState, setApiState] = useState<ApiState>('connecting')
  const [action, setAction] = useState('')
  const [notice, setNotice] = useState<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [uptime, setUptime] = useState('00:00:00')
  const lastSampleRef = useRef('')

  useEffect(() => {
    let active = true

    const bootstrap = async () => {
      try {
        const [session, nextConfiguration, nextTelemetry] = await Promise.all([
          fetch('/api/session', { cache: 'no-store' }).then((response) => readJson<{ token: string }>(response)),
          fetch('/api/config', { cache: 'no-store' }).then((response) => readJson<MinerConfiguration>(response)),
          fetch('/api/status', { cache: 'no-store' }).then((response) => readJson<MinerTelemetry>(response)),
        ])
        if (!active) return
        setSessionToken(session.token)
        setConfiguration(nextConfiguration)
        setForm({
          mode: nextConfiguration.mode,
          wallet: nextConfiguration.wallet,
          worker: nextConfiguration.worker,
          pool: nextConfiguration.pool,
          soloGateway: nextConfiguration.soloGateway,
        })
        setTelemetry(nextTelemetry)
        setApiState('online')
      } catch (error) {
        if (!active) return
        setApiState('offline')
        setNotice({ tone: 'error', text: error instanceof Error ? error.message : 'Local service unavailable' })
      }
    }

    void bootstrap()
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const response = await fetch('/api/status', { cache: 'no-store' })
        const nextTelemetry = await readJson<MinerTelemetry>(response)
        if (!active) return
        setTelemetry(nextTelemetry)
        setApiState('online')
        if (
          nextTelemetry.updatedAt !== lastSampleRef.current
          && typeof nextTelemetry.hashrateTHs === 'number'
        ) {
          lastSampleRef.current = nextTelemetry.updatedAt
          setHistory((current) => [
            ...current,
            {
              timestamp: Date.now(),
              hashrate: nextTelemetry.hashrateTHs ?? 0,
              power: nextTelemetry.powerDrawWatts ?? 0,
              temperature: nextTelemetry.temperatureC ?? 0,
            },
          ].slice(-60))
        }
      } catch {
        if (active) setApiState('offline')
      }
    }
    const interval = window.setInterval(refresh, 2000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    const updateUptime = () => setUptime(formatDuration(telemetry?.startedAt))
    updateUptime()
    const interval = window.setInterval(updateUptime, 1000)
    return () => window.clearInterval(interval)
  }, [telemetry?.startedAt])

  const post = async <T,>(path: string, body: Record<string, unknown> = {}): Promise<T> => {
    if (!sessionToken) throw new Error('Local control session is not ready')
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-BlockHunter-Token': sessionToken,
      },
      body: JSON.stringify(body),
    })
    return readJson<T>(response)
  }

  const submitStart = async (event: FormEvent) => {
    event.preventDefault()
    setAction('start')
    setNotice(null)
    try {
      await post('/api/start', form)
      setNotice({ tone: 'success', text: `Starting ${form.mode} mining through ${form.mode === 'pool' ? form.pool : form.soloGateway}` })
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : 'Unable to start mining' })
    } finally {
      setAction('')
    }
  }

  const probe = async () => {
    setAction('probe')
    setNotice(null)
    try {
      const result = await post<{ detail: string; latencyMs: number }>('/api/probe', form)
      setNotice({ tone: 'success', text: `${result.detail} · ${result.latencyMs} ms` })
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : 'Endpoint check failed' })
    } finally {
      setAction('')
    }
  }

  const stop = async () => {
    setAction('stop')
    try {
      await post('/api/stop')
      setNotice({ tone: 'info', text: 'Stop requested. BlockHunter is draining the miner process.' })
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : 'Unable to stop mining' })
    } finally {
      setAction('')
    }
  }

  const shutdown = async () => {
    if (!window.confirm('Stop mining, close the local console, and restore the original GPU settings?')) return
    setAction('shutdown')
    try {
      await post('/api/shutdown')
      setNotice({ tone: 'info', text: 'BlockHunter is closing. The Windows launcher will restore GPU settings.' })
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : 'Unable to close BlockHunter' })
      setAction('')
    }
  }

  const exportDiagnostics = () => {
    const wallet = configuration?.wallet ?? form.wallet
    const report = {
      generatedAt: new Date().toISOString(),
      application: 'BlockHunter Verified Pearl Mining',
      configuration: configuration ? {
        ...configuration,
        wallet: wallet.length > 16 ? `${wallet.slice(0, 10)}…${wallet.slice(-6)}` : wallet,
      } : null,
      telemetry,
      performanceHistory: history,
      browser: {
        userAgent: navigator.userAgent,
        language: navigator.language,
      },
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `blockhunter-diagnostics-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const isActive = activeStates.has(telemetry?.state ?? '')
  const isRunning = telemetry?.state === 'running'
  const efficiency = telemetry?.hashrateTHs && telemetry?.powerDrawWatts
    ? telemetry.hashrateTHs / telemetry.powerDrawWatts
    : null
  const shareAcceptance = telemetry && telemetry.acceptedShares + telemetry.rejectedShares > 0
    ? (telemetry.acceptedShares / (telemetry.acceptedShares + telemetry.rejectedShares)) * 100
    : null
  const vramTotal = (telemetry?.memoryUsedMiB ?? 0) + (telemetry?.memoryFreeMiB ?? 0)
  const recentEvents = useMemo(() => telemetry?.events.slice(0, 10) ?? [], [telemetry?.events])
  const endpoint = form.mode === 'pool' ? form.pool : form.soloGateway
  const soloNode = telemetry?.soloNode
  const soloReady = soloNode?.state === 'ready'
  const soloStateLabel = soloReady
    ? 'Gateway ready'
    : soloNode?.state === 'syncing'
      ? 'Node syncing'
      : soloNode?.state === 'waiting-peers'
        ? 'Finding peers'
        : soloNode?.state === 'starting-gateway'
          ? 'Starting gateway'
          : soloNode?.state === 'starting'
            ? 'Node starting'
            : soloNode?.installed
              ? 'Gateway waiting'
              : 'Solo setup required'

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#overview" aria-label="BlockHunter home">
          <span className="brand-mark"><Target size={22} /></span>
          <span><strong>BLOCKHUNTER</strong><small>Verified Pearl Mining</small></span>
        </a>
        <nav aria-label="Dashboard sections">
          <a href="#overview">Overview</a>
          <a href="#candidates">Candidates</a>
          <a href="#hardware">Hardware</a>
          <a href="#activity">Activity</a>
        </nav>
        <div className={`api-status api-status--${apiState}`}>
          <i /> {apiState === 'online' ? 'Local link secured' : apiState}
        </div>
      </header>

      <main>
        <section className="hero" id="overview">
          <div className="hero__copy">
            <span className="hero-kicker"><Sparkles size={14} /> RTX 4070 / Ada sm_89</span>
            <h1>Mine Pearl with<br /><em>proof, not promises.</em></h1>
            <p>
              A source-pinned mining console that separates raw speed from accepted work,
              watches every candidate, and keeps your GPU inside measured guardrails.
            </p>
            <div className="hero__facts">
              <span><ShieldCheck size={15} /> Checksummed runtime</span>
              <span><Zap size={15} /> 150 W efficiency profile</span>
              <span><Database size={15} /> No wallet custody</span>
            </div>
          </div>
          <div className="hero-status">
            <div className="hero-status__top">
              <span>Mining engine</span>
              <span className={`state-pill state-pill--${telemetry?.state ?? 'offline'}`}><i /> {telemetry?.state ?? 'offline'}</span>
            </div>
            <strong>{telemetry?.hashrateTHs?.toFixed(2) ?? '—'} <small>TH/s</small></strong>
            <div className="hero-status__meta">
              <span><Clock3 size={14} /> {uptime}</span>
              <span><Signal size={14} /> {telemetry?.connectionState ?? 'disconnected'}</span>
            </div>
            <div className="hero-status__endpoint">
              <Network size={15} />
              <span><small>{telemetry?.mode ?? form.mode}</small>{telemetry?.endpoint ?? endpoint}</span>
            </div>
          </div>
        </section>

        <section className="control-grid">
          <article className="panel setup-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><CircleGauge size={13} /> Mining control</span>
                <h2>Choose how to hunt</h2>
              </div>
              <span className="local-only"><ShieldCheck size={14} /> localhost only</span>
            </div>
            <form onSubmit={submitStart}>
              <div className="mode-selector" aria-label="Mining mode">
                <button
                  type="button"
                  className={form.mode === 'pool' ? 'mode-option mode-option--active' : 'mode-option'}
                  onClick={() => setForm((current) => ({ ...current, mode: 'pool' }))}
                  disabled={isActive}
                >
                  <Server size={19} />
                  <span><strong>Pool mining</strong><small>Steady share payouts</small></span>
                  {form.mode === 'pool' && <CheckCircle2 size={17} />}
                </button>
                <button
                  type="button"
                  className={form.mode === 'solo' ? 'mode-option mode-option--active' : 'mode-option'}
                  onClick={() => setForm((current) => ({ ...current, mode: 'solo' }))}
                  disabled={isActive}
                >
                  <Target size={19} />
                  <span><strong>Solo mining</strong><small>Your node, full reward</small></span>
                  {form.mode === 'solo' && <CheckCircle2 size={17} />}
                </button>
              </div>

              {form.mode === 'pool' ? (
                <>
                  <label className="field">
                    <span>Pool address <small>LuckyPool V3 Stratum</small></span>
                    <div><Network size={16} /><input value={form.pool} onChange={(event) => setForm((current) => ({ ...current, pool: event.target.value }))} placeholder="host:port" disabled={isActive} required /></div>
                  </label>
                  <label className="field">
                    <span>Payout wallet <small>Pearl mainnet</small></span>
                    <div><Wallet size={16} /><input value={form.wallet} onChange={(event) => setForm((current) => ({ ...current, wallet: event.target.value }))} placeholder="prl1p…" disabled={isActive} required /></div>
                  </label>
                </>
              ) : (
                <>
                  <label className="field">
                    <span>Solo gateway <small>pearl-gateway TCP endpoint</small></span>
                    <div><Server size={16} /><input value={form.soloGateway} onChange={(event) => setForm((current) => ({ ...current, soloGateway: event.target.value }))} placeholder="127.0.0.1:8337" disabled={isActive} required /></div>
                  </label>
                  <div className={`solo-note ${soloReady ? 'solo-note--ready' : ''}`}>
                    {soloReady ? <CheckCircle2 size={16} /> : <RefreshCw className={soloNode?.installed ? 'spin' : ''} size={16} />}
                    <div className="solo-note__body">
                      <div className="solo-note__title">
                        <strong>{soloStateLabel}</strong>
                        <span>{soloNode?.syncPercent == null ? '—' : `${soloNode.syncPercent.toFixed(3)}%`}</span>
                      </div>
                      <p>{soloNode?.detail ?? 'BlockHunter can run a verified local pearld and pearl-gateway for solo mining.'}</p>
                      {soloNode?.blocks != null && (
                        <>
                          <div className="solo-progress" aria-label={`Pearl node sync ${soloNode.syncPercent ?? 0}%`}>
                            <i style={{ width: `${Math.max(0, Math.min(100, soloNode.syncPercent ?? 0))}%` }} />
                          </div>
                          <small>{soloNode.blocks.toLocaleString()} / {soloNode.networkHeight?.toLocaleString() ?? '—'} blocks · {soloNode.headers?.toLocaleString() ?? '—'} headers · {soloNode.peers} peers</small>
                        </>
                      )}
                      {!soloNode?.installed && <small>Run <code>scripts/install-pearl-solo.sh</code> once.</small>}
                    </div>
                  </div>
                </>
              )}

              <label className="field">
                <span>Worker name <small>1–32 safe characters</small></span>
                <div><Cpu size={16} /><input value={form.worker} onChange={(event) => setForm((current) => ({ ...current, worker: event.target.value }))} placeholder="blockhunter" disabled={isActive} required /></div>
              </label>

              {notice && <div className={`notice notice--${notice.tone}`}>{notice.tone === 'error' ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}<span>{notice.text}</span></div>}

              <div className="control-actions">
                {!isActive ? (
                  <button className="primary-button" type="submit" disabled={apiState !== 'online' || Boolean(action)}>
                    {action === 'start' ? <RefreshCw className="spin" size={17} /> : <Play size={17} />}
                    Start mining
                  </button>
                ) : (
                  <button className="danger-button" type="button" onClick={stop} disabled={telemetry?.state === 'stopping' || Boolean(action)}>
                    <CircleStop size={17} /> Stop miner
                  </button>
                )}
                <button className="secondary-button" type="button" onClick={probe} disabled={isActive || Boolean(action)}>
                  {action === 'probe' ? <RefreshCw className="spin" size={16} /> : <Signal size={16} />}
                  Test endpoint
                </button>
                <button className="quiet-button" type="button" onClick={shutdown} disabled={Boolean(action)} title="Stop the service and restore original GPU settings">
                  <Power size={16} /> Stop & restore
                </button>
              </div>
            </form>
          </article>

          <article className="panel guardrail-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><ShieldCheck size={13} /> Hardware envelope</span>
                <h2>{configuration?.tuningReady ? 'Guardrails armed' : 'Launch tuning required'}</h2>
              </div>
              <span className={`armed-dot ${configuration?.tuningReady ? 'armed-dot--ready' : ''}`}><i /> {configuration?.tuningReady ? 'ready' : 'not armed'}</span>
            </div>
            <div className={configuration?.tuningReady ? 'profile-orbit' : 'profile-orbit profile-orbit--idle'}>
              <div><strong>{telemetry?.powerTargetWatts ?? configuration?.powerTargetWatts ?? 150}</strong><span>watts</span></div>
              <svg viewBox="0 0 180 180" aria-hidden="true">
                <circle cx="90" cy="90" r="72" />
                <circle className="profile-orbit__active" cx="90" cy="90" r="72" />
              </svg>
            </div>
            <div className="guardrail-list">
              <div><Gauge size={17} /><span><strong>{telemetry?.coreTargetMHz ?? configuration?.coreTargetMHz ?? 2475} MHz</strong><small>locked core target</small></span><CheckCircle2 size={15} /></div>
              <div><Target size={17} /><span><strong>{telemetry?.regionSize ?? configuration?.regionSize ?? 8192} × {telemetry?.regionSize ?? configuration?.regionSize ?? 8192}</strong><small>validated work region</small></span><CheckCircle2 size={15} /></div>
              <div><Thermometer size={17} /><span><strong>{telemetry?.temperatureLimitC ?? configuration?.temperatureLimitC ?? 85} °C</strong><small>automatic cutoff</small></span><CheckCircle2 size={15} /></div>
              <div><HardDrive size={17} /><span><strong>{telemetry?.vramReserveMiB ?? configuration?.vramReserveMiB ?? 2048} MiB</strong><small>desktop reserve</small></span><CheckCircle2 size={15} /></div>
              <div><Zap size={17} /><span><strong>0 MHz offset</strong><small>stock memory clock</small></span><CheckCircle2 size={15} /></div>
            </div>
            <p className="guardrail-caption">Any temperature, power-limit, or VRAM reserve violation terminates the miner instead of chasing one more share.</p>
          </article>
        </section>

        <section className="metric-grid" aria-label="Mining metrics">
          <MetricCard icon={<Zap size={18} />} label="Hashrate" value={telemetry?.hashrateTHs?.toFixed(2) ?? '—'} unit="TH/s" detail={isRunning ? 'Production kernel output' : 'Waiting for active work'} tone="accent" />
          <MetricCard icon={<Gauge size={18} />} label="Efficiency" value={efficiency?.toFixed(3) ?? '—'} unit="TH/W" detail={efficiency ? 'Measured from live board power' : 'Requires power and hashrate'} />
          <MetricCard icon={<CheckCircle2 size={18} />} label="Accepted work" value={(telemetry?.acceptedUserShares ?? 0).toString()} detail={shareAcceptance === null ? 'No pool decisions yet' : `${shareAcceptance.toFixed(1)}% submission acceptance`} />
          <MetricCard icon={<Target size={18} />} label="Potential blocks" value={(telemetry?.blockCandidates ?? 0).toString()} detail={telemetry?.mode === 'solo' ? `${telemetry.submittedBlockProofs} proofs sent to gateway` : 'Only directly observable in solo mode'} tone={telemetry?.blockCandidates ? 'warning' : 'standard'} />
        </section>

        <section className="operations-grid">
          <PerformanceChart history={history} />
          <CandidateRadar telemetry={telemetry} />
        </section>

        <section className="detail-grid" id="hardware">
          <article className="panel hardware-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><Cpu size={13} /> Live hardware</span>
                <h2>{telemetry?.gpuName ?? 'NVIDIA RTX 4070'}</h2>
              </div>
              <span className="driver-chip">driver {telemetry?.driverVersion ?? '550+'}</span>
            </div>
            <div className="hardware-readout">
              <div><span>Board power</span><strong>{telemetry?.powerDrawWatts?.toFixed(0) ?? '—'} <small>W</small></strong></div>
              <div><span>Core clock</span><strong>{telemetry?.coreClockMHz?.toFixed(0) ?? '—'} <small>MHz</small></strong></div>
              <div><span>Temperature</span><strong>{telemetry?.temperatureC?.toFixed(0) ?? '—'} <small>°C</small></strong></div>
              <div><span>Session</span><strong>{uptime}</strong></div>
            </div>
            <div className="vital-list">
              <VitalBar label="GPU utilization" value={telemetry?.utilizationPercent ?? 0} detail={`${telemetry?.utilizationPercent?.toFixed(0) ?? '—'}%`} />
              <VitalBar label="Power envelope" value={((telemetry?.powerDrawWatts ?? 0) / (telemetry?.powerTargetWatts ?? 150)) * 100} detail={`${telemetry?.powerDrawWatts?.toFixed(0) ?? '—'} / ${telemetry?.powerTargetWatts ?? 150} W`} tone="safe" />
              <VitalBar label="Temperature envelope" value={((telemetry?.temperatureC ?? 0) / (telemetry?.temperatureLimitC ?? 85)) * 100} detail={`${telemetry?.temperatureC?.toFixed(0) ?? '—'} / ${telemetry?.temperatureLimitC ?? 85} °C`} tone={(telemetry?.temperatureC ?? 0) > 70 ? 'warm' : 'safe'} />
              <VitalBar label="VRAM allocation" value={vramTotal ? ((telemetry?.memoryUsedMiB ?? 0) / vramTotal) * 100 : 0} detail={`${telemetry?.memoryUsedMiB?.toFixed(0) ?? '—'} MiB used`} />
            </div>
          </article>

          <article className="panel trust-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><ShieldCheck size={13} /> Build provenance</span>
                <h2>Verified runtime</h2>
              </div>
              <div className="panel-heading__actions">
                <span className="verified-badge"><CheckCircle2 size={14} /> integrity pass</span>
                <button className="diagnostic-button" type="button" onClick={exportDiagnostics}><Download size={14} /> Export report</button>
              </div>
            </div>
            <div className="trust-hero">
              <span><ShieldCheck size={29} /></span>
              <div><strong>Source-pinned and checksummed</strong><p>Every installed runtime artifact is hashed before the GPU preflight can pass.</p></div>
            </div>
            <div className="provenance-list">
              <div><span>CUDA target</span><strong>{telemetry?.cudaTarget ?? 'sm_89'} only</strong></div>
              <div><span>Pearl certificate</span><strong>V{telemetry?.certificateVersion ?? 3}</strong></div>
              <div><span>Miner commit</span><code>{shortHash(telemetry?.minerCommit)}</code></div>
              <div><span>Pearl commit</span><code>{shortHash(telemetry?.pearlCommit)}</code></div>
              <div><span>CUDA artifact</span><code>{shortHash(telemetry?.artifactSha256, 16)}</code></div>
              <div><span>Developer fee</span><strong>{telemetry?.devFeePercent ?? 2}% disclosed</strong></div>
            </div>
            <div className="trust-note"><Info size={15} /><span>Integrity verification proves the installed files match the reviewed build. It does not guarantee pool uptime or future rewards.</span></div>
          </article>
        </section>

        <section className="activity-grid" id="activity">
          <article className="panel events-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><Radar size={13} /> Proof lifecycle</span>
                <h2>Candidate activity</h2>
              </div>
              <span className="event-count">{telemetry?.events.length ?? 0} events</span>
            </div>
            <div className="event-list">
              {recentEvents.length ? recentEvents.map((event) => <EventRow event={event} key={event.id} />) : (
                <div className="empty-state"><Radar size={25} /><strong>No candidates yet</strong><span>Jobs, shares, block proofs, and guardrails will appear here.</span></div>
              )}
            </div>
          </article>

          <article className="panel terminal-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"><Terminal size={13} /> Transparent output</span>
                <h2>Miner log</h2>
              </div>
              <span className="live-chip"><i /> live</span>
            </div>
            <div className="terminal-window" aria-live="polite">
              <div className="terminal-window__bar"><i /><i /><i /><span>blockhunter / pearl-miner</span></div>
              <div className="terminal-window__body">
                {(telemetry?.recentMessages ?? []).slice(-18).map((line, index) => (
                  <div key={`${index}-${line.slice(0, 20)}`}><span>{String(index + 1).padStart(2, '0')}</span><code>{line}</code></div>
                ))}
                {!telemetry?.recentMessages.length && <div><span>01</span><code>Waiting for the reviewed miner process…</code></div>}
              </div>
            </div>
          </article>
        </section>
      </main>

      <footer>
        <span><Target size={15} /> BlockHunter runs locally on 127.0.0.1</span>
        <span>Pool support: LuckyPool V3 plaintext Stratum · Solo support: pearl-gateway TCP JSON-RPC</span>
      </footer>
    </div>
  )
}

export default App
