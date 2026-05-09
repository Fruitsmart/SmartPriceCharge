# -*- coding: utf-8 -*-
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta, time
import math

# ROLE: Senior Software Developer for Home Assistant & AppDaemon
# RULES: NO REFACTORING, NO CODE CUTTING, FULL 700+ LINES RETURNED.
# VERSION: 4.1 (Master-Sync Edition | PV-Aware EV Logic | Auto-Reset | Bugfixes)

# --- WETTER FAKTOREN (0.0 = Schlecht / 1.0 = Super) ---
WEATHER_PV_FACTOR = {
    'sunny': 1.0, 'clear-night': 0.0, 'partlycloudy': 0.8, 'cloudy': 0.5,
    'fog': 0.3, 'rainy': 0.1, 'pouring': 0.05, 'snowy': 0.4,
    'lightning': 0.1, 'hail': 0.1, 'windy': 0.5, 'exceptional': 0.0
}

# --- ÜBERSETZUNGSTABELLE (i18n) ---
TRANSLATIONS = {
    'DE': {
        'APP_VERSION': 'Version 4.1 (Wife-Approved | PV-Aware EV | Auto-Reset | Bugfix)',
        'ACTION_MODE_CHANGE': 'Modus-Änderung nötig',
        'ACTION_HEARTBEAT': 'Safety Heartbeat',
        'ERROR_NO_PRICE_DATA': 'FEHLER: Keine Preisdaten',
        'ERROR_NO_INTERVALS': 'FEHLER: Keine Preisintervalle',
        'STATUS_DISCHARGE_BASE': 'Entladen (Eigenverbrauch)',
        'STATUS_DISCHARGE_DIP': 'Entladen (Dip-Refill)',
        'STATUS_DISCHARGE_RESERVE_REACHED': 'Reserve erreicht',
        'STATUS_CHARGE_ACTIVE': 'Laden aktiv',
        'STATUS_CHARGE_BLOCKED': 'Blockiert: Preis zu hoch',
        'STATUS_PV_CHARGING': 'PV-Ladung aktiv',
        'STATUS_WAIT_HOLD': 'Warten (Spread-Hold)',
        'STATUS_WAIT_PV': 'Warten (PV/Peak erwartet)',
        'STATUS_IDLE': 'Standardbetrieb',
        'STATUS_TARGET_REACHED': 'Ziel-SoC erreicht',
        'INFO_SLOTS_NONE': 'Keine Slots gefunden.',
        'INFO_SESSION_START': 'Neue Lade-Session gestartet.',
        'INFO_SESSION_END': 'Lade-Session beendet.',
        'INFO_DISCHARGE_START': 'Smart Discharge aktiv.',
        'INFO_DISCHARGE_END': 'Smart Discharge beendet.',
        'INFO_APP_TERMINATED': 'App beendet.',
        'REPORT_GRID_COST': 'Kosten (Netz)',
        'REPORT_CHARGE_SAVE': 'Ersparnis (Laden)',
        'REPORT_DISCHARGE_VALUE': 'Wert Entladung',
        'REPORT_PV_VALUE': 'Wert PV-Direkt',
        'REPORT_CHARGED_KWH': 'Geladen',
        'STATUS_EV_CHEAP': 'Auto lädt (Billigstrom/Manuell)',
        'STATUS_EV_PV': 'Auto lädt (go-e PV-Überschuss)'
    },
    'EN': {
        'APP_VERSION': 'Version 4.1 (Wife-Approved | PV-Aware EV | Auto-Reset | Bugfix)',
        'ACTION_MODE_CHANGE': 'Mode change required',
        'ACTION_HEARTBEAT': 'Safety Heartbeat',
        'ERROR_NO_PRICE_DATA': 'ERROR: No Price Data',
        'ERROR_NO_INTERVALS': 'ERROR: No Price Intervals',
        'STATUS_DISCHARGE_BASE': 'Discharging',
        'STATUS_DISCHARGE_DIP': 'Discharging (Dip-Refill)',
        'STATUS_DISCHARGE_RESERVE_REACHED': 'Reserve reached',
        'STATUS_CHARGE_ACTIVE': 'Charging active',
        'STATUS_CHARGE_BLOCKED': 'Blocked: Price high',
        'STATUS_PV_CHARGING': 'PV charging active',
        'STATUS_WAIT_HOLD': 'Waiting (Spread-Hold)',
        'STATUS_WAIT_PV': 'Waiting (PV/Peak expected)',
        'STATUS_IDLE': 'Standard Idle',
        'STATUS_TARGET_REACHED': 'Target SoC reached',
        'INFO_SLOTS_NONE': 'No slots found.',
        'INFO_SESSION_START': 'New Charging Session.',
        'INFO_SESSION_END': 'Charging Session ended.',
        'INFO_DISCHARGE_START': 'Smart Discharge active.',
        'INFO_DISCHARGE_END': 'Smart Discharge ended.',
        'INFO_APP_TERMINATED': 'App terminated.',
        'REPORT_GRID_COST': 'Grid Cost',
        'REPORT_CHARGE_SAVE': 'Charge Savings',
        'REPORT_DISCHARGE_VALUE': 'Discharge Value',
        'REPORT_PV_VALUE': 'PV Direct Value',
        'REPORT_CHARGED_KWH': 'Charged'
    }
}

class SmartPriceCharge(hass.Hass):

    def initialize(self):
        lang_code = self.args.get('language', 'DE').upper()
        if lang_code not in TRANSLATIONS: lang_code = 'DE'
        self.T = TRANSLATIONS[lang_code]
        self.log(f"Initializing {self.T['APP_VERSION']}...", level="INFO")

        # IDs
        self.price_sensor_id = self.args['price_sensor_id']
        self.current_soc_sensor_id = self.args['current_soc_sensor_id']
        self.inverter_mode_entity_id = self.args['inverter_mode_entity_id']
        self.inverter_max_soc_entity_id = self.args.get('inverter_max_soc_entity_id', None)
        
        # PV & Power & Wetter
        self.pv_forecast_next_hour_id = self.args['pv_forecast_sensor_id'] 
        self.pv_forecast_current_hour_id = self.args['pv_forecast_current_hour_sensor_id']
        self.pv_forecast_today_remaining_id = self.args['pv_forecast_today_remaining_sensor_id']
        self.pv_forecast_tomorrow_id = self.args.get('pv_forecast_tomorrow_sensor_id', None)
        
        self.pv_peak_time_sensor_id = self.args.get('pv_peak_time_sensor_id', None)
        self.current_pv_power_sensor_id = self.args['current_pv_power_sensor_id']
        self.battery_power_sensor_id = self.args['battery_power_sensor_id']
        self.grid_power_import_export_sensor_id = self.args['grid_power_import_export_sensor_id']
        self.current_house_consumption_w_id = self.args.get('current_house_consumption_w_id', None)
        self.avg_consumption_sensor_id = self.args.get('avg_consumption_sensor_id', None)
        
        # Umwelt-Sensoren
        self.sun_sensor_id = self.args.get('sun_sensor_id', 'sun.sun')
        self.weather_sensor_id = self.args.get('weather_sensor_id', None)
        self.cloud_coverage_sensor_id = self.args.get('cloud_coverage_sensor_id', None)

        # Helfer & Settings
        self.battery_capacity_kwh_id = self.args['battery_capacity_kwh_id']
        self.charger_power_kw_id = self.args['charger_power_kw_id']
        self.target_soc_id = self.args['target_soc_id']
        self.pv_forecast_threshold_kw_id = self.args['pv_forecast_threshold_kw_id']
        self.current_pv_threshold_w_id = self.args['current_pv_threshold_w_id']
        self.price_discharge_threshold_id = self.args['price_discharge_threshold_id']
        self.min_soc_discharge_id = self.args['min_soc_discharge_id']
        self.reference_price_id = self.args['reference_price_id']
        self.charge_intervals_input_id = self.args.get('charge_intervals_input_id', 'input_number.anzahl_guenstigste_ladestunden')

        # --- EV / WALLBOX SETUP ---
        self.ev_logic_active_id = self.args.get('ev_logic_active_id')
        self.ev_target_soc_id = self.args.get('ev_target_soc_id')
        self.ev_wallbox_switch_id = self.args.get('ev_wallbox_switch_id')
        self.ev_soc_sensor_id = self.args.get('ev_soc_sensor_id')
        self.ev_wallbox_amps_id = self.args.get('ev_wallbox_amps_id')
        self.ev_car_charging_switch_id = self.args.get('ev_car_charging_switch_id', 'switch.id4_charging')
        # FIX #6: ev_car_target_soc_entity_id aus YAML lesen statt hartcodiert
        self.ev_car_target_soc_entity_id = self.args.get('ev_car_target_soc_entity_id', 'number.id4_battery_target_charge_level')
        
        # Wallbox PV-Schalter und Hausakku-Schwelle
        self.ev_pv_surplus_switch_id = self.args.get('ev_pv_surplus_switch_id', 'switch.goe_315255_fup')
        self.home_battery_priority_soc = float(self.args.get('home_battery_priority_soc', 95.0))

        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.50))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.efficiency_factor = float(self.args.get('battery_efficiency_factor', 0.90))

        # Dynamic Spread & Sleep-Over
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.08))
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 80.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 95.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        self.sleep_over_soc = float(self.args.get('sleep_over_soc', 30.0))
        self.morning_min_diff = float(self.args.get('morning_min_diff', 0.10))

        # Modi (Angepasst für GoodWe EMS Modus)
        self.mode_charge = self.args.get('inverter_mode_charge', 'charge_battery')
        self.mode_general = self.args.get('inverter_mode_general', 'auto')
        self.mode_backup = self.args.get('inverter_mode_backup', 'auto')

        # Status Tracking
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

        self.debug_mode = self.args.get('debug_mode', False)
        self.log_debug_level = self.args.get('log_debug_level', False)

        self.charging_session_active = False
        self.charging_session_start_time = None
        self.charging_session_net_charged_kwh = 0.0
        self.discharging_active = False
        self.last_inverter_mode_command_time = None
        
        self.sync_handle = None
        
        if not all([self.price_sensor_id, self.current_soc_sensor_id, self.inverter_mode_entity_id]):
            self.log("ERROR: Essential IDs missing!", level="ERROR")
            return
        
        # --- Reflex-Wächter für den Absteck-Vorgang ---
        self.ev_wallbox_status_id = self.args.get('ev_wallbox_status_id', 'sensor.goe_315255_status')
        self.listen_state(self.check_wallbox_disconnect, self.ev_wallbox_status_id)

        # --- UPGRADE: Master-Sync Trigger ---
        # 1. Wenn der Slider bewegt wird
        self.listen_state(self.on_ev_target_soc_slider_change, self.ev_target_soc_id)
        # 2. Wenn der Ladevorgang am Auto startet
        self.listen_state(self.on_ev_charge_start_sync, self.ev_car_charging_switch_id, new="on")
        
        # STARTUP DELAY
        delay = int(self.args.get('startup_delay_seconds', 120))
        self.log(f"Warte {delay} Sekunden bis zum Start der Logik...", level="INFO")
        self.run_in(self.start_app_routine, delay)

    def start_app_routine(self, kwargs):
        self.log("System stabilisiert. Starte Hauptlogik.", level="INFO")
        now = self.datetime()
        next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, next_min, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))
        
        self.run_daily(self.check_weekly_ai_trigger, time(20, 0, 0))
        self.listen_state(self.trigger_ai_analysis, "input_button.start_ki_analyse")
 
        self.main_logic({})

    # --- UPGRADE: Master-Sync Methoden (API Schonung) ---
    def on_ev_target_soc_slider_change(self, entity, attribute, old, new, kwargs):
        if self.sync_handle:
            self.cancel_timer(self.sync_handle)
        self.sync_handle = self.run_in(self.sync_ev_soc_to_car_debounced, 3, value=new)

    def sync_ev_soc_to_car_debounced(self, kwargs):
        try:
            slider_val = int(float(kwargs.get('value', 80)))
            
            # API SCHONUNG: Auto regelt 80% nativ. Wir funken nur rein, wenn über 80% geladen werden soll!
            target_val_for_car = max(80, slider_val)
            car_target = int(self._get_float_state(self.ev_car_target_soc_entity_id, default=80.0))
            
            if car_target != target_val_for_car:
                self.log(f"MASTER-SYNC: Setze Auto-Ladellimit auf {target_val_for_car}% (Slider ist bei {slider_val}%)", level="INFO")
                self.call_service("number/set_value", 
                                  entity_id=self.ev_car_target_soc_entity_id,
                                  value=target_val_for_car)
        except: pass

    def on_ev_charge_start_sync(self, entity, attribute, old, new, kwargs):
        slider_val = self._get_float_state(self.ev_target_soc_id, 80.0)
        self.sync_ev_soc_to_car_debounced({'value': slider_val})

    # --- KI-MODUL STUBS (Verhindert AttributeError) ---
    def check_weekly_ai_trigger(self, kwargs):
        if self.date().weekday() == 6:
            self.trigger_ai_analysis(None, None, None, None, None)

    def trigger_ai_analysis(self, entity, attribute, old, new, kwargs):
        self.log("KI-Analyse: Starte Daten-Sammlung...", level="INFO")
        self.run_in(self._perform_gemini_analysis, 2)

    def _perform_gemini_analysis(self, kwargs):
        self.log("KI-Analyse: Analyse-Prozess abgeschlossen.", level="INFO")

    def _log_debug(self, message, level="INFO"):
        if level == "DEBUG":
            if self.log_debug_level: self.log(message, level="INFO")
            else: self.log(message, level="DEBUG")
        elif level == "INFO": self.log(message, level="INFO")
        elif level in ["WARNING", "ERROR"]: self.log(message, level=level)

    def _get_float_state(self, entity_id, default=0.0):
        if entity_id is None: 
            return default
        try:
            state = self.get_state(entity_id)
            if state in ['unavailable', 'unknown', 'none', 'NH', 'None', None]: 
                return 0.0
            return float(state)
        except Exception: 
            pass
        return default
    
    def _get_tracking_state(self, entity_id): return self._get_float_state(entity_id, default=0.0)
    
    def _set_tracking_state(self, entity_id, value, decimals=6):
        if entity_id:
            try: self.set_state(entity_id, state=round(value, decimals))
            except: pass

    def _set_error_states(self, message_key):
        if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=self.T[message_key])
        if self.cheap_hour_toggle_id: self.turn_off(self.cheap_hour_toggle_id)

    # -----------------------------------------------------------
    #  GENTLEMAN-STOPP (Der VW-Diven Bändiger)
    # -----------------------------------------------------------
    def gentleman_stop(self, reason=""):
        needs_stop = False
        
        if self.ev_wallbox_switch_id and self.get_state(self.ev_wallbox_switch_id) == 'on':
            needs_stop = True
        if self.ev_pv_surplus_switch_id and self.get_state(self.ev_pv_surplus_switch_id) == 'on':
            needs_stop = True
            
        if needs_stop:
            self.log(f"Starte Gentleman-Stopp ({reason})...", level="INFO")
            
            if self.ev_car_charging_switch_id and self.get_state(self.ev_car_charging_switch_id) == 'on':
                self.turn_off(self.ev_car_charging_switch_id)
                self.log("-> Auto angewiesen, Ladevorgang zu beenden.", level="INFO")
                
            self.run_in(self._hard_stop_wallbox, 60)

    def _hard_stop_wallbox(self, kwargs):
        if self.ev_wallbox_switch_id and self.get_state(self.ev_wallbox_switch_id) == 'on':
            self.turn_off(self.ev_wallbox_switch_id)
        if self.ev_pv_surplus_switch_id and self.get_state(self.ev_pv_surplus_switch_id) == 'on':
            self.turn_off(self.ev_pv_surplus_switch_id)
        self.log("-> Gentleman-Stopp abgeschlossen: Wallbox sicher verriegelt.", level="INFO")

    # --- SET_INVERTER_MODE ---
    def _set_inverter_mode(self, target_mode):
        current_mode = self.get_state(self.inverter_mode_entity_id)
        now = self.get_now()
        needs_heartbeat = False
        
        if self.last_inverter_mode_command_time:
            diff = (now - self.last_inverter_mode_command_time).total_seconds() / 60
            if diff > 15: needs_heartbeat = True
        else:
            needs_heartbeat = True
        
        should_send = False
        reason = ""
        
        if current_mode != target_mode:
            should_send = True
            reason = self.T['ACTION_MODE_CHANGE']
        elif needs_heartbeat:
            should_send = True
            reason = self.T['ACTION_HEARTBEAT']
            
        if should_send:
            if not self.debug_mode:
                if target_mode == self.mode_charge and self.inverter_max_soc_entity_id:
                    calculated_target_soc = self._get_float_state(self.target_soc_id, default=100.0)
                    self.log(f"Schreibe Ladeziel {calculated_target_soc}% in {self.inverter_max_soc_entity_id}.", level="INFO")
                    try:
                        self.call_service("number/set_value", entity_id=self.inverter_max_soc_entity_id, value=str(int(calculated_target_soc)))
                    except Exception as e:
                        self.log(f"Fehler beim Setzen des Ladeziels: {e}", level="ERROR")

                self.log(f"ACTION: Set Mode '{target_mode}' ({reason}).", level="INFO")
                self.call_service("select/select_option", entity_id=self.inverter_mode_entity_id, option=target_mode)
            else:
                self.log(f"DEBUG-MODE: Would set '{target_mode}' ({reason}).", level="INFO")
                
            self.last_inverter_mode_command_time = now
        else:
            self._log_debug(f"Inverter Mode '{target_mode}' OK.", level="DEBUG")

    # Tracking Helpers
    def _update_charge_cost_stats(self, net_charged_kwh, avg_charge_price):
        if net_charged_kwh <= 0: return
        ref_price = self._get_float_state(self.reference_price_id, default=0.35)
        cost = net_charged_kwh * avg_charge_price
        saving = net_charged_kwh * (ref_price - avg_charge_price)
        c_k = self._get_tracking_state(self.cost_month_id)
        c_e = self._get_tracking_state(self.savings_month_id)
        c_kg = self._get_tracking_state(self.cost_total_id)
        c_eg = self._get_tracking_state(self.savings_total_id)
        c_km = self._get_tracking_state(self.charged_kwh_month_id)
        c_kg_kwh = self._get_tracking_state(self.charged_kwh_total_id)
        self._set_tracking_state(self.cost_month_id, c_k + cost)
        self._set_tracking_state(self.savings_month_id, c_e + saving)
        self._set_tracking_state(self.cost_total_id, c_kg + cost)
        self._set_tracking_state(self.savings_total_id, c_eg + saving)
        self._set_tracking_state(self.charged_kwh_month_id, c_km + net_charged_kwh, 4)
        self._set_tracking_state(self.charged_kwh_total_id, c_kg_kwh + net_charged_kwh, 4)
        self._update_monthly_report()

    def _update_discharge_saving_stats(self, discharged_kwh_dc, current_price):
        if discharged_kwh_dc <= 0: return
        discharged_kwh_ac = discharged_kwh_dc * self.efficiency_factor
        saving = discharged_kwh_ac * current_price
        c_dis_m = self._get_tracking_state(self.discharge_savings_month_id)
        c_dis_g = self._get_tracking_state(self.discharge_savings_total_id)
        self._set_tracking_state(self.discharge_savings_month_id, c_dis_m + saving)
        self._set_tracking_state(self.discharge_savings_total_id, c_dis_g + saving)
        self._update_monthly_report()

    def _update_pv_direct_stats(self, direct_pv_kwh, current_price):
        if direct_pv_kwh <= 0: return
        saving = direct_pv_kwh * current_price
        c_pv_m = self._get_tracking_state(self.pv_savings_month_id)
        c_pv_g = self._get_tracking_state(self.pv_savings_total_id)
        self._set_tracking_state(self.pv_savings_month_id, c_pv_m + saving)
        self._set_tracking_state(self.pv_savings_total_id, c_pv_g + saving)

    def reset_monthly_stats_daily_check(self, kwargs):
        now = self.datetime()
        if not self.report_id: return
        try: last_reset_str = self.get_state(self.report_id, attribute='last_reset_date')
        except: last_reset_str = None
        should_reset = True
        if last_reset_str:
            try:
                last_reset_date = datetime.strptime(last_reset_str, '%Y-%m-%d').date()
                if last_reset_date.month == now.month and last_reset_date.year == now.year: should_reset = False
            except: pass
        if should_reset:
            for eid in [self.pv_savings_month_id, self.cost_month_id, self.savings_month_id, self.discharge_savings_month_id]:
                self._set_tracking_state(eid, 0.0)
            self._set_tracking_state(self.charged_kwh_month_id, 0.0, 4)
            try:
                attr = self.get_state(self.report_id, attribute='all')['attributes']
                attr['last_reset_date'] = now.strftime('%Y-%m-%d')
                self.set_state(self.report_id, state=self.get_state(self.report_id), attributes=attr)
            except: pass
            self.log("INFO: Monthly stats reset.", level="INFO")
        self._update_monthly_report()

    def _update_monthly_report(self):
        if not self.report_id: return
        try:
            c_cost = self._get_tracking_state(self.cost_month_id)
            c_save = self._get_tracking_state(self.savings_month_id)
            c_dis = self._get_tracking_state(self.discharge_savings_month_id)
            c_kwh = self._get_tracking_state(self.charged_kwh_month_id)
            c_pv = self._get_tracking_state(self.pv_savings_month_id)
            
            report_name = self.datetime().strftime('%B %Y')
            report_text = f"Month ({report_name}):\n{self.T['REPORT_GRID_COST']}: {c_cost:.2f} EUR\n{self.T['REPORT_CHARGE_SAVE']}: {c_save:.2f} EUR\n{self.T['REPORT_DISCHARGE_VALUE']}: {c_dis:.2f} EUR\n{self.T['REPORT_PV_VALUE']}: {c_pv:.2f} EUR\n{self.T['REPORT_CHARGED_KWH']}: {c_kwh:.2f} kWh"
            try: attr = self.get_state(self.report_id, attribute='all')['attributes']
            except: attr = {'icon': 'mdi:file-chart'}
            self.set_state(self.report_id, state=report_text, attributes=attr)
        except: pass

    # --- HAUPTLOGIK ---
    def main_logic(self, kwargs):
        cheap_slots_found = []
        avg_price_slots = 0.0
        is_pv_charge_active = False
        charge_toggle_on = False
        is_discharge_active = False
        current_time_in_best_block = False
        cheap_hours_info = self.T['INFO_SLOTS_NONE']
        
        app_is_enabled = self.get_state(self.app_enabled_switch_id) == 'on'
        current_mode = self.get_state(self.inverter_mode_entity_id)
        now_dt = self.get_now().replace(second=0, microsecond=0, tzinfo=None)
        now_aware = self.get_now()
        
        # --- BASIS-WERTE ---
        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=5.0) 
        charge_pwr = self._get_float_state(self.charger_power_kw_id, default=3.0) 
        target_soc = self._get_float_state(self.target_soc_id, default=100.0)
        pv_fc_thresh = self._get_float_state(self.pv_forecast_threshold_kw_id, default=1.0)
        cur_pv_thresh = self._get_float_state(self.current_pv_threshold_w_id, default=500.0)
        price_discharge_limit = self._get_float_state(self.price_discharge_threshold_id, default=0.30)
        
        # --- EV BASIS-WERTE (DYNAMISCH) ---
        ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=0.0)
        ev_capacity = float(self.args.get('ev_battery_capacity_kwh', 77.0))
        ev_charge_pwr = float(self.args.get('ev_charge_power_kw', 11.0))

        dod = self._get_float_state(self.min_soc_discharge_id, default=20.0)
        base_min_soc = 100.0 - dod 
        
        user_intervals = int(self._get_float_state(self.charge_intervals_input_id, default=16.0))
        
        cur_soc = self._get_float_state(self.current_soc_sensor_id)
        cur_pv = self._get_float_state(self.current_pv_power_sensor_id)
        cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id)
        cur_grid = self._get_float_state(self.grid_power_import_export_sensor_id)
        cur_house = self._get_float_state(self.current_house_consumption_w_id)
        
        # Forecasts
        fc_rem = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        fc_next = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        fc_now = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        fc_tmrw = self._get_float_state(self.pv_forecast_tomorrow_id, default=0.0)
        
        # --- SOMMER-BREMSE ---
        if fc_tmrw >= 10.0:
            survival_target = self.sleep_over_soc
            if target_soc > survival_target:
                self._log_debug(f"Sommer-Bremse! PV Morgen: {fc_tmrw}kWh. Reduziere Hausakku-Netzladeziel von {target_soc}% auf {survival_target}%.", level="INFO")
                target_soc = survival_target
        
        peak_dt = None
        if self.pv_peak_time_sensor_id:
            s = self.get_state(self.pv_peak_time_sensor_id)
            if s and s not in ['unavailable', 'unknown']:
                try: peak_dt = datetime.fromisoformat(s)
                except: pass
        
        self._log_debug(f"SoC:{cur_soc:.1f}% | PV:{cur_pv:.0f}W | FC-Now:{fc_now:.2f} | FC-Morgen:{fc_tmrw:.1f}", level="DEBUG")

        # Prices
        prices_today = self.get_state(self.price_sensor_id, attribute='today')
        prices_tmrw = self.get_state(self.price_sensor_id, attribute='tomorrow')

        if prices_today is None:
            self._set_error_states('ERROR_NO_PRICE_DATA')
            return
        
        all_prices = []
        start_slot = now_dt - timedelta(minutes=now_dt.minute % 15)
        today_date = now_dt.date()
        
        for i, p in enumerate(prices_today):
            if isinstance(p, dict) and 'total' in p:
                price_dt = datetime.combine(today_date, time(i // 4, (i % 4) * 15))
                if price_dt >= start_slot: all_prices.append({'price': float(p['total']), 'time_dt': price_dt})

        if prices_tmrw:
            tmrw_date = (now_dt + timedelta(days=1)).date()
            for i, p in enumerate(prices_tmrw):
                if isinstance(p, dict) and 'total' in p:
                    price_dt = datetime.combine(tmrw_date, time(i // 4, (i % 4) * 15))
                    all_prices.append({'price': float(p['total']), 'time_dt': price_dt})

        if not all_prices:
             self._set_error_states('ERROR_NO_INTERVALS')
             return
        
        # Analysis
        max_future_price = 0.0
        peak_time_slot = None
        if all_prices:
             max_item = max(all_prices, key=lambda x: x['price'])
             max_future_price = max_item['price']
             peak_time_slot = max_item['time_dt']
        
        cur_price = all_prices[0]['price'] if all_prices else 0.0
        cur_spread = max_future_price - cur_price
        
        # Dynamic Spread
        eff_spread = self.base_min_price_spread_eur
        if cur_soc > self.soc_threshold_high: eff_spread = max(eff_spread, self.spread_high_soc_eur)
        elif cur_soc > self.soc_threshold_medium: eff_spread = max(eff_spread, self.spread_medium_soc_eur)
        
        min_interim = 9.99
        interim_dip = False
        if peak_time_slot and peak_time_slot > now_dt:
             for item in all_prices:
                 if item['time_dt'] > now_dt and item['time_dt'] < peak_time_slot:
                     if item['price'] < min_interim: min_interim = item['price']
             refill_profit = cur_price - (min_interim / self.efficiency_factor)
             if refill_profit > self.min_cycle_profit_eur: interim_dip = True

        should_hold = (cur_spread >= eff_spread) and (not interim_dip)

        # Sleep-Over Logic
        effective_min_soc = base_min_soc
        if prices_tmrw and now_dt.hour >= 18:
            tmrw_date = (now_dt + timedelta(days=1)).date()
            morning_peak_price = 0.0
            for item in all_prices:
                if item['time_dt'].date() == tmrw_date and 5 <= item['time_dt'].hour <= 9:
                    if item['price'] > morning_peak_price: morning_peak_price = item['price']
            
            price_diff = morning_peak_price - cur_price
            
            if price_diff > self.morning_min_diff:
                effective_min_soc = max(base_min_soc, self.sleep_over_soc)
                self._log_debug(f"Sleep-Over Active! MinSoC -> {effective_min_soc}% (FC-Morgen: {fc_tmrw} kWh)", level="DEBUG")

        # Demand Calc
        deadline = peak_time_slot if max_future_price > price_discharge_limit else datetime.combine(today_date, time(23, 59))
        is_morning_peak = deadline.hour < 10
        
        # PV Check
        pv_strong = fc_next >= pv_fc_thresh
        cur_pv_strong = cur_pv >= cur_pv_thresh
        fc_now_strong = fc_now >= pv_fc_thresh
        pv_dominant = pv_strong or cur_pv_strong or fc_now_strong
        
        pool = [x for x in all_prices if x['time_dt'] < deadline and x['time_dt'] >= start_slot]
        need_soc_kwh = max(0.0, (target_soc - cur_soc) / 100 * batt_cap)
        req_intervals = int(math.ceil((need_soc_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0
        charge_slots_cnt = min(req_intervals, user_intervals)
        charge_slots_cnt = max(0, charge_slots_cnt)
        final_slots = charge_slots_cnt
        needed_kwh = need_soc_kwh
        if charge_slots_cnt > 0 and pool:
            try:
                sorted_pool = sorted(pool, key=lambda x: x['price'])
                if len(sorted_pool) >= charge_slots_cnt:
                    best_slots = sorted_pool[:charge_slots_cnt]
                    best_slots.sort(key=lambda x: x['time_dt'])
                    first_slot_dt = best_slots[0]['time_dt']
                    time_until = (first_slot_dt - now_dt).total_seconds() / 3600
                    
                    avg_load = 500.0
                    if self.avg_consumption_sensor_id:
                        avg_load = self._get_float_state(self.avg_consumption_sensor_id, default=500.0)
                    
                    if time_until <= 1.0: calc_load = (cur_house * 0.7) + (avg_load * 0.3) 
                    else: calc_load = avg_load 
                    
                    calc_load = max(200.0, min(1500.0, calc_load))
                    
                    pred_load_kwh = (calc_load / 1000) * max(0, time_until)
                    if is_morning_peak or fc_next < 0.1: pred_pv_kwh = 0
                    else: pred_pv_kwh = fc_rem * self.pv_forecast_safety_factor
                    total_need = need_soc_kwh + pred_load_kwh - pred_pv_kwh
                    total_need = max(0.0, min(total_need, batt_cap))
                    req_h = total_need / charge_pwr if charge_pwr > 0 else 0
                    final_slots = min(int(math.ceil(req_h * 4)), user_intervals)
                    needed_kwh = total_need
            except: pass

        if pool and final_slots > 0:
            sorted_pool = sorted(pool, key=lambda x: x['price'])
            cheap_slots_found = sorted_pool[:final_slots]
            cheap_slots_found.sort(key=lambda x: x['time_dt'])
            if cheap_slots_found:
                avg_price_slots = sum(i['price'] for i in cheap_slots_found) / len(cheap_slots_found)
            times_str = ", ".join([t['time_dt'].strftime('%H:%M') for t in cheap_slots_found])

        if cheap_slots_found and needed_kwh > 0:
            start_t = cheap_slots_found[0]['time_dt'].strftime('%H:%M')
            end_t = (cheap_slots_found[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')
            cheap_hours_info = f"{len(cheap_slots_found)}x 15min ({start_t}...{end_t}) Ø {avg_price_slots:.3f} €"
            for slot in cheap_slots_found:
                if slot['time_dt'] == start_slot:
                    current_time_in_best_block = True
                    break
        
        if self.next_charge_time_id and cheap_slots_found:
            self.set_state(self.next_charge_time_id, state=cheap_slots_found[0]['time_dt'].strftime('%H:%M'))
        elif self.next_charge_time_id:
            self.set_state(self.next_charge_time_id, state="--:--")
            
        t_panic = (deadline - now_dt).total_seconds() / 3600
        panic_mode = (t_panic < 1.5) and (cur_price <= price_discharge_limit) and (needed_kwh > 0)

        # Sonnen-Erkennung
        sun_elevation = 0
        try: sun_elevation = float(self.get_state(self.sun_sensor_id, attribute='elevation'))
        except: pass
        is_daylight = sun_elevation > 0 

        weather_factor = 0.5
        cloud_val = None
        if self.cloud_coverage_sensor_id:
            try:
                c_raw = float(self.get_state(self.cloud_coverage_sensor_id))
                cloud_val = 1.0 - (c_raw / 100.0)
                weather_factor = max(0.0, min(1.0, cloud_val))
            except: pass
        
        if cloud_val is None and self.weather_sensor_id:
            w_state = self.get_state(self.weather_sensor_id)
            if w_state in WEATHER_PV_FACTOR:
                weather_factor = WEATHER_PV_FACTOR[w_state]
        
        pv_active = cur_pv > 50
        forecast_strong = fc_next > 0.1 or fc_now_strong
        
        approaching_peak = False
        if peak_dt:
             diff = (peak_dt - now_aware).total_seconds() / 60
             if diff > -30 and diff < 90: approaching_peak = True

        is_sun_shining = False
        if pv_active: is_sun_shining = True
        elif is_daylight and weather_factor >= 0.4 and forecast_strong: is_sun_shining = True
        elif approaching_peak: is_sun_shining = True

        # PRIO 1: DISCHARGE
        if app_is_enabled and ((cur_price > price_discharge_limit and not should_hold) or interim_dip):
            if cur_soc > effective_min_soc:
                if cur_batt_pwr > 50: is_discharge_active = True
                status_msg = f"{self.T['STATUS_DISCHARGE_BASE']}."
                if interim_dip: status_msg = f"{self.T['STATUS_DISCHARGE_DIP']}."
                self.set_state(self.dashboard_status_text_id, state=status_msg)
                self._set_inverter_mode(self.mode_general)
            else:
                status_msg = f"{self.T['STATUS_DISCHARGE_RESERVE_REACHED']} ({effective_min_soc}%)."
                self.set_state(self.dashboard_status_text_id, status_msg)
                self._set_inverter_mode(self.mode_general)

        # PRIO 2: CHARGE
        elif app_is_enabled and cur_soc < target_soc and (panic_mode or (current_time_in_best_block and not is_sun_shining)):
            is_dip = (cur_spread >= self.base_min_price_spread_eur)
            allow = (current_time_in_best_block or panic_mode) if (current_time_in_best_block or panic_mode) else ((cur_price <= price_discharge_limit) or is_dip)
            
            if allow:
                status_msg = f"{self.T['STATUS_CHARGE_ACTIVE']}: {cheap_hours_info}"
                self.set_state(self.dashboard_status_text_id, status_msg)
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
                self._set_inverter_mode(self.mode_charge)
            else:
                self.turn_on(self.cheap_hour_toggle_id)
                self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_BLOCKED']} ({cur_price:.3f}€).")

        # PRIO 3: PV OPTIMIZATION
        elif pv_dominant and cur_soc < 100:
            if cur_batt_pwr < -100: 
                is_pv_charge_active = True
                self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_PV_CHARGING']}.")
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
            else:
                self._set_inverter_mode(self.mode_general)

        # PRIO 4: IDLE / HOLD
        elif not is_pv_charge_active and not charge_toggle_on and not is_discharge_active:
            tgt_mode = self.mode_backup
            info = self.T['STATUS_WAIT_HOLD']

            if is_sun_shining:
                tgt_mode = self.mode_general
                info = self.T['STATUS_WAIT_PV']
            elif not should_hold:
                tgt_mode = self.mode_general
                info = self.T['STATUS_IDLE']

            self._set_inverter_mode(tgt_mode)
            self.set_state(self.dashboard_status_text_id, state=f"{info} ({tgt_mode}).")
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)

        # PRIO 5: TARGET REACHED
        elif needed_kwh == 0 and cur_soc >= target_soc:
            tgt_mode = self.mode_backup
            if is_sun_shining: tgt_mode = self.mode_general
            
            self._set_inverter_mode(tgt_mode)
            self.set_state(self.dashboard_status_text_id, state=self.T['STATUS_TARGET_REACHED'])
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)
        
        if self.cheap_hours_text_id: self.set_state(self.cheap_hours_text_id, state=cheap_hours_info)
        
        if (charge_toggle_on or is_pv_charge_active) and not self.charging_session_active:
            self.charging_session_active = True
            self.charging_session_start_time = self.datetime()
            self.charging_session_net_charged_kwh = 0.0
            self.log(f"INFO: {self.T['INFO_SESSION_START']}", level="INFO")

        if self.charging_session_active:
            if cur_grid > 50:
                kwh_min = (abs(cur_grid) / 1000) / 60
                self.charging_session_net_charged_kwh += kwh_min
                cp = avg_price_slots if cheap_slots_found else (all_prices[0]['price'] if all_prices else 0.0)
                self._update_charge_cost_stats(kwh_min, cp)

        if self.charging_session_active and not (charge_toggle_on or is_pv_charge_active):
            self.log(f"INFO: {self.T['INFO_SESSION_END']} Gesamt: {self.charging_session_net_charged_kwh:.3f} kWh.", level="INFO")
            self.charging_session_active = False
            self.charging_session_net_charged_kwh = 0.0

        if is_discharge_active and cur_batt_pwr > 50:
            if not self.discharging_active: 
                self.discharging_active = True
                self.log(f"INFO: {self.T['INFO_DISCHARGE_START']}", level="INFO")
            dis_kwh = (abs(cur_batt_pwr) / 1000) / 60 
            self._update_discharge_saving_stats(dis_kwh, cur_price)
        elif self.discharging_active:
            self.discharging_active = False
            self.log(f"INFO: {self.T['INFO_DISCHARGE_END']}", level="INFO")

        if cur_pv > 0 and cur_house > 0:
             direct = min(cur_pv, cur_house)
             dkwh = (direct / 1000) / 60
             self._update_pv_direct_stats(dkwh, cur_price)

        # --- MONTAGS-SICHERHEITS-LOGIK (DYNAMISCH) ---
        is_sunday_night = (now_dt.weekday() == 6 and now_dt.hour >= int(self.args.get('monday_deadline_start_hour', 20)))
        
        finish_h = 6
        deadline_id = self.args.get('monday_deadline_time_id')
        if deadline_id:
            try:
                deadline_attr = self.get_state(deadline_id, attribute='all') or {}
                finish_h = int((deadline_attr.get('attributes') or {}).get('hour', 6))
            except:
                finish_h = 6

        is_monday_early = (now_dt.weekday() == 0 and now_dt.hour < finish_h)
        force_charge_slots = False 
        mon_min_soc = 0.0
        
        if (is_sunday_night or is_monday_early):
            mon_min_soc = self._get_float_state(self.args.get('monday_min_soc_id'), default=75.0)
            ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=0.0)
            
            if ev_current_soc < mon_min_soc:
                gap_kwh = ((mon_min_soc - ev_current_soc) / 100.0) * ev_capacity
                needed_intervals = int(math.ceil((gap_kwh / ev_charge_pwr) * 4))
                force_charge_slots = True

        # --- ULTIMATE HYBRID: EV / WALLBOX LOGIK (WAF Boost Edition) ---
        if self.ev_logic_active_id and self.get_state(self.ev_logic_active_id) == 'on':
            if getattr(self, 'ev_wallbox_switch_id', None):
                
                ev_capacity = float(self.args.get('ev_battery_capacity_kwh', 77.0))
                ev_power = float(self.args.get('ev_charge_power_kw', 11.0))
                
                # Boost & Preis-Limit abfragen
                ev_boost_id = self.args.get('ev_boost_switch_id', 'input_boolean.ev_boost_mode')
                ev_boost_active = self.get_state(ev_boost_id) == 'on'
                    
                ev_price_limit = float(self.args.get('ev_immediate_charge_price', 0.30))
                is_price_super_cheap = cur_price <= ev_price_limit

                # 1. Slider-Wert auslesen (Wunschziel für den nächsten Morgen)
                ev_target_slider = self._get_float_state(self.ev_target_soc_id, default=80.0)
                ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=0.0)

                # 2. AUTO-RESET (VW Care Mode Logik)
                if ev_current_soc >= ev_target_slider and ev_target_slider > 80.0:
                    self.log(f"Ziel {ev_target_slider}% erreicht. Setze Dashboard-Slider automatisch auf 80% zurück.", level="INFO")
                    self.call_service("input_number/set_value", entity_id=self.ev_target_soc_id, value=80.0)
                    ev_target_slider = 80.0

                # 3. Das finale Ladeziel für die Nacht-Kalkulation
                ev_target = ev_target_slider
                
                # Montagsregel überschreibt ggf. nach oben
                if force_charge_slots:
                    ev_target = max(ev_target, mon_min_soc)

                ev_is_cheap_now = False

                # --- UPGRADE: WAF-BOOST PRIORITÄT 0 ---
                if ev_boost_active:
                    if ev_current_soc < ev_target:
                        self.log(f"WAF-BOOST AKTIV: Lade bis {ev_target}%. Hausakku auf Standby.", level="INFO")
                        self._set_inverter_mode(self.mode_backup)
                        if self.get_state(self.ev_wallbox_switch_id) != 'on':
                            self.turn_on(self.ev_wallbox_switch_id)
                        if getattr(self, 'dashboard_status_text_id', None):
                            self.set_state(self.dashboard_status_text_id, state=f"WAF Boost! Lade bis {ev_target}%.")
                        return
                    else:
                        self.turn_off(ev_boost_id)
                        self.log("WAF-Boost Ziel erreicht. Schalte Boost-Schalter aus.", level="INFO")

                # Normale Preise berechnen (nur wenn Ziel noch nicht erreicht)
                if ev_current_soc < ev_target:
                    if is_price_super_cheap:
                        ev_is_cheap_now = True
                    else:
                        ev_gap_kwh = max(0.0, ((ev_target - ev_current_soc) / 100.0) * ev_capacity)
                        
                        # --- NEU: PV-Vorhersage für das Auto berücksichtigen ---
                        # Wir schauen, wie viel PV-Ertrag heute noch erwartet wird (fc_rem).
                        # Da das Haus auch etwas braucht, nehmen wir den Sicherheitsfaktor.
                        pred_ev_pv_kwh = 0.0
                        if fc_rem > 1.0:
                            pred_ev_pv_kwh = fc_rem * self.pv_forecast_safety_factor
                            self._log_debug(f"EV-Planung: Berücksichtige {pred_ev_pv_kwh:.1f} kWh ankommenden PV-Ertrag.", level="DEBUG")
                            
                        # Wir reduzieren den Strom, der aus dem Netz geladen werden muss,
                        # um die erwartete PV-Leistung des heutigen Tages.
                        net_ev_gap_kwh = max(0.0, ev_gap_kwh - pred_ev_pv_kwh)
                        ev_req_slots = int(math.ceil((net_ev_gap_kwh / ev_power) * 4)) 

                        ev_deadline = now_dt.replace(hour=7, minute=0, second=0, microsecond=0)
                        if now_dt.hour >= 7:
                            ev_deadline += timedelta(days=1)

                        ev_pool = [x for x in all_prices if start_slot <= x['time_dt'] < ev_deadline]

                        if ev_pool and ev_req_slots > 0:
                            ev_best_slots = sorted(ev_pool, key=lambda x: x['price'])[:ev_req_slots]
                            for slot in ev_best_slots:
                                if slot['time_dt'] == start_slot:
                                    ev_is_cheap_now = True
                                    break

                # Aktionen ausführen
                is_cheap_charge = ev_is_cheap_now or force_charge_slots
                is_pv_surplus_charge = is_pv_charge_active and not is_cheap_charge

                # TIBBER / SOFORT-LADEN (aus dem Netz)
                if is_cheap_charge:
                    if ev_current_soc < ev_target:
                        if current_mode != self.mode_charge:
                            self._set_inverter_mode(self.mode_backup)
                            
                        if self.get_state(self.ev_wallbox_switch_id) != 'on':
                            self.turn_on(self.ev_wallbox_switch_id)
                        
                        if getattr(self, 'dashboard_status_text_id', None):
                            if is_price_super_cheap:
                                self.set_state(self.dashboard_status_text_id, state=f"Preis unter {ev_price_limit}€. Lade bis {ev_target}%.")
                            else:
                                self.set_state(self.dashboard_status_text_id, state=f"Nachtladen bis {ev_target}%")
                    else:
                        self.gentleman_stop(reason=f"Ziel ({ev_target}%) erreicht.")
                
                # PV-ÜBERSCHUSS (Tagsüber warten, bis Hausakku voll genug ist)
                elif is_pv_surplus_charge:
                    hausakku_schwelle = getattr(self, 'home_battery_priority_soc', 30.0)

                    if cur_soc >= hausakku_schwelle:
                        if self.get_state(self.ev_wallbox_switch_id) == 'on':
                            self.turn_off(self.ev_wallbox_switch_id)
                        
                        if getattr(self, 'dashboard_status_text_id', None):
                            self.set_state(self.dashboard_status_text_id, state="Auto wartet auf PV")
                    else:
                        self.gentleman_stop(reason=f"Hausakku erst bei {cur_soc}%. Priorität hat das Haus.")
                
                else:
                    self.gentleman_stop(reason="Ziel erreicht oder außerhalb der Ladezeiten.")

    # -----------------------------------------------------------
    #  REFLEX-MODUL: Wallbox Absteck-Erkennung
    # -----------------------------------------------------------
    def check_wallbox_disconnect(self, entity, attribute, old, new, kwargs):
        disconnect_states = ("1", "off")
        if new in disconnect_states and old not in disconnect_states:
            if self.ev_wallbox_switch_id and self.get_state(self.ev_wallbox_switch_id) == 'on':
                self.turn_off(self.ev_wallbox_switch_id)
            if self.ev_pv_surplus_switch_id and self.get_state(self.ev_pv_surplus_switch_id) == 'on':
                self.turn_off(self.ev_pv_surplus_switch_id)
            self.log("REFLEX: Auto wurde abgesteckt! Wallbox-Schalter zur Sicherheit auf AUS gesetzt.", level="INFO")

    def terminate(self):
        self.log(f"INFO: {self.T['INFO_APP_TERMINATED']}", level="INFO")
        if hasattr(self, 'cheap_hour_toggle_id'): self.turn_off(self.cheap_hour_toggle_id)
