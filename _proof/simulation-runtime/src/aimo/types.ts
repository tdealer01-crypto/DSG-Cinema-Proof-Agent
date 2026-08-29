export type AimoSearchKind = 'qubo-v1' | 'ising-v1';

export interface AimoProblemEnvelope {
  problemId?: string;
  statement: string;
  domain?: string;
  constraints?: {
    aimoEncoding?: AimoQuboEncoding | AimoIsingEncoding;
    [key: string]: unknown;
  };
}

export interface AimoTerm2 {
  i: number;
  j: number;
  weight: string | number;
}

export interface AimoLinearTerm {
  i: number;
  weight: string | number;
}

export interface AimoQuboEncoding {
  kind: 'qubo-v1';
  variableCount: number;
  constant?: string | number;
  linear?: AimoLinearTerm[];
  quadratic?: AimoTerm2[];
  objective?: 'min';
}

export interface AimoIsingEncoding {
  kind: 'ising-v1';
  variableCount: number;
  constant?: string | number;
  h?: AimoLinearTerm[];
  j?: AimoTerm2[];
  objective?: 'min';
}

export interface AimoShard {
  index: number;
  shardId: string;
  seed: string;
  problemHash: string;
  shardCount: number;
}

export interface AimoShardRequest {
  schemaVersion: 'dsg-aimo-v1';
  problem: AimoProblemEnvelope;
  problemHash: string;
  shard: AimoShard;
  maxCandidates: number;
  maxAssignments?: number;
  /**
   * Persisted Control Plane encoding proof. Public solve entrypoints resolve
   * this id from the authority before the deterministic solver is invoked.
   */
  encodingProofId?: string;
  strategyHint?: {
    provider?: string;
    model?: string;
    text?: string;
    responseHash?: string;
  } | null;
}

export interface AimoCandidate {
  answer: string;
  proof: string;
  witness: Record<string, unknown>;
  scoreHint: number;
  verification: {
    kind: 'proof-certificate';
    endpoint: '/v1/math/aimo/exact-energy-witness';
    payload: Record<string, unknown>;
  };
  metadata: Record<string, unknown>;
}

export interface AimoShardResponse {
  ok: boolean;
  status: 'PASS' | 'REVIEW' | 'BLOCKED';
  shardId: string;
  problemHash: string;
  encodingHash?: string;
  encodingProofId?: string;
  encodingProofHash?: string;
  encodingProofAuthority?: 'DSG_CONTROL_PLANE';
  /** Assignments this shard enumerated. Never more than its own partition. */
  searchedAssignments: number;
  /**
   * This shard exhausted its own partition. It says nothing about the other
   * shards, so `searchComplete` on one shard of four is not a whole-space
   * result — see `wholeSpaceSearched`.
   */
  searchComplete: boolean;
  /**
   * This single shard enumerated the entire assignment space, so its minimum is
   * the global minimum of the encoding. False whenever the work was split.
   *
   * `status: 'PASS'` means only that a shard finished its partition. Without
   * this flag a caller reading `PASS` from shard 0 of 4 would have no way to
   * tell that seven eighths of the space was never looked at.
   */
  wholeSpaceSearched: boolean;
  candidates: AimoCandidate[];
  replayHash: string;
  nextAction?: string;
  error?: string;
}
