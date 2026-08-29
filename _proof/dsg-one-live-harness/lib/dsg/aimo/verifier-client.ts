import { sha256Json } from '@/lib/dsg/runtime/hash';
import { getAimoServiceConfig } from './service-registry';
import type {
  AimoCandidate,
  AimoVerificationRequest,
  AimoVerificationResult,
} from './types';

const ALLOWED_ENDPOINT_PREFIXES = [
  '/v1/verify',
  '/v1/hybrid/',
  '/v1/math/',
];

function verifierUrl(endpoint: string): URL {
  if (!endpoint.startsWith('/')) {
    throw new Error('verification endpoint must be a relative /v1/... path');
  }
  if (!ALLOWED_ENDPOINT_PREFIXES.some((prefix) => endpoint.startsWith(prefix))) {
    throw new Error(`verification endpoint is not allowlisted: ${endpoint}`);
  }

  const base = getAimoServiceConfig().cinemaUrl;
  if (!base) {
    throw new Error(
      'AIMO Cinema URL is not configured. Set DSG_AIMO_SERVICE_REGISTRY or legacy DSG_CINEMA_PROOF_URL.',
    );
  }

  const url = new URL(endpoint, base);
  const baseUrl = new URL(base);
  if (url.origin !== baseUrl.origin) {
    throw new Error('verification endpoint escaped the configured verifier origin');
  }
  if (process.env.NODE_ENV === 'production' && url.protocol !== 'https:') {
    throw new Error('AIMO Cinema URL must use HTTPS in production');
  }
  return url;
}

function interpretVerification(
  request: AimoVerificationRequest,
  body: Record<string, unknown>,
): AimoVerificationResult {
  const evidenceHash = sha256Json(body);

  if (request.kind === 'z3-witness') {
    const passed =
      body.accepted === true &&
      body.z3_status === 'SAT' &&
      body.all_constraints_satisfied === true;

    return {
      verdict: passed ? 'PASS' : 'BLOCKED',
      verifier: 'DSG Cinema Proof Agent / Z3 witness gate',
      reason: passed
        ? 'Structured witness satisfies the encoded Z3 constraints.'
        : 'Z3 witness gate did not return accepted SAT with all constraints satisfied.',
      proofHash:
        typeof body.proof_hash === 'string' ? body.proof_hash : undefined,
      evidenceHash,
    };
  }

  if (request.kind === 'proof-certificate') {
    const passed =
      body.verdict === 'PASS' &&
      body.proof_complete === true;

    return {
      verdict: passed ? 'PASS' : 'BLOCKED',
      verifier: 'DSG proof-certificate gate',
      reason: passed
        ? 'Remote verifier returned PASS with proof_complete=true.'
        : 'Proof certificate is incomplete or did not PASS.',
      proofHash:
        typeof body.proof_hash === 'string' ? body.proof_hash : undefined,
      evidenceHash,
      certificateLevel:
        typeof body.certificate_level === 'string'
          ? body.certificate_level
          : undefined,
    };
  }

  const passed =
    body.reproducible_formal_proof === 'PASS' &&
    body.sorryAx === false;

  return {
    verdict: passed ? 'PASS' : 'BLOCKED',
    verifier: 'Lean replay gate',
    reason: passed
      ? 'Formal replay returned PASS and no sorryAx.'
      : 'Lean replay evidence did not meet the fail-closed contract.',
    proofHash:
      typeof body.proof_hash === 'string' ? body.proof_hash : undefined,
    evidenceHash,
  };
}

export async function verifyAimoCandidate(
  candidate: AimoCandidate,
): Promise<AimoVerificationResult> {
  const request = candidate.verification;
  if (!request) {
    return {
      verdict: 'BLOCKED',
      verifier: 'none',
      reason:
        'Candidate has no structured verification request. Proof text alone is never authoritative.',
    };
  }

  try {
    const config = getAimoServiceConfig();
    const url = verifierUrl(request.endpoint);
    const apiKey = config.cinemaApiKey;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(apiKey ? { 'X-API-Key': apiKey } : {}),
      },
      body: JSON.stringify(request.payload),
      signal: AbortSignal.timeout(120_000),
    });

    if (!response.ok) {
      return {
        verdict: 'BLOCKED',
        verifier: 'DSG Cinema Proof Agent',
        reason: `Verifier returned HTTP ${response.status}.`,
      };
    }

    const body = (await response.json()) as Record<string, unknown>;
    return interpretVerification(request, body);
  } catch (error) {
    return {
      verdict: 'BLOCKED',
      verifier: 'DSG Cinema Proof Agent',
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}
