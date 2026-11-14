# IR Remote HTTP Bridge

Home-Assistant-Integration, die Infrarot-Fernbedienungen als Dashboard-Karten nachbildet.
Gesendet und gelernt wird über einen IR-Blaster an einem **Hubitat**-Hub
(Treiber [„Tuya Zigbee IR Remote Control“](https://github.com/luckygerbils/hubitat-tuya-zigbee-ir)),
angesprochen über die **Maker API**.

- Jede eingerichtete Fernbedienung bekommt ihre **eigene Karte** (eigener Kartentyp in der Kartenauswahl).
- **Lernmodus** in der Karte: Taste antippen → der Blaster wartet auf das Signal der Originalfernbedienung →
  Home Assistant speichert den Code bei dieser Taste.
- **Normalmodus**: Taste antippen → Code wird gesendet.
- Zusätzlich gibt es pro Taste eine `button`-Entität für Automationen und Skripte.
- Eigene Fernbedienungen lassen sich mit einer **SVG-Datei + JSON-Definition** hinzufügen.

Mitgeliefert: **EIZO FR-19** und eine **Kamin-/Heizlüfter-Fernbedienung**.

## Installation (HACS)

1. HACS → Menü (⋮) → **Benutzerdefinierte Repositories**
2. Repository `https://github.com/acidcoke/ha-ir-remote-http-bridge`, Typ **Integration** → Hinzufügen
3. „IR Remote HTTP Bridge“ in HACS suchen, herunterladen und Home Assistant neu starten

Die Karte wird von der Integration automatisch geladen – es muss keine Lovelace-Ressource angelegt werden.

## Einrichtung

Voraussetzung in Hubitat: Der IR-Blaster ist in der App **Maker API** ausgewählt.

1. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „IR Remote HTTP Bridge“
2. Eine beliebige URL aus der Maker-API-App einfügen, z. B.
   `http://192.168.1.10/apps/api/38/devices?access_token=…` (das Token wird aus der URL übernommen)
3. IR-Blaster wählen (entfällt, wenn nur ein passendes Gerät freigegeben ist)
4. Fernbedienungs-Layout wählen und einen Namen vergeben

Für jede weitere Fernbedienung die Integration erneut hinzufügen; die Verbindungsdaten sind dann vorausgefüllt.
Mehrere Fernbedienungen können denselben Blaster nutzen.

## Karte

Nach dem Hinzufügen einer Fernbedienung die Seite einmal neu laden. Danach erscheint sie im Dashboard unter
**Karte hinzufügen** mit ihrem Namen. In YAML:

```yaml
type: custom:ir-remote-card-monitor   # „monitor“ = Name der Fernbedienung als Slug
title: Monitor                        # optional
max_width: 280                        # optional, Breite der Zeichnung in px
allow_learning: true                  # optional, false blendet den Lernmodus aus
```

**Lernen:** „Lernmodus“ antippen. Tasten ohne Code sind orange, gelernte grün umrandet. Eine Taste antippen,
die Originalfernbedienung auf den Blaster richten und die Taste drücken. Bei bereits gelernten Tasten wird
nachgefragt (Neu lernen / Testen / Löschen). Mit „Fertig“ zurück in den Normalmodus. Der Lernmodus ist nur
für Administratoren sichtbar.

## Eigene Fernbedienungen

Zwei Dateien mit gleichem Namen in `<config>/ir_remote_http_bridge/` ablegen, z. B. `tv.json` und `tv.svg`,
anschließend die Integration erneut hinzufügen (die Dateien werden dabei neu eingelesen).

`tv.json`:

```json
{
  "name": "Wohnzimmer TV",
  "manufacturer": "ACME",
  "model": "RC-1",
  "buttons": [
    { "id": "power", "name": "Power", "icon": "mdi:power" },
    { "id": "vol_up", "name": "Lauter" }
  ]
}
```

`tv.svg`: beliebige SVG-Zeichnung der ganzen Fernbedienung. Jede Taste ist ein Element (am besten eine Gruppe
`<g>`) mit dem Attribut `data-button="<id>"`, passend zur `id` in der JSON-Datei:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200">
  <rect width="100" height="200" rx="16" fill="#222"/>
  <g data-button="power">
    <circle cx="50" cy="30" r="12" fill="#c00"/>
  </g>
  <g data-button="vol_up">
    <circle cx="50" cy="80" r="12" fill="#555"/>
    <path d="M44 80h12M50 74v12" stroke="#fff" stroke-width="2"/>
  </g>
</svg>
```

- `id`: Kleinbuchstaben, Ziffern und `_`.
- Die klickbare Fläche ist das, was gezeichnet ist; für größere Trefferflächen eine Form mit `fill="transparent"` in die Gruppe legen.
- Eine eigene Datei mit derselben `id` wie ein mitgeliefertes Layout ersetzt dieses.
- Vorlagen: [`custom_components/ir_remote_http_bridge/remotes/`](custom_components/ir_remote_http_bridge/remotes).

## Optionen

Über **Konfigurieren** am Eintrag:

- **Codes senden** – *Per Name* (Standard): Der Hubitat-Treiber speichert jeden gelernten Code zusätzlich unter
  einem Namen (`ha_…_<taste>`); gesendet wird `sendCode(<Name>)`. *Rohcode*: Der in Home Assistant gespeicherte
  Base64-Code wird direkt gesendet – nötig, wenn die Codes im Treiber nicht (mehr) vorhanden sind.
- **Lern-Timeout** – Wartezeit auf das Signal (Standard 30 s).

Über **Neu konfigurieren** lassen sich URL, Token und Geräte-ID ändern; gelernte Codes bleiben erhalten.
Die Codes liegen in `.storage/ir_remote_http_bridge.<entry_id>` und werden beim Löschen des Eintrags entfernt.

## Hinweise

- Ein Code gilt als gelernt, sobald sich das Attribut `lastLearnedCode` des Blasters ändert (Abfrage jede Sekunde).
- Der Treiber kennt keinen Befehl zum Abbrechen: Nach einem Timeout bleibt der Blaster im Lernmodus, bis er ein Signal empfängt.

## Entwicklung

```bash
pip install -r requirements_test.txt
```

```bash
pytest
```
