import { createHash } from 'node:crypto';

export function normalizeStable(value: unknown): unknown {
  if (value === null) return null;
  if (Array.isArray(value)) return value.map((item) => normalizeStable(item));

  if (typeof value === 'object') {
    const source = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) {
      const item = source[key];
      if (typeof item !== 'undefined') out[key] = normalizeStable(item);
    }
    return out;
  }

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('non-finite number is not deterministic JSON');
    return value;
  }

  if (typeof value === 'bigint') return value.toString();
  return value;
}

export function stableStringify(value: unknown): string {
  return JSON.stringify(normalizeStable(value));
}

export function sha256Stable(value: unknown): string {
  return `sha256:${createHash('sha256').update(stableStringify(value), 'utf8').digest('hex')}`;
}

// ============================================================================
// Cross-language interop hashing
// ============================================================================
//
// `sha256Stable` above is this repository's internal content hash. It carries a
// `sha256:` prefix and leaves non-ASCII characters unescaped, because
// `JSON.stringify` does.
//
// The DSG Cinema Proof Agent computes its hashes with
// `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
// and publishes bare hex. Those two encodings agree on ASCII payloads and
// disagree the moment a payload carries a non-ASCII character — so a
// `problemHash` that crosses the repository boundary cannot use the internal
// form.
//
// The pair below is the interop form: same key ordering, same separators, plus
// Python's `ensure_ascii` escaping, and a bare hex digest. See
// `contracts/CANONICAL_HASH.md` for the byte-level specification and
// `contracts/reference/canonical_hash.py` for the Python side.

/** Identifier for the encoding `sha256HexStable` implements. */
export const CANONICAL_HASH_ALGORITHM = 'sha256-canonical-json-ascii-v1';

const NON_ASCII = new RegExp('[\\u007f-\\uffff]', 'g');

/**
 * Canonical JSON with every non-ASCII code unit escaped as `\uXXXX`.
 *
 * The escape is per UTF-16 code unit, which is what `ensure_ascii` does too:
 * an astral character becomes its surrogate pair, not a single `\U0001f600`.
 */
export function canonicalJsonAscii(value: unknown): string {
  const json = JSON.stringify(normalizeStable(value));
  if (typeof json === 'undefined') {
    throw new Error('value has no canonical JSON encoding');
  }
  return json.replace(NON_ASCII, (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
}

/** SHA-256 over `canonicalJsonAscii`, as bare lowercase hex. */
export function sha256HexStable(value: unknown): string {
  return createHash('sha256').update(canonicalJsonAscii(value), 'utf8').digest('hex');
}
