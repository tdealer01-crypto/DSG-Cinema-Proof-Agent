import { sha256Json } from '@/lib/dsg/runtime/hash';
import type { AimoProblemInput, AimoStrategyHint } from './types';
import { normalizeAimoProblem } from './deterministic';

const DEFAULT_NVIDIA_BASE_URL = 'https://integrate.api.nvidia.com';
const DEFAULT_NVIDIA_ISING_MODEL = 'nvidia/ising-calibration-1.5-31b';

export type NvidiaIsingMode = 'off' | 'live' | 'pinned';

export interface NvidiaIsingStrategyConfig {
  mode?: NvidiaIsingMode;
  pinnedText?: string;
  model?: string;
}

function responseText(payload: unknown): string {
  const body = payload as {
    choices?: Array<{ message?: { content?: unknown } }>;
  };
  const content = body.choices?.[0]?.message?.content;
  if (typeof content === 'string') return content.trim();
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === 'string') return part;
        if (part && typeof part === 'object' && 'text' in part) {
          const text = (part as { text?: unknown }).text;
          return typeof text === 'string' ? text : '';
        }
        return '';
      })
      .join('\n')
      .trim();
  }
  return '';
}

export async function getNvidiaIsingStrategy(
  problem: AimoProblemInput,
  config: NvidiaIsingStrategyConfig = {},
): Promise<AimoStrategyHint | undefined> {
  const mode = config.mode ?? 'off';
  if (mode === 'off') return undefined;

  const model =
    config.model ??
    process.env.NVIDIA_ISING_MODEL ??
    DEFAULT_NVIDIA_ISING_MODEL;

  if (mode === 'pinned') {
    const text = config.pinnedText?.trim();
    if (!text) throw new Error('pinned NVIDIA Ising mode requires pinnedText');
    return {
      provider: 'nvidia-ising',
      model,
      text,
      responseHash: sha256Json({ model, text }),
      mode: 'pinned',
      determinism: 'PINNED_REPLAY',
    };
  }

  const apiKey = process.env.NVIDIA_API_KEY;
  if (!apiKey) throw new Error('NVIDIA_API_KEY is not configured');

  const baseUrl =
    process.env.NVIDIA_NIM_BASE_URL ?? DEFAULT_NVIDIA_BASE_URL;
  const url = new URL('/v1/chat/completions', baseUrl);

  if (
    process.env.NODE_ENV === 'production' &&
    url.protocol !== 'https:'
  ) {
    throw new Error('NVIDIA_NIM_BASE_URL must use HTTPS in production');
  }

  const normalized = normalizeAimoProblem(problem);
  const prompt = [
    'You are an advisory strategy source inside DSG AIMO Harness.',
    'Do not claim that you verified or proved the answer.',
    'Return concise mathematical search strategies, decompositions, invariants,',
    'candidate encodings, and falsification ideas that a deterministic simulator can use.',
    'The downstream DSG simulator and proof verifier are authoritative.',
    '',
    `Problem ID: ${normalized.problemId ?? 'unknown'}`,
    `Domain: ${normalized.domain ?? 'unknown'}`,
    'Problem:',
    normalized.statement,
  ].join('\n');

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model,
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 2048,
      temperature: 0,
      top_p: 1,
      stream: false,
    }),
    signal: AbortSignal.timeout(60_000),
  });

  if (!response.ok) {
    throw new Error(`NVIDIA Ising NIM returned HTTP ${response.status}`);
  }

  const payload = await response.json();
  const text = responseText(payload);
  if (!text) throw new Error('NVIDIA Ising NIM returned no strategy text');

  return {
    provider: 'nvidia-ising',
    model,
    text,
    responseHash: sha256Json({ model, text }),
    mode: 'live',
    determinism: 'EXTERNAL_PROVIDER_NOT_GUARANTEED',
  };
}
