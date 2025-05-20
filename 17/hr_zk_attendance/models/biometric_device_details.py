# -*- coding: utf-8 -*-
################################################################################
#    Biometric Device Integration (Hard‑coded rules demo)
#
#    • Tải dữ liệu log từ máy chấm công (ZK)
#    • Tự tạo nhân viên nếu chưa có (lấy tên từ thiết bị)
#    • Lưu log vào zk.machine.attendance luôn kèm employee_id
#    • Suy luận và sinh hr.attendance theo ca làm việc
#
#    Copy nguyên file này vào module Odoo của bạn, khai báo __init__.py & __manifest__.py
#    rồi cập nhật module là chạy.
################################################################################
import datetime
import logging
import pytz
import itertools

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)
try:
    from zk import ZK
except ImportError:
    _logger.error("Please install pyzk:  pip3 install pyzk")

# ========= HARD‑CODED RULES =========
TOLERANCE_CHECKIN = 15      # ± minutes around shift start
TOLERANCE_CHECKOUT = 15     # ± minutes around shift end
SPLIT_MULTI_SHIFT = True    # split by calendar intervals
AUTOFILL_ONE_PUNCH = 'start'  # 'none' | 'start' | 'end'
MAX_SHIFT_HOURS = 12
TOLERANCE_GAP_MERGE = 30    # minutes to merge close punches
ALLOW_CROSS_MIDNIGHT = True
AUTO_CREATE_EMPLOYEE = True


class BiometricDeviceDetails(models.Model):
    """Khai báo thiết bị chấm công và xử lý log."""

    _name = 'biometric.device.details'
    _description = 'Biometric Device Details'

    # ---------------------------------------------------------------------
    #   Fields
    # ---------------------------------------------------------------------
    name = fields.Char(required=True)
    device_ip = fields.Char(required=True)
    port_number = fields.Integer(required=True)
    address_id = fields.Many2one('res.partner', string='Working Address')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    last_download_time = fields.Datetime(
        default="1970-01-01 00:00:00",
        string="Last Download (UTC)")

    # ---------------------------------------------------------------------
    #   LOW‑LEVEL HELPERS
    # ---------------------------------------------------------------------
    def device_connect(self, zk):
        """Return active connection or False."""
        try:
            return zk.connect()
        except Exception:
            return False

    def _get_device_user_names(self, conn):
        """{user_id: name} fetched from device."""
        try:
            return {u.user_id: (u.name or '') for u in conn.get_users() or []}
        except Exception:
            return {}

    def _employee_from_device_id(self, user_id, user_name, cache):
        """Lookup or create employee by device id, cached per run."""
        emp = cache.get(user_id)
        if emp:
            return emp
        emp = self.env['hr.employee'].search([('device_id_num', '=', user_id)], limit=1)
        if not emp and AUTO_CREATE_EMPLOYEE:
            emp = self.env['hr.employee'].create({
                'name': user_name or _(f"Emp {user_id}"),
                'device_id_num': user_id,
                'company_id': self.company_id.id,
            })
        cache[user_id] = emp
        return emp

    # ---------------------------------------------------------------------
    #   USER ACTIONS
    # ---------------------------------------------------------------------
    def action_test_connection(self):
        zk = ZK(self.device_ip, port=self.port_number, timeout=30)
        try:
            if zk.connect():
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': _('Successfully connected'),
                        'type': 'success',
                    }
                }
        except Exception as e:
            raise ValidationError(str(e))

    def action_set_timezone(self):
        for rec in self:
            zk = ZK(rec.device_ip, port=rec.port_number, timeout=15)
            conn = rec.device_connect(zk)
            if not conn:
                raise UserError(_('Device connection failed'))
            user_tz = rec.env.user.tz or 'UTC'
            now_user = pytz.utc.localize(fields.Datetime.now()).astimezone(pytz.timezone(user_tz))
            conn.set_time(now_user)
            conn.disconnect()
        return True

    def action_clear_attendance(self):
        for rec in self:
            zk = ZK(rec.device_ip, port=rec.port_number, timeout=30)
            conn = rec.device_connect(zk)
            if not conn:
                raise UserError(_('Cannot connect to device'))
            conn.disable_device()
            conn.clear_attendance()
            self.env.cr.execute("DELETE FROM zk_machine_attendance WHERE address_id=%s", (rec.address_id.id,))
            conn.enable_device()
            conn.disconnect()
        return True

    # ---------------------------------------------------------------------
    #   CRON / PUBLIC DOWNLOAD
    # ---------------------------------------------------------------------
    @api.model
    def cron_download(self):
        for dev in self.search([]):
            dev.action_download_attendance()

    def action_download_attendance(self):
        for dev in self:
            new_last, raw_ids = dev._download_raw_data()
            if raw_ids:
                dev._process_raw_data(raw_ids)
            if new_last:
                dev.last_download_time = new_last.replace(tzinfo=None)

    # ---------------------------------------------------------------------
    #   STEP 1: DOWNLOAD RAW DATA (ALWAYS WITH employee_id)
    # ---------------------------------------------------------------------
    def _download_raw_data(self):
        self.ensure_one()
        zk_attendance = self.env['zk.machine.attendance']
        last_dt = fields.Datetime.from_string(self.last_download_time or "1970-01-01 00:00:00").replace(tzinfo=pytz.utc)
        newest_dt = last_dt
        new_raw_ids = []

        zk = ZK(self.device_ip, port=self.port_number, timeout=15)
        conn = self.device_connect(zk)
        if not conn:
            raise UserError(_('Cannot connect to device'))

        conn.disable_device()
        user_name_map = self._get_device_user_names(conn)
        recs = conn.get_attendance() or []
        device_tz = pytz.FixedOffset(420)  # UTC+7
        allowed_punch = {'0', '1', '2', '3', '4', '5', '255'}
        emp_cache = {}

        for r in recs:
            utc_dt = device_tz.localize(r.timestamp).astimezone(pytz.utc)
            if utc_dt <= last_dt or utc_dt > datetime.datetime.now(pytz.utc):
                continue
            if utc_dt > newest_dt:
                newest_dt = utc_dt

            # duplicate check
            if zk_attendance.search_count([
                ('device_id_num', '=', r.user_id),
                ('punching_time', '=', fields.Datetime.to_string(utc_dt))
            ]):
                continue

            emp = self._employee_from_device_id(r.user_id, user_name_map.get(r.user_id), emp_cache)
            if not emp:
                continue  # skip if cannot map employee

            punch_val = str(r.punch) if str(r.punch) in allowed_punch else '255'
            att = zk_attendance.create({
                'employee_id': emp.id,
                'device_id_num': r.user_id,
                'attendance_type': str(r.status),
                'punch_type': punch_val,
                'punching_time': fields.Datetime.to_string(utc_dt),
                'address_id': self.address_id.id,
            })
            new_raw_ids.append(att.id)

        conn.enable_device()
        conn.disconnect()
        _logger.info("[%s] Inserted %s new raw lines", self.device_ip, len(new_raw_ids))
        return (newest_dt if newest_dt > last_dt else False, new_raw_ids)

    # ---------------------------------------------------------------------
    #   STEP 2: PROCESS RAW DATA -> hr.attendance
    # ---------------------------------------------------------------------
    def _process_raw_data(self, raw_ids):
        zk_attendance = self.env['zk.machine.attendance'].browse(raw_ids)
        if not zk_attendance:
            return
        hr_attendance = self.env['hr.attendance']

        # group by employee + date UTC
        grouped = sorted(zk_attendance, key=lambda r: (r.employee_id.id, r.punching_time))
        for (emp_id, work_date), group in itertools.groupby(
                grouped,
                key=lambda r: (
                    r.employee_id.id,
                    fields.Date.to_string(fields.Datetime.from_string(r.punching_time).astimezone(pytz.utc).date()))):

            emp = self.env['hr.employee'].browse(emp_id)
            punches = list(group)
            punches.sort(key=lambda r: r.punching_time)

            cal = emp.resource_calendar_id or emp.contract_id.resource_calendar_id
            if not SPLIT_MULTI_SHIFT or not cal:
                self._create_att(emp, punches, hr_attendance)
                continue

            d0 = fields.Date.from_string(work_date)

            # ---- tạo datetime có tzinfo UTC ----
            start_dt = datetime.datetime.combine(
                d0, datetime.time.min, tzinfo=pytz.utc)
            end_dt = start_dt + datetime.timedelta(days=1)

            intervals = cal._work_intervals_batch(
                start_dt, end_dt, resources=[emp.resource_id], tz=pytz.utc
            )

            # Nếu hàm trả list, dùng luôn; nếu trả dict (phiên bản Odoo khác) thì .get()
            if not isinstance(intervals, list):
                intervals = intervals.get(emp.resource_id, [])

            
            for iv in intervals:
                st = iv[0] - datetime.timedelta(minutes=TOLERANCE_CHECKIN)
                en = iv[1] + datetime.timedelta(minutes=TOLERANCE_CHECKOUT)
                st = st.astimezone(pytz.utc)
                en = en.astimezone(pytz.utc)
                chunk = [p for p in punches if st <= fields.Datetime.from_string(p.punching_time) <= en]
                if chunk:
                    self._create_att(emp, chunk, hr_attendance)

    # ---------------------------------------------------------------------
    #   HELPER: build one hr.attendance
    # ---------------------------------------------------------------------
    def _create_att(self, emp, punch_lines, hr_attendance):
        punch_lines.sort(key=lambda l: l.punching_time)
        merged = []
        for p in punch_lines:
            if not merged:
                merged.append(p)
            else:
                gap = (fields.Datetime.from_string(p.punching_time) -
                       fields.Datetime.from_string(merged[-1].punching_time)).total_seconds() / 60
                if gap > TOLERANCE_GAP_MERGE:
                    merged.append(p)

        check_in_dt = fields.Datetime.from_string(merged[0].punching_time)
        check_out_dt = fields.Datetime.from_string(merged[-1].punching_time)

        # one punch case
        if len(merged) == 1:
            if AUTOFILL_ONE_PUNCH == 'none':
                if not hr_attendance.search_count([
                    ('employee_id', '=', emp.id),
                    ('check_in', '=', fields.Datetime.to_string(check_in_dt))]):
                    hr_attendance.create({'employee_id': emp.id, 'check_in': fields.Datetime.to_string(check_in_dt)})
                return
            elif AUTOFILL_ONE_PUNCH == 'start':
                check_out_dt = check_in_dt + datetime.timedelta(hours=8)
            elif AUTOFILL_ONE_PUNCH == 'end':
                check_in_dt = check_out_dt - datetime.timedelta(hours=8)

        duration = (check_out_dt - check_in_dt).total_seconds() / 3600
        if duration > MAX_SHIFT_HOURS:
            check_out_dt = check_in_dt + datetime.timedelta(hours=MAX_SHIFT_HOURS)

        if hr_attendance.search_count([
            ('employee_id', '=', emp.id),
            ('check_in', '=', fields.Datetime.to_string(check_in_dt))]):
            return  # duplicate
        hr_attendance.create({
            'employee_id': emp.id,
            'check_in': fields.Datetime.to_string(check_in_dt),
            'check_out': fields.Datetime.to_string(check_out_dt),
        })

    # ---------------------------------------------------------------------
    #   OTHER
    # ---------------------------------------------------------------------
    def action_restart_device(self):
        zk = ZK(self.device_ip, port=self.port_number, timeout=15)
        conn = self.device_connect(zk)
        if conn:
            conn.restart()
            conn.disconnect()
