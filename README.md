# 🔋 TibberSmartCharge für Home Assistant (AppDaemon)

**Intelligente Batteriesteuerung für dynamische Strompreise (Tibber) & PV-Überschuss – Optimiert für Nulleinspeisung/Eigenverbrauch.**

Dieses AppDaemon-Skript verwandelt deinen Heimspeicher in einen intelligenten Strom-Broker. Es steuert deinen Wechselrichter (primär GoodWe, aber anpassbar) basierend auf Tibber-Preisen, Solar-Prognosen und deinem Hausverbrauch, um die Stromkosten zu minimieren.

-----

## ✨ Features

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
3.  **Tibber Integration** (für die Strompreise).
4.  **Wechselrichter Integration** (getestet mit GoodWe, benötigt Entitäten zum Umschalten des Betriebsmodus).
5.  **Solar Forecast** (z.B. Solcast oder Forecast.Solar) für die Sensoren.

-----

## 🚀 Installation

### 1\. AppDaemon einrichten

Falls noch nicht geschehen, installiere das "AppDaemon" Add-on aus dem Home Assistant Store.

### 2\. Code kopieren

Erstelle eine Datei namens `tibber_smart_charge.py` im Verzeichnis `/config/appdaemon/apps/` und füge den Python-Code dort ein.

### 3\. Helfer erstellen (Input Helper)

Damit das Skript konfigurierbar ist, musst du in Home Assistant unter **Einstellungen -\> Geräte & Dienste -\> Helfer** folgende Entitäten erstellen:

| Typ | Name (Beispiel) | Entity ID (Beispiel) | Beschreibung |
| :--- | :--- | :--- | :--- |
| **Schalter** | Tibber App Aktiv | `input_boolean.tibber_smart_charge_app_aktiv` | Hauptschalter für die Automatisierung |
| **Nummer** | Batteriekapazität | `input_number.batteriekapazitaet_kwh` | Größe deines Akkus (z.B. 10.0) |
| **Nummer** | Ladeleistung | `input_number.ladeziel_soc_prozent` | Bis wie viel % soll geladen werden? |
| **Nummer** | Entladeschwelle | `input_number.tibber_entladeschwelle_eur_per_kwh` | Preis, ab dem entladen werden darf (z.B. 0.30) |
| **Nummer** | Referenzpreis | `input_number.referenz_strompreis...` | Vergleichspreis für Ersparnis-Rechnung |
| **Text** | Status | `input_text.tibber_smart_charge_status` | Zeigt an, was die App gerade macht |
| **Text** | Monatsbericht | `input_text.tibber_smart_charge_monatsbericht` | Statistik-Ausgabe |

*(Zusätzlich benötigst du Helfer für die Statistik-Zahlen, siehe `apps.yaml` Konfiguration)*

### 4\. Konfiguration (apps.yaml)

Öffne die Datei `/config/appdaemon/apps/apps.yaml` und füge folgenden Block ein. **Passe die Sensor-Namen an deine Umgebung an\!**

```yaml
tibber_smart_charge:
  module: tibber_smart_charge_app
  class: TibberSmartCharge
  
  # --- Live Sensoren ---
  tibber_price_sensor_id: sensor.electricity_price_zuhause # Dein Tibber Preis Sensor
  current_soc_sensor_id: sensor.battery_state_of_charge
  goodwe_operation_mode_entity_id: select.inverter_operation_mode
  
  # --- PV Prognosen (Wichtig!) ---
  pv_forecast_sensor_id: sensor.energy_next_hour
  pv_forecast_current_hour_sensor_id: sensor.energy_current_hour
  pv_forecast_today_remaining_sensor_id: sensor.energy_production_today_remaining
  pv_peak_time_sensor_id: sensor.power_highest_peak_time_today # ISO Format Zeitstempel
  
  # --- Power Sensoren ---
  current_pv_power_sensor_id: sensor.pv_power
  battery_power_sensor_id: sensor.battery_power
  grid_power_import_export_sensor_id: sensor.active_power_total
  current_house_consumption_w_id: sensor.house_consumption

  # --- Einstellungen ---
  battery_efficiency_factor: 0.90
  pv_forecast_safety_factor: 0.50
  min_price_spread_eur: 0.08 # Mindestabstand zum Peak, um "Hold" zu aktivieren
  
  # --- Verknüpfung zu deinen Helfern ---
  battery_capacity_kwh_id: input_number.batteriekapazitaet_kwh
  charger_power_kw_id: input_number.ladeleistung_kw
  ladeziel_soc_prozent_id: input_number.ladeziel_soc_prozent
  tibber_discharge_threshold_eur_per_kwh_id: input_number.tibber_entladeschwelle_eur_per_kwh
  min_soc_for_discharge_prozent_id: number.depth_of_discharge_on_grid # Oder Input Number
  
  # --- Status & Tracking ---
  dashboard_status_text_id: input_text.tibber_smart_charge_status
  app_enabled_switch_id: input_boolean.tibber_smart_charge_app_aktiv
  cheap_hour_toggle_id: input_boolean.tibber_guenstige_ladestunde
  next_charge_time_id: input_text.tibber_next_charge_time
  cheap_hours_text_id: input_text.gunstigsten_ladestunden
  monatsbericht_id: input_text.tibber_smart_charge_monatsbericht

  # Tracking Nummern (Erstelle diese Helfer für Statistiken)
  kosten_monat_id: input_number.tibber_smart_charge_kosten_monat
  ersparnis_monat_id: input_number.tibber_smart_charge_ersparnis_monat
  discharge_ersparnis_monat_id: input_number.tibber_smart_discharge_ersparnis_monat
  geladene_kwh_monat_id: input_number.tibber_smart_charge_geladene_kwh_monat
  pv_savings_monat_id: input_number.tibber_smart_pv_savings_monat
  
  # Gesamt Statistiken
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
  {% set sensor_id = 'sensor.electricity_price_DEIN_SENSOR' %}
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

## ⚠️ Haftungsausschluss

Die Nutzung dieses Skripts erfolgt auf eigene Gefahr. Es greift aktiv in die Steuerung deines Wechselrichters ein. Obwohl Sicherheitsmechanismen (wie der Debug-Mode und Heartbeat) integriert sind, übernehme ich keine Haftung für entladene Batterien zur falschen Zeit, unerwartete Stromkosten oder Hardware-Probleme. Bitte teste die Konfiguration zunächst mit `debug_mode: true`.
