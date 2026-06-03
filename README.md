
# 🔋 SmartPriceCharge v4.3.31 (Redundanz Edition / Türsteher Modus) für Home Assistant

**Intelligente Hausakku- & E-Auto-Steuerung für dynamische Strompreise (Tibber) & PV-Überschuss – Optimiert für Nulleinspeisung, maximalen Eigenverbrauch und KI-gestützte Analyse.**

Dieses AppDaemon-Skript verwandelt dein Smart Home in einen intelligenten Hybrid-Strom-Broker. Es steuert deinen Wechselrichter (primär GoodWe) und deine Wallbox (go-e Charger) basierend auf Tibber-Preisen, Solar-Prognosen und deinem Hausverbrauch, um die Stromkosten zu minimieren und die Hardware zu schonen.

---

## ✨ Was ist neu? (Changelog v4.1 ➔ v4.3.31)

Das Skript wurde massiv für die **Unabhängigkeit von Autohersteller-Cloud-Diensten** (insb. VW) und die perfekte Symbiose mit der go-e Wallbox umgebaut:

* 🛡️ **Der "Türsteher-Modus" (VW API Fallback & Redundanz):** Volkswagen blockiert zunehmend Drittanbieter-APIs (Error 403). Dieses Skript fängt den Fehler ab! Es verlässt sich nicht mehr zwingend auf die VW-Cloud. Stattdessen liest es den SoC des Autos über Tibber (`sensor.id_4_ladezustand_2`) aus. Sobald das in Home Assistant eingestellte Ziel erreicht ist, kappt das Skript der Wallbox hart den Strom.
* 🌗 **Trennung von Netz- und PV-Ziel:** Das System ist nun geizig beim Netzkauf, aber maximal offen für die Sonne:
  * **Nachts (Grid):** Lädt in den günstigsten Tibber-Stunden nur bis zu deinem eingestellten Dashboard-Slider (z. B. 40 %). Ladeverluste (10 % AC/DC) werden automatisch einkalkuliert.
  * **Tagsüber (PV):** Sobald PV-Überschuss da ist, lädt das Auto kostenlos immer bis mindestens **80 %** weiter, um die Sonne optimal zu nutzen.
* 🤝 **PV-Delegation (Anti-Ping-Pong):** Das Python-Skript greift bei PV-Überschuss nicht mehr manuell ein. Es schaltet die Wallbox auf "Eco" & "Neutral" und übergibt die sekundengenaue PV-Feinregelung komplett an die go-e Wallbox (via HA Automation).
* 🔢 **Numeric APIv2 Mapping:** Behebt Übersetzungsfehler in Home Assistant. Das Skript spricht jetzt stur die Maschinensprache der go-e Wallbox (z.B. 0, 1, 2, 3, 4).
* 🏖️ **Dynamische Sommer-Bremse:** Das Skript blockiert nachts das Vollladen des Hausakkus, wenn morgen viel Sonne kommt – aber **nur**, wenn das E-Auto morgen auch zu Hause ist und den Strom nicht selbst braucht!

---

## 🔋 Smarte Hausakku-Steuerung (Das bewährte Herzstück)

* 🧠 **Dynamischer Smart Hold:** Die "Warte-Logik" passt sich deinem Akkustand an!
  * **Akku voll:** Nutzt den Akku auch bei mittelhohen Preisen, um Energieverschwendung zu vermeiden.
  * **Akku leer:** Spart die Energie exklusiv für den absoluten Preis-Peak des Tages auf.
* 📉 **Günstig Laden (Eco Charge):** Lädt den Hausakku nachts aus dem Netz, wenn der Strompreis extrem niedrig ist und die PV-Prognose für den kommenden Tag nicht ausreicht.
* ☀️ **Multi-Forecast PV-Integration:** Nutzt drei verschiedene Prognose-Werte (Aktuelle Stunde, Nächste Stunde, Rest des Tages) sowie einen Peak-Time-Sensor, um Wolkenphasen zu überbrücken und unnötiges Netzladen zu verhindern.
* 💰 **Kosten-Tracking:** Berechnet live die Ersparnis gegenüber einem Referenzpreis und trackt Ladekosten sowie Entlade-Gewinne für dein Dashboard.
* ❤️ **Safety Heartbeat:** Überwacht den Wechselrichter-Status und sendet Befehle alle 15 Minuten erneut, falls sie (z.B. durch WLAN-Probleme) nicht ankamen.
* 🚫 **Fokus auf Eigenverbrauch:** Die Logik ist speziell darauf ausgelegt, nicht ins Netz einzuspeisen, sondern den Akku exklusiv für den Hausverbrauch zu nutzen (Nulleinspeisung/Zero Export Optimierung).

---

## 🚗 E-Auto & Wallbox-Logik (Der Offline-Trick)

Da Auto-Hersteller Cloud-APIs oft sperren (wie aktuell VW), nutzt dieses Skript eine **Redundanz-Logik**, um dich zu 100 % unabhängig zu machen.

### Wie das Setup für VW-Fahrer (Offline-Trick) funktioniert:

1. **Auto auf 100 % stellen:** Du stellst im Auto selbst (oder in der VW-App) das Ladelimit **einmalig dauerhaft auf 100 %**.
2. **Dashboard ist der Boss:** Du steuerst dein Ladeziel ab sofort nur noch über den Slider in Home Assistant.
3. **Der Türsteher arbeitet:** Das Skript liest den Ladestand über deinen Tibber-Dongle aus. Sobald dein Home Assistant Slider-Wert erreicht ist, schaltet das Skript die Wallbox ab.
4. **VW-Sync (Bonus):** Funktioniert die VW-API doch einmal (z.B. via HACS), synchronisiert das Skript deinen Slider zur Sicherheit auch direkt mit der VW-Cloud. Fällt die Cloud aus, loggt das Skript einen Fehler, aber der Ladevorgang funktioniert dank "Türsteher" trotzdem perfekt!

### Weitere EV-Features:

* 🚀 **Der "WAF-Boost" (Wife Acceptance Factor):** Eine Notfall-Taste. Ignoriert Preise, schaltet die Wallbox sofort auf 11kW und zwingt den Hausakku in den Standby (`mode_backup`), damit das Auto nicht den teuren Haus-Speicher leersaugt.
* 📅 **Montags-Garantie (Pendler-Sicherheit):** Das System garantiert, dass das E-Auto jeden Montagmorgen (dynamisch bis zu deiner eingestellten Abfahrtszeit) einen definierten Mindestladestand (z.B. 80%) für den Arbeitsweg hat.

---

## 🤖 KI-Auswertung (Gemini-Ready)

Das Skript sammelt Systemdaten und triggert jeden Sonntag um 20:00 Uhr (oder manuell auf Knopfdruck) eine Schnittstelle zur Auswertung durch eine Künstliche Intelligenz. Diese generiert Optimierungspotenziale und liefert einen detaillierten Wochenbericht über deine Ersparnisse.

---

## 🛠 Voraussetzungen & Installation

* Home Assistant & AppDaemon Add-on.
* Tibber API Token.
* Wechselrichter Integration (z.B. GoodWe via HACS).
* E-Auto / Wallbox Integration (z.B. go-e Charger & Tibber / VW ID Integration).
* Solar Forecast (z.B. Solcast oder Forecast.Solar).

### 1. Tibber REST-Sensor anlegen

Füge dies in deine `configuration.yaml` ein (ersetze `DEIN_TIBBER_TOKEN`):

```yaml
sensor:
  - platform: rest
    name: Tibber Preise Vorhersage (REST)
    resource: [https://api.tibber.com/v1-beta/gql](https://api.tibber.com/v1-beta/gql)
    method: POST
    scan_interval: 300
    headers:
      Authorization: "Bearer DEIN_TIBBER_TOKEN"
      Content-Type: application/json
    payload: >-
      { "query": "{ viewer { homes { currentSubscription { priceInfo { today { total startsAt } tomorrow { total startsAt } } } } } }" }
    json_attributes_path: "$.data.viewer.homes[0].currentSubscription.priceInfo"
    value_template: "{{ value_json.today[0].total }}" 
    json_attributes:
      - today
      - tomorrow

```

### 2. Helfer erstellen (Input Helper)

Erstelle in Home Assistant folgende Entitäten unter *Einstellungen -> Geräte & Dienste -> Helfer*:

| **Typ** | **Entity ID** | **Beschreibung** |
| --- | --- | --- |
| **Schalter** | `input_boolean.tibber_smart_charge_app_aktiv` | Hauptschalter der App |
| **Schalter** | `input_boolean.tibber_guenstige_ladestunde` | Zeigt aktive Hausakku-Ladung an |
| **Schalter** | `input_boolean.ev_boost_mode` | Aktiviert sofortiges 11kW Laden (WAF-Boost) |
| **Button** | `input_button.start_ki_analyse` | Startet manuell die KI-Auswertung |
| **Nummer** | `input_number.batteriekapazitaet_kwh` | Größe des Hausakkus in kWh |
| **Nummer** | `input_number.ladeleistung_kw` | Max. AC-Ladeleistung Hausakku |
| **Nummer** | `input_number.ladeziel_soc_prozent` | Ziel-SoC des Hausakkus |
| **Nummer** | `input_number.ev_target_soc` | **Tages-Ziel** des E-Autos (Tibber-Limit) |
| **Nummer** | `input_number.ev_montag_sicherheits_soc` | **Pendler-Ziel** für Montagmorgen |
| **Uhrzeit** | `input_datetime.ev_montag_abfahrtszeit` | Abfahrtszeit am Montag (z.B. 08:30) |
| **Nummer** | `input_number.tibber_entladeschwelle...` | Preislimit für Hausakku-Entladung |
| **Text** | `input_text.tibber_smart_charge_status` | Aktueller Status-Text Hausakku |

*(Hinweis: Für das detaillierte Kosten-Tracking werden zusätzliche `input_number` Helfer für Monat/Gesamt benötigt, siehe Code-Kommentare).*

### 3. PV-Delegation Automation (go-e Charger)

Damit die Wallbox den PV-Strom absolut sekundengenau regelt, erstelle diese Automation direkt in Home Assistant:

```yaml
alias: "Wallbox: PV-Überschuss synchronisieren (go-e)"
mode: single
triggers:
  - trigger: time_pattern
    seconds: /10
actions:
  - action: goecharger_api2.set_pv_data
    data:
      configid: DEINE_GOE_CONFIG_ID
      pgrid: "{{ states('sensor.active_power_total_inverted') | float(0) }}"
      ppv: "{{ states('sensor.pv_power') | float(0) }}"
      pakku: "{{ states('sensor.battery_power') | float(0) }}"

```

---

## 🧠 Entscheidungs-Logik (Prioritäten)

Das Skript prüft jede Minute den Status deines Hauses in einer strengen Hierarchie:

1. 🚀 **WAF-Boost (Prio 0):** Boost aktiv? -> Hausakku geht sofort in Standby, E-Auto lädt mit voller Leistung aus dem Netz.
2. 🔴 **Hochpreis-Entladung (Prio 1):** Preis > Schwelle? -> Haus wird aus dem Akku versorgt, Wallbox wird abgewürgt.
3. 🔵 **Smart Charge (Prio 2):** Billigste Stunden in der Nacht? -> Hausakku und/oder Auto laden günstig auf ihr jeweiliges Netz-Ziel.
4. ☀️ **PV-Optimierung (Prio 3):** PV dominant? -> Überschuss fließt bevorzugt in den Hausakku. Die Wallbox bekommt "Freigabe" (Eco-Modus) und regelt den PV-Strom für das Auto stufenlos intern.
5. ✋ **Smart Hold / Idle (Prio 4):** Standardbetrieb. Akku wird für spätere Preis-Peaks eingefroren, Wallbox bleibt aus.

---

## ⚠️ Haftungsausschluss & Lizenz

Nutzung auf eigene Gefahr. Das Skript greift aktiv in die Hardware-Steuerung (Wechselrichter & Wallbox API) ein. Lizenziert unter MIT-Lizenz.

```

```
