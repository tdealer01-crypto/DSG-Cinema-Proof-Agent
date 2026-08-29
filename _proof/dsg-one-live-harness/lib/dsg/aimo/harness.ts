import { sha256Json } from '@/lib/dsg/runtime/hash';
import {
  createAimoShardPlan,
  hashAimoProblem,
  hashAimoShardPlan,
  mapWithDeterministicIndex,
  normalizeAimoProblem,
  selectCanonicalVerifiedCandidate,
} from './deterministic';
import {
  getNvidiaIsingStrategy,
  type NvidiaIsingStrategyConfig,
} from './nvidia-ising';
import { getAimoServiceConfig } from './service-registry';
import { solveSimulationShard } from './simulation-client';
import { verifyAimoCandidate } from './verifier-client';
import type {
  AimoCandidate,
  AimoCandidateVerification,
  AimoHarnessReceipt,
  AimoProblemInput,
  AimoShardResult,
  AimoStrategyHint,
  AimoVerificationResult,
} from './types';

export interface AimoHarnessDependencies {
  getStrategy?: (
    problem: AimoProblemInput,
    config: NvidiaIsingStrategyConfig,
  ) => Promise<AimoStrategyHint | undefined>;
  solveShard?: typeof solveSimulationShard;
  verifyCandidate?: (candidate: AimoCandidate) => Promise<AimoVerificationResult>;
}

export interface RunAimoHarnessInput {
  problem: AimoProblemInput;
  shardCount?: number;
  parallelism?: number;
  maxCandidatesPerShard?: number;
  nvidiaIsing?: NvidiaIsingStrategyConfig;
  requireAllShards?: boolean;
}

function getMaxParallelism(): number {
  return getAimoServiceConfig().maxParallelism;
}

export async function runAimoHarness(
  input: RunAimoHarnessInput,
  dependencies: AimoHarnessDependencies = {},
): Promise<AimoHarnessReceipt> {
  const problem = normalizeAimoProblem(input.problem);
  const problemHash = hashAimoProblem(problem);
  const shardCount = input.shardCount ?? 16;
  const requestedParallelism = input.parallelism ?? 8;
  const parallelism = Math.min(requestedParallelism, getMaxParallelism());
  const maxCandidatesPerShard = input.maxCandidatesPerShard ?? 8;
  const requireAllShards = input.requireAllShards ?? true;

  if (
    !Number.isInteger(maxCandidatesPerShard) ||
    maxCandidatesPerShard < 1 ||
    maxCandidatesPerShard > 64
  ) {
    throw new Error('maxCandidatesPerShard must be an integer from 1 to 64');
  }

  const shards = createAimoShardPlan(problem, shardCount);
  const shardPlanHash = hashAimoShardPlan(shards);

  const strategyProvider = dependencies.getStrategy ?? getNvidiaIsingStrategy;
  const strategyHint = await strategyProvider(
    problem,
    input.nvidiaIsing ?? { mode: 'off' },
  );

  const runId = sha256Json({
    schemaVersion: 'dsg-aimo-v1',
    problemHash,
    shardPlanHash,
    maxCandidatesPerShard,
    strategyHintHash: strategyHint?.responseHash ?? null,
    requireAllShards,
  });

  const shardSolver = dependencies.solveShard ?? solveSimulationShard;
  const shardResults = await mapWithDeterministicIndex(
    shards,
    parallelism,
    async (shard): Promise<AimoShardResult> =>
      shardSolver({
        problem,
        shard,
        strategyHint,
        maxCandidates: maxCandidatesPerShard,
      }),
  );

  const shardSuccessCount = shardResults.filter((item) => item.ok).length;
  const shardCompleteCount = shardResults.filter(
    (item) => item.ok && item.searchComplete,
  ).length;
  const searchCoverage: AimoHarnessReceipt['searchCoverage'] =
    shardSuccessCount === 0
      ? 'NONE'
      : shardCompleteCount === shards.length
        ? 'COMPLETE'
        : 'PARTIAL';

  const candidates = shardResults
    .flatMap((result) => result.candidates)
    .sort((a, b) => a.candidateHash.localeCompare(b.candidateHash));

  const verifier = dependencies.verifyCandidate ?? verifyAimoCandidate;
  const verified: AimoCandidateVerification[] =
    await mapWithDeterministicIndex(
      candidates,
      parallelism,
      async (candidate) => ({
        candidate,
        verification: await verifier(candidate),
      }),
    );

  const selected = selectCanonicalVerifiedCandidate(verified);
  const independentGlobalOptimum =
    selected?.verification.certificateLevel === 'VERIFIED_GLOBAL_OPTIMUM';
  const coverageAllowsPass =
    independentGlobalOptimum ||
    searchCoverage === 'COMPLETE' ||
    requireAllShards === false;

  let verdict: AimoHarnessReceipt['verdict'] = 'BLOCKED';
  let nextAction: string | undefined;

  if (selected && coverageAllowsPass) {
    verdict = 'PASS';
  } else if (selected && !coverageAllowsPass) {
    verdict = 'REVIEW';
    nextAction =
      'Replay the failed shards until searchCoverage=COMPLETE, or explicitly run with requireAllShards=false and preserve that truth boundary.';
  } else if (searchCoverage !== 'COMPLETE') {
    verdict = 'BLOCKED';
    nextAction =
      'Restore DSG AGI Simulation connectivity and replay every deterministic shard.';
  } else {
    verdict = 'BLOCKED';
    nextAction =
      'No candidate passed the structured verifier. Continue deterministic search or add a correct per-problem verification certificate.';
  }

  const externalProviderDeterminism: AimoHarnessReceipt['externalProviderDeterminism'] =
    !strategyHint
      ? 'NOT_USED'
      : strategyHint.mode === 'pinned'
        ? 'PINNED'
        : 'NOT_GUARANTEED';

  const runDeterminism: AimoHarnessReceipt['runDeterminism'] =
    externalProviderDeterminism === 'NOT_GUARANTEED'
      ? 'CORE_ONLY'
      : 'FULL';

  const truthBoundary =
    'DSG deterministic sharding, candidate hashing, canonical selection, replay inputs, and verifier gating are deterministic. searchCoverage=COMPLETE requires every shard to report searchComplete=true, not merely HTTP success. A live external NVIDIA NIM response is not claimed byte-deterministic; pin its response hash/text for full replay. VERIFIED_GLOBAL_OPTIMUM may PASS despite partial shard search because Cinema independently proves that no lower-energy assignment exists in the full finite encoding. Audit-chain event hashes are preserved as evidence but excluded from the deterministic receipt hash; proofHash/certificateLevel remain binding. No PASS claims arbitrary natural-language proof correctness.';

  const receiptWithoutHash = {
    schemaVersion: 'dsg-aimo-v1' as const,
    runId,
    problemHash,
    shardPlanHash,
    shardCount: shards.length,
    shardSuccessCount,
    shardCompleteCount,
    candidateCount: candidates.length,
    ...(strategyHint ? { strategyHintHash: strategyHint.responseHash } : {}),
    ...(selected ? { selectedCandidate: selected.candidate } : {}),
    ...(selected ? { selectedVerification: selected.verification } : {}),
    verdict,
    searchCoverage,
    deterministicCore: true as const,
    runDeterminism,
    externalProviderDeterminism,
    truthBoundary,
    ...(nextAction ? { nextAction } : {}),
  };

  const deterministicVerification = selected
    ? {
        verdict: selected.verification.verdict,
        verifier: selected.verification.verifier,
        reason: selected.verification.reason,
        proofHash: selected.verification.proofHash ?? null,
        certificateLevel: selected.verification.certificateLevel ?? null,
      }
    : null;

  const deterministicReceiptPayload = {
    schemaVersion: 'dsg-aimo-v1' as const,
    runId,
    problemHash,
    shardPlanHash,
    shardCount: shards.length,
    shardSuccessCount,
    shardCompleteCount,
    candidateCount: candidates.length,
    strategyHintHash: strategyHint?.responseHash ?? null,
    selectedCandidateHash: selected?.candidate.candidateHash ?? null,
    selectedVerification: deterministicVerification,
    verdict,
    searchCoverage,
    deterministicCore: true as const,
    runDeterminism,
    externalProviderDeterminism,
    truthBoundary,
    nextAction: nextAction ?? null,
  };

  return {
    ...receiptWithoutHash,
    receiptHash: sha256Json(deterministicReceiptPayload),
  };
}
