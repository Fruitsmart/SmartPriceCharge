# -*- coding: utf-8 -*-
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta, time
import math

class SmartPriceCharge(hass.Hass):

    def initialize(self):
        self.log("Initializing SmartPriceCharge App - Version 1.2 (Rebranded)...", level="INFO")

        # --- 1. KONFIGURATION: IDs ---
        # Neutrale Bezeichnungen für die Argumente
        self.price_sensor_id = self.args['price_sensor_id']
        self.current_soc_sensor_id = self.args['current_soc_sensor_id']
        self.inverter_mode_entity_id = self.args['inverter_mode_entity_id']
        
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

        # Helfer IDs (Steuerung)
        self.battery_capacity_kwh_id = self.args['battery_capacity_kwh_id']
        self.charger_power_kw_id = self.args['charger_power_kw_id']
        self.target_soc_id = self.args['target_soc_id']
        self.pv_forecast_threshold_kw_id = self.args['pv_forecast_threshold_kw_id']
        self.current_pv_threshold_w_id = self.args['current_pv_threshold_w_id']
        self.price_discharge_threshold_id = self.args['price_discharge_threshold_id']
        self.min_soc_discharge_id = self.args['min_soc_discharge_id']
        self.reference_price_id = self.args['reference_price_id']
        self.charge_intervals_input_id = self.args.get('charge_intervals_input_id', 'input_number.anzahl_guenstigste_ladestunden')

        # --- FAKTOREN & EINSTELLUNGEN ---
        self.pv_forecast_safety_factor = float(self.args.get('pv_forecast_safety_factor', 0.50))
        self.min_cycle_profit_eur = float(self.args.get('min_cycle_profit_eur', 0.02))
        self.efficiency_factor = float(self.args.get('battery_efficiency_factor', 0.90))

        # DYNAMIC SPREAD KONFIGURATION
        self.base_min_price_spread_eur = float(self.args.get('min_price_spread_eur', 0.08))
        self.soc_threshold_medium = float(self.args.get('soc_threshold_medium', 80.0))
        self.spread_medium_soc_eur = float(self.args.get('spread_medium_soc_eur', 0.15))
        self.soc_threshold_high = float(self.args.get('soc_threshold_high', 95.0))
        self.spread_high_soc_eur = float(self.args.get('spread_high_soc_eur', 0.25))
        
        # Inverter Modi (Mapping)
        self.mode_charge = self.args.get('inverter_mode_charge', 'eco_charge')
        self.mode_general = self.args.get('inverter_mode_general', 'general')
        self.mode_backup = self.args.get('inverter_mode_backup', 'backup')

        # Dashboard & Status IDs
        self.dashboard_status_text_id = self.args.get('dashboard_status_text_id', 'input_text.smart_price_charge_status')
        self.app_enabled_switch_id = self.args.get('app_enabled_switch_id', 'input_boolean.smart_price_charge_aktiv')
        self.cheap_hour_toggle_id = self.args.get('cheap_hour_toggle_id', 'input_boolean.smart_price_charge_active_slot')
        self.next_charge_time_id = self.args.get('next_charge_time_id', 'input_text.smart_price_next_charge')
        self.cheap_hours_text_id = self.args.get('cheap_hours_text_id', 'input_text.smart_price_slots')
        self.report_id = self.args.get('report_id', 'input_text.smart_price_report')
        
        # Tracking IDs
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

        # Debug
        self.debug_mode = self.args.get('debug_mode', False)
        self.log_debug_level = self.args.get('log_debug_level', False)

        # Internals
        self.charging_session_active = False
        self.charging_session_net_charged_kwh = 0.0
        self.discharging_active = False
        self.last_inverter_mode_command_time = None
        
        # Check
        if not all([self.price_sensor_id, self.current_soc_sensor_id, self.inverter_mode_entity_id]):
            self.log("ERROR: Essential IDs missing in configuration!", level="ERROR")
            return

        initial_run_time = self.datetime().replace(second=0, microsecond=0) + timedelta(minutes=1)
        self.run_every(self.main_logic, initial_run_time, 60)
        self.run_daily(self.reset_monthly_stats_daily_check, time(0, 1, 0))

    # --- HELPERS ---
    
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
        if entity_id:
            try: self.set_state(entity_id, state=round(value, decimals))
            except Exception as e: self.log(f"WARNING: Tracking error {entity_id}: {e}", level="WARNING")

    def _set_error_states(self, message):
        if self.dashboard_status_text_id: self.set_state(self.dashboard_status_text_id, state=message)
        if self.cheap_hour_toggle_id: self.turn_off(self.cheap_hour_toggle_id)

    def _set_inverter_mode(self, target_mode):
        current_mode = self.get_state(self.inverter_mode_entity_id)
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
            reason = "Mode change required"
        elif needs_heartbeat:
            should_send = True
            reason = "Safety Heartbeat"
        
        if should_send:
            if not self.debug_mode:
                self.log(f"ACTION: Set Inverter Mode '{target_mode}' ({reason}).", level="INFO")
                self.call_service("select/select_option", entity_id=self.inverter_mode_entity_id, option=target_mode)
            else:
                self.log(f"DEBUG-MODE: Would set '{target_mode}' ({reason}).", level="INFO")
            self.last_inverter_mode_command_time = now
        else:
            self._log_debug(f"Inverter: Mode '{target_mode}' is correct (Sync OK).", level="DEBUG")

    # --- STATS TRACKING ---
    def _update_charge_cost_stats(self, net_charged_kwh, avg_charge_price):
        if net_charged_kwh <= 0: return
        ref_price = self._get_float_state(self.reference_price_id, default=0.35)
        cost = net_charged_kwh * avg_charge_price
        saving = net_charged_kwh * (ref_price - avg_charge_price)
        
        self._set_tracking_state(self.cost_month_id, self._get_tracking_state(self.cost_month_id) + cost)
        self._set_tracking_state(self.savings_month_id, self._get_tracking_state(self.savings_month_id) + saving)
        self._set_tracking_state(self.cost_total_id, self._get_tracking_state(self.cost_total_id) + cost)
        self._set_tracking_state(self.savings_total_id, self._get_tracking_state(self.savings_total_id) + saving)
        self._set_tracking_state(self.charged_kwh_month_id, self._get_tracking_state(self.charged_kwh_month_id) + net_charged_kwh, 4)
        self._set_tracking_state(self.charged_kwh_total_id, self._get_tracking_state(self.charged_kwh_total_id) + net_charged_kwh, 4)
        self._update_monthly_report()

    def _update_discharge_saving_stats(self, discharged_kwh_dc, current_price):
        if discharged_kwh_dc <= 0: return
        discharged_kwh_ac = discharged_kwh_dc * self.efficiency_factor
        saving = discharged_kwh_ac * current_price
        
        self._set_tracking_state(self.discharge_savings_month_id, self._get_tracking_state(self.discharge_savings_month_id) + saving)
        self._set_tracking_state(self.discharge_savings_total_id, self._get_tracking_state(self.discharge_savings_total_id) + saving)
        self._update_monthly_report()

    def _update_pv_direct_stats(self, direct_pv_kwh, current_price):
        if direct_pv_kwh <= 0: return
        saving = direct_pv_kwh * current_price
        self._set_tracking_state(self.pv_savings_month_id, self._get_tracking_state(self.pv_savings_month_id) + saving)
        self._set_tracking_state(self.pv_savings_total_id, self._get_tracking_state(self.pv_savings_total_id) + saving)

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
            report_text = f"Month ({report_name}):\nGrid Cost: {c_cost:.2f} EUR\nCharge Savings: {c_save:.2f} EUR\nDischarge Value: {c_dis:.2f} EUR\nPV Direct Value: {c_pv:.2f} EUR\nCharged: {c_kwh:.2f} kWh"
            try: attr = self.get_state(self.report_id, attribute='all')['attributes']
            except: attr = {'icon': 'mdi:file-chart'}
            self.set_state(self.report_id, state=report_text, attributes=attr)
        except: pass

    # --- LOGIC LOOP ---
    def main_logic(self, kwargs):
        # Init
        cheap_slots_found = []
        avg_price_slots = 0.0
        is_pv_charge_active = False
        charge_toggle_on = False
        is_discharge_active = False
        current_time_in_best_block = False
        cheap_hours_info = "No slots found."

        app_is_enabled = self.get_state(self.app_enabled_switch_id) == 'on'
        current_mode = self.get_state(self.inverter_mode_entity_id)
        
        # Get Config Values
        batt_cap = self._get_float_state(self.battery_capacity_kwh_id, default=5.0) 
        charge_pwr = self._get_float_state(self.charger_power_kw_id, default=3.0) 
        target_soc = self._get_float_state(self.target_soc_id, default=100.0)
        pv_fc_thresh = self._get_float_state(self.pv_forecast_threshold_kw_id, default=1.0)
        cur_pv_thresh = self._get_float_state(self.current_pv_threshold_w_id, default=500.0)
        price_discharge_limit = self._get_float_state(self.price_discharge_threshold_id, default=0.30)
        
        dod = self._get_float_state(self.min_soc_discharge_id, default=20.0)
        min_soc_discharge = 100.0 - dod 
        user_intervals = int(self._get_float_state(self.charge_intervals_input_id, default=16.0))
        
        # Get Sensor Values
        cur_soc = self._get_float_state(self.current_soc_sensor_id)
        cur_pv = self._get_float_state(self.current_pv_power_sensor_id)
        cur_batt_pwr = self._get_float_state(self.battery_power_sensor_id)
        cur_grid = self._get_float_state(self.grid_power_import_export_sensor_id)
        cur_house = self._get_float_state(self.current_house_consumption_w_id)
        
        # Forecasts
        fc_rem = self._get_float_state(self.pv_forecast_today_remaining_id, default=0.0)
        fc_next = self._get_float_state(self.pv_forecast_next_hour_id, default=0.0)
        fc_now = self._get_float_state(self.pv_forecast_current_hour_id, default=0.0)
        
        peak_dt = None
        if self.pv_peak_time_sensor_id:
            s = self.get_state(self.pv_peak_time_sensor_id)
            if s and s not in ['unavailable', 'unknown']:
                try: peak_dt = datetime.fromisoformat(s)
                except: pass
        
        self._log_debug(f"SoC:{cur_soc:.1f}% | PV:{cur_pv:.0f}W | FC-Now:{fc_now:.2f} | FC-Next:{fc_next:.2f}", level="DEBUG")

        # --- PRICE DATA ---
        prices_today = self.get_state(self.price_sensor_id, attribute='today')
        prices_tmrw = self.get_state(self.price_sensor_id, attribute='tomorrow')

        if not prices_today:
            self._set_error_states('N/A - No Price Data')
            return
        
        all_prices = []
        now_dt = self.get_now().replace(second=0, microsecond=0, tzinfo=None)
        now_aware = self.get_now()
        start_slot = now_dt - timedelta(minutes=now_dt.minute % 15)
        today_date = now_dt.date()
        
        for i, p in enumerate(prices_today):
            if isinstance(p, dict) and 'total' in p:
                p_dt = datetime.combine(today_date, time(i // 4, (i % 4) * 15))
                if p_dt >= start_slot: all_prices.append({'price': float(p['total']), 'time_dt': p_dt})

        if prices_tmrw:
            tmrw_date = (now_dt + timedelta(days=1)).date()
            for i, p in enumerate(prices_tmrw):
                if isinstance(p, dict) and 'total' in p:
                    p_dt = datetime.combine(tmrw_date, time(i // 4, (i % 4) * 15))
                    all_prices.append({'price': float(p['total']), 'time_dt': p_dt})

        if not all_prices:
             self._set_error_states('N/A - No Intervals')
             return
        
        # --- ANALYSIS ---
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
        if cur_soc > self.soc_threshold_high:
            eff_spread = max(eff_spread, self.spread_high_soc_eur)
            self._log_debug(f"DynSpread: SoC > {self.soc_threshold_high}% -> Spread {eff_spread:.2f}", level="DEBUG")
        elif cur_soc > self.soc_threshold_medium:
            eff_spread = max(eff_spread, self.spread_medium_soc_eur)
            self._log_debug(f"DynSpread: SoC > {self.soc_threshold_medium}% -> Spread {eff_spread:.2f}", level="DEBUG")
        
        min_interim = 9.99
        interim_dip = False
        if peak_time_slot and peak_time_slot > now_dt:
             for item in all_prices:
                 if item['time_dt'] > now_dt and item['time_dt'] < peak_time_slot:
                     if item['price'] < min_interim: min_interim = item['price']
             refill_profit = cur_price - (min_interim / self.efficiency_factor)
             if refill_profit > self.min_cycle_profit_eur: interim_dip = True

        should_hold = (cur_spread >= eff_spread) and (not interim_dip)
        if should_hold: self._log_debug(f"Hold active! Spread {cur_spread:.3f} >= {eff_spread:.3f}", level="DEBUG")

        # --- DEMAND CALC ---
        deadline = peak_time_slot if max_future_price > price_discharge_limit else datetime.combine(today_date, time(23, 59))
        morning_peak = deadline.hour < 10
        
        pv_strong = fc_next >= pv_fc_thresh
        cur_pv_strong = cur_pv >= cur_pv_thresh
        fc_now_strong = fc_now >= pv_fc_thresh
        pv_dominant = pv_strong or cur_pv_strong or fc_now_strong

        pool = [x for x in all_prices if x['time_dt'] < deadline and x['time_dt'] >= start_slot]
        need_soc_kwh = max(0.0, (target_soc - cur_soc) / 100 * batt_cap)
        
        req_intervals = int(math.ceil((need_soc_kwh / charge_pwr) * 4)) if charge_pwr > 0 else 0
        charge_slots_cnt = min(req_intervals, user_intervals)
        charge_slots_cnt = max(0, charge_slots_cnt)
        
        first_slot_dt = deadline
        if charge_slots_cnt > 0 and pool:
            sorted_pool = sorted(pool, key=lambda x: x['price'])
            if len(sorted_pool) >= charge_slots_cnt:
                best_slots = sorted_pool[:charge_slots_cnt]
                best_slots.sort(key=lambda x: x['time_dt'])
                first_slot_dt = best_slots[0]['time_dt']
        
        try:
            time_until = (first_slot_dt - now_dt).total_seconds() / 3600
            load_w = cur_house
            if load_w > 1000: load_w = 800 
            if load_w < 200: load_w = 300 
            pred_load_kwh = (load_w / 1000) * max(0, time_until)
            
            if morning_peak or fc_next < 0.1: pred_pv_kwh = 0
            else: pred_pv_kwh = fc_rem * self.pv_forecast_safety_factor
            
            total_need = need_soc_kwh + pred_load_kwh - pred_pv_kwh
            total_need = max(0.0, min(total_need, batt_cap))
            
            req_h = total_need / charge_pwr if charge_pwr > 0 else 0
            req_int = int(math.ceil(req_h * 4))
            final_slots = min(req_int, user_intervals)
            needed_kwh = total_need
        except:
            needed_kwh = need_soc_kwh
            final_slots = charge_slots_cnt

        # --- FINAL SLOTS ---
        if pool and final_slots > 0:
            sorted_pool = sorted(pool, key=lambda x: x['price'])
            cheap_slots_found = sorted_pool[:final_slots]
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
                if slot['time_dt'] == start_slot:
                    current_time_in_best_block = True
                    break
        
        if self.next_charge_time_id and cheap_slots_found:
            self.set_state(self.next_charge_time_id, state=cheap_slots_found[0]['time_dt'].strftime('%H:%M'))
        elif self.next_charge_time_id:
            self.set_state(self.next_charge_time_id, state="--:--")
            
        # --- DECISION ---
        t_panic = (deadline - now_dt).total_seconds() / 3600
        panic_mode = (t_panic < 1.5) and (cur_price <= price_discharge_limit) and (needed_kwh > 0)

        # PRIO 1: DISCHARGE (High Price)
        if app_is_enabled and ((cur_price > price_discharge_limit and not should_hold) or interim_dip):
            if cur_soc > min_soc_discharge:
                if cur_batt_pwr > 50: is_discharge_active = True
                status_msg = f"Discharging (Price/Dip)."
                self.set_state(self.dashboard_status_text_id, state=status_msg)
                self._set_inverter_mode(self.mode_general)
            else:
                self.set_state(self.dashboard_status_text_id, state=f"Discharge ready (Battery empty).")
                self._set_inverter_mode(self.mode_general)

        # PRIO 2: CHARGE (Low Price)
        elif app_is_enabled and cur_soc < target_soc and (current_time_in_best_block or panic_mode):
            is_dip = (cur_spread >= self.base_min_price_spread_eur)
            if current_time_in_best_block or panic_mode: allow = True
            else: allow = (cur_price <= price_discharge_limit) or is_dip
            
            if allow:
                status_msg = f"Charging: {cheap_hours_info}"
                self.set_state(self.dashboard_status_text_id, state=status_msg)
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
                self._set_inverter_mode(self.mode_charge)
            else:
                self.turn_on(self.cheap_hour_toggle_id)
                self.set_state(self.dashboard_status_text_id, state=f"Blocked: Price too high ({cur_price:.3f}€).")

        # PRIO 3: PV OPTIMIZATION
        elif current_mode == self.mode_general and pv_dominant and cur_soc < 100:
            if cur_batt_pwr < -100: 
                is_pv_charge_active = True
                self.set_state(self.dashboard_status_text_id, state=f"PV Charging.")
                charge_toggle_on = True
                self.turn_on(self.cheap_hour_toggle_id)
            elif current_mode != self.mode_charge:
                self._set_inverter_mode(self.mode_general)

        # PRIO 4: IDLE / HOLD (with ISO Peak Logic)
        elif not is_pv_charge_active and not charge_toggle_on and not is_discharge_active:
            approaching_peak = False
            if peak_dt:
                 diff = (peak_dt - now_aware).total_seconds() / 60
                 if diff > -30 and diff < 90: approaching_peak = True

            sun_shine = cur_pv > 50 or fc_next > 0.1 or fc_now_strong or approaching_peak
            
            tgt_mode = self.mode_backup
            info = "Wait (Spread-Hold)"

            if sun_shine:
                tgt_mode = self.mode_general
                info = "Wait (PV/Peak expected)"
            elif not should_hold:
                tgt_mode = self.mode_general
                info = "Standard (Idle)"

            self._set_inverter_mode(tgt_mode)
            self.set_state(self.dashboard_status_text_id, state=f"{info} ({tgt_mode}).")
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)

        # PRIO 5: TARGET REACHED
        elif needed_kwh == 0 and cur_soc >= target_soc:
            sun_shine = cur_pv > 50 or fc_next > 0.1 or fc_now_strong
            tgt_mode = self.mode_backup
            if sun_shine: tgt_mode = self.mode_general
            
            self._set_inverter_mode(tgt_mode)
            self.set_state(self.dashboard_status_text_id, state=f"Target Reached.")
            charge_toggle_on = False
            self.turn_off(self.cheap_hour_toggle_id)
        
        if self.cheap_hours_text_id: self.set_state(self.cheap_hours_text_id, state=cheap_hours_info)
        
        # Tracking Calls...
        if (charge_toggle_on or is_pv_charge_active) and not self.charging_session_active:
            self.charging_session_active = True
            self.charging_session_start_time = self.datetime()
            self.charging_session_net_charged_kwh = 0.0
        
        if self.charging_session_active:
            if cur_grid < -50: 
                kwh_min = (abs(cur_grid) / 1000) / 60
                self.charging_session_net_charged_kwh += kwh_min
                cp = avg_price_slots if cheap_slots_found else (all_prices[0]['price'] if all_prices else 0.0)
                self._update_charge_cost_stats(kwh_min, cp)

        if self.charging_session_active and not (charge_toggle_on or is_pv_charge_active):
            self.charging_session_active = False
            self.charging_session_net_charged_kwh = 0.0

        if is_discharge_active and cur_batt_pwr > 50:
            if not self.discharging_active: self.discharging_active = True
            dis_kwh = (abs(cur_batt_pwr) / 1000) / 60 
            self._update_discharge_saving_stats(dis_kwh, cur_price)
        elif self.discharging_active:
            self.discharging_active = False

        if cur_pv > 0 and cur_house > 0:
             direct = min(cur_pv, cur_house)
             dkwh = (direct / 1000) / 60
             self._update_pv_direct_stats(dkwh, cur_price)

    def terminate(self):
        self.log("INFO: App terminated.", level="INFO")
        if self.cheap_hour_toggle_id: self.turn_off(self.cheap_hour_toggle_id)
