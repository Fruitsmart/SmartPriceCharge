# 🔋 TibberSmartCharge für Home Assistant (AppDaemon)

**Intelligente Batteriesteuerung für dynamische Strompreise (Tibber) & PV-Überschuss – Optimiert für Nulleinspeisung/Eigenverbrauch.**

Dieses AppDaemon-Skript verwandelt deinen Heimspeicher in einen intelligenten Strom-Broker. Es steuert deinen Wechselrichter (primär GoodWe, aber anpassbar) basierend auf Tibber-Preisen, Solar-Prognosen und deinem Hausverbrauch, um die Stromkosten zu minimieren.

-----

## ✨ Features

  * 🧠 **Dynamischer Smart Hold (Neu in v1.1b):** Die "Warte-Logik" passt sich jetzt deinem Akkustand an!
      * 🔋 **Akku voll:** Die Logik wird "lockerer" und nutzt den Akku auch bei mittelhohen Preisen, um Energieverschwendung zu vermeiden.
      * 🪫 **Akku leer:** Die Logik bleibt "streng" und spart die verbleibende Energie exklusiv für den absoluten Preis-Peak des Tages auf.
  * **📉 Günstig Laden (Eco Charge):** Lädt den Akku automatisch aus dem Netz, wenn der Strompreis sehr niedrig ist und die PV-Prognose für den Tag nicht ausreicht.
  * **🛑 Smart Hold (Spread-Logik):** Verhindert das Entladen des Akkus bei "mittleren" Preisen, wenn später am Tag ein extremer Preis-Peak erwartet wird. Der Akku wird für die teuerste Zeit "aufgespart".
  * **☀️ Multi-Forecast PV-Integration:** Nutzt drei verschiedene Prognose-Werte (Aktuelle Stunde, Nächste Stunde, Rest des Tages) sowie einen Peak-Time-Sensor, um Wolkenphasen zu überbrücken und unnötiges Netzladen zu verhindern.
  * **💰 Kosten-Tracking:** Berechnet live die Ersparnis gegenüber einem Referenzpreis und trackt Ladekosten sowie Entlade-Gewinne.
  * **❤️ Safety Heartbeat:** Überwacht den Wechselrichter-Status und sendet Befehle erneut, falls sie (z.B. durch WLAN-Probleme) nicht angekommen sind.
  * **🚫 Fokus auf Eigenverbrauch:** Die Logik ist speziell darauf ausgelegt, **nicht** ins Netz einzuspeisen, sondern den Akku exklusiv für den Hausverbrauch zu nutzen (Nulleinspeisung/Zero Export Optimierung).

-----

## 🛠 Voraussetzungen

1.  **Home Assistant** (installiert und laufend).
2.  **AppDaemon** Add-on in Home Assistant.
3.  **Tibber API Token** (erhältlich auf https://www.google.com/search?q=developer.tibber.com).
4.  **Wechselrichter Integration ** (getestet mit GoodWe (HACS), benötigt Entitäten zum Umschalten des Betriebsmodus).
5.  **Solar Forecast** (z.B. Solcast oder Forecast.Solar) für die Sensoren.

-----

## 🚀 Installation

### 1\. WICHTIG: Tibber REST-Sensor anlegen

Damit das Skript die Preise für den ganzen Tag und morgen im Voraus kennt, reicht der normale Tibber-Sensor oft nicht aus. Du musst einen **REST Sensor** in deiner `configuration.yaml` anlegen, der die Daten direkt von der Tibber API holt.

Füge dies in deine `configuration.yaml` ein (ersetze `DEIN_TIBBER_TOKEN` mit deinem echten Token):

```yaml
sensor:
  - platform: rest
    name: Tibber Preise Vorhersage (REST)
    resource: https://api.tibber.com/v1-beta/gql
    method: POST
    scan_interval: 300 # Alle 5 Minuten aktualisieren
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

*Starte Home Assistant nach dem Einfügen neu.*

### 2\. AppDaemon einrichten

Falls noch nicht geschehen, installiere das "AppDaemon" Add-on aus dem Home Assistant Store.

### 3\. Code kopieren

Erstelle eine Datei namens `tibber_smart_charge.py` im Verzeichnis `/addon_configs/a0d7b954_appdaemon/apps/` und füge den Python-Code dort ein.

### 4\. Helfer erstellen (Input Helper)

Damit das Skript funktioniert, musst du in Home Assistant unter **Einstellungen -\> Geräte & Dienste -\> Helfer** folgende Entitäten erstellen:

#### A) Steuerungs-Helfer (Notwendig)

| Typ | Name (Beispiel) | Entity ID | Beschreibung |
| :--- | :--- | :--- | :--- |
| **Schalter** | Tibber App Aktiv | `input_boolean.tibber_smart_charge_app_aktiv` | Hauptschalter |
| **Schalter** | Günstige Ladestunde | `input_boolean.tibber_guenstige_ladestunde` | Zeigt an, ob gerade geladen wird (Read-Only) |
| **Nummer** | Batteriekapazität | `input_number.batteriekapazitaet_kwh` | Größe des Akkus in kWh |
| **Nummer** | Ladeleistung | `input_number.ladeleistung_kw` | Max. AC-Ladeleistung (z.B. 3.0) |
| **Nummer** | Ladeziel SoC | `input_number.ladeziel_soc_prozent` | Bis wie viel % soll geladen werden? |
| **Nummer** | Entladeschwelle | `input_number.tibber_entladeschwelle_eur_per_kwh` | Preis, ab dem entladen werden darf |
| **Nummer** | Referenzpreis | `input_number.referenz_strompreis_ohne_optimierung_eur_per_kwh` | Vergleichspreis für Statistik |
| **Nummer** | Max Ladestunden | `input_number.anzahl_guenstigste_ladestunden` | Begrenzung der Ladedauer (z.B. 16) |
| **Text** | Status | `input_text.tibber_smart_charge_status` | Zeigt aktuellen Status an |
| **Text** | Monatsbericht | `input_text.tibber_smart_charge_monatsbericht` | Statistik-Text |

#### B) Statistik-Helfer (Für das Dashboard)

Erstelle diese als **Nummer (Input Number)**:

  * `input_number.tibber_smart_charge_kosten_monat`
  * `input_number.tibber_smart_charge_ersparnis_monat`
  * `input_number.tibber_smart_discharge_ersparnis_monat`
  * `input_number.tibber_smart_charge_geladene_kwh_monat`
  * `input_number.tibber_smart_pv_savings_monat`
  * `input_number.tibber_smart_charge_kosten_gesamt`
  * `input_number.tibber_charge_ersparnis_lifetime_final`
  * `input_number.tibber_smart_discharge_ersparnis_gesamt`
  * `input_number.tibber_smart_charge_geladene_kwh_gesamt`
  * `input_number.tibber_smart_pv_savings_gesamt`

*(Tipp: Du kannst die Namen anpassen, musst sie dann aber auch in der `apps.yaml` ändern).*

### 5\. Konfiguration (apps.yaml)

Öffne die Datei `/config/appdaemon/apps/apps.yaml` und füge folgenden Block ein.

```yaml
tibber_smart_charge:
  module: tibber_smart_charge_app
  class: TibberSmartCharge
  
  # --- Live Sensoren ---
  tibber_price_sensor_id: sensor.tibber_preise_vorhersage_rest # Dein neuer REST Sensor
  current_soc_sensor_id: sensor.battery_state_of_charge
  goodwe_operation_mode_entity_id: select.inverter_operation_mode
  
  # --- PV Prognosen ---
  pv_forecast_sensor_id: sensor.energy_next_hour
  pv_forecast_current_hour_sensor_id: sensor.energy_current_hour
  pv_forecast_today_remaining_sensor_id: sensor.energy_production_today_remaining
  pv_peak_time_sensor_id: sensor.power_highest_peak_time_today # ISO Format
  
  # --- Power Sensoren ---
  current_pv_power_sensor_id: sensor.pv_power
  battery_power_sensor_id: sensor.battery_power
  grid_power_import_export_sensor_id: sensor.active_power_total
  current_house_consumption_w_id: sensor.house_consumption

  # --- Einstellungen ---
  battery_efficiency_factor: 0.90
  pv_forecast_safety_factor: 0.50

  # --- Dynamische Spread Steuerung ---
  # Basis Spread (Gilt bei niedrigem Akkustand)
  min_price_spread_eur: 0.08
  
  # Stufe 1: Akku wird voller
  soc_threshold_medium: 80.0        # Ab 80% SoC...
  spread_medium_soc_eur: 0.15       # ...genügen 15 Cent Abstand (statt 8)
  
  # Stufe 2: Akku ist fast voll
  soc_threshold_high: 95.0          # Ab 95% SoC...
  spread_high_soc_eur: 0.25         # ...genügen 25 Cent Abstand (Akku muss leer werden!)
  
  # --- Verknüpfung zu deinen Helfern ---
  battery_capacity_kwh_id: input_number.batteriekapazitaet_kwh
  charger_power_kw_id: input_number.ladeleistung_kw
  ladeziel_soc_prozent_id: input_number.ladeziel_soc_prozent
  tibber_discharge_threshold_eur_per_kwh_id: input_number.tibber_entladeschwelle_eur_per_kwh
  min_soc_for_discharge_prozent_id: number.depth_of_discharge_on_grid # Oder Input Number
  charge_intervals_input_id: input_number.anzahl_guenstigste_ladestunden
  referenz_strompreis_id: input_number.referenz_strompreis_ohne_optimierung_eur_per_kwh
  
  # --- Status & Tracking ---
  dashboard_status_text_id: input_text.tibber_smart_charge_status
  app_enabled_switch_id: input_boolean.tibber_smart_charge_app_aktiv
  cheap_hour_toggle_id: input_boolean.tibber_guenstige_ladestunde
  next_charge_time_id: input_text.tibber_next_charge_time
  cheap_hours_text_id: input_text.gunstigsten_ladestunden
  monatsbericht_id: input_text.tibber_smart_charge_monatsbericht

  # Tracking Nummern
  kosten_monat_id: input_number.tibber_smart_charge_kosten_monat
  ersparnis_monat_id: input_number.tibber_smart_charge_ersparnis_monat
  discharge_ersparnis_monat_id: input_number.tibber_smart_discharge_ersparnis_monat
  geladene_kwh_monat_id: input_number.tibber_smart_charge_geladene_kwh_monat
  pv_savings_monat_id: input_number.tibber_smart_pv_savings_monat
  
  kosten_gesamt_id: input_number.tibber_smart_charge_kosten_gesamt
  ersparnis_gesamt_id: input_number.tibber_charge_ersparnis_lifetime_final
  discharge_ersparnis_gesamt_id: input_number.tibber_smart_discharge_ersparnis_gesamt
  geladene_kwh_gesamt_id: input_number.tibber_smart_charge_geladene_kwh_gesamt
  pv_savings_gesamt_id: input_number.tibber_smart_pv_savings_gesamt

  # --- Debugging ---
  debug_mode: false # false = Inverter schaltet wirklich! true = Simulation
  log_debug_level: true
```

-----

## 🧠 Wie es funktioniert (Die Logik)

Das Skript prüft jede Minute die Bedingungen und entscheidet nach folgender Priorität:

1.  **🔴 Hochpreis-Entladung (Prio 1):**
    Ist der aktuelle Strompreis höher als deine Schwelle (z.B. 30ct)?
    \-\> **Aktion:** Modus `General`. Der Akku versorgt das Haus.

2.  **🔵 Günstig Laden / Eco Charge (Prio 2):**
    Ist der Strompreis extrem niedrig (verglichen mit dem Tagesdurchschnitt) UND reicht die PV-Prognose für heute nicht aus?
    \-\> **Aktion:** Modus `Eco Charge`. Der Akku wird aus dem Netz geladen.

3.  **☀️ PV-Optimierung (Prio 3):**
    Scheint die Sonne stark genug?
    \-\> **Aktion:** Modus `General`. Überschuss geht in den Akku.

4.  **✋ Smart Hold / Warten (Prio 4):**
    Ist der Preis gerade "okay", aber in ein paar Stunden kommt ein **extremer Preis-Peak**?
    \-\> **Aktion:** Modus `Backup`. Der Akku wird weder geladen noch entladen ("eingefroren"). Wir sparen die Energie für den teuren Peak auf\!

5.  **🟢 Standardbetrieb (Prio 5):**
    Keine besonderen Vorkommnisse.
    \-\> **Aktion:** Modus `General` oder `Backup` (je nach PV-Status).

-----

## 📊 Dashboard Empfehlung (Markdown Karte)

Um den nächsten PV-Peak und den Strompreis im Dashboard korrekt anzuzeigen (auch bei 15-Minuten-Intervallen), nutze diesen Code für eine Markdown-Karte:

```yaml
type: markdown
content: >-
  {# --- PEAK BERECHNUNG --- #}
  {% set sensor_id = 'sensor.tibber_preise_vorhersage_rest' %}
  {% set prices = state_attr(sensor_id, 'today') %}
  {% set start_ts = as_timestamp(today_at("00:00")) %}
  {% set ns = namespace(max=0, time='-') %}

  {% if prices %}
    {# Automatische Erkennung ob Stunden (24) oder 15-Min (96) Werte #}
    {% set step = 900 if (prices | count) > 24 else 3600 %}
    
    {% for p in prices %}
       {% if p.total > ns.max %}
         {% set ns.max = p.total %}
         {% set ns.time = (start_ts + (loop.index0 * step)) | timestamp_custom('%H:%M') %}
       {% endif %}
    {% endfor %}
    
    **Peak heute:** {{ ns.max | round(3) }} € um {{ ns.time }} Uhr
  {% else %}
    Keine Daten.
  {% endif %}
```

-----

---

## ❤️ Unterstützung

Gefällt dir dieses Projekt? Wenn es dir hilft, Stromkosten zu sparen, freue ich mich über einen Kaffee ☕️

[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=fam.obst@live.de&item_name=TibberSmartCharge&currency_code=EUR)

## ⚠️ Haftungsausschluss

Die Nutzung dieses Skripts erfolgt auf eigene Gefahr. Es greift aktiv in die Steuerung deines Wechselrichters ein. Obwohl Sicherheitsmechanismen (wie der Debug-Mode und Heartbeat) integriert sind, übernehme ich keine Haftung für entladene Batterien zur falschen Zeit, unerwartete Stromkosten oder Hardware-Probleme. Bitte teste die Konfiguration zunächst mit `debug_mode: true`.

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe die [LICENSE](LICENSE) Datei für Details.
