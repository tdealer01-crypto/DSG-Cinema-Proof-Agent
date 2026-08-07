create extension if not exists pgcrypto with schema extensions;

create table if not exists public.dsg_audit_head (
  id boolean primary key default true check (id = true),
  sequence bigint not null default 0 check (sequence >= 0),
  event_hash text not null default repeat('0', 64) check (event_hash ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz not null default now()
);

insert into public.dsg_audit_head (id, sequence, event_hash)
values (true, 0, repeat('0', 64))
on conflict (id) do nothing;

create table if not exists public.dsg_audit_events (
  sequence bigint primary key check (sequence > 0),
  created_at timestamptz not null default now(),
  previous_hash text not null check (previous_hash ~ '^[0-9a-f]{64}$'),
  event_hash text not null unique check (event_hash ~ '^[0-9a-f]{64}$'),
  proof_hash text not null check (proof_hash ~ '^[0-9a-f]{64}$'),
  payload jsonb not null
);

create index if not exists dsg_audit_events_created_at_idx on public.dsg_audit_events (created_at desc);
alter table public.dsg_audit_head enable row level security;
alter table public.dsg_audit_events enable row level security;
revoke all on table public.dsg_audit_head from anon, authenticated;
revoke all on table public.dsg_audit_events from anon, authenticated;
grant select on table public.dsg_audit_head to service_role;
grant select on table public.dsg_audit_events to service_role;

create or replace function public.dsg_append_audit_event(p_proof_hash text, p_payload_json text)
returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare
  v_sequence bigint;
  v_previous_hash text;
  v_event_hash text;
  v_payload jsonb;
begin
  if p_proof_hash is null or lower(p_proof_hash) !~ '^[0-9a-f]{64}$' then
    raise exception 'proof_hash must be a 64-character hexadecimal SHA-256 digest';
  end if;
  begin
    v_payload := p_payload_json::jsonb;
  exception when others then
    raise exception 'payload_json must be valid JSON';
  end;
  select sequence, event_hash into v_sequence, v_previous_hash
    from public.dsg_audit_head where id = true for update;
  if not found then
    insert into public.dsg_audit_head (id, sequence, event_hash)
      values (true, 0, repeat('0', 64))
      returning sequence, event_hash into v_sequence, v_previous_hash;
  end if;
  v_sequence := v_sequence + 1;
  v_event_hash := encode(digest(v_previous_hash || ':' || lower(p_proof_hash) || ':' || p_payload_json, 'sha256'), 'hex');
  insert into public.dsg_audit_events(sequence, previous_hash, event_hash, proof_hash, payload)
    values (v_sequence, v_previous_hash, v_event_hash, lower(p_proof_hash), v_payload);
  update public.dsg_audit_head
    set sequence = v_sequence, event_hash = v_event_hash, updated_at = now()
    where id = true;
  return jsonb_build_object('sequence', v_sequence, 'previous_hash', v_previous_hash, 'event_hash', v_event_hash);
end;
$$;

create or replace function public.dsg_get_audit_event(p_event_hash text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'sequence', sequence, 'created_at', created_at, 'previous_hash', previous_hash,
    'event_hash', event_hash, 'proof_hash', proof_hash, 'payload', payload
  ) from public.dsg_audit_events where event_hash = lower(p_event_hash) limit 1;
$$;

revoke all on function public.dsg_append_audit_event(text, text) from public, anon, authenticated;
revoke all on function public.dsg_get_audit_event(text) from public, anon, authenticated;
grant execute on function public.dsg_append_audit_event(text, text) to service_role;
grant execute on function public.dsg_get_audit_event(text) to service_role;
