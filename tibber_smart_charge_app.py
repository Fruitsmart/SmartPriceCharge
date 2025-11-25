# -*- coding: utf-8 -*-
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta, time
import math

class TibberSmartCharge(hass.Hass):

    def initialize(self):
        self.log("Initializing TibberSmartCharge App - Version 1.1b (Configurable Dynamic Spread)...", level="INFO")

        # --- 1. KONFIGURATION: IDs ---
        self.tibber_price_sensor_id = self.args['tibber_price_sensor_id']
        self.current_soc_sensor_id = self.args['current_soc_sensor_id']
        self.goodwe_operation_mode_entity_id = self.args['goodwe_operation_mode_entity_id']
        
        # --- PV SENSOREN ---
        self.pv_forecast_next_hour_id = self.args['pv_forecast_sensor_id'] 
        self.pv_forecast_current_hour_id = self.args['pv_forecast_current_hour_sensor_id']
        self.pv_forecast_today_remaining_id = self.args['pv_forecast_today_remaining_sensor_id']
        self.pv_peak_time_sensor_id = self.args.get('pv_peak_time_sensor_id', None)

        # Live Werte
        self.current_pv_power_sensor_id = self.args['current_pv_power_sensor_id']
        self.battery_power_sensor_id = self.args['battery_power_sensor_id']
        self.grid_power_import_export_sensor_id = self.args['grid_power_import_export_sensor_id']
        self.current_house_consumption_w_id = self.args.get('current_house_consumption_w_id', None)

        # Helfer IDs
        self.battery_capacity_kwh_id = self.args['battery_capacity_kwh_id']
        self.charger_power_kw_id = self.args['charger_power_kw_id']
        self.ladeziel_soc_prozent_id = self.args['ladeziel_soc_prozent_id']
        self.pv_forecast_threshold_kw_id = self.args['pv_forecast_threshold_kw_id']
        self.current_pv_threshold_w_id = self.args['current_pv_threshold_w_id']
        self.tibber_discharge_threshold_eur_per_kwh_id = self.args['tibber_discharge_threshold_eur_per_kwh_id']
        self.min_soc_for_discharge_prozent_id = self.args['min_soc_for_discharge_prozent_id']
        self.referenz_strompreis_id = self.args['referenz_strompreis_id']
        self.charge_intervals_input_id = self.args.get('charge_intervals_input_id', 'input_number.anzahl_guenstigste_ladestunden')

        # --- FAKTOREN & EINSTELLUNGEN ---
        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.50))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.efficiency_factor = float(self.args.get('battery_efficiency_factor', 0.90))

        # DYNAMIC SPREAD KONFIGURATION (Neu in v1.1b)
        # Basis Spread (für SoC < Medium)
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.08))
        
        # Medium SoC Stufe (Standard: ab 80% SoC -> 0.15€ Spread)
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 80.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        
        # High SoC Stufe (Standard: ab 95% SoC -> 0.25€ Spread)
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 95.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        
        # Modi
        self.goodwe_charge_mode_option = self.args.get('goodwe_charge_mode_option', 'eco_charge')
        self.goodwe_general_mode_option = self.args.get('goodwe_general_mode_option', 'general')
        self.goodwe_backup_mode_option = self.args.get('goodwe_backup_mode_option', 'backup')

        # Dashboard & Status IDs
        self.dashboard_status_text_id = self.args.get('dashboard_status_text_id', 'input_text.tibber_smart_charge_status')
        self.app_enabled_switch_id = self.args.get('app_enabled_switch_id', 'input_boolean.tibber_smart_charge_app_aktiv')
        self.cheap_hour_toggle_id = self.args.get('cheap_hour_toggle_id', 'input_boolean.tibber_guenstige_ladestunde')
        self.next_charge_time_id = self.args.get('next_charge_time_id', 'input_text.tibber_next_charge_time')
        self.cheap_hours_text_id = self.args.get('cheap_hours_text_id', 'input_text.gunstigsten_ladestunden')
        self.monatsbericht_id = self.args.get('monatsbericht_id', 'input_text.tibber_smart_charge_monatsbericht')
        
        # Tracking IDs
        self.kosten_monat_id = self.args.get('kosten_monat_id', 'input_number.tibber_smart_charge_kosten_monat')
        self.ersparnis_monat_id = self.args.get('ersparnis_monat_id', 'input_number.tibber_smart_charge_ersparnis_monat')
        self.discharge_ersparnis_monat_id = self.args.get('discharge_ersparnis_monat_id', 'input_number.tibber_smart_discharge_ersparnis_monat')
        self.geladene_kwh_monat_id = self.args.get('geladene_kwh_monat_id', 'input_number.tibber_smart_charge_geladene_kwh_monat')
        self.pv_savings_monat_id = self.args.get('pv_savings_monat_id', 'input_number.tibber_smart_pv_savings_monat')
        self.kosten_gesamt_id = self.args.get('kosten_gesamt_id', 'input_number.tibber_smart_charge_kosten_gesamt')
        self.ersparnis_gesamt_id = self.args.get('ersparnis_gesamt_id', 'input_number.tibber_charge_ersparnis_lifetime_final')
        self.discharge_ersparnis_gesamt_id = self.args.get('discharge_ersparnis_gesamt_id', 'input_number.tibber_smart_discharge_ersparnis_gesamt')
        self.geladene_kwh_gesamt_id = self.args.get('geladene_kwh_gesamt_id', 'input_number.tibber_smart_charge_geladene_kwh_gesamt')
        self.pv_savings_gesamt_id = self.args.get('pv_savings_gesamt_id', 'input_number.tibber_smart_pv_savings_gesamt')

        # Debug Settings
        self.debug_mode = self.args.get('debug_mode', False)
        self.log_debug_level = self.args.get('log_debug_level', False)

        # Interne Variablen
        self.charging_session_active = False
        self.charging_session_start_time = None
        self.charging_session_net_charged_kwh = 0.0
        self.discharging_active = False
        self.last_inverter_mode_command_time = None
        
        if not all([self.tibber_price_sensor_id, self.current_soc_sensor_id, self.goodwe_operation_mode_entity_id]):
            self.log("ERROR: Wichtige IDs fehlen!", level="ERROR")
            return

        initial_run_time = self.datetime().replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, initial_run_time, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))

    # --- HILFSFUNKTIONEN ---
    
    def _log_debug(self, message, level="INFO"):
        if level == "DEBUG":
            if self.log_debug_level: self.log(message, level="INFO")
            else: self.log(message, level="DEBUG")
        elif level == "INFO": self.log(message, level="INFO")
        elif level in ["WARNING", "ERROR"]: self.log(message, level=level)

    def _get_float_state(self, entity_id, attribute=None, default=0.0):
        if entity_id is None: return default
        try:
            state = self.get_state(entity_id, attribute=attribute)
            if state is not None and state not in ['unavailable', 'unknown', 'none', 'None']:
                return float(state)
        except (ValueError, TypeError): pass
        return default
    
    def _get_tracking_state(self, entity_id):
        return self._get_float_state(entity_id, default=0.0)
    
    def _set_tracking_state(self, entity_id, value, decimals=6):
        try:
            self.set_state(entity_id, state=round(value, decimals))
        except Exception as e:
            self.log(f"WARNING: Could not update tracking state for {entity_id}: {e}", level="WARNING")

    def _set_error_states(self, message):
        self.set_state(self.dashboard_status_text_id, state=message)
        self.turn_off(self.cheap_hour_toggle_id)

    def _set_inverter_mode(self, target_mode):
        current_mode = self.get_state(self.goodwe_operation_mode_entity_id)
        now = self.get_now()
        
        needs_heartbeat = False
        if self.last_inverter_mode_command_time:
            diff = (now - self.last_inverter_mode_command_time).total_seconds() / 60
            if diff > 15: needs_heartbeat = True
        else: needs_heartbeat = True 
            
        should_send = False
        reason = ""

        if current_mode != target_mode:
            should_send = True
            reason = "Modus-Änderung nötig"
        elif needs_heartbeat:
            should_send = True
            reason = "Safety Heartbeat"
        
        if should_send:
            if not self.debug_mode:
                self.log(f"ACTION: Sende Modus '{target_mode}' ({reason}).", level="INFO")
                self.call_service("select/select_option", entity_id=self.goodwe_operation_mode_entity_id, option=target_mode)
            else:
                self.log(f"DEBUG-MODE: Würde '{target_mode}' senden ({reason}).", level="INFO")
            self.last_inverter_mode_command_time = now
        else:
            self._log_debug(f"Smart-Mode: Modus '{target_mode}' passt (Sync OK).", level="DEBUG")

    # --- TRACKING FUNKTIONEN ---
    def _update_charge_cost_stats(self, net_charged_kwh, avg_charge_price):
        if net_charged_kwh <= 0: return
        referenz_preis = self._get_float_state(self.referenz_strompreis_id, default=0.35)
        kosten = net_charged_kwh * avg_charge_price
        ersparnis = net_charged_kwh * (referenz_preis - avg_charge_price)
        c_k = self._get_tracking_state(self.kosten_monat_id)
        c_e = self._get_tracking_state(self.ersparnis_monat_id)
        c_kg = self._get_tracking_state(self.kosten_gesamt_id)
        c_eg = self._get_tracking_state(self.ersparnis_gesamt_id)
        c_km = self._get_tracking_state(self.geladene_kwh_monat_id)
        c_kg_kwh = self._get_tracking_state(self.geladene_kwh_gesamt_id)
        self._set_tracking_state(self.kosten_monat_id, c_k + kosten)
        self._set_tracking_state(self.ersparnis_monat_id, c_e + ersparnis)
        self._set_tracking_state(self.kosten_gesamt_id, c_kg + kosten)
        self._set_tracking_state(self.ersparnis_gesamt_id, c_eg + ersparnis)
        self._set_tracking_state(self.geladene_kwh_monat_id, c_km + net_charged_kwh, decimals=4)
        self._set_tracking_state(self.geladene_kwh_gesamt_id, c_kg_kwh + net_charged_kwh, decimals=4)
        self._update_monthly_report()

    def _update_discharge_saving_stats(self, discharged_kwh_dc, current_spot_price):
        if discharged_kwh_dc <= 0: return
        discharged_kwh_ac = discharged_kwh_dc * self.efficiency_factor
        ersparnis = discharged_kwh_ac * current_spot_price
        c_dis_m = self._get_tracking_state(self.discharge_ersparnis_monat_id)
        c_dis_g = self._get_tracking_state(self.discharge_ersparnis_gesamt_id)
        self._set_tracking_state(self.discharge_ersparnis_monat_id, c_dis_m + ersparnis)
        self._set_tracking_state(self.discharge_ersparnis_gesamt_id, c_dis_g + ersparnis)
        self._update_monthly_report()

    def _update_pv_direct_stats(self, direct_pv_kwh, current_spot_price):
        if direct_pv_kwh <= 0: return
        ersparnis = direct_pv_kwh * current_spot_price
        c_pv_m = self._get_tracking_state(self.pv_savings_monat_id)
        c_pv_g = self._get_tracking_state(self.pv_savings_gesamt_id)
        self._set_tracking_state(self.pv_savings_monat_id, c_pv_m + ersparnis)
        self._set_tracking_state(self.pv_savings_gesamt_id, c_pv_g + ersparnis)

    def reset_monthly_stats_daily_check(self, kwargs):
        now = self.datetime()
        try: last_reset_str = self.get_state(self.monatsbericht_id, attribute='last_reset_date')
        except: last_reset_str = None
        should_reset = True
        if last_reset_str:
            try:
                last_reset_date = datetime.strptime(last_reset_str, '%Y-%m-%d').date()
                if last_reset_date.month == now.month and last_reset_date.year == now.year: should_reset = False
            except: should_reset = True
        if should_reset:
            self._set_tracking_state(self.pv_savings_monat_id, 0.0)
            self._set_tracking_state(self.kosten_monat_id, 0.0)
            self._set_tracking_state(self.ersparnis_monat_id, 0.0)
            self._set_tracking_state(self.discharge_ersparnis_monat_id, 0.0)
            self._set_tracking_state(self.geladene_kwh_monat_id, 0.0, decimals=4)
            try:
                attr = self.get_state(self.monatsbericht_id, attribute='all')['attributes']
                attr['last_reset_date'] = now.strftime('%Y-%m-%d')
                self.set_state(self.monatsbericht_id, state=self.get_state(self.monatsbericht_id), attributes=attr)
            except: pass
            self.log("INFO: Monatsreset durchgeführt.", level="INFO")
        self._update_monthly_report()

    def _update_monthly_report(self):
        try:
            c_kosten = self._get_tracking_state(self.kosten_monat_id)
            c_ersparnis = self._get_tracking_state(self.ersparnis_monat_id)
            c_dis_ersparnis = self._get_tracking_state(self.discharge_ersparnis_monat_id)
            c_kwh = self._get_tracking_state(self.geladene_kwh_monat_id)
            c_pv = self._get_tracking_state(self.pv_savings_monat_id)
            report_name = self.datetime().strftime('%B %Y')
            report_text = f"Monat ({report_name}):\nKosten (Netz): {c_kosten:.2f} EUR\nErsparnis (Laden): {c_ersparnis:.2f} EUR\nErsparnis (Entladen): {c_dis_ersparnis:.2f} EUR\nErsparnis (PV-Direkt): {c_pv:.2f} EUR\nGeladen: {c_kwh:.2f} kWh"
            try: attr = self.get_state(self.monatsbericht_id, attribute='all')['attributes']
            except: attr = {'icon': 'mdi:file-chart'}
            self.set_state(self.monatsbericht_id, state=report_text, attributes=attr)
        except: pass

    # --- HAUPTLOGIK ---
    def main_logic(self, kwargs):
        # Init
        cheap_slots_found = []
        avg_price_slots = 0.0
        is_pv_charge_active = False
        charge_toggle_on = False
        is_discharge_active = False
        current_time_in_best_block = False
        cheap_hours_info = "Keine Zeit gefunden."

        app_is_enabled = self.get_state(self.app_enabled_switch_id) == 'on'
        current_goodwe_mode = self.get_state(self.goodwe_operation_mode_entity_id)
        
        # Werte holen
        battery_capacity_kwh = self._get_float_state(self.battery_capacity_kwh_id, default=5.0) 
        charger_power_kw = self._get_float_state(self.charger_power_kw_id, default=3.0) 
        ladeziel_soc_prozent = self._get_float_state(self.ladeziel_soc_prozent_id, default=100.0)
        pv_forecast_threshold_kw = self._get_float_state(self.pv_forecast_threshold_kw_id, default=1.0)
        current_pv_threshold_w = self._get_float_state(self.current_pv_threshold_w_id, default=500.0)
        tibber_entladeschwelle_eur_per_kwh = self._get_float_state(self.tibber_discharge_threshold_eur_per_kwh_id, default=0.30)
        dod_value = self._get_float_state(self.min_soc_for_discharge_prozent_id, default=20.0)
        min_soc_for_discharge_prozent = 100.0 - dod_value 
        user_defined_intervals = int(self._get_float_state(self.charge_intervals_input_id, default=16.0))
        
        # Sensoren
        current_soc_prozent = self._get_float_state(self.current_soc_sensor_id)
        current_pv_power_w = self._get_float_state(self.current_pv_power_sensor_id)
        current_battery_power_w = self._get_float_state(self.battery_power_sensor_id)
        current_grid_power_w = self._get_float_state(self.grid_power_import_export_sensor_id)
        current_house_consumption_w = self._get_float_state(self.current_house_consumption_w_id)
        
        # 4 Forecast Werte
        pv_forecast_remaining_kwh = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        pv_forecast_next_hour_kw = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        pv_forecast_current_hour_kw = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        
        pv_peak_time_dt = None
        if self.pv_peak_time_sensor_id:
            state_str = self.get_state(self.pv_peak_time_sensor_id)
            if state_str and state_str not in ['unavailable', 'unknown']:
                try: pv_peak_time_dt = datetime.fromisoformat(state_str)
                except: pass
        
        self._log_debug(f"SoC:{current_soc_prozent:.1f}% | PV:{current_pv_power_w:.0f}W | FC-Now:{pv_forecast_current_hour_kw:.2f}", level="DEBUG")

        # --- PREIS DATEN ---
        today_prices_raw = self.get_state(self.tibber_price_sensor_id, attribute='today')
        tomorrow_prices_raw = self.get_state(self.tibber_price_sensor_id, attribute='tomorrow')

        if not today_prices_raw:
            self._set_error_states('N/A - Keine Preisdaten')
            return
        
        all_15min_prices = []
        now_dt = self.get_now().replace(second=0, microsecond=0, tzinfo=None)
        now_aware = self.get_now()
        current_15min_start_dt = now_dt - timedelta(minutes=now_dt.minute % 15)
        today_date = now_dt.date()
        
        for i, p in enumerate(today_prices_raw):
            if isinstance(p, dict) and 'total' in p:
                price_dt = datetime.combine(today_date, time(i // 4, (i % 4) * 15))
                if price_dt >= current_15min_start_dt: all_15min_prices.append({'price': float(p['total']), 'time_dt': price_dt})

        if tomorrow_prices_raw:
            tomorrow_date = (now_dt + timedelta(days=1)).date()
            for i, p in enumerate(tomorrow_prices_raw):
                if isinstance(p, dict) and 'total' in p:
                    price_dt = datetime.combine(tomorrow_date, time(i // 4, (i % 4) * 15))
                    all_15min_prices.append({'price': float(p['total']), 'time_dt': price_dt})

        if not all_15min_prices:
             self._set_error_states('N/A - Keine Intervalle')
             return
        
        # --- PREISANALYSE (Dynamischer Spread v1.1b) ---
        max_future_price = 0.0
        peak_time_dt = None
        if all_15min_prices:
             max_price_item = max(all_15min_prices, key=lambda x: x['price'])
             max_future_price = max_price_item['price']
             peak_time_dt = max_price_item['time_dt']
        
        current_tibber_price = all_15min_prices[0]['price'] if all_15min_prices else 0.0
        current_spread = max_future_price - current_tibber_price
        
        # DYNAMIC SPREAD LOGIK (Konfigurierbar)
        effective_min_spread = self.base_min_price_spread_eur
        
        if current_soc_prozent > self.soc_threshold_high:
            effective_min_spread = max(effective_min_spread, self.spread_high_soc_eur)
            self._log_debug(f"DynSpread: SoC > {self.soc_threshold_high}% -> Spread {effective_min_spread:.2f}", level="DEBUG")
        elif current_soc_prozent > self.soc_threshold_medium:
            effective_min_spread = max(effective_min_spread, self.spread_medium_soc_eur)
            self._log_debug(f"DynSpread: SoC > {self.soc_threshold_medium}% -> Spread {effective_min_spread:.2f}", level="DEBUG")
        
        min_interim_price = 9.99
        interim_dip_found = False
        if peak_time_dt and peak_time_dt > now_dt:
             for item in all_15min_prices:
                 if item['time_dt'] > now_dt and item['time_dt'] < peak_time_dt:
                     if item['price'] < min_interim_price: min_interim_price = item['price']
             refill_profit = current_tibber_price - (min_interim_price / self.efficiency_factor)
             if refill_profit > self.min_cycle_profit_eur: interim_dip_found = True

        # Nutzung des effektiven Spreads
        should_hold_for_peak = (current_spread >= effective_min_spread) and (not interim_dip_found)
        
        if should_hold_for_peak:
             self._log_debug(f"Hold aktiv! Spread {current_spread:.3f} >= {effective_min_spread:.3f}", level="DEBUG")

        # --- BEDARFS-BERECHNUNG ---
        deadline_dt = peak_time_dt if max_future_price > tibber_entladeschwelle_eur_per_kwh else datetime.combine(today_date, time(23, 59))
        is_morning_peak = deadline_dt.hour < 10
        
        pv_forecast_strong_enough = pv_forecast_next_hour_kw >= pv_forecast_threshold_kw
        current_pv_strong_enough = current_pv_power_w >= current_pv_threshold_w
        current_hour_forecast_strong_enough = pv_forecast_current_hour_kw >= pv_forecast_threshold_kw
        is_pv_dominant = pv_forecast_strong_enough or current_pv_strong_enough or current_hour_forecast_strong_enough

        pool_to_search = [x for x in all_15min_prices if x['time_dt'] < deadline_dt and x['time_dt'] >= current_15min_start_dt]
        needed_kwh_soc = max(0.0, (ladeziel_soc_prozent - current_soc_prozent) / 100 * battery_capacity_kwh)
        
        required_15min_intervals_initial = int(math.ceil((needed_kwh_soc / charger_power_kw) * 4)) if charger_power_kw > 0 else 0
        charge_block_intervals_initial = min(required_15min_intervals_initial, user_defined_intervals)
        charge_block_intervals_initial = max(0, charge_block_intervals_initial)
        
        first_charge_slot_dt = deadline_dt
        if charge_block_intervals_initial > 0 and pool_to_search:
            sorted_by_price_initial = sorted(pool_to_search, key=lambda x: x['price'])
            if len(sorted_by_price_initial) >= charge_block_intervals_initial:
                cheapest_slots_initial = sorted_by_price_initial[:charge_block_intervals_initial]
                cheapest_slots_initial.sort(key=lambda x: x['time_dt'])
                first_charge_slot_dt = cheapest_slots_initial[0]['time_dt']
        
        try:
            time_until_charge = (first_charge_slot_dt - now_dt).total_seconds() / 3600
            assumed_load_w = current_house_consumption_w
            if assumed_load_w > 1000: assumed_load_w = 800 
            if assumed_load_w < 200: assumed_load_w = 300 
            avg_house_load_kw = assumed_load_w / 1000
            predicted_consumption_kwh = avg_house_load_kw * max(0, time_until_charge)
            
            if is_morning_peak or pv_forecast_next_hour_kw < 0.1: predicted_pv_kwh = 0
            else: predicted_pv_kwh = pv_forecast_remaining_kwh * self.pv_forecast_safety_factor
            
            needed_kwh_total = needed_kwh_soc + predicted_consumption_kwh - predicted_pv_kwh
            needed_kwh_total = max(0.0, needed_kwh_total)
            needed_kwh_total = min(needed_kwh_total, battery_capacity_kwh)
            
            required_charge_hours_total = needed_kwh_total / charger_power_kw if charger_power_kw > 0 else 0
            required_15min_intervals = int(math.ceil(required_charge_hours_total * 4))
            charge_block_intervals = min(required_15min_intervals, user_defined_intervals)
            charge_block_intervals = max(0, charge_block_intervals)
            needed_kwh = needed_kwh_total
        except Exception as e:
            self.log(f"ERROR bei Bedarfsberechnung: {e}", level="ERROR")
            needed_kwh = needed_kwh_soc
            charge_block_intervals = charge_block_intervals_initial

        # --- FINAL SLOTS ---
        if pool_to_search and charge_block_intervals > 0:
            sorted_by_price = sorted(pool_to_search, key=lambda x: x['price'])
            cheap_slots_found = sorted_by_price[:charge_block_intervals]
            cheap_slots_found.sort(key=lambda x: x['time_dt'])
            if cheap_slots_found:
                avg_price_slots = sum(i['price'] for i in cheap_slots_found) / len(cheap_slots_found)
            times_str = ", ".join([t['time_dt'].strftime('%H:%M') for t in cheap_slots_found])
            self._log_debug(f"Slots: {times_str} (Ø {avg_price_slots:.3f} EUR)", level="DEBUG")

        if cheap_slots_found and needed_kwh > 0:
            start_t = cheap_slots_found[0]['time_dt'].strftime('%H:%M')
            end_t = (cheap_slots_found[-1]['time_dt'] + timedelta(minutes=15)).strftime('%H:%M')
            cheap_hours_info = f"{len(cheap_slots_found)}x 15min ({start_t}...{end_t}) Ø {avg_price_slots:.3f} €"
            for slot in cheap_slots_found:
                if slot['time_dt'] == current_15min_start_dt:
                    current_time_in_best_block = True
                    break
        
        if self.next_charge_time_id and cheap_slots_found:
            self.set_state(self.next_charge_time_id, state=cheap_slots_found[0]['time_dt'].strftime('%H:%M'))
        elif self.next_charge_time_id:
            self.set_state(self.next_charge_time_id, state="--:--")
            
        # --- ENTSCHEIDUNG & AKTION ---
        time_until_deadline_panic = (deadline_dt - now_dt).total_seconds() / 3600
        is_panic_mode = (time_until_deadline_panic < 1.5) and (current_tibber_price <= tibber_entladeschwelle_eur_per_kwh) and (needed_kwh > 0)

        # PRIO 1: HOCHPREIS-ENTLADUNG
        if app_is_enabled and ((current_tibber_price > tibber_entladeschwelle_eur_per_kwh and not should_hold_for_peak) or interim_dip_found):
            if current_soc_prozent > min_soc_for_discharge_prozent:
                if current_battery_power_w > 50: is_discharge_active = True
                status_msg = f"Entladen (Eigenverbrauch)." if not interim_dip_found else f"Entladen (Dip-Refill)."
                self.set_state(self.dashboard_status_text_id, state=status_msg)
                self._set_inverter_mode(self.goodwe_general_mode_option)
            else:
                self.set_state(self.dashboard_status_text_id, state=f"Entladen bereit (Akku leer).")
                self._set_inverter_mode(self.goodwe_general_mode_option)

        # PRIO 2: GÜNSTIG LADEN
        elif app_is_enabled and current_soc_prozent < ladeziel_soc_prozent and (current_time_in_best_block or is_panic_mode):
            is_relative_dip = (current_spread >= self.base_min_price_spread_eur) # Basis Spread gilt hier
            if current_time_in_best_block or is_panic_mode: allowed_to_charge = True
            else: allowed_to_charge = (current_tibber_price <= tibber_entladeschwelle_eur_per_kwh) or is_relative_dip
            
            if allowed_to_charge:
                status_msg = f"Laden aktiv: {cheap_hours_info}"
                self.set_state(self.dashboard_status_text_id, state=status_msg)
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
                self._set_inverter_mode(self.goodwe_charge_mode_option)
            else:
                self.turn_on(self.cheap_hour_toggle_id)
                self.set_state(self.dashboard_status_text_id, state=f"Blockiert: Preis zu hoch ({current_tibber_price:.3f}€).")

        # PRIO 3: PV-OPTIMIERUNG
        elif current_goodwe_mode == self.goodwe_general_mode_option and is_pv_dominant and current_soc_prozent < 100:
            if current_battery_power_w < -100: 
                is_pv_charge_active = True
                self.set_state(self.dashboard_status_text_id, state=f"PV-Ladung aktiv.")
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
            elif current_goodwe_mode != self.goodwe_charge_mode_option:
                self._set_inverter_mode(self.goodwe_general_mode_option)

        # PRIO 4: IDLE / HOLD
        elif not is_pv_charge_active and not charge_toggle_on and not is_discharge_active:
            is_approaching_peak = False
            if pv_peak_time_dt:
                 diff_to_peak = (pv_peak_time_dt - now_aware).total_seconds() / 60
                 if diff_to_peak > -30 and diff_to_peak < 90: is_approaching_peak = True

            is_sun_shining = current_pv_power_w > 50 or pv_forecast_next_hour_kw > 0.1 or current_hour_forecast_strong_enough or is_approaching_peak
            
            target_mode = self.goodwe_backup_mode_option
            info_text = "Warten (Spread-Hold)"

            if is_sun_shining:
                target_mode = self.goodwe_general_mode_option
                info_text = "Warten (PV/Peak erwartet)"
            elif not should_hold_for_peak:
                target_mode = self.goodwe_general_mode_option
                info_text = "Standardbetrieb"

            self._set_inverter_mode(target_mode)
            self.set_state(self.dashboard_status_text_id, state=f"{info_text} ({target_mode}).")
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)

        # PRIO 5: ZIEL ERREICHT
        elif needed_kwh == 0 and current_soc_prozent >= ladeziel_soc_prozent:
            is_sun_shining = current_pv_power_w > 50 or pv_forecast_next_hour_kw > 0.1 or current_hour_forecast_strong_enough
            target_mode = self.goodwe_backup_mode_option
            if is_sun_shining: target_mode = self.goodwe_general_mode_option
            
            self._set_inverter_mode(target_mode)
            self.set_state(self.dashboard_status_text_id, state=f"Ziel erreicht.")
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)
        
        self.set_state(self.cheap_hours_text_id, state=cheap_hours_info)
        
        if (charge_toggle_on or is_pv_charge_active) and not self.charging_session_active:
            self.charging_session_active = True
            self.charging_session_start_time = self.datetime()
            self.charging_session_net_charged_kwh = 0.0
            self.log("INFO: Neue Lade-Session gestartet.", level="INFO")
        
        if self.charging_session_active:
            if current_grid_power_w < -50: 
                kwh_this_minute = (abs(current_grid_power_w) / 1000) / 60
                self.charging_session_net_charged_kwh += kwh_this_minute
                current_price = avg_price_slots if cheap_slots_found else (all_15min_prices[0]['price'] if all_15min_prices else 0.0)
                self._update_charge_cost_stats(kwh_this_minute, current_price)

        if self.charging_session_active and not (charge_toggle_on or is_pv_charge_active):
            self.log(f"INFO: Lade-Session beendet. Gesamt: {self.charging_session_net_charged_kwh:.3f} kWh.", level="INFO")
            self.charging_session_active = False
            self.charging_session_net_charged_kwh = 0.0

        if is_discharge_active and current_battery_power_w > 50:
            if not self.discharging_active:
                self.discharging_active = True
                self.log("INFO: Smart Discharge aktiv.", level="INFO")
            discharged_kwh_this_minute = (abs(current_battery_power_w) / 1000) / 60 
            current_tibber_price_eur_per_kwh = all_15min_prices[0]['price'] if all_15min_prices else 0.0
            self._update_discharge_saving_stats(discharged_kwh_this_minute, current_tibber_price_eur_per_kwh)
        elif self.discharging_active:
            self.discharging_active = False
            self.log("INFO: Smart Discharge beendet.", level="INFO")

        if current_pv_power_w > 0 and current_house_consumption_w > 0:
             direct_pv_w = min(current_pv_power_w, current_house_consumption_w)
             direct_pv_kwh = (direct_pv_w / 1000) / 60
             current_spot_price = all_15min_prices[0]['price'] if all_15min_prices else 0.0
             self._update_pv_direct_stats(direct_pv_kwh, current_spot_price)

    def terminate(self):
        self.log("INFO: App beendet.", level="INFO")
        self.turn_off(self.cheap_hour_toggle_id)
