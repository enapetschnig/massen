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
    const { plan_id } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    const sb = createClient(supabaseUrl, supabaseKey)

    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    const apiKey = cfg?.value
    if (!apiKey) throw new Error("API Key nicht konfiguriert")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    const { data: pdfData, error: dlErr } = await sb.storage.from("plaene").download(plan.storage_path)
    if (dlErr) throw new Error("PDF Download: " + dlErr.message)

    const buf = await pdfData.arrayBuffer()
    const bytes = new Uint8Array(buf)
    let binary = ""
    for (let i = 0; i < bytes.length; i++) { binary += String.fromCharCode(bytes[i]) }
    const pdfB64 = btoa(binary)

    const claudeRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: 8192,
        messages: [{
          role: "user",
          content: [
            { type: "document", source: { type: "base64", media_type: "application/pdf", data: pdfB64 } },
            { type: "text", text: "Du bist der beste Bautechniker Österreichs. Analysiere diesen Bauplan vollständig.\n\nExtrahiere ALLES:\n1. Maßstab, Geschoss\n2. RÄUME: Name, Bodenbelag, Fläche m², Umfang m, Höhe m, Wandfläche m²\n3. FENSTER: FE_[Nr] / RPH / FPH / AL Breite+Höhe / RB Breite+Höhe (mm)\n4. TÜREN: T[Nr] / Breite×Höhe / Typ\n5. Wandstärken mm\n\nNUR valides JSON:\n{\"massstab\":\"1:100\",\"geschoss\":\"EG\",\"raeume\":[{\"name\":\"\",\"bodenbelag\":\"\",\"flaeche_m2\":0,\"umfang_m\":0,\"hoehe_m\":0,\"wandflaeche_m2\":0,\"konfidenz\":0.9}],\"fenster\":[{\"bezeichnung\":\"\",\"raum\":\"\",\"al_breite_mm\":0,\"al_hoehe_mm\":0,\"rb_breite_mm\":0,\"rb_hoehe_mm\":0,\"flaeche_m2\":0,\"konfidenz\":0.9}],\"tueren\":[{\"bezeichnung\":\"\",\"raum\":\"\",\"breite_mm\":0,\"hoehe_mm\":0,\"konfidenz\":0.85}],\"gesamt_konfidenz\":0.85}" }
          ]
        }]
      })
    })

    const claudeJson = await claudeRes.json()
    if (claudeJson.error) throw new Error("Claude: " + (claudeJson.error?.message || JSON.stringify(claudeJson.error)))

    const rawText = claudeJson.content?.[0]?.text || "{}"
    let result: any
    try {
      const match = rawText.match(/\{[\s\S]*\}/)
      result = JSON.parse(match ? match[0] : rawText)
    } catch { throw new Error("KI-Antwort nicht parsbar") }

    for (const r of (result.raeume || [])) {
      await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
    }
    for (const f of (result.fenster || [])) {
      await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
    }
    for (const t of (result.tueren || [])) {
      await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })
    }

    const konfidenz = Math.round((result.gesamt_konfidenz || 0.5) * 100)
    await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: konfidenz, agent_log: result }).eq("id", plan_id)

    return new Response(JSON.stringify({ status: "ok", raeume: (result.raeume||[]).length, fenster: (result.fenster||[]).length, tueren: (result.tueren||[]).length, konfidenz }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } })
  }
})
