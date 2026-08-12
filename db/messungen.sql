-- =============================================================================
-- AUFMASS-WERKZEUG (Umbau nach docs/UMBAU_DIGIPLAN.md, Etappe E1)
-- In Supabase SQL-Editor ausführen. Idempotent (IF NOT EXISTS).
--
-- WARUM DIESE TABELLEN: Bis heute gab es keine MESSUNG als Objekt. Es gab nur
-- `elemente` (die KI-Lesung) und `LVPosition` (im Speicher berechnet, nie
-- gespeichert). Damit konnte der Nutzer nichts messen, was die KI nicht
-- erkannt hat — genau das ist der Unterschied zu einem echten Aufmaß-Werkzeug.
-- Ab hier ist jede Menge ein gespeichertes, prüfbares, klickbares Objekt.
-- =============================================================================

-- 1) POSITIONEN — das Leistungsverzeichnis des Projekts (oder eine Firmen-
--    Vorlage, wenn projekt_id NULL ist).
create table if not exists positionen (
    id uuid primary key default gen_random_uuid(),
    projekt_id uuid references projekte(id) on delete cascade,  -- NULL = Vorlage
    firma_id uuid references firmen(id) on delete cascade,
    nr text not null,                       -- "1.2"
    bezeichnung text not null,              -- "Zementestrich 5 cm"
    langtext text,
    einheit text not null default 'm2',     -- m2 | m3 | m | stk | kg | psch
    lg text,                                -- Leistungsgruppe, z.B. "11"
    regel_id text,                          -- -> massen_logic.AUFMASS_REGELN
    verschnitt_pct real default 0,
    quelle text default 'eigen',            -- eigen | onlv_import | katalog | ki
    sort integer default 0,
    erstellt_am timestamptz default now()
);
create index if not exists ix_positionen_projekt on positionen (projekt_id);
create index if not exists ix_positionen_vorlage on positionen (firma_id)
    where projekt_id is null;

-- 2) MESSUNGEN — das Herzstück. Eine Zeile = eine Messung am Plan.
--    Die GEOMETRIE ist die Wahrheit: daraus folgen Wert und Formel, und
--    daraus wird der Aufmaßplan gezeichnet. Nichts wird "nur gerechnet".
create table if not exists messungen (
    id uuid primary key default gen_random_uuid(),
    projekt_id uuid not null references projekte(id) on delete cascade,
    plan_id uuid references plaene(id) on delete cascade,
    seite integer default 0,

    typ text not null,                      -- flaeche|laenge|stueck|volumen|abzug|bauteil
    nummer integer,                         -- M1, M2 … Referenz im Protokoll
    bezeichnung text,
    -- Punkte in PLAN-Koordinaten (pt), nicht in Bildpixeln: bleibt gültig,
    -- wenn das Vorschaubild in anderer Auflösung gerendert wird.
    geometrie jsonb not null,               -- {form, punkte:[[x,y]…], meta:{}}
    formel text,                            -- "5,84 × 4,77 − 1,20 × 0,90"
    wert real,
    einheit text,

    position_id uuid references positionen(id) on delete set null,
    -- Abzug hängt an seiner Fläche: löscht man die Fläche, geht der Abzug mit.
    parent_id uuid references messungen(id) on delete cascade,

    quelle text default 'mensch',           -- ki | ki_bestaetigt | mensch
    status text default 'aktiv',            -- vorschlag | aktiv | verworfen
    raum_ref text,                          -- Raum-Anker für die Kreuztabelle
    notiz text,
    erstellt_am timestamptz default now(),
    geaendert_am timestamptz default now()
);
create index if not exists ix_messungen_projekt on messungen (projekt_id);
create index if not exists ix_messungen_plan on messungen (plan_id, seite);
create index if not exists ix_messungen_position on messungen (position_id);
create index if not exists ix_messungen_parent on messungen (parent_id);

-- 3) Fortlaufende Nummer je Projekt (M1, M2 …) — der Mensch referenziert
--    Messungen über diese Nummer, nicht über die UUID.
create or replace function messung_naechste_nummer(p_projekt uuid)
returns integer language sql stable as $$
    select coalesce(max(nummer), 0) + 1 from messungen where projekt_id = p_projekt;
$$;

-- 4) geaendert_am automatisch mitführen.
create or replace function messung_touch() returns trigger language plpgsql as $$
begin
    new.geaendert_am := now();
    return new;
end $$;
drop trigger if exists tr_messung_touch on messungen;
create trigger tr_messung_touch before update on messungen
    for each row execute function messung_touch();
