---

# Workflow: Verkehrsunfall Haftpflicht (Fremdschaden)

## Falltyp-Kennung
FALLTYP: verkehrsunfall_haftpflicht
VARIANTEN: [auffahrunfall, vorfahrtsverletzung, abbiegeunfall, parkschaden, fahrstreifenwechsel, auffahren_auf_stauende]

## Beschreibung
Die Schadensregulierung hat streng nach der Differenzhypothese des Schadensrechts zu erfolgen, wonach der Mandant als Geschädigter wirtschaftlich exakt so zu stellen ist, wie er ohne das schädigende Unfallereignis stünde. Anspruchsgegner sind der Schädiger sowie dessen Kfz-Haftpflichtversicherer im Wege des Direktanspruchs gemäß § 115 VVG. Das Ziel ist die vollumfängliche Durchsetzung der objektiven Schadenspositionen, wobei der technischen Beweisbarkeit durch qualifizierte Sachverständigengutachten stets absolute Priorität gegenüber pauschalen, automatisierten Kürzungsargumenten der Versicherungswirtschaft einzuräumen ist.

## FRISTEN-GRUNDREGEL (gilt für ALLE Schriftstücke an Versicherungen)
Jedes Schreiben an eine gegnerische Versicherung oder einen Schädiger MUSS eine konkrete Frist enthalten. Versicherungen sind chronisch überlastet — ohne gesetzte Frist wird nicht reagiert.
- Erstanschreiben / Haftungsübernahme: 14 Tage ab Zugang
- Regulierungsaufforderung nach Gutachten: 14 Tage ab Zugang
- Widerspruch gegen Kürzung: 10 Tage Nachfrist
- Mahnung bei Zahlungsverzug: 10 Tage Nachfrist mit Klageandrohung
- Deckungsanfrage Rechtsschutzversicherung: 14 Tage
LOKI: Niemals ein Schreiben an eine Versicherung ohne explizite Frist erstellen. Standardformulierung: "...haben wir uns eine Frist bis zum [Datum] notiert."

## Minimaldaten für Erstanschreiben (PFLICHTFELDER)
Folgende Daten müssen in der Akte vorhanden sein, bevor ein Erstanschreiben erstellt werden kann:
- Vollmacht (Dokument unterschrieben und hochgeladen)
- Unfalldatum (PFLICHT)
- Unfallort (PFLICHT)
- Gegner-Kennzeichen
- Gegnerische Haftpflichtversicherung (Name)
NICHT erforderlich: Schaden-Nr. (ist oft bei Mandatsübernahme noch nicht bekannt — kein Hindernis!)
LOKI: Wenn alle Pflichtfelder vorhanden sind, sofort Erstanschreiben vorschlagen — nicht auf Gutachten warten, nicht auf Schaden-Nr. warten.

## Praxis-Hinweis Sachverständige
In der Praxis liefert der Sachverständige (SV) die Akte — mit oder ohne fertiges Gutachten:
- SV Typ A liefert fertiges Gutachten + Vollmacht direkt an die Kanzlei.
- SV Typ B liefert nur Fotos + Daten + Vollmacht — hält Gutachten zurück bis Haftungsübernahme bestätigt ist (schützt Mandanten bei fraglicher Schuldfrage).
In beiden Fällen gilt: Das Erstanschreiben geht SOFORT raus, sobald Minimaldaten vorhanden. Das Erstanschreiben dient auch als Schuldfrage-Sonde — die Reaktion der Versicherung zeigt frühzeitig ob Haftung unbestritten oder strittig ist.

## Typische Schadenspositionen
- Reparaturkosten (konkret oder fiktiv) gemäß § 249 Abs. 2 BGB
- Sachverständigenkosten (Grundhonorar und Nebenkosten unter Beachtung des Sachverständigenrisikos) gemäß § 249 BGB
- Merkantiler Minderwert als Entschädigung in Geld gemäß § 251 Abs. 1 BGB
- Mietwagenkosten oder Nutzungsausfallentschädigung für die Dauer der technischen Ausfallzeit gemäß § 249 BGB
- UPE-Aufschläge und Verbringungskosten bei regionaler Üblichkeit gemäß § 249 BGB
- Haushaltsführungsschaden bei unfallbedingter Einschränkung gemäß § 842 BGB
- Allgemeine Unkostenpauschale gemäß § 249 BGB
- Vorgerichtliche Rechtsanwaltskosten gemäß § 249 BGB
- Schmerzensgeld bei Personenschäden gemäß § 253 Abs. 2 BGB

## Workflow-Stufen

### Stufe 1: Mandatsannahme (Voraussetzungen: Erstkontakt erfolgt, Minimaldaten liegen vor)
Erkennungsmerkmale in der Akte: Vollmacht vorhanden, Fragebogen ausgefüllt mit Unfalldatum und Unfallort, gegnerische Versicherung bekannt, noch keine Korrespondenz mit der Gegenseite geführt.
Nächste Schritte:
- Vollmacht und Fragebogen auf Vollständigkeit prüfen (Pflichtfelder: Unfalldatum, Unfallort, Gegner-Kennzeichen, Versicherung).
- Falls gegnerische Versicherung noch unbekannt: Zentralruf der Autoversicherer über Kennzeichen kontaktieren.
- Mandanten über Schadensminderungspflicht und Dispositionsfreiheit (fiktiv vs. konkret § 249 Abs. 2 BGB) aufklären.
- Sofort zu Stufe 2 übergehen — kein Warten auf Gutachten oder Schaden-Nr.
Typische Dokumente/Briefe: Vollmacht, ggf. Anschreiben Zentralruf.
Typische Fristen: Keine gesetzliche Frist, aber interne Bearbeitung innerhalb von 24 Stunden anstreben.
ki_memory-Schlüssel: "mandat_erfasst_minimaldaten_vollstaendig"

### Stufe 2: Erstanschreiben Doppelpack — Versicherung UND Mandant (Voraussetzungen: Minimaldaten vollständig)
Erkennungsmerkmale Stufe 2 GESAMT (alle drei Unterschritte beachten!):
  2A OFFEN: Vollmacht vorhanden, Unfalldatum + Unfallort bekannt, Versicherung bekannt, KEIN generierter Brief an Versicherung vorhanden → Erstanschreiben Versicherung vorschlagen.
  2A ERLEDIGT: Generierter Brief mit empfaenger="versicherung" in GENERIERTE BRIEFE vorhanden.
  2A VERSENDET: Zusätzlich E-Mail-Dokument (Titel beginnt mit "E-Mail:") in DOKUMENTE vorhanden.
  2B OFFEN: 2A erledigt/versendet, aber KEIN generierter Brief an Mandanten vorhanden → Erstanschreiben Mandant vorschlagen (NÄCHSTER SCHRITT!).
  2B ERLEDIGT: Generierter Brief mit empfaenger="mandant" vorhanden.
  2C OFFEN: Beide Briefe vorhanden, aber KEINE Aufgabe/Frist "Antwort Versicherung" → Aufgabe + 14-Tage-Frist erstellen.
LOKI-TRIGGER für 2A: Sobald Minimaldaten vorhanden und kein Versicherungsbrief existiert: "Alle Angaben für das Erstanschreiben liegen vor. Soll ich mit dem Entwurf an die Versicherung beginnen?"
LOKI-TRIGGER für 2B: Sobald Versicherungsbrief vorhanden/versendet und kein Mandantenbrief: "Das Erstanschreiben an die Versicherung wurde versendet. Jetzt erstelle ich das Informationsschreiben an die Mandantin."
Nächste Schritte (ZWINGEND SEQUENZIELL — niemals beide Briefe gleichzeitig erstellen):
- SCHRITT 2A — Erstanschreiben an Versicherung als Entwurf zeigen (KEIN direktes Speichern):
  Unfallhergang aus Fragebogen schildern, Haftungsübernahme gemäß § 115 VVG, §§ 7, 18 StVG fordern.
  Frist von 14 Tagen ab Zugang setzen (PFLICHT gemäß Fristen-Grundregel).
  Falls Gutachten bereits vorhanden: dem Schreiben beifügen und Schadenshöhe beziffern.
  Falls kein Gutachten vorhanden: Schreiben ohne Schadenshöhe, Nachforderung nach Gutachteneingang.
  → Entwurf zeigen, warten auf Bestätigung oder Korrekturwunsch des Users.
  → Erst nach ausdrücklicher Bestätigung ("Ja", "Ok", "Speichern") den Brief speichern.
- SCHRITT 2B — Erst NACH Speicherung von 2A: Entwurf an Mandant zeigen (KEIN direktes Speichern):
  Inhalt (kurz und knapp, drei Punkte):
  1. Mandatsübernahme bestätigen: Wir haben Ihr Mandat übernommen und sind ab sofort für Sie tätig.
  2. Anlage zur Kenntnisnahme: Das Erstanschreiben an die Versicherung ist beigefügt.
  3. Handlungsanweisung: Jegliche Kommunikation seitens der gegnerischen Versicherung oder sonstiger Dritter zu diesem Fall bitte NICHT beantworten — unkommentiert und unverändert an uns weiterleiten.
  Ton: Freundlich, klar, kein Juristendeutsch.
  → Entwurf zeigen, warten auf Bestätigung oder Korrekturwunsch des Users.
  → Erst nach ausdrücklicher Bestätigung den Brief speichern.
- SCHRITT 2C — Nach Speicherung beider Briefe: Aufgabe erstellen: "Antwort Versicherung abwarten — Frist [Datum in 14 Tagen]".
Warum das Mandantenschreiben unverzichtbar ist:
  Das Erstanschreiben an den Mandanten ist die erste und oft lange Zeit einzige schriftliche Bestätigung,
  dass die Kanzlei die Tätigkeit aufgenommen hat. Es dokumentiert nach außen (Mandant, Versicherung, Gericht)
  den Beginn der anwaltlichen Tätigkeit und damit den Gebührenanspruch der Kanzlei ab diesem Zeitpunkt.
  Ohne dieses Schreiben fehlt die Grundlage für spätere RVG-Gebühren.
Strategische Funktion des Versicherungsschreibens: Klärt die Schuldfrage im Vorfeld. Reaktion der Versicherung zeigt: Haftung unbestritten → Vollgas Regulierung. Haftung bestritten → andere Strategie (Stufe 3b).
Typische Dokumente/Briefe: Erstanschreiben Versicherung (Haftungsübernahme), Erstanschreiben Mandant (mit Anlage Versicherungsschreiben).
Typische Fristen: 14 Tage Antwortfrist an Versicherung (PFLICHT). Mandantenschreiben ohne Frist.
ki_memory-Schlüssel: "erstanschreiben_versicherung_versendet_frist_14_tage_notiert", "erstanschreiben_mandant_versendet"

### Stufe 3a: Haftung anerkannt — Regulierungsphase (Voraussetzungen: Versicherung hat Haftung bestätigt)
Erkennungsmerkmale in der Akte: Haftungsübernahme oder Regulierungsbereitschaft der Versicherung schriftlich bestätigt, Gutachten liegt vor oder wird jetzt fertiggestellt.
Nächste Schritte:
- Gutachten auf Vollständigkeit prüfen: UPE-Aufschläge, Verbringungskosten, Merkantiler Minderwert, Restwert.
- Vollständige Schadensaufstellung an Versicherung mit allen Positionen inkl. RVG-Gebühren.
- Bei Totalschaden: Sofort eigenen Restwert aus Gutachten sichern — Fahrzeug verkaufen BEVOR Versicherung Restwertbörse einschaltet.
- Frist für Zahlung: 14 Tage ab Zugang (PFLICHT).
- Aufgabe erstellen: "Zahlungseingang kontrollieren — Frist [Datum]".
Typische Dokumente/Briefe: Schadensaufstellung, Regulierungsaufforderung mit Gutachten, Mandantenanschreiben zur Information.
Typische Fristen: 14 Tage Zahlungsfrist (PFLICHT).
ki_memory-Schlüssel: "haftung_anerkannt_schadensaufstellung_versendet_frist_notiert"

### Stufe 3b: Haftung bestritten — Schuldfrage klären (Voraussetzungen: Versicherung bestreitet Haftung dem Grunde nach)
Erkennungsmerkmale in der Akte: Versicherung lehnt Haftung ab oder bestreitet Unfallhergang, keine Regulierungsbereitschaft.
Nächste Schritte:
- Sachverhalt rechtlich und technisch aufbereiten: Zeugen, Polizeibericht, Dashcam-Material, technische Unfallrekonstruktion.
- Ggf. Akteneinsicht bei Polizei oder Staatsanwaltschaft beantragen.
- Deckungsanfrage bei Rechtsschutzversicherung des Mandanten stellen (14 Tage Frist).
- Widerspruchsschreiben an Versicherung mit Darlegung des Anscheinsbeweises (§ 9 StVG i.V.m. § 254 BGB).
- Gutachten (SV Typ B) jetzt beauftragen falls noch nicht geschehen.
Typische Dokumente/Briefe: Widerspruch Haftungsablehnung, Deckungsanfrage RSV, Akteneinsichtsgesuch.
Typische Fristen: Widerspruch innerhalb 14 Tage, Deckungsanfrage RSV 14 Tage (PFLICHT).
ki_memory-Schlüssel: "haftung_bestritten_widerspruch_versendet_deckungsanfrage_gestellt"

### Stufe 4: Abwehr unberechtigter Kürzungen und Prüfberichte (Voraussetzungen: Versicherung hat Teilzahlung geleistet und Prüfbericht übersandt)
Erkennungsmerkmale in der Akte: Zahlungseingang entspricht nicht der Forderungssumme, automatisierter Prüfbericht (z.B. ControlExpert, Audatex) liegt vor, Stundenverrechnungssätze oder Nebenkosten wurden gestrichen.
Nächste Schritte:
- Prüfbericht als unbeachtlichen Parteivortrag zurückweisen: kein physisch besichtigtes Gutachten, daher keine Beweiskraft.
- Werkstatt- und Sachverständigenrisiko geltend machen: Risiko überhöhter Rechnungen trägt der Schädiger, nicht der Mandant.
- Bei fiktiver Abrechnung: Verweis auf freie Werkstätten abwehren wenn Fahrzeug jünger als 3 Jahre oder lückenlos scheckheftgepflegt.
- Nachforderungsschreiben mit konkretem Differenzbetrag und Klageandrohung.
- Frist: 10 Tage Nachfrist (PFLICHT).
Typische Dokumente/Briefe: Widerspruchsschreiben gegen Prüfbericht, Nachforderungsanschreiben mit Klageandrohung.
Typische Fristen: 10 Tage Nachfrist (PFLICHT).
ki_memory-Schlüssel: "widerspruch_kuerzung_versendet_nachfrist_10_tage_notiert"

### Stufe 5: Klagevorbereitung und gerichtliche Durchsetzung (Voraussetzungen: Außergerichtliche Nachfrist fruchtlos verstrichen)
Erkennungsmerkmale in der Akte: Versicherung verweigert endgültig Nachregulierung, Deckungszusage RSV liegt vor oder Mandant wünscht Selbstzahlermandat.
Nächste Schritte:
- Klageschrift unter strikter Darlegung der technischen Kausalität und der Differenzhypothese.
- Zessionsfalle vermeiden: Bei noch nicht bezahlten Werkstatt- oder Gutachterkosten zwingend Zahlung direkt an Zessionar beantragen.
- Gerichtsstand prüfen: Wohnort Kläger oder Unfallort (§ 20 StVG — fliegender Gerichtsstand).
Typische Dokumente/Briefe: Deckungsanfrage RSV Klageverfahren, Klageschrift.
Typische Fristen: Klage unter Beachtung der dreijährigen Regelverjährung (§ 195 BGB) einreichen.
ki_memory-Schlüssel: "klage_eingereicht_verfahren_anhaengig"

### Stufe 6: Aktenabschluss und Kostenfestsetzung (Voraussetzungen: Rechtskräftiges Urteil, Vergleich oder vollständige Zahlung)
Erkennungsmerkmale in der Akte: Fremdgeldkonto ausgeglichen, Hauptforderung und Zinsen reguliert.
Nächste Schritte:
- Kostenfestsetzungsantrag gemäß § 103 ff. ZPO bei Obsiegen einreichen.
- Fremdgelder an Mandanten auskehren und Endabrechnung mit RSV erstellen.
- Akte auf "Geschlossen" setzen, Archivierungsfrist 10 Jahre notieren.
Typische Dokumente/Briefe: Kostenfestsetzungsantrag, Endabrechnungsschreiben an Mandant und RSV.
Typische Fristen: Auskehrung Fremdgeld innerhalb 3 Tage nach Zahlungseingang.
ki_memory-Schlüssel: "akte_abgerechnet_und_abgeschlossen"

## Typische Fallstricke
- Erstanschreiben ohne Frist: Versicherungen reagieren ohne gesetzte Frist regelmäßig nicht — immer 14 Tage Frist setzen, nie "baldmöglichst".
- Zessionsfalle im Klageverfahren: Klagt Werkstatt/SV aus abgetretenem Recht, entfällt Schutz des Werkstattrisikos. Klage im Namen des Geschädigten auf Zahlung an Dritten (Zug-um-Zug).
- Restwertbörsen-Falle bei Totalschaden: Meldet man Totalschaden unbegutachtet der Versicherung, schaltet diese das Fahrzeug in überregionale Restwertbörsen — künstlich überhöhter Restwert mindert Auszahlung. Eigenes Gutachten MUSS vor Meldung vorliegen.
- Unzureichende Abgrenzung von Vorschäden: Vorschaden technisch nicht differenziert → kompletter Verlust des Schadensersatzanspruchs nach § 287 ZPO.
- Fiktive Abrechnung und Vorsteuer: Bei fiktiver Abrechnung darf keine MwSt. gefordert werden.
- Verbringungskosten und UPE-Aufschläge bei fiktiver Abrechnung: Nur erstattungsfähig wenn Sachverständiger deren regionalen Anfall branchenüblich bestätigt.
- Haushaltsführungsschaden: Ohne detailliertes zeitnahes Haushalts-Tagebuch regelmäßig nicht durchsetzbar.
- Anscheinsbeweis: Bei Auffahrunfall oder Spurwechsel spricht Anschein gegen den Auffahrenden — harte technische Fakten nötig um diesen zu erschüttern.
- Automatisierte Prüfberichte (ControlExpert etc.): Nie unkommentiert hinnehmen — schreibtischgefertigter Bericht ohne Fahrzeugbesichtigung entkräftet qualifiziertes Sachverständigengutachten nicht.

## Erkennungsmerkmale für automatische Falltypzuordnung
Verkehrsunfall, Haftpflichtschaden, 115 VVG, 249 BGB, Differenzhypothese, Sachverständigengutachten, fiktive Abrechnung, konkrete Abrechnung, Prüfbericht, ControlExpert, Werkstattrisiko, Sachverständigenrisiko, UPE-Aufschläge, Verbringungskosten, Nutzungsausfallentschädigung, Merkantiler Minderwert, Vorschaden, 287 ZPO, Anscheinsbeweis, Bagatellschaden, Totalschaden, Restwertbörse, Schmerzensgeld, Haushaltsführungsschaden, Zessionsfalle, Reparaturkostenübernahmebestätigung, Erstanschreiben, Haftungsübernahme, Schuldfrage, Vollmacht, Kfz-Gutachten, Unfallhergang, Kennzeichen, Gegnerische Versicherung

---
