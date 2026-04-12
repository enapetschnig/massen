import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
}

const MODEL = "claude-sonnet-4-20250514"

function parseJson(raw: string): any {
  try { return JSON.parse(raw) } catch {}
  const m = raw.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (m) try { return JSON.parse(m[1]) } catch {}
  const m2 = raw.match(/\{[\s\S]*\}/)
  if (m2) try { return JSON.parse(m2[0]) } catch {}
  throw new Error("JSON parse failed")
}

async function callClaude(apiKey: string, system: string, content: any[], maxTok = 16384): Promise<any> {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model: MODEL, max_tokens: maxTok, system, messages: [{ role: "user", content }] }),
  })
  if (!r.ok) throw new Error("Claude " + r.status)
  const j = await r.json()
  return parseJson(j.content?.[0]?.text || "{}")
}

// ═══ DETERMINISTIC MATH ENGINE ═══

interface RoomDims {
  name: string
  wohnung: string
  flaeche: number
  umfang: number
  hoehe: number
  bodenbelag: string
  sideA: number  // longer side
  sideB: number  // shorter side
}

function calcRoomDimensions(room: any, rohbauHoehe: number): RoomDims | null {
  // Calculate room dimensions from area + perimeter
  const F = room.flaeche_m2 || 0
  const U = room.umfang_m || 0
  const H = rohbauHoehe || room.hoehe_m || 2.60

  if (F > 0 && U > 0) {
    // Quadratic formula: a + b = U/2, a * b = F
    const halfU = U / 2
    const discriminant = halfU * halfU - 4 * F
    if (discriminant >= 0) {
      const a = (halfU + Math.sqrt(discriminant)) / 2
      const b = (halfU - Math.sqrt(discriminant)) / 2
      return { name: room.name || "", wohnung: (room.wohnung || "").toUpperCase(),
               flaeche: F, umfang: U, hoehe: H, bodenbelag: room.bodenbelag || "",
               sideA: Math.round(a * 100) / 100, sideB: Math.round(b * 100) / 100 }
    }
  }

  // Fallback: use area and estimate as square
  if (F > 0) {
    const side = Math.sqrt(F)
    return { name: room.name || "", wohnung: (room.wohnung || "").toUpperCase(),
             flaeche: F, umfang: U || side * 4, hoehe: H, bodenbelag: room.bodenbelag || "",
             sideA: Math.round(side * 100) / 100, sideB: Math.round(side * 100) / 100 }
  }

  return null
}

function calcWandflaeche(room: RoomDims): number {
  // Wall area = perimeter × height
  return Math.round(room.umfang * room.hoehe * 100) / 100
}

function calcOENORMAbzug(oeffnungFlaeche: number, gewerk: string): number {
  // Returns multiplier: 0 = no deduction, 0.5 = half, 1.0 = full
  if (gewerk === "mauerwerk") {
    if (oeffnungFlaeche < 0.5) return 0
    if (oeffnungFlaeche <= 3.0) return 0.5
    return 1.0
  }
  if (gewerk === "putz" || gewerk === "maler") {
    if (oeffnungFlaeche < 2.5) return 0
    if (oeffnungFlaeche <= 10.0) return 0.5
    return 1.0
  }
  if (gewerk === "fliesen") {
    if (oeffnungFlaeche < 0.1) return 0
    return 1.0
  }
  return 0
}

function normalizeWindowDimension(val: number): number {
  // Auto-detect unit and convert to mm
  if (val < 30) return val * 100   // cm → mm (e.g., 15 → 1500)
  if (val < 300) return val * 10   // cm → mm (e.g., 147 → 1470)
  return val                        // already mm
}

function isNassraum(name: string): boolean {
  return /bad|wc|dusche|nassraum|wasch/i.test(name)
}

function isBad(name: string): boolean {
  return /bad|dusche|nassraum/i.test(name)
}

function isWC(name: string): boolean {
  return /\bwc\b|toilette/i.test(name)
}

function hasFliesenBoden(bodenbelag: string, name: string): boolean {
  if (/fliesen|feinsteinzeug|keramik|steinzeug/i.test(bodenbelag)) return true
  // Bad/WC typically have tiles even if not specified
  if (isNassraum(name) && !bodenbelag) return true
  return false
}

function calcMassen(
  raeume: any[], fenster: any[], tueren: any[],
  gewerk: string, geschosse: number, whgProOg: number, hEG: number, hOG: number
): any[] {
  const positionen: any[] = []
  const dims = raeume.map(r => calcRoomDimensions(r, hEG)).filter(d => d !== null) as RoomDims[]
  const whgNames = [...new Set(dims.map(d => d.wohnung))].filter(w => w.startsWith("TOP"))
  const egWhg = whgNames.length || 1
  const ogFloors = geschosse - 1
  const wandstaerke_m = 0.20 // default inner wall thickness

  // Normalize window dimensions
  const normalizedFenster = fenster.map(f => {
    const al_h = normalizeWindowDimension(f.al_hoehe_mm || 1470) / 1000
    const al_b = normalizeWindowDimension(f.al_breite_mm || 1200) / 1000
    const rb_h = normalizeWindowDimension(f.rb_hoehe_mm || 1570) / 1000
    const rb_b = normalizeWindowDimension(f.rb_breite_mm || 1300) / 1000
    return {
      ...f,
      al_hoehe_m: al_h,
      al_breite_m: al_b,
      rb_hoehe_m: rb_h,
      rb_breite_m: rb_b,
      flaeche_m2: Math.round(al_h * al_b * 100) / 100,
    }
  })

  // Normalize door dimensions
  const normalizedTueren = tueren.map(t => ({
    ...t,
    breite_m: (t.breite_mm || 900) / 1000,
    hoehe_m: (t.hoehe_mm || 2100) / 1000,
    flaeche_m2: Math.round(((t.breite_mm || 900) / 1000) * ((t.hoehe_mm || 2100) / 1000) * 100) / 100,
  }))

  // Total opening areas per room for deductions
  function openingsForRoom(roomName: string, whg: string): number {
    let total = 0
    for (const f of normalizedFenster) {
      if ((f.raum || "").toLowerCase() === roomName.toLowerCase() &&
          (f.wohnung || "").toUpperCase() === whg) {
        total += f.flaeche_m2
      }
    }
    for (const t of normalizedTueren) {
      if ((t.raum || "").toLowerCase() === roomName.toLowerCase() &&
          (t.wohnung || "").toUpperCase() === whg) {
        total += t.flaeche_m2
      }
    }
    return total
  }

  // ═══ MALER ═══
  if (gewerk === "maler" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "ML." : ""
    let totalWandEG = 0, totalDeckeEG = 0, totalLeibungEG = 0
    const berechnungWand: string[] = []
    const berechnungDecke: string[] = []
    const berechnungLeibung: string[] = []

    for (const d of dims) {
      const wf = calcWandflaeche(d)
      const oeffnung = openingsForRoom(d.name, d.wohnung)
      const abzugFaktor = calcOENORMAbzug(oeffnung, "maler")
      const abzug = Math.round(oeffnung * abzugFaktor * 100) / 100
      const netto = Math.round((wf - abzug) * 100) / 100

      totalWandEG += netto
      berechnungWand.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}×${d.hoehe.toFixed(2)}=${wf.toFixed(2)} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m²`)

      totalDeckeEG += d.flaeche
      berechnungDecke.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m²`)
    }

    // Leibungen: per window 2×wandstaerke×height + wandstaerke×width
    for (const f of normalizedFenster) {
      const leib = 2 * wandstaerke_m * f.al_hoehe_m + wandstaerke_m * f.al_breite_m
      const leibFlaeche = Math.round(leib * 100) / 100
      totalLeibungEG += leibFlaeche
      berechnungLeibung.push(`${f.bezeichnung || "Fenster"}: 2×${wandstaerke_m}×${f.al_hoehe_m.toFixed(2)}+${wandstaerke_m}×${f.al_breite_m.toFixed(2)} = ${leibFlaeche.toFixed(2)} m²`)
    }

    // OG multiplication
    const ogFaktorFlaeche = egWhg > 0 ? (whgProOg / egWhg) * (hOG / hEG) : 0
    const ogFaktorDecke = egWhg > 0 ? (whgProOg / egWhg) : 0
    const ogFaktorLeibung = egWhg > 0 ? (whgProOg / egWhg) : 0

    const totalWandOG = Math.round(totalWandEG * ogFaktorFlaeche * ogFloors * 100) / 100
    const totalDeckeOG = Math.round(totalDeckeEG * ogFaktorDecke * ogFloors * 100) / 100
    const totalLeibungOG = Math.round(totalLeibungEG * ogFaktorLeibung * ogFloors * 100) / 100

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Grundierung Wände EG", gewerk: "Maler",
        raum_referenz: "Alle Räume EG", berechnung: berechnungWand,
        endsumme: Math.round(totalWandEG * 100) / 100, einheit: "m²", konfidenz: 90 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Grundierung Wände OG (×${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalWandEG.toFixed(2)} × ${(ogFaktorFlaeche * ogFloors).toFixed(2)} = ${totalWandOG.toFixed(2)}`],
        endsumme: totalWandOG, einheit: "m²", konfidenz: 85 },
      { pos_nr: `${prefix}2`, beschreibung: "Anstrich Wände EG", gewerk: "Maler",
        raum_referenz: "Alle Räume EG", berechnung: berechnungWand,
        endsumme: Math.round(totalWandEG * 100) / 100, einheit: "m²", konfidenz: 90 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Anstrich Wände OG (×${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalWandEG.toFixed(2)} × ${(ogFaktorFlaeche * ogFloors).toFixed(2)} = ${totalWandOG.toFixed(2)}`],
        endsumme: totalWandOG, einheit: "m²", konfidenz: 85 },
      { pos_nr: `${prefix}3`, beschreibung: "Grundierung Decken EG", gewerk: "Maler",
        raum_referenz: "Alle Räume EG", berechnung: berechnungDecke,
        endsumme: Math.round(totalDeckeEG * 100) / 100, einheit: "m²", konfidenz: 92 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Grundierung Decken OG (×${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalDeckeEG.toFixed(2)} × ${(ogFaktorDecke * ogFloors).toFixed(2)} = ${totalDeckeOG.toFixed(2)}`],
        endsumme: totalDeckeOG, einheit: "m²", konfidenz: 87 },
      { pos_nr: `${prefix}4`, beschreibung: "Anstrich Decken EG", gewerk: "Maler",
        raum_referenz: "Alle Räume EG", berechnung: berechnungDecke,
        endsumme: Math.round(totalDeckeEG * 100) / 100, einheit: "m²", konfidenz: 92 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Anstrich Decken OG (×${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalDeckeEG.toFixed(2)} × ${(ogFaktorDecke * ogFloors).toFixed(2)} = ${totalDeckeOG.toFixed(2)}`],
        endsumme: totalDeckeOG, einheit: "m²", konfidenz: 87 },
      { pos_nr: `${prefix}5`, beschreibung: "Leibungen EG", gewerk: "Maler",
        raum_referenz: "Fenster EG", berechnung: berechnungLeibung,
        endsumme: Math.round(totalLeibungEG * 100) / 100, einheit: "m²", konfidenz: 85 },
      { pos_nr: `${prefix}5-OG`, beschreibung: `Leibungen OG (×${ogFloors})`, gewerk: "Maler",
        raum_referenz: "Fenster OG", berechnung: [`EG ${totalLeibungEG.toFixed(2)} × ${(ogFaktorLeibung * ogFloors).toFixed(2)} = ${totalLeibungOG.toFixed(2)}`],
        endsumme: totalLeibungOG, einheit: "lfm", konfidenz: 80 },
    )
  }

  // ═══ FLIESEN ═══
  if (gewerk === "fliesen" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "FL." : ""
    let totalBodenEG = 0, totalWandBadEG = 0, totalWandWCEG = 0, totalSockelEG = 0
    const berechnungBoden: string[] = []
    const berechnungWandBad: string[] = []
    const berechnungWandWC: string[] = []
    const berechnungSockel: string[] = []
    const fliesenHoehe = 2.10 // standard tile height for wet rooms

    for (const d of dims) {
      if (hasFliesenBoden(d.bodenbelag, d.name)) {
        totalBodenEG += d.flaeche
        berechnungBoden.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m²`)

        totalSockelEG += d.umfang
        berechnungSockel.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)} lfm`)
      }

      if (isBad(d.name)) {
        const wandBad = Math.round(d.umfang * fliesenHoehe * 100) / 100
        const oeffnung = openingsForRoom(d.name, d.wohnung)
        const abzug = calcOENORMAbzug(oeffnung, "fliesen") * oeffnung
        const netto = Math.round((wandBad - abzug) * 100) / 100
        totalWandBadEG += netto
        berechnungWandBad.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}×${fliesenHoehe} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m²`)
      }

      if (isWC(d.name)) {
        const wandWC = Math.round(d.umfang * fliesenHoehe * 100) / 100
        const oeffnung = openingsForRoom(d.name, d.wohnung)
        const abzug = calcOENORMAbzug(oeffnung, "fliesen") * oeffnung
        const netto = Math.round((wandWC - abzug) * 100) / 100
        totalWandWCEG += netto
        berechnungWandWC.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}×${fliesenHoehe} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m²`)
      }
    }

    const ogFaktor = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Bodenfliesen EG", gewerk: "Fliesen",
        raum_referenz: "Nassräume EG", berechnung: berechnungBoden,
        endsumme: Math.round(totalBodenEG * 100) / 100, einheit: "m²", konfidenz: 90 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Bodenfliesen OG (×${ogFloors})`, gewerk: "Fliesen",
        raum_referenz: "Nassräume OG", berechnung: [`EG ${totalBodenEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalBodenEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalBodenEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 85 },
    )

    if (totalWandBadEG > 0) {
      positionen.push(
        { pos_nr: `${prefix}2`, beschreibung: "Wandfliesen Bad EG", gewerk: "Fliesen",
          raum_referenz: "Bad EG", berechnung: berechnungWandBad,
          endsumme: Math.round(totalWandBadEG * 100) / 100, einheit: "m²", konfidenz: 88 },
        { pos_nr: `${prefix}2-OG`, beschreibung: `Wandfliesen Bad OG (×${ogFloors})`, gewerk: "Fliesen",
          raum_referenz: "Bad OG", berechnung: [`EG ${totalWandBadEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalWandBadEG * ogFaktor).toFixed(2)}`],
          endsumme: Math.round(totalWandBadEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 83 },
      )
    }

    if (totalWandWCEG > 0) {
      positionen.push(
        { pos_nr: `${prefix}3`, beschreibung: "Wandfliesen WC EG", gewerk: "Fliesen",
          raum_referenz: "WC EG", berechnung: berechnungWandWC,
          endsumme: Math.round(totalWandWCEG * 100) / 100, einheit: "m²", konfidenz: 88 },
        { pos_nr: `${prefix}3-OG`, beschreibung: `Wandfliesen WC OG (×${ogFloors})`, gewerk: "Fliesen",
          raum_referenz: "WC OG", berechnung: [`EG ${totalWandWCEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalWandWCEG * ogFaktor).toFixed(2)}`],
          endsumme: Math.round(totalWandWCEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 83 },
      )
    }

    positionen.push(
      { pos_nr: `${prefix}4`, beschreibung: "Sockelleisten EG", gewerk: "Fliesen",
        raum_referenz: "Nassräume EG", berechnung: berechnungSockel,
        endsumme: Math.round(totalSockelEG * 100) / 100, einheit: "lfm", konfidenz: 85 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Sockelleisten OG (×${ogFloors})`, gewerk: "Fliesen",
        raum_referenz: "Nassräume OG", berechnung: [`EG ${totalSockelEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalSockelEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalSockelEG * ogFaktor * 100) / 100, einheit: "lfm", konfidenz: 80 },
    )
  }

  // ═══ ESTRICH ═══
  if (gewerk === "estrich" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "ES." : ""
    let totalEstrichEG = 0, totalRandEG = 0, totalNassraumEG = 0
    const berechnungEstrich: string[] = []
    const berechnungRand: string[] = []
    const berechnungNass: string[] = []

    for (const d of dims) {
      totalEstrichEG += d.flaeche
      berechnungEstrich.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m²`)

      totalRandEG += d.umfang
      berechnungRand.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)} lfm`)

      if (isNassraum(d.name)) {
        totalNassraumEG += d.flaeche
        berechnungNass.push(`${d.wohnung} ${d.name}: ${d.flaeche.toFixed(2)} m²`)
      }
    }

    const ogFaktor = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Zementestrich EG", gewerk: "Estrich",
        raum_referenz: "Alle Räume EG", berechnung: berechnungEstrich,
        endsumme: Math.round(totalEstrichEG * 100) / 100, einheit: "m²", konfidenz: 92 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Zementestrich OG (×${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalEstrichEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalEstrichEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalEstrichEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 87 },
      { pos_nr: `${prefix}2`, beschreibung: "Randdämmstreifen EG", gewerk: "Estrich",
        raum_referenz: "Alle Räume EG", berechnung: berechnungRand,
        endsumme: Math.round(totalRandEG * 100) / 100, einheit: "lfm", konfidenz: 90 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Randdämmstreifen OG (×${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalRandEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalRandEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalRandEG * ogFaktor * 100) / 100, einheit: "lfm", konfidenz: 85 },
      { pos_nr: `${prefix}3`, beschreibung: "Trittschalldämmung EG", gewerk: "Estrich",
        raum_referenz: "Alle Räume EG", berechnung: berechnungEstrich,
        endsumme: Math.round(totalEstrichEG * 100) / 100, einheit: "m²", konfidenz: 92 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Trittschalldämmung OG (×${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalEstrichEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalEstrichEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalEstrichEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 87 },
      { pos_nr: `${prefix}4`, beschreibung: "Dampfsperre Nassräume EG", gewerk: "Estrich",
        raum_referenz: "Nassräume EG", berechnung: berechnungNass,
        endsumme: Math.round(totalNassraumEG * 100) / 100, einheit: "m²", konfidenz: 88 },
      { pos_nr: `${prefix}4-OG`, beschreibung: `Dampfsperre Nassräume OG (×${ogFloors})`, gewerk: "Estrich",
        raum_referenz: "Nassräume OG", berechnung: [`EG ${totalNassraumEG.toFixed(2)} × ${ogFaktor.toFixed(2)} = ${(totalNassraumEG * ogFaktor).toFixed(2)}`],
        endsumme: Math.round(totalNassraumEG * ogFaktor * 100) / 100, einheit: "m²", konfidenz: 83 },
    )
  }

  // ═══ MAUERWERK ═══
  if (gewerk === "mauerwerk" || gewerk === "allgemein") {
    const prefix = gewerk === "allgemein" ? "MW." : ""
    const aussenWandstaerke = 0.30 // 300mm typical
    let totalInnenEG = 0, totalLeibungEG = 0
    const berechnungInnen: string[] = []
    const berechnungLeibung: string[] = []

    for (const d of dims) {
      const wf = calcWandflaeche(d)
      const oeffnung = openingsForRoom(d.name, d.wohnung)
      const abzugFaktor = calcOENORMAbzug(oeffnung, "mauerwerk")
      const abzug = Math.round(oeffnung * abzugFaktor * 100) / 100
      const netto = Math.round((wf - abzug) * 100) / 100
      totalInnenEG += netto
      berechnungInnen.push(`${d.wohnung} ${d.name}: ${d.umfang.toFixed(2)}×${d.hoehe.toFixed(2)}=${wf.toFixed(2)} -${abzug.toFixed(2)} = ${netto.toFixed(2)} m²`)
    }

    // Leibungen from windows
    for (const f of normalizedFenster) {
      // Leibung = (2 × height + width) × wall thickness
      const leibLfm = 2 * f.al_hoehe_m + f.al_breite_m
      const leibFlaeche = Math.round(leibLfm * aussenWandstaerke * 100) / 100
      totalLeibungEG += leibFlaeche
      berechnungLeibung.push(`${f.bezeichnung || "Fenster"}: (2×${f.al_hoehe_m.toFixed(2)}+${f.al_breite_m.toFixed(2)})×${aussenWandstaerke} = ${leibFlaeche.toFixed(2)} m²`)
    }

    const ogFaktorWand = egWhg > 0 ? (whgProOg / egWhg) * (hOG / hEG) * ogFloors : 0
    const ogFaktorLeibung = egWhg > 0 ? (whgProOg / egWhg) * ogFloors : 0

    // Außenwand: estimate from building dimensions if available
    // We don't have building dims in this function, so we sum all room perimeters as approximation
    // Rough estimate: outer wall ≈ sqrt(total floor area) × 4 × height
    const totalFloor = dims.reduce((s, d) => s + d.flaeche, 0)
    const buildingSide = Math.sqrt(totalFloor)
    const aussenWandEG = Math.round(buildingSide * 4 * hEG * 100) / 100

    positionen.push(
      { pos_nr: `${prefix}1`, beschreibung: "Außenwand EG (Schätzung)", gewerk: "Mauerwerk",
        raum_referenz: "Gebäude EG", berechnung: [`Geschätzt aus Gesamtfläche: √${totalFloor.toFixed(1)}×4×${hEG} = ${aussenWandEG.toFixed(2)} m²`],
        endsumme: aussenWandEG, einheit: "m²", konfidenz: 60 },
      { pos_nr: `${prefix}1-OG`, beschreibung: `Außenwand OG (×${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Gebäude OG", berechnung: [`EG ${aussenWandEG.toFixed(2)} × ${hOG/hEG} × ${ogFloors} = ${(aussenWandEG * hOG/hEG * ogFloors).toFixed(2)}`],
        endsumme: Math.round(aussenWandEG * (hOG / hEG) * ogFloors * 100) / 100, einheit: "m²", konfidenz: 55 },
      { pos_nr: `${prefix}2`, beschreibung: "Innenwände EG", gewerk: "Mauerwerk",
        raum_referenz: "Alle Räume EG", berechnung: berechnungInnen,
        endsumme: Math.round(totalInnenEG * 100) / 100, einheit: "m²", konfidenz: 85 },
      { pos_nr: `${prefix}2-OG`, beschreibung: `Innenwände OG (×${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Alle Räume OG", berechnung: [`EG ${totalInnenEG.toFixed(2)} × ${ogFaktorWand.toFixed(2)} = ${(totalInnenEG * ogFaktorWand).toFixed(2)}`],
        endsumme: Math.round(totalInnenEG * ogFaktorWand * 100) / 100, einheit: "m²", konfidenz: 80 },
      { pos_nr: `${prefix}3`, beschreibung: "Leibungen EG", gewerk: "Mauerwerk",
        raum_referenz: "Fenster EG", berechnung: berechnungLeibung,
        endsumme: Math.round(totalLeibungEG * 100) / 100, einheit: "m²", konfidenz: 82 },
      { pos_nr: `${prefix}3-OG`, beschreibung: `Leibungen OG (×${ogFloors})`, gewerk: "Mauerwerk",
        raum_referenz: "Fenster OG", berechnung: [`EG ${totalLeibungEG.toFixed(2)} × ${ogFaktorLeibung.toFixed(2)} = ${(totalLeibungEG * ogFaktorLeibung).toFixed(2)}`],
        endsumme: Math.round(totalLeibungEG * ogFaktorLeibung * 100) / 100, einheit: "m²", konfidenz: 77 },
    )
  }

  return positionen
}

/*
 * Step-based orchestrator with 4-PASS FOCUSED VISION SCAN.
 *   step=1 → 4 focused passes (Structure, Rooms, Windows/Doors, Dimensions) + merge
 *   step=2 → Kalkulation (ÖNORM mass calculation, gewerk-specific)
 *   step=3 → Kritik (quality check + finalize)
 */
serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders })

  try {
    const { plan_id, step = 1, gewerk = "allgemein", geschosse = 3, whg_pro_og = 4 } = await req.json()
    if (!plan_id) throw new Error("plan_id fehlt")

    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!)
    const { data: cfg } = await sb.from("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").single()
    if (!cfg?.value) throw new Error("API Key fehlt")

    const { data: plan } = await sb.from("plaene").select("*").eq("id", plan_id).single()
    if (!plan) throw new Error("Plan nicht gefunden")

    // ========== STEP 1: 4-Pass Focused Vision Scan ==========
    if (step === 1) {
      // Clean old results
      await sb.from("massen").delete().eq("plan_id", plan_id)
      await sb.from("elemente").delete().eq("plan_id", plan_id)
      await sb.from("plaene").update({ verarbeitet: false, agent_log: { start: new Date().toISOString() } }).eq("id", plan_id)

      const { data: u } = await sb.storage.from("plaene").createSignedUrl(plan.storage_path, 3600)
      if (!u?.signedUrl) throw new Error("PDF URL fehlt")
      const pdfSource = { type: "document", source: { type: "url", url: u.signedUrl } }

      const errors: string[] = []

      // ---- PASS 1A: STRUCTURE ----
      let pass1A: any = {}
      try {
        pass1A = await callClaude(cfg.value,
          `Du bist Bauingenieur. Analysiere die STRUKTUR dieses Plans. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Beantworte NUR diese Fragen als JSON:
1. massstab: welcher Maßstab?
2. geschoss: welches Geschoss?
3. raumhoehe_m: welche Raumhöhe steht im Plan?
4. anzahl_wohnungen: wie viele Wohnungen/Einheiten (Top) sind sichtbar?
5. wohnungen: Liste jeder Wohnung mit {name, raeume: [Raumname, ...], flaeche_wohnnutz_m2}
6. wandstaerken_mm: welche Wandstärken erkennst du?
7. gebaeude_laenge_m: Gesamtlänge des Gebäudes
8. gebaeude_tiefe_m: Gesamttiefe

JSON-Format:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raumhoehe_m": 2.60,
  "anzahl_wohnungen": 4,
  "wohnungen": [
    { "name": "Top 1", "raeume": ["Vorraum", "Wohnküche", "Bad"], "flaeche_wohnnutz_m2": 55.0 }
  ],
  "wandstaerken_mm": [300, 200, 120],
  "gebaeude_laenge_m": 24.0,
  "gebaeude_tiefe_m": 12.0
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1A: " + e.message)
      }

      // Update log after Pass 1A
      await sb.from("plaene").update({
        agent_log: {
          start: new Date().toISOString(),
          pass1A: { ts: new Date().toISOString(), ok: errors.length === 0, wohnungen: (pass1A.wohnungen || []).length },
        }
      }).eq("id", plan_id)

      // ---- PASS 1B: ROOMS ----
      let pass1B: any = {}
      try {
        pass1B = await callClaude(cfg.value,
          `Du bist Bautechniker. Lies JEDEN Text in JEDEM Raum. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Für JEDEN Raum im Plan lies EXAKT ab:
- Name (wie er im Plan steht)
- Fläche m² (die Zahl mit m²)
- Umfang (U: xx.xx m)
- Höhe (H: x.xx m)
- Bodenbelag
- Zu welcher Wohnung (Top) gehört der Raum?
- Position als [x%, y%, w%, h%]
Gib die EXAKTEN Zahlen aus dem Plan zurück, keine Schätzungen!

JSON-Format:
{
  "raeume": [
    {
      "name": "Wohnküche",
      "flaeche_m2": 26.37,
      "umfang_m": 20.66,
      "hoehe_m": 2.42,
      "bodenbelag": "Parkett",
      "wohnung": "Top 1",
      "position_pct": [10, 20, 35, 40],
      "konfidenz": 0.95
    }
  ]
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1B: " + e.message)
      }

      // Update log after Pass 1B
      const log1B = (await sb.from("plaene").select("agent_log").eq("id", plan_id).single()).data?.agent_log || {}
      log1B.pass1B = { ts: new Date().toISOString(), ok: !errors.some(e => e.startsWith("Pass1B")), raeume: (pass1B.raeume || []).length }
      await sb.from("plaene").update({ agent_log: log1B }).eq("id", plan_id)

      // ---- PASS 1C: WINDOWS & DOORS ----
      let pass1C: any = {}
      try {
        pass1C = await callClaude(cfg.value,
          `Du bist Fenstertechniker. Lies JEDE Fenster- und Türbezeichnung. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Suche ALLE Fensterbezeichnungen (FE_, F_) und Türen (T_).
Fenster: Lies RPH, FPH, AL Breite+Höhe, RB Breite+Höhe in mm.
Türen: Lies Breite, Höhe, Typ.
Ordne jedes Element einem Raum und einer Wohnung zu.

JSON-Format:
{
  "fenster": [
    {
      "bezeichnung": "FE_31",
      "raum": "Wohnküche",
      "wohnung": "Top 1",
      "rph_mm": 1010,
      "fph_mm": 480,
      "al_breite_mm": 1510,
      "al_hoehe_mm": 1510,
      "rb_breite_mm": 1760,
      "rb_hoehe_mm": 1760,
      "position_pct": [5, 35, 5, 10],
      "konfidenz": 0.90
    }
  ],
  "tueren": [
    {
      "bezeichnung": "T1",
      "raum": "Wohnküche",
      "wohnung": "Top 1",
      "breite_mm": 900,
      "hoehe_mm": 2100,
      "typ": "Drehflügel",
      "position_pct": [30, 45, 3, 5],
      "konfidenz": 0.85
    }
  ]
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1C: " + e.message)
      }

      // Update log after Pass 1C
      const log1C = (await sb.from("plaene").select("agent_log").eq("id", plan_id).single()).data?.agent_log || {}
      log1C.pass1C = { ts: new Date().toISOString(), ok: !errors.some(e => e.startsWith("Pass1C")), fenster: (pass1C.fenster || []).length, tueren: (pass1C.tueren || []).length }
      await sb.from("plaene").update({ agent_log: log1C }).eq("id", plan_id)

      // ---- PASS 1D: DIMENSIONS ----
      let pass1D: any = {}
      try {
        pass1D = await callClaude(cfg.value,
          `Du bist Vermesser. Lies die MAẞKETTEN. Antworte NUR mit validem JSON, KEIN Markdown.`,
          [
            pdfSource,
            { type: "text", text: `Lies ALLE Bemaßungszahlen im Plan. Das sind Zahlen an Linien mit Pfeilen/Endstrichen.
Die Zahlen sind in ZENTIMETERN. Typische Werte: 120-800.
Suche speziell:
- Gesamtmaße an den Außenkanten
- Maße zwischen Wohnungstrennwänden
- Maße einzelner Wandabschnitte
Für JEDES Maß: {wert_cm, beschreibung, position: 'oben/unten/links/rechts/innen'}

JSON-Format:
{
  "masse": [
    { "wert_cm": 587, "beschreibung": "Wand Wohnküche Süd", "position": "unten" }
  ],
  "gebaeude_laenge_cm": 2400,
  "gebaeude_tiefe_cm": 1200
}` },
          ])
      } catch (e: any) {
        errors.push("Pass1D: " + e.message)
      }

      // ---- MERGE all 4 passes ----
      const merged: any = {
        massstab: pass1A.massstab || null,
        geschoss: pass1A.geschoss || null,
        raumhoehe_global_m: pass1A.raumhoehe_m || null,
        anzahl_wohnungen: pass1A.anzahl_wohnungen || null,
        wohnungen: pass1A.wohnungen || [],
        wandstaerken_mm: pass1A.wandstaerken_mm || [],
        gebaeude_laenge_m: pass1A.gebaeude_laenge_m || (pass1D.gebaeude_laenge_cm ? pass1D.gebaeude_laenge_cm / 100 : null),
        gebaeude_tiefe_m: pass1A.gebaeude_tiefe_m || (pass1D.gebaeude_tiefe_cm ? pass1D.gebaeude_tiefe_cm / 100 : null),
        raeume: pass1B.raeume || [],
        fenster: pass1C.fenster || [],
        tueren: pass1C.tueren || [],
        masse: pass1D.masse || [],
        gebaeude_laenge_cm: pass1D.gebaeude_laenge_cm || null,
        gebaeude_tiefe_cm: pass1D.gebaeude_tiefe_cm || null,
      }

      // Calculate wandflaeche for each room
      for (const r of merged.raeume) {
        if (r.umfang_m && r.hoehe_m) {
          r.wandflaeche_m2 = Math.round(r.umfang_m * r.hoehe_m * 100) / 100
        }
        if (!r.flaeche_m2 && r.umfang_m) r.flaeche_m2 = 0
      }

      // Calculate fensterflaeche for each window
      for (const f of merged.fenster) {
        if (f.al_breite_mm && f.al_hoehe_mm) {
          f.flaeche_m2 = Math.round(f.al_breite_mm * f.al_hoehe_mm / 10000) / 100
        }
      }

      // ---- Store elements in DB ----
      for (const r of merged.raeume)
        await sb.from("elemente").insert({ plan_id, typ: "raum", bezeichnung: r.name || "", daten: r, konfidenz: Math.round((r.konfidenz || 0.5) * 100) })
      for (const f of merged.fenster)
        await sb.from("elemente").insert({ plan_id, typ: "fenster", bezeichnung: f.bezeichnung || "", daten: f, konfidenz: Math.round((f.konfidenz || 0.5) * 100) })
      for (const t of merged.tueren)
        await sb.from("elemente").insert({ plan_id, typ: "tuer", bezeichnung: t.bezeichnung || "", daten: t, konfidenz: Math.round((t.konfidenz || 0.5) * 100) })

      // ---- Update agent_log ----
      const log = {
        start: new Date().toISOString(),
        step1: {
          ts: new Date().toISOString(),
          r: merged.raeume.length,
          f: merged.fenster.length,
          t: merged.tueren.length,
          masse: merged.masse.length,
          pass1A: { ok: !errors.some(e => e.startsWith("Pass1A")), wohnungen: (pass1A.wohnungen || []).length },
          pass1B: { ok: !errors.some(e => e.startsWith("Pass1B")), raeume: (pass1B.raeume || []).length },
          pass1C: { ok: !errors.some(e => e.startsWith("Pass1C")), fenster: (pass1C.fenster || []).length, tueren: (pass1C.tueren || []).length },
          pass1D: { ok: !errors.some(e => e.startsWith("Pass1D")), masse: (pass1D.masse || []).length },
          errors: errors.length > 0 ? errors : undefined,
        },
        geo: merged,
        gewerk: gewerk,
        geschosse: geschosse,
        whg_pro_og: whg_pro_og,
        pass1A: pass1A,
      }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step1_done",
        next_step: 2,
        raeume: merged.raeume.length,
        fenster: merged.fenster.length,
        tueren: merged.tueren.length,
        masse: merged.masse.length,
        wohnungen: (pass1A.wohnungen || []).length,
        errors: errors.length > 0 ? errors : undefined,
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 2: Kalkulation ==========
    if (step === 2) {
      const geo = plan.agent_log?.geo
      const selectedGewerk = plan.agent_log?.gewerk || gewerk || "allgemein"
      if (!geo) throw new Error("Step 1 zuerst ausführen")

      // Build gewerk-specific prompt additions
      const gewerkPrompts: Record<string, string> = {
        verputzer: `
FOKUS: VERPUTZER / SPACHTELARBEITEN (VP/SR) nach ÖNORM B 2204

EXAKTE BERECHNUNGSMETHODE eines professionellen Verputzerbetriebs:

═══ POSITION: INNENPUTZ WÄNDE (m²) ═══

Der Verputzer verputzt NUR die WOHNUNGSTRENNWÄNDE - das sind die DICKEN Wände
zwischen den Wohnungseinheiten (Top). NICHT die Zimmerwände innerhalb der Wohnung!

Für JEDE Wohnung (Top) berechne:
- WAND 1 (Tiefe): Gebäudetiefe-Maß × Raumhöhe (z.B. 5.87m × 2.66m = 15.61m²)
- WAND 2 (Breite): Wohnungsbreite × Raumhöhe (z.B. 7.14m × 2.66m = 18.99m²)
- Bei Eckwohnungen: zusätzliche Wände (3-4 statt 2)

WANDLÄNGEN - KRITISCH WICHTIG:
- WAND A = Tiefe EINER Wohnung (NICHT Gebäudetiefe!)
  In einem Mehrfamilienhaus ist die Wohnungstiefe typisch 5-6m.
  Die Gebäudetiefe ist 15-20m aber die Trennwand geht nur durch EINE Wohnung!
  Teile die Gebäudetiefe durch die Anzahl der Wohnungen in der Tiefe!
  Beispiel: Gebäudetiefe 17.8m ÷ 3 Wohnungen = 5.93m pro Wohnung
- WAND B = Breite der Wohnung (die Querwand)
  ECKWOHNUNGEN (am Ende des Gebäudes): BREIT! 6-8m (z.B. 7.14m)
  MITTELWOHNUNGEN (in der Mitte): SCHMAL! 3-4m (z.B. 3.27m)
  ACHTUNG: Eckwohnungen haben die BREITERE Querwand, nicht die schmale!

BESONDERHEITEN BEI ECKWOHNUNGEN:
- Eckwohnungen haben MEHR Trennwände als Mittelwohnungen (3-5 statt 2)
- Sie haben oft BETONZWISCHENWÄNDE (Zwischenwand Beton)
- Betonzwischenwände werden BEIDSEITIG verputzt → Faktor 2!
  Beispiel: "Zwischenwand Beton: 2 × 6.20 × 1.0 × 2.66 = 32.98"
- Die größte Eckwohnung kann 50-90 m² Trennwand-Putzfläche haben

RAUMHÖHE: Verwende das ROHBAUMASS (Roh-Decke bis Roh-Boden):
- EG: typisch 2.60-2.70m (z.B. 2.66m)
- OG: typisch 2.55-2.65m (z.B. 2.60m)
Das Rohbaumaß ist ca. 20-25cm HÖHER als das Fertigmaß im Plan!
Wenn im Plan H=2.42m steht → Rohbaumaß ≈ 2.42 + 0.24 = 2.66m (EG)

═══ POSITION: HAFTGRUND (m²) ═══

NUR auf Betonwänden (Zwischenwand Beton) - NICHT auf Ziegel/Mauerwerk!
Betonwände brauchen Haftgrund weil Beton glatt und nicht saugend ist.
Berechne: Betonwand-Länge × Raumhöhe × Anzahl Seiten
Bei Betontrennwänden: BEIDE Seiten verputzen → Faktor 2!

═══ POSITION: KANTENPROFIL (lfm) ═══

Pro Fenster im Innenbereich:
- Fenster Aufrecht (beide Seiten): 2 × Fensterhöhe
  - Normale Fenster: 2 × 1.47m = 2.94 lfm
  - Loggia/Balkontür: 2 × Raumhöhe (2.60m oder 2.66m)
- Fensterbank: 1 × Fensterbreite
  - Normal: 1.20m
  - Klein (WC/Bad): 0.50m
Loggia-Fenster: 2 × Raumhöhe (KEINE Fensterbank - raumhohe Verglasung)
Zwischenwand Beton: 2 × Raumhöhe (beide Kanten der Betonwand)

═══ POSITION: ANPUTZLEISTE (lfm) ═══

Pro Fenster: NUR die aufrechten Teile, KEINE Fensterbänke!
- Fenster Aufrecht: 2 × Fensterhöhe
- Loggia: 2 × Raumhöhe
Gleiche Berechnung wie Kantenprofil MINUS die Fensterbänke.

═══ ÖNORM B 2204 ABZUGSREGELN ═══
- Öffnungen bis 0.5m²: kein Abzug, Leibungen dazurechnen
- Öffnungen 0.5-4.0m² MIT Leibungen: durchgemessen (nicht abziehen)
- Öffnungen 0.5-4.0m² OHNE Leibungen: abziehen
- Öffnungen über 4.0m²: abziehen, Leibungen extra addieren

BERECHNUNGSFORMAT: Jede Zeile: Beschreibung | Anz × Länge × Breite × Höhe = Zwischensumme`,

        mauerwerk: `
FOKUS: MAUERWERK / ROHBAU
- Außenwände: Ansichtsflächen × Wandstärke = Volumen m³
- Innenwände: Wandlänge × Wandhöhe × Wandstärke = Volumen m³
- Abzüge: Öffnungen <0.5m² kein, 0.5-3m² halb, >3m² voll
- Leibungen separat`,

        maler: `
FOKUS: MALER / ANSTRICH
- Wandflächen pro Raum (Umfang × Höhe - Öffnungsabzüge)
- Deckenflächen pro Raum
- Leibungsflächen (seitlich, Sturz, Brüstung)
- Grundierung als eigene Position`,

        fliesen: `
FOKUS: FLIESEN / BELÄGE
- Bodenfliesen pro Raum (nur Räume mit Fliesen)
- Wandfliesen pro Raum (Bad, WC, Küche - typisch bis 2.10m Höhe)
- Sockelleisten
- Abzüge: <0.1m² kein, ≥0.1m² voll`,

        estrich: `
FOKUS: ESTRICH
- Zementestrich pro Raum
- Randdämmstreifen (Laufmeter Umfang)
- Trittschalldämmung (gleiche Fläche)
- Feuchtigkeitssperre (Nassräume)`,

        trockenbau: `
FOKUS: TROCKENBAU
- Gipskartonwände (Fläche, Laufmeter)
- Vorsatzschalen
- Abhangdecken
- Spachtelung und Verfugung`,

        allgemein: `
ALLE GEWERKE berechnen:
01. Mauerwerk/Rohbau (m², m³)
02. Innenputz (m², lfm)
03. Außenputz (m², lfm)
04. Malerarbeiten (m²)
05. Bodenbelag nach Typ (m²)
06. Estrich (m²)
07. Fensterbänke (lfm)
08. Leibungen (m², lfm)`,
      }

      // ═══ VERPUTZER: Deterministic math-based calculation (no Claude!) ═══
      if (selectedGewerk === "verputzer") {
        const geschosseVal = plan.agent_log?.geschosse || geschosse || 3
        const whgProOg = plan.agent_log?.whg_pro_og || whg_pro_og || 4
        const hEG = 2.66  // Rohbaumaß EG
        const hOG = 2.60  // Rohbaumaß OG
        const ogFloors = geschosseVal - 1

        // Group rooms by apartment from geo data
        const raeume = geo.raeume || []
        const fenster = geo.fenster || []
        const wohnungen: Record<string, any[]> = {}
        for (const r of raeume) {
          const w = (r.wohnung || "Unbekannt").toUpperCase()
          if (!wohnungen[w]) wohnungen[w] = []
          wohnungen[w].push(r)
        }
        const whgNames = Object.keys(wohnungen).filter(w => w.startsWith("TOP"))
        const egWhg = whgNames.length || 3

        // Calculate wall lengths from room area + perimeter
        function calcSides(F: number, U: number): [number, number] | null {
          const half = U / 2
          const d = half * half - 4 * F
          if (d < 0) return null
          return [(half + Math.sqrt(d)) / 2, (half - Math.sqrt(d)) / 2]
        }

        let totalEG = 0
        const berechnungIP: string[] = []
        const berechnungKP: string[] = []
        const berechnungAP: string[] = []
        let totalKP = 0
        let totalAP = 0

        for (const wName of whgNames) {
          const rooms = wohnungen[wName]
          // Find Vorraum (hallway) - gives apartment width
          const vorraum = rooms.find((r: any) => /vorraum|flur|gang|diele/i.test(r.name || ""))
          // Find Wohnküche (living kitchen) - gives apartment depth
          const wohnkueche = rooms.find((r: any) => /wohnk|küche|wohn/i.test(r.name || ""))

          let breite = 0, tiefe = 0

          // Calculate from Vorraum
          if (vorraum?.umfang_m && vorraum?.flaeche_m2) {
            const sides = calcSides(vorraum.flaeche_m2, vorraum.umfang_m)
            if (sides) breite = sides[0] // longer side = apartment width
          }

          // Calculate from Wohnküche
          if (wohnkueche?.umfang_m && wohnkueche?.flaeche_m2) {
            const sides = calcSides(wohnkueche.flaeche_m2, wohnkueche.umfang_m)
            if (sides) {
              // The side ~5.7-5.9m is the depth
              if (sides[0] > 4.5 && sides[0] < 7) tiefe = sides[0]
              else if (sides[1] > 4.5 && sides[1] < 7) tiefe = sides[1]
              else tiefe = sides[0] // fallback
            }
          }

          // For Mittelwohnungen: Vorraum is too small, use Wohnküche short side as width
          if (breite < 2.5 && wohnkueche?.umfang_m && wohnkueche?.flaeche_m2) {
            const sides = calcSides(wohnkueche.flaeche_m2, wohnkueche.umfang_m)
            if (sides) breite = sides[1] // shorter side = apartment width for middle units
          }

          // Fallback
          if (tiefe === 0) tiefe = 5.87
          if (breite === 0) breite = 5.00

          const wf = (tiefe + breite) * hEG
          totalEG += wf
          berechnungIP.push(`${wName}: Tiefe ${tiefe.toFixed(2)}m + Breite ${breite.toFixed(2)}m × ${hEG}m = ${wf.toFixed(2)} m²`)
        }

        // Fenster: Kantenprofil + Anputzleiste
        // Multiply by whg count since each apartment has similar windows
        for (const f of fenster) {
          let fh_raw = f.al_hoehe_mm || 1470
          let fb_raw = f.al_breite_mm || 1200
          // Auto-detect unit: if value < 30, it's in cm → ×10 for mm; if < 300 it's cm → ×10
          if (fh_raw < 30) fh_raw *= 100  // cm to mm (e.g. 15 → 1500)
          else if (fh_raw < 300) fh_raw *= 10  // cm to mm (e.g. 147 → 1470)
          if (fb_raw < 30) fb_raw *= 100
          else if (fb_raw < 300) fb_raw *= 10
          const fh = fh_raw / 1000  // mm to m
          const fb = fb_raw / 1000
          const isLoggia = fh > 2.2  // Raumhohe Fenster = Loggia
          const kp = isLoggia ? 2 * hEG : 2 * fh + fb
          const ap = isLoggia ? 2 * hEG : 2 * fh  // Anputzleiste OHNE Fensterbank
          totalKP += kp
          totalAP += ap
          berechnungKP.push(`${f.bezeichnung || "Fenster"}: ${isLoggia ? "Loggia 2×"+hEG : "2×"+fh.toFixed(2)+"+"+(isLoggia?"":fb.toFixed(2))} = ${kp.toFixed(2)} lfm`)
          berechnungAP.push(`${f.bezeichnung || "Fenster"}: ${isLoggia ? "Loggia 2×"+hEG : "2×"+fh.toFixed(2)} = ${ap.toFixed(2)} lfm`)
        }

        // OG multiplication: each OG floor has whgProOg apartments
        // EG has egWhg apartments. OG apartments have same wall lengths but different height.
        // IP: scale by (whgProOg/egWhg) for apartment count and (hOG/hEG) for height
        const ipPerWhgEG = egWhg > 0 ? totalEG / egWhg : 0  // IP per apartment in EG
        const ipPerWhgOG = ipPerWhgEG * (hOG / hEG)  // Adjust height for OG
        const totalOG_IP = ipPerWhgOG * whgProOg * ogFloors  // Total all OG floors
        // KP/AP: scale by apartment count only (no height factor - it's lfm per window)
        const kpPerWhgEG = egWhg > 0 ? totalKP / egWhg : 0
        const totalOG_KP = kpPerWhgEG * whgProOg * ogFloors
        const apPerWhgEG = egWhg > 0 ? totalAP / egWhg : 0
        const totalOG_AP = apPerWhgEG * whgProOg * ogFloors

        const positionen = [
          {
            pos_nr: "2.3.1", beschreibung: "Haftgrund", gewerk: "Innenputz",
            raum_referenz: "Betonwände", berechnung: ["Betonwände visuell nicht eindeutig erkennbar - manuell prüfen"],
            endsumme: 0, einheit: "m²", konfidenz: 50,
          },
          {
            pos_nr: "2.3.2", beschreibung: "Innenputz Wände EG", gewerk: "Innenputz",
            raum_referenz: "Trennwände EG", berechnung: berechnungIP,
            endsumme: Math.round(totalEG * 100) / 100, einheit: "m²", konfidenz: 95,
          },
          {
            pos_nr: "2.3.2-OG", beschreibung: `Innenputz Wände OG (×${ogFloors} Geschosse)`, gewerk: "Innenputz",
            raum_referenz: "Trennwände OG", berechnung: [`${egWhg} EG-Whg à ${ipPerWhgEG.toFixed(2)}m² → ${whgProOg} OG-Whg à ${ipPerWhgOG.toFixed(2)}m² × ${ogFloors} Geschosse = ${totalOG_IP.toFixed(2)}m²`],
            endsumme: Math.round(totalOG_IP * 100) / 100, einheit: "m²", konfidenz: 90,
          },
          {
            pos_nr: "2.3.3", beschreibung: "Kantenprofil EG", gewerk: "Innenputz",
            raum_referenz: "Fenster EG", berechnung: berechnungKP,
            endsumme: Math.round(totalKP * 100) / 100, einheit: "lfm", konfidenz: 90,
          },
          {
            pos_nr: "2.3.3-OG", beschreibung: `Kantenprofil OG (×${ogFloors})`, gewerk: "Innenputz",
            raum_referenz: "Fenster OG", berechnung: [`EG ${totalKP.toFixed(2)} × ${(whgProOg/egWhg*ogFloors).toFixed(2)}`],
            endsumme: Math.round(totalOG_KP * 100) / 100, einheit: "lfm", konfidenz: 85,
          },
          {
            pos_nr: "2.3.4", beschreibung: "Anputzleiste EG", gewerk: "Innenputz",
            raum_referenz: "Fenster EG", berechnung: berechnungAP,
            endsumme: Math.round(totalAP * 100) / 100, einheit: "lfm", konfidenz: 90,
          },
          {
            pos_nr: "2.3.4-OG", beschreibung: `Anputzleiste OG (×${ogFloors})`, gewerk: "Innenputz",
            raum_referenz: "Fenster OG", berechnung: [`EG ${totalAP.toFixed(2)} × ${(whgProOg/egWhg*ogFloors).toFixed(2)}`],
            endsumme: Math.round(totalOG_AP * 100) / 100, einheit: "lfm", konfidenz: 85,
          },
        ]

        // Store
        for (const p of positionen) {
          await sb.from("massen").insert({ plan_id, ...p })
        }

        const log = plan.agent_log || {}
        log.step2 = {
          ts: new Date().toISOString(),
          methode: "deterministic_math",
          eg_whg: egWhg, og_floors: ogFloors, whg_pro_og: whgProOg,
          total_ip: Math.round((totalEG + totalOG_IP) * 100) / 100,
          total_kp: Math.round((totalKP + totalOG_KP) * 100) / 100,
          total_ap: Math.round((totalAP + totalOG_AP) * 100) / 100,
        }
        await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

        return new Response(JSON.stringify({
          status: "step2_done", next_step: 3, massen: positionen.length,
          methode: "deterministic_math",
          zusammenfassung: {
            innenputz_eg: Math.round(totalEG * 100) / 100,
            innenputz_og: Math.round(totalOG_IP * 100) / 100,
            innenputz_gesamt: Math.round((totalEG + totalOG_IP) * 100) / 100,
            kantenprofil_gesamt: Math.round((totalKP + totalOG_KP) * 100) / 100,
            anputzleiste_gesamt: Math.round((totalAP + totalOG_AP) * 100) / 100,
          },
        }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
      }

      // ═══ OTHER GEWERKE: Deterministic math engine first, Claude as fallback ═══
      const geschosseVal = plan.agent_log?.geschosse || geschosse || 3
      const whgProOgVal = plan.agent_log?.whg_pro_og || whg_pro_og || 4
      const hEGOther = 2.66  // Rohbaumaß EG
      const hOGOther = 2.60  // Rohbaumaß OG

      // Supported gewerke for deterministic math
      const mathGewerke = ["maler", "fliesen", "estrich", "mauerwerk", "allgemein"]

      if (mathGewerke.includes(selectedGewerk)) {
        // ═══ DETERMINISTIC MATH for maler/fliesen/estrich/mauerwerk/allgemein ═══
        const mathPositionen = calcMassen(
          geo.raeume || [], geo.fenster || [], geo.tueren || [],
          selectedGewerk, geschosseVal, whgProOgVal, hEGOther, hOGOther
        )

        if (mathPositionen.length > 0) {
          // Store deterministic results
          for (const p of mathPositionen) {
            await sb.from("massen").insert({ plan_id, ...p })
          }

          const log = plan.agent_log || {}
          log.step2 = {
            ts: new Date().toISOString(),
            methode: "deterministic_math",
            gewerk: selectedGewerk,
            pos: mathPositionen.length,
            eg_whg: ([...new Set((geo.raeume || []).map((r: any) => (r.wohnung || "").toUpperCase()))] as string[]).filter(w => w.startsWith("TOP")).length || 1,
            og_floors: geschosseVal - 1,
            whg_pro_og: whgProOgVal,
          }
          await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

          return new Response(JSON.stringify({
            status: "step2_done",
            next_step: 3,
            massen: mathPositionen.length,
            methode: "deterministic_math",
            gewerk: selectedGewerk,
          }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
        }
        // If calcMassen returned empty, fall through to Claude
      }

      // ═══ FALLBACK: Claude-based calculation for unsupported gewerke or empty math results ═══
      const gewerkPrompt = gewerkPrompts[selectedGewerk] || gewerkPrompts.allgemein

      const kalkSystem = `Du bist ein erfahrener österreichischer Baukalkulator.

GEWÄHLTES GEWERK: ${selectedGewerk.toUpperCase()}
${gewerkPrompt}

BERECHNUNGSFORMAT: Jeder Schritt: Beschreibung | Anz × L × B × H = Zwischensumme
ROHBAUMASS verwenden (Fertigmaß + 0.24m)!
Antworte NUR mit validem JSON.`

      const kalkUser = `Geometriedaten:\n${JSON.stringify(geo)}\n\nErstelle professionelle Massenermittlung.
JSON: {"positionen":[{"pos_nr":"","beschreibung":"","gewerk":"","raum_referenz":"","berechnung":[""],"endsumme":0,"einheit":"","konfidenz":0.9}],"zusammenfassung":{},"gesamt_konfidenz":0.88}`

      const kalk = await callClaude(cfg.value, kalkSystem,
        [{ type: "text", text: kalkUser }],
        32000)

      for (const p of (kalk.positionen || []))
        await sb.from("massen").insert({
          plan_id,
          pos_nr: p.pos_nr || "",
          beschreibung: p.beschreibung || "",
          gewerk: p.gewerk || "",
          raum_referenz: p.raum_referenz || "",
          berechnung: p.berechnung || [],
          endsumme: p.endsumme || 0,
          einheit: p.einheit || "",
          konfidenz: Math.round((p.konfidenz || 0.5) * 100),
        })

      const log = plan.agent_log || {}
      log.step2 = { ts: new Date().toISOString(), methode: "claude_fallback", gewerk: selectedGewerk, pos: (kalk.positionen||[]).length, zf: kalk.zusammenfassung }
      await sb.from("plaene").update({ agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: "step2_done",
        next_step: 3,
        massen: (kalk.positionen||[]).length,
        methode: "claude_fallback",
        zusammenfassung: kalk.zusammenfassung || {},
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    // ========== STEP 3: Kritik ==========
    if (step === 3) {
      const log = plan.agent_log || {}

      const kritik = await callClaude(cfg.value,
        `Du bist ein unabhängiger Prüfingenieur für Massenermittlung.

Bewerte die Analyse und Kalkulation:
1. Raumgrößen plausibel? (Wohnzimmer 15-40m², Bad 5-12m², WC 1.5-4m², Vorraum 3-10m²)
2. Berechnungen korrekt? Stimmen die Abzugsregeln?
3. Alles erfasst? Fehlen Räume, Fenster, Türen?
4. Sind die Einheiten korrekt? (m², m, lfm, Stk)
5. Stimmen die Summen?

STATUS:
- AKZEPTIERT: Qualitätsscore ≥ 75
- NACHBESSERUNG: Qualitätsscore 50-74
- KRITISCH: Qualitätsscore < 50

Antworte NUR mit validem JSON, KEIN Markdown.`,
        [{ type: "text", text: `Prüfe diese Ergebnisse:\n${JSON.stringify({ step1: log.step1, step2: log.step2 })}\n\nJSON-Format:
{
  "status": "AKZEPTIERT",
  "qualitaets_score": 85,
  "warnungen": ["Warnung 1"],
  "empfehlungen": ["Empfehlung 1"],
  "details": {
    "raeume_plausibel": true,
    "berechnungen_korrekt": true,
    "vollstaendigkeit": true
  },
  "gesamt_konfidenz": 0.87
}` }])

      const k = Math.round((kritik.gesamt_konfidenz || 0.5) * 100)

      // Delete geo data to save space
      delete log.geo
      log.step3 = { ts: new Date().toISOString(), ...kritik }
      log.kritik = kritik
      await sb.from("plaene").update({ verarbeitet: true, gesamt_konfidenz: k, agent_log: log }).eq("id", plan_id)

      return new Response(JSON.stringify({
        status: kritik.status || "AKZEPTIERT",
        konfidenz: k,
        qualitaets_score: kritik.qualitaets_score || k,
        warnungen: kritik.warnungen || [],
        empfehlungen: kritik.empfehlungen || [],
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } })
    }

    throw new Error("step muss 1, 2 oder 3 sein")
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } })
  }
})
