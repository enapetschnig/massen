import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

const MODEL = "claude-sonnet-4-20250514"
const ANTHROPIC_VERSION = "2023-06-01"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseJsonResponse(raw: string): any {
  // Try direct parse first
  try { return JSON.parse(raw) } catch { /* fallback */ }
  // Regex: find outermost { ... }
  const m = raw.match(/\{[\s\S]*\}/)
  if (m) {
    try { return JSON.parse(m[0]) } catch { /* fallback */ }
  }
  // Try removing markdown fences
  const stripped = raw.replace(/```(?:json)?\s*/g, "").replace(/```/g, "").trim()
  try { return JSON.parse(stripped) } catch { /* fallback */ }
  const m2 = stripped.match(/\{[\s\S]*\}/)
  if (m2) {
    try { return JSON.parse(m2[0]) } catch { /* give up */ }
  }
  throw new Error("JSON-Parsing fehlgeschlagen: " + raw.substring(0, 200))
}

async function callClaude(
  apiKey: string,
  systemPrompt: string,
  userContent: any[],
  maxTokens = 16384,
): Promise<any> {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": ANTHROPIC_VERSION,
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: maxTokens,
      system: systemPrompt,
      messages: [{ role: "user", content: userContent }],
    }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`Claude API ${res.status}: ${err.substring(0, 400)}`)
  }
  const claude = await res.json()
  const text = claude.content?.[0]?.text || "{}"
  return parseJsonResponse(text)
}

async function updateAgentLog(
  sb: any,
  planId: string,
  stepName: string,
  stepResult: any,
) {
  // Read current log, append step
  const { data: plan } = await sb
    .from("plaene")
    .select("agent_log")
    .eq("id", planId)
    .single()
  const log = plan?.agent_log || {}
  log[stepName] = { timestamp: new Date().toISOString(), result: stepResult }
  await sb.from("plaene").update({ agent_log: log }).eq("id", planId)
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    const { plan_id } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    // ------------------------------------------------------------------
    // 1. Load plan & API key, create signed URL
    // ------------------------------------------------------------------

    const { data: cfg, error: cfgErr } = await sb
      .from("app_config")
      .select("value")
      .eq("key", "ANTHROPIC_API_KEY")
      .single()
    if (cfgErr || !cfg?.value) throw new Error("ANTHROPIC_API_KEY nicht konfiguriert")
    const apiKey = cfg.value

    const { data: plan, error: planErr } = await sb
      .from("plaene")
      .select("*")
      .eq("id", plan_id)
      .single()
    if (planErr || !plan) throw new Error("Plan nicht gefunden: " + (planErr?.message || plan_id))

    const { data: urlData, error: urlErr } = await sb.storage
      .from("plaene")
      .createSignedUrl(plan.storage_path, 3600)
    if (urlErr || !urlData?.signedUrl)
      throw new Error("Signed URL fehlgeschlagen: " + (urlErr?.message || "unbekannt"))

    const signedUrl = urlData.signedUrl

    // ------------------------------------------------------------------
    // 2. Delete existing results for re-analysis
    // ------------------------------------------------------------------

    await sb.from("massen").delete().eq("plan_id", plan_id)
    await sb.from("elemente").delete().eq("plan_id", plan_id)

    // Init agent_log
    await sb.from("plaene").update({
      verarbeitet: false,
      agent_log: { gestartet: new Date().toISOString() },
    }).eq("id", plan_id)

    // ==================================================================
    // STEP 1 – PARSER (Vision)
    // ==================================================================

    const step1System = `Du bist der erfahrenste Bautechniker Österreichs mit 30 Jahren Praxis im Hochbau.
Du analysierst Baupläne mit absoluter Präzision. Deine Aufgabe: JEDES Detail aus dem Plan extrahieren.

RÄUME ZÄHLEN:
- Zähle JEDEN Raum im Plan. Übliche österreichische Wohnungen haben: Vorraum/Flur, Wohnzimmer/Wohnküche, Schlafzimmer, Kinderzimmer, Bad, WC, Abstellraum, Terrasse/Loggia/Balkon. Wenn du weniger als 5 Räume findest, schau NOCHMAL genauer hin.
- Auch Nebenräume wie Abstellkammer, Technikraum, Speis, Schrankraum zählen als eigener Raum.
- Terrassen, Loggien und Balkone IMMER als eigenen Raum erfassen (mit Bodenbelag "Fliesen" oder "Betonplatten").

FENSTER UND TEXT LESEN:
- Fenster stehen oft ROTIERT an den Wänden. Lies auch senkrechten/schrägen Text.
- Fensterbeschriftungen können entlang der Wand geschrieben sein – drehe den Plan gedanklich, um sie zu lesen.
- Fensternotation: FE_[Nr] / RPH [mm] / FPH [mm] / AL[Breite] / AL[Höhe] / RB[Breite] / RB[Höhe]
- Wenn ein Wert < 30: wahrscheinlich in cm angegeben → mit 10 multiplizieren für mm
- Häufige Fehllesungen vermeiden: "1510" ist NICHT "1310", "2100" ist NICHT "2700", "480" ist NICHT "430". Lies jede Ziffer einzeln.

MAßE AN WÄNDEN:
- Maße an Wänden: Lies die Maßketten entlang der Wände. Format: Einzelmaße und Gesamtmaße.
- Außenmaße stehen oft AUSSERHALB des Grundrisses in einer eigenen Maßkette.
- Innenmaße stehen innerhalb oder direkt an den Wänden.
- Wandstärken sind die kleinen Zahlen ZWISCHEN zwei Maßlinien (z.B. 20, 25, 30 = cm, oder 200, 250, 300 = mm).

PLANKOPF:
- Im Plankopf (meist rechts unten) steht: Maßstab, Geschoss, Planungsbüro, Planbezeichnung.
- Maßstab beachten: 1:50, 1:100 etc. – beeinflusst wie Maße zu interpretieren sind.

HÖHENANGABEN:
- Höhenangaben stehen manchmal nur EINMAL im Plan und gelten für alle Räume des Geschosses.
- Typische Raumhöhen: Rohbau 2.60-2.80m, lichte Höhe 2.50-2.60m.
- Suche nach Schnittdarstellungen oder Höhenkoten (z.B. +2,60 OKFFB).

TÜREN:
- Türen erkennt man am Viertelkreis-Symbol (Türblatt-Schwenkbereich).
- Eingangstüren sind breiter (90-100cm), Zimmertüren 70-90cm, WC/Bad-Türen 60-80cm.
- Schiebetüren haben ein anderes Symbol (gestrichelte Linie in der Wand).

Wandfläche = Umfang × Raumhöhe

Antworte AUSSCHLIESSLICH mit validem JSON, KEIN Markdown, KEINE Erklärungen.`

    const step1User = [
      {
        type: "document",
        source: { type: "url", url: signedUrl },
      },
      {
        type: "text",
        text: `Analysiere diesen Bauplan VOLLSTÄNDIG und extrahiere ALLE Informationen.

Liefere folgendes JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "planungsbuero": "",
  "wandstaerken_mm": [300, 200],
  "raeume": [
    {
      "name": "Wohnzimmer",
      "bodenbelag": "Parkett",
      "flaeche_m2": 25.5,
      "umfang_m": 20.2,
      "hoehe_m": 2.6,
      "wandflaeche_m2": 52.52,
      "konfidenz": 0.9
    }
  ],
  "fenster": [
    {
      "bezeichnung": "FE_01",
      "raum": "Wohnzimmer",
      "rph_mm": 1010,
      "fph_mm": 480,
      "al_breite_mm": 1510,
      "al_hoehe_mm": 1510,
      "rb_breite_mm": 1760,
      "rb_hoehe_mm": 1760,
      "flaeche_m2": 2.28,
      "konfidenz": 0.85
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnzimmer",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Zimmertür",
      "konfidenz": 0.85
    }
  ],
  "gesamt_konfidenz": 0.85
}

WICHTIG:
- JEDEN Raum erfassen, auch Flur, Abstellraum, WC
- JEDES Fenster mit ALLEN Parametern (RPH, FPH, AL, RB)
- JEDE Tür mit Breite und Höhe
- Alle Wandstärken notieren
- NUR valides JSON zurückgeben`,
      },
    ]

    const step1Result = await callClaude(apiKey, step1System, step1User)
    await updateAgentLog(sb, plan_id, "step1_parser", step1Result)

    // ==================================================================
    // STEP 2 – GEOMETRIE (Verification & Enrichment)
    // ==================================================================

    const step2System = `Du bist ein Experte für Baugeometrie und Plausibilitätsprüfung österreichischer Baupläne.
Du erhältst die Rohdaten einer Plananalyse und verfeinerst sie.

Deine Aufgaben:
1. Plausibilität prüfen: Sind Raumflächen realistisch? Stimmen Umfang und Fläche zusammen?
2. Fehlende Werte berechnen: Wandflächen = Umfang × Höhe, Fensterflächen = AL_Breite × AL_Höhe / 1.000.000
3. Fenster und Türen den richtigen Räumen zuordnen (falls nicht geschehen)
4. Bei Fenstern prüfen: RB muss GRÖSSER als AL sein (RB = Rohbaumaß, AL = Architekturlichtmaß)
5. Unstimmigkeiten markieren

Antworte AUSSCHLIESSLICH mit validem JSON, KEIN Markdown.`

    const step2User = [
      {
        type: "text",
        text: `Hier sind die Rohdaten aus der Plananalyse. Prüfe und verfeinere sie.

ROHDATEN:
${JSON.stringify(step1Result, null, 2)}

Liefere das verfeinerte JSON im GLEICHEN Format zurück, ergänzt um:
{
  ...alle bisherigen Felder...,
  "korrekturen": [
    { "feld": "raum.Wohnzimmer.wandflaeche_m2", "alt": 0, "neu": 52.52, "grund": "Berechnet aus Umfang × Höhe" }
  ],
  "warnungen": ["RB < AL bei FE_03 – bitte Plan prüfen"],
  "gesamt_konfidenz": 0.88
}`,
      },
    ]

    const step2Result = await callClaude(apiKey, step2System, step2User)
    await updateAgentLog(sb, plan_id, "step2_geometrie", step2Result)

    // ==================================================================
    // STEP 3 – KALKULATION (ÖNORM-Massenermittlung)
    // ==================================================================

    const step3System = `Du bist ein erfahrener österreichischer Baukalkulator, spezialisiert auf Massenermittlung nach ÖNORM.
Du berechnest Bauleistungen präzise nach österreichischen Normen und Richtlinien.

REGELN FÜR ABZÜGE:

MAUERWERK (m³):
- Wandfläche × Wandstärke = Brutto-Volumen
- Öffnungen < 0,5 m²: KEIN Abzug
- Öffnungen 0,5–3,0 m²: HALBER Abzug (50%)
- Öffnungen > 3,0 m²: VOLLER Abzug (100%)

INNENPUTZ (m²):
- Wandfläche + Leibungsflächen
- Leibung Seiten = 2 × (Wandstärke × Öffnungshöhe)
- Leibung Sturz = Wandstärke × Öffnungsbreite
- Abzüge Öffnungen: < 2,5 m² kein Abzug, 2,5–10 m² halber Abzug, > 10 m² voller Abzug

MALERARBEITEN (m²):
- Gleiche Regeln wie Innenputz

BODENBELAG (m²):
- Raumfläche nach Bodenbelagstyp gruppiert

ESTRICH (m²):
- Alle Raumflächen

FENSTERBÄNKE (lfm):
- Laufmeter = Fensterbreite (RB) in Metern

Antworte AUSSCHLIESSLICH mit validem JSON, KEIN Markdown.`

    const step3User = [
      {
        type: "text",
        text: `Berechne die Massenermittlung für folgende Plandaten:

RÄUME, FENSTER, TÜREN:
${JSON.stringify(step2Result, null, 2)}

Liefere folgendes JSON-Format:
{
  "positionen": [
    {
      "pos_nr": "01.01",
      "beschreibung": "Mauerwerk Außenwand 30cm – Wohnzimmer",
      "gewerk": "Mauerwerk",
      "raum_referenz": "Wohnzimmer",
      "berechnung": [
        "Wandfläche brutto: 20.2m × 2.6m = 52.52 m²",
        "Abzug FE_01 (2.28 m², halber Abzug): -1.14 m²",
        "Abzug T1 (1.89 m², halber Abzug): -0.945 m²",
        "Wandfläche netto: 50.435 m²",
        "Volumen: 50.435 m² × 0.30 m = 15.13 m³"
      ],
      "endsumme": 15.13,
      "einheit": "m³",
      "konfidenz": 0.9
    }
  ],
  "zusammenfassung": {
    "mauerwerk_m3": 45.5,
    "innenputz_m2": 230.0,
    "malerarbeiten_m2": 230.0,
    "bodenbelag_m2": { "Parkett": 50.0, "Fliesen": 20.0 },
    "estrich_m2": 70.0,
    "fensterbaenke_lfm": 12.5
  },
  "gesamt_konfidenz": 0.88
}

WICHTIG:
- Erstelle Positionen für JEDEN Raum und JEDES Gewerk. Ein Raum mit 4 Wänden, 2 Fenstern und 1 Tür braucht mindestens: Mauerwerk, Innenputz (mit Leibungen), Malerarbeiten (mit Leibungen), Bodenbelag, Estrich.
- Position-Nummern systematisch: 01.xx = Mauerwerk, 02.xx = Putz, 03.xx = Maler, 04.xx = Boden, 05.xx = Estrich, 06.xx = Fensterbänke
- Leibungsberechnung IMMER ausweisen: Seiten = 2 × Wandstärke × Öffnungshöhe, Sturz = Wandstärke × Öffnungsbreite
- JEDE Position mit nachvollziehbaren Berechnungsschritten
- Abzugsregeln STRIKT einhalten
- Leibungen bei Putz und Malerarbeiten berücksichtigen
- Jeder Raum muss Positionen haben`,
      },
    ]

    const step3Result = await callClaude(apiKey, step3System, step3User, 32000)
    await updateAgentLog(sb, plan_id, "step3_kalkulation", step3Result)

    // ==================================================================
    // STEP 4 – KRITIK (Quality Check)
    // ==================================================================

    const step4System = `Du bist ein unabhängiger Prüfingenieur für Massenermittlungen im österreichischen Hochbau.
Deine Aufgabe ist die kritische Qualitätsprüfung aller Ergebnisse.

Prüfe:
1. Sind Raumgrößen realistisch? (Wohnräume 15-40m², Bad 5-15m², WC 2-5m², Flur 5-15m²)
2. Stimmen die Berechnungen rechnerisch? (Wandfläche = U×H, Volumen = Fläche×Dicke)
3. Wurden ALLE Räume, Fenster, Türen erfasst?
4. Sind die Abzugsregeln korrekt angewendet?
5. Sind die Einheiten korrekt?
6. Fehlen Positionen? (Jeder Raum braucht mindestens: Mauerwerk, Putz, Maler, Boden, Estrich)
7. Sind Konfidenzwerte plausibel?

Antworte AUSSCHLIESSLICH mit validem JSON, KEIN Markdown.`

    const step4User = [
      {
        type: "text",
        text: `Prüfe die gesamte Analyse und Massenermittlung:

SCHRITT 1 – PARSER-ERGEBNIS:
${JSON.stringify(step1Result, null, 2)}

SCHRITT 2 – GEOMETRIE-ERGEBNIS:
${JSON.stringify(step2Result, null, 2)}

SCHRITT 3 – KALKULATION-ERGEBNIS:
${JSON.stringify(step3Result, null, 2)}

Liefere folgendes JSON-Format:
{
  "status": "AKZEPTIERT",
  "qualitaets_score": 85,
  "pruefungen": [
    {
      "kategorie": "Raumgrößen",
      "status": "OK",
      "details": "Alle Raumgrößen im plausiblen Bereich"
    },
    {
      "kategorie": "Berechnungen",
      "status": "WARNUNG",
      "details": "Mauerwerk Flur: Wandfläche weicht um 3% ab"
    }
  ],
  "fehler": [],
  "warnungen": ["Kleine Abweichung bei Flur-Wandfläche"],
  "empfehlungen": ["Wandstärke Flur nochmals am Plan prüfen"],
  "gesamt_konfidenz": 0.87
}

STATUS-WERTE:
- AKZEPTIERT: Score >= 75, keine kritischen Fehler
- NACHBESSERUNG: Score 50-74, behebbare Probleme
- KRITISCH: Score < 50, grundlegende Fehler`,
      },
    ]

    const step4Result = await callClaude(apiKey, step4System, step4User)
    await updateAgentLog(sb, plan_id, "step4_kritik", step4Result)

    // ==================================================================
    // STEP 5 – VERIFICATION (Re-check PDF for missed elements)
    // ==================================================================

    const raeumeCount = (step2Result.raeume || []).length
    const fensterCount = (step2Result.fenster || []).length
    const tuerenCount = (step2Result.tueren || []).length

    const step5System = `Du bist ein unabhängiger Prüfer für Bauplan-Analysen. Du erhältst einen Bauplan und die bisherigen Analyseergebnisse.
Deine EINZIGE Aufgabe: Finde ÜBERSEHENE Elemente (Räume, Fenster, Türen), die in der bisherigen Analyse FEHLEN.

Antworte AUSSCHLIESSLICH mit validem JSON, KEIN Markdown, KEINE Erklärungen.`

    const step5User = [
      {
        type: "document",
        source: { type: "url", url: signedUrl },
      },
      {
        type: "text",
        text: `Hier ist der Plan nochmals. Die bisherige Analyse hat ${raeumeCount} Räume, ${fensterCount} Fenster, ${tuerenCount} Türen gefunden.

Bisherige Räume: ${(step2Result.raeume || []).map((r: any) => r.name).join(", ")}
Bisherige Fenster: ${(step2Result.fenster || []).map((f: any) => f.bezeichnung).join(", ")}
Bisherige Türen: ${(step2Result.tueren || []).map((t: any) => t.bezeichnung).join(", ")}

Prüfe ob Räume/Fenster/Türen ÜBERSEHEN wurden. Schau besonders auf:
- kleine Räume (WC, Abstellraum, Speis, Schrankraum, Technikraum)
- Fenster in Nebenräumen (Bad, WC, Abstellraum)
- Türen zwischen Räumen (auch Schiebetüren)
- Terrassen, Loggien, Balkone

Liste NUR die FEHLENDEN Elemente auf. Wenn nichts fehlt, gib leere Arrays zurück.

JSON-Format:
{
  "fehlende_raeume": [
    {
      "name": "Abstellraum",
      "bodenbelag": "Fliesen",
      "flaeche_m2": 3.5,
      "umfang_m": 7.6,
      "hoehe_m": 2.6,
      "wandflaeche_m2": 19.76,
      "konfidenz": 0.7
    }
  ],
  "fehlende_fenster": [
    {
      "bezeichnung": "FE_05",
      "raum": "WC",
      "rph_mm": 0,
      "fph_mm": 0,
      "al_breite_mm": 600,
      "al_hoehe_mm": 600,
      "rb_breite_mm": 850,
      "rb_hoehe_mm": 850,
      "flaeche_m2": 0.36,
      "konfidenz": 0.6
    }
  ],
  "fehlende_tueren": [
    {
      "bezeichnung": "T6",
      "raum": "Abstellraum",
      "breite_mm": 700,
      "hoehe_mm": 2100,
      "typ": "Zimmertür",
      "konfidenz": 0.6
    }
  ],
  "kommentar": "WC-Fenster und Abstellraum-Tür waren im Plan schwer lesbar."
}`,
      },
    ]

    const step5Result = await callClaude(apiKey, step5System, step5User, 16384)
    await updateAgentLog(sb, plan_id, "step5_verification", step5Result)

    // Merge newly found elements into step2Result
    if (step5Result.fehlende_raeume?.length) {
      step2Result.raeume = [...(step2Result.raeume || []), ...step5Result.fehlende_raeume]
    }
    if (step5Result.fehlende_fenster?.length) {
      step2Result.fenster = [...(step2Result.fenster || []), ...step5Result.fehlende_fenster]
    }
    if (step5Result.fehlende_tueren?.length) {
      step2Result.tueren = [...(step2Result.tueren || []), ...step5Result.fehlende_tueren]
    }

    // ==================================================================
    // Store results in database
    // ==================================================================

    // Store rooms
    for (const r of (step2Result.raeume || [])) {
      await sb.from("elemente").insert({
        plan_id,
        typ: "raum",
        bezeichnung: r.name || "",
        daten: r,
        konfidenz: Math.round((r.konfidenz || 0.5) * 100),
      })
    }

    // Store windows
    for (const f of (step2Result.fenster || [])) {
      await sb.from("elemente").insert({
        plan_id,
        typ: "fenster",
        bezeichnung: f.bezeichnung || "",
        daten: f,
        konfidenz: Math.round((f.konfidenz || 0.5) * 100),
      })
    }

    // Store doors
    for (const t of (step2Result.tueren || [])) {
      await sb.from("elemente").insert({
        plan_id,
        typ: "tuer",
        bezeichnung: t.bezeichnung || "",
        daten: t,
        konfidenz: Math.round((t.konfidenz || 0.5) * 100),
      })
    }

    // Store mass calculation positions
    for (const pos of (step3Result.positionen || [])) {
      await sb.from("massen").insert({
        plan_id,
        pos_nr: pos.pos_nr || "",
        beschreibung: pos.beschreibung || "",
        gewerk: pos.gewerk || "",
        raum_referenz: pos.raum_referenz || "",
        berechnung: pos.berechnung || [],
        endsumme: pos.endsumme || 0,
        einheit: pos.einheit || "",
        konfidenz: Math.round((pos.konfidenz || 0.5) * 100),
      })
    }

    // ==================================================================
    // Update plan with final results
    // ==================================================================

    const gesamtKonfidenz = Math.round(
      (step4Result.gesamt_konfidenz || step3Result.gesamt_konfidenz || 0.5) * 100,
    )

    // Build complete agent log
    const { data: currentPlan } = await sb
      .from("plaene")
      .select("agent_log")
      .eq("id", plan_id)
      .single()

    const finalLog = {
      ...(currentPlan?.agent_log || {}),
      abgeschlossen: new Date().toISOString(),
      kritik: step4Result,
      verification: step5Result,
      zusammenfassung: step3Result.zusammenfassung || {},
    }

    await sb.from("plaene").update({
      verarbeitet: true,
      gesamt_konfidenz: gesamtKonfidenz,
      agent_log: finalLog,
    }).eq("id", plan_id)

    // ==================================================================
    // Return summary
    // ==================================================================

    const warnungen = [
      ...(step2Result.warnungen || []),
      ...(step4Result.warnungen || []),
    ]

    return new Response(
      JSON.stringify({
        status: step4Result.status || "AKZEPTIERT",
        raeume: (step2Result.raeume || []).length,
        fenster: (step2Result.fenster || []).length,
        tueren: (step2Result.tueren || []).length,
        massen: (step3Result.positionen || []).length,
        konfidenz: gesamtKonfidenz,
        qualitaets_score: step4Result.qualitaets_score || null,
        warnungen,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    )
  } catch (err: any) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    )
  }
})
