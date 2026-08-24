import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const manifest = JSON.parse(await readFile(path.join(root, 'stripe-app.json'), 'utf8'));

const allowedTopLevel = new Set([
  '$schema',
  'allowed_redirect_uris',
  'constants',
  'distribution_type',
  'icon',
  'id',
  'name',
  'permissions',
  'sandbox_install_compatible',
  'stripe_api_access_type',
  'ui_extension',
  'version',
]);
const unexpected = Object.keys(manifest).filter((key) => !allowedTopLevel.has(key));
if (unexpected.length > 0) {
  throw new Error(`Unsupported Stripe manifest fields: ${unexpected.join(', ')}`);
}

if (
  manifest.id !== 'pics.dsg.governance' ||
  manifest.name !== 'DSG Governance Gate' ||
  manifest.version !== '2.7.1' ||
  manifest.distribution_type !== 'public' ||
  manifest.sandbox_install_compatible !== true ||
  manifest.stripe_api_access_type !== 'oauth'
) {
  throw new Error('Stripe app identity, distribution, or authentication contract is invalid');
}

if (!Array.isArray(manifest.allowed_redirect_uris) || manifest.allowed_redirect_uris.length !== 1) {
  throw new Error('Exactly one production OAuth redirect URI is required');
}
const [redirectUri] = manifest.allowed_redirect_uris;
if (!/^https:\/\/[^/]+\/marketplace\/stripe\/callback$/.test(redirectUri)) {
  throw new Error(`OAuth redirect URI is not a concrete HTTPS callback: ${redirectUri}`);
}

const expectedPermissions = new Set(['charge_read', 'payment_intent_read']);
if (!Array.isArray(manifest.permissions) || manifest.permissions.length !== expectedPermissions.size) {
  throw new Error('Stripe manifest must request only the two payment-detail read permissions');
}
for (const request of manifest.permissions) {
  const keys = Object.keys(request).sort().join(',');
  if (keys !== 'permission,purpose') {
    throw new Error(`Permission request has invalid fields: ${keys}`);
  }
  if (!expectedPermissions.delete(request.permission)) {
    throw new Error(`Unexpected or duplicate permission: ${request.permission}`);
  }
  if (typeof request.purpose !== 'string' || request.purpose.length < 20) {
    throw new Error(`Permission ${request.permission} has no useful purpose`);
  }
}

const views = manifest.ui_extension?.views;
if (
  !Array.isArray(views) ||
  views.length !== 1 ||
  views[0]?.viewport !== 'stripe.dashboard.payment.detail' ||
  views[0]?.component !== 'ChargeGate'
) {
  throw new Error('Stripe payment detail viewport is not wired to ChargeGate');
}

const connectSources = manifest.ui_extension?.content_security_policy?.['connect-src'];
if (!Array.isArray(connectSources) || connectSources.length !== 1) {
  throw new Error('CSP must contain exactly one connect-src URL');
}
const [evaluateUrl] = connectSources;
if (!/^https:\/\/[^/]+\/stripe\/evaluate$/.test(evaluateUrl)) {
  throw new Error(`CSP URL is not the concrete Stripe evaluation endpoint: ${evaluateUrl}`);
}
if (manifest.constants?.CINEMA_API_BASE !== new URL(evaluateUrl).origin) {
  throw new Error('CINEMA_API_BASE constant does not match the CSP origin');
}

console.log(`Validated Stripe App ${manifest.version}: ${evaluateUrl}`);
