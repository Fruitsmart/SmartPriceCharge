**Steuert deinen GoodWe Batteriespeicher intelligent basierend auf dynamischen Tibber-Strompreisen.
Der Akku wird automatisch in den günstigsten Stunden geladen und dient sonst dem Eigenverbrauch (kein Export ins Netz).**

Dieser Blueprint erstellt automatisch die benötigten Helfer ('input_boolean' und 'input_number') und integriert sie.

**Funktionen:**

- Erkennt die günstigsten Stunden aus Tibber-Preisen für HEUTE und MORGEN.
- Nutzt den "Backup"-Modus zum Laden und den "General"-Modus für Eigenverbrauch.
- Aktiviert den GoodWe "Fast Charging Switch" während des Ladens (um die volle Ladegeschwindigkeit zu gewährleisten).
- Berücksichtigt die benötigte Ladedauer des Akkus (Konfiguration über den generierten Helfer 'Anzahl Günstigste Ladestunden').

**Voraussetzungen:**

- HACS GoodWe Integration (für Steuerung des Arbeitsmodus und Fast Charging Switch).
- Ein funktionierender Tibber REST-Sensor (sensor.tibber_preise_prognose), der die Attribute 'today' und 'tomorrow' liefert.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FFruitsmart%2FGoodWe-Tibber-Smart-Charging-Automatisiertes-Laden-Eigenverbrauch-%2Fblob%2Fmain%2Fgoodwe_tibber_smart_charging.v1.0.3.yaml)
