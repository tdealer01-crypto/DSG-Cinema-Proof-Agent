import React, { useEffect, useMemo, useState } from 'react';
import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context';
import {
  Badge,
  Banner,
  Box,
  ContextView,
  Spinner,
} from '@stripe/ui-extension-sdk/ui';

import { CINEMA_API_BASE } from '../runtime';

type Decision = 'ALLOW' | 'REVIEW' | 'BLOCK';
type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
type StripeObjectType = 'charge' | 'payment_intent' | 'payout' | 'refund';

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

function inferObjectType(id: string): StripeObjectType | null {
  if (id.startsWith('ch_')) return 'charge';
  if (id.startsWith('pi_')) return 'payment_intent';
  if (id.startsWith('po_')) return 'payout';
  if (id.startsWith('re_')) return 'refund';
  return null;
}

function shortHash(value: string): string {
  if (!value) return 'Unavailable';
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
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

function readTransactionContext(extensionContext?: ExtensionContextValue | null) {
  const ctx = extensionContext as any;
  const objectContext = ctx?.environment?.objectContext ?? {};
  const object = objectContext?.object ?? objectContext;

  const objectId =
    typeof objectContext?.id === 'string'
      ? objectContext.id
      : typeof object?.id === 'string'
        ? object.id
        : '';

  const amountCandidates = [
    object?.amount,
    object?.amount_received,
    object?.amount_captured,
    object?.amount_paid,
  ];
  const amount = amountCandidates.find((value) => typeof value === 'number');

  const riskValue =
    object?.outcome?.risk_level ??
    object?.risk_level ??
    object?.payment_method_details?.risk_level;

  return {
    accountId: typeof ctx?.userContext?.account?.id === 'string' ? ctx.userContext.account.id : '',
    objectId,
    objectType: inferObjectType(objectId),
    amountCents: typeof amount === 'number' ? amount : undefined,
    currency: typeof object?.currency === 'string' ? object.currency : undefined,
    stripeStatus: typeof object?.status === 'string' ? object.status : undefined,
    riskLevel: normalizeRiskLevel(riskValue),
  };
}

export default function ChargeGate({
  extensionContext,
}: {
  extensionContext?: ExtensionContextValue | null;
}) {
  const transaction = useMemo(
    () => readTransactionContext(extensionContext),
    [extensionContext],
  );

  const [result, setResult] = useState<VerificationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      if (!transaction.accountId || !transaction.objectId || !transaction.objectType) {
        setResult(null);
        setError('Open a supported Stripe payment, payout, or refund detail view.');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`${CINEMA_API_BASE}/stripe/evaluate`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            stripe_account_id: transaction.accountId,
            object_type: transaction.objectType,
            object_id: transaction.objectId,
            amount_cents: transaction.amountCents,
            currency: transaction.currency,
            stripe_status: transaction.stripeStatus,
            risk_level: transaction.riskLevel,
          }),
        });

        if (!response.ok) {
          throw new Error(`Verification unavailable (HTTP ${response.status})`);
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
          setError(err instanceof Error ? err.message : 'Verification unavailable');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    verify();

    return () => {
      cancelled = true;
    };
  }, [
    transaction.accountId,
    transaction.objectId,
    transaction.objectType,
    transaction.amountCents,
    transaction.currency,
    transaction.stripeStatus,
    transaction.riskLevel,
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
          <Box css={{ font: 'caption', color: 'secondary' }}>
            No transaction is treated as approved when the exact proof is unavailable.
          </Box>
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
