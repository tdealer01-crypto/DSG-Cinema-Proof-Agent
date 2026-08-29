export type AimoVerdict = 'PASS' | 'REVIEW' | 'BLOCKED';

export type AimoVerificationKind =
  | 'z3-witness'
  | 'proof-certificate'
  | 'lean-replay';

export interface AimoProblemInput {
  problemId?: string;
  statement: string;
  domain?: string;
  constraints?: Record<string, unknown>;
}

export interface AimoShard {
  index: number;
  shardId: string;
  seed: string;
  problemHash: string;
  shardCount: number;
}

export interface AimoStrategyHint {
  provider: 'nvidia-ising';
  model: string;
  text: string;
  responseHash: string;
  mode: 'live' | 'pinned';
  determinism: 'EXTERNAL_PROVIDER_NOT_GUARANTEED' | 'PINNED_REPLAY';
}

export interface AimoVerificationRequest {
  kind: AimoVerificationKind;
  endpoint: string;
  payload: unknown;
}

export interface AimoCandidateInput {
  answer: string;
  proof?: string;
  witness?: unknown;
  scoreHint?: number;
  verification?: AimoVerificationRequest;
  metadata?: Record<string, unknown>;
}

export interface AimoCandidate extends AimoCandidateInput {
  candidateId: string;
  shardId: string;
  solver: 'dsg-agi-simulation';
  candidateHash: string;
  provenanceHash: string;
}

export interface AimoVerificationResult {
  verdict: AimoVerdict;
  verifier: string;
  reason: string;
  proofHash?: string;
  evidenceHash?: string;
  certificateLevel?: string;
}

export interface AimoCandidateVerification {
  candidate: AimoCandidate;
  verification: AimoVerificationResult;
}

export interface AimoShardResult {
  shard: AimoShard;
  ok: boolean;
  status?: AimoVerdict;
  searchComplete: boolean;
  searchedAssignments?: number;
  encodingHash?: string;
  encodingProofId?: string;
  encodingProofHash?: string;
  encodingProofAuthority?: 'DSG_CONTROL_PLANE';
  candidates: AimoCandidate[];
  replayHash?: string;
  error?: string;
}

export interface AimoHarnessReceipt {
  schemaVersion: 'dsg-aimo-v1';
  runId: string;
  problemHash: string;
  shardPlanHash: string;
  shardCount: number;
  shardSuccessCount: number;
  shardCompleteCount: number;
  candidateCount: number;
  strategyHintHash?: string;
  selectedCandidate?: AimoCandidate;
  selectedVerification?: AimoVerificationResult;
  verdict: AimoVerdict;
  searchCoverage: 'COMPLETE' | 'PARTIAL' | 'NONE';
  deterministicCore: true;
  runDeterminism: 'FULL' | 'CORE_ONLY';
  externalProviderDeterminism: 'NOT_USED' | 'PINNED' | 'NOT_GUARANTEED';
  truthBoundary: string;
  nextAction?: string;
  receiptHash: string;
}
