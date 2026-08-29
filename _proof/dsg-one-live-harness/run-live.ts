import { writeFileSync } from 'node:fs';
import { runAimoHarness } from './lib/dsg/aimo/harness';

type SafeEvent = { surface: string; status: number; searchedAssignments?: number; searchComplete?: boolean; encodingProofId?: string; encodingProofHash?: string; encodingProofAuthority?: string };
const events: SafeEvent[] = [];
const originalFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input.toString() : input.url);
  const response = await originalFetch(input, init);
  const event: SafeEvent = { surface: url.pathname, status: response.status };
  if (url.pathname === '/v1/aimo/solve-shard') {
    try {
      const body = await response.clone().json() as Record<string, unknown>;
      if (typeof body.searchedAssignments === 'number') event.searchedAssignments = body.searchedAssignments;
      if (typeof body.searchComplete === 'boolean') event.searchComplete = body.searchComplete;
      if (typeof body.encodingProofId === 'string') event.encodingProofId = body.encodingProofId;
      if (typeof body.encodingProofHash === 'string') event.encodingProofHash = body.encodingProofHash;
      if (typeof body.encodingProofAuthority === 'string') event.encodingProofAuthority = body.encodingProofAuthority;
    } catch {}
  }
  if (url.pathname === '/api/dsg/v1/encoding/prove' || url.pathname === '/v1/aimo/solve-shard' || url.pathname === '/v1/math/aimo/exact-energy-witness') events.push(event);
  return response;
}) as typeof fetch;

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const receipt = await runAimoHarness({
  problem: {
    problemId: 'dsg-live-authority-proof-v1',
    statement: 'Find the exact minimum of the supplied two-variable QUBO encoding.',
    domain: 'live-e2e-proof',
    constraints: {
      aimoEncoding: {
        kind: 'qubo-v1',
        variableCount: 2,
        linear: [
          { i: 0, weight: -3 },
          { i: 1, weight: -2 },
        ],
        quadratic: [{ i: 0, j: 1, weight: 4 }],
        objective: 'min',
      },
    },
  },
  shardCount: 1,
  parallelism: 1,
  maxCandidatesPerShard: 2,
  nvidiaIsing: { mode: 'off' },
  requireAllShards: true,
});

const selected = receipt.selectedCandidate;
const metadata = selected?.metadata ?? {};
const verification = receipt.selectedVerification;
const simulationEvent = events.find((event) => event.surface === '/v1/aimo/solve-shard');
const proofId = typeof metadata.encodingProofId === 'string' ? metadata.encodingProofId : '';
const proofHash = typeof metadata.encodingProofHash === 'string' ? metadata.encodingProofHash : '';

let authorityLookupStatus = 0;
let authorityLookupMatches = false;
if (proofId) {
  const base = process.env.DSG_CONTROL_PLANE_URL;
  const key = process.env.DSG_CONTROL_PLANE_API_KEY;
  requireValue(base && key, 'Control Plane lookup binding missing');
  const lookup = await originalFetch(new URL(`/api/dsg/v1/encoding/proofs/${proofId}`, base), {
    headers: { Accept: 'application/json', Authorization: `Bearer ${key}` },
    signal: AbortSignal.timeout(15_000),
  });
  authorityLookupStatus = lookup.status;
  if (lookup.ok) {
    const body = await lookup.json() as Record<string, any>;
    authorityLookupMatches = body.ok === true && body.status === 'PASS' && body.proofId === proofId && body.proof?.proofHash === proofHash;
  }
}

const proof = {
  schemaVersion: 'dsg-live-aimo-e2e-proof-v1',
  dsgOneSourceCommit: 'b2395a072b1e85c68fababefe799c07744641605',
  verdict: receipt.verdict,
  searchCoverage: receipt.searchCoverage,
  shardSuccessCount: receipt.shardSuccessCount,
  shardCompleteCount: receipt.shardCompleteCount,
  candidateCount: receipt.candidateCount,
  receiptHash: receipt.receiptHash,
  candidateHash: selected?.candidateHash ?? null,
  encodingProofId: proofId || null,
  encodingProofHash: proofHash || null,
  encodingProofAuthority: typeof metadata.encodingProofAuthority === 'string' ? metadata.encodingProofAuthority : null,
  searchedAssignments: simulationEvent?.searchedAssignments ?? null,
  simulationSearchComplete: simulationEvent?.searchComplete ?? null,
  verifierVerdict: verification?.verdict ?? null,
  verifier: verification?.verifier ?? null,
  verifierProofHash: verification?.proofHash ?? null,
  certificateLevel: verification?.certificateLevel ?? null,
  authorityLookupStatus,
  authorityLookupMatches,
  network: events,
  truthBoundary: 'Executes byte-identical merged DSG ONE AIMO orchestration source in a Cinema production-authorized GitHub runner against live Azure Control Plane, Simulation and Cinema services. It proves the finite encoded QUBO execution/proof chain, not arbitrary natural-language theorem correctness.',
};

writeFileSync('live-e2e-proof.json', `${JSON.stringify(proof, null, 2)}\n`);
console.log(`LIVE_AIMO_E2E_PROOF=${JSON.stringify(proof)}`);

requireValue(receipt.verdict === 'PASS', `receipt verdict=${receipt.verdict}`);
requireValue(receipt.searchCoverage === 'COMPLETE', `searchCoverage=${receipt.searchCoverage}`);
requireValue(receipt.shardSuccessCount === 1, `shardSuccessCount=${receipt.shardSuccessCount}`);
requireValue(receipt.shardCompleteCount === 1, `shardCompleteCount=${receipt.shardCompleteCount}`);
requireValue(receipt.candidateCount > 0, `candidateCount=${receipt.candidateCount}`);
requireValue(selected, 'selected candidate missing');
requireValue(metadata.encodingProofAuthority === 'DSG_CONTROL_PLANE', 'encoding proof authority mismatch');
requireValue(/^epf_[0-9a-f]{32}$/.test(proofId), 'encoding proof id malformed');
requireValue(/^[0-9a-f]{64}$/.test(proofHash), 'encoding proof hash malformed');
requireValue((simulationEvent?.searchedAssignments ?? 0) > 0, 'simulation enumerated zero assignments');
requireValue(simulationEvent?.searchComplete === true, 'simulation search not complete');
requireValue(verification?.verdict === 'PASS', `verifier verdict=${verification?.verdict ?? 'missing'}`);
requireValue(Boolean(verification?.proofHash), 'Cinema verifier proof hash missing');
requireValue(authorityLookupStatus === 200 && authorityLookupMatches, 'Control Plane persisted authority lookup mismatch');
console.log('FULL_LIVE_E2E=PASS');
