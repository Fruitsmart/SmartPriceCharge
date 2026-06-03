# -*- coding: utf-8 -*-
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta, time
import math

# VERSION: 4.3.31 (Redundanz Edition | VW Sync + Türsteher Fallback)

# --- WETTER FAKTOREN (0.0 = Schlecht / 1.0 = Super) ---
WEATHER_PV_FACTOR = {
    'sunny': 1.0, 'clear-night': 0.0, 'partlycloudy': 0.8, 'cloudy': 0.5,
    'fog': 0.3, 'rainy': 0.1, 'pouring': 0.05, 'snowy': 0.4,
    'lightning': 0.1, 'hail': 0.1, 'windy': 0.5, 'exceptional': 0.0
}

# --- ÜBERSETZUNGSTABELLE (i18n) ---
TRANSLATIONS = {
    'DE': {
        'APP_VERSION': 'Version 4.3.31 (Redundanz Edition)',
        'ACTION_MODE_CHANGE': 'Modus-Änderung nötig',
        'ACTION_HEARTBEAT': 'Safety Heartbeat',
        'ERROR_NO_PRICE_DATA': 'FEHLER: Keine Preisdaten',
        'ERROR_NO_INTERVALS': 'FEHLER: Keine Preisintervalle',
        'STATUS_DISCHARGE_BASE': 'Entladen (Eigenverbrauch)',
        'STATUS_DISCHARGE_DIP': 'Entladen (Dip-Refill)',
        'STATUS_DISCHARGE_RESERVE_REACHED': 'Reserve erreicht',
        'STATUS_CHARGE_ACTIVE': 'Hausakku lädt (Netz)',
        'STATUS_CHARGE_BLOCKED': 'Blockiert: Preis zu hoch',
        'STATUS_PV_CHARGING': 'Hausakku lädt (PV)',
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
        'STATUS_EV_PV': 'Auto regelt PV-Ladung (go-e übernimmt)',
        'STATUS_EV_PLAN_NONE': 'Kein Netzladen geplant (PV/Ziel erreicht)',
        'STATUS_EV_PLAN_ACTIVE': 'Netzladen geplant: {start} - {end} ({slots} Slots)',
        'STATUS_EV_PLAN_WAIT': 'Warte auf billige Slots...',
        'STATUS_EV_PLAN_BOOST': 'WAF-BOOST aktiv: Laden bis {target}%',
        'STATUS_EV_PLAN_PV': 'Warten auf PV-Überschuss',
        'STATUS_EV_MANUAL': 'Manuelle Ladung (Hausakku Standby)',
        'STATUS_EV_BLOCK': 'Schutz: Auto gestoppt (Teuer)',
        'STATUS_CHARGE_NET': 'Netzladen Auto (Aktiv)'
    },
    'EN': {
        'APP_VERSION': 'Version 4.3.31 (Redundanz Edition)',
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
        'INFO_APP_TERMINATED': 'App beendet.',
        'REPORT_GRID_COST': 'Grid Cost',
        'REPORT_CHARGE_SAVE': 'Charge Savings',
        'REPORT_DISCHARGE_VALUE': 'Discharge Value',
        'REPORT_PV_VALUE': 'PV Direct Value',
        'REPORT_CHARGED_KWH': 'Charged',
        'STATUS_EV_PLAN_NONE': 'No charging planned',
        'STATUS_EV_PLAN_ACTIVE': 'Planned: {start} - {end} ({slots} slots)',
        'STATUS_EV_PLAN_WAIT': 'Waiting for cheap slots...',
        'STATUS_EV_PLAN_BOOST': 'WAF-BOOST active: Charging to {target}%',
        'STATUS_EV_PLAN_PV': 'Waiting for PV',
        'STATUS_EV_MANUAL': 'Manual Charge (Home Battery Standby)',
        'STATUS_EV_BLOCK': 'Protection: Car stopped (Expensive)',
        'STATUS_CHARGE_NET': 'Grid Charging Auto (Active)'
    }
}

class SmartPriceCharge(hass.Hass):

    def initialize(self):
        lang_code = self.args.get('language', 'DE').upper()
        if lang_code not in TRANSLATIONS: lang_code = 'DE'
        self.T = TRANSLATIONS[lang_code]
        self.log(f"Initializing {self.T['APP_VERSION']}...", level="INFO")

        # --- BASIS CONFIG ---
        self.price_sensor_id = self.args['price_sensor_id']
        self.current_soc_sensor_id = self.args['current_soc_sensor_id']
        self.inverter_mode_entity_id = self.args['inverter_mode_entity_id']
        self.inverter_max_soc_entity_id = self.args.get('inverter_max_soc_entity_id', 'number.goodwe_eco_mode_soc')
        
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
        self.ev_target_soc_id = self.args.get('ev_target_soc_id') # Slider 1
        self.ev_wallbox_switch_id = self.args.get('ev_wallbox_switch_id')
        self.ev_soc_sensor_id = self.args.get('ev_soc_sensor_id') # Tibber SoC Sensor
        self.ev_wallbox_amps_id = self.args.get('ev_wallbox_amps_id')
        self.ev_car_charging_switch_id = self.args.get('ev_car_charging_switch_id', 'switch.id4_charging')
        self.ev_car_target_soc_entity_id = self.args.get('ev_car_target_soc_entity_id', 'number.id4_battery_target_charge_level')
        self.ev_pv_surplus_switch_id = self.args.get('ev_pv_surplus_switch_id', 'switch.goe_315255_fup')
        self.ev_logic_mode_id = self.args.get('ev_logic_mode_id')
        self.ev_charge_plan_id = self.args.get('ev_charge_plan_id') 
        self.ev_boost_switch_id = self.args.get('ev_boost_switch_id')
        
        self.monday_min_soc_id = self.args.get('monday_min_soc_id', 'input_number.ev_montag_sicherheits_soc') # Slider 2
        self.monday_deadline_time_id = self.args.get('monday_deadline_time_id', 'input_datetime.ev_montag_abfahrtszeit')
        
        self.home_battery_priority_soc = float(self.args.get('home_battery_priority_soc', 95.0))

        # Dynamic Parameters
        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.50))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.efficiency_factor = float(self.args.get('battery_efficiency_factor', 0.90))
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.08))
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 80.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 95.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        self.sleep_over_soc = float(self.args.get('sleep_over_soc', 30.0))
        self.morning_min_diff = float(self.args.get('morning_min_diff', 0.10))

        # Inverter Modes & Tracking IDs
        self.mode_charge = self.args.get('inverter_mode_charge', 'charge_battery')
        self.mode_general = self.args.get('inverter_mode_general', 'auto')
        self.mode_backup = self.args.get('inverter_mode_backup', 'battery_standby')
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
        
        self.ev_wallbox_status_id = self.args.get('ev_wallbox_status_id', 'sensor.go_echarger_315255_car_state')
        self.listen_state(self.check_wallbox_disconnect, self.ev_wallbox_status_id)
        
        # NEU: Listener für VW-Sync hinzugefügt (Fehlertolerant)
        if self.ev_target_soc_id:
            self.listen_state(self.on_ev_target_soc_slider_change, self.ev_target_soc_id)
        
        delay = int(self.args.get('startup_delay_seconds', 120))
        self.run_in(self.start_app_routine, delay)

    def start_app_routine(self, kwargs):
        self.log("System stabilisiert. Starte Hauptlogik.", level="INFO")
        now = self.datetime()
        next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, next_min, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))
        
        # Führe beim Start einen initialen Sync aus
        initial_val = self._get_float_state(self.ev_target_soc_id, 80.0)
        self.sync_ev_soc_to_car_debounced({'value': initial_val})
        self.main_logic({})

    # --- MASTER-SYNC METHODS (Mit Fehlertoleranz) ---
    def on_ev_target_soc_slider_change(self, entity, attribute, old, new, kwargs):
        """Wird ausgelöst, wenn du den Slider im Dashboard bewegst."""
        if self.sync_handle: self.cancel_timer(self.sync_handle)
        self.sync_handle = self.run_in(self.sync_ev_soc_to_car_debounced, 3, value=new)

    def sync_ev_soc_to_car_debounced(self, kwargs):
        """Sendet das Limit an VW. Fängt Fehler ab, falls die API gestört ist."""
        try:
            slider_val = int(float(kwargs.get('value', 80)))
            # WICHTIG: Wir senden immer mindestens 80% an das Auto, damit PV-Laden immer 
            # bis 80% funktionieren kann, selbst wenn dein Tages-Slider auf z.B. 40% steht.
            target_val_for_car = max(80, slider_val)
            
            if self.ev_car_target_soc_entity_id:
                # Versuch, mit VW zu kommunizieren
                self.call_service("number/set_value", entity_id=self.ev_car_target_soc_entity_id, value=target_val_for_car)
                self.log(f"VW-SYNC: Auto Ladelimit erfolgreich auf {target_val_for_car}% aktualisiert.", level="INFO")
        except Exception as e:
            # Wenn VW streikt, loggen wir das nur als Info. Die Logik bricht nicht ab!
            self.log(f"VW-SYNC fehlgeschlagen (API offline?). Ignoriere und nutze Wallbox-Fallback. Details: {e}", level="INFO")

    # --- HELPERS ---
    def _log_debug(self, message, level="INFO"):
        if level == "DEBUG":
            if self.log_debug_level: self.log(message, level="INFO")
            else: self.log(message, level="DEBUG")
        else: self.log(message, level=level)

    def _get_float_state(self, entity_id, default=0.0):
        if not entity_id: return default
        try:
            state = self.get_state(entity_id)
            if state in ['unavailable', 'unknown', 'none', None]: return 0.0
            return float(state)
        except: return default
    
    def _get_tracking_state(self, entity_id): return self._get_float_state(entity_id, default=0.0)
    
    def _set_tracking_state(self, entity_id, value, decimals=6):
        if entity_id:
            try: self.set_state(entity_id, state=round(value, decimals))
            except: pass

    def _set_error_states(self, message_key):
        if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=self.T[message_key])

    # --- WALLBOX CONTROL ---
    def _set_wallbox_state(self, state_option: str):
        eid = getattr(self, 'ev_wallbox_switch_id', None)
        if not eid: return
        domain = eid.split('.')[0]
        
        if domain == 'select':
            opt_lower = state_option.lower()
            target = "0" 
            if opt_lower in ['off', 'aus', '1']: target = "1"
            elif opt_lower in ['on', 'ein', '2']: target = "2"

            current = str(self.get_state(eid))
            if current != target:
                if target in ['0', '2'] and current == '1':
                    self.log("ID.4 WAKE-UP: Triggere Signalunterbrechung...", level="INFO")
                    self.call_service("select/select_option", entity_id=eid, option="1") 
                    self.run_in(self._deferred_wb_select, 5, option=target)
                else:
                    self.call_service("select/select_option", entity_id=eid, option=target)
        else:
            if state_option.lower() in ['on', 'neutral']: self.turn_on(eid)
            else: self.turn_off(eid)

    def _deferred_wb_select(self, kwargs):
        eid = getattr(self, 'ev_wallbox_switch_id', None)
        if eid: self.call_service("select/select_option", entity_id=eid, option=kwargs['option'])

    def _set_wallbox_logic_mode(self, mode_str: str):
        eid = getattr(self, 'ev_logic_mode_id', None)
        if eid:
            target = "4" if mode_str.lower() == "eco" else "3"
            current = str(self.get_state(eid))
            if current != target:
                self.call_service("select/select_option", entity_id=eid, option=target)

    def _set_inverter_mode(self, target_mode):
        current_mode = self.get_state(self.inverter_mode_entity_id)
        now = self.get_now()
        heartbeat = False
        reason = ""
        
        if not self.last_inverter_mode_command_time: 
            heartbeat = True
            reason = self.T['ACTION_HEARTBEAT']
        elif (now - self.last_inverter_mode_command_time).total_seconds() > 900: 
            heartbeat = True
            reason = self.T['ACTION_HEARTBEAT']
            
        if current_mode != target_mode:
            reason = self.T['ACTION_MODE_CHANGE']
        
        if current_mode != target_mode or heartbeat:
            if not self.debug_mode:
                if target_mode == self.mode_charge and self.inverter_max_soc_entity_id:
                    val = self._get_float_state(self.target_soc_id, default=100.0)
                    self.call_service("number/set_value", entity_id=self.inverter_max_soc_entity_id, value=str(int(val)))
                self.call_service("select/select_option", entity_id=self.inverter_mode_entity_id, option=target_mode)
                self.log(f"ACTION: Set Mode '{target_mode}' ({reason}).", level="INFO")
            self.last_inverter_mode_command_time = now
        else:
            self.log(f"Inverter Mode '{target_mode}' OK.", level="INFO")

    # --- TRACKING HELPERS ---
    def _update_charge_cost_stats(self, net_charged_kwh, avg_charge_price):
        if net_charged_kwh <= 0: return
        ref_p = self._get_float_state(self.reference_price_id, 0.35)
        cost = net_charged_kwh * avg_charge_price
        saving = net_charged_kwh * (ref_p - avg_charge_price)
        self._set_tracking_state(self.cost_month_id, self._get_tracking_state(self.cost_month_id) + cost)
        self._set_tracking_state(self.savings_month_id, self._get_tracking_state(self.savings_month_id) + saving)
        self._set_tracking_state(self.cost_total_id, self._get_tracking_state(self.cost_total_id) + cost)
        self._set_tracking_state(self.savings_total_id, self._get_tracking_state(self.savings_total_id) + saving)
        self._set_tracking_state(self.charged_kwh_month_id, self._get_tracking_state(self.charged_kwh_month_id) + net_charged_kwh, 4)
        self._set_tracking_state(self.charged_kwh_total_id, self._get_tracking_state(self.charged_kwh_total_id) + net_charged_kwh, 4)
        self._update_monthly_report()

    def _update_discharge_saving_stats(self, discharged_kwh_dc, current_price):
        if discharged_kwh_dc <= 0: return
        ac = discharged_kwh_dc * self.efficiency_factor
        sav = ac * current_price
        self._set_tracking_state(self.discharge_savings_month_id, self._get_tracking_state(self.discharge_savings_month_id) + sav)
        self._set_tracking_state(self.discharge_savings_total_id, self._get_tracking_state(self.discharge_savings_total_id) + sav)
        self._update_monthly_report()

    def _update_pv_direct_stats(self, direct_pv_kwh, current_price):
        if direct_pv_kwh <= 0: return
        sav = direct_pv_kwh * current_price
        self._set_tracking_state(self.pv_savings_month_id, self._get_tracking_state(self.pv_savings_month_id) + sav)
        self._set_tracking_state(self.pv_savings_total_id, self._get_tracking_state(self.pv_savings_total_id) + sav)

    def reset_monthly_stats_daily_check(self, kwargs):
        now = self.datetime()
        if not self.report_id: return
        try: 
            attr = self.get_state(self.report_id, attribute='all')['attributes']
            last_reset = attr.get('last_reset_date')
            if not last_reset or datetime.strptime(last_reset, '%Y-%m-%d').month != now.month:
                for eid in [self.pv_savings_month_id, self.cost_month_id, self.savings_month_id, self.discharge_savings_month_id]: self._set_tracking_state(eid, 0.0)
                self._set_tracking_state(self.charged_kwh_month_id, 0.0, 4)
                attr['last_reset_date'] = now.strftime('%Y-%m-%d')
                self.set_state(self.report_id, state=self.get_state(self.report_id), attributes=attr)
        except: pass
        self._update_monthly_report()

    def _update_monthly_report(self):
        if not self.report_id: return
        report = f"Monat ({self.datetime().strftime('%B %Y')}):\n{self.T['REPORT_GRID_COST']}: {self._get_tracking_state(self.cost_month_id):.2f} €\n{self.T['REPORT_CHARGE_SAVE']}: {self._get_tracking_state(self.savings_month_id):.2f} €\n{self.T['REPORT_DISCHARGE_VALUE']}: {self._get_tracking_state(self.discharge_savings_month_id):.2f} €\n{self.T['REPORT_PV_VALUE']}: {self._get_tracking_state(self.pv_savings_month_id):.2f} €\n{self.T['REPORT_CHARGED_KWH']}: {self._get_tracking_state(self.charged_kwh_month_id):.2f} kWh"
        self.set_state(self.report_id, state=report)

    # --- MAIN LOGIC ---
    def main_logic(self, kwargs):
        SIMULATE_SUNDAY_NIGHT = False
        cheap_slots_found = []
        avg_price_slots = 0.0
        is_pv_charge_active = False
        charge_toggle_on = False
        is_discharge_active = False
        current_time_in_best_block = False
        cheap_hours_info = self.T['INFO_SLOTS_NONE']
        
        now_dt = self.get_now().replace(second=0, microsecond=0, tzinfo=None)
        now_aware = self.get_now()
        app_is_enabled = self.get_state(self.app_enabled_switch_id) == 'on'
        
        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, 5.0) 
        charge_pwr = self._get_float_state(self.charger_power_kw_id, 3.0) 
        target_soc = self._get_float_state(self.target_soc_id, 100.0)
        pv_fc_thresh = self._get_float_state(self.pv_forecast_threshold_kw_id, 1.0)
        cur_pv_thresh = self._get_float_state(self.current_pv_threshold_w_id, 500.0)
        price_discharge_limit = self._get_float_state(self.price_discharge_threshold_id, 0.30)
        user_intervals = int(self._get_float_state(self.charge_intervals_input_id, 16.0))
        cur_soc = self._get_float_state(self.current_soc_sensor_id)
        cur_pv = self._get_float_state(self.current_pv_power_sensor_id)
        cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id)
        cur_grid = self._get_float_state(self.grid_power_import_export_sensor_id)
        cur_house = self._get_float_state(self.current_house_consumption_w_id)
        dod = self._get_float_state(self.min_soc_discharge_id, default=20.0)
        base_min_soc = 100.0 - dod 
        
        wb_status = str(self.get_state(self.ev_wallbox_status_id)).strip().lower()
        car_state = str(self.get_state(self.ev_car_charging_switch_id)).strip().lower()
        wb_force = str(self.get_state(self.ev_wallbox_switch_id)).strip().lower()
        ev_active = (wb_status in ["charging", "laden", "2"]) or (car_state in ["on", "true", "charging"])
        
        is_manual_override = (wb_force in ['on', '2', 'ein'])

        self.log(f"EV-Schutz Check: WB-Status='{wb_status}', Switch='{wb_force}', Auto='{car_state}' -> WB Aktiv: {ev_active}", level="INFO")

        fc_rem = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        fc_next = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        fc_now = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        fc_tmrw = self._get_float_state(self.pv_forecast_tomorrow_id, default=0.0)
        
        self.log(f"SoC:{cur_soc:.1f}% | PV:{cur_pv:.0f}W | FC-Now:{fc_now:.2f} | FC-Morgen:{fc_tmrw:.1f}", level="INFO")

        # ==========================================================
        # 🚗 EV TARGET & TIBBER SOC LOGIC (PV vs. Grid Split)
        # ==========================================================
        ev_gap_kwh = 0.0
        car_is_full = False
        
        ev_target_daily = self._get_float_state(self.ev_target_soc_id, 40.0)
        monday_target = self._get_float_state(self.monday_min_soc_id, 80.0)
        
        ev_current_soc = self._get_float_state(self.ev_soc_sensor_id, default=100.0)
        ev_cap = float(self.args.get('ev_battery_capacity_kwh', 77.0))
        ev_pwr = float(self.args.get('ev_charge_power_kw', 11.0))
        
        dl_hour, dl_minute = 7, 0
        if getattr(self, 'monday_deadline_time_id', None):
            try:
                t_str = str(self.get_state(self.monday_deadline_time_id))
                if t_str and t_str not in ['unavailable', 'unknown', 'none']:
                    parts = t_str.split(':')
                    dl_hour, dl_minute = int(parts[0]), int(parts[1])
            except: pass

        is_mon_sec = False
        if now_dt.weekday() == 6 and now_dt.hour >= int(self.args.get('monday_deadline_start_hour', 8)):
            is_mon_sec = True
        elif now_dt.weekday() == 0 and (now_dt.hour < dl_hour or (now_dt.hour == dl_hour and now_dt.minute <= dl_minute)):
            is_mon_sec = True

        if SIMULATE_SUNDAY_NIGHT: is_mon_sec = True
        
        # 1. NETZ-ZIEL
        ev_grid_target = ev_target_daily
        if is_mon_sec: 
            ev_grid_target = max(ev_grid_target, monday_target)
            
        # 2. PV-ZIEL (Türsteher-Limit)
        ev_pv_target = max(80.0, ev_grid_target)
        
        if self.ev_logic_active_id and self.get_state(self.ev_logic_active_id) == 'on':
            # Der Fallback-Türsteher kappt den Strom, sobald das PV/Absolute Ziel erreicht ist.
            if ev_current_soc >= ev_pv_target:
                car_is_full = True
                
            if ev_current_soc < ev_grid_target:
                ev_gap_kwh = ((ev_grid_target - ev_current_soc) / 100.0) * ev_cap

        # ==========================================================
        
        tomorrow_weekday = (now_dt + timedelta(days=1)).weekday()
        is_car_home_tomorrow = tomorrow_weekday in [5, 6]
        
        dynamic_summer_threshold = 10.0
        if is_car_home_tomorrow:
            dynamic_summer_threshold += ev_gap_kwh
        
        if fc_tmrw >= dynamic_summer_threshold:
            survival_target = self.sleep_over_soc
            if target_soc > survival_target: target_soc = survival_target
                
        peak_dt = None
        if self.pv_peak_time_sensor_id:
            s = self.get_state(self.pv_peak_time_sensor_id)
            if s and s not in ['unavailable', 'unknown']:
                try: peak_dt = datetime.fromisoformat(s)
                except: pass

        prices_today = self.get_state(self.price_sensor_id, attribute='today')
        prices_tmrw = self.get_state(self.price_sensor_id, attribute='tomorrow')
        all_prices = []
        start_slot = now_dt - timedelta(minutes=now_dt.minute % 15)
        today_date = now_dt.date()
        
        if prices_today:
            for i, p in enumerate(prices_today):
                dt = datetime.combine(now_dt.date(), time(i // 4, (i % 4) * 15))
                if dt >= start_slot: all_prices.append({'price': float(p['total']), 'time_dt': dt})
        if prices_tmrw:
            for i, p in enumerate(prices_tmrw):
                dt = datetime.combine(now_dt.date() + timedelta(days=1), time(i // 4, (i % 4) * 15))
                all_prices.append({'price': float(p['total']), 'time_dt': dt})

        if SIMULATE_SUNDAY_NIGHT and all_prices: all_prices[0]['price'] = -99.99 

        if not all_prices:
            self._set_error_states('ERROR_NO_PRICE_DATA')
            return

        cur_price = all_prices[0]['price']
        max_future_price = max([x['price'] for x in all_prices])
        peak_time_slot = max(all_prices, key=lambda x: x['price'])['time_dt']
        cur_spread = max_future_price - cur_price
        
        eff_spread = self.base_min_price_spread_eur
        if cur_soc > self.soc_threshold_high: eff_spread = max(eff_spread, self.spread_high_soc_eur)
        elif cur_soc > self.soc_threshold_medium: eff_spread = max(eff_spread, self.spread_medium_soc_eur)
        
        min_interim = 9.99
        interim_dip = False
        if peak_time_slot > now_dt:
             for item in all_prices:
                 if item['time_dt'] > now_dt and item['time_dt'] < peak_time_slot:
                     if item['price'] < min_interim: min_interim = item['price']
             refill_profit = cur_price - (min_interim / self.efficiency_factor)
             if refill_profit > self.min_cycle_profit_eur: interim_dip = True

        should_hold = (cur_spread >= eff_spread) and (not interim_dip)

        effective_min_soc = base_min_soc
        if prices_tmrw and now_dt.hour >= 18:
            morning_peak_price = 0.0
            for item in all_prices:
                if item['time_dt'].date() == (today_date + timedelta(days=1)) and 5 <= item['time_dt'].hour <= 9:
                    if item['price'] > morning_peak_price: morning_peak_price = item['price']
            if (morning_peak_price - cur_price) > self.morning_min_diff:
                effective_min_soc = max(base_min_soc, self.sleep_over_soc)

        deadline = peak_time_slot if max_future_price > price_discharge_limit else datetime.combine(today_date, time(23, 59))
        is_morning_peak = deadline.hour < 10
        pv_dominant = (fc_next >= pv_fc_thresh) or (cur_pv >= cur_pv_thresh) or (fc_now >= pv_fc_thresh)
        
        pool = [x for x in all_prices if x['time_dt'] < deadline and x['time_dt'] >= start_slot]
        need_soc_kwh = max(0.0, (target_soc - cur_soc) / 100 * batt_cap)
        final_slots = min(int(math.ceil((need_soc_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0, user_intervals)
        needed_kwh = need_soc_kwh
        
        if final_slots > 0 and pool:
            try:
                sorted_pool = sorted(pool, key=lambda x: x['price'])
                if len(sorted_pool) >= final_slots:
                    best_slots = sorted_pool[:final_slots]
                    best_slots.sort(key=lambda x: x['time_dt'])
                    time_until = (best_slots[0]['time_dt'] - now_dt).total_seconds() / 3600
                    calc_load = self._get_float_state(self.avg_consumption_sensor_id, default=500.0)
                    if time_until <= 1.0: calc_load = (cur_house * 0.7) + (calc_load * 0.3) 
                    pred_load_kwh = (max(200.0, min(1500.0, calc_load)) / 1000) * max(0, time_until)
                    pred_pv_kwh = 0 if is_morning_peak or fc_next < 0.1 else fc_rem * self.pv_forecast_safety_factor
                    total_need = max(0.0, min(need_soc_kwh + pred_load_kwh - pred_pv_kwh, batt_cap))
                    final_slots = min(int(math.ceil((total_need / charge_pwr) * 4)) if charge_pwr > 0 else 0, user_intervals)
                    needed_kwh = total_need
            except: pass

        if pool and final_slots > 0:
            best_slots = sorted(pool, key=lambda x: x['price'])[:final_slots]
            best_slots.sort(key=lambda x: x['time_dt'])
            if best_slots:
                avg_price_slots = sum(i['price'] for i in best_slots) / len(best_slots)
                cheap_hours_info = f"{len(best_slots)}x 15min ({best_slots[0]['time_dt'].strftime('%H:%M')}...{(best_slots[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')}) Ø {avg_price_slots:.3f} €"
                if any(s['time_dt'] == start_slot for s in best_slots): current_time_in_best_block = True
                if self.next_charge_time_id: self.set_state(self.next_charge_time_id, state=best_slots[0]['time_dt'].strftime('%H:%M'))
        elif self.next_charge_time_id:
            self.set_state(self.next_charge_time_id, state="--:--")
            
        panic_mode = ((deadline - now_dt).total_seconds() / 3600 < 1.5) and (cur_price <= price_discharge_limit) and (needed_kwh > 0)

        weather_factor = 0.5
        try:
            cloud_val = 1.0 - (float(self.get_state(self.cloud_coverage_sensor_id)) / 100.0) if self.cloud_coverage_sensor_id else None
            if cloud_val is not None: weather_factor = max(0.0, min(1.0, cloud_val))
            elif self.weather_sensor_id: weather_factor = WEATHER_PV_FACTOR.get(self.get_state(self.weather_sensor_id), 0.5)
        except: pass
        
        is_daylight = float(self.get_state(self.sun_sensor_id, attribute='elevation', default=0)) > 0 
        approaching_peak = peak_dt and (-30 < (peak_dt - now_aware).total_seconds() / 60 < 90)
        is_sun_shining = cur_pv > 50 or (is_daylight and weather_factor >= 0.4 and (fc_next > 0.1 or fc_now >= pv_fc_thresh)) or approaching_peak

        # ==========================================================
        # 🚗 EV PLANNING (Berechnet nur bis zum Grid-Target)
        # ==========================================================
        ev_is_cheap_now = False
        ev_plan_text = self.T['STATUS_EV_PLAN_NONE']
        
        if self.ev_logic_active_id and self.get_state(self.ev_logic_active_id) == 'on':
            if ev_current_soc < ev_grid_target:
                if self.get_state(self.ev_boost_switch_id) == 'on':
                    ev_is_cheap_now = True
                    ev_plan_text = self.T['STATUS_EV_PLAN_BOOST'].format(target=ev_grid_target)
                else:
                    dl = now_dt.replace(hour=dl_hour if is_mon_sec else 7, minute=dl_minute if is_mon_sec else 0, second=0, microsecond=0)
                    if now_dt >= dl: dl += timedelta(days=1)
                    
                    if now_dt.weekday() == 6 and is_mon_sec: 
                        dl = (now_dt + timedelta(days=1)).replace(hour=dl_hour, minute=dl_minute, second=0, microsecond=0)
                        
                    needed_s = int(math.ceil((((ev_grid_target - ev_current_soc) / 100 * ev_cap) / 0.90) / ev_pwr * 4))
                    pool = [x for x in all_prices if start_slot <= x['time_dt'] < dl]
                    
                    if pool and needed_s > 0:
                        best = sorted(pool, key=lambda x: x['price'])[:needed_s]
                        best.sort(key=lambda x: x['time_dt'])
                        if is_mon_sec:
                            ev_plan_text = f"Pendler-Ladung ({int(ev_grid_target)}%): {best[0]['time_dt'].strftime('%H:%M')} - {(best[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')}"
                        else:
                            ev_plan_text = self.T['STATUS_EV_PLAN_ACTIVE'].format(start=best[0]['time_dt'].strftime('%H:%M'), end=(best[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M'), slots=len(best))
                        if any(s['time_dt'] == start_slot for s in best): ev_is_cheap_now = True
                    if cur_price <= float(self.args.get('ev_immediate_charge_price', 0.20)): ev_is_cheap_now = True

        if self.ev_charge_plan_id: self.set_state(self.ev_charge_plan_id, state=ev_plan_text)

        # ==========================================================
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 1. WALLBOX DELEGATION
        # ==========================================================
        if not is_manual_override:
            if ev_is_cheap_now:
                self._set_wallbox_logic_mode("Default")
                self._set_wallbox_state("On")
            elif car_is_full:
                self._set_wallbox_logic_mode("Eco")
                self._set_wallbox_state("Off")
            elif pv_dominant and cur_soc >= self.home_battery_priority_soc:
                self._set_wallbox_logic_mode("Eco")
                self._set_wallbox_state("Neutral")
            else:
                self._set_wallbox_logic_mode("Eco")
                self._set_wallbox_state("Neutral")

        # ==========================================================
        # ⚖️ ENTSCHEIDUNGS-MATRIX: 2. HAUSAKKU (AppDaemon Master)
        # ==========================================================
        if ev_is_cheap_now:
            self._set_inverter_mode(self.mode_backup)
            charge_toggle_on = False
            if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=self.T['STATUS_CHARGE_NET'])
            
        elif app_is_enabled and ((cur_price > price_discharge_limit and not should_hold) or interim_dip):
            if cur_soc > effective_min_soc:
                if ev_active or is_manual_override:
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state="EV lädt (Hausakku Standby)")
                else:
                    if cur_batt_pwr > 50: is_discharge_active = True
                    status_msg = f"{self.T['STATUS_DISCHARGE_DIP']}" if interim_dip else f"{self.T['STATUS_DISCHARGE_BASE']}"
                    if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=status_msg)
                    self._set_inverter_mode(self.mode_general)
            else:
                status_msg = f"{self.T['STATUS_DISCHARGE_RESERVE_REACHED']} ({effective_min_soc}%)."
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=status_msg)
                self._set_inverter_mode(self.mode_general)

        elif app_is_enabled and cur_soc < target_soc and (panic_mode or (current_time_in_best_block and not is_sun_shining)):
            is_dip = (cur_spread >= self.base_min_price_spread_eur)
            allow = (current_time_in_best_block or panic_mode) if (current_time_in_best_block or panic_mode) else ((cur_price <= price_discharge_limit) or is_dip)
            
            if allow:
                charge_toggle_on = True
                self._set_inverter_mode(self.mode_charge)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_ACTIVE']}: {cheap_hours_info}")
            else:
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_CHARGE_BLOCKED']} ({cur_price:.3f}€).")

        elif pv_dominant:
            if cur_soc < self.home_battery_priority_soc:
                self._set_inverter_mode(self.mode_general)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=f"PV: Hausakku Prio (<{self.home_battery_priority_soc}%)")
            else:
                if ev_active and cur_batt_pwr > 500:
                    self._set_inverter_mode(self.mode_backup)
                    if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state="EV lädt PV (Akku Standby)")
                else:
                    self._set_inverter_mode(self.mode_general)
                    if cur_batt_pwr < -100: 
                        is_pv_charge_active = True
                        charge_toggle_on = True
                        if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=f"{self.T['STATUS_PV_CHARGING']}.")
                    else:
                        if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=self.T['STATUS_EV_PV'])

        elif needed_kwh == 0 and cur_soc >= target_soc:
            charge_toggle_on = False
            if ev_active or is_manual_override:
                self._set_inverter_mode(self.mode_backup)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state="EV Schutz aktiv: Hausakku Standby.")
            else:
                tgt_mode = self.mode_general if is_sun_shining else self.mode_backup
                self._set_inverter_mode(tgt_mode)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=self.T['STATUS_TARGET_REACHED'])

        else:
            charge_toggle_on = False
            if ev_active or is_manual_override:
                self._set_inverter_mode(self.mode_backup)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state="EV lädt (Standby).")
            else:
                tgt_mode = self.mode_backup
                info = self.T['STATUS_WAIT_HOLD']
                if is_sun_shining:
                    tgt_mode = self.mode_general
                    info = self.T['STATUS_WAIT_PV']
                elif not should_hold:
                    tgt_mode = self.mode_general
                    info = self.T['STATUS_IDLE']

                self._set_inverter_mode(tgt_mode)
                if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=f"{info} ({tgt_mode}).")

        # Toggles Schalten
        if hasattr(self, 'cheap_hour_toggle_id') and self.cheap_hour_toggle_id:
            if charge_toggle_on: self.turn_on(self.cheap_hour_toggle_id)
            else: self.turn_off(self.cheap_hour_toggle_id)
        if self.cheap_hours_text_id: self.set_state(self.cheap_hours_text_id, state=cheap_hours_info)

        # --- STATS UPDATES ---
        if (charge_toggle_on or is_pv_charge_active) and not self.charging_session_active:
            self.charging_session_active = True
            self.charging_session_start_time = self.datetime()
            self.charging_session_net_charged_kwh = 0.0
        if self.charging_session_active:
            if cur_grid > 50:
                kwh_min = (abs(cur_grid) / 1000) / 60
                self.charging_session_net_charged_kwh += kwh_min
                cp = avg_price_slots if cheap_slots_found else (all_prices[0]['price'] if all_prices else 0.0)
                self._update_charge_cost_stats(kwh_min, cp)
        if self.charging_session_active and not (charge_toggle_on or is_pv_charge_active):
            self.charging_session_active = False
            self.charging_session_net_charged_kwh = 0.0
        if is_discharge_active and cur_batt_pwr > 50:
            if not self.discharging_active: self.discharging_active = True
            self._update_discharge_saving_stats((abs(cur_batt_pwr) / 1000) / 60, cur_price)
        elif self.discharging_active:
            self.discharging_active = False
        if cur_pv > 0 and cur_house > 0:
            self._update_pv_direct_stats((min(cur_pv, cur_house) / 1000) / 60, cur_price)

    def check_wallbox_disconnect(self, entity, attribute, old, new, kwargs):
        disconnect_states = ("unplugged", "nicht verbunden", "disconnected", "kabel entfernt")
        if new and new.lower() in disconnect_states and old and old.lower() not in disconnect_states:
            self._set_wallbox_state("Off")
            if getattr(self, 'ev_pv_surplus_switch_id', None): self.turn_off(self.ev_pv_surplus_switch_id)
            self.log("REFLEX: Auto physisch abgesteckt. Wallbox OFF.", level="INFO")

    # ==============================================================================
    # 🤖 FÜGE HIER DEIN KI-MODUL EIN
    # ==============================================================================
    def check_weekly_ai_trigger(self, kwargs): pass
    def trigger_ai_analysis(self, e, a, o, n, k): pass
    def _perform_gemini_analysis(self, k): pass

    def terminate(self):
        self.log(f"INFO: {self.T['INFO_APP_TERMINATED']}", level="INFO")
