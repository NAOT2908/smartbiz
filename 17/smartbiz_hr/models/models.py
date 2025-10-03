from collections import defaultdict


DEFAULT_TOLERANCE_MIN = 3  # dung sai ± phút so với mốc giờ gửi
def _tz_get(self):
    return [(tz, tz) for tz in pytz.all_timezones]
# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os,json,re
import base64,pytz,logging,unidecode,textwrap
from datetime import datetime, timedelta, time, date as dt_date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from odoo.tools.float_utils import float_round
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook
from collections import defaultdict

class HR_Contract(models.Model):
    _inherit = ['hr.contract']
    calculation_policy_id = fields.Many2one('smartbiz_hr.calculation_policy', string='Calculation Policy', required=True)
    allowance_ids = fields.One2many('smartbiz_hr.contract_allowance', 'contract_id')


    # --- Helpers ---
    def _to_date(self, v):
        if isinstance(v, dt_date):
            return v
        if isinstance(v, datetime):
            return v.date()
        # cố gắng parse nếu là string
        try:
            return fields.Date.from_string(v)
        except Exception:
            return None

    # --- Public API: được module khác gọi ---
    def generate_work_entries(self, generate_from, generate_to, force=False):
        return True
        """
        Gọi engine WE tùy chỉnh để tái tính Work Entries cho nhân viên thuộc các HĐ này
        trong khoảng [generate_from, generate_to] (tính theo ngày, inclusive).
        Trả về recordset hr.work.entry vừa tính trong khoảng đó.
        """
        self = self.sudo()
        WE = self.env['hr.work.entry'].sudo()

        d0 = self._to_date(generate_from)
        d1 = self._to_date(generate_to)
        if not (d0 and d1) or d0 > d1:
            # Trả về rỗng theo convention của Odoo
            return WE.browse()

        # Lấy danh sách nhân viên của các HĐ này
        emp_ids = self.mapped('employee_id').ids
        if not emp_ids:
            return WE.browse()

        # Chạy engine theo từng ngày (engine tự lọc active contract theo ngày)
        cur = d0
        while cur <= d1:
            WE._recompute_day(cur, emp_ids)
            cur += timedelta(days=1)

        # Trả về các WE đã được (re)compute trong khoảng, cho các nhân viên liên quan
        start_dt = datetime.combine(d0, time.min)
        stop_dt = datetime.combine(d1, time.max)
        result = WE.search([
            ('employee_id', 'in', emp_ids),
            ('date_stop', '>=', start_dt),
            ('date_start', '<=', stop_dt),
            # chỉ lấy WE đã validate cho sạch dữ liệu tiêu thụ
            ('state', '=', 'validated'),
        ])
        return result

class HR_WorkEntry(models.Model):
    _inherit = ['hr.work.entry']
    _sql_constraints = [ ('uniq_source_key', 'unique(source, source_key)', 'Duplicated work entry source key!')   ]
    source = fields.Selection([('daily_attendance','Daily Attendance'),('manual_daily','Manual Daily'),('manual_attendance','Manual Attendance'),('leave','Leave'),('overtime','Overtime'),('early','Early'),('late','Late'),('manual','Manual'),], string='Source', index=True)
    source_key = fields.Char(string='Source Key', index=True)
    work_day = fields.Date(string='Work Day', index=True)


    # Các source mà engine quản lý (để purge/validate theo ngày)
    ENGINE_SOURCES = (
        'daily_attendance', 'manual_daily', 'manual_attendance',
        'leave', 'overtime', 'early', 'late',
    )

    # ====== OVERRIDES: create/write an toàn với key ============================================
    @api.model_create_multi
    def create(self, vals_list):
        """Chỉ tạo khi đủ source & source_key; thiếu → bỏ qua."""
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        filtered = []
        for vals in vals_list:
            if vals.get('source') and vals.get('source_key'):
                filtered.append(vals)
            else:
                _logger.debug("[WE.create] Bypass do thiếu source/source_key: %s", vals)
        if not filtered:
            return self.browse()
        return super().create(filtered)

    def write(self, vals):
        """Chỉ cho phép ghi các bản ghi có source/source_key; không cho xóa khóa qua write."""
        allowed = self.filtered(lambda we: we.source and we.source_key)
        skipped = self - allowed
        if skipped:
            _logger.debug("[WE.write] Bypass %d bản ghi do thiếu source/source_key", len(skipped))
        if not allowed:
            return True
        safe = dict(vals)
        if 'source' in safe and not safe.get('source'):
            safe.pop('source')
        if 'source_key' in safe and not safe.get('source_key'):
            safe.pop('source_key')
        return super(HR_WorkEntry, allowed).write(safe)

    # ======================================================================
    # 0) BOOTSTRAP / DEFAULTS
    # ======================================================================
    @api.model
    def _ensure_default_policies(self):
        """Seed WET + Attendance/OT/Calculation policy mặc định. Trả về (att, ot, calc)."""
        WET = self.env['hr.work.entry.type'].sudo()

        def _wet(code, name):
            rec = WET.search([('code', '=', code)], limit=1)
            if not rec:
                rec = WET.create({'name': name, 'code': code})
            elif name and rec.name != name:
                rec.name = name
            return rec

        wet_normal = _wet('WORK',  'Normal Work')
        wet_leave  = _wet('LEAVE', 'Leave')
        wet_early  = _wet('EARLY', 'Early Work')
        wet_late   = _wet('LATE',  'Late Work')
        wet_ot150  = _wet('OT150', 'Overtime 150%')
        wet_ot200  = _wet('OT200', 'Overtime 200%')
        wet_ot300  = _wet('OT300', 'Overtime 300%')

        AttPol = self.env['smartbiz_hr.attendance_policy'].sudo()
        att = AttPol.search([('name', '=', 'SmartBiz Default Attendance Policy')], limit=1)
        if not att:
            att = AttPol.create({
                'name': 'SmartBiz Default Attendance Policy',
                'must_check_in': True, 'must_check_out': True,
                'must_check_break_time': False,
                'missing_mode': 'alert',
                'minutes_before_check_in': 120,  'minutes_after_check_in': 120,
                'minutes_before_check_out': 120, 'minutes_after_check_out': 120,
                'minutes_as_late': 5, 'minutes_as_early': 5,
                'normal_work_type_id': wet_normal.id,
                'early_work_type_id':  wet_early.id,
                'late_work_type_id':   wet_late.id,
            })

        OTPol = self.env['smartbiz_hr.overtime_policy'].sudo()
        ot = OTPol.search([('name', '=', 'SmartBiz Default OT Policy')], limit=1)
        if not ot:
            ot = OTPol.create({
                'name': 'SmartBiz Default OT Policy',
                'max_hours_per_day': 4, 'max_hours_per_week': 30, 'max_hours_per_year': 500,
                'reconcile_with_attendance': False,
                'weekday_overtime_type_id': wet_ot150.id,
                'weekend_overtime_type_id': wet_ot200.id,
                'holiday_overtime_type_id': wet_ot300.id,
            })

        Calc = self.env['smartbiz_hr.calculation_policy'].sudo()
        calc = Calc.search([('name', '=', 'SmartBiz Default Calculation Policy')], limit=1)
        if not calc:
            calc = Calc.create({
                'name': 'SmartBiz Default Calculation Policy', 'active': True,
                'is_flexible': False, 'standard_hours_per_day': 8.0,
                'attendance_policy_id': att.id, 'overtime_policy_id': ot.id,
            })

        self._ensure_default_calendar_leave_and_ot_rules()
        return att, ot, calc

    def _ensure_default_calendar_leave_and_ot_rules(self):
        """Seed OT rules + calendar leave types tối thiểu (idempotent)."""
        L = self.env['smartbiz_hr.calendar_leave_type'].sudo()
        R = self.env['smartbiz_hr.overtime_rule'].sudo()
        WET = self.env['hr.work.entry.type'].sudo()
        def _wet(code): return WET.search([('code', '=', code)], limit=1)

        def _mk_rule(name, rtype, wet_code, prio=30):
            rec = R.search([('name', '=', name), ('type', '=', rtype)], limit=1)
            if rec:
                return rec
            wet = _wet(wet_code) or WET.create({'name': wet_code, 'code': wet_code})
            return R.create({'name': name, 'type': rtype, 'priority': prio, 'work_entry_type_id': wet.id})

        rule_working = _mk_rule('OT Working (150%)', 'working_day', 'OT150')
        rule_weekend = _mk_rule('OT Weekend (200%)', 'non_working_day', 'OT200')
        rule_holiday = _mk_rule('OT Holiday (300%)', 'leave_day', 'OT300')

        def _mk_ctype(code, name, day_wet_code=None, rule=None):
            rec = L.search([('code', '=', code)], limit=1)
            vals = {'name': name, 'code': code}
            if day_wet_code and _wet(day_wet_code):
                vals['work_entry_type_id'] = _wet(day_wet_code).id
            vals['overtime_rule_id'] = (rule or rule_working).id
            if rec:
                updates = {}
                if vals.get('work_entry_type_id') and not rec.work_entry_type_id:
                    updates['work_entry_type_id'] = vals['work_entry_type_id']
                if vals.get('overtime_rule_id') and not rec.overtime_rule_id:
                    updates['overtime_rule_id'] = vals['overtime_rule_id']
                if updates:
                    rec.sudo().write(updates)
                return rec
            return L.create(vals)

        _mk_ctype('PH',     'Public Holiday',      None,    rule_holiday)
        _mk_ctype('SATOFF', 'Saturday Off',        'LEAVE', rule_weekend)
        _mk_ctype('MAKEUP', 'Make-up Working Day', None,    rule_working)
        return True

    # ======================================================================
    # 1) TZ & CALENDAR HELPERS
    # ======================================================================
    def _emp_tz(self, emp_id, day=None):
        Emp = self.env['hr.employee'].browse(emp_id)
        tzname = (Emp.resource_calendar_id and Emp.resource_calendar_id.tz) or Emp.user_id.tz or self.env.user.tz or 'UTC'
        try:
            return pytz.timezone(tzname)
        except Exception:
            return pytz.UTC

    def _local_to_utc_naive(self, dt_local, tz):
        if dt_local.tzinfo is None:
            dt_local = tz.localize(dt_local)
        return dt_local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _mk_local_dt(self, day_date, hour_float, tz):
        h = int(hour_float)
        m = int(round((hour_float - h) * 60))
        return self._local_to_utc_naive(datetime.combine(day_date, time(h, m, 0)), tz)

    def _fmt_tz(self, dt_utc_naive, tz):
        if not dt_utc_naive:
            return '-'
        return fields.Datetime.to_string(dt_utc_naive.replace(tzinfo=pytz.UTC).astimezone(tz))

    def _normalize_dt(self, dt):
        if not dt:
            return None
        if isinstance(dt, datetime) and dt.tzinfo:
            return dt.astimezone(pytz.UTC).replace(tzinfo=None)
        return dt

    # ======================================================================
    # 2) TOÁN TỬ KHOẢNG THỜI GIAN
    # ======================================================================
    def _merge_intervals(self, intervals, start_dt=None, stop_dt=None):
        iv = []
        for (s, e) in intervals or []:
            s = self._normalize_dt(s); e = self._normalize_dt(e)
            if start_dt: s = max(s, self._normalize_dt(start_dt))
            if stop_dt:  e = min(e, self._normalize_dt(stop_dt))
            if s and e and s < e:
                iv.append((s, e))
        if not iv:
            return []
        iv.sort(key=lambda x: x[0])
        merged = [iv[0]]
        for s, e in iv[1:]:
            ls, le = merged[-1]
            if s < le:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))
        return merged

    def _subtract_intervals(self, base_intervals, cut_intervals):
        if not base_intervals:
            return []
        if not cut_intervals:
            return self._merge_intervals(base_intervals)
        cuts = self._merge_intervals(cut_intervals)
        res = []
        for (bs, be) in base_intervals:
            cur = [(bs, be)]
            for (cs, ce) in cuts:
                nxt = []
                for (s, e) in cur:
                    if ce <= s or cs >= e:
                        nxt.append((s, e))
                    else:
                        if s < cs:
                            nxt.append((s, cs))
                        if ce < e:
                            nxt.append((ce, e))
                cur = nxt
                if not cur:
                    break
            res += cur
        return self._merge_intervals(res)

    def _intersection_intervals(self, a_intervals, b_intervals):
        if not a_intervals or not b_intervals:
            return []
        a = self._merge_intervals(a_intervals)
        b = self._merge_intervals(b_intervals)
        out = []
        i = j = 0
        while i < len(a) and j < len(b):
            s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
            if s < e:
                out.append((s, e))
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
        return out

    # ======================================================================
    # 3) CALENDAR MARKERS & SEGMENTS
    # ======================================================================
    def _markers_of_day(self, emp_id, day_date):
        d0 = datetime.combine(day_date, time.min)
        d1 = datetime.combine(day_date, time.max)
        domain = [
            ('date_from', '<=', d1),
            ('date_to',   '>=', d0),
            ('leave_type_id', '!=', False),
        ]
        return self.env['resource.calendar.leaves'].sudo().search(domain)

    def _fetch_company_calendar_leaves_for_day(self, emp_id, day_date):
        """Trả về:
           - cal_plain: [(s,e)]
           - cal_typed: [(s,e, wet_id, token)]
        Có xử lý nghỉ bù cơ bản và fallback WET=LEAVE khi thiếu."""
        d0 = datetime.combine(day_date, time.min)
        d1 = datetime.combine(day_date, time.max)
        RCL = self.env['resource.calendar.leaves'].sudo()
        WET = self.env['hr.work.entry.type'].sudo()
        wet_leave_fallback = WET.search([('code', '=', 'LEAVE')], limit=1)

        def _segments_on(day):
            _pol, _otpol, cal = self._get_policies_and_calendar(emp_id, day)
            tz = self._emp_tz(emp_id, day)
            return self._get_day_segments(cal, day, emp_tz=tz) or []

        def _cut_by_segments(day, s, e):
            win = [(max(s, datetime.combine(day, time.min)),
                    min(e, datetime.combine(day, time.max)))]
            segs = _segments_on(day)
            return self._intersection_intervals(win, segs) if segs else win

        typed = []
        todays = RCL.search([
            ('date_from', '<=', d1), ('date_to', '>=', d0),
            ('leave_type_id', '!=', False),
        ])
        if todays:
            segs_today = _segments_on(day_date)
            if segs_today:
                for lv in todays:
                    s = max(self._normalize_dt(lv.date_from), d0)
                    e = min(self._normalize_dt(lv.date_to),   d1)
                    if not (s and e and s < e):
                        continue
                    wet_id = (
                        lv.leave_type_id.work_entry_type_id.id
                        if (lv.leave_type_id and lv.leave_type_id.work_entry_type_id)
                        else (getattr(lv, 'work_entry_type_id', False) and lv.work_entry_type_id.id)
                        or (wet_leave_fallback and wet_leave_fallback.id)
                    )
                    if not wet_id:
                        continue
                    for (ps, pe) in _cut_by_segments(day_date, s, e):
                        if ps < pe:
                            token = f"CAL:{lv.leave_type_id.code if lv.leave_type_id else 'COMP'}:{day_date}:{int(ps.timestamp())}-{int(pe.timestamp())}"
                            typed.append((ps, pe, wet_id, token))
            # nếu không có segs → coi như non-working; nghỉ bù sẽ xử lý ở chỗ khác (đơn giản hoá)
        cal_plain = self._merge_intervals([(s, e) for (s, e, _w, _t) in typed])
        return cal_plain, typed

    def _get_day_segments(self, cal, day_date, emp_tz=None):
        tz = emp_tz or pytz.UTC
        if not cal:
            return []
        dow = str(day_date.weekday())

        def _is_break(line):
            dp = getattr(line, 'day_period', False)
            return (dp and str(dp).lower() == 'lunch')

        lines = cal.attendance_ids.filtered(lambda l: l.dayofweek == dow and not _is_break(l))
        if not lines:
            return []
        segs = []
        for l in sorted(lines, key=lambda x: (x.hour_from, x.hour_to)):
            V0 = self._mk_local_dt(day_date, l.hour_from, tz)
            R0 = self._mk_local_dt(day_date, l.hour_to, tz)
            if V0 < R0:
                segs.append((V0, R0))
        return self._merge_intervals(segs)

    # ======================================================================
    # 4) CHẤM CÔNG → NORMAL/LATE/EARLY (chỉ áp dụng cho lịch làm)
    # ======================================================================
    def _compute_from_segments(self, punches, segments, pol):
        """Tính (normal_iv, late_iv, early_iv) theo segment lịch & mốc punch (daily + manual-1đ).
           - Nếu must_check_break_time=True: xét theo từng segment.
           - Nếu False: chỉ xét IN ở segment đầu & OUT ở segment cuối (day-level).
           - LATE/EARLY chỉ sinh khi minutes_as_late / minutes_as_early > 0."""
        if not segments:
            return ([], [], [])
        def mm(x): return int(x or 0)
        punches = sorted(set(punches))
        if not pol:
            return (self._merge_intervals(segments), [], [])

        VM, VE = mm(pol.minutes_as_late), mm(pol.minutes_as_early)
        normal_iv, late_iv, early_iv = [], [], []

        if pol.must_check_break_time:
            for (V0, R0) in segments:
                in_win = (V0 - timedelta(minutes=mm(pol.minutes_before_check_in)),
                          V0 + timedelta(minutes=mm(pol.minutes_after_check_in)))
                out_win = (R0 - timedelta(minutes=mm(pol.minutes_before_check_out)),
                           R0 + timedelta(minutes=mm(pol.minutes_after_check_out)))
                ins = [t for t in punches if in_win[0] <= t <= in_win[1]]
                outs = [t for t in punches if out_win[0] <= t <= out_win[1]]
                V1 = min(ins) if ins else None
                R1 = max(outs) if outs else None

                # V_eff / R_eff
                if not V1 and not pol.must_check_in:
                    V_eff = V0
                elif V1:
                    if VM > 0 and V1 > V0 and (V1 - V0).total_seconds()/60 > VM:
                        V_eff = V1
                    else:
                        V_eff = V0
                else:
                    V_eff = None

                if not R1 and not pol.must_check_out:
                    R_eff = R0
                elif R1:
                    if VE > 0 and R1 < R0 and (R0 - R1).total_seconds()/60 > VE:
                        R_eff = R1
                    else:
                        R_eff = R0
                else:
                    R_eff = None

                # LATE/EARLY chỉ khi VM/VE > 0
                if VM > 0 and V1 and V1 > V0 and (V1 - V0).total_seconds()/60 > VM and pol.late_work_type_id:
                    late_iv.append((V0, V1))
                if VE > 0 and R1 and R1 < R0 and (R0 - R1).total_seconds()/60 > VE and pol.early_work_type_id:
                    early_iv.append((R1, R0))
                if V_eff and R_eff and V_eff < R_eff:
                    normal_iv.append((V_eff, R_eff))
            return (self._merge_intervals(normal_iv), self._merge_intervals(late_iv), self._merge_intervals(early_iv))

        # Day-level
        first_V0, last_R0 = segments[0][0], segments[-1][1]
        in_win_first = (first_V0 - timedelta(minutes=mm(pol.minutes_before_check_in)),
                        first_V0 + timedelta(minutes=mm(pol.minutes_after_check_in)))
        out_win_last = (last_R0 - timedelta(minutes=mm(pol.minutes_before_check_out)),
                        last_R0 + timedelta(minutes=mm(pol.minutes_after_check_out)))
        ins_first = [t for t in punches if in_win_first[0] <= t <= in_win_first[1]]
        outs_last = [t for t in punches if out_win_last[0] <= t <= out_win_last[1]]
        V1 = min(ins_first) if ins_first else None
        R1 = max(outs_last) if outs_last else None

        for i, (V0, R0) in enumerate(segments):
            is_first, is_last = (i == 0), (i == len(segments) - 1)
            # V_eff
            if is_first:
                if not V1 and not pol.must_check_in: V_eff = V0
                elif V1:
                    if VM > 0 and V1 > V0 and (V1 - V0).total_seconds()/60 > VM:
                        V_eff = V1
                    else:
                        V_eff = V0
                else:
                    V_eff = None
            else:
                V_eff = V0
            # R_eff
            if is_last:
                if not R1 and not pol.must_check_out: R_eff = R0
                elif R1:
                    if VE > 0 and R1 < R0 and (R0 - R1).total_seconds()/60 > VE:
                        R_eff = R1
                    else:
                        R_eff = R0
                else:
                    R_eff = None
            else:
                R_eff = R0

            if is_first and VM > 0 and V1 and V1 > V0 and (V1 - V0).total_seconds()/60 > VM and pol.late_work_type_id:
                late_iv.append((V0, V1))
            if is_last and VE > 0 and R1 and R1 < R0 and (R0 - R1).total_seconds()/60 > VE and pol.early_work_type_id:
                early_iv.append((R1, R0))
            if V_eff and R_eff and V_eff < R_eff:
                normal_iv.append((V_eff, R_eff))

        return (self._merge_intervals(normal_iv), self._merge_intervals(late_iv), self._merge_intervals(early_iv))

    # ======================================================================
    # 5) FETCHERS (punch/attendance/leave/OT helpers)
    # ======================================================================
    def _fetch_daily_punch_times(self, employee_ids, start_dt, stop_dt):
        res = defaultdict(list)
        rows = self.env['daily.attendance'].search([
            ('employee_id', 'in', employee_ids),
            ('punching_time', '>=', start_dt), ('punching_time', '<=', stop_dt),
        ], order='employee_id, punching_time asc')
        for r in rows:
            res[r.employee_id.id].append(self._normalize_dt(r.punching_time))
        return res

    def _fetch_manual_punch_times(self, employee_ids, start_dt, stop_dt):
        """Các mốc check_in/check_out đã duyệt (một đầu vẫn tính)."""
        res, Att = defaultdict(list), self.env['hr.attendance'].sudo()
        if not employee_ids:
            return res
        atts = Att.search([
            ('employee_id', 'in', employee_ids), ('state', '=', 'approved'),
            ('check_in', '<=', stop_dt),
            '|', ('check_out', '>=', start_dt), ('check_out', '=', False),
        ], order='employee_id, check_in')
        for a in atts:
            if a.check_in and start_dt <= a.check_in <= stop_dt:
                res[a.employee_id.id].append(self._normalize_dt(a.check_in))
            if a.check_out and start_dt <= a.check_out <= stop_dt:
                res[a.employee_id.id].append(self._normalize_dt(a.check_out))
        return res

    def _fetch_manual_attendance(self, employee_ids, start_dt, stop_dt):
        """Intervals hr.attendance (approved) đủ 2 đầu — dùng phủ segment."""
        res, Att = defaultdict(list), self.env['hr.attendance'].sudo()
        if not employee_ids:
            return res
        domain = expression.OR([
            [('employee_id', 'in', employee_ids), ('state', '=', 'approved'),
             ('check_in', '<=', stop_dt), ('check_out', '>=', start_dt)],
            [('employee_id', 'in', employee_ids), ('state', '=', 'approved'),
             ('check_in', '<=', start_dt), ('check_out', '>=', stop_dt)],
        ])
        for a in Att.search(domain, order='employee_id, check_in'):
            if not (a.check_in and a.check_out): continue
            s, e = max(a.check_in, start_dt), min(a.check_out, stop_dt)
            if s < e:
                res[a.employee_id.id].append((self._normalize_dt(s), self._normalize_dt(e)))
        return res

    def _fetch_leave_spans_for_alerts(self, employee_ids, start_dt, stop_dt):
        """Khoảng nghỉ cá nhân (validate) để trừ khi dựng cảnh báo."""
        res, Leave = defaultdict(list), self.env['hr.leave'].sudo()
        if not employee_ids:
            return res
        leaves = Leave.search([
            ('employee_id', 'in', employee_ids), ('state', '=', 'validate'),
            ('date_from', '<=', stop_dt), ('date_to', '>=', start_dt),
        ])
        for lv in leaves:
            s0 = self._normalize_dt(lv.date_from or (lv.request_date_from and datetime.combine(lv.request_date_from, time.min)))
            e0 = self._normalize_dt(lv.date_to   or (lv.request_date_to   and datetime.combine(lv.request_date_to,   time.max)))
            if s0 and e0 and s0 < e0:
                s0, e0 = max(s0, start_dt), min(e0, stop_dt)
                if s0 < e0:
                    res[lv.employee_id.id].append((s0, e0))
        for emp_id, spans in res.items():
            res[emp_id] = self._merge_intervals(spans)
        return res

    def _fetch_leaves(self, employee_ids, start_dt, stop_dt):
        """Khoảng nghỉ hr.leave (validate) — CẮT THEO SEGMENT làm việc."""
        Leave = self.env['hr.leave'].sudo()
        WET   = self.env['hr.work.entry.type'].sudo()
        res   = defaultdict(list)
        if not employee_ids:
            return res

        wet_leave = WET.search([('code', '=', 'LEAVE')], limit=1)

        def _norm(v, at_end=False):
            if not v: return None
            if isinstance(v, datetime): return self._normalize_dt(v)
            try:
                return self._normalize_dt(fields.Datetime.from_string(v))
            except Exception:
                try:
                    d = fields.Date.from_string(v)
                    return self._normalize_dt(datetime.combine(d, time.max if at_end else time.min)) if d else None
                except Exception:
                    return None

        leaves = Leave.search([
            ('employee_id', 'in', employee_ids),
            ('state', '=', 'validate'),
            ('date_from', '<=', stop_dt),
            ('date_to', '>=', start_dt),
        ])

        for lv in leaves:
            emp_id = lv.employee_id.id
            s0 = _norm(lv.date_from or lv.request_date_from, False)
            e0 = _norm(lv.date_to   or lv.request_date_to,   True)
            if not (s0 and e0 and s0 < e0):
                continue
            s0, e0 = max(s0, start_dt), min(e0, stop_dt)
            if not (s0 < e0):
                continue

            wet = getattr(lv.holiday_status_id, 'work_entry_type_id', False) or wet_leave
            if not wet:
                continue

            # cắt theo segment lịch
            Emp = self.env['hr.employee'].browse(emp_id)
            pol, otpol, cal = self._get_policies_and_calendar(emp_id)
            tz  = self._emp_tz(emp_id)
            cur, last = s0.date(), e0.date()
            while cur <= last:
                win = (max(s0, datetime.combine(cur, time.min)),
                       min(e0, datetime.combine(cur, time.max)))
                if not (win[0] < win[1]):
                    cur += timedelta(days=1); continue
                segs = self._get_day_segments(cal, cur, emp_tz=tz)
                if not segs:
                    cur += timedelta(days=1); continue
                for (cs, ce) in self._intersection_intervals([win], segs):
                    if cs < ce:
                        res[emp_id].append((cs, ce, wet.id, f"HR:{lv.id}"))
                cur += timedelta(days=1)
        return res

    # ======================================================================
    # 6) OVERTIME HELPERS
    # ======================================================================
    def _pick_rule_wet(self, rtype):
        Rule = self.env['smartbiz_hr.overtime_rule'].sudo()
        r = Rule.search([('type', '=', rtype)], order='priority desc, id asc', limit=1)
        return r.work_entry_type_id.id if r and r.work_entry_type_id else False

    def _day_calendar_leave_spans(self, emp_id, day_date):
        d0 = datetime.combine(day_date, time.min)
        d1 = datetime.combine(day_date, time.max)
        spans_typed = []
        for lv in self._markers_of_day(emp_id, day_date):
            if not getattr(lv, 'leave_type_id', False):
                continue
            s = max(self._normalize_dt(lv.date_from), d0)
            e = min(self._normalize_dt(lv.date_to),   d1)
            if s < e:
                spans_typed.append((s, e, lv.leave_type_id))
        plain = self._merge_intervals([(s, e) for (s, e, _t) in spans_typed])
        return plain, spans_typed

    def _resolve_ot_wet_for_piece(self, emp_id, day_date, ps, pe, segs, leave_plain, leave_typed):
        for (ls, le, ltype) in leave_typed:
            if ls <= ps and pe <= le:
                if ltype.overtime_rule_id and ltype.overtime_rule_id.work_entry_type_id:
                    return ltype.overtime_rule_id.work_entry_type_id.id
                return self._pick_rule_wet('leave_day') or False
        has_segs = bool(segs)
        return (self._pick_rule_wet('working_day') if has_segs else self._pick_rule_wet('non_working_day')) or False

    def _fetch_ot_request_windows_for_alerts(self, employee_ids, start_dt, stop_dt):
        """OT request windows cho cảnh báo (không phụ thuộc punch)."""
        res = defaultdict(list)
        if not employee_ids:
            return res
        OTL = self.env['smartbiz_hr.request_line'].sudo()
        lines = OTL.search([
            ('employee_id', 'in', employee_ids),
            ('state', '=', 'approved'),
            ('start_date', '<=', stop_dt),
            ('end_date', '>=', start_dt),
        ])
        for ln in lines:
            emp_id = ln.employee_id.id
            s0 = max(self._normalize_dt(ln.start_date), start_dt)
            e0 = min(self._normalize_dt(ln.end_date),   stop_dt)
            if not (s0 and e0 and s0 < e0):
                continue
            cur = s0.date()
            last = e0.date()
            while cur <= last:
                day_s = max(s0, datetime.combine(cur, time.min))
                day_e = min(e0, datetime.combine(cur, time.max))
                if day_s < day_e:
                    res[emp_id].append((day_s, day_e))
                cur += timedelta(days=1)
        for emp_id, ivs in res.items():
            res[emp_id] = self._merge_intervals(ivs)
        return res

    def _adjust_ot_windows_by_punches(self, req_windows, pol, punches, day_level=True):
        """
        Điều chỉnh các khoảng OT theo mốc chấm khi reconcile=True.
        - Nếu must_check_break_time=True: IN/OUT cho TỪNG CỬA SỔ OT (không dùng VM/VE).
        - Nếu day_level (must_check_break_time=False): chỉ IN ở OT đầu và OUT ở OT cuối.
        - Không sinh late/early cho OT.
        """
        if not req_windows:
            return []
        wins = []
        for (s, e) in req_windows:
            s = self._normalize_dt(s); e = self._normalize_dt(e)
            if s and e and s < e:
                wins.append((s, e))
        if not wins:
            return []
        wins.sort(key=lambda x: x[0])
        def mm(x): return int(x or 0)
        before_in  = timedelta(minutes=mm(pol.minutes_before_check_in))
        after_in   = timedelta(minutes=mm(pol.minutes_after_check_in))
        before_out = timedelta(minutes=mm(pol.minutes_before_check_out))
        after_out  = timedelta(minutes=mm(pol.minutes_after_check_out))
        pts = sorted({self._normalize_dt(p) for p in (punches or []) if self._normalize_dt(p)})

        def eff_start(start):
            if not pol.must_check_in:
                return start
            in_win = (start - before_in, start + after_in)
            cand = [p for p in pts if in_win[0] <= p <= in_win[1]]
            if not cand:
                return None
            v1 = min(cand)
            return start if v1 <= start else v1  # không dùng VM
        def eff_end(end):
            if not pol.must_check_out:
                return end
            out_win = (end - before_out, end + after_out)
            cand = [p for p in pts if out_win[0] <= p <= out_win[1]]
            if not cand:
                return None
            r1 = max(cand)
            return end if r1 >= end else r1  # không dùng VE

        out = []
        if not day_level or getattr(pol, 'must_check_break_time', False):
            # mỗi cửa sổ tự tính IN/OUT
            for (s0, e0) in wins:
                s_eff = eff_start(s0)
                e_eff = eff_end(e0)
                if s_eff and e_eff and s_eff < e_eff:
                    out.append((s_eff, e_eff))
            return out

        # day-level: chỉ đầu & cuối
        s0, e0 = wins[0]
        sn, en = wins[-1]
        start_eff = eff_start(s0)
        end_eff   = eff_end(en)
        if len(wins) == 1:
            if start_eff and end_eff and start_eff < end_eff:
                out.append((max(start_eff, s0), min(end_eff, e0)))
            return out
        # First
        if start_eff:
            s_eff = max(start_eff, s0)
            if s_eff < e0:
                out.append((s_eff, e0))
        # Middle
        for (ws, we) in wins[1:-1]:
            out.append((ws, we))
        # Last
        if end_eff:
            e_eff = min(end_eff, en)
            if wins[-1][0] < e_eff:
                out.append((wins[-1][0], e_eff))
        return [(s, e) for (s, e) in out if s < e]

    def _fetch_ot_lines(self, employee_ids, start_dt, stop_dt, daily_by_emp=None):
        """
        Trả về {emp_id: [(s,e, wetype_id, line_id)]}.
        - Với reconcile=True:
          * Nếu must_check_break_time=True: điều chỉnh IN/OUT từng cửa sổ OT theo mốc punch (không dùng muộn/sớm).
          * Nếu False: chỉ điều chỉnh cửa sổ đầu/cuối (IN đầu, OUT cuối).
        - OT đè CAL; nếu là working day thì cắt phần trùng segment lịch.
        """
        res = defaultdict(list)
        if not employee_ids:
            return res

        OTL = self.env['smartbiz_hr.request_line'].sudo()
        # punches trong ngày (daily + manual-1đ) + endpoints attendance FULL
        manual_full_all = self._fetch_manual_attendance(employee_ids, start_dt, stop_dt)
        manual_pts_all  = self._fetch_manual_punch_times(employee_ids, start_dt, stop_dt)
        daily_pts_all   = daily_by_emp or defaultdict(list)

        # Gom yêu cầu theo emp/day
        per_day = defaultdict(list)  # (emp, day) -> [(s,e,line_id)]
        lines = OTL.search([
            ('employee_id', 'in', employee_ids),
            ('state', '=', 'approved'),
            ('start_date', '<=', stop_dt),
            ('end_date', '>=', start_dt),
        ], order='employee_id,start_date,id')

        for ln in lines:
            emp_id = ln.employee_id.id
            s0, e0 = max(self._normalize_dt(ln.start_date), start_dt), min(self._normalize_dt(ln.end_date), stop_dt)
            if not (s0 and e0 and s0 < e0):
                continue
            cur = s0.date(); last = e0.date()
            while cur <= last:
                win = (max(s0, datetime.combine(cur, time.min)),
                       min(e0, datetime.combine(cur, time.max)))
                if win[0] < win[1]:
                    per_day[(emp_id, cur)].append((win[0], win[1], ln.id))
                cur += timedelta(days=1)

        def merge_day_windows_with_id(wlist):
            if not wlist:
                return []
            wlist = sorted(wlist, key=lambda x: (x[0], x[1]))
            out = []
            cs, ce, lid = wlist[0]
            for (s, e, li) in wlist[1:]:
                if s < ce:
                    if e > ce:
                        ce = e
                else:
                    out.append((cs, ce, lid))
                    cs, ce, lid = s, e, li
            out.append((cs, ce, lid))
            return out

        for (emp_id, day) in sorted(per_day.keys(), key=lambda k: (k[0], k[1])):
            raw = merge_day_windows_with_id(per_day[(emp_id, day)])
            if not raw:
                continue

            pol, otpol, cal = self._get_policies_and_calendar(emp_id, day)
            tz = self._emp_tz(emp_id, day)
            segs = self._get_day_segments(cal, day, emp_tz=tz)
            cal_plain, cal_typed = self._day_calendar_leave_spans(emp_id, day)

            punches = []
            punches += list(daily_pts_all.get(emp_id, []))
            punches += list(manual_pts_all.get(emp_id, []))
            for (fs, fe) in (manual_full_all.get(emp_id, []) or []):
                if fs: punches.append(fs)
                if fe: punches.append(fe)
            punches = [p for p in punches if p and datetime.combine(day, time.min) <= p <= datetime.combine(day, time.max)]

            req_windows = [(s, e) for (s, e, _lid) in raw]

            if otpol and getattr(otpol, 'reconcile_with_attendance', False):
                eff_windows = self._adjust_ot_windows_by_punches(
                    req_windows, pol, punches,
                    day_level=not getattr(pol, 'must_check_break_time', False)
                )
            else:
                eff_windows = list(req_windows)

            if not eff_windows:
                continue

            for (ow_s, ow_e) in eff_windows:
                if not (ow_s and ow_e and ow_s < ow_e):
                    continue
                # chọn line_id tham chiếu
                ref_id = None
                for (s, e, lid) in raw:
                    if max(s, ow_s) < min(e, ow_e):
                        ref_id = lid; break

                inside_leave = self._intersection_intervals([(ow_s, ow_e)], cal_plain)
                for (ps, pe) in inside_leave:
                    wet_id = self._resolve_ot_wet_for_piece(emp_id, day, ps, pe, segs, cal_plain, cal_typed)
                    if wet_id and ps < pe:
                        res[emp_id].append((ps, pe, wet_id, ref_id or 0))

                rest = self._subtract_intervals([(ow_s, ow_e)], cal_plain)
                pieces = []
                if segs:
                    for (rs, re) in rest:
                        pieces += self._subtract_intervals([(rs, re)], segs)  # ngoài giờ làm
                else:
                    pieces = rest
                for (ps, pe) in pieces:
                    if ps < pe:
                        wet_id = self._resolve_ot_wet_for_piece(emp_id, day, ps, pe, segs, cal_plain, cal_typed)
                        if wet_id:
                            res[emp_id].append((ps, pe, wet_id, ref_id or 0))

        return res

    # ======================================================================
    # 7) CONTRACT HELPERS & POLICY PICKER
    # ======================================================================
    def _best_contract_on(self, emp_id, day_date):
        Contract = self.env['hr.contract'].sudo()
        day = day_date if isinstance(day_date, dt_date) else (day_date.date() if isinstance(day_date, datetime) else fields.Date.today())
        rec = Contract.search([
            ('employee_id', '=', emp_id), ('date_start', '<=', day),
            '|', ('date_end', '=', False), ('date_end', '>=', day),
        ], limit=1, order='date_start desc')
        if not rec:
            rec = Contract.search([('employee_id', '=', emp_id), ('date_start', '<=', day)], limit=1, order='date_start desc')
        if not rec:
            rec = Contract.search([('employee_id', '=', emp_id)], limit=1, order='date_start desc')
        return rec or False

    def _contract_spans_for_day(self, emp_id, day_date):
        Contract = self.env['hr.contract'].sudo()
        day = day_date if isinstance(day_date, dt_date) else day_date.date()
        d0, d1 = datetime.combine(day, time.min), datetime.combine(day, time.max)
        cons = Contract.search([
            ('employee_id', '=', emp_id), ('state', '=', 'open'),
            ('date_start', '<=', day), '|', ('date_end', '=', False), ('date_end', '>=', day),
        ], order='date_start asc')
        spans = []
        for c in cons:
            cs = max(datetime.combine(max(c.date_start, day), time.min), d0)
            ce = min(datetime.combine((c.date_end or day), time.max), d1)
            if cs < ce:
                spans.append((self._normalize_dt(cs), self._normalize_dt(ce), c.id))
        return spans

    def _iter_contract_slices(self, emp_id, day_date, s, e):
        """Chẻ (s,e) theo ranh giới HĐ; nếu spans chồng lấn → gộp về HĐ tốt nhất."""
        s, e = self._normalize_dt(s), self._normalize_dt(e)
        if not (s and e and s < e):
            return
        spans = self._contract_spans_for_day(emp_id, day_date)
        if not spans:
            best = self._best_contract_on(emp_id, day_date)
            if best:
                yield (s, e, best.id)
            return
        has_overlap = any(not (spans[i][1] <= spans[i + 1][0]) for i in range(len(spans) - 1))
        if has_overlap:
            best = self._best_contract_on(emp_id, day_date) or spans[-1][2]
            _logger.warning("Overlapping contracts for emp_id=%s on %s -> fold into cid=%s", emp_id, day_date, best and best.id)
            yield (s, e, best and best.id)
            return
        for (cs, ce, cid) in spans:
            ss, ee = max(s, cs), min(e, ce)
            if ss < ee:
                yield (ss, ee, cid)

    def _get_policies_and_calendar(self, emp_id, day_date=None):
        """
        Trả về (attendance_policy, overtime_policy, resource_calendar) cho nhân viên.
        - ƯU TIÊN lịch từ HỢP ĐỒNG đang dùng để tính toán ngày 'day_date' nếu HĐ có resource_calendar_id.
        - Luôn có fallback về default policies và lịch chuẩn.
        """
        att_default, ot_default, calc_default = self._ensure_default_policies()
        Emp = self.env['hr.employee'].browse(emp_id)

        # contract theo ngày
        best = self._best_contract_on(emp_id, day_date or fields.Date.context_today(self))
        contract = best or Emp.contract_id

        if not contract or not contract.calculation_policy_id:
            if contract:
                try:
                    contract.sudo().write({'calculation_policy_id': calc_default.id})
                except Exception:
                    pass
            pol   = calc_default.attendance_policy_id or att_default
            otpol = calc_default.overtime_policy_id  or ot_default
        else:
            pol   = contract.calculation_policy_id.attendance_policy_id or att_default
            otpol = contract.calculation_policy_id.overtime_policy_id  or ot_default

        # LỊCH: ưu tiên lịch của HĐ; sau đó lịch của nhân viên; sau đó lịch chuẩn hệ thống
        cal = getattr(contract, 'resource_calendar_id', False) or Emp.resource_calendar_id
        if not cal:
            try:
                cal = self.env.ref('resource.resource_calendar_std')
            except Exception:
                cal = Emp.resource_calendar_id
        return pol, otpol, cal

    # ======================================================================
    # 8) UPSERT / PURGE / VALIDATE
    # ======================================================================
    def _advisory_lock_for_key(self, token):
        import hashlib
        d = hashlib.sha1((token or '').encode('utf-8')).digest()
        k1 = int.from_bytes(d[0:4], 'big', signed=True)
        k2 = int.from_bytes(d[4:8], 'big', signed=True)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (k1, k2))

    def _nudge_1s_if_border_equal(self, emp_id, s, e):
        """Nếu WE khác bắt đầu/kết thúc đúng biên → đẩy 1s để né xung đột."""
        if not (s and e and s < e):
            return s, e
        one = timedelta(seconds=1)
        prev = self.sudo().search([('employee_id', '=', emp_id), ('date_stop', '=', s), ('state', '!=', 'cancelled')], limit=1)
        if prev: s = s + one
        nxt = self.sudo().search([('employee_id', '=', emp_id), ('date_start', '=', e), ('state', '!=', 'cancelled')], limit=1)
        if nxt: e = e - one
        for _ in range(2):
            if s >= e: break
            bump = False
            if self.sudo().search([('employee_id', '=', emp_id), ('date_stop', '=', s)], limit=1):
                s = s + one; bump = True
            if self.sudo().search([('employee_id', '=', emp_id), ('date_start', '=', e)], limit=1):
                e = e - one; bump = True
            if not bump: break
        return s, e

    def _upsert(self, emp_id, day_date, s, e, wetype_id, source, source_key, contract_id=None):
        """Ghi/ghi-đè WE engine bằng (source, source_key)."""
        if not (wetype_id and s and e):
            return
        s = self._normalize_dt(s); e = self._normalize_dt(e)
        if not (s and e and s < e):
            return
        self._advisory_lock_for_key(f"{source}:{source_key}")
        s, e = self._nudge_1s_if_border_equal(emp_id, s, e)
        if not (s and e and s < e):
            return

        rec = self.sudo().search([('source', '=', source), ('source_key', '=', source_key)], limit=1)
        cid = contract_id or (self._best_contract_on(emp_id, day_date) and self._best_contract_on(emp_id, day_date).id)
        if not cid:
            return

        vals = {
            'name': f'{source}:{day_date}',
            'employee_id': emp_id,
            'contract_id': cid,
            'work_entry_type_id': wetype_id,
            'date_start': s,
            'date_stop': e,
            'state': 'draft',
            'active': True,
            'source': source,
            'source_key': source_key,
            'work_day': day_date,
        }

        def _do_write_or_create():
            if rec:
                rec.sudo().write(vals)
            else:
                with self.env.cr.savepoint():
                    self.sudo().create(vals)

        try:
            _do_write_or_create()
        except Exception as ex:
            msg = str(ex)
            if ('uniq_source_key' in msg) or ('unique constraint' in msg and 'source_key' in msg) or ('duplicate key value' in msg and 'source_key' in msg):
                other = self.sudo().search([('source', '=', source), ('source_key', '=', source_key)], limit=1)
                with self.env.cr.savepoint():
                    if other:
                        other.sudo().write(vals)
                    else:
                        self.sudo().create(vals)
                return
            if ('work_entries_no_validated_conflict' in msg) or ('ExclusionViolation' in msg):
                overlap = self.sudo().search([
                    ('employee_id', '=', emp_id),
                    ('date_start', '<', e),
                    ('date_stop', '>', s),
                    '|', ('source', 'in', getattr(self, 'ENGINE_SOURCES', ())), ('source', '=', False),
                ])
                if overlap:
                    for we in overlap:
                        try:
                            we.sudo().unlink()
                        except Exception:
                            try:
                                we.sudo().write({'state': 'draft'})
                                we.sudo().unlink()
                            except Exception:
                                pass
                with self.env.cr.savepoint():
                    again = self.sudo().search([('source', '=', source), ('source_key', '=', source_key)], limit=1)
                    if again:
                        again.sudo().write(vals)
                    else:
                        self.sudo().create(vals)
                return
            raise

    def _bulk_validate_engine(self, emp_id, day_date):
        domain = [
            ('employee_id', '=', emp_id),
            ('work_day', '=', day_date),
            ('state', '=', 'draft'),
            ('source', 'in', getattr(self, 'ENGINE_SOURCES', self.ENGINE_SOURCES)),
        ]
        recs = self.sudo().search(domain)
        if recs:
            recs.sudo().write({'state': 'validated'})

    def _purge_stale(self, emp_id, day_date, valid_keys_by_source):
        existing = self.search([
            ('employee_id', '=', emp_id), ('work_day', '=', day_date),
            ('source', 'in', list(valid_keys_by_source.keys())),
        ])
        for we in existing:
            if we.source_key not in valid_keys_by_source.get(we.source, set()):
                try:
                    we.sudo().unlink()
                except Exception:
                    try:
                        we.sudo().write({'state': 'draft'})
                        we.sudo().unlink()
                    except Exception:
                        pass

    # ======================================================================
    # 9) ALERTS — cron (reconcile OT coi OT windows là segment phải chấm)
    # ======================================================================
    def _has_punch_in_window(self, punches, win):
        if not win:
            return True
        w0, w1 = win
        return any(w0 <= t <= w1 for t in punches)

    def _alert_close_state(self):
        Alert = self.env['smartbiz_hr.attendance_alert']
        sel = [s[0] for s in (Alert._fields.get('state').selection or [])]
        if 'resolved' in sel:
            return 'resolved'
        for cand in ['done', 'closed', 'processed']:
            if cand in sel:
                return cand
        for s in sel:
            if s != 'open':
                return s
        return 'open'

    def _set_alert_state(self, emp_id, date_dt, alert_type, action, block_start=None, block_end=None, note=''):
        Alert = self.env['smartbiz_hr.attendance_alert'].sudo()
        close_state = self._alert_close_state()
        day_start, day_end = datetime.combine(date_dt.date(), time.min), datetime.combine(date_dt.date(), time.max)
        base_dom = [('employee_id', '=', emp_id), ('alert_type', '=', alert_type), ('date', '>=', day_start), ('date', '<=', day_end)]

        if action == 'open':
            rec = Alert.search(base_dom, order='id desc', limit=1)
            vals = {'employee_id': emp_id, 'date': date_dt, 'alert_type': alert_type, 'state': 'open'}
            if block_start is not None: vals['block_start'] = block_start
            if block_end   is not None: vals['block_end']   = block_end
            if note: vals['note'] = note
            (rec and rec.write(vals)) or Alert.create(vals)
            return

        if close_state != 'open':
            closables = Alert.search(base_dom + [('state', 'in', ['open', 'ack'])])
            if closables:
                closables.write({'state': close_state})

    @api.model
    def cron_build_attendance_alerts(self, days_back=1, max_emps_per_tick=5000):
        now_utc = datetime.utcnow()
        today = fields.Date.context_today(self)
        d0 = today - timedelta(days=int(days_back or 0))
        d1 = today

        emp_ids = self._get_employees_changed(d0, d1, limit=max_emps_per_tick)
        if not emp_ids:
            return True

        ot_req_all = self._fetch_ot_request_windows_for_alerts(emp_ids,
                                                               datetime.combine(d0, time.min),
                                                               datetime.combine(d1, time.max))

        day = d0
        while day <= d1:
            active_ids = self._active_employees_on(day, emp_ids)
            if not active_ids:
                day += timedelta(days=1)
                continue

            start_dt = datetime.combine(day, time.min)
            stop_dt  = datetime.combine(day, time.max)

            daily_times = self._fetch_daily_punch_times(active_ids, start_dt, stop_dt)
            manual_iv   = self._fetch_manual_attendance(active_ids, start_dt, stop_dt)
            manual_pts  = self._fetch_manual_punch_times(active_ids, start_dt, stop_dt)
            personal_leave_spans = self._fetch_leave_spans_for_alerts(active_ids, start_dt, stop_dt)

            for emp_id in active_ids:
                pol, otpol, cal = self._get_policies_and_calendar(emp_id, day)
                if not pol or not (pol.must_check_in or pol.must_check_out or pol.must_check_break_time):
                    self._set_alert_state(emp_id, start_dt, 'missing_check_in',  'close')
                    self._set_alert_state(emp_id, start_dt, 'missing_check_out', 'close')
                    continue

                tz   = self._emp_tz(emp_id, day)
                segs_sched = self._get_day_segments(cal, day, emp_tz=tz)  # [(V0,R0)]

                ot_req_segments = []
                if otpol and getattr(otpol, 'reconcile_with_attendance', False):
                    reqs = [(max(s, start_dt), min(e, stop_dt))
                            for (s, e) in (ot_req_all.get(emp_id, []) or [])
                            if s < e and not (e <= start_dt or s >= stop_dt)]
                    ot_req_segments = self._merge_intervals(reqs)

                segments_tagged = []
                for (s, e) in segs_sched:      segments_tagged.append((s, e, 'sched'))
                for (s, e) in ot_req_segments: segments_tagged.append((s, e, 'ot'))
                segments_tagged.sort(key=lambda x: x[0])

                cal_plain, _cal_typed = self._day_calendar_leave_spans(emp_id, day)
                leave_cover = self._merge_intervals(cal_plain + list(personal_leave_spans.get(emp_id, [])))

                def cut_leave_tagged(tagged):
                    out = []
                    for (s, e, k) in tagged:
                        for (cs, ce) in self._subtract_intervals([(s, e)], leave_cover):
                            if cs < ce:
                                out.append((cs, ce, k))
                    return out

                segments_tagged = cut_leave_tagged(segments_tagged)

                manual_full = [(max(s, start_dt), min(e, stop_dt))
                               for (s, e) in manual_iv.get(emp_id, []) if s and e and s < e]
                manual_full = self._merge_intervals(manual_full)

                segments_eff = []
                for (V0, R0, kind) in segments_tagged:
                    rem = self._subtract_intervals([(V0, R0)], manual_full)
                    for (rs, re) in rem:
                        segments_eff.append((rs, re, kind))

                if not segments_eff:
                    self._set_alert_state(emp_id, start_dt, 'missing_check_in',  'close')
                    self._set_alert_state(emp_id, start_dt, 'missing_check_out', 'close')
                    continue

                def mm(x): return int(x or 0)
                in_before  = timedelta(minutes=mm(pol.minutes_before_check_in))
                in_after   = timedelta(minutes=mm(pol.minutes_after_check_in))
                out_before = timedelta(minutes=mm(pol.minutes_before_check_out))
                out_after  = timedelta(minutes=mm(pol.minutes_after_check_out))

                punches_all = sorted(set(
                    [t for t in daily_times.get(emp_id, []) if start_dt <= t <= stop_dt] +
                    [t for t in manual_pts.get(emp_id, []) if start_dt <= t <= stop_dt]
                ))

                ot_indices = [i for i, (_, _, k) in enumerate(segments_eff) if k == 'ot']
                first_ot_idx = ot_indices[0] if ot_indices else None
                last_ot_idx  = ot_indices[-1] if ot_indices else None

                missing_in_any = False
                missing_out_any = False
                in_block = out_block = None
                in_note_win = out_note_win = None

                for idx, (V0, R0, kind) in enumerate(segments_eff):
                    if pol.must_check_break_time:
                        require_in  = bool(pol.must_check_in)
                        require_out = bool(pol.must_check_out)
                    else:
                        if kind == 'sched':
                            require_in  = bool(pol.must_check_in)  and (idx == 0)
                            require_out = bool(pol.must_check_out) and (idx == len(segments_eff) - 1)
                            if not require_out and (idx + 1 < len(segments_eff)) and segments_eff[idx + 1][2] == 'ot':
                                require_out = bool(pol.must_check_out)  # biên SCHED→OT
                        else:  # 'ot'
                            if otpol and getattr(otpol, 'reconcile_with_attendance', False):
                                require_in  = bool(pol.must_check_in)  and (idx == first_ot_idx)
                                require_out = bool(pol.must_check_out) and (idx == last_ot_idx)
                            else:
                                require_in = require_out = False

                    if require_in:
                        in_win = (V0 - in_before, V0 + in_after)
                        if now_utc > in_win[1] and not self._has_punch_in_window(punches_all, in_win):
                            if not missing_in_any:
                                missing_in_any = True
                                in_block = (V0, R0); in_note_win = in_win

                    if require_out:
                        out_win = (R0 - out_before, R0 + out_after)
                        if now_utc > out_win[1] and not self._has_punch_in_window(punches_all, out_win):
                            if not missing_out_any:
                                missing_out_any = True
                                out_block = (V0, R0); out_note_win = out_win

                if missing_in_any and in_block:
                    V0, R0 = in_block
                    note = _("Thiếu chấm VÀO: %s → %s") % (self._fmt_tz(in_note_win[0], tz), self._fmt_tz(in_note_win[1], tz))
                    self._set_alert_state(emp_id, V0, 'missing_check_in', 'open', block_start=V0, block_end=R0, note=note)
                else:
                    self._set_alert_state(emp_id, start_dt, 'missing_check_in', 'close')

                if missing_out_any and out_block:
                    V0, R0 = out_block
                    note = _("Thiếu chấm RA: %s → %s") % (self._fmt_tz(out_note_win[0], tz), self._fmt_tz(out_note_win[1], tz))
                    self._set_alert_state(emp_id, R0, 'missing_check_out', 'open', block_start=V0, block_end=R0, note=note)
                else:
                    self._set_alert_state(emp_id, start_dt, 'missing_check_out', 'close')

            day += timedelta(days=1)
        return True

    # ======================================================================
    # 10) STACK RESOLVE ƯU TIÊN & RECOMPUTE ENGINE
    # ======================================================================
    def _priority_key(self, kind, ctx=None):
        base = {
            'overtime':       100,
            'leave_company':   80,
            'leave_personal':  70,
            'normal_manual':   50,
            'normal_daily':    40,
            'early':           30,
            'late':            20,
        }.get(kind, 0)
        if kind == 'leave_company' and ctx:
            base += int((ctx.get('rule_priority') or 0))
        return base

    def _stack_resolve(self, layers):
        """
        layers: list[{'kind': <str>, 'items': [(s,e,wet_id,key,cid)], 'priority_ctx': {...}}]
        Trả về: [(s,e,wet_id,key,cid,kind)] đã loại trừ chồng lấn theo ưu tiên giảm dần.
        """
        enriched = []
        for layer in layers or []:
            k = layer.get('kind'); ctx = layer.get('priority_ctx') or {}
            enriched.append((self._priority_key(k, ctx), layer))
        enriched.sort(key=lambda x: x[0], reverse=True)

        taken = []   # [(s,e)]
        plan  = []
        for _score, layer in enriched:
            keep = []
            for item in layer.get('items', []):
                if not item or len(item) < 5:
                    continue
                s, e, wet_id, key, cid = item
                if not (s and e and wet_id and cid and s < e):
                    continue
                remain = self._subtract_intervals([(s, e)], taken)
                for (rs, re) in remain:
                    if rs < re:
                        keep.append((rs, re, wet_id, key, cid))
            for rec in keep:
                plan.append((*rec, layer['kind']))
            taken = self._merge_intervals(taken + [(s, e) for (s, e, *_r) in keep])
        return plan

    def _active_employees_on(self, day_date, employee_ids):
        if not employee_ids:
            return []
        Contract = self.env['hr.contract'].sudo()
        day = day_date if isinstance(day_date, dt_date) else day_date.date()
        rows = Contract.read_group(
            domain=[('employee_id', 'in', employee_ids), ('state', '=', 'open'),
                    ('date_start', '<=', day), '|', ('date_end', '=', False), ('date_end', '>=', day)],
            fields=['employee_id'], groupby=['employee_id'], lazy=False
        )
        return [r['employee_id'][0] for r in rows if r.get('employee_id')]

    def _preclean_day(self, day_date, employee_ids):
        if not employee_ids:
            return
        start_dt, stop_dt = datetime.combine(day_date, time.min), datetime.combine(day_date, time.max)
        domain = [
            ('employee_id', 'in', employee_ids),
            ('date_start', '<=', stop_dt), ('date_stop', '>=', start_dt),
            ('source', 'in', self.ENGINE_SOURCES),
        ]
        old = self.sudo().search(domain)
        if old:
            for we in old:
                try:
                    we.sudo().unlink()
                except Exception:
                    try:
                        we.sudo().write({'state': 'draft'})
                        we.sudo().unlink()
                    except Exception:
                        pass

    @api.model
    def cron_recompute_from_sources(self, days_back=10, max_emps_per_tick=2000):
        today = fields.Date.context_today(self)
        d0, d1 = today - timedelta(days=int(days_back)), today
        emp_ids = self._get_employees_changed(d0, d1, limit=max_emps_per_tick)
        if not emp_ids:
            return True
        d = d0
        while d <= d1:
            self._recompute_day(d, emp_ids)
            d += timedelta(days=1)
        return True

    def _finalize_validate_day(self, emp_id, day_date):
        d0 = datetime.combine(day_date, time.min)
        d1 = datetime.combine(day_date, time.max)
        recs = self.sudo().search([
            ('employee_id', '=', emp_id),
            ('date_start', '<=', d1),
            ('date_stop', '>=', d0),
            ('active', '=', True),
        ])
        if recs:
            recs._reset_conflicting_state()
            recs.write({'state': 'draft'})
            recs.action_validate()

    @api.model
    def _recompute_day(self, day_date, employee_ids):
        if isinstance(day_date, datetime):
            day_date = day_date.date()
        start_dt = datetime.combine(day_date, time.min)
        stop_dt  = datetime.combine(day_date, time.max)

        employee_ids = self._active_employees_on(day_date, employee_ids)
        if not employee_ids:
            return True

        self._preclean_day(day_date, employee_ids)

        daily_times   = self._fetch_daily_punch_times(employee_ids, start_dt, stop_dt)
        manual_att    = self._fetch_manual_attendance(employee_ids, start_dt, stop_dt)
        leave_persons = self._fetch_leaves(employee_ids, start_dt, stop_dt)
        ot_lines      = self._fetch_ot_lines(employee_ids, start_dt, stop_dt, daily_times)

        for emp_id in employee_ids:
            pol, otpol, cal = self._get_policies_and_calendar(emp_id, day_date)
            emp_tz   = self._emp_tz(emp_id, day_date)
            segments = self._get_day_segments(cal, day_date, emp_tz=emp_tz)
            day_span = [(start_dt, stop_dt)]

            # CAL của công ty (đầy đủ)
            cal_plain_full, cal_typed_full = self._fetch_company_calendar_leaves_for_day(emp_id, day_date)
            cal_wes, cal_spans = [], []
            wet_leave_fallback = self.env['hr.work.entry.type'].sudo().search([('code', '=', 'LEAVE')], limit=1)
            for (s, e, wet_id, token) in cal_typed_full:
                if not (s and e and s < e): continue
                wet_eff = wet_id or (wet_leave_fallback and wet_leave_fallback.id)
                if not wet_eff: continue
                any_yield = False
                for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, s, e):
                    key = f"CAL:{emp_id}:{cid}:{token}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                    cal_wes.append((ss, ee, wet_eff, key, cid)); any_yield = True
                if not any_yield:
                    cid = self._best_contract_on(emp_id, day_date)
                    if cid:
                        key = f"CAL:{emp_id}:{cid.id}:{token}:{day_date}:{int(s.timestamp())}-{int(e.timestamp())}"
                        cal_wes.append((s, e, wet_eff, key, cid.id))
                cal_spans.append((s, e))
            cal_spans = self._merge_intervals(cal_spans)

            # LEAVE cá nhân (cắt CAL)
            person_lv_raw = (leave_persons.get(emp_id, []) or [])
            person_lv_kept = []
            for (s, e, wet_id, leave_id) in person_lv_raw:
                s, e = max(s, start_dt), min(e, stop_dt)
                if not (s and e and s < e and wet_id): continue
                for (rs, re) in self._subtract_intervals([(s, e)], cal_spans):
                    if rs < re:
                        person_lv_kept.append((rs, re, wet_id, leave_id))
            person_spans = self._merge_intervals([(s, e) for (s, e, _w, _id) in person_lv_kept])

            # MANUAL intervals FULL (đủ 2 đầu)
            manual_full = [(max(s, start_dt), min(e, stop_dt))
                           for (s, e) in manual_att.get(emp_id, [])
                           if s and e and s < e]
            manual_in_segments = self._intersection_intervals(manual_full, segments)
            manual_in_segments = self._merge_intervals(self._intersection_intervals(manual_in_segments, day_span))

            # DAILY punches & NORMAL theo segment
            manual_pts  = self._fetch_manual_punch_times([emp_id], start_dt, stop_dt)
            daily_pure  = list(daily_times.get(emp_id, []))
            manual_zero = manual_pts.get(emp_id, [])
            daily_total = sorted(set(daily_pure + manual_zero))

            normal_from_daily, late_base, early_base = self._compute_from_segments(daily_total, segments, pol)
            normal_from_daily = self._intersection_intervals(normal_from_daily, day_span)
            normal_from_daily = self._subtract_intervals(normal_from_daily, manual_in_segments)

            # LATE/EARLY theo tổng punch (chỉ khi VM/VE > 0 trong _compute_from_segments)
            punch_all = sorted(set(list(daily_times.get(emp_id, [])) +
                                   [t for pair in manual_att.get(emp_id, []) for t in pair if t]))
            _unused, late_iv, early_iv = self._compute_from_segments(punch_all, segments, pol)
            late_iv  = self._intersection_intervals(late_iv,  day_span)
            early_iv = self._intersection_intervals(early_iv, day_span)

            # OT (đè CAL, nhưng trừ LEAVE cá nhân)
            ot_intv = ot_lines.get(emp_id, [])
            ot_only = []
            for (s, e, wet, line_id) in ot_intv:
                s, e = max(s, start_dt), min(e, stop_dt)
                if not (s and e and s < e): continue
                kept = self._subtract_intervals([(s, e)], person_spans)
                for (ks, ke) in kept:
                    if ks < ke:
                        ot_only.append((ks, ke, wet, line_id))

            # Khối chặn NORMAL/LATE/EARLY = CAL + LEAVE + OT
            block_for_normal = self._merge_intervals(
                cal_spans + person_spans + [(s, e) for (s, e, _w, _i) in ot_only]
            )
            normal_after_leave = self._subtract_intervals(normal_from_daily, block_for_normal)
            manual_after_leave = self._subtract_intervals(manual_in_segments, block_for_normal)

            # ====== STACK LAYERS ======
            wetype_normal = pol.normal_work_type_id.id if pol and pol.normal_work_type_id else False

            layers = []

            # OT
            items_ot = []
            for (s, e, wet_id, line_id) in ot_only:
                for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, s, e):
                    key = f"OT:{line_id}:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                    items_ot.append((ss, ee, wet_id, key, cid))
            if items_ot:
                layers.append({'kind': 'overtime', 'items': items_ot})

            # CAL (leave company)
            items_cal = [(ss, ee, wet_id, key, cid) for (ss, ee, wet_id, key, cid) in cal_wes]
            if items_cal:
                layers.append({'kind': 'leave_company', 'items': items_cal, 'priority_ctx': {'rule_priority': 30}})

            # LEAVE cá nhân
            items_lv = []
            for (s, e, wet_id, leave_id) in person_lv_kept:
                for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, s, e):
                    key = f"LEAVE:{leave_id}:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                    items_lv.append((ss, ee, wet_id, key, cid))
            if items_lv:
                layers.append({'kind': 'leave_personal', 'items': items_lv})

            # EARLY / LATE (đã giới hạn VM/VE trong compute)
            if pol and pol.early_work_type_id:
                items_e = []
                for (s, e) in early_iv:
                    for (cs, ce) in self._subtract_intervals([(s, e)], block_for_normal):
                        for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, cs, ce):
                            key = f"EARLY:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                            items_e.append((ss, ee, pol.early_work_type_id.id, key, cid))
                if items_e:
                    layers.append({'kind': 'early', 'items': items_e})

            if pol and pol.late_work_type_id:
                items_l = []
                for (s, e) in late_iv:
                    for (cs, ce) in self._subtract_intervals([(s, e)], block_for_normal):
                        for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, cs, ce):
                            key = f"LATE:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                            items_l.append((ss, ee, pol.late_work_type_id.id, key, cid))
                if items_l:
                    layers.append({'kind': 'late', 'items': items_l})

            # MANUAL NORMAL
            if wetype_normal:
                items_nm = []
                for (s, e) in manual_after_leave:
                    for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, s, e):
                        key = f"MAN:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                        items_nm.append((ss, ee, wetype_normal, key, cid))
                if items_nm:
                    layers.append({'kind': 'normal_manual', 'items': items_nm})

            # DAILY NORMAL
            if wetype_normal:
                items_dn = []
                has_zero = bool(manual_zero)
                has_daily = bool(daily_pure)
                daily_src = 'manual_daily' if (has_zero and not has_daily) else 'daily_attendance'
                prefix    = 'MDLY' if daily_src == 'manual_daily' else 'DAILY'
                for (s, e) in self._subtract_intervals(normal_after_leave, []):
                    for ss, ee, cid in self._iter_contract_slices(emp_id, day_date, s, e):
                        key = f"{prefix}:{emp_id}:{cid}:{day_date}:{int(ss.timestamp())}-{int(ee.timestamp())}"
                        items_dn.append((ss, ee, wetype_normal, key, cid))
                if items_dn:
                    layers.append({'kind': 'normal_daily', 'items': items_dn})

            # Resolve không chồng lấn theo ưu tiên
            plan = self._stack_resolve(layers)  # [(s,e,wet_id,key,cid,kind)]

            # Upsert theo plan
            valid_by_src = defaultdict(set)
            for (s, e, wet_id, key, cid, kind) in plan:
                if kind == 'overtime':
                    src = 'overtime'
                elif kind in ('leave_company', 'leave_personal'):
                    src = 'leave'
                elif kind == 'normal_manual':
                    src = 'manual_attendance'
                elif kind == 'normal_daily':
                    src = 'daily_attendance' if key.startswith('DAILY:') else 'manual_daily'
                elif kind == 'early':
                    src = 'early'
                elif kind == 'late':
                    src = 'late'
                else:
                    src = 'manual'
                self._upsert(emp_id, day_date, s, e, wet_id, src, key, contract_id=cid)
                valid_by_src[src].add(key)

            # Purge WE engine cũ không còn trong plan
            self._purge_stale(emp_id, day_date, valid_by_src)

            # Validate tất cả WE engine của NV trong ngày
            self._bulk_validate_engine(emp_id, day_date)

        return True

    # ======================================================================
    # 11) EMP CHANGED WINDOW
    # ======================================================================
    def _get_employees_changed(self, d0, d1, limit=2000):
        emp_ids = set()
        base0, base1 = datetime.combine(d0, time.min), datetime.combine(d1, time.max)

        DA = self.env['daily.attendance']
        rows = DA.read_group([('punching_time', '>=', base0), ('punching_time', '<=', base1)], ['employee_id'], ['employee_id'], lazy=False)
        emp_ids |= {r['employee_id'][0] for r in rows if r.get('employee_id')}

        Leave = self.env['hr.leave']
        rows = Leave.read_group(
            [('state', '=', 'validate'), ('request_date_from', '<=', base1), ('request_date_to', '>=', base0)],
            ['employee_id'], ['employee_id'], lazy=False)
        emp_ids |= {r['employee_id'][0] for r in rows if r.get('employee_id')}

        OTL = self.env['smartbiz_hr.request_line']
        rows = OTL.read_group(
            [('state', '=', 'approved'), ('start_date', '<=', base1), ('end_date', '>=', base0)],
            ['employee_id'], ['employee_id'], lazy=False)
        emp_ids |= {r['employee_id'][0] for r in rows if r.get('employee_id')}

        Att = self.env['hr.attendance']
        domain_att = expression.OR([
            [('check_in', '<=', base1), ('check_out', '>=', base0)],
            [('check_in', '<=', base1), ('check_out', '=', False)],
        ])
        rows = Att.read_group(domain_att, ['employee_id'], ['employee_id'], lazy=False)
        emp_ids |= {r['employee_id'][0] for r in rows if r.get('employee_id')}

        ids = list(emp_ids)
        return ids[:limit] if limit else ids

class HR_Attendance(models.Model):
    _inherit = ['hr.attendance', 'smartbiz.workflow_base']
    _name = 'hr.attendance'
    name = fields.Char(store='True')
    state = fields.Selection([('draft','Draft'),('to_submit','To Submit'),('approved','Approved'),('refused','Refused')], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_submit(self):
        self.write({'state': 'to_submit'})

        
        
    def action_to_submit_approve(self):
        self.write({'state': 'approved'})

        
        
    def action_to_submit_refuse(self):
        self.write({'state': 'refused'})

        
        
    def action_to_submit_redo(self):
        self.write({'state': 'draft'})

        
        
    @api.model
    def create(self, vals):
        rec = super().create(vals)
        if rec.employee_id and rec.check_in:
            # chỉ kích khi là 'approved' (tuỳ nhu cầu)
            if rec.state == 'approved':
                self.env['hr.work.entry']._recompute_day(rec.check_in.date(), [rec.employee_id.id])
        return rec

    def write(self, vals):
        fields_of_interest = {'employee_id', 'check_in', 'check_out', 'state'}
        will_affect = any(k in vals for k in fields_of_interest)
        old_snaps = []
        if will_affect:
            for r in self:
                old_snaps.append({
                    'emp_id': r.employee_id.id,
                    'start': r.check_in,
                    'end': r.check_out,
                    'state': r.state,
                })

        res = super().write(vals)

        if will_affect:
            affected = set()
            for snap in old_snaps:
                if snap['emp_id'] and snap['start']:
                    d = snap['start'].date()
                    affected.add((snap['emp_id'], d))
            for r in self:
                if r.employee_id and r.check_in:
                    affected.add((r.employee_id.id, r.check_in.date()))

            by_day = {}
            for (emp_id, day) in affected:
                by_day.setdefault(day, set()).add(emp_id)
            WE = self.env['hr.work.entry']
            for day, emp_set in by_day.items():
                WE._recompute_day(day, list(emp_set))

        return res

    def unlink(self):
        old_snaps = []
        for r in self:
            old_snaps.append({'emp_id': r.employee_id.id, 'start': r.check_in})
        res = super().unlink()
        if old_snaps:
            by_day = {}
            for snap in old_snaps:
                if snap['emp_id'] and snap['start']:
                    by_day.setdefault(snap['start'].date(), set()).add(snap['emp_id'])
            WE = self.env['hr.work.entry']
            for day, emp_set in by_day.items():
                WE._recompute_day(day, list(emp_set))
        return res

class HR_Employee(models.Model):
    _inherit = ['hr.employee']
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    code = fields.Char(string='Code')


    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            if rec.code:
                rec.display_name = rec.code + ' - ' + rec.name
            else:
                rec.display_name = rec.name

class HR_Payslip(models.Model):
    _inherit = ['hr.payslip']
    name = fields.Char(store='True')


    # =========================
    # A) Chuẩn giờ/ngày từ Policy
    # =========================
    def _sbz_policy_hours_per_day(self):
        """Lấy chuẩn giờ/ngày từ Calculation Policy; không có thì trả 0."""
        self.ensure_one()
        contract = self.contract_id
        std = 0.0
        if contract and getattr(contract, 'calculation_policy_id', False):
            std = float(contract.calculation_policy_id.standard_hours_per_day or 0.0)
        return std if std > 0 else 0.0

    # =========================
    # B) Giờ lịch theo từng ngày
    # =========================
    def _sbz_calendar_hours_by_day(self, date_from, date_to):
        """{date: hours_of_day} – giờ làm việc 'thiết kế' của lịch trên từng ngày (bỏ leave cá nhân)."""
        self.ensure_one()
        cal = (
            self.contract_id.resource_calendar_id
            or self.employee_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        result = {}
        if not cal or not date_from or not date_to:
            return result

        cur = date_from
        while cur <= date_to:
            dt0 = datetime.combine(cur, time.min)
            dt1 = datetime.combine(cur, time.max)
            dur = cal.get_work_duration_data(
                dt0, dt1,
                compute_leaves=False,
                domain=['|', ('work_entry_type_id', '=', False), ('work_entry_type_id.is_leave', '=', False)],
            )
            result[cur] = float(dur.get('hours', 0.0))
            cur += timedelta(days=1)
        return result

    # =======================================
    # C) Gom WE theo WET & ngày trong kỳ lương
    # =======================================
    def _sbz_collect_we_by_wet_and_day(self):
        """
        Kết quả:
          - by_wet_day: dict[(wet_id, day)] -> hours
          - wet_meta:   dict[wet_id]        -> hr.work.entry.type
        """
        self.ensure_one()
        if not (self.contract_id and self.employee_id and self.date_from and self.date_to):
            return {}, {}

        WE = self.env['hr.work.entry'].sudo()
        start_dt = datetime.combine(self.date_from, time.min)
        stop_dt  = datetime.combine(self.date_to,   time.max)

        wes = WE.search([
            ('employee_id', '=', self.employee_id.id),
            ('contract_id', '=', self.contract_id.id),
            ('state', '=', 'validated'),
            ('date_stop', '>=', start_dt),
            ('date_start', '<=', stop_dt),
        ])
        by_wet_day = defaultdict(float)
        wet_meta = {}
        if not wes:
            return by_wet_day, wet_meta

        for we in wes:
            s = max(we.date_start, start_dt)
            e = min(we.date_stop,  stop_dt)
            if not (s and e and s < e):
                continue

            # Rải theo từng ngày
            d_cursor = s
            while d_cursor.date() <= e.date():
                d0 = datetime.combine(d_cursor.date(), time.min)
                d1 = datetime.combine(d_cursor.date(), time.max)
                seg_s = max(s, d0)
                seg_e = min(e, d1)
                if seg_s < seg_e:
                    wh = (seg_e - seg_s).total_seconds() / 3600.0
                    key = (we.work_entry_type_id.id, d_cursor.date())
                    by_wet_day[key] += wh
                    wet_meta[we.work_entry_type_id.id] = we.work_entry_type_id
                d_cursor = d_cursor + timedelta(days=1)

        return by_wet_day, wet_meta

    # ==========================
    # D) Làm tròn số ngày theo WET
    # ==========================
    @staticmethod
    def _sbz_round_days(wet, days):
        if getattr(wet, 'round_days', False) and wet.round_days != 'NO':
            precision = 0.5 if wet.round_days == "HALF" else 1
            method = wet.round_days_type or 'HALF-UP'
            return float_round(days, precision_rounding=precision, rounding_method=method)
        return days

    # ===========================================
    # E) GHI ĐÈ HOÀN TOÀN: gom công từ WE cho payslip
    # ===========================================
    def _get_worked_day_lines(self, domain=None, check_out_of_contract=False):
        """
        Trả list worked day lines (100% từ WE):
        - Nếu policy có chuẩn giờ/ngày: days = hours / chuẩn
        - Nếu không:   days = sum( hours_D / hours_calendar_D )
        Bỏ OUT_OF_CONTRACT.
        """
        self.ensure_one()
        by_wet_day, wet_meta = self._sbz_collect_we_by_wet_and_day()
        if not by_wet_day:
            return []

        std_hpd = self._sbz_policy_hours_per_day()
        lines = []

        # Nhánh 1: có chuẩn giờ/ngày
        if std_hpd > 0:
            hours_by_wet = defaultdict(float)
            for (wet_id, _day), h in by_wet_day.items():
                hours_by_wet[wet_id] += h
            for wet_id, hours in hours_by_wet.items():
                wet = wet_meta.get(wet_id)
                days_raw = hours / std_hpd
                days = self._sbz_round_days(wet, days_raw)
                lines.append({
                    'sequence': wet.sequence,
                    'work_entry_type_id': wet.id,
                    'code': wet.code,
                    'name': wet.name,
                    'number_of_hours': hours,
                    'number_of_days': days,
                    'amount': 0.0,
                    'is_credit_time': bool(getattr(wet, 'is_credit_time', False)),
                })
            lines.sort(key=lambda x: x['sequence'])
            return lines

        # Nhánh 2: không có chuẩn → quy đổi theo lịch từng ngày
        cal_hours_by_day = self._sbz_calendar_hours_by_day(self.date_from, self.date_to)
        EPS = 1e-5
        days_by_wet = defaultdict(float)
        hours_by_wet = defaultdict(float)

        for (wet_id, day), h in by_wet_day.items():
            denom = max(cal_hours_by_day.get(day, 0.0), EPS)
            days_by_wet[wet_id] += (h / denom)
            hours_by_wet[wet_id] += h

        for wet_id, days_raw in days_by_wet.items():
            wet = wet_meta.get(wet_id)
            days = self._sbz_round_days(wet, days_raw)
            lines.append({
                'sequence': wet.sequence,
                'work_entry_type_id': wet.id,
                'code': wet.code,
                'name': wet.name,
                'number_of_hours': hours_by_wet[wet_id],
                'number_of_days': days,
                'amount': 0.0,
                    'is_credit_time': bool(getattr(wet, 'is_credit_time', False)),
            })

        lines.sort(key=lambda x: x['sequence'])
        return lines

    # ==========================
    # F) LOCALDICT – chỉ theo CODE
    # ==========================
    def _get_base_local_dict(self):
        # (giữ như core)  :contentReference[oaicite:3]{index=3}
        return {
            'float_round': float_round,
            'float_compare': float_compare,
            "relativedelta": relativedelta,
            "ceil": math.ceil,
            "floor": math.floor,
            'UserError': UserError,
            'date': date,
            'datetime': datetime,
        }

    def _get_localdict(self):
        """
        **Chỉ cấp biến theo CODE**:
          - we_hours, we_days: {wet_code: float}
          - inputs, worked_days: map theo code (mặc định Odoo đã vậy)
          - categories: theo code (core)
          - rules/result_rules: theo code (core)
          - month_std_days/hours, prod_summary/prod_total (giữ nguyên tiện ích cũ)
        """
        self.ensure_one()

        # Base của core + xử lý multi-input  :contentReference[oaicite:4]{index=4}
        input_list = [line.code for line in self.input_line_ids if line.code]
        cnt = Counter(input_list)
        multi_input_lines = [k for k, v in cnt.items() if v > 1]
        same_type_input_lines = {line_code: [line for line in self.input_line_ids if line.code == line_code]
                                 for line_code in multi_input_lines}

        base = {
            **self._get_base_local_dict(),
            **{
                'categories': defaultdict(lambda: 0),
                'rules': defaultdict(lambda: dict(total=0, amount=0, quantity=0)),
                'payslip': self,
                'worked_days': {line.code: line for line in self.worked_days_line_ids if line.code},
                'inputs': {line.code: line for line in self.input_line_ids if line.code},
                'employee': self.employee_id,
                'contract': self.contract_id,
                'result_rules': defaultdict(lambda: dict(total=0, amount=0, quantity=0, rate=0)),
                'same_type_input_lines': same_type_input_lines,
            }
        }

        # Các tiện ích tháng/kỳ (từ code cũ của bạn)  
        try:
            prod_wc, prod_total = self._get_production_activity_summary()
        except Exception:
            prod_wc, prod_total = {}, {'records': self.env['smartbiz_mes.production_activity'],
                                       'quantity': 0, 'duration': 0, 'quality': 0, 'cost': 0}
        try:
            month_workdays, month_workhours = self._get_month_workstats(
                exclude_public_holiday=True,
                use_payslip_period=False,
                consider_contract_span=True,
            )
        except Exception:
            month_workdays, month_workhours = 0.0, 0.0

        # Tính theo code WET
        by_wet_day, wet_meta = self._sbz_collect_we_by_wet_and_day()
        std_hpd = self._sbz_policy_hours_per_day()
        EPS = 1e-5

        hours_by_code = defaultdict(float)
        days_by_code = defaultdict(float)

        if std_hpd > 0:
            for (wet_id, _day), h in by_wet_day.items():
                wet = wet_meta.get(wet_id)
                code = (wet.code or '').strip() if wet else ''
                if code:
                    hours_by_code[code] += h
            for code, h in hours_by_code.items():
                days_by_code[code] = h / std_hpd
        else:
            cal_hours_by_day = self._sbz_calendar_hours_by_day(self.date_from, self.date_to)
            for (wet_id, day), h in by_wet_day.items():
                wet = wet_meta.get(wet_id)
                code = (wet.code or '').strip() if wet else ''
                if not code:
                    continue
                denom = max(cal_hours_by_day.get(day, 0.0), EPS)
                hours_by_code[code] += h
                days_by_code[code]  += (h / denom)

        # Làm tròn theo WET
        for wet_id, wet in wet_meta.items():
            code = (wet.code or '').strip()
            if not code:
                continue
            if code in days_by_code:
                days_by_code[code] = self._sbz_round_days(wet, days_by_code[code])

        # Alias gợi nhớ
        base.update({
            'env': self.env,
            'prod_summary': prod_wc,
            'prod_total':   prod_total,
            'month_std_days':  month_workdays,
            'month_std_hours': month_workhours,
            'we_hours': dict(hours_by_code),
            'we_days':  dict(days_by_code),
        })
        return base

    # ==========================
    # G) Tiện ích giữ lại từ code cũ
    # ==========================
    def _sum(self, code, from_date, to_date=None):
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""
            SELECT sum(pl.total)
              FROM hr_payslip as hp, hr_payslip_line as pl
             WHERE hp.employee_id = %s
               AND hp.state in ('done', 'paid')
               AND hp.date_from >= %s
               AND hp.date_to   <= %s
               AND hp.id = pl.slip_id
               AND pl.code = %s
        """, (self.employee_id.id, from_date, to_date, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

    def _sum_category(self, code, from_date, to_date=None):
        self.ensure_one()
        if to_date is None:
            to_date = fields.Date.today()
        self.env['hr.payslip'].flush_model(['employee_id', 'state', 'date_from', 'date_to'])
        self.env['hr.payslip.line'].flush_model(['total', 'slip_id', 'category_id'])
        self.env['hr.salary.rule.category'].flush_model(['code'])
        self.env.cr.execute("""
            SELECT sum(pl.total)
              FROM hr_payslip as hp, hr_payslip_line as pl, hr_salary_rule_category as rc
             WHERE hp.employee_id = %s
               AND hp.state in ('done', 'paid')
               AND hp.date_from >= %s
               AND hp.date_to   <= %s
               AND hp.id = pl.slip_id
               AND rc.id = pl.category_id
               AND rc.code = %s
        """, (self.employee_id.id, from_date, to_date, code))
        res = self.env.cr.fetchone()
        return res and res[0] or 0.0

    def _sum_worked_days(self, code, from_date, to_date=None):
        self.ensure_one()
        if to_date is None:
            to_date = fields.Date.today()
        self.env.cr.execute("""
            SELECT sum(hwd.amount)
              FROM hr_payslip hp, hr_payslip_worked_days hwd, hr_work_entry_type hwet
             WHERE hp.state in ('done', 'paid')
               AND hp.id = hwd.payslip_id
               AND hwet.id = hwd.work_entry_type_id
               AND hp.employee_id = %(employee)s
               AND hp.date_to <= %(stop)s
               AND hwet.code = %(code)s
               AND hp.date_from >= %(start)s
        """, {'employee': self.employee_id.id, 'code': code, 'start': from_date, 'stop': to_date})
        res = self.env.cr.fetchone()
        return res[0] if res else 0.0

    def _get_rule_name(self, localdict, rule, employee_lang):
        # (giữ tương thích core)
        if localdict.get('result_name'):
            rule_name = localdict['result_name']
        elif rule.code in ['BASIC', 'GROSS', 'NET', 'DEDUCTION', 'REIMBURSEMENT']:
            if rule.code == 'BASIC':
                if rule.name == "Double Holiday Pay":
                    rule_name = _("Double Holiday Pay")
                if rule.struct_id.name == "CP200: Employees 13th Month":
                    rule_name = _("Prorated end-of-year bonus")
                else:
                    rule_name = _('Basic Salary')
            elif rule.code == "GROSS":
                rule_name = _('Gross')
            elif rule.code == "DEDUCTION":
                rule_name = _('Deduction')
            elif rule.code == "REIMBURSEMENT":
                rule_name = _('Reimbursement')
            elif rule.code == 'NET':
                rule_name = _('Net Salary')
        else:
            rule_name = rule.with_context(lang=employee_lang).name
        return rule_name

    def _get_worked_days_line_amount(self, code):
        wds = self.worked_days_line_ids.filtered(lambda wd: wd.code == code)
        return sum(wd.amount for wd in wds)

    def _get_worked_days_line_number_of_hours(self, code):
        wds = self.worked_days_line_ids.filtered(lambda wd: wd.code == code)
        return sum(wd.number_of_hours for wd in wds)

    def _get_worked_days_line_number_of_days(self, code):
        wds = self.worked_days_line_ids.filtered(lambda wd: wd.code == code)
        return sum(wd.number_of_days for wd in wds)

    def _get_input_line_amount(self, code):
        lines = self.input_line_ids.filtered(lambda line: line.code == code)
        return sum(line.amount for line in lines)

    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options)
        if options and options.get('toolbar'):
            for view_type in res['views']:
                res['views'][view_type]['toolbar'].pop('print', None)
        return res

    def action_print_payslip(self):
        return {
            'name': 'Payslip',
            'type': 'ir.actions.act_url',
            'url': '/print/payslips?list_ids=%(list_ids)s' % {'list_ids': ','.join(str(x) for x in self.ids)},
        }

    def action_export_payslip(self):
        self.ensure_one()
        return {
            "name": "Debug Payslip",
            "type": "ir.actions.act_url",
            "url": "/debug/payslip/%s" % self.id,
        }

    def _get_contract_wage(self):
        self.ensure_one()
        return self.contract_id._get_contract_wage()

    def compute_sheet(self):
        # Giữ flow của bạn  :contentReference[oaicite:6]{index=6}
        payslips = self.filtered(lambda slip: slip.state in ['draft', 'verify'])
        payslips.line_ids.unlink()
        self.env.flush_all()
        today = fields.Date.today()
        for payslip in payslips:
            number = payslip.number or self.env['ir.sequence'].next_by_code('salary.slip')
            payslip.write({'number': number, 'state': 'verify', 'compute_date': today})
        self.env['hr.payslip.line'].create(payslips._get_payslip_lines())
        return True

    # --------------------------------------------------------------
    # Sản lượng sản xuất (giữ nguyên như bạn)
    # --------------------------------------------------------------
    def _get_production_activity_summary(self):
        self.ensure_one()

        if not self.date_from or not self.date_to:
            empty_rec = self.env['smartbiz_mes.production_activity']
            return {}, {'records': empty_rec,
                        'quantity': 0.0, 'duration': 0.0,
                        'quality': 0.0, 'cost': 0.0}

        dt_start = datetime.combine(self.date_from, time.min)
        dt_stop = datetime.combine(self.date_to, time.max)

        acts = self.env['smartbiz_mes.production_activity'].search([
            ('employee_id', '=', self.employee_id.id),
            ('start', '>=', dt_start),
            ('finish', '<=', dt_stop),
        ])

        def _init():
            return {
                'records': self.env['smartbiz_mes.production_activity'],
                'quantity': 0.0,
                'duration': 0.0,
                'quality': 0.0,
                'cost': 0.0,
            }

        summary = defaultdict(_init)
        total = _init()

        for act in acts:
            wc_id = act.workcenter_id.id
            duration_min = act.duration or 0.0
            duration_hr = duration_min / 60.0
            cost_hour = act.workcenter_id.costs_hour or 0.0
            cost = duration_hr * cost_hour

            s = summary[wc_id]
            s['records'] += act
            s['quantity'] += act.quantity or 0.0
            s['duration'] += duration_min
            s['quality'] += act.quality or 0.0
            s['cost'] += cost

            total['records'] += act
            total['quantity'] += act.quantity or 0.0
            total['duration'] += duration_min
            total['quality'] += act.quality or 0.0
            total['cost'] += cost

        summary = {k: dict(v, records=v['records']) for k, v in summary.items()}
        total = dict(total, records=total['records'])
        return summary, total

class Resource_CalendarLeaves(models.Model):
    _inherit = ['resource.calendar.leaves']
    leave_type_id = fields.Many2one('smartbiz_hr.calendar_leave_type', string='Leave Type')


class HR_SalaryRule(models.Model):
    _inherit = ['hr.salary.rule']
    name = fields.Char(store='True')

    # ---- helpers ----
    def _resolve_struct_id(self, res):
        """Cố gắng lấy struct_id từ res/context/active."""
        sid = res.get('struct_id') or self.env.context.get('default_struct_id')
        if not sid and self.env.context.get('active_model') == 'hr.payroll.structure':
            sid = self.env.context.get('active_id')
        if isinstance(sid, (list, tuple)):
            sid = sid[0]
        return sid

    @api.model
    def default_get(self, fields_list):
        """Điền mặc định 3 ô Python bằng hướng dẫn + danh sách CODE hiện có (dynamic)."""
        res = super().default_get(fields_list)
            
        def _pairs(records, code_field='code', name_field='name'):
            """Trả list 'Tên — CODE' (bỏ rỗng/None)."""
            vals = []
            for r in records:
                code = (getattr(r, code_field, '') or '').strip()
                name = (getattr(r, name_field, '') or '').strip()
                if code:
                    vals.append(f"{name} — {code}" if name else code)
            return sorted(vals, key=str.lower)

        def _mk_section(title, lines):
            if not lines:
                return ""
            body = "\n".join(f"#   - {ln}" for ln in lines)
            return f"# {title}:\n{body}\n"
            
        # Xác định struct_id đang tạo rule cho nó
        struct_id = self._resolve_struct_id(res)
        Structure = self.env['hr.payroll.structure'].sudo()
        Rule = self.env['hr.salary.rule'].sudo()
        Cat  = self.env['hr.salary.rule.category'].sudo()

        # ==== Lấy danh sách theo STRUCT ====
        struct_note = ""
        if struct_id:
            # Rule thuộc struct
            rules = Rule.search([('struct_id', '=', struct_id)])
            # Category dùng trong struct (theo các rule của struct)
            cats = Cat.browse(rules.mapped('category_id').ids)

            # Input Type chỉ những cái được tham chiếu bởi rule trong struct (nếu model tồn tại)
            inp_lines = []
            if 'hr.rule.input' in self.env and 'input_id' in self.env['hr.rule.input']._fields:
                # tên field đến rule có thể là salary_rule_id hoặc rule_id -> bắt cả 2
                rid_field = 'salary_rule_id' if 'salary_rule_id' in self.env['hr.rule.input']._fields else \
                            ('rule_id' if 'rule_id' in self.env['hr.rule.input']._fields else None)
                if rid_field:
                    rule_inputs = self.env['hr.rule.input'].sudo().search([(f'{rid_field}.struct_id', '=', struct_id)])
                    inp_types = rule_inputs.mapped('input_id')
                    inp_lines = _pairs(inp_types, 'code', 'name')
        else:
            struct_note = "# [Lưu ý] Chưa xác định 'Cấu trúc lương'. Hãy chọn struct để danh sách CODE lọc theo cấu trúc.\n"
            rules = Rule.search([])
            cats  = Cat.search([])
            inp_lines = []
            if 'hr.payslip.input.type' in self.env:
                inp_types = self.env['hr.payslip.input.type'].sudo().search([])
                inp_lines = _pairs(inp_types, 'code', 'name')

        rule_lines = _pairs(rules, 'code', 'name')
        cat_lines  = _pairs(cats,  'code', 'name')

        # Work Entry Type: không gắn struct; nếu muốn lọc riêng thì chỉnh tuỳ ý
        wet_lines = []
        if 'hr.work.entry.type' in self.env:
            wets = self.env['hr.work.entry.type'].sudo().search([])
            wet_lines = _pairs(wets, 'code', 'name')

        # Các section comment động
        sec_rules = _mk_section("Rule trong Cấu trúc hiện tại (Tên — CODE)", rule_lines)
        sec_cats  = _mk_section("Category dùng trong Cấu trúc (Tên — CODE)",  cat_lines)
        sec_inps  = _mk_section("Input Type dùng trong Cấu trúc (Tên — CODE)", inp_lines)
        sec_wets  = _mk_section("Work Entry Type (Tên — CODE)",               wet_lines)

        header_common = f"""{struct_note}# HƯỚNG DẪN — Biến Localdict (dùng cho mọi ô Python)
# --------------------------------------------------------
# Truy cập theo CODE (không dùng ID):
#   - payslip, employee, contract, env
#   - rules['CODE'] -> dict(total, amount, quantity)
#   - categories['CAT'] -> số (tổng theo nhóm)
#   - worked_days['CODE'] -> .number_of_days / .number_of_hours / .amount
#   - inputs['CODE'].amount
#   - we_hours['WET_CODE'], we_days['WET_CODE']  # từ WE engine
#   - month_std_days, month_std_hours            # chuẩn công tháng/kỳ (lịch − nghỉ Cty)
#   - prod_summary, prod_total                   # nếu dùng MES

{sec_rules}{sec_cats}{sec_inps}{sec_wets}
"""

        cond_tpl = f"""{header_common}
# Ví dụ (Điều kiện): NET > 10% nhóm NET
# result = rules['NET']['total'] > categories['NET'] * 0.10
result = False
"""

        amount_tpl = f"""{header_common}
# Ví dụ (Amount):
#   OT300:
# result = we_hours.get('OT300', 0.0) * contract.hourly_wage * 3.0
#   Lương cơ bản theo ngày:
# result = (contract.wage / (month_std_days or 1.0)) * we_days.get('WORK', 0.0)
result = 0.0
"""

        qty_tpl = f"""{header_common}
# Ví dụ (Quantity):
# result_qty = we_days.get('WORK', 0.0)
result_qty = 0.0
"""

        # Ghi đè luôn (để thắng defaults từ context/view)
        if 'condition_python' in fields_list:
            res['condition_python'] = cond_tpl
        if 'amount_python_compute' in fields_list:
            res['amount_python_compute'] = amount_tpl
        if 'quantity_python_compute' in fields_list:
            res['quantity_python_compute'] = qty_tpl

        # đảm bảo 3 selector ở chế độ Python
        if 'condition_select' in fields_list:
            res.setdefault('condition_select', 'python')
        if 'amount_select' in fields_list:
            res.setdefault('amount_select', 'code')
        if 'quantity_select' in fields_list:
            res.setdefault('quantity_select', 'code')

        return res

class smartbiz_hr_OvertimeRequest(models.Model):
    _name = "smartbiz_hr.overtime_request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Overtime Request"
    name = fields.Char(string='Name')
    employee_ids = fields.Many2many('hr.employee', string='Employee')
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    lines_ids = fields.One2many('smartbiz_hr.request_line', 'request_id')
    note = fields.Text(string='Note')
    approver_ids = fields.Many2many('res.users', 'overtime_request_users_rel',  string='Approver')
    state = fields.Selection([('draft','Draft'),('to_submit','To Submit'),('to_approve','To Approve'),('approved','Approved'),('refused','Refused'),], string= 'Status', readonly= False, copy = True, index = False, tracking = True, default = 'draft')


    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for rec in self:
            if rec.end_date and rec.start_date:
                rec.duration = (rec.end_date - rec.start_date).total_seconds() / 3600
            else:
                rec.duration = 0

    def action_draft_submit(self):
        for req in self:
            # Tạo / cập nhật line
            vals_list = []
            for emp in req.employee_ids:
                line = req.lines_ids.filtered(lambda l: l.employee_id == emp)
                if line:
                    line.write({
                        'start_date': req.start_date,
                        'end_date'  : req.end_date,
                        'state'     : 'to_submit',
                    })
                else:
                    vals_list.append({
                        'request_id': req.id,
                        'employee_id': emp.id,
                        'start_date': req.start_date,
                        'end_date'  : req.end_date,
                        'state'     : 'to_submit',
                    })
            if vals_list:
                self.env['smartbiz_hr.request_line'].create(vals_list)

            old = req.state
            req.write({'state': 'to_submit'})
            req._post_state_message(old)
        return True

        
        
    def action_to_submit_approve(self):
        for req in self:
            req._set_lines_state('to_approve')
            old = req.state
            req.state = 'to_approve'
            req._post_state_message(old)
        return True

        
        
    def action_to_submit_refuse(self):
        for req in self:
            req._set_lines_state('refused')
            old = req.state
            req.write({'state': 'refused', 'approver_ids': [(4, self.env.uid)]})
            req._post_state_message(old)
        return True

        
        
    def action_to_approve_approve(self):
        for req in self:
            if req.state != 'to_approve':
                raise UserError(_("Chỉ có yêu cầu đang 'Chờ duyệt' mới được duyệt."))

            req._set_lines_state('approved')  # Line sẽ tự tạo Work Entry
            old = req.state
            req.write({
                'state': 'approved',
                'approver_ids': [(4, self.env.uid)],
            })
            req._post_state_message(old)
        return True

        
        
    def action_refused_to_draft(self):
        for req in self:
            req._set_lines_state('draft')
            old = req.state
            req.state = 'draft'
            req._post_state_message(old)

        
        
    # Đặt cùng state cho tất cả line
    def _set_lines_state(self, new_state):
        for req in self:
            req.lines_ids.write({'state': new_state})

    # Tính lại state cha dựa trên line
    def _sync_state_from_lines(self):
        PRIORITY = ['refused', 'to_approve', 'to_submit', 'draft']  # approved check riêng
        for req in self:
            line_states = set(req.lines_ids.mapped('state'))
            if not line_states:
                target = 'draft'
            elif line_states == {'approved'}:
                target = 'approved'
            else:
                target = next((st for st in PRIORITY if st in line_states), 'draft')
            if req.state != target:
                old = req.state
                req.state = target
                req._post_state_message(old)

    # Gửi message vào chatter khi state đổi
    def _post_state_message(self, old_state):
        sel = dict(self._fields['state'].selection)
        for req in self:
            req.message_post(
                body=_("Trạng thái thay đổi từ %s → %s bởi %s.") %
                     (sel.get(old_state, old_state),
                      sel.get(req.state, req.state),
                      self.env.user.display_name),
                subtype_xmlid='mail.mt_comment'
            )

class smartbiz_hr_RequestLine(models.Model):
    _name = "smartbiz_hr.request_line"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Request Line"
    request_id = fields.Many2one('smartbiz_hr.overtime_request', string='Request')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    state = fields.Selection([('draft','Draft'),('to_submit','To Submit'),('to_approve','To Approve'),('approved','Approved'),('refused','Refused'),], string= 'Status', readonly= False, copy = True, index = False, tracking = True, default = 'draft')


    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for rec in self:
            if rec.end_date and rec.start_date:
                rec.duration = (rec.end_date - rec.start_date).total_seconds() / 3600
            else:
                rec.duration = 0

    def action_draft_submit(self):
        self.write({'state': 'to_submit'})

        
        
    def action_to_submit_approve(self):
        self.write({'state': 'to_approve'})

        
        
    def action_to_submit_refuse(self):
        self.write({'state': 'refused'})

        
        
    def action_to_approve_approve(self):
        self.write({'state': 'approved'})

        
        
    def action_refused_to_draft(self):
        self.write({'state': 'draft'})

        
        
    # -------------------- Constraints --------------------
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for r in self:
            if r.start_date and r.end_date and r.end_date <= r.start_date:
                raise ValidationError(_("End Date must be greater than Start Date."))



    # -------------------- Engine triggers --------------------
    def _trigger_recompute_engine(self, old_snapshots=None):
        """
        Gọi engine tính lại theo (employee, ngày) bị ảnh hưởng.
        old_snapshots: list các dict {'emp_id', 'start', 'end'} trước khi sửa/xoá.
        """
        WE = self.env['hr.work.entry']
        # Tập (emp_id, day) cần tính
        affected = set()

        # 1) Dữ liệu cũ (nếu có)
        if old_snapshots:
            for snap in old_snapshots:
                emp_id = snap.get('emp_id')
                s = snap.get('start')
                e = snap.get('end')
                if not (emp_id and s and e):
                    continue
                d = s.date()
                while d <= e.date():
                    affected.add((emp_id, d))
                    d += timedelta(days=1)

        # 2) Dữ liệu hiện tại
        for r in self:
            if not (r.employee_id and r.start_date and r.end_date):
                continue
            emp_id = r.employee_id.id
            d = r.start_date.date()
            while d <= r.end_date.date():
                affected.add((emp_id, d))
                d += timedelta(days=1)

        # Chạy engine theo nhóm ngày/nhân sự
        # Gom theo ngày để gọi 1 lần với list emp_ids
        by_day = {}
        for (emp_id, day) in affected:
            by_day.setdefault(day, set()).add(emp_id)

        for day, emp_set in by_day.items():
            WE._recompute_day(day, list(emp_set))

    # -------------------- Overlap helpers --------------------
    def _overlap_domain(self, emp_id, start_dt, end_dt, exclude_ids=None):
        """Domain tìm các line OT của cùng nhân viên bị chồng lấn với [start_dt, end_dt)."""
        exclude_ids = exclude_ids or []
        domain = [
            ('employee_id', '=', emp_id),
            # bỏ qua line đã từ chối (nếu muốn tính cả refused thì xóa điều kiện này)
            ('state', '!=', 'refused'),
            # điều kiện chồng lấn chuẩn
            ('start_date', '<', end_dt),
            ('end_date', '>', start_dt),
        ]
        if exclude_ids:
            domain.append(('id', 'not in', exclude_ids))
        return domain

    def _check_overlap_batch(self, records=None):
        """
        Kiểm tra chồng lấn cho một tập record (mặc định: self).
        Gộp theo employee để giảm số lần query.
        """
        def to_user_timezone(self, dt):
            if not dt:
                return None

            dt = pytz.utc.localize(dt) if dt.tzinfo is None else dt.astimezone(pytz.utc)
            user_tz = pytz.timezone(self.env.user.tz or 'UTC')
            return dt.astimezone(user_tz)
        recs = records or self
        # gom theo employee
        buckets = {}
        for r in recs:
            # chỉ kiểm khi đủ dữ liệu
            if not (r.employee_id and r.start_date and r.end_date):
                continue
            buckets.setdefault(r.employee_id.id, []).append(r)

        for emp_id, items in buckets.items():
            # Với từng item, tìm xem có record nào khác chồng lấn không
            for r in items:
                domain = self._overlap_domain(
                    emp_id=emp_id,
                    start_dt=r.start_date,
                    end_dt=r.end_date,
                    exclude_ids=[r.id] if r.id else []
                )
                # limit=1 để nhanh
                dup = self.search(domain, limit=1)
                if dup:
                    raise ValidationError(_(
                        "Nhân viên %s đã có yêu cầu OT trùng khoảng thời gian:\n"
                        "• Dòng hiện tại: [%s → %s]\n"
                        "• Bị trùng với: [%s → %s] (Request #%s)"
                    ) % (
                        r.employee_id.display_name,
                        fields.Datetime.to_string(to_user_timezone(r.start_date)),
                        fields.Datetime.to_string(to_user_timezone(r.end_date)),
                        fields.Datetime.to_string(to_user_timezone(dup.start_date)),
                        fields.Datetime.to_string(to_user_timezone(dup.end_date)),
                        dup.request_id.display_name or dup.request_id.id,
                    ))

    # -------------------- Constraints --------------------
    @api.constrains('employee_id', 'start_date', 'end_date', 'state')
    def _constrains_no_overlap(self):
        """
        Ràng buộc mức ORM: cấm trùng OT cho cùng 1 nhân viên.
        Bỏ qua các bản ghi thiếu thời gian hoặc đã refused.
        """
        # lọc ra những bản ghi có dữ liệu đủ và không phải refused
        candidates = self.filtered(
            lambda r: r.employee_id and r.start_date and r.end_date and r.state != 'refused'
        )
        if candidates:
            self._check_overlap_batch(candidates)

    # -------------------- Overrides create/write --------------------
    @api.model
    def create(self, vals):
        # tạo trước rồi check (để có id loại trừ chính nó khi search)
        rec = super().create(vals)
        # chỉ check khi đủ dữ liệu & không phải refused
        if rec.employee_id and rec.start_date and rec.end_date and rec.state != 'refused':
            rec._check_overlap_batch(rec)
        # logic cũ của bạn
        rec._log_state_change(old_state=None, new_state=rec.state)
        rec._trigger_recompute_engine()
        rec.mapped('request_id')._sync_state_from_lines()
        return rec

    def write(self, vals):
        res = super().write(vals)
        # sau khi viết, kiểm tra trùng cho các record bị ảnh hưởng
        fields_of_interest = {'employee_id', 'start_date', 'end_date', 'state'}
        if any(k in vals for k in fields_of_interest):
            candidates = self.filtered(
                lambda r: r.employee_id and r.start_date and r.end_date and r.state != 'refused'
            )
            if candidates:
                self._check_overlap_batch(candidates)

        # logic cũ của bạn
        if 'state' in vals:
            for r in self:
                r._log_state_change(old_state=None, new_state=r.state)  # hoặc dùng old_states như bạn đã làm
        if any(k in vals for k in {'employee_id', 'start_date', 'end_date', 'state'}):
            self._trigger_recompute_engine()
        self.mapped('request_id')._sync_state_from_lines()
        return res

    def unlink(self):
        # Lưu snapshot cũ trước khi xoá
        old_snaps = []
        for r in self:
            old_snaps.append({
                'emp_id': r.employee_id.id,
                'start': r.start_date,
                'end': r.end_date,
                'state': r.state,
            })
        res = super().unlink()
        # Sau khi xoá, gọi engine để purge các WE OT cũ
        if old_snaps:
            self.env['hr.work.entry']  # ensure env
            # Tạo record ảo để dùng helper
            dummy = self.env['smartbiz_hr.request_line']
            dummy._trigger_recompute_engine(old_snapshots=old_snaps)
        return res

    # -------------------- Helpers --------------------
    def _log_state_change(self, old_state, new_state):
        """Ghi log vào chatter khi state thay đổi."""
        if old_state == new_state:
            return
        sel = dict(self._fields['state'].selection)
        for r in self:
            r.message_post(
                body=_("Status changed from <b>%s</b> → <b>%s</b> by %s.") %
                     (sel.get(old_state, old_state),
                      sel.get(new_state, new_state),
                      self.env.user.display_name),
                subtype_xmlid='mail.mt_comment'
            )

class smartbiz_hr_Allowance(models.Model):
    _name = "smartbiz_hr.allowance"
    _description = "Allowance"
    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)


class smartbiz_hr_ContractAllowance(models.Model):
    _name = "smartbiz_hr.contract_allowance"
    _description = "Contract Allowance"
    contract_id = fields.Many2one('hr.contract', string='Contract')
    allowance_id = fields.Many2one('smartbiz_hr.allowance', string='Allowance')
    code = fields.Char(string='Code', compute='_compute_code', store=True)
    value = fields.Float(string='Value')


    @api.depends('allowance_id')
    def _compute_code(self):
        for rec in self:
            rec.code = rec.allowance_id.code

class smartbiz_hr_OverTimeRule(models.Model):
    _name = "smartbiz_hr.overtime_rule"
    _description = "OverTime Rule"
    name = fields.Char(string='Name', required=True)
    type = fields.Selection([('working_day','Working Day'),('non_working_day','Non Working Day'),('leave_day','Leave Day'),], string='Type', required=True, default = 'leave_day')
    work_entry_type_id = fields.Many2one('hr.work.entry.type', string='Work Entry Type', required=True)
    priority = fields.Integer(string='Priority', default = 10)


class smartbiz_hr_CalendarLeaveType(models.Model):
    _name = "smartbiz_hr.calendar_leave_type"
    _description = "Calendar Leave Type"
    _sql_constraints = [('uniq_name_type', 'unique(name, type)', 'Duplicated Overtime Rule for the same name & type!')]
    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    work_entry_type_id = fields.Many2one('hr.work.entry.type', string='Work Entry Type')
    overtime_rule_id = fields.Many2one('smartbiz_hr.overtime_rule', string='Overtime Rule', required=True)


class smartbiz_hr_CalculationPolicy(models.Model):
    _name = "smartbiz_hr.calculation_policy"
    _description = "Calculation Policy"
    name = fields.Char(string='Name')
    active = fields.Boolean(string='Active')
    is_flexible = fields.Boolean(string='Is Flexible')
    standard_hours_per_day = fields.Float(string='Standard Hours Per Day')
    attendance_policy_id = fields.Many2one('smartbiz_hr.attendance_policy', string='Attendance Policy')
    overtime_policy_id = fields.Many2one('smartbiz_hr.overtime_policy', string='OverTime Policy')
    contract_ids = fields.One2many('hr.contract', 'calculation_policy_id')


class smartbiz_hr_AttendancePolicy(models.Model):
    _name = "smartbiz_hr.attendance_policy"
    _description = "Attendance Policy"
    name = fields.Char(string='Name')
    must_check_in = fields.Boolean(string='Must Check In')
    must_check_out = fields.Boolean(string='Must Check Out')
    must_check_break_time = fields.Boolean(string='Must Check Break Time')
    missing_mode = fields.Selection([('half_day','Half Day'),('alert','Alert'),], string='Missing Mode')
    minutes_before_check_in = fields.Integer(string='Minutes Before Check In')
    minutes_after_check_in = fields.Integer(string='Minutes After Check In')
    minutes_before_check_out = fields.Integer(string='Minutes Before Check Out')
    minutes_after_check_out = fields.Integer(string='Minutes After Check Out')
    minutes_as_late = fields.Integer(string='Minutes As Late')
    minutes_as_early = fields.Integer(string='Minutes As Early')
    normal_work_type_id = fields.Many2one('hr.work.entry.type', string='Normal Work Type')
    early_work_type_id = fields.Many2one('hr.work.entry.type', string='Early Work Type')
    late_work_type_id = fields.Many2one('hr.work.entry.type', string='Late Work Type')


class smartbiz_hr_OverTimePolicy(models.Model):
    _name = "smartbiz_hr.overtime_policy"
    _description = "OverTime Policy"
    name = fields.Char(string='Name')
    max_hours_per_day = fields.Integer(string='Max Hours Per Day')
    max_hours_per_week = fields.Integer(string='Max Hours Per Week')
    max_hours_per_year = fields.Integer(string='Max Hours Per Year')
    reconcile_with_attendance = fields.Boolean(string='Reconcile With Attendance')
    weekday_overtime_type_id = fields.Many2one('hr.work.entry.type', string='Weekday Overtime Type')
    weekend_overtime_type_id = fields.Many2one('hr.work.entry.type', string='Weekend Overtime Type')
    holiday_overtime_type_id = fields.Many2one('hr.work.entry.type', string='Holiday Overtime Type')


class smartbiz_hr_AttendanceAlert(models.Model):
    _name = "smartbiz_hr.attendance_alert"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Attendance Alert"
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    date = fields.Datetime(string='Date')
    block_start = fields.Datetime(string='Block Start')
    block_end = fields.Datetime(string='Block End')
    alert_type = fields.Selection([('missing_check_in','Missing Check In'),('missing_check_out','Missing Check Out'),], string='Alert Type')
    note = fields.Text(string='Note')
    state = fields.Selection([('open','Open'),('ack','Ack'),('resolved','Resolved'),], string= 'Status', readonly= False, copy = True, index = False, default = 'open')


    @api.depends('employee_id', 'date', 'alert_type')
    def _compute_name(self):
        type_map = dict(self._fields['alert_type'].selection)
        for r in self:
            # lấy tz của user nhân viên (fallback tz của user hiện tại)
            try:
                tz = pytz.timezone(r.employee_id.tz or self.env.user.tz or 'UTC')
            except Exception:
                tz = pytz.UTC
            # định dạng 'date' theo tz để hiển thị
            def _fmt(dt):
                if not dt:
                    return ''
                return fields.Datetime.to_string(dt.replace(tzinfo=pytz.UTC).astimezone(tz))
            r.name = "[%s] %s - %s" % (_fmt(r.date), r.employee_id.name or '', type_map.get(r.alert_type, 'Alert'))

    def action_open_create_attendance(self):
        """Mở form tạo hr.attendance với dữ liệu gợi ý từ alert."""
        self.ensure_one()
        self.write({'state': 'ack'})
        ctx = {
            'default_employee_id': self.employee_id.id,
            'default_check_in': self.date,
            'default_check_out': self.date,
            'default_name': _('Created from Attendance Alert'),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Attendance'),
            'res_model': 'hr.attendance',
            'view_mode': 'form',
            'target': 'current',
            'context': ctx,
        }

        
        
    def action_open_create_leave(self):
        """Mở form tạo hr.leave (người dùng chọn loại nghỉ)."""
        self.ensure_one()
        self.write({'state': 'ack'})
        # hr.leave cần holiday_status_id; để user chọn trong form
        ctx = {
            'default_employee_id': self.employee_id.id,
            'default_request_date_from': self.block_start or self.date,
            'default_request_date_to': self.block_end or self.date,
            'default_name': _('Created from Attendance Alert'),
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Time Off'),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'target': 'current',
            'context': ctx,
        }

        
        
    def action_open_confirm(self):
        self.write({'state': 'ack'})

        
        
class smartbiz_hr_MailerConfiguration(models.Model):
    _name = "smartbiz_hr.mailer_configuration"
    _description = "Mailer Configuration"
    name = fields.Char(string='Name')
    active = fields.Boolean(string='Active')
    timezone = fields.Selection(_tz_get, string='Timezone', default = lambda self: self.env.user.tz or 'UTC')
    subject = fields.Char(string='Subject')
    include_ot = fields.Boolean(string='Include OT')
    include_leave = fields.Boolean(string='Include Leave')
    include_attendance = fields.Boolean(string='Include Attendance')
    recipient_mode = fields.Selection([('manager','Manager'),('users','Users'),('groups','Groups'),('partners','Partners'),], string='Recipient Mode', default = 'manager')
    users_ids = fields.Many2many('res.users', string='Users')
    user_groups_ids = fields.Many2many('res.groups', 'mailer_configuration_groups_rel',  string='User Groups')
    partners_ids = fields.Many2many('res.partner', 'mailer_configuration_partner_rel',  string='Partners')
    mail_template_id = fields.Many2one('mail.template', string='Mail Template')
    time_ids = fields.One2many('smartbiz_hr.mailer_time', 'mailer_id')


    # =========================
    # =======  CRON  ==========
    # =========================
    @api.model
    def cron_mailer_tick(self):
        """Chạy mỗi 5 phút: quét tất cả cấu hình còn active và gửi nếu đến hạn."""
        now_utc = fields.Datetime.now()
        for cfg in self.search([('active', '=', True)]):
            cfg._run_due_schedules(now_utc=now_utc)
        return True

    def _run_due_schedules(self, now_utc=None):
        self.ensure_one()
        now_utc = now_utc or fields.Datetime.now()
        if not self.time_ids:
            return
        for t in self.time_ids.filtered('active'):
            if t._is_due(self.timezone, now_utc=now_utc):
                self._send_digest()
                # cập nhật mốc đã chạy hôm nay (local)
                tz = pytz.timezone(self.timezone or 'UTC')
                local_date = now_utc.astimezone(tz).date()
                t.sudo().write({'last_run': local_date})

    # =========================
    # =======  DATA  ==========
    # =========================
    def _manager_user_of(self, emp):
        user = emp.parent_id and emp.parent_id.user_id or False
        if not user and emp.department_id and emp.department_id.manager_id:
            user = emp.department_id.manager_id.user_id
        return user

    def _collect_pending_by_manager(self):
        """Map: manager_user_id -> list(items). Tôn trọng include_*."""
        self.ensure_one()
        res = {}
        # OT
        if self.include_ot:
            for ln in self.env['smartbiz_hr.request_line'].sudo().search([('state', 'in', ['to_submit', 'to_approve'])]):
                mgr = self._manager_user_of(ln.employee_id)
                if not mgr:
                    continue
                res.setdefault(mgr.id, []).append({
                    'emp': ln.employee_id, 'model': 'smartbiz_hr.request_line', 'rec': ln,
                    'date': fields.Datetime.to_string(ln.start_date),
                    'detail': "+%.2f giờ (%s – %s)" % (
                        (ln.duration or 0.0),
                        fields.Datetime.to_string(ln.start_date),
                        fields.Datetime.to_string(ln.end_date),
                    ),
                })
        # Leave
        if self.include_leave:
            for lv in self.env['hr.leave'].sudo().search([('state', 'in', ['confirm', 'validate1'])]):
                mgr = self._manager_user_of(lv.employee_id)
                if not mgr:
                    continue
                res.setdefault(mgr.id, []).append({
                    'emp': lv.employee_id, 'model': 'hr.leave', 'rec': lv,
                    'date': fields.Date.to_string(lv.request_date_from or lv.date_from),
                    'detail': _("Từ %s đến %s") % (
                        fields.Datetime.to_string(lv.request_date_from or lv.date_from),
                        fields.Datetime.to_string(lv.request_date_to or lv.date_to),
                    ),
                })
        # Attendance tay
        if self.include_attendance:
            for at in self.env['hr.attendance'].sudo().search([('state', '=', 'to_submit')]):
                mgr = self._manager_user_of(at.employee_id)
                if not mgr:
                    continue
                res.setdefault(mgr.id, []).append({
                    'emp': at.employee_id, 'model': 'hr.attendance', 'rec': at,
                    'date': fields.Datetime.to_string(at.check_in or fields.Datetime.now()),
                    'detail': _("Check-in: %s — Check-out: %s") % (
                        fields.Datetime.to_string(at.check_in) if at.check_in else '-',
                        fields.Datetime.to_string(at.check_out) if at.check_out else '-',
                    ),
                })
        return res

    def _collect_all_pending(self):
        """List tất cả items (dùng cho chế độ users/groups/partners)."""
        self.ensure_one()
        items = []
        if self.include_ot:
            for ln in self.env['smartbiz_hr.request_line'].sudo().search([('state', 'in', ['to_submit', 'to_approve'])]):
                items.append({
                    'emp': ln.employee_id, 'model': 'smartbiz_hr.request_line', 'rec': ln,
                    'date': fields.Datetime.to_string(ln.start_date),
                    'detail': "+%.2f giờ (%s – %s)" % (
                        (ln.duration or 0.0),
                        fields.Datetime.to_string(ln.start_date),
                        fields.Datetime.to_string(ln.end_date),
                    ),
                })
        if self.include_leave:
            for lv in self.env['hr.leave'].sudo().search([('state', 'in', ['confirm', 'validate1'])]):
                items.append({
                    'emp': lv.employee_id, 'model': 'hr.leave', 'rec': lv,
                    'date': fields.Date.to_string(lv.request_date_from or lv.date_from),
                    'detail': _("Từ %s đến %s") % (
                        fields.Datetime.to_string(lv.request_date_from or lv.date_from),
                        fields.Datetime.to_string(lv.request_date_to or lv.date_to),
                    ),
                })
        if self.include_attendance:
            for at in self.env['hr.attendance'].sudo().search([('state', '=', 'to_submit')]):
                items.append({
                    'emp': at.employee_id, 'model': 'hr.attendance', 'rec': at,
                    'date': fields.Datetime.to_string(at.check_in or fields.Datetime.now()),
                    'detail': _("Check-in: %s — Check-out: %s") % (
                        fields.Datetime.to_string(at.check_in) if at.check_in else '-',
                        fields.Datetime.to_string(at.check_out) if at.check_out else '-',
                    ),
                })
        return items

    # =========================
    # ===== RENDER/MAIL =======
    # =========================
    def _base_url(self):
        return self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')

    def _rtype_label(self, model_name):
        if model_name == 'smartbiz_hr.request_line':
            return _('Làm thêm giờ / Overtime')
        if model_name == 'hr.leave':
            return _('Nghỉ phép / Leave')
        if model_name == 'hr.attendance':
            return _('Cập nhật công / Attendance Update')
        return model_name

    def _rec_form_url(self, model, rec_id):
        return f"{self._base_url()}/web#id={rec_id}&model={model}&view_type=form"

    def _render_items_table(self, items):
        rows = []
        for it in items:
            url = self._rec_form_url(it['model'], it['rec'].id)
            rows.append(f"""
                <tr>
                  <td>{it['emp'].display_name}</td>
                  <td>{self._rtype_label(it['model'])}</td>
                  <td>{it['date']}</td>
                  <td>{it['detail']}</td>
                  <td><a href="{url}">Phê duyệt / Từ chối</a><br/><a href="{url}">Approve / Reject</a></td>
                </tr>
            """)
        if not rows:
            rows.append(f"""<tr><td colspan="5" style="text-align:center;padding:8px;color:#888">
                {_('Không có yêu cầu nào đang chờ duyệt / No pending requests.')}</td></tr>""")
        thead = f"""
            <thead style="background:#f3f4f6">
              <tr>
                <th>{_('Nhân viên / Employee')}</th>
                <th>{_('Loại yêu cầu / Request Type')}</th>
                <th>{_('Ngày yêu cầu / Request Date')}</th>
                <th>{_('Chi tiết / Details')}</th>
                <th>{_('Thao tác / Action')}</th>
              </tr>
            </thead>"""
        return f"""<table border="1" cellpadding="6" cellspacing="0" width="100%" style="border-collapse:collapse">
            {thead}<tbody>{''.join(rows)}</tbody></table>"""

    def _render_default_body(self, items, manager_name=None):
        base_url = self._base_url()
        items_html = self._render_items_table(items)
        header = _('[Tổng hợp yêu cầu chờ phê duyệt] / [Approval Request Summary]')
        hi = _('Kính gửi Quản lý,') if not manager_name else (_('Kính gửi ') + manager_name + ',')
        hi_en = _('Dear Manager,') if not manager_name else (_('Dear ') + manager_name + ',')
        return f"""
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px">
          <p><b>{header}</b></p>
          <p>{hi}<br/>{hi_en}</p>
          <p>{_('Dưới đây là các yêu cầu chờ phê duyệt của đội ngũ Anh/Chị:')}<br/>
             {_('The following requests from your team members are pending your approval:')}</p>
          {items_html}
          <p>{_('Vui lòng đăng nhập hệ thống để xem chi tiết và xử lý:')} <a href="{base_url}">{_('[Link phê duyệt]')}</a><br/>
             {_('Please log in to the system to review and take action:')} <a href="{base_url}">{_('[Approval Link]')}</a></p>
          <p>{_('Xin cảm ơn sự hợp tác kịp thời của Anh/Chị.')}<br/>{_('Thank you for your prompt response.')}</p>
          <p>{_('Trân trọng,')}<br/>{_('Best regards,')}<br/><b>MARUNIX VIETNAM</b><br/>SmartBiz HR Management System</p>
        </div>
        """

    def _send_email(self, email_to_list, subject, body_html):
        emails = [e for e in (email_to_list or []) if e]
        if not emails:
            return
        mail = self.env['mail.mail'].sudo().create({
            'subject': subject or self.subject,
            'email_to': ','.join(sorted(set(emails))),
            'body_html': body_html,
            'auto_delete': True,
        })
        mail.send()

    def _emails_from_groups(self):
        emails = set()
        for g in self.users_ids:  # users_ids hiện đang là res.groups
            for u in g.users:
                if u.partner_id and u.partner_id.email:
                    emails.add(u.partner_id.email)
        return emails
        
    # =========================
    # ===== Main Sender =======
    # =========================
    def _send_digest(self):
        for cfg in self:
            template = cfg.mail_template_id
            subject = cfg.subject or ''
            base_ctx = {'base_url': cfg._base_url()}

            if cfg.recipient_mode == 'manager':
                pending_map = cfg._collect_pending_by_manager()
                for mgr_id, items in pending_map.items():
                    user = self.env['res.users'].browse(mgr_id)
                    email_to = user.partner_id.email if user and user.partner_id else False
                    if not email_to:
                        continue
                    items_html = cfg._render_items_table(items)
                    if template:
                        vals = template.with_context(items_html=items_html,
                                                     manager_name=user.name or '',
                                                     **base_ctx).generate_email(cfg.id)
                        cfg._send_email([email_to], vals.get('subject') or subject, vals.get('body_html') or '')
                    else:
                        body = cfg._render_default_body(items, manager_name=user.name or '')
                        cfg._send_email([email_to], subject, body)

            elif cfg.recipient_mode in ('users', 'groups', 'partners'):
                items = cfg._collect_all_pending()
                items_html = cfg._render_items_table(items)
                emails = set()
                if cfg.recipient_mode == 'users':
                    for u in cfg.user_groups_ids:  # user_groups_ids hiện là res.users
                        if u.partner_id and u.partner_id.email:
                            emails.add(u.partner_id.email)
                elif cfg.recipient_mode == 'groups':
                    emails |= cfg._emails_from_groups()
                elif cfg.recipient_mode == 'partners':
                    for p in cfg.partners_ids:
                        if p.email:
                            emails.add(p.email)
                if not emails:
                    continue
                if template:
                    vals = template.with_context(items_html=items_html, **base_ctx).generate_email(cfg.id)
                    cfg._send_email(list(emails), vals.get('subject') or subject, vals.get('body_html') or '')
                else:
                    body = cfg._render_default_body(items)
                    cfg._send_email(list(emails), subject, body)

class smartbiz_hr_MailerTime(models.Model):
    _name = "smartbiz_hr.mailer_time"
    _description = "Mailer Time"
    mailer_id = fields.Many2one('smartbiz_hr.mailer_configuration', string='Mailer')
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    hour = fields.Integer(string='Hour')
    minute = fields.Integer(string='Minute')
    last_run = fields.Date(string='Last Run')
    active = fields.Boolean(string='Active')


    @api.depends('hour', 'minute')
    def _compute_name(self):
        for r in self:
            r.name = "%02d:%02d" % (r.hour or 0, r.minute or 0)

    @api.constrains('hour', 'minute')
    def _check_time(self):
        for r in self:
            if not (0 <= int(r.hour or 0) <= 23 and 0 <= int(r.minute or 0) <= 59):
                raise ValidationError(_("Giờ/phút không hợp lệ."))

    def _is_due(self, tzname, now_utc=None, tolerance_min=DEFAULT_TOLERANCE_MIN):
        """Kiểm tra mốc này có đến hạn tại thời điểm now_utc (theo tz) và chưa gửi trong ngày local chưa."""
        self.ensure_one()
        if not self.active:
            return False
        tz = pytz.timezone(tzname or 'UTC')
        now_utc = now_utc or fields.Datetime.now()
        now_local = now_utc.astimezone(tz)

        sched_local = now_local.replace(hour=int(self.hour or 0), minute=int(self.minute or 0), second=0, microsecond=0)
        # tránh gửi trùng trong cùng một ngày local
        if self.last_run and self.last_run == sched_local.date():
            return False
        delta_min = abs((now_local - sched_local).total_seconds()) / 60.0
        return delta_min <= float(tolerance_min or 0)

