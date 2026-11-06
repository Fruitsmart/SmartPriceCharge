# ==============================================================================
# SmartPriceCharge Configuration (v6.6.0 - Peak-Absicherung, PV-Bilanz, Netzladen bei Sonne)
# ==============================================================================
# AppDaemon Application for Intelligent Battery & EV Charging with Tibber & GoodWe
# ==============================================================================

import appdaemon.plugins.hass.hassapi as hass
import requests
import json
import math
import threading
from datetime import datetime, time, timedelta

APP_VERSION = "6.6.0"

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
        'REPORT_DISCHARGE_VALUE': "Entlade-Ersparnis",
        'REPORT_PV_VALUE': "PV-Direkt-Ersparnis",
        'REPORT_CHARGED_KWH': "Geladene kWh",
        'STATUS_PV_CHARGING': "PV-Laden aktiv",
        'STATUS_DISCHARGE_BASE': "Entladen aktiv (Netzunterstützung)",
        'STATUS_DISCHARGE_DIP': "Entladen aktiv (Preistief überbrücken)",
        'STATUS_DISCHARGE_RESERVE_REACHED': "Entladen gestoppt: Reserve erreicht",
        'STATUS_CHARGE_ACTIVE': "Laden aktiv (Günstiger Slot)",
        'STATUS_CHARGE_BLOCKED': "Laden gesperrt (Preis zu hoch)",
        'STATUS_TARGET_REACHED': "Ziel-SoC erreicht: Standby / Normalbetrieb",
        'STATUS_EV_PLAN_NONE': "Kein EV-Plan aktiv",
        'STATUS_EV_PLAN_BOOST': "Sofort-Laden (Boost) bis {target}%",
        'STATUS_EV_PLAN_ACTIVE': "EV Billig-Slots ({start} - {end}, {slots} Slots)",
        'STATUS_EV_CHEAP': "EV-Laden aktiv: Günstiger Slot ({target}%)",
        'STATUS_EV_PV': "EV-Laden aktiv: PV-Überschuss",
        'STATUS_WAIT_HOLD': "Warten (Spread-Hold)",
        'STATUS_WAIT_PV': "Warten auf PV-Überschuss",
        'STATUS_IDLE': "Standby / Normalbetrieb",
        'INFO_APP_INIT': "SmartPriceCharge v6.6.0 gestartet",
        'INFO_APP_TERMINATED': "SmartPriceCharge beendet",
        'INFO_CHARGE_START': "Ladevorgang gestartet.",
        'INFO_CHARGE_END': "Ladevorgang beendet.",
        'INFO_DISCHARGE_START': "Entladevorgang gestartet.",
        'INFO_DISCHARGE_END': "Entladevorgang beendet.",
        'ERROR_NO_PRICE_DATA': "Fehler: Keine Preisdaten von Tibber verfügbar!",
    },
    'EN': {
        'REPORT_GRID_COST': "Grid Costs",
        'REPORT_CHARGE_SAVE': "Charging Savings",
        'REPORT_DISCHARGE_VALUE': "Discharge Savings",
        'REPORT_PV_VALUE': "PV Direct Savings",
        'REPORT_CHARGED_KWH': "Charged kWh",
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
        'INFO_APP_INIT': "SmartPriceCharge v6.6.0 initialized",
        'INFO_APP_TERMINATED': "SmartPriceCharge terminated",
        'INFO_CHARGE_START': "Charging session started.",
        'INFO_CHARGE_END': "Charging session ended.",
        'INFO_DISCHARGE_START': "Discharging session started.",
        'INFO_DISCHARGE_END': "Discharging session ended.",
        'ERROR_NO_PRICE_DATA': "Error: No price data available from Tibber!",
    }
}


class SmartPriceCharge(hass.Hass):

    def initialize(self):
        self.lang = self.args.get('language', 'DE').upper()
        self.T = TRANSLATIONS.get(self.lang, TRANSLATIONS['DE'])
        self.log(f"INFO: {self.T['INFO_APP_INIT']} ({APP_VERSION})", level="INFO")

        self.log_debug_level = self.args.get('log_debug_level', False)
        self.efficiency_factor = float(self.args.get(
            'battery_efficiency_factor', self.args.get('efficiency_factor', 0.90)
        ))
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.06))
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 75.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 90.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.morning_min_diff = float(self.args.get('morning_min_diff', 0.08))
        # Ab welchem Preishub (EUR/kWh) ein Preisberg als eigener 'Peak' gilt (Abend-Peak, Morgen-Peak ...)
        self.peak_swing_eur = float(self.args.get('peak_swing_eur', 0.10))
        # Preise innerhalb dieser Toleranz gelten als gleich teuer -> frühester Slot gewinnt
        self.price_tie_eur = float(self.args.get('price_tie_eur', 0.01))
        # Obergrenze für die Hauslast-Schätzung (W) aus dem 24h-Durchschnitt
        self.max_load_w = float(self.args.get('max_load_w', 1000.0))

        # Sensor IDs
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

        self.sun_sensor_id = self.args.get('sun_sensor_id', None)
        self.weather_sensor_id = self.args.get('weather_sensor_id', None)
        self.cloud_coverage_sensor_id = self.args.get('cloud_coverage_sensor_id', None)

        self.battery_capacity_kwh_id = self.args['battery_capacity_kwh_id']
        self.charger_power_kw_id = self.args['charger_power_kw_id']
        self.target_soc_id = self.args['target_soc_id']
        self.pv_forecast_threshold_kw_id = self.args['pv_forecast_threshold_kw_id']
        self.current_pv_threshold_w_id = self.args['current_pv_threshold_w_id']
        self.price_discharge_threshold_id = self.args['price_discharge_threshold_id']
        self.min_soc_discharge_id = self.args['min_soc_discharge_id']
        self.reference_price_id = self.args.get('reference_price_id', None)
        self.charge_intervals_input_id = self.args.get('charge_intervals_input_id', None)
        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.85))
        self.sleep_over_soc = float(self.args.get('sleep_over_soc', 30.0))

        # EV Settings
        self.ev_logic_active_id = self.args.get('ev_logic_active_id', None)
        self.ev_target_soc_id = self.args.get('ev_target_soc_id', 'input_number.ev_target_soc')
        self.ev_grid_target_soc_id = self.args.get('ev_grid_target_soc_id', 'input_number.ev_grid_target_soc')
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
        self.ev_charge_plan_id = self.args.get('ev_charge_plan_id', 'input_text.ev_charge_plan')
        self.monday_deadline_time_id = self.args.get('monday_deadline_time_id', 'input_datetime.monday_ev_deadline')
        self.monday_min_soc_id = self.args.get('monday_min_soc_id', 'input_number.ev_montag_sicherheits_soc')
        self.ev_immediate_charge_price_id = self.args.get('ev_immediate_charge_price_id', None)

        # Priority
        self.home_battery_priority_soc = float(self.args.get('home_battery_priority_soc', 95.0))

        # Control States
        self.dashboard_status_text_id = self.args.get('dashboard_status_text_id', 'input_text.smart_price_charge_status')
        self.app_enabled_switch_id = self.args.get('app_enabled_switch_id', 'input_boolean.smart_price_charge_aktiv')
        self.cheap_hour_toggle_id = self.args.get('cheap_hour_toggle_id', 'input_boolean.smart_price_charge_active_slot')
        self.next_charge_time_id = self.args.get('next_charge_time_id', 'input_text.smart_price_next_charge')
        self.cheap_hours_text_id = self.args.get('cheap_hours_text_id', 'input_text.smart_price_slots')
        self.report_id = self.args.get('report_id', 'input_text.smart_price_report')

        # Stats IDs
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
        self.gemini_model = self.args.get('gemini_model', 'gemini-1.5-flash')
        self.gemini_api_key = self.args.get('gemini_api_key', None)
        self.ai_trigger_button_id = self.args.get('ai_trigger_button_id', None)
        self.ai_advice_text_id = self.args.get('ai_advice_text_id', None)

        self._lock = threading.RLock()
        self._state_cache = {}
        self._wb_last_app_cmd = None
        self._last_inv_cmd_time = None
        self._inv_retry_count = 0

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
        # Nach einem Neustart ist _wb_last_app_cmd leer. Stünde die Wallbox dann auf 'Ein' (2), würde das
        # ewig als manueller Override gelten (die App fasst sie nie wieder an). Daher aktuellen Zustand übernehmen.
        wb_now = str(self._safe_get_state(self.ev_wallbox_switch_id, default="")).strip().lower()
        if wb_now in ['on', '2', 'ein']:
            self._wb_last_app_cmd = '2'
        now = self.get_now()
        next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, next_min, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))
        self.run_daily(self.check_weekly_ai_trigger, time(18, 0, 0))
        self.listen_event(self.trigger_ai_analysis, "trigger_ai_analysis")
        if getattr(self, 'ai_trigger_button_id', None):
            self.listen_state(self.trigger_ai_analysis_button, self.ai_trigger_button_id)
        self.main_logic({})

    def _safe_get_state(self, entity_id, attribute=None, default=None):
        """Safe get_state wrapper that prevents self.get_state(None) calls."""
        if not entity_id or str(entity_id).lower() in ['none', 'null', '', 'unavailable', 'unknown']:
            return default
        try:
            val = self.get_state(entity_id, attribute=attribute) if attribute else self.get_state(entity_id)
            return default if val in ['unavailable', 'unknown', 'none', None] else val
        except Exception:
            return default

    def _get_float_state(self, entity_id, default=0.0):
        """Thread-safe float state access with caching and safe default fallback."""
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
        """Thread-safe state setting with immediate cache update."""
        if not entity_id:
            return
        val = round(value, decimals)
        with self._lock:
            try:
                self.set_state(entity_id, state=val)
                self._state_cache[f"float_{entity_id}"] = val
            except (ValueError, TypeError, KeyError):
                pass

    def _set_error_states(self, message_key):
        if getattr(self, 'dashboard_status_text_id', None):
            msg = self.T.get(message_key, message_key)
            self.set_state(self.dashboard_status_text_id, state=msg)

    def check_wallbox_disconnect(self, entity, attribute, old, new, kwargs):
        """Stecker-Reflex: Setzt Wallbox auf Eco, wenn abgesteckt."""
        app_enabled = (self._safe_get_state(self.app_enabled_switch_id, default='on') == 'on')
        if not app_enabled:
            return

        is_disconnected = False
        if entity == self.ev_plug_sensor_id and str(new).lower() in ['off', 'false', '0']:
            is_disconnected = True
        elif entity == self.ev_wallbox_status_id and str(new).lower() in ['1', '0', 'off', 'false', 'idle']:
            is_disconnected = True

        if is_disconnected:
            if self.log_debug_level:
                self.log("Stecker-Reflex: Auto abgesteckt -> Setze Wallbox sofort auf Eco.", level="INFO")
            self._set_wallbox_logic_mode("Eco")
            self._set_wallbox_state("1")
            if getattr(self, 'ev_boost_switch_id', None) and self._safe_get_state(self.ev_boost_switch_id) == 'on':
                self.turn_off(self.ev_boost_switch_id)

    def _set_wallbox_logic_mode(self, mode: str):
        with self._lock:
            eid = getattr(self, 'ev_logic_mode_id', None)
            if not eid:
                return
            target_val = "4" if mode.lower() == "eco" else "3"
            current = str(self._safe_get_state(eid, default=""))
            if current != target_val:
                try:
                    self.call_service("select/select_option", entity_id=eid, option=target_val)
                except Exception as e:
                    if self.log_debug_level:
                        self.log(f"Wallbox LMO Switch Fehler: {e}", level="ERROR")

    def _set_wallbox_state(self, state_option: str):
        """
        Sendet den Status an die Wallbox.
        Erwartet "0" (Neutral), "1" (Off), "2" (On) fuer Select-Entities.
        """
        with self._lock:
            eid = getattr(self, 'ev_wallbox_switch_id', None)
            if not eid:
                return
            domain = eid.split('.')[0]

            if domain == 'select':
                opt_lower = state_option.lower()
                target = "0"
                if opt_lower in ['off', 'aus', '1']:
                    target = "1"
                elif opt_lower in ['on', 'ein', '2']:
                    target = "2"

                raw_current = str(self._safe_get_state(eid, default="")).strip().lower()
                if raw_current in ['off', 'aus', '1', 'stop', 'disabled', 'ausgeschaltet']:
                    current_norm = "1"
                elif raw_current in ['on', 'ein', '2', 'charging', 'enabled', 'eingeschaltet']:
                    current_norm = "2"
                else:
                    current_norm = "0"

                self._wb_last_app_cmd = target

                if current_norm != target:
                    if target in ['0', '2'] and current_norm == '1':
                        if self.log_debug_level:
                            self.log("ID.4 WAKE-UP: Triggere Signalunterbrechung via Neutral (0)...", level="INFO")
                        self.call_service("select/select_option", entity_id=eid, option="0")
                        self.run_in(self._deferred_wb_select, 3, option=target)
                    else:
                        self.call_service("select/select_option", entity_id=eid, option=target)

    def _deferred_wb_select(self, kwargs):
        opt = kwargs.get('option', "0")
        eid = getattr(self, 'ev_wallbox_switch_id', None)
        if eid:
            self._wb_last_app_cmd = opt
            try:
                self.call_service("select/select_option", entity_id=eid, option=opt)
            except Exception as e:
                if self.log_debug_level:
                    self.log(f"Deferred WB Select Fehler: {e}", level="ERROR")

    # ==========================================================
    # ROBUSTE GOODWE-STEUERUNG (GESTAFFELT + AUTO-RELOAD)
    # ==========================================================
    def _set_inverter_mode(self, target_mode):
        with self._lock:
            if not self.inverter_mode_entity_id:
                return

            now = self.get_now()
            if self._last_inv_cmd_time is None:
                self._last_inv_cmd_time = now - timedelta(minutes=10)

            raw_ems = self.get_state(self.inverter_mode_entity_id)
            raw_op = self.get_state(self.inverter_operation_mode_entity_id) if self.inverter_operation_mode_entity_id else "ok"

            # 1. Prüfen, ob die GoodWe-Integration komplett "unavailable" ist
            if raw_ems in ['unavailable', 'unknown', None] or raw_op in ['unavailable', 'unknown', None]:
                if (now - self._last_inv_cmd_time).total_seconds() >= 60:
                    self.log("WARNUNG: GoodWe Entität ist 'unavailable' -> Lade GoodWe-Integration automatisch neu!", level="WARNING")
                    try:
                        self.call_service("homeassistant/reload_config_entry", entity_id=self.inverter_mode_entity_id)
                    except Exception as e:
                        self.log(f"Reload Fehler: {e}", level="ERROR")
                    self._last_inv_cmd_time = now
                return

            current_mode = str(raw_ems).strip()
            target_op = self.inverter_op_mode_general
            if target_mode == self.mode_charge:
                target_op = self.inverter_op_mode_charge
            elif target_mode == self.mode_backup and self.inverter_op_mode_backup:
                target_op = self.inverter_op_mode_backup
            current_op = str(raw_op).strip() if self.inverter_operation_mode_entity_id else target_op

            # 2. Prüfen, ob UI-Status abweicht
            mode_mismatch = (current_mode != target_mode) or (self.inverter_operation_mode_entity_id and current_op != target_op)

            # 3. ECHTER HARDWARE-CHECK: Macht der Wechselrichter physisch das, was die Integration anzeigt?
            # (GoodWe: negativ = Akku lädt, positiv = Akku entlädt)
            cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id, default=0.0)
            cur_soc = self._get_float_state(self.current_soc_sensor_id, default=50.0)
            target_soc = self._get_float_state(self.target_soc_id, default=100.0)
            secs_since_last_cmd = (now - self._last_inv_cmd_time).total_seconds()

            hardware_stuck = False
            if not mode_mismatch and secs_since_last_cmd >= 120:
                # Fall A: Soll aus dem Netz laden, ist noch unter Ziel-SoC, aber Ladeleistung ist < 100W
                if target_mode == self.mode_charge and cur_soc < (target_soc - 1.0) and cur_batt_pwr > -100.0:
                    hardware_stuck = True
                    self.log(f"WARNUNG: GoodWe zeigt '{current_mode}'/'{current_op}', lädt aber nicht (Batt: {cur_batt_pwr:.0f}W)!", level="WARNING")
                # Fall B: Soll im Standby/Backup halten, entlädt sich aber trotzdem mit > 150W ins Haus
                elif target_mode == self.mode_backup and cur_batt_pwr > 150.0:
                    hardware_stuck = True
                    self.log(f"WARNUNG: GoodWe zeigt '{current_mode}'/'{current_op}', entlädt aber trotzdem (Batt: {cur_batt_pwr:.0f}W)!", level="WARNING")

            if not mode_mismatch and not hardware_stuck:
                self._inv_retry_count = 0
                return

            # Nicht öfter als alle 45 Sekunden schalten, damit die gestaffelte Sequenz durchlaufen kann
            if secs_since_last_cmd < 45:
                return

            self._last_inv_cmd_time = now

            # Wenn die Hardware trotz richtiger Anzeige in HA klemmt: Integration neu laden + nach 15s neu schalten!
            if hardware_stuck:
                self._inv_retry_count += 1
                self.log(f"SELBSTHEILUNG (Versuch {self._inv_retry_count}): Lade GoodWe-Integration neu und sende '{target_mode}' in 15s erneut...", level="WARNING")
                try:
                    self.call_service("homeassistant/reload_config_entry", entity_id=self.inverter_mode_entity_id)
                except Exception as e:
                    self.log(f"Reload Fehler: {e}", level="ERROR")
                self.run_in(self._execute_staggered_goodwe_cmd, 15, target_mode=target_mode, target_op=target_op)
            else:
                self.log(f"ACTION: Schalte GoodWe gestaffelt auf OpMode='{target_op}' & EMS='{target_mode}' (Aktuell: Op='{current_op}', EMS='{current_mode}')", level="INFO")
                self._execute_staggered_goodwe_cmd({"target_mode": target_mode, "target_op": target_op})

    def _execute_staggered_goodwe_cmd(self, kwargs):
        """Sendet die Befehle mit je 2 Sekunden Abstand, damit der GoodWe UDP-Dongle kein Paket verschluckt."""
        target_mode = kwargs.get("target_mode")
        target_op = kwargs.get("target_op")

        # Schritt 1: Eco Mode Ziel-SoC setzen (wichtig vor dem Start von eco_charge)
        if self.inverter_max_soc_entity_id:
            target_soc_val = float(self._get_float_state(self.target_soc_id, default=100.0)) if target_mode == self.mode_charge else 100.0
            current_max_soc = self._get_float_state(self.inverter_max_soc_entity_id, default=100.0)
            if abs(current_max_soc - target_soc_val) > 0.5:
                try:
                    self.call_service("number/set_value", entity_id=self.inverter_max_soc_entity_id, value=target_soc_val)
                except Exception as e:
                    if self.log_debug_level:
                        self.log(f"Inverter Max SoC Fehler: {e}", level="ERROR")

        # Schritt 2: Nach 2 Sekunden zuerst die übergeordnete Wechselrichter-Betriebsart (Operation Mode) setzen
        if self.inverter_operation_mode_entity_id and target_op:
            self.run_in(self._delayed_op_mode_cmd, 2, target_op=target_op)

        # Schritt 3: Nach 4 Sekunden den EMS-Modus setzen
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
        """Parst Zeitstempel aus Tibber-Slot-Dict oder berechnet Index sicher."""
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
        hours = minutes_offset // 60
        mins = minutes_offset % 60
        extra_days = hours // 24
        hours = hours % 24
        return datetime.combine(base_date + timedelta(days=extra_days), time(hours, mins)).replace(tzinfo=tz)

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

    def _pv_window(self, now, deadline, is_daylight):
        """
        Liefert (stunden, anteil, nutzt_morgen) für das PV-Zeitfenster zwischen jetzt und Deadline:
        - stunden: Stunden mit PV-Erzeugung vor der Deadline
        - anteil: Anteil der (Rest-)Tagesproduktion, der vor der Deadline anfällt
        - nutzt_morgen: True, wenn das Fenster der morgige Tag ist (dann gilt die Morgen-Prognose)
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

    def _update_tracking_stats(self, cur_price, cur_pv, cur_batt_pwr, charge_pwr):
        ref_price = self._get_float_state(self.reference_price_id, default=0.35)
        if cur_batt_pwr < -100:
            charged_kwh = (abs(cur_batt_pwr) / 1000.0) * (1.0 / 60.0)
            if cur_pv >= abs(cur_batt_pwr):
                pv_save = charged_kwh * ref_price
                self._set_tracking_state(self.pv_savings_month_id, self._get_tracking_state(self.pv_savings_month_id) + pv_save)
                self._set_tracking_state(self.pv_savings_total_id, self._get_tracking_state(self.pv_savings_total_id) + pv_save)
            else:
                grid_part_kwh = ((abs(cur_batt_pwr) - max(0.0, cur_pv)) / 1000.0) * (1.0 / 60.0)
                cost = grid_part_kwh * cur_price
                saved = grid_part_kwh * max(0.0, ref_price - cur_price)
                if self.cost_month_id and str(self.cost_month_id).startswith('input_number'):
                    self._set_tracking_state(self.cost_month_id, self._get_tracking_state(self.cost_month_id) + cost)
                self._set_tracking_state(self.cost_total_id, self._get_tracking_state(self.cost_total_id) + cost)
                self._set_tracking_state(self.savings_month_id, self._get_tracking_state(self.savings_month_id) + saved)
                self._set_tracking_state(self.savings_total_id, self._get_tracking_state(self.savings_total_id) + saved)
                self._set_tracking_state(self.charged_kwh_month_id, self._get_tracking_state(self.charged_kwh_month_id) + grid_part_kwh, 4)
                self._set_tracking_state(self.charged_kwh_total_id, self._get_tracking_state(self.charged_kwh_total_id) + grid_part_kwh, 4)

        if cur_batt_pwr > 100:
            discharged_kwh = (cur_batt_pwr / 1000.0) * (1.0 / 60.0)
            discharge_saved = discharged_kwh * max(0.0, cur_price - (ref_price * (2.0 - self.efficiency_factor)))
            self._set_tracking_state(self.discharge_savings_month_id, self._get_tracking_state(self.discharge_savings_month_id) + discharge_saved)
            self._set_tracking_state(self.discharge_savings_total_id, self._get_tracking_state(self.discharge_savings_total_id) + discharge_saved)

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
            f"{self.T['REPORT_CHARGED_KWH']}: {self._get_tracking_state(self.charged_kwh_month_id):.2f} kWh"
        )
        try:
            self.set_state(self.report_id, state=report)
        except Exception as e:
            if self.log_debug_level:
                self.log(f"Report SetState Fehler: {e}", level="ERROR")

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

        # Basic Sensor Reads
        cur_soc = self._get_float_state(self.current_soc_sensor_id, default=50.0)
        cur_pv = self._get_float_state(self.current_pv_power_sensor_id, default=0.0)
        cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id, default=0.0)
        cur_grid = self._get_float_state(self.grid_power_import_export_sensor_id, default=0.0)
        cur_house = self._get_float_state(self.current_house_consumption_w_id, default=300.0)

        # DoD / Min SoC Calculation (Handles GoodWe 90% DoD cleanly)
        dod = self._get_float_state(self.min_soc_discharge_id, default=90.0)
        base_min_soc = (100.0 - dod) if dod > 50.0 else dod

        # ==========================================================
        # EV ZIEL- & PENDLER-LOGIK (EXAKTE TRENNUNG TÄGLICH VS MONTAG)
        # ==========================================================
        ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=50.0)
        ev_daily_grid_target = self._get_float_state(self.ev_target_soc_id, default=40.0)

        # Pendler Deadline Uhrzeit auslesen (Standard: 07:00 Uhr)
        dl_hour, dl_minute = 7, 0
        if self.monday_deadline_time_id:
            try:
                t_str = str(self._safe_get_state(self.monday_deadline_time_id, default=""))
                if t_str and t_str not in ['unavailable', 'unknown', 'none']:
                    parts = t_str.split(':')
                    dl_hour, dl_minute = int(parts[0]), int(parts[1])
            except Exception:
                pass

        # Montags-Sicherheits-SoC aus input_number.ev_montag_sicherheits_soc lesen
        mon_grid_target = self._get_float_state(self.monday_min_soc_id, default=80.0)
        monday_start_hour = int(self.args.get('monday_deadline_start_hour', 12))

        # Prüfen, ob wir im Montags-Pendler-Fenster sind (Sonntag ab Startzeit bis Montagmorgen Abfahrt)
        is_mon_sec = False
        if (now.weekday() == 6 and now.hour >= monday_start_hour) or (
            now.weekday() == 0 and (now.hour < dl_hour or (now.hour == dl_hour and now.minute <= dl_minute))
        ):
            is_mon_sec = True
            ev_grid_target = max(ev_daily_grid_target, mon_grid_target)
        else:
            ev_grid_target = ev_daily_grid_target

        # PV-Obergrenze ist immer mindestens 80% (oder höher, falls Netz-/Tagesziel höher steht)
        ev_max_pv_soc = max(80.0, ev_grid_target, ev_daily_grid_target)

        # Wallbox State Parsing
        wb_status = str(self._safe_get_state(self.ev_wallbox_status_id, default="")).strip().lower()
        wb_force = str(self._safe_get_state(self.ev_wallbox_switch_id, default="")).strip().lower()

        charging_states = {"charging", "laden", "2", "on", "true"}
        ev_active = (wb_status in charging_states)

        # Solve Self-Lockout: Only treat as manual override if state differs from app's last command
        is_manual_override = False
        if wb_force in ['on', '2', 'ein']:
            if self._wb_last_app_cmd != '2':
                is_manual_override = True

        # Forecast Reads
        fc_rem = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        fc_next = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        fc_now = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        fc_tmrw = self._get_float_state(self.pv_forecast_tomorrow_id, default=0.0)

        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=10.0)
        charge_pwr = self._get_float_state(self.charger_power_kw_id, default=3.0)
        target_soc = self._get_float_state(self.target_soc_id, default=100.0)
        pv_fc_thresh = self._get_float_state(self.pv_forecast_threshold_kw_id, default=1.5)
        cur_pv_thresh = self._get_float_state(self.current_pv_threshold_w_id, default=500.0)
        price_discharge_limit = self._get_float_state(self.price_discharge_threshold_id, default=0.32)
        user_intervals = int(self._get_float_state(self.charge_intervals_input_id, default=16))

        ev_cap = self.ev_battery_capacity_kwh
        ev_pwr = self.ev_charger_power_kw

        if self.log_debug_level:
            self.log(f"HAUS-SoC:{cur_soc:.1f}% | PV:{cur_pv:.0f}W | FC-Now:{fc_now:.2f} | FC-Morgen:{fc_tmrw:.1f}", level="INFO")
            self.log(f"EV-Schutz Check: WB-Status='{wb_status}', Switch='{wb_force}' -> WB Aktiv: {ev_active} | EV-SoC: {ev_current_soc}% (Ziel(Aktiv): {ev_grid_target}% | Täglich: {ev_daily_grid_target}%, Montag: {mon_grid_target}%, MonAktiv: {is_mon_sec}, PV-Max: {ev_max_pv_soc}%)", level="INFO")

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

        # NÄCHSTER relevanter Preisberg statt globalem Maximum über bis zu 2 Tage.
        # Nachmittags liegen die Morgen-Preise vor: ein höherer Morgen-Peak würde sonst die Deadline auf
        # morgen früh schieben und den heutigen Abend-Peak ungesichert lassen.
        peak_item = self._find_next_peak(all_prices, self.peak_swing_eur) or global_peak
        peak_time_slot = peak_item['time_dt']
        peak_price = peak_item['price']
        cur_spread = peak_price - cur_price

        # Die SoC-Staffelung des Mindestabstands soll verhindern, dass ein (fast) voller Akku die PV blockiert.
        # Das gilt nur, solange die PV wirklich produziert; danach (Abend) wird für den Peak gehalten.
        eff_spread = self.base_min_price_spread_eur
        if cur_pv > 300.0:
            if cur_soc > self.soc_threshold_high:
                eff_spread = max(eff_spread, self.spread_high_soc_eur)
            elif cur_soc > self.soc_threshold_medium:
                eff_spread = max(eff_spread, self.spread_medium_soc_eur)

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

        # Spread-Hold: Akku sparen, solange ein deutlich teurerer Peak kommt. Bewusst OHNE absolute
        # Entladeschwelle: liegen alle Tagespreise über der Schwelle (z.B. 0.44-0.62 bei Schwelle 0.30),
        # würde der Akku sonst nie gehalten und wäre vor dem Abend-Peak leergelaufen.
        should_hold = (cur_spread >= eff_spread) and (not interim_dip)

        effective_min_soc = base_min_soc
        if prices_tmrw and now.hour >= 18:
            morning_peak_price = 0.0
            for item in all_prices:
                if item['time_dt'].date() == (today_date + timedelta(days=1)) and 5 <= item['time_dt'].hour <= 9:
                    if item['price'] > morning_peak_price:
                        morning_peak_price = item['price']
            if (morning_peak_price - cur_price) > self.morning_min_diff:
                effective_min_soc = max(base_min_soc, self.sleep_over_soc)

        deadline = peak_time_slot if peak_price > price_discharge_limit else datetime.combine(today_date, time(23, 59)).replace(tzinfo=now.tzinfo)

        is_daylight = float(self._safe_get_state(self.sun_sensor_id, attribute='elevation', default=0)) > 0

        # --- ENERGIE-BILANZ bis zur Deadline (Peak) ---------------------------------------------
        # Im Hold bleibt die Batterieenergie bis zum Peak erhalten. Gutschreiben darf man nur den
        # PV-ÜBERSCHUSS (Prognose minus Hausverbrauch während der PV-Stunden), nicht die gesamte PV.
        pv_hours, pv_share, pv_uses_tomorrow = self._pv_window(now, deadline, is_daylight)
        pv_fc_kwh = fc_tmrw if pv_uses_tomorrow else fc_rem
        # Tageslast tagsüber ist meist deutlich niedriger als der 24h-Schnitt (Abend/Wärmepumpe/EV) -> Mix mit aktueller Last
        avg_24h_w = max(200.0, min(self.max_load_w, self._get_float_state(self.avg_consumption_sensor_id, default=500.0)))
        avg_load_w = max(200.0, 0.5 * avg_24h_w + 0.5 * min(self.max_load_w, cur_house))
        pv_surplus_kwh = 0.0
        if pv_hours > 0:
            pv_surplus_kwh = max(0.0, pv_fc_kwh * pv_share - (avg_load_w / 1000.0) * pv_hours) * self.pv_forecast_safety_factor

        need_soc_kwh = max(0.0, (target_soc - cur_soc) / 100 * batt_cap)
        needed_kwh = max(0.0, min(need_soc_kwh - pv_surplus_kwh, batt_cap))
        slots_uncapped = int(math.ceil((needed_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0
        final_slots = min(slots_uncapped, user_intervals)

        # Nur Slots, in denen sich Netzladen gegenüber dem Peak nach Wirkungsgrad noch lohnt
        max_buy_price = peak_price * self.efficiency_factor - self.min_cycle_profit_eur
        pool = [x for x in all_prices if start_slot <= x['time_dt'] < deadline and x['price'] <= max_buy_price]

        cheap_hours_info = "0x 15min (--:--) Ø 0.000 EUR"
        current_time_in_best_block = False
        best_slots = []
        if pool and final_slots > 0:
            tie = self.price_tie_eur
            best_slots = sorted(pool, key=lambda x: (round(x['price'] / tie) if tie > 0 else x['price'], x['time_dt']))[:final_slots]
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
                f"PLAN: Peak {peak_time_slot.strftime('%d.%m %H:%M')} @{peak_price:.3f} (Max 2 Tage {max_future_price:.3f}) | "
                f"Bedarf {need_soc_kwh:.1f}kWh - PV-Überschuss {pv_surplus_kwh:.1f}kWh (PV {pv_fc_kwh:.1f}kWh, {pv_hours:.1f}h, Last {avg_load_w:.0f}W) "
                f"= {needed_kwh:.1f}kWh -> {slots_uncapped} Slots (Limit {user_intervals}, Pool {len(pool)}, max. Kaufpreis {max_buy_price:.3f}) | "
                f"Hold={should_hold} (Spread {cur_spread:.3f}/{eff_spread:.2f}, Dip={interim_dip})",
                level="INFO")
        if slots_uncapped > user_intervals and (now.hour, now.date()) != getattr(self, '_last_cap_warn', None):
            self._last_cap_warn = (now.hour, now.date())
            self.log(f"WARNUNG: Ladeplan braucht {slots_uncapped} Slots, begrenzt durch 'charge_intervals' = {user_intervals} "
                     f"(Einheit: 15-Minuten-Slots, NICHT Stunden!) - Akku erreicht Ziel-SoC evtl. nicht rechtzeitig.", level="WARNING")

        # Panic: kurz vor dem Peak noch Bedarf -> jetzt laden, aber nur wenn es sich gegenüber dem Peak noch lohnt
        profit_ok_now = (peak_price * self.efficiency_factor - cur_price) >= self.min_cycle_profit_eur
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

        approaching_peak = peak_dt and (-30 < (peak_dt - now).total_seconds() / 60 < 90)

        # FIX: Sonne gilt nur als aktiv, wenn PV mindestens die Ladeschwelle (z.B. 500W) erreicht
        # oder mehr erzeugt als das Haus gerade verbraucht (verhindert das Leerlaufen bei 50-300W Herbst-Dämmerung!)
        is_sun_shining = (cur_pv >= cur_pv_thresh) or (cur_pv > (cur_house + 100))

        # ==========================================================
        # 🚗 EV PLANNING (Berechnet bis zum Grid-/Montags-Target)
        # ==========================================================
        ev_is_cheap_now = False
        ev_plan_text = self.T['STATUS_EV_PLAN_NONE']
        imm_price = self._get_float_state(self.ev_immediate_charge_price_id, default=float(self.args.get('ev_immediate_charge_price', 0.20)))

        if self.ev_logic_active_id and self._safe_get_state(self.ev_logic_active_id) == 'on':
            if ev_current_soc < ev_grid_target:
                if self._safe_get_state(self.ev_boost_switch_id) == 'on':
                    ev_is_cheap_now = True
                    ev_plan_text = self.T['STATUS_EV_PLAN_BOOST'].format(target=int(ev_grid_target))
                else:
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
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 1. WALLBOX DELEGATION
        # ==========================================================
        if not is_manual_override:
            if self._safe_get_state(self.ev_plug_sensor_id) == 'on':
                if ev_current_soc >= ev_max_pv_soc:
                    self._set_wallbox_logic_mode("Eco")
                    self._set_wallbox_state("1")
                    if getattr(self, 'ev_boost_switch_id', None) and self._safe_get_state(self.ev_boost_switch_id) == 'on':
                        self.turn_off(self.ev_boost_switch_id)

                elif ev_current_soc < ev_grid_target and (self._safe_get_state(self.ev_boost_switch_id) == 'on' or ev_is_cheap_now):
                    self._set_wallbox_logic_mode("Default")
                    self._set_wallbox_state("2")

                else:
                    if getattr(self, 'ev_boost_switch_id', None) and self._safe_get_state(self.ev_boost_switch_id) == 'on':
                        self.turn_off(self.ev_boost_switch_id)

                    priority_hysteresis = float(self.args.get('home_battery_priority_hysteresis', 5.0))
                    required_battery_soc = self.home_battery_priority_soc - priority_hysteresis if ev_active else self.home_battery_priority_soc

                    if ev_current_soc < ev_max_pv_soc and cur_soc >= required_battery_soc and is_daylight:
                        self._set_wallbox_logic_mode("Eco")
                        self._set_wallbox_state("0")
                    else:
                        self._set_wallbox_logic_mode("Eco")
                        self._set_wallbox_state("1")
            else:
                self._set_wallbox_logic_mode("Eco")
                self._set_wallbox_state("1")
                if getattr(self, 'ev_boost_switch_id', None) and self._safe_get_state(self.ev_boost_switch_id) == 'on':
                    self.turn_off(self.ev_boost_switch_id)

        # ==========================================================
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 2. HAUSAKKU
        # ==========================================================
        charge_toggle_on = False
        pv_saturates = (cur_pv - cur_house) >= 0.8 * charge_pwr * 1000.0
        # EV lädt gerade per Netz (App-Slot oder manuell erzwungen) -> Hausakku darf nicht ins Auto entladen
        ev_grid_slot = ev_active and (is_manual_override or self._wb_last_app_cmd == '2')

        # 1. EV-SCHUTZ (Wenn das Auto lädt und Hausakku < 50% -> Hausakku sofort im Standby schützen)
        if (ev_active or is_manual_override) and cur_soc < 50:
            self._set_inverter_mode(self.mode_backup)
            if self.dashboard_status_text_id:
                self.set_state(self.dashboard_status_text_id, state="EV aktiv: Hausakku Standby (Schutz <50%)")

        # 2. GEPLANTES NETZLADEN (Günstige berechnete Slots vor dem Peak, Panic-Mode oder unter Sofort-Ladepreis)
        # Gilt auch bei Sonne: Der Plan hat den PV-Überschuss bereits abgezogen. Nur wenn die PV allein den
        # Lader (fast) auslastet, wird kein Netzstrom gezogen. Im Modus 'charge_battery' wird PV ohnehin zuerst genutzt.
        elif cur_soc < target_soc and not pv_saturates and (panic_mode or current_time_in_best_block or cur_price <= imm_price):
            is_dip = (cur_spread >= self.base_min_price_spread_eur)
            allow = (current_time_in_best_block or panic_mode) if (current_time_in_best_block or panic_mode) else ((cur_price <= price_discharge_limit) or is_dip)

            if allow or cur_price <= imm_price:
                charge_toggle_on = True
                self._set_inverter_mode(self.mode_charge)
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_ACTIVE']}: {cur_price:.3f}€ / Slot aktiv")
            else:
                self._set_inverter_mode(self.mode_backup if should_hold else self.mode_general)
                if self.dashboard_status_text_id:
                    self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_BLOCKED']} ({cur_price:.3f} EUR).")

        # 3. ECHTER PV-ÜBERSCHUSS (PV >= Ladeschwelle oder PV > Hausverbrauch)
        elif is_sun_shining:
            if cur_soc < self.home_battery_priority_soc:
                if ev_grid_slot:
                    # Auto lädt aus dem Netz (günstiger Slot): sonst würde 'auto' den Hausakku ins Auto leeren
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state="EV lädt (Netz): Hausakku Standby")
                elif should_hold and cur_pv < (cur_house - 150.0):
                    # PV deckt das Haus nicht: im Modus 'auto' würde der Akku vor dem Peak entladen.
                    # Es gibt keinen PV-Überschuss, also geht durch Standby auch nichts verloren.
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id:
                        self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_WAIT_HOLD']} (PV {cur_pv:.0f}W < Haus {cur_house:.0f}W, Akku für Peak {peak_price:.2f}€)")
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

        # 4. AKKU SPAREN FÜR DEN PEAK (Spread-Hold: Verhindert das Leerlaufen von 60% auf 10% vor dem teuren Abend!)
        elif should_hold and cur_soc < target_soc:
            self._set_inverter_mode(self.mode_backup)
            if self.dashboard_status_text_id:
                self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_WAIT_HOLD']} ({cur_soc:.0f}% für Peak gehalten)")

        # 5. ENTLADEN INS HAUS FREIGEBEN (Wenn der teure Preis-Peak da ist oder kein Hold nötig ist)
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

        self._update_tracking_stats(cur_price, cur_pv, cur_batt_pwr, charge_pwr)

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

            total_saved = saved + discharge_saved + pv_saved

            self.log(f"KI-Analyse Live-Daten: Cost={cost:.2f}€ ({self.cost_month_id}), Saved={saved:.2f}€, DischSaved={discharge_saved:.2f}€, PV={pv_saved:.2f}€, kWh={kwh:.2f}", level="INFO")

            if round(cost, 2) <= 0.0 and round(total_saved, 2) <= 0.0 and round(kwh, 2) <= 0.0:
                if self.ai_advice_text_id:
                    self.set_state(self.ai_advice_text_id, state="Keine aktuellen Statistikdaten in Home Assistant gefunden.")
                return

            self.log(f"KI-Analyse Daten: Cost={cost:.2f}€, Saved={saved:.2f}€ (Laden:{saved:.2f}€, Entladen:{discharge_saved:.2f}€, PV:{pv_saved:.2f}€), kWh={kwh:.2f}", level="INFO")

            prompt = (
                f"Smart Home Energieberater: Netzkosten: {cost:.2f} EUR. "
                f"Gesamtersparnis: {total_saved:.2f} EUR (Laden: {saved:.2f} EUR, Entladen: {discharge_saved:.2f} EUR, PV-Direkt: {pv_saved:.2f} EUR). "
                f"Geladene Energie: {kwh:.2f} kWh. "
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