# -*- coding: utf-8 -*-
from odoo import models, fields, api
import re

# ------------------------------------------------------------------
# utility
# ------------------------------------------------------------------
def float_to_hms(minutes_float):
    if minutes_float == 0:
        return "-"
    total_seconds = round(minutes_float * 60)
    hours   = total_seconds // 3600
    remain  = total_seconds % 3600
    mins    = remain // 60
    secs    = remain % 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


class WorkOrderDashboard(models.Model):
    _inherit = "mrp.workorder"

    # ================================================================
    # bộ lọc line / shift (không đổi)
    # ================================================================
    @api.model
    def get_filter_options(self):
        lines  = self.env['smartbiz_mes.production_line'].search([])
        shifts = self.env['smartbiz_mes.shift'].search([])
        return {
            'lines' : [{'id': l.id, 'name': l.name or ''} for l in lines],
            'shifts': [{'id': s.id, 'name': s.name or ''} for s in shifts],
        }

    # ================================================================
    # xếp thứ tự các bước
    # ================================================================
    def __get_all_steps_ordered(self, productions):
        step_positions = {}
        for prod in productions:
            if prod.bom_id:
                operations = prod.bom_id.operation_ids.sorted(key=lambda o: o.sequence)
                for idx, op in enumerate(operations, 1):
                    name = (op.name or op.workcenter_id.name or "Unknown").strip()
                    step_positions.setdefault(name.lower(), []).append(idx)
            else:
                wos = self.env['mrp.workorder'].search(
                    [('production_id', '=', prod.id)], order='id asc'
                )
                for idx, wo in enumerate(wos, 1):
                    name = (
                        wo.operation_id.name or wo.name or
                        (wo.workcenter_id and wo.workcenter_id.name) or
                        "Unknown"
                    ).strip()
                    step_positions.setdefault(name.lower(), []).append(idx)

        # trung bình vị trí
        avg_rank = {
            step: sum(pos_list) / len(pos_list) for step, pos_list in step_positions.items()
        }
        return sorted(avg_rank.keys(), key=lambda s: avg_rank[s])

    # ================================================================
    # xác định ca
    # ================================================================
    SHIFT_CUTOFF = (13, 45)     # 13:30

    def _shift_idx_from_start(self, dt):
        if not dt:
            return 0
        t = fields.Datetime.context_timestamp(self, dt)   # local‑time (naive)
        return 1 if (t.hour, t.minute) < self.SHIFT_CUTOFF else 2

    # ================================================================
    # 1) DASHBOARD
    # ================================================================
    @api.model
    def get_dashboard_data(self, date="", line="", shift=""):
        dom_act = [('start', '!=', False)]
        if date:
            dom_act += [('start', '>=', f"{date} 00:00:00"),
                        ('start', '<=', f"{date} 23:59:59")]
        if line:
            dom_act.append(('work_order_id.production_line_id.name', 'ilike', line))

        acts_all = self.env['smartbiz_mes.production_activity'].search(dom_act)

        # lọc theo ca nếu cần
        shift_num = 0
        if re.search(r'\b1\b', str(shift)): shift_num = 1
        if re.search(r'\b2\b', str(shift)): shift_num = 2
        acts_det = acts_all.filtered(
            lambda a: self._shift_idx_from_start(a.start) == shift_num
        ) if shift_num else acts_all

        # KPI
        # prods_kpi = acts_all.mapped('work_order_id.production_id')
        prods_kpi = self.env['mrp.production'].browse(set(acts_all.mapped('work_order_id.production_id').ids))
        acts_kpi  = acts_all.filtered(
            lambda a: a.finish and a.quality >= 0.9 and a.activity_type != 'paused'
        )
        kpi = {
            'total_plan_qty'  : sum(prods_kpi.mapped('product_qty')),
            'finish_shift1'   : 0,
            'finish_shift2'   : 0,
            'packing_progress': 0,
        }
        for act in acts_kpi:
            if (act.work_order_id.operation_id.name or "").strip().lower() != 'đóng gói':
                continue
            kpi['packing_progress'] += act.quantity
            idx = self._shift_idx_from_start(act.start)
            if idx == 1: kpi['finish_shift1'] += act.quantity
            if idx == 2: kpi['finish_shift2'] += act.quantity

        # bảng 1.1
        prods_det = acts_det.mapped('work_order_id.production_id')
        all_steps = self.__get_all_steps_ordered(prods_det)
        step_disp = {s: s.capitalize() for s in all_steps}

        now   = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        rows  = []
        lots = len(prods_det)
        for stt, prod in enumerate(prods_det, 1):
            acts = acts_det.filtered(lambda a: a.work_order_id.production_id.id == prod.id)
            m = {s: {
                    'time': 0, 'qty': 0, 'not': 0,
                    'paused': False, 'status': 'none', 'actual_time': 0
                } for s in all_steps}

            for a in acts:
                sname = (
                    a.work_order_id.operation_id.name or
                    a.work_order_id.name or
                    (a.work_order_id.workcenter_id and a.work_order_id.workcenter_id.name) or
                    "unknown"
                ).strip().lower()
                if sname not in m:
                    continue
                rec = m[sname]
                if a.activity_type == 'paused':
                    dur = 0
                    rec['paused'] = True
                elif a.finish:
                    dur = a.duration
                else:
                    start_local = fields.Datetime.context_timestamp(self, a.start)
                    dur = (now - start_local).total_seconds() / 60
                    
                rec['actual_time'] += dur
                rec['time'] += dur / (a.work_order_id.workcenter_id.equipment_quantity or 1)
                rec['qty']  += a.quantity
                if not a.finish:
                    rec['not'] += 1

            for rec in m.values():
                if rec['paused']:
                    rec['status'] = 'paused'
                elif not rec['time']:
                    rec['status'] = 'none'
                elif rec['not']:
                    rec['status'] = 'working'
                else:
                    rec['status'] = 'done'

            # total_actual = sum(r['actual_time'] for r in m.values())
            total_actual = sum(r['actual_time'] for k, r in m.items()
                            if k.strip().lower() != 'đóng gói'
                        )
            row = {
                'stt'                 : stt,
                'kh'                  : prod.origin or "",
                'lot'                 : prod.name,
                'item'                : prod.product_id.name,
                'so_luong'            : prod.product_qty,
                'thoi_gian_tieu_chuan': round(total_actual/(lots or 1), 2),                      # không tính khi bỏ mặc định
                'thoi_gian_thuc_te'   : round(total_actual, 2),
            }
            for s in all_steps:
                d = step_disp[s]
                r = m[s]
                if r['qty'] or r['time'] or r['status'] != 'none':
                    row[d] = {
                        'time'    : round(r['time'],2),
                        'quantity': r['qty'],
                        'status'  : r['status'],
                    }
            for disp in step_disp.values():              # chính là list 'steps' frontend nhận
                row.setdefault(disp, {
                    'time'    : '-',
                    'quantity': 0,
                    'status'  : 'none',
                })
            rows.append(row)

        return {
            'steps': [step_disp[s] for s in all_steps],
            'data' : rows,
            'kpi'  : kpi,
        }

    # ================================================================
    # 2) FAULTY DATA
    # ================================================================
    @api.model
    def get_faulty_data(self, date="", line="", shift=""):
        dom = [
            ('quality', '<', 0.9),
            ('start', '!=', False),
            ('finish', '!=', False),
        ]
        if date:
            dom += [('start', '>=', f"{date} 00:00:00"),
                    ('start', '<=', f"{date} 23:59:59")]
        if line:
            dom.append(('work_order_id.production_line_id.name', 'ilike', line))

        acts_faulty = self.env['smartbiz_mes.production_activity'].search(dom)

        # lọc ca
        if re.search(r'\b1\b', str(shift)):
            acts_faulty = acts_faulty.filtered(lambda a: self._shift_idx_from_start(a.start) == 1)
        elif re.search(r'\b2\b', str(shift)):
            acts_faulty = acts_faulty.filtered(lambda a: self._shift_idx_from_start(a.start) == 2)

        prods      = acts_faulty.mapped('work_order_id.production_id')
        all_steps  = self.__get_all_steps_ordered(prods)
        step_disp  = {s: s.capitalize() for s in all_steps}

        grouped = {}
        for act in acts_faulty:
            prod = act.work_order_id.production_id
            lot  = prod.name
            grouped.setdefault(lot, {
                'kh'        : prod.origin,
                'lot'       : lot,
                'item'      : prod.product_id.name,
                'components': {},
            })
            comp = act.component_id
            if not comp:
                continue

            sname_raw = (
                act.work_order_id.operation_id.name or
                act.work_order_id.name or
                (act.work_order_id.workcenter_id and act.work_order_id.workcenter_id.name) or
                "unknown"
            ).strip().lower()
            step_name = step_disp.get(sname_raw, sname_raw.capitalize())

            cm = grouped[lot]['components'].setdefault(
                comp.id,
                {'component_name': comp.name, 'total_faulty': 0.0}
            )
            cm['total_faulty'] += act.quantity
            cm[step_name] = cm.get(step_name, 0.0) + act.quantity

        faulty_data = []
        stt = 1
        for lot_data in grouped.values():
            for comp in lot_data['components'].values():
                row = {
                    'stt'           : stt,
                    'kh'            : lot_data['kh'],
                    'lot'           : lot_data['lot'],
                    'item'          : lot_data['item'],
                    'component_name': comp['component_name'],
                    'total_faulty'  : comp['total_faulty'],
                }
                for step in all_steps:
                    disp = step_disp[step]
                    if disp in comp:
                        qty = comp[disp]
                        row[disp] = {
                            'quantity': qty,
                            'status'  : 'ng' if qty else 'ok',
                        }
                for disp in step_disp.values():
                    row.setdefault(disp, {
                        'quantity': 0.0,
                        'status'  : 'ok',
                    })
                faulty_data.append(row)
                stt += 1

        return {
            'steps': [step_disp[s] for s in all_steps],
            'data' : faulty_data,
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
