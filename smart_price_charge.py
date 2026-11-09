# ==============================================================================
# SmartPriceCharge (v6.8.4 - bedarfsorientiertes Ladeziel, Peak-Absicherung, PV-Bilanz)
# ==============================================================================
# AppDaemon Application for Intelligent Battery & EV Charging with Tibber & GoodWe
# ==============================================================================

import appdaemon.plugins.hass.hassapi as hass
import requests
import json
import math
import os
import threading
from datetime import datetime, time, timedelta

APP_VERSION = "6.8.4"

WEATHER_PV_FACTOR = {
    'sunny': 1.0,
    'clear-night': 0.0,
    'partlycloudy': 0.7,
    'cloudy': 0.3,
    'fog': 0.2,
    'rainy': 0.1,
    'snowy': 0.1,
    'windy': 0.5
}

TRANSLATIONS = {
    'DE': {
        'REPORT_GRID_COST': "Netzkosten",
        'REPORT_CHARGE_SAVE': "Lade-Ersparnis",
        'REPORT_DISCHARGE_VALUE': "Entlade-Gewinn (Echt)",
        'REPORT_PV_VALUE': "PV-Direkt-Ersparnis",
        'REPORT_CHARGED_KWH': "Geladene kWh (Netz)",
        'STATUS_PV_CHARGING': "PV-Laden aktiv",
        'STATUS_DISCHARGE_BASE': "Entladen aktiv (Eigenverbrauch)",
        'STATUS_DISCHARGE_DIP': "Entladen aktiv (Preistief überbrücken)",
        'STATUS_DISCHARGE_RESERVE_REACHED': "Entladen gestoppt: Reserve erreicht",
        'STATUS_CHARGE_ACTIVE': "Hausakku lädt (Netz-Slot)",
        'STATUS_CHARGE_BLOCKED': "Laden gesperrt (Preis zu hoch)",
        'STATUS_TARGET_REACHED': "Ziel-SoC erreicht: Normalbetrieb",
        'STATUS_EV_PLAN_NONE': "Kein EV-Netzladen geplant",
        'STATUS_EV_PLAN_BOOST': "Sofort-Laden (Boost) bis {target}%",
        'STATUS_EV_PLAN_ACTIVE': "EV Billig-Slots ({start} - {end}, {slots} Slots)",
        'STATUS_EV_CHEAP': "EV-Laden aktiv: Günstiger Slot ({target}%)",
        'STATUS_EV_PV': "EV-Laden aktiv: PV-Überschuss",
        'STATUS_WAIT_HOLD': "Warten (Spread-Hold)",
        'STATUS_WAIT_PV': "Warten auf PV-Überschuss",
        'STATUS_IDLE': "Standby / Normalbetrieb",
        'INFO_APP_INIT': "SmartPriceCharge v6.8.4 gestartet",
        'INFO_APP_TERMINATED': "SmartPriceCharge beendet",
        'ERROR_NO_PRICE_DATA': "Fehler: Keine Preisdaten von Tibber verfügbar!",
    },
    'EN': {
        'REPORT_GRID_COST': "Grid Costs",
        'REPORT_CHARGE_SAVE': "Charging Savings",
        'REPORT_DISCHARGE_VALUE': "Discharge Profit (Real)",
        'REPORT_PV_VALUE': "PV Direct Savings",
        'REPORT_CHARGED_KWH': "Charged kWh (Grid)",
        'STATUS_PV_CHARGING': "PV Charging active",
        'STATUS_DISCHARGE_BASE': "Discharging active (Grid support)",
        'STATUS_DISCHARGE_DIP': "Discharging active (Covering price dip)",
        'STATUS_DISCHARGE_RESERVE_REACHED': "Discharge stopped: Reserve reached",
        'STATUS_CHARGE_ACTIVE': "Charging active (Cheap Slot)",
        'STATUS_CHARGE_BLOCKED': "Charging blocked (Price too high)",
        'STATUS_TARGET_REACHED': "Target SoC reached: Standby / Normal operation",
        'STATUS_EV_PLAN_NONE': "No EV plan active",
        'STATUS_EV_PLAN_BOOST': "Immediate Charging (Boost) to {target}%",
        'STATUS_EV_PLAN_ACTIVE': "EV Cheap Slots ({start} - {end}, {slots} slots)",
        'STATUS_EV_CHEAP': "EV Charging active: Cheap Slot ({target}%)",
        'STATUS_EV_PV': "EV Charging active: PV Surplus",
        'STATUS_WAIT_HOLD': "Holding Battery (Spread-Hold)",
        'STATUS_WAIT_PV': "Waiting for PV Surplus",
        'STATUS_IDLE': "Idle / General Mode",
        'INFO_APP_INIT': "SmartPriceCharge v6.8.4 initialized",
        'INFO_APP_TERMINATED': "SmartPriceCharge terminated",
        'ERROR_NO_PRICE_DATA': "Error: No price data available from Tibber!",
    }
}


class SmartPriceCharge(hass.Hass):

    def initialize(self):
        self.lang = self.args.get('language', 'DE').upper()
        self.T = TRANSLATIONS.get(self.lang, TRANSLATIONS['DE'])
        self.log(f"INFO: {self.T['INFO_APP_INIT']} ({APP_VERSION})", level="INFO")

        self.debug_mode = self.args.get('debug_mode', False)
        self.log_debug_level = self.args.get('log_debug_level', True)
        self.efficiency_factor = float(self.args.get(
            'battery_efficiency_factor', self.args.get('efficiency_factor', 0.90)
        ))
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.06))
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 75.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 90.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.morning_min_diff = float(self.args.get('morning_min_diff', 0.10))
        # Ab welchem Preishub (EUR/kWh) ein Preisberg als eigener 'Peak' gilt (Abend-Peak, Morgen-Peak ...)
        self.peak_swing_eur = float(self.args.get('peak_swing_eur', 0.10))
        # Preise innerhalb dieser Toleranz gelten als gleich teuer -> frühester Slot gewinnt
        self.price_tie_eur = float(self.args.get('price_tie_eur', 0.01))
        # Obergrenze der Hauslast-Schätzung (W) für die PV-Überschuss-Bilanz
        self.max_load_w = float(self.args.get('max_load_w', 1000.0))
        # True: im geplanten Netz-Slot wird auch bei Sonne aus dem Netz nachgeladen (PV wird im Modus charge_battery zuerst genutzt)
        self.grid_charge_in_sun = bool(self.args.get('grid_charge_in_sun', True))
        # True: Das Ladeziel ist nur die OBERGRENZE. Geladen wird nur so viel, wie das teure Preisfenster
        # verbraucht (jede kWh muss sich gegen ihren Verwertungspreis lohnen). False = immer bis zum Ladeziel.
        self.need_based_target = bool(self.args.get('need_based_target', True))
        # Sicherheitsaufschlag auf den Bedarf des teuren Fensters (0.10 = +10 %)
        self.peak_reserve_margin = float(self.args.get('peak_reserve_margin', 0.10))
        # Hauslast (W), mit der die Morgen-Brücke den Bedarf bis zum Ende des Morgen-Peaks rechnet.
        # 0 = automatisch (24h-Durchschnitt, max. 1500 W). Beim Abgleich mit dem Log ('Brücke Bedarf') anpassen.
        self.morning_load_w = float(self.args.get('morning_load_w', 0.0))
        # PV-Übernahme am Morgen: Reicht die PV-Prognose des Tages für mindestens so viele kWh, endet der
        # Akku-Bedarf der Morgen-Brücke 'pv_takeover_delay_h' Stunden nach Sonnenaufgang.
        self.pv_takeover_min_kwh = float(self.args.get('pv_takeover_min_kwh', 4.0))
        self.pv_takeover_delay_h = float(self.args.get('pv_takeover_delay_h', 2.0))
        # PV-Kalibrierung: vergleicht abends die Tagesprognose mit der gemessenen PV-Erzeugung
        self.pv_forecast_today_sensor_id = self.args.get('pv_forecast_today_sensor_id', None)  # Solcast 'Prognose heute' (Tagessumme, kWh)
        self.pv_energy_today_sensor_id = self.args.get('pv_energy_today_sensor_id', None)      # PV-Tagesertrag des Wechselrichters (kWh), optional
        self.pv_auto_calibrate = bool(self.args.get('pv_auto_calibrate', False))               # True: Sicherheitsfaktor aus den letzten Tagen ableiten

        # Basis & GoodWe Sensoren
        self.price_sensor_id = self.args['price_sensor_id']
        self.current_soc_sensor_id = self.args['current_soc_sensor_id']
        self.inverter_mode_entity_id = self.args['inverter_mode_entity_id']

        self.inverter_operation_mode_entity_id = self.args.get('inverter_operation_mode_entity_id', None)
        self.inverter_op_mode_charge = self.args.get('inverter_op_mode_charge', "eco_charge")
        self.inverter_op_mode_general = self.args.get('inverter_op_mode_general', "general")
        self.inverter_op_mode_backup = self.args.get('inverter_op_mode_backup', "backup")

        self.mode_charge = self.args.get('inverter_mode_charge', "charge_battery")
        self.mode_general = self.args.get('inverter_mode_general', "auto")
        self.mode_backup = self.args.get('inverter_mode_backup', "battery_standby")
        self.inverter_max_soc_entity_id = self.args.get('inverter_max_soc_entity_id', None)

        # PV & Power & Wetter
        self.pv_forecast_next_hour_id = self.args.get('pv_forecast_sensor_id', None)
        self.pv_forecast_current_hour_id = self.args.get('pv_forecast_current_hour_sensor_id', None)
        self.pv_forecast_today_remaining_id = self.args.get('pv_forecast_today_remaining_sensor_id', None)
        self.pv_forecast_tomorrow_id = self.args.get('pv_forecast_tomorrow_sensor_id', None)
        self.pv_peak_time_sensor_id = self.args.get('pv_peak_time_sensor_id', None)
        self.current_pv_power_sensor_id = self.args.get('current_pv_power_sensor_id', None)
        self.battery_power_sensor_id = self.args.get('battery_power_sensor_id', None)
        self.grid_power_import_export_sensor_id = self.args.get('grid_power_import_export_sensor_id', None)
        self.current_house_consumption_w_id = self.args.get('current_house_consumption_w_id', None)
        self.avg_consumption_sensor_id = self.args.get('avg_consumption_sensor_id', None)

        self.sun_sensor_id = self.args.get('sun_sensor_id', 'sun.sun')
        self.weather_sensor_id = self.args.get('weather_sensor_id', None)
        self.cloud_coverage_sensor_id = self.args.get('cloud_coverage_sensor_id', None)

        # Konfigurations-Helfer
        self.battery_capacity_kwh_id = self.args['battery_capacity_kwh_id']
        self.charger_power_kw_id = self.args['charger_power_kw_id']
        self.target_soc_id = self.args['target_soc_id']
        self.pv_forecast_threshold_kw_id = self.args['pv_forecast_threshold_kw_id']
        self.current_pv_threshold_w_id = self.args['current_pv_threshold_w_id']
        self.price_discharge_threshold_id = self.args['price_discharge_threshold_id']
        self.min_soc_discharge_id = self.args['min_soc_discharge_id']
        self.reference_price_id = self.args.get('reference_price_id', None)
        self.charge_intervals_input_id = self.args.get('charge_intervals_input_id', None)
        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.50))
        self.sleep_over_soc = float(self.args.get('sleep_over_soc', 30.0))

        # EV / Wallbox Steuerung
        self.ev_logic_active_id = self.args.get('ev_logic_active_id', None)
        self.ev_target_soc_id = self.args.get('ev_target_soc_id', 'input_number.ev_target_soc')
        self.ev_soc_sensor_id = self.args.get('ev_soc_sensor_id', None)
        self.ev_wallbox_switch_id = self.args.get('ev_wallbox_switch_id', None)
        self.ev_wallbox_amps_id = self.args.get('ev_wallbox_amps_id', None)
        self.ev_pv_surplus_switch_id = self.args.get('ev_pv_surplus_switch_id', None)
        self.ev_wallbox_status_id = self.args.get('ev_wallbox_status_id', None)
        self.ev_logic_mode_id = self.args.get('ev_logic_mode_id', 'select.goe_315255_lmo')
        self.ev_battery_capacity_kwh = float(self.args.get('ev_battery_capacity_kwh', 77.0))
        self.ev_charger_power_kw = float(self.args.get(
            'ev_charge_power_kw', self.args.get('ev_charger_power_kw', 11.0)
        ))
        self.ev_boost_switch_id = self.args.get('ev_boost_switch_id', None)
        self.ev_plug_sensor_id = self.args.get('ev_plug_sensor_id', None)
        self.ev_charge_plan_id = self.args.get('ev_charge_plan_id', 'input_text.ev_ladeplan')
        self.monday_deadline_time_id = self.args.get('monday_deadline_time_id', 'input_datetime.ev_montag_abfahrtszeit')
        self.monday_min_soc_id = self.args.get('monday_min_soc_id', 'input_number.ev_montag_sicherheits_soc')
        self.ev_immediate_charge_price_id = self.args.get('ev_immediate_charge_price_id', None)

        # Winter-Parameter
        self.home_battery_priority_soc = float(self.args.get('home_battery_priority_soc', 95.0))
        self.home_battery_priority_hysteresis = float(self.args.get('home_battery_priority_hysteresis', 5.0))

        # Status & Tracking Helfer
        self.dashboard_status_text_id = self.args.get('dashboard_status_text_id', 'input_text.tibber_smart_charge_status')
        self.app_enabled_switch_id = self.args.get('app_enabled_switch_id', 'input_boolean.tibber_smart_charge_app_aktiv')
        self.cheap_hour_toggle_id = self.args.get('cheap_hour_toggle_id', 'input_boolean.tibber_guenstige_ladestunde')
        self.next_charge_time_id = self.args.get('next_charge_time_id', 'input_text.tibber_next_charge_time')
        self.cheap_hours_text_id = self.args.get('cheap_hours_text_id', 'input_text.gunstigsten_ladestunden')
        self.report_id = self.args.get('report_id', 'input_text.tibber_smart_charge_monatsbericht')

        # Statistiken
        self.cost_month_id = self.args.get('cost_month_id', None)
        self.savings_month_id = self.args.get('savings_month_id', None)
        self.discharge_savings_month_id = self.args.get('discharge_savings_month_id', None)
        self.charged_kwh_month_id = self.args.get('charged_kwh_month_id', None)
        self.pv_savings_month_id = self.args.get('pv_savings_month_id', None)
        self.cost_total_id = self.args.get('cost_total_id', None)
        self.savings_total_id = self.args.get('savings_total_id', None)
        self.discharge_savings_total_id = self.args.get('discharge_savings_total_id', None)
        self.charged_kwh_total_id = self.args.get('charged_kwh_total_id', None)
        self.pv_savings_total_id = self.args.get('pv_savings_total_id', None)

        # KI Integration
        raw_model = str(self.args.get('gemini_model', 'gemini-2.5-flash')).strip()
        if "3.5" in raw_model:
            raw_model = "gemini-2.5-flash"
        self.gemini_model = raw_model
        self.gemini_api_key = self.args.get('gemini_api_key', None)
        self.ai_trigger_button_id = self.args.get('ai_trigger_button_id', None)
        self.ai_advice_text_id = self.args.get('ai_advice_text_id', None)

        self._lock = threading.RLock()
        self._state_cache = {}
        self._wb_timer_handle = None
        self._last_inv_cmd_time = None
        self._last_reload_time = None
        self._inv_retry_count = 0
        # Nach einem Moduswechsel braucht der GoodWe oft mehrere Minuten, bis die Leistung anläuft.
        # Erst danach gilt 'lädt nicht' als Hardware-Hänger (vorher 120 s -> unnötige Integrations-Reloads).
        self.inverter_stuck_after_s = float(self.args.get('inverter_stuck_after_s', 300.0))

        self._battery_stored_kwh = 0.0
        self._battery_avg_buy_price = 0.25

        self._pv_day = None
        self._pv_measured_kwh = 0.0
        self._pv_fc_total = None
        self._pv_partial = False
        self._pv_last_ts = None
        self._pv_history = []
        self._pv_auto_factor = None
        try:
            self._calib_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pv_calibration.json')
        except Exception:
            self._calib_file = None
        self._load_pv_history()

        if not all([self.price_sensor_id, self.current_soc_sensor_id, self.inverter_mode_entity_id]):
            self.log("ERROR: Essential IDs missing!", level="ERROR")
            return

        if self.ev_wallbox_status_id:
            self.listen_state(self.check_wallbox_disconnect, self.ev_wallbox_status_id)
        if getattr(self, 'ev_plug_sensor_id', None):
            self.listen_state(self.check_wallbox_disconnect, self.ev_plug_sensor_id)

        delay = int(self.args.get('startup_delay_seconds', 120))
        self.run_in(self.start_app_routine, delay)

    def start_app_routine(self, kwargs):
        self.log("System stabilisiert. Starte Hauptlogik.", level="INFO")
        now = self.get_now()
        next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, next_min, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))
        self.run_daily(self.check_weekly_ai_trigger, time(18, 0, 0))
        self.run_daily(self._log_pv_calibration, time(22, 0, 0))
        self.listen_event(self.trigger_ai_analysis, "trigger_ai_analysis")
        if getattr(self, 'ai_trigger_button_id', None):
            self.listen_state(self.trigger_ai_analysis_button, self.ai_trigger_button_id)

        cur_soc = self._get_float_state(self.current_soc_sensor_id, default=0.0)
        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=7.5)
        dod = self._get_float_state(self.min_soc_discharge_id, default=90.0)
        base_min_soc = (100.0 - dod) if dod > 50.0 else dod
        self._battery_stored_kwh = max(0.0, ((cur_soc - base_min_soc) / 100.0) * batt_cap)

        m_cost = self._get_tracking_state(self.cost_month_id)
        m_kwh = self._get_tracking_state(self.charged_kwh_month_id)
        if m_kwh > 1.0 and m_cost > 0 and str(self.cost_month_id).startswith('input_number.'):
            self._battery_avg_buy_price = min(0.60, max(0.05, m_cost / m_kwh))

        self.main_logic({})

    def _safe_get_state(self, entity_id, attribute=None, default=None):
        if not entity_id or str(entity_id).lower() in ['none', 'null', '', 'unavailable', 'unknown']:
            return default
        try:
            val = self.get_state(entity_id, attribute=attribute) if attribute else self.get_state(entity_id)
            return default if val in ['unavailable', 'unknown', 'none', None] else val
        except Exception:
            return default

    def _get_float_state(self, entity_id, default=0.0):
        if not entity_id or str(entity_id).lower() in ['none', 'null', '', 'unavailable', 'unknown']:
            return default
        cache_key = f"float_{entity_id}"
        if cache_key in self._state_cache:
            return self._state_cache[cache_key]
        with self._lock:
            try:
                state = self.get_state(entity_id)
                if state in ['unavailable', 'unknown', 'none', None]:
                    self._state_cache[cache_key] = default
                    return default
                value = float(state)
                self._state_cache[cache_key] = value
                return value
            except (ValueError, TypeError, KeyError):
                self._state_cache[cache_key] = default
                return default

    def _get_tracking_state(self, entity_id):
        return self._get_float_state(entity_id, default=0.0)

    def _set_tracking_state(self, entity_id, value, decimals=6):
        if not entity_id or not str(entity_id).startswith('input_number.'):
            return
        val = round(value, decimals)
        with self._lock:
            try:
                cache_key = f"float_{entity_id}"
                if cache_key in self._state_cache and abs(self._state_cache[cache_key] - val) < 1e-9:
                    return
                # Als String senden: ein Zahlenwert 0.0 wurde bei manchen AppDaemon-Versionen als 'kein Zustand' gewertet (HTTP 400)
                self.set_state(entity_id, state=str(val))
                self._state_cache[cache_key] = val
            except (ValueError, TypeError, KeyError):
                pass

    def _set_error_states(self, message_key):
        if getattr(self, 'dashboard_status_text_id', None):
            msg = self.T.get(message_key, message_key)
            self.set_state(self.dashboard_status_text_id, state=msg)

    def check_wallbox_disconnect(self, entity, attribute, old, new, kwargs):
        app_enabled = (self._safe_get_state(self.app_enabled_switch_id, default='on') == 'on')
        if not app_enabled:
            return

        is_disconnected = False
        if entity == self.ev_plug_sensor_id and str(new).lower() in ['off', 'false', '0']:
            is_disconnected = True
        elif entity == self.ev_wallbox_status_id and str(new).lower() in ['1', '0', 'off', 'false', 'unplugged', 'nicht verbunden', 'disconnected', 'kabel entfernt', 'inaktiv/frei', 'frei']:
            is_disconnected = True

        if is_disconnected:
            if self.log_debug_level:
                self.log("Stecker-Reflex: Auto abgesteckt -> Setze Wallbox sofort auf 1 (Laden nicht zulassen).", level="INFO")
            self._set_wallbox_logic_mode("Eco")
            self._set_wallbox_state("1")
            if getattr(self, 'ev_boost_switch_id', None) and self._safe_get_state(self.ev_boost_switch_id) == 'on':
                self.turn_off(self.ev_boost_switch_id)

    def _set_wallbox_logic_mode(self, mode: str):
        with self._lock:
            eid = getattr(self, 'ev_logic_mode_id', None)
            if not eid:
                return
            target_val = "4" if str(mode).lower() in ["eco", "4"] else "3"
            current = str(self.get_state(eid)).strip()
            if current != target_val:
                try:
                    self.call_service("select/select_option", entity_id=eid, option=target_val)
                except Exception as e:
                    if self.log_debug_level:
                        self.log(f"Wallbox LMO Switch Fehler: {e}", level="ERROR")

    def _set_wallbox_state(self, state_option: str):
        with self._lock:
            eid = getattr(self, 'ev_wallbox_switch_id', None)
            if not eid:
                return

            opt_lower = str(state_option).strip().lower()
            if opt_lower in ['1', 'off', 'aus']:
                target = "1"
            elif opt_lower in ['2', 'on', 'ein']:
                target = "2"
            else:
                target = "0"

            if target == "1" and self._wb_timer_handle is not None:
                try:
                    self.cancel_timer(self._wb_timer_handle)
                except Exception:
                    pass
                self._wb_timer_handle = None

            current = str(self.get_state(eid)).strip()

            if current != target:
                if target == "2" and current == "1":
                    self.log(f"WALLBOX WAKE-UP: Schalte {eid} von '1' auf '0' und in 3s auf '2'...", level="INFO")
                    try:
                        self.call_service("select/select_option", entity_id=eid, option="0")
                    except Exception as e:
                        self.log(f"Wallbox Wakeup Fehler: {e}", level="ERROR")
                    if self._wb_timer_handle is not None:
                        try:
                            self.cancel_timer(self._wb_timer_handle)
                        except Exception:
                            pass
                    self._wb_timer_handle = self.run_in(self._deferred_wb_select, 3, option="2")
                else:
                    self.log(f"WALLBOX ACTION: Schalte {eid} von '{current}' auf '{target}'", level="INFO")
                    try:
                        self.call_service("select/select_option", entity_id=eid, option=target)
                    except Exception as e:
                        self.log(f"Wallbox Switch Fehler: {e}", level="ERROR")

    def _deferred_wb_select(self, kwargs):
        with self._lock:
            self._wb_timer_handle = None
            opt = str(kwargs.get('option', "2"))
            eid = getattr(self, 'ev_wallbox_switch_id', None)
            if eid:
                try:
                    self.log(f"WALLBOX WAKE-UP FINISHED: Setze {eid} final auf '{opt}'", level="INFO")
                    self.call_service("select/select_option", entity_id=eid, option=opt)
                except Exception as e:
                    self.log(f"Deferred WB Select Fehler: {e}", level="ERROR")

    def _set_inverter_mode(self, target_mode):
        with self._lock:
            if not self.inverter_mode_entity_id:
                return

            now = self.get_now()
            if self._last_inv_cmd_time is None:
                self._last_inv_cmd_time = now - timedelta(minutes=10)

            raw_ems = self.get_state(self.inverter_mode_entity_id)
            raw_op = self.get_state(self.inverter_operation_mode_entity_id) if self.inverter_operation_mode_entity_id else "ok"

            if raw_ems in ['unavailable', 'unknown', None] or raw_op in ['unavailable', 'unknown', None]:
                reload_pause_ok = self._last_reload_time is None or (now - self._last_reload_time).total_seconds() >= 180
                if (now - self._last_inv_cmd_time).total_seconds() >= 60 and reload_pause_ok:
                    self.log("WARNUNG: GoodWe Entität ist 'unavailable' -> Lade GoodWe-Integration automatisch neu!", level="WARNING")
                    try:
                        self.call_service("homeassistant/reload_config_entry", entity_id=self.inverter_mode_entity_id)
                    except Exception as e:
                        self.log(f"Reload Fehler: {e}", level="ERROR")
                    self._last_inv_cmd_time = now
                    self._last_reload_time = now
                return

            current_mode = str(raw_ems).strip()
            target_op = self.inverter_op_mode_general
            if target_mode == self.mode_charge:
                target_op = self.inverter_op_mode_charge
            elif target_mode == self.mode_backup and self.inverter_op_mode_backup:
                target_op = self.inverter_op_mode_backup
            current_op = str(raw_op).strip() if self.inverter_operation_mode_entity_id else target_op

            mode_mismatch = (current_mode != target_mode) or (self.inverter_operation_mode_entity_id and current_op != target_op)

            cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id, default=0.0)
            cur_soc = self._get_float_state(self.current_soc_sensor_id, default=50.0)
            target_soc = self._get_float_state(self.target_soc_id, default=100.0)
            secs_since_last_cmd = (now - self._last_inv_cmd_time).total_seconds()

            hardware_stuck = False
            if not mode_mismatch and secs_since_last_cmd >= self.inverter_stuck_after_s:
                if target_mode == self.mode_charge and cur_soc < (target_soc - 1.0) and cur_batt_pwr > -100.0:
                    hardware_stuck = True
                    self.log(f"WARNUNG: GoodWe zeigt '{current_mode}'/'{current_op}', lädt aber nicht (Batt: {cur_batt_pwr:.0f}W)!", level="WARNING")
                elif target_mode == self.mode_backup and cur_batt_pwr > 150.0:
                    hardware_stuck = True
                    self.log(f"WARNUNG: GoodWe zeigt '{current_mode}'/'{current_op}', entlädt aber trotzdem (Batt: {cur_batt_pwr:.0f}W)!", level="WARNING")

            if not mode_mismatch and not hardware_stuck:
                self._inv_retry_count = 0
                if self.log_debug_level:
                    self.log(f"Inverter Mode '{target_mode}' (OpMode: '{current_op}') OK.", level="INFO")
                return

            if secs_since_last_cmd < 45:
                return

            self._last_inv_cmd_time = now

            if self.debug_mode:
                self.log(f"DEBUG-MODE: Würde GoodWe auf OpMode='{target_op}' & EMS='{target_mode}' schalten.", level="INFO")
                return

            if hardware_stuck:
                self._inv_retry_count += 1
                self.log(f"SELBSTHEILUNG (Versuch {self._inv_retry_count}): Lade GoodWe-Integration neu und sende '{target_mode}' in 15s erneut...", level="WARNING")
                self._last_reload_time = now
                try:
                    self.call_service("homeassistant/reload_config_entry", entity_id=self.inverter_mode_entity_id)
                except Exception as e:
                    self.log(f"Reload Fehler: {e}", level="ERROR")
                self.run_in(self._execute_staggered_goodwe_cmd, 15, target_mode=target_mode, target_op=target_op)
            else:
                self.log(f"ACTION: Schalte GoodWe gestaffelt auf OpMode='{target_op}' & EMS='{target_mode}' (Aktuell: Op='{current_op}', EMS='{current_mode}')", level="INFO")
                self._execute_staggered_goodwe_cmd({"target_mode": target_mode, "target_op": target_op})

    def _execute_staggered_goodwe_cmd(self, kwargs):
        target_mode = kwargs.get("target_mode")
        target_op = kwargs.get("target_op")

        if self.inverter_max_soc_entity_id:
            target_soc_val = float(self._get_float_state(self.target_soc_id, default=100.0)) if target_mode == self.mode_charge else 100.0
            current_max_soc = self._get_float_state(self.inverter_max_soc_entity_id, default=100.0)
            if abs(current_max_soc - target_soc_val) > 0.5:
                try:
                    self.call_service("number/set_value", entity_id=self.inverter_max_soc_entity_id, value=target_soc_val)
                except Exception as e:
                    if self.log_debug_level:
                        self.log(f"Inverter Max SoC Fehler: {e}", level="ERROR")

        if self.inverter_operation_mode_entity_id and target_op:
            self.run_in(self._delayed_op_mode_cmd, 2, target_op=target_op)

        self.run_in(self._delayed_ems_mode_cmd, 4, target_mode=target_mode)

    def _delayed_op_mode_cmd(self, kwargs):
        target_op = kwargs.get("target_op")
        try:
            self.call_service("select/select_option", entity_id=self.inverter_operation_mode_entity_id, option=target_op)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"GoodWe OpMode Switch Fehler: {e}", level="ERROR")

    def _delayed_ems_mode_cmd(self, kwargs):
        target_mode = kwargs.get("target_mode")
        try:
            self.call_service("select/select_option", entity_id=self.inverter_mode_entity_id, option=target_mode)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"Inverter Mode Switch Fehler: {e}", level="ERROR")

    def _parse_slot_time(self, p, idx, base_date, tz):
        for key in ['startsAt', 'start_time', 'time', 'start']:
            if key in p and p[key]:
                try:
                    dt = datetime.fromisoformat(str(p[key]))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=tz)
                    return dt
                except Exception:
                    pass
        minutes_offset = idx * 15
        return datetime.combine(base_date, time(0, 0)).replace(tzinfo=tz) + timedelta(minutes=minutes_offset)

    def _find_next_peak(self, prices, swing):
        """
        Findet den ERSTEN echten Preisberg in der Zukunft (chronologische Liste).
        Ein Berg beginnt, sobald der Preis um >= swing über das bisherige Minimum steigt, und gilt als
        beendet, sobald er um >= swing vom Höchstwert abfällt. So werden Abend-Peak heute und Morgen-Peak
        morgen nacheinander abgesichert, statt nur das globale Maximum über zwei Tage anzusteuern.
        Gibt None zurück, wenn es keinen Berg dieser Größe gibt (flacher Tag).
        """
        run_min = None
        peak = None
        for item in prices:
            p = item['price']
            if peak is None:
                run_min = p if run_min is None else min(run_min, p)
                if p >= run_min + swing:
                    peak = item
            elif p > peak['price']:
                peak = item
            elif p <= peak['price'] - swing:
                return peak
        return peak

    # ==========================================================
    # PV-KALIBRIERUNG (Prognose vs. gemessen)
    # ==========================================================
    def _load_pv_history(self):
        try:
            if self._calib_file and os.path.exists(self._calib_file):
                with open(self._calib_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._pv_history = [e for e in data if isinstance(e, dict) and 'forecast' in e and 'measured' in e][-30:]
        except Exception:
            self._pv_history = []
        self._update_pv_auto_factor()

    def _save_pv_history(self):
        try:
            if self._calib_file:
                with open(self._calib_file, 'w', encoding='utf-8') as f:
                    json.dump(self._pv_history[-30:], f)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"PV-Kalibrierung: Speichern fehlgeschlagen: {e}", level="WARNING")

    def _pv_ratio_recent(self, n=7):
        recent = self._pv_history[-n:]
        fc_sum = sum(e['forecast'] for e in recent)
        if len(recent) == 0 or fc_sum <= 0:
            return None, len(recent)
        return sum(e['measured'] for e in recent) / fc_sum, len(recent)

    def _update_pv_auto_factor(self):
        ratio, n = self._pv_ratio_recent()
        self._pv_auto_factor = None
        if self.pv_auto_calibrate and ratio is not None and n >= 3:
            self._pv_auto_factor = max(0.3, min(1.0, 0.7 * ratio))

    def _pv_track(self, now, cur_pv, fc_rem):
        """Summiert die gemessene PV-Energie des Tages und merkt sich die Prognose vom Morgen."""
        today = now.date()
        if self._pv_day != today:
            self._pv_day = today
            self._pv_measured_kwh = 0.0
            self._pv_fc_total = None
            self._pv_partial = now.hour >= 5          # App nach 05:00 gestartet -> Tagessumme unvollständig
            self._pv_last_ts = None
        if self._pv_last_ts is not None:
            dt_h = min(5.0 / 60.0, max(0.0, (now - self._pv_last_ts).total_seconds() / 3600.0))
            self._pv_measured_kwh += max(0.0, cur_pv) / 1000.0 * dt_h
        self._pv_last_ts = now
        if self._pv_fc_total is None and now.hour >= 4:
            total = self._get_float_state(self.pv_forecast_today_sensor_id, default=0.0) if self.pv_forecast_today_sensor_id else 0.0
            if not total or total <= 0:
                total = fc_rem          # Fallback: Rest-Prognose am frühen Morgen entspricht der Tagessumme
            if total and total > 0:
                self._pv_fc_total = total

    def _log_pv_calibration(self, kwargs):
        now = self.get_now()
        fc = self._pv_fc_total
        meas = self._pv_measured_kwh
        partial = self._pv_partial
        if self.pv_energy_today_sensor_id:
            val = self._get_float_state(self.pv_energy_today_sensor_id, default=0.0)
            if val > 0:
                meas, partial = val, False
        if not fc or fc < 0.2 or meas is None:
            self.log("PV-Kalibrierung: keine verwertbaren Daten für heute (Prognose fehlt oder App zu spät gestartet).", level="INFO")
            return
        ratio = meas / fc
        if partial:
            self.log(f"PV-Kalibrierung {now.strftime('%d.%m.')}: Prognose {fc:.1f} kWh, gemessen {meas:.1f} kWh (unvollständig, App nach 05:00 gestartet - nicht gewertet)", level="INFO")
            return
        self._pv_history = [e for e in self._pv_history if e.get('date') != now.strftime('%Y-%m-%d')]
        self._pv_history.append({'date': now.strftime('%Y-%m-%d'), 'forecast': round(fc, 2), 'measured': round(meas, 2)})
        self._pv_history = self._pv_history[-30:]
        self._save_pv_history()
        self._update_pv_auto_factor()
        avg, n = self._pv_ratio_recent()
        hint = ""
        if avg is not None and n >= 3:
            suggestion = max(0.3, min(1.0, 0.7 * avg))
            hint = f" | Ø letzte {n} Tage: Faktor {avg:.2f} -> Richtwert pv_forecast_safety_factor ca. {suggestion:.2f} (aktuell {self.pv_forecast_safety_factor:.2f}{', automatisch ' + format(self._pv_auto_factor, '.2f') if self._pv_auto_factor else ''})"
        self.log(f"PV-Kalibrierung {now.strftime('%d.%m.')}: Prognose {fc:.1f} kWh, gemessen {meas:.1f} kWh (Faktor {ratio:.2f}){hint}", level="INFO")

    def _sun_time(self, attr, now):
        """Liest next_rising / next_setting von sun.sun als zeitzonenbewusstes datetime (oder None)."""
        if not self.sun_sensor_id:
            return None
        v = self._safe_get_state(self.sun_sensor_id, attribute=attr)
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
            return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
        except Exception:
            return None

    def _pv_window(self, now, deadline, is_daylight):
        """
        Liefert (stunden, anteil, nutzt_morgen) für das PV-Zeitfenster zwischen jetzt und Deadline:
        stunden = Stunden mit PV vor der Deadline, anteil = Anteil der (Rest-)Tagesproduktion vor der Deadline,
        nutzt_morgen = True, wenn das Fenster der morgige Tag ist (dann gilt die Morgen-Prognose).
        """
        def _parse(attr):
            if not self.sun_sensor_id:
                return None
            v = self._safe_get_state(self.sun_sensor_id, attribute=attr)
            if not v:
                return None
            try:
                dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
                return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
            except Exception:
                return None

        hours_to_deadline = max(0.0, (deadline - now).total_seconds() / 3600.0)
        setting = _parse('next_setting')
        rising = _parse('next_rising')
        if setting is None or (not is_daylight and rising is None):
            hrs = min(hours_to_deadline, 6.0) if is_daylight else 0.0
            return hrs, (1.0 if hrs > 0 else 0.0), False

        start = now if is_daylight else rising
        day_h = max(0.01, (setting - start).total_seconds() / 3600.0)
        win_start = max(start, now)
        win_end = min(setting, deadline)
        hrs = max(0.0, (win_end - win_start).total_seconds() / 3600.0)
        uses_tomorrow = (not is_daylight) and start.astimezone(now.tzinfo).date() > now.date()
        return hrs, min(1.0, hrs / day_h), uses_tomorrow

    def _update_tracking_stats(self, cur_price, cur_pv, cur_batt_pwr, cur_house):
        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=7.5)
        ref_price = self._get_float_state(self.reference_price_id, default=0.40)

        if self._battery_stored_kwh < 0:
            self._battery_stored_kwh = 0.0
        if self._battery_stored_kwh > batt_cap:
            self._battery_stored_kwh = batt_cap

        if cur_pv > 0 and cur_house > 0:
            direct_pv_kwh = (min(cur_pv, cur_house) / 1000.0) * (1.0 / 60.0)
            pv_direct_save = direct_pv_kwh * cur_price
            self._set_tracking_state(self.pv_savings_month_id, self._get_tracking_state(self.pv_savings_month_id) + pv_direct_save)
            self._set_tracking_state(self.pv_savings_total_id, self._get_tracking_state(self.pv_savings_total_id) + pv_direct_save)

        if cur_batt_pwr < -100:
            charged_kwh_min = (abs(cur_batt_pwr) / 1000.0) * (1.0 / 60.0)
            pv_surplus_w = max(0.0, cur_pv - cur_house)
            pv_part_kwh = min(charged_kwh_min, (pv_surplus_w / 1000.0) * (1.0 / 60.0))
            grid_part_kwh = max(0.0, charged_kwh_min - pv_part_kwh)

            cost_this_minute = grid_part_kwh * cur_price
            total_cost_before = self._battery_stored_kwh * self._battery_avg_buy_price
            new_total_stored = self._battery_stored_kwh + charged_kwh_min

            if new_total_stored > 0:
                self._battery_avg_buy_price = (total_cost_before + cost_this_minute) / new_total_stored

            self._battery_stored_kwh = min(new_total_stored, batt_cap)

            if grid_part_kwh > 0:
                cost = grid_part_kwh * cur_price
                saved_vs_ref = grid_part_kwh * max(0.0, ref_price - cur_price)
                self._set_tracking_state(self.cost_month_id, self._get_tracking_state(self.cost_month_id) + cost)
                self._set_tracking_state(self.cost_total_id, self._get_tracking_state(self.cost_total_id) + cost)
                self._set_tracking_state(self.savings_month_id, self._get_tracking_state(self.savings_month_id) + saved_vs_ref)
                self._set_tracking_state(self.savings_total_id, self._get_tracking_state(self.savings_total_id) + saved_vs_ref)
                self._set_tracking_state(self.charged_kwh_month_id, self._get_tracking_state(self.charged_kwh_month_id) + grid_part_kwh, 4)
                self._set_tracking_state(self.charged_kwh_total_id, self._get_tracking_state(self.charged_kwh_total_id) + grid_part_kwh, 4)

        elif cur_batt_pwr > 100:
            discharged_kwh_min = (cur_batt_pwr / 1000.0) * (1.0 / 60.0)
            kwh_needed_from_store = discharged_kwh_min / self.efficiency_factor

            cost_if_bought_now = discharged_kwh_min * cur_price
            cost_when_stored = kwh_needed_from_store * self._battery_avg_buy_price
            real_profit = max(0.0, cost_if_bought_now - cost_when_stored)

            self._battery_stored_kwh = max(0.0, self._battery_stored_kwh - kwh_needed_from_store)

            if real_profit > 0:
                self._set_tracking_state(self.discharge_savings_month_id, self._get_tracking_state(self.discharge_savings_month_id) + real_profit)
                self._set_tracking_state(self.discharge_savings_total_id, self._get_tracking_state(self.discharge_savings_total_id) + real_profit)

        self._update_monthly_report()

    def reset_monthly_stats_daily_check(self, kwargs):
        now = self.get_now()
        if now.day == 1:
            attr = self._safe_get_state(self.report_id, attribute='all', default={})
            if isinstance(attr, dict) and attr.get('attributes'):
                attr = attr['attributes']
            else:
                attr = {}
            last_reset = attr.get('last_reset_date', '')
            if last_reset != now.strftime('%Y-%m-%d'):
                try:
                    for eid in [self.pv_savings_month_id, self.cost_month_id, self.savings_month_id, self.discharge_savings_month_id]:
                        self._set_tracking_state(eid, 0.0)
                    self._set_tracking_state(self.charged_kwh_month_id, 0.0, 4)
                    attr['last_reset_date'] = now.strftime('%Y-%m-%d')
                    self.set_state(self.report_id, state=self._safe_get_state(self.report_id, default=""), attributes=attr)
                except Exception as e:
                    if self.log_debug_level:
                        self.log(f"Reset Monatsstatistik Fehler: {e}", level="ERROR")
        self._update_monthly_report()

    def _update_monthly_report(self):
        if not self.report_id:
            return
        now = self.get_now()
        report = (
            f"Monat ({now.strftime('%B %Y')}):\n"
            f"{self.T['REPORT_GRID_COST']}: {self._get_tracking_state(self.cost_month_id):.2f} EUR\n"
            f"{self.T['REPORT_CHARGE_SAVE']}: {self._get_tracking_state(self.savings_month_id):.2f} EUR\n"
            f"{self.T['REPORT_DISCHARGE_VALUE']}: {self._get_tracking_state(self.discharge_savings_month_id):.2f} EUR\n"
            f"{self.T['REPORT_PV_VALUE']}: {self._get_tracking_state(self.pv_savings_month_id):.2f} EUR\n"
            f"{self.T['REPORT_CHARGED_KWH']}: {self._get_tracking_state(self.charged_kwh_month_id):.2f} kWh\n"
            f"Ø-Einkaufspreis Akku: {self._battery_avg_buy_price:.3f} EUR/kWh"
        )
        try:
            self.set_state(self.report_id, state=report)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"Report SetState Fehler: {e}", level="ERROR")

    # ==========================================================
    # HAUPTLOGIK
    # ==========================================================
    def main_logic(self, kwargs):
        self._state_cache.clear()
        app_is_enabled = (self._safe_get_state(self.app_enabled_switch_id, default='on') == 'on')

        if not app_is_enabled:
            if self.dashboard_status_text_id:
                self.set_state(self.dashboard_status_text_id, state="SmartPriceCharge deaktiviert")
            return

        now = self.get_now()
        today_date = now.date()
        start_slot = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)

        cur_soc = self._get_float_state(self.current_soc_sensor_id, default=50.0)
        cur_pv = self._get_float_state(self.current_pv_power_sensor_id, default=0.0)
        cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id, default=0.0)
        cur_grid = self._get_float_state(self.grid_power_import_export_sensor_id, default=0.0)
        cur_house = self._get_float_state(self.current_house_consumption_w_id, default=300.0)
        self._pv_track(now, cur_pv, self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0))

        dod = self._get_float_state(self.min_soc_discharge_id, default=90.0)
        base_min_soc = (100.0 - dod) if dod > 50.0 else dod

        # ==========================================================
        # EV ZIEL- & PENDLER-LOGIK
        # ==========================================================
        ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=50.0)
        ev_daily_grid_target = self._get_float_state(self.ev_target_soc_id, default=40.0)

        dl_hour, dl_minute = 7, 0
        if self.monday_deadline_time_id:
            try:
                t_str = str(self._safe_get_state(self.monday_deadline_time_id, default=""))
                if t_str and t_str not in ['unavailable', 'unknown', 'none']:
                    parts = t_str.split(':')
                    dl_hour, dl_minute = int(parts[0]), int(parts[1])
            except Exception:
                pass

        mon_grid_target = self._get_float_state(self.monday_min_soc_id, default=80.0)
        monday_start_hour = int(self.args.get('monday_deadline_start_hour', 12))

        is_mon_sec = False
        if (now.weekday() == 6 and now.hour >= monday_start_hour) or (
            now.weekday() == 0 and (now.hour < dl_hour or (now.hour == dl_hour and now.minute <= dl_minute))
        ):
            is_mon_sec = True
            ev_grid_target = max(ev_daily_grid_target, mon_grid_target)
        else:
            ev_grid_target = ev_daily_grid_target

        ev_max_pv_soc = max(80.0, ev_grid_target, ev_daily_grid_target)

        wb_status = str(self._safe_get_state(self.ev_wallbox_status_id, default="")).strip().lower()
        wb_force = str(self._safe_get_state(self.ev_wallbox_switch_id, default="")).strip().lower()
        charging_states = {"charging", "laden", "2", "on", "true"}
        ev_active = (wb_status in charging_states)

        plug_state = str(self._safe_get_state(self.ev_plug_sensor_id, default="")).strip().lower()
        connected_wb_states = {"laden", "charging", "abgeschlossen", "complete", "warten", "wait", "2", "3", "4"}
        car_connected = (plug_state == 'on') or (wb_status in connected_wb_states)

        is_manual_override = (self._safe_get_state(self.ev_boost_switch_id) == 'on') if self.ev_boost_switch_id else False

        # ==========================================================
        # PV PROGNOSEN & SCHWELLENWERTE
        # ==========================================================
        fc_rem = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        fc_next = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        fc_now = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        fc_tmrw = self._get_float_state(self.pv_forecast_tomorrow_id, default=0.0)

        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=7.5)
        charge_pwr = self._get_float_state(self.charger_power_kw_id, default=3.5)
        target_soc = self._get_float_state(self.target_soc_id, default=100.0)
        pv_fc_thresh = self._get_float_state(self.pv_forecast_threshold_kw_id, default=1.0)
        cur_pv_thresh = self._get_float_state(self.current_pv_threshold_w_id, default=1000.0)
        price_discharge_limit = self._get_float_state(self.price_discharge_threshold_id, default=0.30)
        user_intervals = int(self._get_float_state(self.charge_intervals_input_id, default=12))

        ev_cap = self.ev_battery_capacity_kwh
        ev_pwr = self.ev_charger_power_kw

        ev_gap_kwh = max(0.0, ((ev_grid_target - ev_current_soc) / 100.0) * ev_cap / self.efficiency_factor) if (self.ev_logic_active_id and self._safe_get_state(self.ev_logic_active_id) == 'on') else 0.0
        tomorrow_weekday = (now.weekday() + 1) % 7
        dynamic_summer_threshold = 10.0 + (ev_gap_kwh if tomorrow_weekday in [5, 6] else 0.0)

        if self.log_debug_level:
            self.log(
                f"HAUS-SoC:{cur_soc:.1f}% | PV:{cur_pv:.0f}W (Schwelle:{cur_pv_thresh:.0f}W) | "
                f"FC-Now:{fc_now:.2f}kWh (Schwelle:{pv_fc_thresh:.2f}kW) | FC-Rest:{fc_rem:.2f}kWh | FC-Morgen:{fc_tmrw:.1f}kWh",
                level="INFO"
            )
            self.log(
                f"EV-Schutz Check: WB-Status='{wb_status}', Switch='{wb_force}' -> WB Aktiv: {ev_active} | "
                f"EV-SoC: {ev_current_soc}% (Ziel(Aktiv): {ev_grid_target}% | Täglich: {ev_daily_grid_target}%, "
                f"Montag: {mon_grid_target}%, MonAktiv: {is_mon_sec}, PV-Max: {ev_max_pv_soc}%)",
                level="INFO"
            )

        peak_dt = None
        if self.pv_peak_time_sensor_id:
            s = str(self._safe_get_state(self.pv_peak_time_sensor_id, default=""))
            if s and s not in ['unavailable', 'unknown', 'none']:
                try:
                    peak_dt = datetime.fromisoformat(s)
                    if peak_dt.tzinfo is None:
                        peak_dt = peak_dt.replace(tzinfo=now.tzinfo)
                except Exception:
                    pass

        prices_today = self._safe_get_state(self.price_sensor_id, attribute='today', default=[])
        prices_tmrw = self._safe_get_state(self.price_sensor_id, attribute='tomorrow', default=[])

        all_prices = []
        if isinstance(prices_today, list):
            for i, p in enumerate(prices_today):
                if isinstance(p, dict) and 'total' in p:
                    dt = self._parse_slot_time(p, i, today_date, now.tzinfo)
                    if dt >= start_slot:
                        all_prices.append({'price': float(p['total']), 'time_dt': dt})

        if isinstance(prices_tmrw, list):
            for i, p in enumerate(prices_tmrw):
                if isinstance(p, dict) and 'total' in p:
                    dt = self._parse_slot_time(p, i, today_date + timedelta(days=1), now.tzinfo)
                    all_prices.append({'price': float(p['total']), 'time_dt': dt})

        if not all_prices:
            self._set_error_states('ERROR_NO_PRICE_DATA')
            return

        cur_price = all_prices[0]['price']
        global_peak = max(all_prices, key=lambda x: x['price'])
        max_future_price = global_peak['price']
        min_future_price = min(x['price'] for x in all_prices)

        # DYNAMISCHE PREISSCHWELLE: Die Entladeschwelle aus dem Dashboard bleibt als Untergrenze bestehen.
        # Liegen aber ALLE Preise darüber (Winter: 0.44-0.62 bei Schwelle 0.30), wären Hold, Morgen-Brücke,
        # Panic-Mode und Slot-Pool wirkungslos. Dann gilt die Mitte der Preisspanne als Grenze billig/teuer.
        price_discharge_limit_user = price_discharge_limit
        if (max_future_price - min_future_price) >= self.peak_swing_eur:
            price_discharge_limit = max(price_discharge_limit, min_future_price + 0.5 * (max_future_price - min_future_price))

        # NÄCHSTER relevanter Preisberg statt globalem Maximum über bis zu 2 Tage.
        peak_item = self._find_next_peak(all_prices, self.peak_swing_eur) or global_peak
        peak_time_slot = peak_item['time_dt']
        peak_price = peak_item['price']
        cur_spread = peak_price - cur_price

        # SoC-Staffelung des Mindestabstands: soll verhindern, dass ein (fast) voller Akku die PV blockiert.
        # Gilt nur, solange die PV wirklich produziert; am Abend wird für den Peak gehalten.
        eff_spread = self.base_min_price_spread_eur
        if cur_pv > 300.0:
            if cur_soc > self.soc_threshold_high:
                eff_spread = max(eff_spread, self.spread_high_soc_eur)
            elif cur_soc > self.soc_threshold_medium:
                eff_spread = max(eff_spread, self.spread_medium_soc_eur)

        # ==========================================================
        # ZWEI-HORIZONTE-LOGIK (Morgen-Peak vs. Abend-Peak!)
        # ==========================================================
        avg_load_w = max(200.0, min(1500.0, self._get_float_state(self.avg_consumption_sensor_id, default=500.0)))
        usable_soc_kwh = max(0.0, (cur_soc - base_min_soc) / 100.0 * batt_cap) * self.efficiency_factor

        morning_date = today_date if now.hour < 10 else (today_date + timedelta(days=1))
        morning_window = [
            x for x in all_prices
            if x['time_dt'].date() == morning_date and 5 <= x['time_dt'].hour < 10 and x['time_dt'] >= start_slot
        ]

        morning_bridge_active = False
        morning_deadline = None
        morning_deficit_kwh = 0.0
        bridge_peak_price = None

        if (now.hour >= 18 or now.hour < 9) and morning_window:
            max_morning_slot = max(morning_window, key=lambda x: x['price'])
            max_morning_price = max_morning_slot['price']
            pre_morning_pool = [x for x in all_prices if x['time_dt'] < max_morning_slot['time_dt'] and x['time_dt'] >= start_slot]
            min_night_price = min([x['price'] for x in pre_morning_pool]) if pre_morning_pool else cur_price

            if (max_morning_price >= price_discharge_limit or (max_morning_price - min_night_price) >= self.morning_min_diff) and min_night_price < price_discharge_limit:
                end_of_morning_peak = datetime.combine(morning_date, time(10, 0)).replace(tzinfo=now.tzinfo)
                # PV übernimmt kurz nach Sonnenaufgang, wenn die Tagesprognose brauchbar ist
                sun_morning_kwh = fc_rem if morning_date == today_date else fc_tmrw
                if sun_morning_kwh >= self.pv_takeover_min_kwh:
                    rise_dt = self._sun_time('next_rising', now)
                    if rise_dt is not None:
                        end_of_morning_peak = min(end_of_morning_peak, rise_dt.astimezone(now.tzinfo) + timedelta(hours=self.pv_takeover_delay_h))
                # Bedarf = Last x Anzahl der TEUREN Morgen-Slots (Preis nach Wirkungsgrad über dem Nacht-Ladepreis),
                # gezählt ab dem letzten günstigen Nachtslot bis zum Ende des Peaks bzw. der PV-Übernahme.
                # (Früher: feste Last x 5 h = mehr als der Akku fasst -> jede Nacht Vollladung aus dem Netz.)
                cheapest_night = [x for x in pre_morning_pool if x['price'] <= min_night_price + self.price_tie_eur]
                cheap_t = max(cheapest_night, key=lambda x: x['time_dt'])['time_dt'] if cheapest_night else now
                thr_morning = (min_night_price + self.min_cycle_profit_eur) / self.efficiency_factor
                for x in all_prices:
                    if x['time_dt'] > max_morning_slot['time_dt'] and x['price'] < thr_morning:
                        end_of_morning_peak = min(end_of_morning_peak, x['time_dt'])
                        break
                n_morning = sum(1 for x in all_prices if cheap_t < x['time_dt'] < end_of_morning_peak and x['price'] >= thr_morning)
                hours_until_morning_end = n_morning * 0.25
                morning_load = self.morning_load_w if self.morning_load_w > 0 else min(avg_load_w, self.max_load_w)
                needed_for_morning_kwh = max(
                    ((self.sleep_over_soc - base_min_soc) / 100.0) * batt_cap * self.efficiency_factor,
                    (morning_load / 1000.0) * hours_until_morning_end * (1.0 + self.peak_reserve_margin)
                )
                if self.log_debug_level:
                    self.log(f"Brücke Bedarf: {needed_for_morning_kwh:.1f}kWh ({n_morning} teure Morgen-Slots bis {end_of_morning_peak.strftime('%H:%M')}, Last {morning_load:.0f}W, Reserve {self.sleep_over_soc:.0f}%), nutzbar {usable_soc_kwh:.1f}kWh", level="INFO")

                if usable_soc_kwh < needed_for_morning_kwh and pre_morning_pool:
                    morning_bridge_active = True
                    morning_deadline = max_morning_slot['time_dt']
                    morning_deficit_kwh = (needed_for_morning_kwh - usable_soc_kwh) / self.efficiency_factor
                    bridge_peak_price = max_morning_price

        min_interim = 9.99
        interim_dip = False
        if peak_time_slot > now:
            for item in all_prices:
                if item['time_dt'] > now and item['time_dt'] < peak_time_slot:
                    if item['price'] < min_interim:
                        min_interim = item['price']
            refill_profit = cur_price - (min_interim / self.efficiency_factor)
            if refill_profit > self.min_cycle_profit_eur:
                interim_dip = True

        should_hold = (cur_price < price_discharge_limit) and (cur_spread >= eff_spread) and (not interim_dip)

        effective_min_soc = base_min_soc
        if prices_tmrw and now.hour >= 18:
            morning_peak_price = 0.0
            for item in all_prices:
                if item['time_dt'].date() == (today_date + timedelta(days=1)) and 5 <= item['time_dt'].hour <= 9:
                    if item['price'] > morning_peak_price:
                        morning_peak_price = item['price']
            if (morning_peak_price - cur_price) > self.morning_min_diff:
                effective_min_soc = max(base_min_soc, self.sleep_over_soc)

        if morning_bridge_active and morning_deadline is not None:
            deadline = morning_deadline
            is_morning_peak = True
            plan_peak_price = bridge_peak_price
        else:
            deadline = peak_time_slot if peak_price > price_discharge_limit else datetime.combine(today_date, time(23, 59)).replace(tzinfo=now.tzinfo)
            is_morning_peak = deadline.hour < 10
            plan_peak_price = peak_price

        # Nur Slots, in denen sich Netzladen gegenüber dem Peak nach Wirkungsgrad noch lohnt
        max_buy_price = plan_peak_price * self.efficiency_factor - self.min_cycle_profit_eur
        pool = [x for x in all_prices if start_slot <= x['time_dt'] < deadline and x['price'] <= max_buy_price]
        if morning_bridge_active:
            pool = [x for x in pool if x['price'] < price_discharge_limit]

        # SONNEN-REGEL (Ziel-SoC senken, wenn die PV den Akku ohnehin wieder füllt) gilt NUR, wenn der Plan
        # über die Nacht geht oder kein Abend-Peak ansteht. Für den heutigen Abend-Peak hilft die Sonne von
        # morgen nicht: der Akku muss heute gefüllt werden.
        evening_peak_today = (deadline.date() == today_date and deadline.hour >= 10 and peak_price > price_discharge_limit)
        if not morning_bridge_active and not evening_peak_today:
            sun_after_kwh = fc_rem if (deadline.hour < 10 and deadline.date() == today_date) else fc_tmrw
            if sun_after_kwh >= dynamic_summer_threshold and target_soc > self.sleep_over_soc:
                target_soc = self.sleep_over_soc

        # --- ENERGIE-BILANZ bis zur Deadline (nur Plan ohne Morgen-Brücke) ---
        pv_surplus_kwh = 0.0
        pv_hours = 0.0
        pv_fc_kwh = 0.0
        plan_load_w = 0.0
        pv_sf = self._pv_auto_factor if (self.pv_auto_calibrate and self._pv_auto_factor) else self.pv_forecast_safety_factor
        if not morning_bridge_active:
            # Im Hold bleibt die Batterieenergie bis zum Peak erhalten. Gutschreiben darf man nur den
            # PV-ÜBERSCHUSS (Prognose minus Hausverbrauch während der PV-Stunden), nicht die gesamte PV.
            is_daylight_plan = float(self._safe_get_state(self.sun_sensor_id, attribute='elevation', default=0)) > 0
            pv_hours, pv_share, pv_uses_tomorrow = self._pv_window(now, deadline, is_daylight_plan)
            pv_fc_kwh = fc_tmrw if pv_uses_tomorrow else fc_rem
            avg_24h_w = max(200.0, min(self.max_load_w, self._get_float_state(self.avg_consumption_sensor_id, default=500.0)))
            plan_load_w = max(200.0, 0.5 * avg_24h_w + 0.5 * min(self.max_load_w, cur_house))
            if pv_hours > 0:
                pv_surplus_kwh = max(0.0, pv_fc_kwh * pv_share - (plan_load_w / 1000.0) * pv_hours) * pv_sf

        def _slots_for(need_kwh):
            return min(int(math.ceil((need_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0, user_intervals)

        def _pick_slots(n):
            tie = self.price_tie_eur
            if not pool or n <= 0:
                return []
            return sorted(pool, key=lambda x: (round(x['price'] / tie) if tie > 0 else x['price'], x['time_dt']))[:n]

        # --- BEDARFSORIENTIERTES LADEZIEL (Ladeziel aus dem Dashboard = Obergrenze) ---
        # Eine kWh im Akku lohnt sich nur, wenn sie später in einem Slot verbraucht wird, dessen Preis nach
        # Wirkungsgrad über dem Ladepreis + Mindestgewinn liegt. Das teure Fenster reicht von jetzt bis zum
        # ersten Slot NACH dem Peak, der unter diese Grenze fällt (dort kann günstig nachgeladen werden).
        target_soc_plan = target_soc
        hump_info = ""
        if self.need_based_target and not morning_bridge_active:
            # Der Bedarf zählt erst NACH dem letzten günstigen Ladeslot (was davor verbraucht wird, deckt die vorhandene Ladung)
            cheap_t = start_slot
            if pool:
                min_pool = min(x['price'] for x in pool)
                cheap_t = max((x for x in pool if x['price'] <= min_pool + self.price_tie_eur), key=lambda x: x['time_dt'])['time_dt']
            hump_load_w = (self.morning_load_w if self.morning_load_w > 0 else min(avg_load_w, self.max_load_w)) if is_morning_peak else avg_load_w

            def _target_for(charge_price):
                thr = (charge_price + self.min_cycle_profit_eur) / self.efficiency_factor
                end = None
                for x in all_prices:
                    if x['time_dt'] > deadline and x['price'] < thr:
                        end = x['time_dt']
                        break
                if end is None:
                    end = all_prices[-1]['time_dt'] + timedelta(minutes=15)
                if is_morning_peak:
                    # PV übernimmt kurz nach Sonnenaufgang, wenn die Tagesprognose brauchbar ist
                    sun_kwh = fc_rem if deadline.date() == today_date else fc_tmrw
                    if sun_kwh >= self.pv_takeover_min_kwh:
                        rise_dt = self._sun_time('next_rising', now)
                        if rise_dt is not None:
                            end = min(end, rise_dt.astimezone(now.tzinfo) + timedelta(hours=self.pv_takeover_delay_h))
                n_hump = sum(1 for x in all_prices if max(start_slot, cheap_t) <= x['time_dt'] < end and x['price'] >= thr)
                demand_kwh = n_hump * (hump_load_w / 1000.0) * 0.25 / self.efficiency_factor
                t_soc = min(target_soc, base_min_soc + demand_kwh * (1.0 + self.peak_reserve_margin) / batt_cap * 100.0)
                return t_soc, demand_kwh, n_hump, end

            if pool:
                p_charge = min(x['price'] for x in pool)
                t1 = _target_for(p_charge)[0]
                need1 = max(0.0, min((t1 - cur_soc) / 100 * batt_cap - pv_surplus_kwh, batt_cap))
                picked = _pick_slots(_slots_for(need1))
                if picked:
                    p_charge = sum(x['price'] for x in picked) / len(picked)
                target_soc_plan, demand_kwh, n_hump, hump_end = _target_for(p_charge)
                hump_info = f" | Peak-Fenster {n_hump} Slots bis {hump_end.strftime('%H:%M')} = {demand_kwh:.1f}kWh -> Ziel {target_soc_plan:.0f}% (max {target_soc:.0f}%)"
            else:
                target_soc_plan = min(target_soc, cur_soc)

        need_soc_kwh = morning_deficit_kwh if morning_bridge_active else max(0.0, (target_soc_plan - cur_soc) / 100 * batt_cap)
        needed_kwh = max(0.0, min(need_soc_kwh - pv_surplus_kwh, batt_cap))
        slots_uncapped = int(math.ceil((needed_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0
        final_slots = _slots_for(needed_kwh)

        cheap_hours_info = "0x 15min (--:--) Ø 0.000 EUR"
        current_time_in_best_block = False
        best_slots = _pick_slots(final_slots)
        best_slots.sort(key=lambda x: x['time_dt'])

        if best_slots:
            avg_price_slots = sum(i['price'] for i in best_slots) / len(best_slots)
            cheap_hours_info = f"{len(best_slots)}x 15min ({best_slots[0]['time_dt'].strftime('%H:%M')}...{(best_slots[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')}) Ø {avg_price_slots:.3f} EUR"
            if any(s['time_dt'] == start_slot for s in best_slots):
                current_time_in_best_block = True
            if self.next_charge_time_id:
                self.set_state(self.next_charge_time_id, state=best_slots[0]['time_dt'].strftime('%H:%M'))
        elif self.next_charge_time_id:
            self.set_state(self.next_charge_time_id, state="--:--")

        if self.log_debug_level:
            self.log(
                f"PLAN: {'Morgen-Brücke' if morning_bridge_active else 'Peak'} {deadline.strftime('%d.%m %H:%M')} @{plan_peak_price:.3f} (Max {max_future_price:.3f}, Grenze {price_discharge_limit:.3f}/Schwelle {price_discharge_limit_user:.2f}) | "
                f"Bedarf {need_soc_kwh:.1f}kWh - PV-Überschuss {pv_surplus_kwh:.1f}kWh (PV {pv_fc_kwh:.1f}kWh, {pv_hours:.1f}h, Last {plan_load_w:.0f}W, Faktor {pv_sf:.2f}) "
                f"= {needed_kwh:.1f}kWh -> {slots_uncapped} Slots (Limit {user_intervals}, Pool {len(pool)}, max. Kaufpreis {max_buy_price:.3f}) | "
                f"Hold={should_hold} (Spread {cur_spread:.3f}/{eff_spread:.2f}, Dip={interim_dip}) Ziel-SoC {target_soc:.0f}%{hump_info}",
                level="INFO")
        if slots_uncapped > user_intervals and (now.hour, now.date()) != getattr(self, '_last_cap_warn', None):
            self._last_cap_warn = (now.hour, now.date())
            self.log(f"WARNUNG: Ladeplan braucht {slots_uncapped} Slots, begrenzt durch 'charge_intervals' = {user_intervals} "
                     f"(Einheit: 15-Minuten-Slots) - Akku erreicht Ziel-SoC evtl. nicht rechtzeitig.", level="WARNING")

        # Panic: kurz vor dem Peak noch Bedarf -> jetzt laden, aber nur wenn es sich gegenüber dem Peak noch lohnt
        profit_ok_now = (plan_peak_price * self.efficiency_factor - cur_price) >= self.min_cycle_profit_eur
        panic_mode = (deadline > now) and ((deadline - now).total_seconds() / 3600 < 1.5) and (needed_kwh > 0.2) and profit_ok_now

        weather_factor = 0.5
        try:
            cloud_val = 1.0 - (float(self._safe_get_state(self.cloud_coverage_sensor_id, default=50)) / 100.0) if self.cloud_coverage_sensor_id else None
            if cloud_val is not None:
                weather_factor = max(0.0, min(1.0, cloud_val))
            elif self.weather_sensor_id:
                weather_factor = WEATHER_PV_FACTOR.get(self._safe_get_state(self.weather_sensor_id, default="cloudy"), 0.5)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"Wetterfaktor Fehler: {e}", level="ERROR")

        is_daylight = float(self._safe_get_state(self.sun_sensor_id, attribute='elevation', default=0)) > 0
        approaching_peak = peak_dt and (-30 < (peak_dt - now).total_seconds() / 60 < 90)

        # Respektiert strikt deine beiden Dashboard-Schwellenwerte:
        # 1. input_number.aktuelle_pv_ladeschwelle_w (cur_pv_thresh, z.B. 1000 W)
        # 2. input_number.pv_prognose_ladeschwelle_kw (pv_fc_thresh, z.B. 1.0 kW)
        is_sun_shining = (cur_pv >= cur_pv_thresh) or (
            is_daylight and weather_factor >= 0.4 and (fc_now >= pv_fc_thresh or fc_next >= pv_fc_thresh)
        )

        # ==========================================================
        # 🚗 EV PLANNING
        # ==========================================================
        ev_is_cheap_now = False
        ev_plan_text = self.T['STATUS_EV_PLAN_NONE']
        imm_price = self._get_float_state(self.ev_immediate_charge_price_id, default=float(self.args.get('ev_immediate_charge_price', 0.20)))

        if self.ev_logic_active_id and self._safe_get_state(self.ev_logic_active_id) == 'on':
            if is_manual_override:
                ev_is_cheap_now = True
                ev_plan_text = self.T['STATUS_EV_PLAN_BOOST'].format(target=int(ev_max_pv_soc))
            elif ev_current_soc < ev_grid_target:
                if is_mon_sec:
                    if now.weekday() == 6:
                        dl = (now + timedelta(days=1)).replace(hour=dl_hour, minute=dl_minute, second=0, microsecond=0).replace(tzinfo=now.tzinfo)
                    else:
                        dl = now.replace(hour=dl_hour, minute=dl_minute, second=0, microsecond=0).replace(tzinfo=now.tzinfo)
                else:
                    dl = now.replace(hour=7, minute=0, second=0, microsecond=0).replace(tzinfo=now.tzinfo)
                    if now >= dl:
                        dl += timedelta(days=1)

                needed_s = int(math.ceil((((ev_grid_target - ev_current_soc) / 100 * ev_cap) / self.efficiency_factor) / ev_pwr * 4))
                pool_ev = [x for x in all_prices if start_slot <= x['time_dt'] < dl]

                if pool_ev and needed_s > 0:
                    best_ev = sorted(pool_ev, key=lambda x: x['price'])[:needed_s]
                    best_ev.sort(key=lambda x: x['time_dt'])
                    if is_mon_sec:
                        ev_plan_text = f"Pendler-Ladung ({int(ev_grid_target)}%): {best_ev[0]['time_dt'].strftime('%H:%M')} - {(best_ev[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')}"
                    else:
                        ev_plan_text = self.T['STATUS_EV_PLAN_ACTIVE'].format(start=best_ev[0]['time_dt'].strftime('%H:%M'), end=(best_ev[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M'), slots=len(best_ev))
                    if any(s['time_dt'] == start_slot for s in best_ev):
                        ev_is_cheap_now = True

                if cur_price <= imm_price:
                    ev_is_cheap_now = True

        if self.ev_charge_plan_id:
            self.set_state(self.ev_charge_plan_id, state=ev_plan_text)

        # ==========================================================
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 1. WALLBOX DELEGATION (options: "0", "1", "2")
        # ==========================================================
        if car_connected:
            if is_manual_override:
                if ev_current_soc < ev_max_pv_soc:
                    self._set_wallbox_logic_mode("Default")
                    self._set_wallbox_state("2")
                else:
                    self._set_wallbox_logic_mode("Eco")
                    self._set_wallbox_state("1")
                    if getattr(self, 'ev_boost_switch_id', None):
                        self.turn_off(self.ev_boost_switch_id)

            elif ev_current_soc < ev_grid_target and ev_is_cheap_now:
                self._set_wallbox_logic_mode("Default")
                self._set_wallbox_state("2")

            else:
                required_battery_soc = self.home_battery_priority_soc - self.home_battery_priority_hysteresis if ev_active else self.home_battery_priority_soc

                if is_daylight and ev_current_soc < ev_max_pv_soc and cur_soc >= required_battery_soc:
                    self._set_wallbox_logic_mode("Eco")
                    self._set_wallbox_state("0")
                else:
                    self._set_wallbox_logic_mode("Eco")
                    self._set_wallbox_state("1")
        else:
            self._set_wallbox_logic_mode("Eco")
            self._set_wallbox_state("1")
            if is_manual_override and getattr(self, 'ev_boost_switch_id', None):
                self.turn_off(self.ev_boost_switch_id)

        # ==========================================================
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 2. HAUSAKKU
        # ==========================================================
        charge_toggle_on = False
        # PV (abzüglich Haus) lastet den Lader schon (fast) aus -> kein Netzstrom nötig
        pv_saturates = (cur_pv - cur_house) >= 0.8 * charge_pwr * 1000.0
        # EV lädt gerade per Netz (Boost oder günstiger Slot) -> Hausakku darf nicht ins Auto entladen
        ev_grid_slot = ev_active and (is_manual_override or (ev_current_soc < ev_grid_target and ev_is_cheap_now))

        # 1. EV-SCHUTZ (Wenn Auto lädt und Hausakku < 50% -> Hausakku im Standby schützen)
        if (ev_active or is_manual_override) and cur_soc < 50:
            self._set_inverter_mode(self.mode_backup)
            if self.dashboard_status_text_id:
                self.set_state(self.dashboard_status_text_id, state="EV aktiv: Hausakku Standby (Schutz <50%)")

        # 2. GEPLANTES NETZLADEN (auch bei Sonne: der Plan hat den PV-Überschuss schon abgezogen; im Modus
        #    'charge_battery' wird PV ohnehin zuerst genutzt. 'grid_charge_in_sun: false' stellt das alte Verhalten her.)
        elif cur_soc < target_soc and not pv_saturates and (self.grid_charge_in_sun or cur_pv < cur_pv_thresh or panic_mode) and (panic_mode or current_time_in_best_block or (cur_price <= imm_price and (self.grid_charge_in_sun or not is_sun_shining))):
            slot_profitable = ((plan_peak_price * self.efficiency_factor) - cur_price) >= self.min_cycle_profit_eur
            is_dip = (cur_spread >= self.base_min_price_spread_eur)
            allow = slot_profitable if (current_time_in_best_block or panic_mode) else ((cur_price <= price_discharge_limit) or is_dip)

            if allow or cur_price <= imm_price:
                charge_toggle_on = True
                self._set_inverter_mode(self.mode_charge)
                if self.dashboard_status_text_id:
                    # Plan-Kurzinfo fürs Dashboard: wie lange noch, wie viel Bedarf, bis zu welchem Ziel
                    if morning_bridge_active:
                        plan_txt = f"Morgen-Brücke: noch {len(best_slots)} Slots, Bedarf {needed_kwh:.1f}kWh"
                    elif panic_mode and not current_time_in_best_block:
                        plan_txt = f"Nachladen vor Peak {plan_peak_price:.2f}€, Bedarf {needed_kwh:.1f}kWh"
                    else:
                        plan_txt = f"noch {len(best_slots)} Slots, Bedarf {needed_kwh:.1f}kWh, Ziel {target_soc_plan:.0f}%, Peak {plan_peak_price:.2f}€"
                    self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_ACTIVE']}: {cur_price:.3f}€ / Slot aktiv | {plan_txt}")
            else:
                self._set_inverter_mode(self.mode_backup if should_hold else self.mode_general)
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_BLOCKED']} ({cur_price:.3f} EUR).")

        # 3. ECHTER PV-ÜBERSCHUSS (HAT JETZT IMMER VORRANG VOR DEM STANDBY!)
        elif is_sun_shining:
            if cur_soc < self.home_battery_priority_soc:
                if ev_grid_slot:
                    # Auto lädt aus dem Netz: sonst würde 'auto' den Hausakku ins Auto leeren
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state="EV lädt (Netz): Hausakku Standby")
                elif should_hold and cur_pv < (cur_house - 150.0):
                    # PV deckt das Haus nicht: im Modus 'auto' würde der Akku vor dem Peak entladen.
                    # Es gibt keinen PV-Überschuss, also geht durch Standby auch nichts verloren.
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_WAIT_HOLD']} (PV {cur_pv:.0f}W < Haus {cur_house:.0f}W, Akku für Peak {plan_peak_price:.2f}€)")
                else:
                    self._set_inverter_mode(self.mode_general)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state=f"PV-Eigenverbrauch: Hausakku Prio ({cur_pv:.0f}W | <{self.home_battery_priority_soc}%)")
            else:
                if ev_active and cur_batt_pwr > 500:
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state="EV lädt PV (Akku Standby)")
                else:
                    self._set_inverter_mode(self.mode_general)
                    if cur_batt_pwr < -100:
                        charge_toggle_on = True
                        if self.dashboard_status_text_id:
                            self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_PV_CHARGING']}.")
                    else:
                        if self.dashboard_status_text_id:
                            self.set_state(self.dashboard_status_text_id, state=f"Eigenverbrauch aktiv ({cur_pv:.0f}W PV)")

        # 4. AKKU SPAREN FÜR DEN PEAK (Spread-Hold: Greift NUR, wenn KEINE starke Sonne da ist!)
        elif should_hold and cur_soc < target_soc:
            self._set_inverter_mode(self.mode_backup)
            if self.dashboard_status_text_id:
                self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_WAIT_HOLD']} ({cur_soc:.0f}% für Peak gehalten)")

        # 5. ENTLADEN INS HAUS FREIGEBEN
        elif (cur_price >= price_discharge_limit) or cur_soc >= target_soc or interim_dip or (not should_hold):
            if cur_soc > effective_min_soc:
                if ev_active or is_manual_override:
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state="EV lädt (Hausakku Standby)")
                else:
                    status_msg = f"{self.T['STATUS_DISCHARGE_DIP']}" if interim_dip else f"{self.T['STATUS_DISCHARGE_BASE']}"
                    if cur_soc >= target_soc:
                        status_msg = "Ziel-SoC erreicht: Normalbetrieb (Eigenverbrauch)"
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state=status_msg)
                    self._set_inverter_mode(self.mode_general)
            else:
                status_msg = f"{self.T['STATUS_DISCHARGE_RESERVE_REACHED']} ({effective_min_soc}%)."
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state=status_msg)
                self._set_inverter_mode(self.mode_backup)

        # 6. FALLBACK
        else:
            if ev_active or is_manual_override:
                self._set_inverter_mode(self.mode_backup)
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state="EV lädt (Standby).")
            else:
                self._set_inverter_mode(self.mode_backup if should_hold else self.mode_general)
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_WAIT_HOLD'] if should_hold else self.T['STATUS_IDLE']}.")

        if hasattr(self, 'cheap_hour_toggle_id') and self.cheap_hour_toggle_id:
            if charge_toggle_on:
                self.turn_on(self.cheap_hour_toggle_id)
            else:
                self.turn_off(self.cheap_hour_toggle_id)
        if self.cheap_hours_text_id:
            self.set_state(self.cheap_hours_text_id, state=cheap_hours_info)

        self._update_tracking_stats(cur_price, cur_pv, cur_batt_pwr, cur_house)

    def check_weekly_ai_trigger(self, kwargs):
        if self.gemini_api_key:
            if self.get_now().weekday() == 6:
                self.trigger_ai_analysis("event", {}, {})

    def trigger_ai_analysis_button(self, entity, attribute, old, new, kwargs):
        self.trigger_ai_analysis("button", {}, {})

    def trigger_ai_analysis(self, event_name: str, data: dict, kwargs: dict) -> None:
        if not self.gemini_api_key:
            return
        self.log("KI-Analyse: Starte Daten-Sammlung...", level="INFO")
        threading.Thread(target=self._perform_gemini_analysis).start()

    def _perform_gemini_analysis(self) -> None:
        if not self.gemini_api_key:
            return
        try:
            def _get_live(eid):
                if not eid:
                    return 0.0
                try:
                    st = self.get_state(eid)
                    return float(st) if st not in ['unavailable', 'unknown', 'none', None] else 0.0
                except Exception:
                    return 0.0

            cost = _get_live(self.cost_month_id)
            saved = _get_live(self.savings_month_id)
            discharge_saved = _get_live(self.discharge_savings_month_id)
            pv_saved = _get_live(self.pv_savings_month_id)
            kwh = _get_live(self.charged_kwh_month_id)

            total_saved = discharge_saved + pv_saved

            self.log(
                f"KI-Analyse Live-Daten: Cost={cost:.2f}€, ChargeSave={saved:.2f}€, "
                f"Arbitrage={discharge_saved:.2f}€, PV={pv_saved:.2f}€, kWh={kwh:.2f}",
                level="INFO"
            )

            if round(cost, 2) <= 0.0 and round(total_saved, 2) <= 0.0 and round(kwh, 2) <= 0.0:
                if self.ai_advice_text_id:
                    self.set_state(self.ai_advice_text_id, state="Keine aktuellen Statistikdaten in Home Assistant gefunden.")
                return

            prompt = (
                f"Smart Home Energieberater: Netzkosten: {cost:.2f} EUR. "
                f"Gesamtersparnis: {total_saved:.2f} EUR (Arbitrage-Gewinn: {discharge_saved:.2f} EUR, PV-Direkt: {pv_saved:.2f} EUR). "
                f"Geladene Netz-Energie (Akku): {kwh:.2f} kWh. Ø-Speicher-Einkaufspreis: {self._battery_avg_buy_price:.3f} EUR. "
                "Gib eine kurze, prägnante Einschätzung (1-2 Sätze) für den Hausbesitzer."
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.gemini_api_key
            }
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            advice = result['candidates'][0]['content']['parts'][0]['text']
            advice = advice.replace('\n', ' ').strip()
            if len(advice) > 255:
                advice = advice[:252] + "..."
            if self.ai_advice_text_id:
                self.set_state(self.ai_advice_text_id, state=advice)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"KI-Request fehlgeschlagen: {e}", level="ERROR")

    def terminate(self):
        self.log(f"INFO: {self.T['INFO_APP_TERMINATED']}", level="INFO")
        with self._lock:
            if self._wb_timer_handle is not None:
                try:
                    self.cancel_timer(self._wb_timer_handle)
                except Exception:
                    pass
                self._wb_timer_handle = None
