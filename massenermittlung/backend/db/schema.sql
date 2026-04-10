-- =============================================================================
-- KI-Massenermittlung - Supabase Database Schema
-- =============================================================================

-- Enable UUID generation
create extension if not exists "uuid-ossp";

-- =============================================================================
-- FIRMEN (Companies)
-- =============================================================================
create table if not exists firmen (
    id uuid primary key default uuid_generate_v4(),
    name text not null,
    email text unique not null,
    passwort_hash text not null,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index idx_firmen_email on firmen(email);

-- =============================================================================
-- PROJEKTE (Projects)
-- =============================================================================
create table if not exists projekte (
    id uuid primary key default uuid_generate_v4(),
    firma_id uuid not null references firmen(id) on delete cascade,
    name text not null,
    adresse text,
    beschreibung text,
    status text default 'aktiv' check (status in ('aktiv', 'archiviert')),
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index idx_projekte_firma on projekte(firma_id);

-- =============================================================================
-- PLAENE (Plans / PDFs)
-- =============================================================================
create table if not exists plaene (
    id uuid primary key default uuid_generate_v4(),
    projekt_id uuid not null references projekte(id) on delete cascade,
    dateiname text not null,
    storage_path text not null,
    seitenanzahl integer,
    status text default 'hochgeladen'
        check (status in ('hochgeladen', 'wird_analysiert', 'analysiert', 'fehler')),
    analyse_fortschritt integer default 0,
    analyse_log jsonb default '[]'::jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index idx_plaene_projekt on plaene(projekt_id);

-- =============================================================================
-- ELEMENTE (Detected building elements)
-- =============================================================================
create table if not exists elemente (
    id uuid primary key default uuid_generate_v4(),
    plan_id uuid not null references plaene(id) on delete cascade,
    seite integer not null,
    typ text not null,
    bezeichnung text,
    bbox jsonb,
    eigenschaften jsonb default '{}'::jsonb,
    confidence real default 0.0,
    created_at timestamptz default now()
);

create index idx_elemente_plan on elemente(plan_id);
create index idx_elemente_typ on elemente(typ);

-- =============================================================================
-- MASSEN (Calculated quantities)
-- =============================================================================
create table if not exists massen (
    id uuid primary key default uuid_generate_v4(),
    plan_id uuid not null references plaene(id) on delete cascade,
    element_id uuid references elemente(id) on delete set null,
    position_nr text,
    beschreibung text not null,
    einheit text not null,
    menge real not null,
    formel text,
    ki_berechnet boolean default true,
    manuell_korrigiert boolean default false,
    notizen text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index idx_massen_plan on massen(plan_id);
create index idx_massen_element on massen(element_id);

-- =============================================================================
-- LERNREGELN (Learning rules from corrections)
-- =============================================================================
create table if not exists lernregeln (
    id uuid primary key default uuid_generate_v4(),
    firma_id uuid not null references firmen(id) on delete cascade,
    element_typ text not null,
    regel jsonb not null,
    beschreibung text,
    anwendungen integer default 0,
    aktiv boolean default true,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index idx_lernregeln_firma on lernregeln(firma_id);
create index idx_lernregeln_typ on lernregeln(element_typ);

-- =============================================================================
-- KORREKTUREN (User corrections for learning)
-- =============================================================================
create table if not exists korrekturen (
    id uuid primary key default uuid_generate_v4(),
    masse_id uuid not null references massen(id) on delete cascade,
    firma_id uuid not null references firmen(id) on delete cascade,
    alter_wert real not null,
    neuer_wert real not null,
    grund text,
    gelernt boolean default false,
    created_at timestamptz default now()
);

create index idx_korrekturen_masse on korrekturen(masse_id);
create index idx_korrekturen_firma on korrekturen(firma_id);

-- =============================================================================
-- Storage bucket for plan PDFs
-- =============================================================================
insert into storage.buckets (id, name, public)
values ('plaene', 'plaene', false)
on conflict (id) do nothing;

-- RLS policies (enable row-level security)
alter table firmen enable row level security;
alter table projekte enable row level security;
alter table plaene enable row level security;
alter table elemente enable row level security;
alter table massen enable row level security;
alter table lernregeln enable row level security;
alter table korrekturen enable row level security;

-- Service-role bypasses RLS by default, so no additional policies needed
-- for the backend. If direct client access is needed later, add policies here.
