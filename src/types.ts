export type Network = 'Ethereum' | 'Base' | 'Arbitrum'

export type RiskLevel = 'Critical' | 'High' | 'Medium' | 'Low'

export type Entity = {
  id: string
  address: string
  label: string
  category: string
  network: Network
  riskScore: number
  balance: string
  firstSeen: string
  lastSeen: string
  transactions: number
  inflow: string
  outflow: string
  flags: string[]
}

export type Activity = {
  id: string
  hash: string
  from: string
  to: string
  value: string
  fiatValue: string
  asset: string
  network: Network
  risk: RiskLevel
  time: string
  direction: 'In' | 'Out'
}

export type Investigation = {
  id: string
  title: string
  subject: string
  priority: RiskLevel
  status: 'Open' | 'Review' | 'Monitoring'
  updated: string
  signals: number
}

export type MinerTelemetry = {
  state: string
  startedAt: string | null
  updatedAt: string
  worker: string
  mode: MiningMode | 'benchmark'
  pool: string | null
  soloGateway: string | null
  endpoint: string | null
  connectionState: string
  gpuName: string
  driverVersion: string
  cudaTarget: string
  regionSize: number
  certificateVersion: number
  devFeePercent: number
  acceptedShares: number
  acceptedUserShares: number
  acceptedDevShares: number
  rejectedShares: number
  proofCandidates: number
  blockCandidates: number
  submittedBlockProofs: number
  proofErrors: number
  jobsReceived: number
  staleJobs: number
  hashrateTHs: number | null
  targetExponent: number | null
  boundExponent: number | null
  poolDifficulty: string | null
  currentJob?: string | null
  workMode?: string
  endpointLatencyMs?: number
  temperatureC?: number
  powerDrawWatts?: number
  powerLimitWatts?: number
  powerTargetWatts: number
  coreClockMHz?: number
  coreTargetMHz: number
  utilizationPercent?: number
  memoryUsedMiB?: number
  memoryFreeMiB?: number
  vramReserveMiB: number
  temperatureLimitC: number
  verifiedBuild: boolean
  artifactSha256: string
  minerCommit: string
  pearlCommit: string
  profileName: string
  events: MinerEvent[]
  recentMessages: string[]
  lastMessage?: string
  stopReason?: string
  soloNode: SoloNodeTelemetry | null
}

export type SoloNodeTelemetry = {
  installed: boolean
  state: string
  detail: string
  nodeService: string
  gatewayService: string
  nodeRpcReady: boolean
  gatewayReady: boolean
  blocks: number | null
  headers: number | null
  networkHeight: number | null
  syncPercent: number | null
  initialBlockDownload: boolean | null
  peers: number
  updatedAt: string
}

export type MiningMode = 'pool' | 'solo'

export type MinerEvent = {
  id: number
  timestamp: string
  kind: 'job' | 'share' | 'block' | 'warning' | 'guardrail' | 'network' | 'system'
  title: string
  detail: string
  severity: 'info' | 'candidate' | 'success' | 'warning' | 'error'
}

export type MinerConfiguration = {
  mode: MiningMode
  wallet: string
  worker: string
  pool: string
  soloGateway: string
  poolProtocol: string
  soloProtocol: string
  tuningReady: boolean
  powerTargetWatts: number
  coreTargetMHz: number
  temperatureLimitC: number
  vramReserveMiB: number
  regionSize: number
  devFeePercent: number
}

export type MinerForm = Pick<
  MinerConfiguration,
  'mode' | 'wallet' | 'worker' | 'pool' | 'soloGateway'
>
