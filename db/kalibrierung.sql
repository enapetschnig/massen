-- =============================================================================
-- Selbst-Kalibrierung (MOAT) + Super-Admin — Schema-Erweiterung
-- In Supabase SQL-Editor ausführen. Idempotent (IF NOT EXISTS / on conflict).
-- =============================================================================

-- 1) Gelernte Korrektur-Faktoren. firma_id = NULL → globale Basis (e-power).
--    Auflösung in der App: User-Override > Firma > Global > Default.
create table if not exists kalibrierungen (
    id uuid primary key default gen_random_uuid(),
    firma_id uuid references firmen(id) on delete cascade,   -- NULL = global
    faktor_key text not null,
    wert real not null,
    n_belege integer default 0,
    ratio_median real,
    stand timestamptz default now()
);

-- ein Faktor pro Firma (bzw. genau einer global) — ermöglicht sauberes Neu-Lernen.
create unique index if not exists uq_kalibrierung_firma_faktor
    on kalibrierungen (coalesce(firma_id, '00000000-0000-0000-0000-000000000000'::uuid), faktor_key);

create index if not exists idx_kalibrierung_firma on kalibrierungen(firma_id);

-- 2) Hochgeladene Polier-Soll-Listen + die daraus berechneten Belege (ratios je
--    Faktor). Aus ALLEN Listen einer Firma werden die Faktoren gelernt (≥2 Belege).
create table if not exists soll_listen (
    id uuid primary key default gen_random_uuid(),
    firma_id uuid not null references firmen(id) on delete cascade,
    projekt_id uuid references projekte(id) on delete set null,
    rohtext text,
    positionen integer default 0,
    belege jsonb default '[]'::jsonb,    -- [{faktor, ratio, ist, soll}]
    erstellt_am timestamptz default now()
);

create index if not exists idx_soll_listen_firma on soll_listen(firma_id);

-- 3) Account-Sperre für den Super-Admin (e-power steuert, wer das Produkt nutzt).
alter table firmen add column if not exists gesperrt boolean default false;

-- 4) Admin-Token für die /api/admin/*-Endpunkte (Server prüft dagegen).
--    Setze einen sicheren Wert; die normale Firma-Auth läuft client-seitig.
insert into app_config (key, value)
values ('ADMIN_TOKEN', 'BITTE-SICHEREN-WERT-SETZEN')
on conflict (key) do nothing;

-- Hinweis: Service-Role (Backend) umgeht RLS. Falls direkter Client-Zugriff auf
-- kalibrierungen/soll_listen nötig wird, hier RLS-Policies ergänzen.
