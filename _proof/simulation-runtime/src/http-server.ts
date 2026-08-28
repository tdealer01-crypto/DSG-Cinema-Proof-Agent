import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import {
  isAimoBearerAuthorized,
  resolveAimoExpectedKey,
} from './aimo/auth.js';
import { solveGovernedAimoShard } from './aimo/governed-solver.js';
import type { AimoShardRequest } from './aimo/types.js';

const PORT = Number(process.env.PORT ?? 8080);
const MAX_BODY_BYTES = 1_000_000;

function json(res: ServerResponse, statusCode: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
    'x-content-type-options': 'nosniff',
  });
  res.end(payload);
}

function expectedKey(): string | undefined {
  return resolveAimoExpectedKey(
    process.env.DSG_AGI_SIMULATION_API_KEY,
    process.env.DSG_AIMO_ROOT_KEY,
  );
}

function authorized(req: IncomingMessage): boolean {
  return isAimoBearerAuthorized(
    req.headers.authorization,
    expectedKey(),
    process.env.NODE_ENV === 'production',
  );
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;

  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY_BYTES) throw new Error('request body too large');
    chunks.push(buffer);
  }

  const text = Buffer.concat(chunks).toString('utf8');
  return text ? JSON.parse(text) : {};
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    json(res, 200, {
      ok: true,
      service: 'dsg-agi-simulation',
      aimoShardEndpoint: '/v1/aimo/solve-shard',
      deterministicSearchKinds: ['qubo-v1', 'ising-v1'],
      authConfigured: Boolean(expectedKey()),
      encodingProofAuthorityConfigured: Boolean(
        process.env.DSG_CONTROL_PLANE_URL && process.env.DSG_CONTROL_PLANE_API_KEY,
      ),
      authMode: process.env.DSG_AGI_SIMULATION_API_KEY
        ? 'service-key'
        : process.env.DSG_AIMO_ROOT_KEY
          ? 'shared-root-derived'
          : 'unconfigured',
      productionAuthFailClosed: true,
      truthBoundary:
        'Public AIMO shard search requires a persisted Control Plane encoding proof bound to the exact structural encoding. PASS means this shard search completed, not that the original natural-language theorem has been proved. Final witness verification belongs to DSG Cinema Proof Agent.',
    });
    return;
  }

  if (req.method === 'POST' && url.pathname === '/v1/aimo/solve-shard') {
    if (!authorized(req)) {
      json(res, 401, { ok: false, status: 'BLOCKED', error: 'unauthorized' });
      return;
    }

    try {
      const body = (await readJson(req)) as AimoShardRequest;
      const result = await solveGovernedAimoShard(body);
      json(res, result.ok ? 200 : 400, result);
    } catch (error) {
      json(res, 400, {
        ok: false,
        status: 'BLOCKED',
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }

  json(res, 404, { ok: false, error: 'not found' });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`DSG AGI Simulation HTTP server listening on ${PORT}`);
});
