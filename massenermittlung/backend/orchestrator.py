"""
Orchestrator - Koordination aller AI-Agenten für die Massenermittlung.

Steuerungsfluss:
1. Lern-Agent: Bestehende Regeln laden
2. Parser-Agent: PDF-Textextraktion
3. Geometrie-Agent: Bauobjekt-Interpretation
4. Kalkulations-Agent: Massenberechnung
5. Kritik-Agent: Qualitätskontrolle

Bei niedriger Konfidenz oder Kritik-Beanstandung werden betroffene Agenten
erneut ausgeführt (max. 3 Iterationen).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional, Set

from agents import parser_run, geometrie_run, kalkulations_run, kritik_run, lern_run
from db.supabase_client import (
    get_lernregeln,
    get_korrekturen,
    create_masse,
    create_element,
    update_plan,
    create_lernregel,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
PARSER_CONFIDENCE_THRESHOLD = 0.70
QUALITY_WARN_THRESHOLD = 60
QUALITY_APPROVE_THRESHOLD = 80


class Orchestrator:
    """Koordiniert die AI-Agenten-Pipeline für die Massenermittlung."""

    def __init__(self):
        self.iteration = 0
        self.ergebnisse: dict[str, Any] = {}
        self.warnungen: list[str] = []
        self.websockets: set = set()

    async def _send_progress(self, schritt: str, fortschritt: int, details: str = ""):
        """Sendet WebSocket-Fortschrittsupdates an alle verbundenen Clients."""
        message = json.dumps({
            "typ": "fortschritt",
            "schritt": schritt,
            "fortschritt": fortschritt,
            "details": details,
            "iteration": self.iteration,
            "zeitstempel": datetime.now(timezone.utc).isoformat(),
        })

        disconnected = set()
        for ws in self.websockets:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)

        self.websockets -= disconnected

    async def _run_lern_agent(self, firma_id: str, planbuero: str) -> dict:
        """Schritt 1: Lernregeln laden und Empfehlungen generieren."""
        await self._send_progress("lern_agent", 5, "Lade Lernregeln...")

        try:
            bisherige_regeln = get_lernregeln(firma_id)
            korrektur_historie = get_korrekturen(firma_id=firma_id)
        except Exception as e:
            logger.warning("Supabase-Abfrage für Lernregeln fehlgeschlagen: %s", e)
            bisherige_regeln = []
            korrektur_historie = []

        kontext = {
            "planbuero": planbuero,
            "firma_id": firma_id,
            "bisherige_regeln": bisherige_regeln,
            "korrektur_historie": korrektur_historie,
        }

        ergebnis = await lern_run(kontext)
        self.ergebnisse["lern"] = ergebnis

        await self._send_progress(
            "lern_agent", 10,
            f"{len(ergebnis.get('aktive_regeln', []))} Regeln geladen, "
            f"{len(ergebnis.get('empfehlungen', []))} Empfehlungen",
        )
        return ergebnis

    async def _run_parser_agent(self, pdf_path: str, lern_empfehlungen: list[str]) -> dict:
        """Schritt 2: PDF-Textextraktion."""
        await self._send_progress("parser_agent", 15, "Extrahiere Text aus PDF...")

        anweisung = ""
        if lern_empfehlungen:
            anweisung = "Lernregeln beachten:\n" + "\n".join(f"- {e}" for e in lern_empfehlungen)

        kontext = {"pdf_path": pdf_path}
        ergebnis = await parser_run(kontext, anweisung)
        self.ergebnisse["parser"] = ergebnis

        konfidenz = ergebnis.get("gesamt_konfidenz", 0)
        cluster_count = len(ergebnis.get("text_cluster", []))

        await self._send_progress(
            "parser_agent", 35,
            f"{cluster_count} Textcluster extrahiert, Konfidenz: {konfidenz:.0%}",
        )
        return ergebnis

    async def _run_geometrie_agent(self, parser_ergebnis: dict, lern_empfehlungen: list[str]) -> dict:
        """Schritt 3: Geometrie-Interpretation."""
        await self._send_progress("geometrie_agent", 40, "Interpretiere Bauobjekte...")

        anweisung = ""
        if lern_empfehlungen:
            anweisung = "Lernregeln beachten:\n" + "\n".join(f"- {e}" for e in lern_empfehlungen)

        kontext = {"parser_ergebnis": parser_ergebnis}
        ergebnis = await geometrie_run(kontext, anweisung)
        self.ergebnisse["geometrie"] = ergebnis

        await self._send_progress(
            "geometrie_agent", 55,
            f"{len(ergebnis.get('raeume', []))} Räume, "
            f"{len(ergebnis.get('fenster', []))} Fenster, "
            f"{len(ergebnis.get('tueren', []))} Türen erkannt",
        )
        return ergebnis

    async def _run_kalkulations_agent(self, geometrie_ergebnis: dict, lern_empfehlungen: list[str]) -> dict:
        """Schritt 4: Massenberechnung."""
        await self._send_progress("kalkulations_agent", 60, "Berechne Massen nach ÖNORM...")

        anweisung = ""
        if lern_empfehlungen:
            anweisung = "Lernregeln beachten:\n" + "\n".join(f"- {e}" for e in lern_empfehlungen)

        kontext = {"geometrie_ergebnis": geometrie_ergebnis}
        ergebnis = await kalkulations_run(kontext, anweisung)
        self.ergebnisse["kalkulation"] = ergebnis

        await self._send_progress(
            "kalkulations_agent", 75,
            f"{len(ergebnis.get('positionen', []))} Positionen berechnet",
        )
        return ergebnis

    async def _run_kritik_agent(self, parser_ergebnis: dict, geometrie_ergebnis: dict, kalkulations_ergebnis: dict) -> dict:
        """Schritt 5: Qualitätskontrolle."""
        await self._send_progress("kritik_agent", 80, "Prüfe Ergebnisse...")

        kontext = {
            "parser_ergebnis": parser_ergebnis,
            "geometrie_ergebnis": geometrie_ergebnis,
            "kalkulations_ergebnis": kalkulations_ergebnis,
        }
        ergebnis = await kritik_run(kontext)
        self.ergebnisse["kritik"] = ergebnis

        await self._send_progress(
            "kritik_agent", 90,
            f"Status: {ergebnis.get('status', 'UNBEKANNT')}, "
            f"Qualität: {ergebnis.get('gesamt_qualitaet', 0)}%",
        )
        return ergebnis

    async def _store_results(self, plan_id: str, firma_id: str):
        """Speichert Ergebnisse in Supabase."""
        await self._send_progress("speichern", 92, "Speichere Ergebnisse...")

        geometrie = self.ergebnisse.get("geometrie", {})
        kalkulation = self.ergebnisse.get("kalkulation", {})
        kritik = self.ergebnisse.get("kritik", {})

        try:
            # Store elements (rooms, windows, doors)
            for raum in geometrie.get("raeume", []):
                create_element(
                    plan_id=plan_id,
                    typ="raum",
                    bezeichnung=raum.get("name", ""),
                    daten=raum,
                    konfidenz=raum.get("konfidenz", 0),
                )

            for fenster in geometrie.get("fenster", []):
                create_element(
                    plan_id=plan_id,
                    typ="fenster",
                    bezeichnung=fenster.get("bezeichnung", ""),
                    daten=fenster,
                    konfidenz=fenster.get("konfidenz", 0),
                )

            for tuer in geometrie.get("tueren", []):
                create_element(
                    plan_id=plan_id,
                    typ="tuer",
                    bezeichnung=tuer.get("bezeichnung", ""),
                    daten=tuer,
                    konfidenz=tuer.get("konfidenz", 0),
                )

            # Store calculated quantities (massen)
            for position in kalkulation.get("positionen", []):
                create_masse(
                    plan_id=plan_id,
                    pos_nr=position.get("pos_nr", ""),
                    beschreibung=position.get("beschreibung", ""),
                    gewerk=position.get("gewerk", ""),
                    raum_referenz=position.get("raum_referenz", ""),
                    berechnung=position.get("berechnung", []),
                    endsumme=position.get("endsumme", 0),
                    einheit=position.get("einheit", ""),
                    konfidenz=position.get("konfidenz", 0),
                )

            # Store new learning rules
            lern = self.ergebnisse.get("lern", {})
            for neue_regel in lern.get("neue_regeln", []):
                try:
                    create_lernregel(
                        firma_id=firma_id,
                        planbuero=neue_regel.get("planbuero", ""),
                        gueltig_fuer=neue_regel.get("gueltig_fuer", ""),
                        agent=neue_regel.get("agent", ""),
                        beschreibung=neue_regel.get("beschreibung", ""),
                        korrektur_json=neue_regel,
                    )
                except Exception as e:
                    logger.warning("Lernregel konnte nicht gespeichert werden: %s", e)

            # Update plan with results
            qualitaet = kritik.get("gesamt_qualitaet", 0)
            update_plan(plan_id, {
                "verarbeitet": True,
                "gesamt_konfidenz": qualitaet,
                "agent_log": {
                    "parser_konfidenz": self.ergebnisse.get("parser", {}).get("gesamt_konfidenz", 0),
                    "geometrie_konfidenz": self.ergebnisse.get("geometrie", {}).get("gesamt_konfidenz", 0),
                    "kalkulation_konfidenz": kalkulation.get("gesamt_konfidenz", 0),
                    "kritik_status": kritik.get("status", ""),
                    "gesamt_qualitaet": qualitaet,
                    "iterationen": self.iteration,
                    "zusammenfassung": kalkulation.get("zusammenfassung", {}),
                    "warnungen": self.warnungen,
                },
            })

            await self._send_progress("speichern", 95, "Ergebnisse gespeichert")

        except Exception as e:
            logger.error("Fehler beim Speichern der Ergebnisse: %s", e, exc_info=True)
            self.warnungen.append(f"Speicherfehler: {str(e)}")

    async def run(
        self,
        pdf_path: str,
        firma_id: str,
        plan_id: str,
        websockets: Optional[set] = None,
    ) -> dict:
        """
        Führt die vollständige Massenermittlungs-Pipeline aus.

        Args:
            pdf_path: Pfad zur PDF-Datei.
            firma_id: ID der Firma in Supabase.
            plan_id: ID des Plans in Supabase.
            websockets: Set von WebSocket-Verbindungen für Fortschrittsupdates.

        Returns:
            Dict mit allen Ergebnissen und dem Gesamtstatus.
        """
        self.websockets = websockets or set()
        self.iteration = 0
        self.ergebnisse = {}
        self.warnungen = []

        logger.info("Orchestrator gestartet für Plan %s (Firma: %s)", plan_id, firma_id)
        await self._send_progress("start", 0, "Massenermittlung gestartet")

        try:
            # Step 1: Load learning rules
            lern_ergebnis = await self._run_lern_agent(firma_id, planbuero="")
            lern_empfehlungen = lern_ergebnis.get("empfehlungen", [])

            # Step 2: Parse PDF (with retry on low confidence)
            parser_ergebnis = await self._run_parser_agent(pdf_path, lern_empfehlungen)

            if parser_ergebnis.get("gesamt_konfidenz", 0) < PARSER_CONFIDENCE_THRESHOLD:
                self.warnungen.append(
                    f"Parser-Konfidenz niedrig ({parser_ergebnis['gesamt_konfidenz']:.0%}), "
                    "führe erneuten Parsing-Versuch durch"
                )
                logger.info("Parser-Konfidenz < 70%%, wiederhole Parsing")
                retry_anweisung = (
                    "WIEDERHOLUNG: Die vorherige Extraktion hatte niedrige Konfidenz. "
                    "Bitte besonders sorgfältig extrahieren und Cluster überprüfen."
                )
                kontext = {"pdf_path": pdf_path}
                parser_ergebnis = await parser_run(kontext, retry_anweisung)
                self.ergebnisse["parser"] = parser_ergebnis
                await self._send_progress(
                    "parser_agent", 35,
                    f"Parser wiederholt: Konfidenz jetzt {parser_ergebnis.get('gesamt_konfidenz', 0):.0%}",
                )

            # Iterative improvement loop
            geometrie_ergebnis = None
            kalkulations_ergebnis = None
            kritik_ergebnis = None

            while self.iteration < MAX_ITERATIONS:
                self.iteration += 1
                logger.info("Iteration %d/%d", self.iteration, MAX_ITERATIONS)

                # Step 3: Geometry interpretation
                if geometrie_ergebnis is None or self._should_rerun("geometrie", kritik_ergebnis):
                    verbesserung = self._get_improvement_instructions("geometrie", kritik_ergebnis)
                    empfehlungen = lern_empfehlungen.copy()
                    if verbesserung:
                        empfehlungen.append(f"NACHBESSERUNG: {verbesserung}")
                    geometrie_ergebnis = await self._run_geometrie_agent(parser_ergebnis, empfehlungen)

                # Step 4: Quantity calculation
                if kalkulations_ergebnis is None or self._should_rerun("kalkulation", kritik_ergebnis):
                    verbesserung = self._get_improvement_instructions("kalkulation", kritik_ergebnis)
                    empfehlungen = lern_empfehlungen.copy()
                    if verbesserung:
                        empfehlungen.append(f"NACHBESSERUNG: {verbesserung}")
                    kalkulations_ergebnis = await self._run_kalkulations_agent(geometrie_ergebnis, empfehlungen)

                # Step 5: Quality control
                kritik_ergebnis = await self._run_kritik_agent(
                    parser_ergebnis, geometrie_ergebnis, kalkulations_ergebnis,
                )

                # Check if accepted or if we've hit max iterations
                if kritik_ergebnis.get("status") == "AKZEPTIERT":
                    logger.info("Kritik-Agent: AKZEPTIERT nach Iteration %d", self.iteration)
                    break

                if kritik_ergebnis.get("status") == "KRITISCHER_FEHLER":
                    self.warnungen.append("Kritischer Fehler erkannt - Ergebnisse erfordern manuelle Prüfung")
                    break

                if self.iteration >= MAX_ITERATIONS:
                    self.warnungen.append(
                        f"Maximale Iterationen ({MAX_ITERATIONS}) erreicht - "
                        f"Qualität: {kritik_ergebnis.get('gesamt_qualitaet', 0)}%"
                    )
                    break

                logger.info(
                    "Nachbesserung erforderlich (Iteration %d): %s",
                    self.iteration,
                    ", ".join(kritik_ergebnis.get("verbesserungsanweisungen", [])),
                )

            # Store results in Supabase
            await self._store_results(plan_id, firma_id)

            # Determine final quality assessment
            qualitaet = kritik_ergebnis.get("gesamt_qualitaet", 0) if kritik_ergebnis else 0
            if qualitaet < QUALITY_WARN_THRESHOLD:
                qualitaets_bewertung = "WARNUNG_BENUTZER"
                self.warnungen.append(
                    f"Gesamtqualität unter {QUALITY_WARN_THRESHOLD}% - "
                    "manuelle Überprüfung dringend empfohlen"
                )
            elif qualitaet < QUALITY_APPROVE_THRESHOLD:
                qualitaets_bewertung = "MIT_WARNUNGEN"
            else:
                qualitaets_bewertung = "FREIGEGEBEN"

            ergebnis = {
                "status": "abgeschlossen",
                "qualitaets_bewertung": qualitaets_bewertung,
                "gesamt_qualitaet": qualitaet,
                "iterationen": self.iteration,
                "parser_ergebnis": self.ergebnisse.get("parser", {}),
                "geometrie_ergebnis": self.ergebnisse.get("geometrie", {}),
                "kalkulations_ergebnis": self.ergebnisse.get("kalkulation", {}),
                "kritik_ergebnis": self.ergebnisse.get("kritik", {}),
                "lern_ergebnis": self.ergebnisse.get("lern", {}),
                "warnungen": self.warnungen,
            }

            await self._send_progress("abgeschlossen", 100, f"Fertig - Qualität: {qualitaet}%")
            logger.info("Orchestrator abgeschlossen: Qualität=%d%%, Iterationen=%d", qualitaet, self.iteration)
            return ergebnis

        except Exception as e:
            logger.error("Orchestrator-Fehler: %s", e, exc_info=True)
            await self._send_progress("fehler", -1, f"Fehler: {str(e)}")
            return {
                "status": "fehler",
                "qualitaets_bewertung": "FEHLER",
                "gesamt_qualitaet": 0,
                "iterationen": self.iteration,
                "warnungen": self.warnungen + [f"Orchestrator-Fehler: {str(e)}"],
                "parser_ergebnis": self.ergebnisse.get("parser", {}),
                "geometrie_ergebnis": self.ergebnisse.get("geometrie", {}),
                "kalkulations_ergebnis": self.ergebnisse.get("kalkulation", {}),
                "kritik_ergebnis": self.ergebnisse.get("kritik", {}),
                "lern_ergebnis": self.ergebnisse.get("lern", {}),
            }

    def _should_rerun(self, bereich: str, kritik_ergebnis: Optional[dict]) -> bool:
        """Prüft ob ein Agent wiederholt werden muss basierend auf Kritik."""
        if kritik_ergebnis is None:
            return False
        if kritik_ergebnis.get("status") != "NACHBESSERUNG_ERFORDERLICH":
            return False

        fehler = kritik_ergebnis.get("fehler", [])
        return any(
            f.get("bereich") == bereich and f.get("kategorie") in ("KRITISCH", "WARNUNG")
            for f in fehler
        )

    def _get_improvement_instructions(self, bereich: str, kritik_ergebnis: Optional[dict]) -> str:
        """Extrahiert Verbesserungsanweisungen für einen bestimmten Bereich."""
        if kritik_ergebnis is None:
            return ""

        fehler = kritik_ergebnis.get("fehler", [])
        relevante_fehler = [
            f.get("korrekturvorschlag", f.get("beschreibung", ""))
            for f in fehler
            if f.get("bereich") == bereich
        ]

        anweisungen = kritik_ergebnis.get("verbesserungsanweisungen", [])
        relevante_anweisungen = [a for a in anweisungen if bereich.lower() in a.lower()]

        alle = relevante_fehler + relevante_anweisungen
        return " | ".join(alle) if alle else ""
