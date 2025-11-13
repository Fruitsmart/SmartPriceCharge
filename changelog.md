Absolut\! Eine Changelog ist eine hervorragende Idee, um die Entwicklung und Verbesserungen des Blueprints transparent zu machen.

Hier ist eine detaillierte Changelog für die bisherigen Versionen deines "GoodWe & Tibber Smart Charge (Optimiert)" Blueprints:

---

### **Changelog: GoodWe & Tibber Smart Charge Blueprint**

**Version 5.0 (Aktuell)**

* **Neue Funktionen:**
    * **Status-Helfer integriert:** Zwei neue `input` Optionen für Helfer hinzugefügt:
        * `Text-Helfer Günstige Stunden` (`input_text`): Zeigt die Uhrzeiten der X günstigsten Stunden des Tages an, in denen das Laden aus dem Netz geplant ist.
        * `Toggle-Helfer Akku lädt aus Netz` (`input_boolean`): Zeigt in Echtzeit an, ob der Akku im Backup-Modus (also aus dem Netz) geladen wird.
    * **Verbesserte Sichtbarkeit:** Durch die Helfer kann der aktuelle Status der Automation nun einfach im Home Assistant Dashboard oder in anderen Automatisierungen angezeigt und genutzt werden.
* **Verbesserungen:**
    * Anpassung der `action`-Sektion, um die neuen Helfer zu steuern (setzen des Textes und des Toggles).

**Version 4.0**

* **BREAKING CHANGE / Wichtige Änderung (Tibber-Sensor-Vorbereitung):**
    * **Vereinfachung der Tibber-Preisdaten-Verarbeitung:** Die komplexe Jinja2-Logik zur Extraktion der Tibber-Preisdaten wurde aus dem Blueprint entfernt und in eine **externe Template-Sensor-Definition für `configuration.yaml`** ausgelagert (`sensor.tibber_processed_prices`).
    * **Vorteil:** Dies macht den Blueprint robuster gegenüber YAML-Parsing-Fehlern und Einrückungsproblemen, die bei der direkten Attributabfrage in den Blueprint-Variablen auftraten. Die Daten sind nun vorverarbeitet und stabil.
* **Fehlerbehebungen:**
    * Behebung des hartnäckigen YAML-Parsing-Fehlers (`while scanning a quoted scalar... found unexpected end of stream`) im `tibber_raw_prices`-Bereich durch die Auslagerung in einen dedizierten Template-Sensor.
* **Dokumentation:**
    * Anpassung der Installationsanleitung, um die neue, erforderliche Definition des `sensor.tibber_processed_prices` in der `configuration.yaml` klar zu beschreiben.

**Version 3.0**

* **Fehlerbehebungen:**
    * Behebung des YAML-Parsing-Fehlers (`mapping values are not allowed here...`) verursacht durch Doppelpunkte `:` in den `name`-Feldern der `input`-Sektion.
    * Alle `name`-Felder wurden angepasst, um keine Doppelpunkte mehr zu enthalten.

**Version 2.0**

* **Verbesserungen:**
    * **Detaillierte Beschreibung:** Die `description` des Blueprints wurde erheblich erweitert und formatiert, um die Funktionsweise, Voraussetzungen und Anwendungsfälle klarer darzustellen.
    * **Verbesserte Input-Beschreibungen:** Alle `description`-Felder in der `input`-Sektion wurden detaillierter und benutzerfreundlicher gestaltet, um die Konfiguration zu erleichtern.
    * Kleinere Optimierungen der Kommentare für bessere Lesbarkeit.

**Version 1.0 (Initial Release)**

* **Kernfunktionalität:**
    * Grundlegende Implementierung der intelligenten Batteriesteuerung für GoodWe-Wechselrichter basierend auf Tibber-Preisdaten.
    * Unterstützung für "günstiges Laden" aus dem Netz (Backup-Modus).
    * Berücksichtigung der aktuellen PV-Leistung und optional eines Solar-Prognose-Sensors zur Vermeidung unnötigen Netzbezugs.
    * Automatisches Management der Exportsperre im General-Modus zur Maximierung des Eigenverbrauchs und zur Vermeidung von Netzbezug bei Entladung bzw. zur Freigabe bei Vollladung.
* **Konfigurierbare Parameter:**
    * `tibber_price_data_sensor`, `pv_power_sensor`, `battery_soc_sensor`, `goodwe_work_mode_selector`, `goodwe_export_limit_switch`, `solar_forecast_sensor` (optional).
    * Einstellbare Schwellenwerte für `charge_hours`, `pv_threshold_low`, `pv_threshold_high`, `soc_full_threshold`.

---
