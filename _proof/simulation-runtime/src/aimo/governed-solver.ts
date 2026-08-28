import { sha256Stable } from './stable.js';
import { solveAimoShard } from './solver.js';
import {
  verifyEncodingProofAuthority,
  type EncodingProofAuthorityDeps,
} from './encoding-proof-authority.js';
import type { AimoShardRequest, AimoShardResponse } from './types.js';

function blocked(
  request: AimoShardRequest,
  error: string,
): AimoShardResponse {
  return {
    ok: false,
    status: 'BLOCKED',
    shardId: request.shard?.shardId ?? 'unknown',
    problemHash: request.problemHash ?? 'unknown',
    searchedAssignments: 0,
    searchComplete: false,
    wholeSpaceSearched: false,
    candidates: [],
    replayHash: sha256Stable({
      schemaVersion: 'dsg-aimo-authority-block-v1',
      problemHash: request.problemHash ?? null,
      shardId: request.shard?.shardId ?? null,
      encodingProofId: request.encodingProofId ?? null,
      error,
    }),
    error,
  };
}

/**
 * Public execution boundary for the exact shard solver.
 *
 * `solveAimoShard` remains a pure deterministic function for golden vectors,
 * property tests and independent verification. Network-facing entrypoints must
 * call this wrapper so no assignment is enumerated until the supplied proof id
 * has been resolved from the authenticated Control Plane authority and bound to
 * the exact problem and structural encoding.
 */
export async function solveGovernedAimoShard(
  request: AimoShardRequest,
  deps: EncodingProofAuthorityDeps = {},
): Promise<AimoShardResponse> {
  const authority = await verifyEncodingProofAuthority(request, deps);
  if (!authority.ok) return blocked(request, `encoding proof blocked: ${authority.error}`);

  const result = solveAimoShard(request);
  const proof = authority.proof;
  const candidates = result.candidates.map((candidate) => ({
    ...candidate,
    metadata: {
      ...candidate.metadata,
      encodingProofId: proof.proofId,
      encodingProofHash: proof.proofHash,
      encodingProofAuthority: proof.authority,
    },
  }));

  return {
    ...result,
    candidates,
    encodingProofId: proof.proofId,
    encodingProofHash: proof.proofHash,
    encodingProofAuthority: proof.authority,
    replayHash: sha256Stable({
      schemaVersion: 'dsg-aimo-governed-shard-response-v1',
      solverReplayHash: result.replayHash,
      encodingProofId: proof.proofId,
      encodingProofHash: proof.proofHash,
      encodingAuthorityHash: proof.encodingHash,
      authority: proof.authority,
    }),
  };
}
