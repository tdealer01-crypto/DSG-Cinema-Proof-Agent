import { createHash } from 'node:crypto';
import { sha256Json } from '@/lib/dsg/runtime/hash';
import { stableJsonStringify } from '@/lib/dsg/runtime/stable-json';
import type { AimoProblemInput } from '@/lib/dsg/aimo/types';

export type SimulationEncoding =
  | {
      kind: 'qubo-v1';
      variableCount: number;
      constant?: string | number;
      linear?: Array<{ i: number; weight: string | number }>;
      quadratic?: Array<{ i: number; j: number; weight: string | number }>;
      objective?: 'min';
    }
  | {
      kind: 'ising-v1';
      variableCount: number;
      constant?: string | number;
      h?: Array<{ i: number; weight: string | number }>;
      j?: Array<{ i: number; j: number; weight: string | number }>;
      objective?: 'min';
    };

export type ControlPlaneEncoding =
  | {
      kind: 'qubo-v1';
      variableCount: number;
      constant?: string | number;
      linear?: Array<{ index: number; weight: string | number }>;
      quadratic?: Array<{ i: number; j: number; weight: string | number }>;
      objective?: 'min';
    }
  | {
      kind: 'ising-v1';
      variableCount: number;
      constant?: string | number;
      h?: Array<{ index: number; weight: string | number }>;
      j?: Array<{ i: number; j: number; weight: string | number }>;
      objective?: 'min';
    };

export interface EncodingProofBinding {
  proofId: string;
  proofHash: string;
  encodingHash: string;
  problemId: string;
  encodingType: 'qubo-v1' | 'ising-v1';
}

export interface EncodingProofClientConfig {
  controlPlaneUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
}

interface EncodingProofResponse {
  ok?: unknown;
  proofId?: unknown;
  status?: unknown;
  proof?: {
    proofId?: unknown;
    proofHash?: unknown;
    encodingHash?: unknown;
    status?: unknown;
    subject?: {
      problemId?: unknown;
      encodingType?: unknown;
    };
  };
}

const PROOF_ID = /^epf_[0-9a-f]{32}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isCoefficient(value: unknown): value is string | number {
  return (
    (typeof value === 'number' && Number.isFinite(value)) ||
    (typeof value === 'string' && value.length > 0)
  );
}

function readLinearTerms(value: unknown): Array<{ i: number; weight: string | number }> | undefined {
  if (typeof value === 'undefined') return undefined;
  if (!Array.isArray(value)) throw new Error('encoding linear terms must be an array');
  return value.map((item) => {
    if (!isRecord(item) || !Number.isInteger(item.i) || !isCoefficient(item.weight)) {
      throw new Error('encoding linear term must contain integer i and finite weight');
    }
    return { i: Number(item.i), weight: item.weight };
  });
}

function readQuadraticTerms(value: unknown): Array<{ i: number; j: number; weight: string | number }> | undefined {
  if (typeof value === 'undefined') return undefined;
  if (!Array.isArray(value)) throw new Error('encoding quadratic terms must be an array');
  return value.map((item) => {
    if (
      !isRecord(item) ||
      !Number.isInteger(item.i) ||
      !Number.isInteger(item.j) ||
      !isCoefficient(item.weight)
    ) {
      throw new Error('encoding quadratic term must contain integer i/j and finite weight');
    }
    return { i: Number(item.i), j: Number(item.j), weight: item.weight };
  });
}

export function readSimulationEncoding(value: unknown): SimulationEncoding {
  if (!isRecord(value)) throw new Error('normalized problem has no aimoEncoding object');
  const kind = value.kind;
  const variableCount = value.variableCount;
  if (
    (kind !== 'qubo-v1' && kind !== 'ising-v1') ||
    !Number.isInteger(variableCount) ||
    Number(variableCount) < 1
  ) {
    throw new Error('aimoEncoding must be qubo-v1/ising-v1 with a positive variableCount');
  }
  if (value.constant !== undefined && !isCoefficient(value.constant)) {
    throw new Error('aimoEncoding constant must be finite');
  }
  if (value.objective !== undefined && value.objective !== 'min') {
    throw new Error('aimoEncoding objective must be min when provided');
  }

  if (kind === 'qubo-v1') {
    if (value.h !== undefined || value.j !== undefined) {
      throw new Error('QUBO encoding must not contain Ising fields');
    }
    const linear = readLinearTerms(value.linear);
    const quadratic = readQuadraticTerms(value.quadratic);
    return {
      kind,
      variableCount: Number(variableCount),
      ...(value.constant !== undefined ? { constant: value.constant as string | number } : {}),
      ...(linear ? { linear } : {}),
      ...(quadratic ? { quadratic } : {}),
      ...(value.objective === 'min' ? { objective: 'min' as const } : {}),
    };
  }

  if (value.linear !== undefined || value.quadratic !== undefined) {
    throw new Error('Ising encoding must not contain QUBO fields');
  }
  const h = readLinearTerms(value.h);
  const j = readQuadraticTerms(value.j);
  return {
    kind,
    variableCount: Number(variableCount),
    ...(value.constant !== undefined ? { constant: value.constant as string | number } : {}),
    ...(h ? { h } : {}),
    ...(j ? { j } : {}),
    ...(value.objective === 'min' ? { objective: 'min' as const } : {}),
  };
}

/** Convert simulation `{ i }` linear terms to the Control Plane `{ index }` schema. */
export function toControlPlaneEncoding(encoding: SimulationEncoding): ControlPlaneEncoding {
  if (encoding.kind === 'qubo-v1') {
    return {
      kind: encoding.kind,
      variableCount: encoding.variableCount,
      ...(encoding.constant !== undefined ? { constant: encoding.constant } : {}),
      ...(encoding.linear
        ? { linear: encoding.linear.map((term) => ({ index: term.i, weight: term.weight })) }
        : {}),
      ...(encoding.quadratic
        ? { quadratic: encoding.quadratic.map((term) => ({ ...term })) }
        : {}),
      ...(encoding.objective ? { objective: encoding.objective } : {}),
    };
  }

  return {
    kind: encoding.kind,
    variableCount: encoding.variableCount,
    ...(encoding.constant !== undefined ? { constant: encoding.constant } : {}),
    ...(encoding.h
      ? { h: encoding.h.map((term) => ({ index: term.i, weight: term.weight })) }
      : {}),
    ...(encoding.j ? { j: encoding.j.map((term) => ({ ...term })) } : {}),
    ...(encoding.objective ? { objective: encoding.objective } : {}),
  };
}

export function controlPlaneEncodingHash(encoding: ControlPlaneEncoding): string {
  return createHash('sha256')
    .update(stableJsonStringify(encoding), 'utf8')
    .digest('hex');
}

export function encodingProofProblemId(
  problem: AimoProblemInput,
  problemHash: string,
): string {
  const explicit = problem.problemId?.trim();
  return explicit || `aimo-${problemHash.replace(/^sha256:/, '')}`;
}

function endpoint(config: EncodingProofClientConfig): { url: URL; apiKey: string } {
  const rawUrl = config.controlPlaneUrl?.trim();
  const apiKey = config.apiKey?.trim();
  if (!rawUrl || !apiKey) {
    throw new Error('Control Plane encoding-proof URL/API key is not configured');
  }

  const base = new URL(rawUrl);
  if (base.protocol !== 'http:' && base.protocol !== 'https:') {
    throw new Error('Control Plane encoding-proof URL must use HTTP or HTTPS');
  }
  if (process.env.NODE_ENV === 'production' && base.protocol !== 'https:') {
    throw new Error('Control Plane encoding-proof URL must use HTTPS in production');
  }
  return { url: new URL('/api/dsg/v1/encoding/prove', base), apiKey };
}

/**
 * Issue or idempotently replay a persisted structural encoding proof.
 *
 * No client-side proof cache is used: Control Plane owns idempotency/replay and
 * the proof is request-bound. Caching by encoding alone would incorrectly reuse
 * a proof across different problem/request identities.
 */
export async function requestEncodingProofForShard(input: {
  problem: AimoProblemInput;
  problemHash: string;
  shardId: string;
  config: EncodingProofClientConfig;
}): Promise<EncodingProofBinding> {
  const rawEncoding = input.problem.constraints?.aimoEncoding;
  const simulationEncoding = readSimulationEncoding(rawEncoding);
  const encoding = toControlPlaneEncoding(simulationEncoding);
  const problemId = encodingProofProblemId(input.problem, input.problemHash);
  const encodingHash = controlPlaneEncodingHash(encoding);
  const requestIdentity = {
    schemaVersion: 'dsg-aimo-encoding-proof-request-v1',
    problemHash: input.problemHash,
    shardId: input.shardId,
    encoding,
  };
  const nonce = sha256Json({ scope: 'encoding-proof-nonce', ...requestIdentity });
  const idempotencyKey = sha256Json({ scope: 'encoding-proof-idempotency', ...requestIdentity });
  const target = endpoint(input.config);

  const response = await fetch(target.url, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Authorization: `Bearer ${target.apiKey}`,
    },
    body: JSON.stringify({
      problemId,
      encodingType: encoding.kind,
      encoding,
      nonce,
      idempotencyKey,
    }),
    signal: AbortSignal.timeout(input.config.timeoutMs ?? 8_000),
  });

  if (!response.ok) {
    throw new Error(`Control Plane encoding proof returned HTTP ${response.status}`);
  }

  const body = (await response.json()) as EncodingProofResponse;
  const proof = body.proof;
  if (
    body.ok !== true ||
    body.status !== 'PASS' ||
    typeof body.proofId !== 'string' ||
    !PROOF_ID.test(body.proofId) ||
    !proof ||
    proof.proofId !== body.proofId ||
    proof.status !== 'PASS'
  ) {
    throw new Error('Control Plane did not issue an authoritative PASS encoding proof');
  }
  if (typeof proof.proofHash !== 'string' || !SHA256_HEX.test(proof.proofHash)) {
    throw new Error('Control Plane encoding proof hash is missing or malformed');
  }
  if (proof.encodingHash !== encodingHash) {
    throw new Error('Control Plane encoding proof hash does not match submitted encoding');
  }
  if (proof.subject?.problemId !== problemId || proof.subject?.encodingType !== encoding.kind) {
    throw new Error('Control Plane encoding proof subject does not match submitted problem');
  }

  return {
    proofId: body.proofId,
    proofHash: proof.proofHash,
    encodingHash,
    problemId,
    encodingType: encoding.kind,
  };
}
