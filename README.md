# 🔋 SmartPriceCharge v4.1 (Ultimate Hybrid EMS) für Home Assistant

**Intelligente Hausakku- & E-Auto-Steuerung für dynamische Strompreise (Tibber) & PV-Überschuss – Optimiert für Nulleinspeisung, maximalen Eigenverbrauch und KI-gestützte Analyse.**

Dieses AppDaemon-Skript verwandelt dein Smart Home in einen intelligenten Strom-Broker. Es steuert deinen Wechselrichter (primär GoodWe) und deine Wallbox basierend auf Tibber-Preisen, Solar-Prognosen und deinem Hausverbrauch, um die Stromkosten zu minimieren und die Hardware zu schonen.

---

## ✨ Features

### 🔋 Smarte Hausakku-Steuerung (Das bewährte Herzstück)

* 🧠 **Dynamischer Smart Hold:** Die "Warte-Logik" passt sich jetzt deinem Akkustand an!
* 🔋 **Akku voll:** Die Logik wird "lockerer" und nutzt den Akku auch bei mittelhohen Preisen, um Energieverschwendung zu vermeiden.
* 🪫 **Akku leer:** Die Logik bleibt "streng" und spart die verbleibende Energie exklusiv für den absoluten Preis-Peak des Tages auf.


* 📉 **Günstig Laden (Eco Charge):** Lädt den Akku automatisch aus dem Netz, wenn der Strompreis sehr niedrig ist und die PV-Prognose für den Tag nicht ausreicht.
* ☀️ **Multi-Forecast PV-Integration:** Nutzt drei verschiedene Prognose-Werte (Aktuelle Stunde, Nächste Stunde, Rest des Tages) sowie einen Peak-Time-Sensor, um Wolkenphasen zu überbrücken und unnötiges Netzladen zu verhindern.
* 💰 **Kosten-Tracking:** Berechnet live die Ersparnis gegenüber einem Referenzpreis und trackt Ladekosten sowie Entlade-Gewinne.
* ❤️ **Safety Heartbeat:** Überwacht den Wechselrichter-Status und sendet Befehle erneut, falls sie (z.B. durch WLAN-Probleme) nicht angekommen sind.
* 🚫 **Fokus auf Eigenverbrauch:** Die Logik ist speziell darauf ausgelegt, *nicht* ins Netz einzuspeisen, sondern den Akku exklusiv für den Hausverbrauch zu nutzen (Nulleinspeisung/Zero Export Optimierung).
* 🏖️ **Sommer-Bremse:** Wird für morgen viel Sonne vorhergesagt (> 10 kWh), blockiert das Skript das Vollladen des Akkus in der Nacht, um Platz für den kostenlosen Sonnenstrom zu lassen.

### 🚗 E-Auto & Wallbox-Logik (Neu in v4.1)

* 🌤️ **PV-Aware Charging:** Das Skript zieht die erwartete PV-Energie für den kommenden Tag von den benötigten Netz-Ladeslots der Nacht ab. Die Sonne lädt mit, das Netz wird geschont.
* 🚀 **Der "WAF-Boost" (Wife Acceptance Factor):** Eine Notfall-Taste. Das Skript ignoriert Preise, schaltet die Wallbox ein und zwingt den Hausakku in den Standby (`mode_backup`), damit das Auto nicht den teuren Haus-Speicher leersaugt.
* 🔄 **Master-Sync mit API-Schonung:** Ladeziele aus dem Dashboard werden intelligent (mit 3 Sekunden Debounce) an das Auto (z.B. VW-Cloud) gesendet, um Account-Sperren wegen API-Spamming zu verhindern.
* 🛡️ **Auto-Reset (Care Mode):** Wird das Auto für weite Fahrten auf 100% geladen, setzt das Skript den Dashboard-Regler danach automatisch auf schonende 80% zurück.
* 📅 **Montags-Garantie:** Das System garantiert, dass das E-Auto jeden Montagmorgen einen definierten Mindestladestand (z.B. 75%) für den Arbeitsweg hat.
* 🤝 **Gentleman-Stopp:** Das Skript kappt der Wallbox niemals hart den Strom. Es stoppt erst das Auto per Software und lässt das Wallbox-Relais erst 60 Sekunden später sanft abfallen.

### 🤖 KI-Auswertung

* 🧠 **KI-Analyse (Gemini-Ready):** Das Skript sammelt Systemdaten und triggert jeden Sonntag um 20:00 Uhr (oder manuell auf Knopfdruck) eine Schnittstelle zur Auswertung durch eine Künstliche Intelligenz, um Optimierungspotenziale zu generieren.

---

## 🛠 Voraussetzungen

1. **Home Assistant**.
2. **AppDaemon** Add-on.
3. **Tibber API Token**.
4. **Wechselrichter Integration** (z.B. GoodWe via HACS).
5. **E-Auto / Wallbox Integration** (z.B. go-e Charger & VW ID Integration).
6. **Solar Forecast** (z.B. Solcast oder Forecast.Solar).

---

## 🚀 Installation

### 1. Tibber REST-Sensor anlegen

Füge dies in deine `configuration.yaml` ein (ersetze `DEIN_TIBBER_TOKEN`):

```yaml
sensor:
  - platform: rest
    name: Tibber Preise Vorhersage (REST)
    resource: https://api.tibber.com/v1-beta/gql
    method: POST
    scan_interval: 300
    headers:
      Authorization: "Bearer DEIN_TIBBER_TOKEN"
      Content-Type: application/json
    payload: >-
      {
        "query": "{ viewer { homes { currentSubscription { priceInfo { today { total startsAt } tomorrow { total startsAt } } } } } }"
      }
    json_attributes_path: "$.data.viewer.homes[0].currentSubscription.priceInfo"
    value_template: "{{ value_json.today[0].total }}" 
    json_attributes:
      - today
      - tomorrow

```

### 2. Helfer erstellen (Input Helper)

Erstelle in Home Assistant folgende Entitäten unter **Einstellungen -> Geräte & Dienste -> Helfer**:

#### A) Steuerungs-Helfer (Notwendig)

| Typ | Entity ID | Beschreibung |
| --- | --- | --- |
| **Schalter** | `input_boolean.tibber_smart_charge_app_aktiv` | Hauptschalter der App |
| **Schalter** | `input_boolean.tibber_guenstige_ladestunde` | Zeigt aktive Ladung an (Read-Only) |
| **Schalter** | `input_boolean.ev_boost_mode` | **NEU:** Aktiviert sofortiges Laden (WAF-Boost) |
| **Button** | `input_button.start_ki_analyse` | **NEU:** Startet manuell die KI-Auswertung |
| **Nummer** | `input_number.batteriekapazitaet_kwh` | Größe des Akkus in kWh |
| **Nummer** | `input_number.ladeleistung_kw` | Max. AC-Ladeleistung |
| **Nummer** | `input_number.ladeziel_soc_prozent` | Ziel-SoC des Hausakkus |
| **Nummer** | `input_number.ev_target_soc` | **NEU:** Ziel-SoC des E-Autos (0-100%) |
| **Nummer** | `input_number.tibber_entladeschwelle_eur_per_kwh` | Preislimit für Entladung |
| **Nummer** | `input_number.referenz_strompreis_ohne_optimierung_eur_per_kwh` | Vergleichspreis für Statistik |
| **Nummer** | `input_number.anzahl_guenstigste_ladestunden` | Begrenzung der täglichen Ladedauer |
| **Text** | `input_text.tibber_smart_charge_status` | Aktueller Status-Text |
| **Text** | `input_text.tibber_smart_charge_monatsbericht` | Zusammenfassung der Ersparnisse |

#### B) Statistik-Helfer (Input Number)

* `input_number.tibber_smart_charge_kosten_monat` / `_gesamt`
* `input_number.tibber_smart_charge_ersparnis_monat` / `_lifetime_final`
* `input_number.tibber_smart_discharge_ersparnis_monat` / `_gesamt`
* `input_number.tibber_smart_charge_geladene_kwh_monat` / `_gesamt`
* `input_number.tibber_smart_pv_savings_monat` / `_gesamt`

---

## 🧠 Entscheidungs-Logik (Prioritäten)

Das Skript prüft jede Minute den Status in dieser Reihenfolge:

1. 🚀 **WAF-Boost (Prio 0):** Boost aktiv? -> Hausakku Standby, E-Auto Laden aus Netz.
2. 🔴 **Hochpreis-Entladung (Prio 1):** Preis > Schwelle? -> Haus aus Akku versorgen.
3. 🔵 **Smart Charge (Prio 2):** Billigster Slot oder Zeitmangel? -> Akku/Auto laden.
4. ☀️ **PV-Optimierung (Prio 3):** Sonne scheint (>1kW)? -> Eigenverbrauch/Laden.
5. ✋ **Smart Hold / Idle (Prio 4):** Späterer Preis-Peak? -> Akku einfrieren für Peak-Nutzung.

---

## ⚠️ Haftungsausschluss & Lizenz

Nutzung auf eigene Gefahr. Das Skript greift aktiv in die Hardware-Steuerung ein. Lizenziert unter MIT-Lizenz.

---
