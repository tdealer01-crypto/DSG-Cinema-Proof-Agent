import { createHash } from 'node:crypto';
import { stableStringify } from './stable.js';
import type {
  AimoIsingEncoding,
  AimoQuboEncoding,
  AimoShardRequest,
} from './types.js';

const PROOF_ID = /^epf_[0-9a-f]{32}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;
const LOOKUP_TIMEOUT_MS = 5_000;

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

export interface VerifiedEncodingProofAuthority {
  proofId: string;
  proofHash: string;
  encodingHash: string;
  problemId: string;
  encodingType: 'qubo-v1' | 'ising-v1';
  authority: 'DSG_CONTROL_PLANE';
}

export type EncodingProofAuthorityResult =
  | { ok: true; proof: VerifiedEncodingProofAuthority }
  | { ok: false; error: string };

export interface EncodingProofAuthorityDeps {
  env?: NodeJS.ProcessEnv;
  fetchImpl?: typeof fetch;
}

type ProofLookupBody = {
  ok?: unknown;
  status?: unknown;
  proofId?: unknown;
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
};

/**
 * The simulation repository historically names linear indices `i`, while the
 * Control Plane encoding-proof contract names them `index`. Convert explicitly
 * before hashing so proof binding is semantic and not an accidental schema
 * mismatch.
 */
export function toControlPlaneEncoding(
  encoding: AimoQuboEncoding | AimoIsingEncoding,
): ControlPlaneEncoding {
  if (encoding.kind === 'qubo-v1') {
    return {
      kind: encoding.kind,
      variableCount: encoding.variableCount,
      ...(typeof encoding.constant !== 'undefined' ? { constant: encoding.constant } : {}),
      ...(encoding.linear
        ? { linear: encoding.linear.map((term) => ({ index: term.i, weight: term.weight })) }
        : {}),
      ...(encoding.quadratic
        ? {
            quadratic: encoding.quadratic.map((term) => ({
              i: term.i,
              j: term.j,
              weight: term.weight,
            })),
          }
        : {}),
      ...(encoding.objective ? { objective: encoding.objective } : {}),
    };
  }

  return {
    kind: encoding.kind,
    variableCount: encoding.variableCount,
    ...(typeof encoding.constant !== 'undefined' ? { constant: encoding.constant } : {}),
    ...(encoding.h
      ? { h: encoding.h.map((term) => ({ index: term.i, weight: term.weight })) }
      : {}),
    ...(encoding.j
      ? {
          j: encoding.j.map((term) => ({
            i: term.i,
            j: term.j,
            weight: term.weight,
          })),
        }
      : {}),
    ...(encoding.objective ? { objective: encoding.objective } : {}),
  };
}

/** Exact hash form used by Control Plane `canonicalHash`: sorted JSON, bare hex. */
export function controlPlaneEncodingHash(
  encoding: AimoQuboEncoding | AimoIsingEncoding,
): string {
  return createHash('sha256')
    .update(stableStringify(toControlPlaneEncoding(encoding)), 'utf8')
    .digest('hex');
}

/**
 * Control Plane requires a non-empty problemId. For callers that do not carry
 * one, derive a deterministic id from the already-canonical problem hash.
 */
export function encodingProofProblemId(request: AimoShardRequest): string {
  const explicit = request.problem.problemId?.trim();
  if (explicit) return explicit;
  return `aimo-${request.problemHash.replace(/^sha256:/, '')}`;
}

function lookupConfig(
  proofId: string,
  env: NodeJS.ProcessEnv,
): { ok: true; url: URL; apiKey: string } | { ok: false; error: string } {
  if (!PROOF_ID.test(proofId)) {
    return { ok: false, error: 'encoding proof id is missing or malformed' };
  }

  const rawBase = env.DSG_CONTROL_PLANE_URL?.trim();
  const apiKey = env.DSG_CONTROL_PLANE_API_KEY?.trim();
  if (!rawBase || !apiKey) {
    return {
      ok: false,
      error: 'Control Plane encoding-proof authority is not configured',
    };
  }

  let base: URL;
  try {
    base = new URL(rawBase);
  } catch {
    return { ok: false, error: 'DSG_CONTROL_PLANE_URL is invalid' };
  }

  if (base.protocol !== 'http:' && base.protocol !== 'https:') {
    return { ok: false, error: 'DSG_CONTROL_PLANE_URL must use HTTP or HTTPS' };
  }
  if (env.NODE_ENV === 'production' && base.protocol !== 'https:') {
    return { ok: false, error: 'DSG_CONTROL_PLANE_URL must use HTTPS in production' };
  }

  return {
    ok: true,
    url: new URL(`/api/dsg/v1/encoding/proofs/${proofId}`, base),
    apiKey,
  };
}

export async function verifyEncodingProofAuthority(
  request: AimoShardRequest,
  deps: EncodingProofAuthorityDeps = {},
): Promise<EncodingProofAuthorityResult> {
  const proofId = request.encodingProofId?.trim() ?? '';
  const encoding = request.problem.constraints?.aimoEncoding;
  if (!encoding || (encoding.kind !== 'qubo-v1' && encoding.kind !== 'ising-v1')) {
    return { ok: false, error: 'formal QUBO/Ising encoding is required before proof lookup' };
  }

  const env = deps.env ?? process.env;
  const config = lookupConfig(proofId, env);
  if (!config.ok) return config;

  const fetchImpl = deps.fetchImpl ?? fetch;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), LOOKUP_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetchImpl(config.url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${config.apiKey}`,
      },
      signal: controller.signal,
    });
  } catch {
    return { ok: false, error: 'Control Plane encoding-proof lookup failed' };
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    return {
      ok: false,
      error: `Control Plane encoding-proof lookup returned HTTP ${response.status}`,
    };
  }

  let body: ProofLookupBody;
  try {
    body = (await response.json()) as ProofLookupBody;
  } catch {
    return { ok: false, error: 'Control Plane encoding-proof response is not valid JSON' };
  }

  const proof = body.proof;
  const expectedProblemId = encodingProofProblemId(request);
  const expectedEncodingHash = controlPlaneEncodingHash(encoding);

  if (
    body.ok !== true ||
    body.status !== 'PASS' ||
    body.proofId !== proofId ||
    !proof ||
    proof.proofId !== proofId ||
    proof.status !== 'PASS'
  ) {
    return { ok: false, error: 'Control Plane did not return an authoritative PASS proof' };
  }

  if (typeof proof.proofHash !== 'string' || !SHA256_HEX.test(proof.proofHash)) {
    return { ok: false, error: 'Control Plane proof hash is missing or malformed' };
  }
  if (proof.encodingHash !== expectedEncodingHash) {
    return { ok: false, error: 'encoding proof does not match the encoding being solved' };
  }
  if (proof.subject?.problemId !== expectedProblemId) {
    return { ok: false, error: 'encoding proof does not match the problem being solved' };
  }
  if (proof.subject?.encodingType !== encoding.kind) {
    return { ok: false, error: 'encoding proof type does not match the encoding being solved' };
  }

  return {
    ok: true,
    proof: {
      proofId,
      proofHash: proof.proofHash,
      encodingHash: expectedEncodingHash,
      problemId: expectedProblemId,
      encodingType: encoding.kind,
      authority: 'DSG_CONTROL_PLANE',
    },
  };
}
