import { createHmac, timingSafeEqual } from 'node:crypto';

type AimoServiceName = 'simulation' | 'cinema' | 'control-plane';

interface AimoRegistryDocument {
  simulationUrl?: string;
  cinemaUrl?: string;
  controlPlaneUrl?: string;
  maxParallelism?: number;
}

export interface AimoServiceConfig {
  mode: 'registry' | 'legacy';
  simulationUrl?: string;
  cinemaUrl?: string;
  controlPlaneUrl?: string;
  simulationApiKey?: string;
  cinemaApiKey?: string;
  /**
   * Canonical DSG API key for /api/dsg/v1/* routes. This is deliberately not
   * derived from DSG_AIMO_ROOT_KEY because Control Plane API auth resolves its
   * own persisted API-key store.
   */
  controlPlaneApiKey?: string;
  maxParallelism: number;
  rootKeyConfigured: boolean;
}

export interface AimoServiceReadiness {
  ready: boolean;
  mode: 'registry' | 'legacy';
  simulationConfigured: boolean;
  cinemaConfigured: boolean;
  controlPlaneConfigured: boolean;
  internalAuthConfigured: boolean;
  maxParallelism: number;
  missing: string[];
}

function optional(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
}

function parseRegistry(raw: string | undefined): AimoRegistryDocument | undefined {
  const value = optional(raw);
  if (!value) return undefined;

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error('DSG_AIMO_SERVICE_REGISTRY must be valid JSON');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('DSG_AIMO_SERVICE_REGISTRY must be a JSON object');
  }

  const candidate = parsed as Record<string, unknown>;
  return {
    simulationUrl:
      typeof candidate.simulationUrl === 'string'
        ? optional(candidate.simulationUrl)
        : undefined,
    cinemaUrl:
      typeof candidate.cinemaUrl === 'string'
        ? optional(candidate.cinemaUrl)
        : undefined,
    controlPlaneUrl:
      typeof candidate.controlPlaneUrl === 'string'
        ? optional(candidate.controlPlaneUrl)
        : undefined,
    maxParallelism:
      typeof candidate.maxParallelism === 'number'
        ? candidate.maxParallelism
        : undefined,
  };
}

function normalizeParallelism(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value ?? 16);
  if (!Number.isInteger(parsed) || parsed < 1) return 16;
  return Math.min(parsed, 64);
}

export function deriveAimoServiceToken(
  rootKey: string,
  service: AimoServiceName,
): string {
  const digest = createHmac('sha256', rootKey)
    .update(`dsg-aimo-v1:${service}`)
    .digest('hex');
  return `dsg_aimo_${digest}`;
}

export function isAimoControlPlaneTokenAuthorized(
  provided: string | undefined,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const rootKey = optional(env.DSG_AIMO_ROOT_KEY);
  const token = optional(provided);
  if (!rootKey || !token) return false;

  const expected = deriveAimoServiceToken(rootKey, 'control-plane');
  const actualBytes = Buffer.from(token);
  const expectedBytes = Buffer.from(expected);
  if (actualBytes.length !== expectedBytes.length) return false;
  return timingSafeEqual(actualBytes, expectedBytes);
}

export function getAimoServiceConfig(
  env: NodeJS.ProcessEnv = process.env,
): AimoServiceConfig {
  const registry = parseRegistry(env.DSG_AIMO_SERVICE_REGISTRY);
  const rootKey = optional(env.DSG_AIMO_ROOT_KEY);

  const simulationUrl =
    registry?.simulationUrl ?? optional(env.DSG_AGI_SIMULATION_URL);
  const cinemaUrl = registry?.cinemaUrl ?? optional(env.DSG_CINEMA_PROOF_URL);
  const controlPlaneUrl =
    registry?.controlPlaneUrl ?? optional(env.DSG_CONTROL_PLANE_URL);

  const simulationApiKey =
    optional(env.DSG_AGI_SIMULATION_API_KEY) ??
    (rootKey ? deriveAimoServiceToken(rootKey, 'simulation') : undefined);
  const cinemaApiKey =
    optional(env.DSG_CINEMA_PROOF_API_KEY) ??
    (rootKey ? deriveAimoServiceToken(rootKey, 'cinema') : undefined);
  const controlPlaneApiKey = optional(env.DSG_CONTROL_PLANE_API_KEY);

  const maxParallelism = normalizeParallelism(
    registry?.maxParallelism ?? env.DSG_AIMO_MAX_PARALLELISM,
  );

  return {
    mode: registry ? 'registry' : 'legacy',
    simulationUrl,
    cinemaUrl,
    controlPlaneUrl,
    simulationApiKey,
    cinemaApiKey,
    controlPlaneApiKey,
    maxParallelism,
    rootKeyConfigured: Boolean(rootKey),
  };
}

export function getAimoServiceReadiness(
  env: NodeJS.ProcessEnv = process.env,
): AimoServiceReadiness {
  const config = getAimoServiceConfig(env);
  const missing: string[] = [];

  if (!config.simulationUrl) missing.push('simulationUrl');
  if (!config.cinemaUrl) missing.push('cinemaUrl');
  if (!config.controlPlaneUrl) missing.push('controlPlaneUrl');
  if (!config.simulationApiKey) missing.push('simulationAuth');
  if (!config.cinemaApiKey) missing.push('cinemaAuth');
  if (!config.controlPlaneApiKey) missing.push('controlPlaneAuth');

  return {
    ready: missing.length === 0,
    mode: config.mode,
    simulationConfigured: Boolean(config.simulationUrl),
    cinemaConfigured: Boolean(config.cinemaUrl),
    controlPlaneConfigured: Boolean(
      config.controlPlaneUrl && config.controlPlaneApiKey,
    ),
    internalAuthConfigured: Boolean(
      config.simulationApiKey &&
        config.cinemaApiKey &&
        config.controlPlaneApiKey,
    ),
    maxParallelism: config.maxParallelism,
    missing,
  };
}
