import { sha256Json, sha256Text } from '@/lib/dsg/runtime/hash';
import type {
  AimoCandidate,
  AimoCandidateInput,
  AimoCandidateVerification,
  AimoProblemInput,
  AimoShard,
} from './types';

export const AIMO_SCHEMA_VERSION = 'dsg-aimo-v1' as const;

export function normalizeAimoProblem(problem: AimoProblemInput): AimoProblemInput {
  const statement = problem.statement
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.trimEnd())
    .join('\n')
    .trim();

  if (!statement) throw new Error('AIMO problem statement is required');

  return {
    ...(problem.problemId ? { problemId: problem.problemId.trim() } : {}),
    statement,
    ...(problem.domain ? { domain: problem.domain.trim() } : {}),
    ...(problem.constraints ? { constraints: problem.constraints } : {}),
  };
}

export function hashAimoProblem(problem: AimoProblemInput): string {
  return sha256Json({
    schemaVersion: AIMO_SCHEMA_VERSION,
    problem: normalizeAimoProblem(problem),
  });
}

export function createAimoShardPlan(
  problem: AimoProblemInput,
  shardCount: number,
): AimoShard[] {
  if (!Number.isInteger(shardCount) || shardCount < 1 || shardCount > 4096) {
    throw new Error('shardCount must be an integer from 1 to 4096');
  }

  const problemHash = hashAimoProblem(problem);

  return Array.from({ length: shardCount }, (_, index) => {
    const seed = sha256Text(
      `${AIMO_SCHEMA_VERSION}|${problemHash}|shard:${index}`,
    );
    return {
      index,
      shardId: `shard-${String(index).padStart(4, '0')}-${seed.slice(-12)}`,
      seed,
      problemHash,
      shardCount,
    };
  });
}

export function hashAimoShardPlan(shards: AimoShard[]): string {
  return sha256Json(
    shards.map(({ index, shardId, seed, problemHash, shardCount }) => ({
      index,
      shardId,
      seed,
      problemHash,
      shardCount,
    })),
  );
}

export function materializeCandidate(
  input: AimoCandidateInput,
  shard: AimoShard,
): AimoCandidate {
  const answer = input.answer.trim();
  if (!answer) throw new Error('Simulation candidate answer must not be empty');

  const canonical = {
    shardId: shard.shardId,
    solver: 'dsg-agi-simulation' as const,
    answer,
    ...(input.proof ? { proof: input.proof.trim() } : {}),
    ...(typeof input.witness !== 'undefined' ? { witness: input.witness } : {}),
    ...(typeof input.scoreHint === 'number' ? { scoreHint: input.scoreHint } : {}),
    ...(input.verification ? { verification: input.verification } : {}),
    ...(input.metadata ? { metadata: input.metadata } : {}),
  };

  const candidateHash = sha256Json(canonical);
  const provenanceHash = sha256Json({
    schemaVersion: AIMO_SCHEMA_VERSION,
    problemHash: shard.problemHash,
    shardSeed: shard.seed,
    candidateHash,
  });

  return {
    ...canonical,
    candidateId: `candidate-${candidateHash.slice(-16)}`,
    candidateHash,
    provenanceHash,
  };
}

function proofSize(candidate: AimoCandidate): number {
  return (candidate.proof ?? candidate.answer).length;
}

export function selectCanonicalVerifiedCandidate(
  items: AimoCandidateVerification[],
): AimoCandidateVerification | undefined {
  return [...items]
    .filter((item) => item.verification.verdict === 'PASS')
    .sort((a, b) => {
      const lengthDelta = proofSize(a.candidate) - proofSize(b.candidate);
      if (lengthDelta !== 0) return lengthDelta;
      return a.candidate.candidateHash.localeCompare(b.candidate.candidateHash);
    })[0];
}

export async function mapWithDeterministicIndex<T, R>(
  items: T[],
  parallelism: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (!Number.isInteger(parallelism) || parallelism < 1 || parallelism > 64) {
    throw new Error('parallelism must be an integer from 1 to 64');
  }

  const results = new Array<R>(items.length);
  let nextIndex = 0;

  async function consume(): Promise<void> {
    for (;;) {
      const index = nextIndex++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  }

  const workerCount = Math.min(parallelism, items.length);
  await Promise.all(Array.from({ length: workerCount }, () => consume()));
  return results;
}
