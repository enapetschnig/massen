import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    const { masse_id, feld, alter_wert, neuer_wert, firma_id } = await req.json()
    if (!masse_id || !feld || !firma_id) {
      throw new Error("masse_id, feld und firma_id sind Pflichtfelder")
    }

    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    // ------------------------------------------------------------------
    // 1. Resolve planbuero from masse -> plan -> planbuero
    // ------------------------------------------------------------------

    const { data: masse, error: masseErr } = await sb
      .from("massen")
      .select("plan_id")
      .eq("id", masse_id)
      .single()
    if (masseErr || !masse) throw new Error("Masse nicht gefunden: " + (masseErr?.message || masse_id))

    const { data: plan, error: planErr } = await sb
      .from("plaene")
      .select("planungsbuero")
      .eq("id", masse.plan_id)
      .single()
    if (planErr || !plan) throw new Error("Plan nicht gefunden: " + (planErr?.message || masse.plan_id))

    const planbuero = plan.planungsbuero || "unbekannt"

    // ------------------------------------------------------------------
    // 2. Store the correction in korrekturen table
    // ------------------------------------------------------------------

    const { error: insertErr } = await sb.from("korrekturen").insert({
      firma_id,
      masse_id,
      planbuero,
      feld,
      original_wert: alter_wert,
      korrektur_wert: neuer_wert,
      in_lernregel_umgewandelt: false,
    })
    if (insertErr) throw new Error("Korrektur speichern fehlgeschlagen: " + insertErr.message)

    // ------------------------------------------------------------------
    // 3. Load all corrections for this firma_id
    // ------------------------------------------------------------------

    const { data: korrekturen, error: korrErr } = await sb
      .from("korrekturen")
      .select("*")
      .eq("firma_id", firma_id)
      .eq("in_lernregel_umgewandelt", false)
    if (korrErr) throw new Error("Korrekturen laden fehlgeschlagen: " + korrErr.message)

    // ------------------------------------------------------------------
    // 4. Detect patterns: group by planbuero + feld, count occurrences
    // ------------------------------------------------------------------

    const groups: Record<string, typeof korrekturen> = {}
    for (const k of korrekturen || []) {
      const key = `${k.planbuero}::${k.feld}`
      if (!groups[key]) groups[key] = []
      groups[key].push(k)
    }

    let neueRegel = false
    let patternDesc = "Keine neuen Muster erkannt"

    for (const [key, items] of Object.entries(groups)) {
      if (items.length <= 2) continue

      const [groupPlanbuero, groupFeld] = key.split("::")

      // Check if a rule for this combination already exists
      const { data: existing } = await sb
        .from("lernregeln")
        .select("id, bestaetigt")
        .eq("firma_id", firma_id)
        .eq("planbuero", groupPlanbuero)
        .eq("gueltig_fuer", groupFeld)
        .eq("aktiv", true)
        .single()

      if (existing) {
        // Update confirmation count
        await sb
          .from("lernregeln")
          .update({ bestaetigt: existing.bestaetigt + 1 })
          .eq("id", existing.id)
        continue
      }

      // Analyze the correction pattern
      const korrekturen_sample = items.map((i) => ({
        original: i.original_wert,
        korrektur: i.korrektur_wert,
      }))

      const beschreibung =
        `Planbuero "${groupPlanbuero}" – Feld "${groupFeld}" wird systematisch korrigiert ` +
        `(${items.length} Korrekturen). Beispiel: ${items[0].original_wert} -> ${items[0].korrektur_wert}`

      // ------------------------------------------------------------------
      // 5. Create learning rule
      // ------------------------------------------------------------------

      const { error: regelErr } = await sb.from("lernregeln").insert({
        firma_id,
        planbuero: groupPlanbuero,
        gueltig_fuer: groupFeld,
        agent: "lern-agent",
        beschreibung,
        korrektur_json: {
          typ: "systematische_korrektur",
          feld: groupFeld,
          anzahl_korrekturen: items.length,
          beispiele: korrekturen_sample.slice(0, 5),
        },
        bestaetigt: items.length,
        aktiv: true,
      })
      if (regelErr) throw new Error("Lernregel erstellen fehlgeschlagen: " + regelErr.message)

      // Mark corrections as converted to rule
      const ids = items.map((i) => i.id)
      await sb
        .from("korrekturen")
        .update({ in_lernregel_umgewandelt: true })
        .in("id", ids)

      neueRegel = true
      patternDesc = beschreibung
    }

    // ------------------------------------------------------------------
    // Return result
    // ------------------------------------------------------------------

    return new Response(
      JSON.stringify({
        status: "ok",
        neue_regel: neueRegel,
        pattern: patternDesc,
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
