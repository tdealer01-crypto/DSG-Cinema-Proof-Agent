import { createHmac, timingSafeEqual } from 'node:crypto';

export function deriveAimoSimulationToken(rootKey: string): string {
  const digest = createHmac('sha256', rootKey)
    .update('dsg-aimo-v1:simulation')
    .digest('hex');
  return `dsg_aimo_${digest}`;
}

export function resolveAimoExpectedKey(
  serviceKey: string | undefined,
  rootKey: string | undefined,
): string | undefined {
  const specific = serviceKey?.trim();
  if (specific) return specific;

  const root = rootKey?.trim();
  return root ? deriveAimoSimulationToken(root) : undefined;
}

export function isAimoBearerAuthorized(
  authorization: string | string[] | undefined,
  expected: string | undefined,
  production: boolean,
): boolean {
  if (!expected) return !production;
  if (Array.isArray(authorization)) return false;
  if (typeof authorization !== 'string' || !authorization.startsWith('Bearer ')) return false;

  const actual = authorization.slice('Bearer '.length);
  const actualBytes = new TextEncoder().encode(actual);
  const expectedBytes = new TextEncoder().encode(expected);
  if (actualBytes.byteLength !== expectedBytes.byteLength) return false;
  return timingSafeEqual(actualBytes, expectedBytes);
}
