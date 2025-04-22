# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta

def float_to_hms(minutes_float):
    if minutes_float == 0:
        return "-"
    total_seconds = round(minutes_float * 60)
    hours = total_seconds // 3600
    remain = total_seconds % 3600
    mins = remain // 60
    secs = remain % 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}"

class WorkOrderDashboard(models.Model):
    _inherit = "mrp.workorder"

    @api.model
    def get_filter_options(self):
        """
        Lấy danh sách line, shift => { lines: [...], shifts: [...] }
        """
        line_records = self.env['smartbiz_mes.production_line'].search([])
        lines_data = [{'id': line.id, 'name': line.name or ''} for line in line_records]

        shift_records = self.env['smartbiz_mes.shift'].search([])
        shifts_data = [{'id': s.id, 'name': s.name or ''} for s in shift_records]

        return {
            'lines': lines_data,
            'shifts': shifts_data
        }

    # ----------------------------------------------------------------
    # 1) WORKORDER DASHBOARD
    # ----------------------------------------------------------------
    def __get_all_steps_ordered(self, productions):
        """
        Trả về:
        - all_steps_ordered: Danh sách tất cả step sắp xếp theo "vị trí trung bình".

        
        Logic:
        1) Nếu production có bom_id -> lấy operation_ids theo sequence.
        2) Nếu không có bom_id -> lấy danh sách workorder (order='id asc'),
            gán pos=1,2,... theo thứ tự.
        3) Gom step_name và pos vào step_positions[step_name].
        4) Tính trung bình pos cho mỗi step_name -> sắp xếp -> all_steps_ordered.
        """

        step_positions = {}       # {step_name: [pos1, pos2, ...]} dùng để tính trung bình


        for prod in productions:
            # Nếu có BOM
            if prod.bom_id:
                operations = prod.bom_id.operation_ids.sorted(key=lambda op: op.sequence)
                pos = 1

                for op in operations:
                    op_name = (op.name or "").strip()
                    if not op_name:
                        # fallback lấy workcenter_id name
                        op_name = op.workcenter_id.name if op.workcenter_id else "Unknown Op"
                    step_positions.setdefault(op_name.lower(), []).append(pos)
                    pos += 1
            else:
                # Không có BOM => Lấy các WO của production
                wos = self.env['mrp.workorder'].search(
                    [('production_id', '=', prod.id)],
                    order='id asc'  # Hoặc order='name asc' nếu bạn muốn
                )
                pos = 1
                for wo in wos:
                    # Ưu tiên operation_id.name, nếu trống thì fallback sang wo.name/workcenter
                    if wo.operation_id:
                        step_name = (wo.operation_id.name or "").strip()
                    else:
                        step_name = (wo.name or wo.workcenter_id.name or "Unknown").strip()
                    step_positions.setdefault(step_name.lower(), []).append(pos)
                    pos += 1

        # Tính vị trí trung bình
        step_avg_rank = {}
        for step_name, positions in step_positions.items():
            if positions:
                avg_rank = sum(positions) / len(positions)
            else:
                avg_rank = 9999
            step_avg_rank[step_name] = avg_rank

        # Sắp xếp step_name theo avg_rank tăng dần
        all_steps_ordered = sorted(step_avg_rank.keys(), key=lambda s: step_avg_rank[s])

        return all_steps_ordered


    @api.model
    def get_dashboard_data(self, date="", line="", shift=""):
        domain_prod = [('state', 'not in', ['draft', 'cancel'])]
        if date:
            domain_prod.append(('date_start', '>=', date + ' 00:00:00'))
            domain_prod.append(('date_start', '<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name', 'ilike', line))
        if shift:
            domain_prod.append(('shift_id.name', 'ilike', shift))

        production_orders = self.env['mrp.production'].search(domain_prod)

        all_activities = self.env['smartbiz_mes.production_activity'].search([
            ('work_order_id.production_id', 'in', production_orders.ids),
            ('start', '!=', False),
            ('quality', '>=', 0.9)
        ])

        

        all_steps = self.__get_all_steps_ordered(production_orders)

        step_display_names = {step: step.capitalize() for step in all_steps}

        dashboard_data = []
        stt = 1

        current_time = datetime.now()

        for prod in production_orders:
            sub_acts = all_activities.filtered(lambda a: a.work_order_id.production_id == prod)

            step_map = {
                step: {
                    'time': 0.0,
                    'status': 'none',
                    'count_total': 0,
                    'count_not_finished': 0,
                    'quantity': 0,
                }
                for step in all_steps
            }

            for act in sub_acts:
                step_name = ""
                # Ưu tiên operation_id
                if act.work_order_id.operation_id:
                    step_name = (act.work_order_id.operation_id.name or "").strip().lower()
                # Nếu vẫn trống => fallback work_order_id.name
                elif act.work_order_id and act.work_order_id.name:
                    step_name = act.work_order_id.name.strip().lower()
                # Nếu vẫn trống => fallback workcenter_id.name
                elif act.workcenter_id and act.workcenter_id.name:
                    step_name = act.workcenter_id.name.strip().lower()
                else:
                    step_name = "unknown"
                if step_name not in step_map:
                    continue
                
                duration = act.duration
                if not act.finish:
                    duration = (current_time - act.start).total_seconds() / 60  # thời gian tính bằng phút

                step_map[step_name]['time'] += duration
                step_map[step_name]['quantity'] += act.quantity
                step_map[step_name]['count_total'] += 1

                if not act.finish:
                    step_map[step_name]['count_not_finished'] += 1

            for step in all_steps:
                info = step_map[step]
                if info['count_total'] == 0 or info['time'] == 0:
                    info['status'] = 'none'
                elif info['count_not_finished'] > 0:
                    info['status'] = 'working'
                else:
                    info['status'] = 'done'

            total_actual_time = sum(step_map[s]['time'] for s in all_steps)

            row = {
                'stt': stt,
                'kh': prod.origin or "",
                'lot': prod.name or "",
                'item': prod.product_id.name or "",
                'so_luong': prod.product_qty,
                'thoi_gian_tieu_chuan': float_to_hms(prod.duration_expected),
                'thoi_gian_thuc_te': float_to_hms(total_actual_time),
            }

            for step in all_steps:
                display_name = step_display_names[step]
                row[display_name] = {
                    'time': float_to_hms(step_map[step]['time']),
                    'quantity': step_map[step]['quantity'],
                    'status': step_map[step]['status'],
                }

            dashboard_data.append(row)
            stt += 1

        return {
            'steps': [step_display_names[s] for s in all_steps],
            'data': dashboard_data
        }


    @api.model
    def get_faulty_data(self, date="", line="", shift=""):
        """
        Tính sản phẩm lỗi => Gom theo lot, component, step => hiển thị tab WorkOrder => 1.2
        """
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        all_steps = self.__get_all_steps_ordered(prods)
        step_disp = {s: s.capitalize() for s in all_steps}

        grouped_faulty_data = {}
        for prod in prods:
            lot_key = prod.name
            if lot_key not in grouped_faulty_data:
                grouped_faulty_data[lot_key] = {
                    'kh': prod.origin,
                    'lot': prod.name,
                    'item': prod.product_id.name,
                    'components': {},
                }
            sub_wos = wos.filtered(lambda w: w.production_id == prod)
            faulty_acts = self.env['smartbiz_mes.production_activity'].search([
                ('work_order_id','in', sub_wos.ids),
                ('quality','<',0.9),
                ('start','!=',False),
                ('finish','!=',False),
            ])
            for act in faulty_acts:
                comp = act.component_id
                if not comp:
                    continue
                step_n = ""
                # Ưu tiên operation_id
                if act.work_order_id.operation_id:
                    step_n = (act.work_order_id.operation_id.name or "").strip().lower()
                # Nếu vẫn trống => fallback work_order_id.name
                elif act.work_order_id and act.work_order_id.name:
                    step_n = act.work_order_id.name.strip().lower()
                # Nếu vẫn trống => fallback workcenter_id.name
                elif act.workcenter_id and act.workcenter_id.name:
                    step_n = act.workcenter_id.name.strip().lower()
                else:
                    step_n = "unknown"
                step_name = step_disp.get(step_n, step_n.capitalize())

                if comp.id not in grouped_faulty_data[lot_key]['components']:
                    grouped_faulty_data[lot_key]['components'][comp.id] = {
                        'component_name': comp.name,
                        'total_faulty': 0.0,
                        **{step_disp[s]: 0.0 for s in all_steps}
                    }
                cdict = grouped_faulty_data[lot_key]['components'][comp.id]
                cdict['total_faulty'] += act.quantity
                if step_name in cdict:
                    cdict[step_name] += act.quantity

        faulty_data = []
        stt = 1
        for lot_data in grouped_faulty_data.values():
            for comp_data in lot_data['components'].values():
                row = {
                    'stt': stt,
                    'kh': lot_data['kh'],
                    'lot': lot_data['lot'],
                    'item': lot_data['item'],
                    'component_name': comp_data['component_name'],
                    'total_faulty': comp_data['total_faulty'],
                }
                for step_ in sorted(comp_data.keys()):
                    if step_ in ['component_name','total_faulty']:
                        continue
                    row[step_] = comp_data[step_]
                faulty_data.append(row)
                stt+=1
        return {
            'steps': [step_disp[s] for s in all_steps],
            'data':faulty_data
            }

    # ----------------------------------------------------------------
    # 2) Tất cả KPI Analytics (Cũ + Mới)
    # ----------------------------------------------------------------
    @api.model
    def get_analytics_kpis(self, date="", line="", shift=""):
        """
        Tính toàn bộ KPI, gồm cũ (Quality, Defect, Productivity, Time, Completion, OEE)
        và mới (Downtime, Setup Efficiency, Scrap, Yield, Throughput, Rework, 
                 Labor Productivity, Machine Utilization, OnTime Delivery, Bottleneck).
        Trả về dictionary:
          {
            "quality_data": [...],
            "defect_data": [...],
            "productivity_data": [...],
            "time_data": [...],
            "completion_data": [...],
            "oee_data": [...],
            "downtime_rate": float,
            "setup_efficiency": float,
            "scrap_rate": float,
            "yield_rate": float,
            "throughput_rate": float,
            "rework_rate": float,
            "labor_productivity": float,
            "machine_utilization": float,
            "on_time_delivery": float,
            "bottleneck_index": float,
          }
        """
        # -- Gọi các hàm cũ:
        quality_data = self.get_quality_report(date, line, shift)
        defect_data = self.get_defect_by_workcenter_shift(date, line, shift)
        productivity_data = self.get_productivity_by_shift_employee(date, line, shift)
        time_data = self.get_avg_time_per_unit(date, line, shift)
        completion_data = self.get_completion_rate(date, line, shift)
        oee_data = self.get_oee_report(date, line, shift)

        # Tính KPI Mới:
        # Giả sử load production orders
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        if not prods:
            return {
                "quality_data": quality_data,
                "defect_data": defect_data,
                "productivity_data": productivity_data,
                "time_data": time_data,
                "completion_data": completion_data,
                "oee_data": oee_data,
                # KPI mới => đặt =0
                "downtime_rate": 0,
                "setup_efficiency": 0,
                "scrap_rate": 0,
                "yield_rate": 0,
                "throughput_rate": 0,
                "rework_rate": 0,
                "labor_productivity": 0,
                "machine_utilization": 0,
                "on_time_delivery": 0,
                "bottleneck_index": 0,
            }

        # Tính 1 số logic dummy
        # - downtime_rate: (planned - actual)/planned *100
        # - setup_efficiency: 25/30 => 83.3
        # - scrap_rate: (NG / total) * 100
        # - yield_rate: (OK / total) * 100
        # - throughput_rate: total_produced / (duration_min/60)
        # - rework_rate: fix cứng 5
        # - labor_productivity: total_produced / worker_hours * 100
        # - machine_utilization: (actual / planned)*100
        # - on_time_delivery: fix cứng 90
        # - bottleneck_index: fix cứng 75

        # Tính total_produced, total_ok, total_ng
        total_ok = 0.0
        total_ng = 0.0
        for q in quality_data:
            total_ok += (q.get('ok_qty', 0.0) or 0.0)
            total_ng += (q.get('ng_qty', 0.0) or 0.0)
        total_prod = total_ok + total_ng

        # Tính planned vs actual
        total_planned = 0.0
        total_actual = 0.0
        for p in prods:
            if p.date_start and p.date_finished:
                dt_start = fields.Datetime.from_string(p.date_start)
                dt_finish = fields.Datetime.from_string(p.date_finished)
                planned_minutes = (dt_finish - dt_start).total_seconds()/60.0
                total_planned += planned_minutes
                # p.duration => Odoo cũ? Mặc định k có p.duration, tạm fix
                # Hoặc ta sum durations from p.workorder_ids
                actual_mins = sum(wo.duration for wo in p.workorder_ids)
                total_actual += actual_mins

        downtime_rate = 0
        if total_planned>0:
            downtime_rate = ( (total_planned - total_actual)/ total_planned ) * 100

        # Setup Efficiency => Dummy
        setup_efficiency = 83.33

        scrap_rate = 0
        yield_rate = 0
        if total_prod>0:
            scrap_rate = (total_ng/total_prod)*100
            yield_rate = (total_ok/total_prod)*100

        # Tính throughput => total_prod / (actual_mins/60)
        # Ở code cũ: total_duration_minutes = sum(p.duration_expected)?
        # Chúng ta tạm coi actual = total_actual => throughput
        throughput_rate = 0
        if (total_actual/60.0)>0:
            throughput_rate = total_prod / (total_actual/60.0)

        # Rework => fix cứng 5
        rework_rate = 5

        # Labor Productivity => total_prod / (40*gọi là worker_count) * 100 => dummy
        # Tạm worker_count = len(prods)
        worker_count = len(prods)
        labor_productivity = 0
        if worker_count>0:
            # giả sử 40h là 2400 phút?
            # total_prod / total_hours * 100 => dummy
            total_hours = 40*worker_count
            labor_productivity = (total_prod / total_hours)*100

        machine_utilization = 0
        if total_planned>0:
            machine_utilization = (total_actual / total_planned)*100

        on_time_delivery = 90
        bottleneck_index = 75

        return {
            "quality_data": quality_data,
            "defect_data": defect_data,
            "productivity_data": productivity_data,
            "time_data": time_data,
            "completion_data": completion_data,
            "oee_data": oee_data,

            "downtime_rate": round(downtime_rate,2),
            "setup_efficiency": round(setup_efficiency,2),
            "scrap_rate": round(scrap_rate,2),
            "yield_rate": round(yield_rate,2),
            "throughput_rate": round(throughput_rate,2),
            "rework_rate": round(rework_rate,2),
            "labor_productivity": round(labor_productivity,2),
            "machine_utilization": round(machine_utilization,2),
            "on_time_delivery": round(on_time_delivery,2),
            "bottleneck_index": round(bottleneck_index,2),
        }

    @api.model
    def get_quality_report(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        activities = self.env['smartbiz_mes.production_activity'].search([
            ('work_order_id','in', wos.ids),
            ('start','!=',False),
            ('finish','!=',False),
        ])

        quality_map = {}
        for act in activities:
            production = act.work_order_id.production_id
            lot_name = production.name or ""
            product_name = production.product_id.display_name or ""
            comp_name = act.component_id.name or ""
            key = (lot_name, product_name, comp_name)
            if key not in quality_map:
                quality_map[key] = {
                    'lot': lot_name,
                    'product': product_name,
                    'component': comp_name,
                    'ok_qty': 0.0,
                    'ng_qty': 0.0,
                    'total_qty': 0.0,
                }
            if act.quality >= 0.9:
                quality_map[key]['ok_qty'] += act.quantity
            else:
                quality_map[key]['ng_qty'] += act.quantity
            quality_map[key]['total_qty'] += act.quantity

        results = []
        stt = 1
        for val in quality_map.values():
            ok_ratio = (val['ok_qty'] / val['total_qty'] * 100) if val['total_qty'] else 0.0
            ng_ratio = (val['ng_qty'] / val['total_qty'] * 100) if val['total_qty'] else 0.0
            results.append({
                'stt': stt,
                'lot': val['lot'],
                'product': val['product'],
                'component': val['component'],
                'ok_qty': val['ok_qty'],
                'ng_qty': val['ng_qty'],
                'total_qty': val['total_qty'],
                'ok_ratio': round(ok_ratio, 2),
                'ng_ratio': round(ng_ratio, 2),
            })
            stt += 1
        return results

    @api.model
    def get_defect_by_workcenter_shift(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        # Gom NG theo workcenter
        result_map = {}
        activities = self.env['smartbiz_mes.production_activity'].search([
            ('work_order_id','in', wos.ids),
            ('finish','!=',False),
        ])
        for act in activities:
            if act.quality < 0.9:
                wc_name = act.work_order_id.workcenter_id.name if act.work_order_id.workcenter_id else "Unknown WC"
                # shift -> từ production
                # Muốn group shift hay hiển thị shift => ta đọc shift từ production
                # => act.work_order_id.production_id.shift_id.name
                shift_name = act.work_order_id.production_id.shift_id.name if act.work_order_id.production_id.shift_id else "No Shift"

                key = (wc_name, shift_name)
                if key not in result_map:
                    result_map[key] = 0.0
                result_map[key] += act.quantity

        results = []
        stt = 1
        for (wc, sh), ng_qty in result_map.items():
            results.append({
                'stt': stt,
                'workcenter': wc,
                'shift': sh,
                'ng_qty': ng_qty,
            })
            stt += 1
        return results

    @api.model
    def get_productivity_by_shift_employee(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        activities = self.env['smartbiz_mes.production_activity'].search([
            ('work_order_id','in', wos.ids),
            ('finish','!=',False),
        ])

        result_map = {}
        for act in activities:
            if act.quality >= 0.9:  # OK
                shift_name = act.work_order_id.production_id.shift_id.name if act.work_order_id.production_id.shift_id else "No Shift"
                emp_name = act.employee_id.name if act.employee_id else "No Employee"
                key = (shift_name, emp_name)
                if key not in result_map:
                    result_map[key] = 0.0
                result_map[key] += act.quantity

        results = []
        stt = 1
        for (sh, emp), ok_qty in result_map.items():
            results.append({
                'stt': stt,
                'shift': sh,
                'employee': emp,
                'ok_qty': ok_qty,
            })
            stt += 1
        return results

    @api.model
    def get_avg_time_per_unit(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        activities = self.env['smartbiz_mes.production_activity'].search([
            ('work_order_id','in', wos.ids),
            ('finish','!=',False),
        ])

        data_map = {}
        for act in activities:
            if act.quality >= 0.9 and act.quantity>0:
                product = act.product_id
                pid = product.id if product else False
                pname = product.display_name if product else "Unknown"
                if pid not in data_map:
                    data_map[pid] = {
                        'product_name': pname,
                        'total_duration': 0.0,
                        'total_qty': 0.0,
                    }
                data_map[pid]['total_duration'] += act.duration
                data_map[pid]['total_qty'] += act.quantity

        results = []
        stt = 1
        for pid, val in data_map.items():
            avg_time = 0.0
            if val['total_qty']>0:
                avg_time = val['total_duration'] / val['total_qty']
            results.append({
                'stt': stt,
                'product': val['product_name'],
                'total_duration': round(val['total_duration'],2),
                'total_qty': val['total_qty'],
                'avg_time_per_unit': round(avg_time,2),
            })
            stt += 1
        return results

    @api.model
    def get_completion_rate(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        results = []
        stt = 1
        for prod in prods:
            sub_wos = wos.filtered(lambda w: w.production_id == prod)
            ok_activities = self.env['smartbiz_mes.production_activity'].search([
                ('work_order_id','in', sub_wos.ids),
                ('finish','!=',False),
                ('quality','>=',0.9),
            ])
            total_ok = sum(ok_activities.mapped('quantity'))
            plan_qty = prod.product_qty
            completion = 0.0
            if plan_qty>0:
                completion = total_ok / plan_qty * 100.0
            results.append({
                'stt': stt,
                'production_name': prod.name,
                'product': prod.product_id.display_name,
                'plan_qty': plan_qty,
                'ok_qty': total_ok,
                'completion_rate': round(completion,2),
            })
            stt += 1
        return results

    @api.model
    def get_oee_report(self, date="", line="", shift=""):
        domain_prod = [('state','not in',['draft','cancel'])]
        if date:
            domain_prod.append(('date_start','>=', date + ' 00:00:00'))
            domain_prod.append(('date_start','<=', date + ' 23:59:59'))
        if line:
            domain_prod.append(('production_line_id.name','ilike', line))
        if shift:
            domain_prod.append(('shift_id.name','ilike', shift))

        prods = self.env['mrp.production'].search(domain_prod)
        wos = self.env['mrp.workorder'].search([('production_id','in', prods.ids)])

        results = []
        stt = 1
        for prod in prods:
            sub_wos = wos.filtered(lambda w: w.production_id == prod)
            activities = self.env['smartbiz_mes.production_activity'].search([
                ('work_order_id','in', sub_wos.ids),
                ('finish','!=',False),
            ])
            total_qty = sum(a.quantity for a in activities)
            total_ok = sum(a.quantity for a in activities if a.quality>=0.9)
            total_ng = total_qty - total_ok
            total_duration = sum(a.duration for a in activities)  # phút

            # Giả sử fix cứng
            plan_time = 480.0
            nominal_rate = 1.0

            availability = total_duration/plan_time if plan_time>0 else 0
            performance = (total_qty/total_duration)/nominal_rate if (total_duration>0 and nominal_rate>0) else 0
            quality = total_ok/total_qty if total_qty>0 else 0
            oee = availability*performance*quality

            results.append({
                'stt': stt,
                'production_name': prod.name,
                'total_qty': total_qty,
                'ok_qty': total_ok,
                'ng_qty': total_ng,
                'duration': round(total_duration,2),
                'availability': round(availability*100,2),
                'performance': round(performance*100,2),
                'quality': round(quality*100,2),
                'oee': round(oee*100,2),
            })
            stt += 1
        return results
