import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

/** Format a number for German Excel: comma as decimal separator */
function fmtNum(val: number | null | undefined, decimals = 2): string {
  if (val === null || val === undefined) return ""
  return val.toFixed(decimals).replace(".", ",")
}

/** Escape a CSV field: wrap in quotes if it contains semicolons, quotes, or newlines */
function esc(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return ""
  const s = String(val)
  if (s.includes(";") || s.includes('"') || s.includes("\n")) {
    return '"' + s.replace(/"/g, '""') + '"'
  }
  return s
}

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
    // 1. Load plan
    // ------------------------------------------------------------------

    const { data: plan, error: planErr } = await sb
      .from("plaene")
      .select("*")
      .eq("id", plan_id)
      .single()
    if (planErr || !plan) throw new Error("Plan nicht gefunden: " + (planErr?.message || plan_id))

    // ------------------------------------------------------------------
    // 2. Load elemente for this plan
    // ------------------------------------------------------------------

    const { data: elemente, error: elemErr } = await sb
      .from("elemente")
      .select("*")
      .eq("plan_id", plan_id)
    if (elemErr) throw new Error("Elemente laden fehlgeschlagen: " + elemErr.message)

    const raeume = (elemente || []).filter((e: any) => e.typ === "raum")
    const fenster = (elemente || []).filter((e: any) => e.typ === "fenster")

    // ------------------------------------------------------------------
    // 3. Load massen for this plan
    // ------------------------------------------------------------------

    const { data: massen, error: massenErr } = await sb
      .from("massen")
      .select("*")
      .eq("plan_id", plan_id)
      .order("pos_nr", { ascending: true })
    if (massenErr) throw new Error("Massen laden fehlgeschlagen: " + massenErr.message)

    // ------------------------------------------------------------------
    // 4. Build CSV
    // ------------------------------------------------------------------

    const lines: string[] = []

    // UTF-8 BOM is prepended to the final output, not as a CSV line

    // Plan header info
    const planName = plan.dateiname || plan.name || "Plan"
    const geschoss = plan.agent_log?.step1_parser?.result?.geschoss || ""
    const massstab = plan.agent_log?.step1_parser?.result?.massstab || ""
    lines.push(`Plan;${esc(planName)}`)
    if (geschoss) lines.push(`Geschoss;${esc(geschoss)}`)
    if (massstab) lines.push(`Massstab;${esc(massstab)}`)
    lines.push("")

    // ---- Section 1: MASSENERMITTLUNG ----
    lines.push("MASSENERMITTLUNG")
    lines.push("Pos;Beschreibung;Gewerk;Raum;Berechnung;Endsumme;Einheit;Konfidenz")

    for (const m of massen || []) {
      const berechnung = Array.isArray(m.berechnung)
        ? m.berechnung.join(" | ")
        : String(m.berechnung || "")
      lines.push([
        esc(m.pos_nr),
        esc(m.beschreibung),
        esc(m.gewerk),
        esc(m.raum_referenz),
        esc(berechnung),
        fmtNum(m.endsumme),
        esc(m.einheit),
        fmtNum(m.konfidenz, 0),
      ].join(";"))
    }

    lines.push("")

    // ---- Section 2: RAEUME ----
    lines.push("RAEUME")
    lines.push("Nr;Name;Bodenbelag;Flaeche m2;Umfang m;Hoehe m;Wandflaeche m2;Konfidenz")

    raeume.forEach((r: any, idx: number) => {
      const d = r.daten || {}
      lines.push([
        String(idx + 1),
        esc(d.name || r.bezeichnung || ""),
        esc(d.bodenbelag || ""),
        fmtNum(d.flaeche_m2),
        fmtNum(d.umfang_m),
        fmtNum(d.hoehe_m),
        fmtNum(d.wandflaeche_m2),
        fmtNum(r.konfidenz, 0),
      ].join(";"))
    })

    lines.push("")

    // ---- Section 3: FENSTER ----
    lines.push("FENSTER")
    lines.push("Nr;Bezeichnung;Raum;AL Breite mm;AL Hoehe mm;RB Breite mm;RB Hoehe mm;Flaeche m2;Konfidenz")

    fenster.forEach((f: any, idx: number) => {
      const d = f.daten || {}
      lines.push([
        String(idx + 1),
        esc(d.bezeichnung || f.bezeichnung || ""),
        esc(d.raum || ""),
        fmtNum(d.al_breite_mm, 0),
        fmtNum(d.al_hoehe_mm, 0),
        fmtNum(d.rb_breite_mm, 0),
        fmtNum(d.rb_hoehe_mm, 0),
        fmtNum(d.flaeche_m2),
        fmtNum(f.konfidenz, 0),
      ].join(";"))
    })

    lines.push("")

    // ---- Section 4: ZUSAMMENFASSUNG ----
    lines.push("ZUSAMMENFASSUNG")
    lines.push("Gewerk;Endsumme;Einheit")

    // Group massen by gewerk and sum endsumme
    const gewerkSums: Record<string, { summe: number; einheit: string }> = {}
    for (const m of massen || []) {
      const gw = m.gewerk || "Sonstiges"
      if (!gewerkSums[gw]) gewerkSums[gw] = { summe: 0, einheit: m.einheit || "" }
      gewerkSums[gw].summe += m.endsumme || 0
    }

    for (const [gewerk, info] of Object.entries(gewerkSums).sort((a, b) => a[0].localeCompare(b[0]))) {
      lines.push([
        esc(gewerk),
        fmtNum(info.summe),
        esc(info.einheit),
      ].join(";"))
    }

    // ------------------------------------------------------------------
    // 5. Return CSV with BOM and download headers
    // ------------------------------------------------------------------

    const csvContent = "\uFEFF" + lines.join("\r\n") + "\r\n"
    const filename = `Massenermittlung_${planName.replace(/[^a-zA-Z0-9_\-]/g, "_")}.csv`

    return new Response(csvContent, {
      headers: {
        ...corsHeaders,
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    })
  } catch (err: any) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    )
  }
})
