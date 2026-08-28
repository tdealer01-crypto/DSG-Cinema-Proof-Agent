import type {
  AimoCandidate,
  AimoIsingEncoding,
  AimoProblemEnvelope,
  AimoQuboEncoding,
  AimoShardRequest,
  AimoShardResponse,
} from './types.js';
import { CANONICAL_HASH_ALGORITHM, sha256HexStable, sha256Stable } from './stable.js';

const MAX_VARIABLES = 62;
const DEFAULT_MAX_ASSIGNMENTS = 250_000;

/**
 * Exported so an independent checker recomputes energy with the same exact
 * integer arithmetic rather than a second, slightly different implementation.
 * Independence in `scripts/witness-selfcheck.ts` comes from Z3, which is handed
 * the encoding directly and never sees the enumerator's result.
 */
export function asBigInt(value: string | number | undefined, field: string): bigint {
  if (typeof value === 'undefined') return 0n;
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      throw new Error(`${field} must be a safe integer or decimal integer string`);
    }
    return BigInt(value);
  }
  if (!/^-?\d+$/.test(value)) {
    throw new Error(`${field} must be an integer string`);
  }
  return BigInt(value);
}

function validateVariableCount(variableCount: number): void {
  if (!Number.isInteger(variableCount) || variableCount < 1 || variableCount > MAX_VARIABLES) {
    throw new Error(`variableCount must be an integer from 1 to ${MAX_VARIABLES}`);
  }
}

export function bitAt(index: bigint, i: number): 0 | 1 {
  return Number((index >> BigInt(i)) & 1n) as 0 | 1;
}

export function spinAt(index: bigint, i: number): -1 | 1 {
  return bitAt(index, i) === 1 ? 1 : -1;
}

export function quboEnergy(encoding: AimoQuboEncoding, index: bigint): bigint {
  let energy = asBigInt(encoding.constant, 'constant');

  for (const term of encoding.linear ?? []) {
    if (term.i < 0 || term.i >= encoding.variableCount) {
      throw new Error(`linear term index out of range: ${term.i}`);
    }
    energy += asBigInt(term.weight, `linear[${term.i}]`) * BigInt(bitAt(index, term.i));
  }

  for (const term of encoding.quadratic ?? []) {
    if (
      term.i < 0 ||
      term.i >= encoding.variableCount ||
      term.j < 0 ||
      term.j >= encoding.variableCount
    ) {
      throw new Error(`quadratic term index out of range: ${term.i},${term.j}`);
    }
    energy +=
      asBigInt(term.weight, `quadratic[${term.i},${term.j}]`) *
      BigInt(bitAt(index, term.i) * bitAt(index, term.j));
  }

  return energy;
}

export function isingEnergy(encoding: AimoIsingEncoding, index: bigint): bigint {
  let energy = asBigInt(encoding.constant, 'constant');

  for (const term of encoding.h ?? []) {
    if (term.i < 0 || term.i >= encoding.variableCount) {
      throw new Error(`h term index out of range: ${term.i}`);
    }
    energy += asBigInt(term.weight, `h[${term.i}]`) * BigInt(spinAt(index, term.i));
  }

  for (const term of encoding.j ?? []) {
    if (
      term.i < 0 ||
      term.i >= encoding.variableCount ||
      term.j < 0 ||
      term.j >= encoding.variableCount
    ) {
      throw new Error(`j term index out of range: ${term.i},${term.j}`);
    }
    energy +=
      asBigInt(term.weight, `j[${term.i},${term.j}]`) *
      BigInt(spinAt(index, term.i) * spinAt(index, term.j));
  }

  return energy;
}

function bitsFor(index: bigint, variableCount: number): number[] {
  return Array.from({ length: variableCount }, (_, i) => bitAt(index, i));
}

function spinsFor(index: bigint, variableCount: number): number[] {
  return Array.from({ length: variableCount }, (_, i) => spinAt(index, i));
}

function scoreHintFromEnergy(energy: bigint): number {
  const capped = energy < -1_000_000_000n
    ? -1_000_000_000n
    : energy > 1_000_000_000n
      ? 1_000_000_000n
      : energy;
  return -Number(capped);
}

function candidateFor(
  problem: AimoProblemEnvelope,
  problemHash: string,
  encoding: AimoQuboEncoding | AimoIsingEncoding,
  encodingHash: string,
  assignmentIndex: bigint,
  energy: bigint,
): AimoCandidate {
  const isQubo = encoding.kind === 'qubo-v1';
  const assignment = isQubo
    ? { bits: bitsFor(assignmentIndex, encoding.variableCount) }
    : { spins: spinsFor(assignmentIndex, encoding.variableCount) };

  const witness = {
    kind: encoding.kind,
    assignmentIndex: assignmentIndex.toString(),
    variableCount: encoding.variableCount,
    energy: energy.toString(),
    ...assignment,
  };

  return {
    answer: JSON.stringify(witness),
    proof:
      `Exact ${encoding.kind} witness: assignment ${assignmentIndex.toString()} ` +
      `has integer energy ${energy.toString()}.`,
    witness,
    scoreHint: scoreHintFromEnergy(energy),
    verification: {
      kind: 'proof-certificate',
      endpoint: '/v1/math/aimo/exact-energy-witness',
      payload: {
        schemaVersion: 'dsg-aimo-exact-energy-v1',
        problemId: problem.problemId ?? null,
        problem,
        problemHash,
        encodingHash,
        encoding,
        witness,
        proveOptimality: true,
        // `problemHash` and `encodingHash` above are this repository's internal
        // content hashes: `sha256:`-prefixed, and produced by `JSON.stringify`,
        // which leaves non-ASCII characters unescaped. A verifier written in
        // another language cannot reproduce them from a spec alone.
        //
        // `interop` carries the same two hashes in the cross-repository
        // encoding — bare hex over ASCII-escaped canonical JSON — which is what
        // an independent verifier recomputes and checks. See
        // contracts/CANONICAL_HASH.md.
        interop: {
          hashAlgorithm: CANONICAL_HASH_ALGORITHM,
          problemHash: sha256HexStable({ schemaVersion: 'dsg-aimo-v1', problem }),
          encodingHash: sha256HexStable(encoding),
        },
      },
    },
    metadata: {
      search: 'deterministic-exact-sharded-enumeration',
      objective: 'min',
      assignmentIndex: assignmentIndex.toString(),
    },
  };
}

/**
 * What the caller still has to do before the result means anything global.
 *
 * A shard that finished its own partition is done, but it has still only seen
 * `1/shardCount` of the space. Saying nothing there would let `PASS` read as an
 * exhaustive result.
 */
function nextActionFor(
  searchComplete: boolean,
  wholeSpaceSearched: boolean,
  shardCount: number,
): { nextAction?: string } {
  if (!searchComplete) {
    return {
      nextAction:
        'Continue the same deterministic shard with a larger maxAssignments or use more shards. Do not claim exhaustive optimum yet.',
    };
  }
  if (!wholeSpaceSearched) {
    return {
      nextAction:
        `This shard exhausted its own partition only. Combine all ${shardCount} shards and take the minimum across them before claiming a global optimum.`,
    };
  }
  return {};
}

function validateShard(request: AimoShardRequest): void {
  const shard = request.shard;
  if (!Number.isInteger(shard.index) || shard.index < 0) throw new Error('invalid shard.index');
  if (!Number.isInteger(shard.shardCount) || shard.shardCount < 1) {
    throw new Error('invalid shard.shardCount');
  }
  if (shard.index >= shard.shardCount) throw new Error('shard.index must be < shard.shardCount');
  if (shard.problemHash !== request.problemHash) throw new Error('shard problemHash mismatch');
  if (!Number.isInteger(request.maxCandidates) || request.maxCandidates < 1 || request.maxCandidates > 64) {
    throw new Error('maxCandidates must be an integer from 1 to 64');
  }
}

export function solveAimoShard(request: AimoShardRequest): AimoShardResponse {
  try {
    validateShard(request);

    const actualProblemHash = sha256Stable({
      schemaVersion: 'dsg-aimo-v1',
      problem: request.problem,
    });
    if (actualProblemHash !== request.problemHash) {
      return {
        ok: false,
        status: 'BLOCKED',
        shardId: request.shard.shardId,
        problemHash: request.problemHash,
        searchedAssignments: 0,
        searchComplete: false,
        wholeSpaceSearched: false,
        candidates: [],
        replayHash: sha256Stable({ reason: 'problem hash mismatch', request }),
        error: 'problemHash does not match canonical problem',
      };
    }

    const encoding = request.problem.constraints?.aimoEncoding;
    if (!encoding || (encoding.kind !== 'qubo-v1' && encoding.kind !== 'ising-v1')) {
      return {
        ok: true,
        status: 'REVIEW',
        shardId: request.shard.shardId,
        problemHash: request.problemHash,
        searchedAssignments: 0,
        searchComplete: false,
        wholeSpaceSearched: false,
        candidates: [],
        replayHash: sha256Stable({
          schemaVersion: 'dsg-aimo-shard-response-v1',
          shardId: request.shard.shardId,
          problemHash: request.problemHash,
          status: 'REVIEW',
          reason: 'formal encoding required',
        }),
        nextAction:
          'Provide constraints.aimoEncoding as qubo-v1 or ising-v1. Natural-language strategy hints are advisory and are not executed as code.',
      };
    }

    validateVariableCount(encoding.variableCount);

    const totalAssignments = 1n << BigInt(encoding.variableCount);
    const stride = BigInt(request.shard.shardCount);
    let index = BigInt(request.shard.index);
    const requestedLimit = request.maxAssignments ?? DEFAULT_MAX_ASSIGNMENTS;
    if (!Number.isInteger(requestedLimit) || requestedLimit < 1 || requestedLimit > 5_000_000) {
      throw new Error('maxAssignments must be an integer from 1 to 5,000,000');
    }

    const encodingHash = sha256Stable(encoding);
    const ranked: Array<{ index: bigint; energy: bigint }> = [];
    let searchedAssignments = 0;

    while (index < totalAssignments && searchedAssignments < requestedLimit) {
      const energy =
        encoding.kind === 'qubo-v1'
          ? quboEnergy(encoding, index)
          : isingEnergy(encoding, index);

      ranked.push({ index, energy });
      searchedAssignments++;
      index += stride;
    }

    ranked.sort((a, b) => {
      if (a.energy < b.energy) return -1;
      if (a.energy > b.energy) return 1;
      if (a.index < b.index) return -1;
      if (a.index > b.index) return 1;
      return 0;
    });

    const winners = ranked.slice(0, request.maxCandidates);
    const candidates = winners.map(({ index: assignmentIndex, energy }) =>
      candidateFor(
        request.problem,
        request.problemHash,
        encoding,
        encodingHash,
        assignmentIndex,
        energy,
      ),
    );

    const searchComplete = index >= totalAssignments;
    const wholeSpaceSearched = searchComplete && request.shard.shardCount === 1;
    const status = candidates.length > 0 ? (searchComplete ? 'PASS' : 'REVIEW') : 'BLOCKED';

    const responseWithoutReplay = {
      schemaVersion: 'dsg-aimo-shard-response-v1',
      status,
      shardId: request.shard.shardId,
      problemHash: request.problemHash,
      encodingHash,
      searchedAssignments,
      searchComplete,
      wholeSpaceSearched,
      candidateWitnesses: candidates.map((candidate) => candidate.witness),
    };

    return {
      ok: true,
      status,
      shardId: request.shard.shardId,
      problemHash: request.problemHash,
      encodingHash,
      searchedAssignments,
      searchComplete,
      wholeSpaceSearched,
      candidates,
      replayHash: sha256Stable(responseWithoutReplay),
      ...nextActionFor(searchComplete, wholeSpaceSearched, request.shard.shardCount),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      status: 'BLOCKED',
      shardId: request.shard?.shardId ?? 'unknown',
      problemHash: request.problemHash ?? 'unknown',
      searchedAssignments: 0,
      searchComplete: false,
      wholeSpaceSearched: false,
      candidates: [],
      replayHash: sha256Stable({ error: message, request }),
      error: message,
    };
  }
}
