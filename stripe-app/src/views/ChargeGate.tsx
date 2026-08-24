import React, { useEffect, useMemo, useState } from 'react';
import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context';
import { createHttpClient, STRIPE_API_KEY } from '@stripe/ui-extension-sdk/http_client';
import {
  Badge,
  Banner,
  Box,
  Button,
  ContextView,
  Spinner,
} from '@stripe/ui-extension-sdk/ui';
import { fetchStripeSignature } from '@stripe/ui-extension-sdk/utils';
import Stripe from 'stripe';

import { CINEMA_API_BASE } from '../runtime';

type Decision = 'ALLOW' | 'REVIEW' | 'BLOCK';
type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
type StripeObjectType = 'charge' | 'payment_intent';

const stripe = new Stripe(STRIPE_API_KEY, {
  httpClient: createHttpClient(),
  apiVersion: '2025-08-27.basil',
});
const REQUEST_TIMEOUT_MS = 20_000;

function withAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      const error = new Error('Operation aborted');
      error.name = 'AbortError';
      reject(error);
    };
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener('abort', onAbort, { once: true });
    operation.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener('abort', onAbort);
        reject(error);
      },
    );
  });
}

interface Remediation {
  code: string;
  problem: string;
  cause: string;
  next_step: string;
  self_service: boolean;
  endpoint?: string;
  docs: string;
}

interface VerificationResult {
  decision: Decision;
  reason: string;
  risk_score: number;
  risk_level: RiskLevel;
  policy_version: string;
  verified: boolean;
  verification: 'VERIFIED_GLOBAL_OPTIMUM';
  proof_hash: string;
  request_hash: string;
  context_hash: string;
  witness: number[];
  energy_exact?: string | null;
  evaluated_at: string;
}

const BADGE_TYPE = {
  ALLOW: 'positive',
  REVIEW: 'warning',
  BLOCK: 'negative',
} as const;

const BANNER_TYPE = {
  ALLOW: 'default',
  REVIEW: 'caution',
  BLOCK: 'critical',
} as const;

function readObjectType(value: unknown, id: string): StripeObjectType | null {
  if (value === 'charge' && id.startsWith('ch_')) return 'charge';
  if (value === 'payment_intent' && id.startsWith('pi_')) return 'payment_intent';
  return null;
}

function shortHash(value: string): string {
  if (!value) return 'Unavailable';
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function readRemediation(body: unknown): Remediation | null {
  if (!body || typeof body !== 'object') return null;
  const envelope = body as Record<string, unknown>;
  const detail =
    envelope.detail && typeof envelope.detail === 'object'
      ? (envelope.detail as Record<string, unknown>)
      : envelope;
  const remediation = detail.remediation;
  if (!remediation || typeof remediation !== 'object') return null;

  const candidate = remediation as Record<string, unknown>;
  if (typeof candidate.next_step !== 'string' || typeof candidate.problem !== 'string') {
    return null;
  }
  return candidate as unknown as Remediation;
}

function normalizeRiskLevel(value: unknown): RiskLevel | undefined {
  if (value === 'low' || value === 'medium' || value === 'high' || value === 'critical') {
    return value;
  }
  if (value === 'normal') return 'low';
  if (value === 'elevated') return 'high';
  if (value === 'highest') return 'critical';
  return undefined;
}

function readTransactionContext({ userContext, environment }: ExtensionContextValue) {
  const objectId = environment?.objectContext?.id ?? '';
  return {
    accountId: userContext?.account?.id ?? '',
    userId: userContext?.id ?? '',
    objectId,
    objectType: readObjectType(environment?.objectContext?.object, objectId),
  };
}

async function retrieveTransaction(
  objectType: StripeObjectType,
  objectId: string,
  timeoutMs: number,
) {
  if (objectType === 'charge') {
    const charge = await stripe.charges.retrieve(objectId, { timeout: timeoutMs });
    return {
      amountCents: charge.amount,
      currency: charge.currency,
      stripeStatus: charge.status,
      riskLevel: normalizeRiskLevel(charge.outcome?.risk_level),
      livemode: charge.livemode,
    };
  }

  const paymentIntent = await stripe.paymentIntents.retrieve(
    objectId,
    { expand: ['latest_charge'] },
    { timeout: timeoutMs },
  );
  const latestCharge =
    paymentIntent.latest_charge && typeof paymentIntent.latest_charge !== 'string'
      ? paymentIntent.latest_charge
      : null;
  return {
    amountCents: paymentIntent.amount_received || paymentIntent.amount,
    currency: paymentIntent.currency,
    stripeStatus: paymentIntent.status,
    riskLevel: normalizeRiskLevel(latestCharge?.outcome?.risk_level),
    livemode: paymentIntent.livemode,
  };
}

export default function ChargeGate(extensionContext: ExtensionContextValue) {
  const transaction = useMemo(
    () => readTransactionContext(extensionContext),
    [extensionContext.environment, extensionContext.userContext],
  );

  const [result, setResult] = useState<VerificationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [remediation, setRemediation] = useState<Remediation | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | undefined;

    const verify = async () => {
      let requestTimeout: ReturnType<typeof setTimeout> | undefined;
      let requestTimedOut = false;
      if (
        !transaction.accountId ||
        !transaction.userId ||
        !transaction.objectId ||
        !transaction.objectType
      ) {
        setResult(null);
        setRemediation(null);
        setError('Open a Stripe charge or PaymentIntent detail view.');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      setRemediation(null);

      try {
        controller = new AbortController();
        requestTimeout = setTimeout(() => {
          requestTimedOut = true;
          controller?.abort();
        }, REQUEST_TIMEOUT_MS);
        const stripeObject = await withAbort(
          retrieveTransaction(
            transaction.objectType,
            transaction.objectId,
            REQUEST_TIMEOUT_MS,
          ),
          controller.signal,
        );
        const signedPayload: Record<string, string | number | boolean> = {
          stripe_account_id: transaction.accountId,
          livemode: stripeObject.livemode,
          object_type: transaction.objectType,
          object_id: transaction.objectId,
          amount_cents: stripeObject.amountCents,
          currency: stripeObject.currency,
          stripe_status: stripeObject.stripeStatus,
        };
        if (stripeObject.riskLevel) {
          signedPayload.risk_level = stripeObject.riskLevel;
        }

        // Stripe adds the current user_id and account_id to this signature.
        // Per the Stripe Apps backend guide, pass only the additional payload,
        // then append those two context fields to the body.
        const stripeSignature = await withAbort(
          fetchStripeSignature(signedPayload),
          controller.signal,
        );
        const response = await fetch(`${CINEMA_API_BASE}/stripe/evaluate`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'Stripe-Signature': stripeSignature,
          },
          body: JSON.stringify({
            ...signedPayload,
            user_id: transaction.userId,
            account_id: transaction.accountId,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          // A refusal carries the action that resolves it. Show that instead of
          // leaving the user with a status code they cannot act on.
          const refusal = await response.json().catch(() => null);
          const fix = readRemediation(refusal);
          if (fix && !cancelled) {
            setRemediation(fix);
          }
          throw new Error(
            fix?.problem ?? `Verification unavailable (HTTP ${response.status})`,
          );
        }

        const body = (await response.json()) as VerificationResult;
        if (
          body.verified !== true ||
          body.verification !== 'VERIFIED_GLOBAL_OPTIMUM' ||
          !['ALLOW', 'REVIEW', 'BLOCK'].includes(body.decision)
        ) {
          throw new Error('Backend returned an unverified decision');
        }

        if (!cancelled) {
          setResult(body);
        }
      } catch (err) {
        if (!cancelled) {
          setResult(null);
          setError(
            requestTimedOut || (err instanceof Error && err.name === 'AbortError')
              ? 'Verification timed out. Retry after checking the Cinema service status.'
              : err instanceof Error
                ? err.message
                : 'Verification unavailable',
          );
        }
      } finally {
        if (requestTimeout !== undefined) {
          clearTimeout(requestTimeout);
        }
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    verify();

    return () => {
      cancelled = true;
      controller?.abort();
    };
  }, [
    transaction.accountId,
    transaction.userId,
    transaction.objectId,
    transaction.objectType,
    retryKey,
  ]);

  if (loading) {
    return (
      <ContextView title="DSG Governance Gate">
        <Box css={{ alignX: 'center', padding: 'large' }}>
          <Spinner />
        </Box>
      </ContextView>
    );
  }

  if (!result) {
    return (
      <ContextView title="DSG Governance Gate">
        <Box css={{ stack: 'y', gapY: 'medium' }}>
          <Badge type="warning">REVIEW</Badge>
          <Banner
            type="caution"
            title="Verification needs attention"
            description={error ?? 'No verified result is available. The safe state is REVIEW.'}
          />

          {remediation ? (
            <Box css={{ stack: 'y', gapY: 'small' }}>
              <Box css={{ font: 'caption', color: 'secondary' }}>What to do next</Box>
              <Box css={{ font: 'caption' }}>{remediation.next_step}</Box>
              <Box css={{ font: 'caption', color: 'secondary' }}>
                {remediation.self_service
                  ? 'You can resolve this yourself.'
                  : 'This needs an operator on the DSG side.'}
              </Box>
            </Box>
          ) : null}

          <Box css={{ font: 'caption', color: 'secondary' }}>
            No transaction is treated as approved when the exact proof is unavailable.
          </Box>
          <Button type="primary" onPress={() => setRetryKey((value) => value + 1)}>
            Retry verification
          </Button>
        </Box>
      </ContextView>
    );
  }

  return (
    <ContextView title="DSG Governance Gate">
      <Box css={{ stack: 'y', gapY: 'medium' }}>
        <Badge type={BADGE_TYPE[result.decision]}>{result.decision}</Badge>

        <Banner
          type={BANNER_TYPE[result.decision]}
          title={
            result.decision === 'ALLOW'
              ? 'Verified for this policy'
              : result.decision === 'BLOCK'
                ? 'Blocked by verified policy'
                : 'Review required'
          }
          description={result.reason}
        />

        <Box css={{ stack: 'y', gapY: 'small' }}>
          <Box css={{ font: 'caption', color: 'secondary' }}>Risk</Box>
          <Box css={{ font: 'caption' }}>
            {result.risk_level.toUpperCase()} · {result.risk_score}/100
          </Box>
        </Box>

        <Box css={{ stack: 'y', gapY: 'small' }}>
          <Box css={{ font: 'caption', color: 'secondary' }}>Verification</Box>
          <Badge type="positive">Z3 global optimum verified</Badge>
        </Box>

        <Box css={{ stack: 'y', gapY: 'small' }}>
          <Box css={{ font: 'caption', color: 'secondary' }}>Policy</Box>
          <Box css={{ font: 'caption' }}>{result.policy_version}</Box>
        </Box>

        <Box css={{ stack: 'y', gapY: 'small' }}>
          <Box css={{ font: 'caption', color: 'secondary' }}>Proof</Box>
          <Box css={{ font: 'caption', wordBreak: 'break-all' }}>
            {shortHash(result.proof_hash)}
          </Box>
        </Box>

        <Box css={{ stack: 'y', gapY: 'small' }}>
          <Box css={{ font: 'caption', color: 'secondary' }}>Transaction binding</Box>
          <Box css={{ font: 'caption', wordBreak: 'break-all' }}>
            {shortHash(result.context_hash)}
          </Box>
        </Box>

        <Box css={{ font: 'caption', color: 'secondary' }}>
          Decision, proof, and transaction context are bound deterministically. If verification
          cannot complete, the app falls back to REVIEW.
        </Box>
      </Box>
    </ContextView>
  );
}
