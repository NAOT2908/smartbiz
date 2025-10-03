from collections import defaultdict
from dateutil.relativedelta import relativedelta
# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions, _, tools
import os, json, re
import base64, pytz, logging, unidecode, textwrap
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

# >>> ADD
from urllib.parse import quote  # URL encode cho domain JSON


# ============================================================================
#   HR Work Entry (mở rộng)
# ============================================================================
class HR_WorkEntry(models.Model):
    _inherit = ['hr.work.entry']
    workcenter_id = fields.Many2one('mrp.workcenter', string='Workcenter')
    ok_quantity = fields.Float(string='OK Quantity')
    ng_quantity = fields.Float(string='NG Quantity')


# ============================================================================
#   Payslip (bổ sung thống kê sản xuất & ngày công chuẩn)
# ============================================================================
class HR_Payslip(models.Model):
    _inherit = ['hr.payslip']
    name = fields.Char(store='True')

    # --------------------------------------------------------------
    # Lịch làm việc tháng: trả về (ngày công, giờ công) sau khi trừ
    # ngày nghỉ lễ toàn công ty (global leaves).
    # --------------------------------------------------------------
    def _get_month_workstats(self, exclude_public_holiday=True, use_payslip_period=False):
        """
        Trả về tuple (workdays_float, workhours_float).

        - exclude_public_holiday=True: trừ các leave global (resource_id=False).
        - use_payslip_period=False: mặc định tính cho *toàn tháng* chứa date_from.
          Nếu True => dùng chính khoảng date_from–date_to của payslip.
        """
        self.ensure_one()

        # Lấy calendar theo chuẩn: contract > employee > company.
        cal = (
            self.contract_id.resource_calendar_id
            or self.employee_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        if not cal or not self.date_from:
            return 0.0, 0.0

        if use_payslip_period and self.date_to:
            date_start = self.date_from
            date_end = self.date_to
        else:
            # Toàn bộ tháng chứa date_from
            month_start = self.date_from.replace(day=1)
            month_end = month_start + relativedelta(months=1, days=-1)
            date_start = month_start
            date_end = month_end

        dt_start = datetime.combine(date_start, time.min)
        dt_end = datetime.combine(date_end, time.max)

        if exclude_public_holiday:
            # Domain chỉ lấy nghỉ lễ chung (global)
            domain = [('time_type', '=', 'leave'), ('resource_id', '=', False)]
            compute_leaves = True
        else:
            domain = None
            compute_leaves = False

        dur = cal.get_work_duration_data(
            dt_start, dt_end,
            compute_leaves=compute_leaves,
            domain=domain,
        )
        # Hàm trả về {'days': n, 'hours': h}
        return float(dur.get('days', 0.0)), float(dur.get('hours', 0.0))

    def _get_production_activity_summary(self):
        """
        Kết quả:
        --------
        prod_wc  : { workcenter_id: {
                        'records' : recordset smartbiz_mes.production_activity,
                        'quantity': float,
                        'duration': float,   # phút
                        'quality' : float,
                        'cost'    : float,   # tiền tệ
                    }, ... }
        prod_total : {'records', 'quantity', 'duration', 'quality', 'cost'}
        """
        self.ensure_one()

        if not self.date_from or not self.date_to:
            empty_rec = self.env['smartbiz_mes.production_activity']
            return {}, {'records': empty_rec,
                        'quantity': 0.0, 'duration': 0.0,
                        'quality': 0.0, 'cost': 0.0}

        # Ghép date -> datetime toàn ngày
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
            duration_min = act.duration or 0.0            # phút
            duration_hr = duration_min / 60.0             # giờ
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

        # Ép defaultdict về dict
        summary = {k: dict(v, records=v['records']) for k, v in summary.items()}
        total = dict(total, records=total['records'])
        return summary, total

    # ------------------------------------------------------------------
    # Đưa dữ liệu vào localdict
    # ------------------------------------------------------------------
    def _get_localdict(self):
        localdict = super()._get_localdict()
        localdict['env'] = self.env

        prod_wc, prod_total = self._get_production_activity_summary()
        month_workdays, month_workhours = self._get_month_workstats(
            exclude_public_holiday=True,
            use_payslip_period=False,  # đổi True nếu muốn theo kỳ payslip
        )

        localdict.update({
            'prod_wc': prod_wc,
            'prod_total': prod_total,
            'month_workdays': month_workdays,    # ngày công chuẩn (trừ nghỉ lễ)
            'month_workhours': month_workhours,  # giờ công chuẩn (trừ nghỉ lễ)
        })
        return localdict


# ============================================================================
#   Overtime Request
# ============================================================================
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
    approver_ids = fields.Many2many('res.users', 'overtime_request_users_rel', string='Approver')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_submit', 'To Submit'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], string='Status', readonly=False, copy=True, index=False, tracking=True, default='draft')

    # ------------------------------------------------------------------
    # Cấu hình hệ thống (điền đúng xmlid nếu có action/menu sẵn)
    # ------------------------------------------------------------------
    _OT_ACTION_XMLID = 'smartbiz_hr.smartbiz_hr_overtime_request_action'  # sửa theo module của bạn
    _OT_MENU_XMLID = 'smartbiz_hr.smartbiz_hr_overtime_request_menu'      # sửa theo module của bạn
    _OT_NOTIFY_EMAIL = 'toannd@adsose.com'                              # email đích cố định

    # ======  Helpers gửi mail  =================================================
    def _get_partner_for_notify(self):
        """Đảm bảo tồn tại res.partner cho email nhận thông báo."""
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([('email', '=', self._OT_NOTIFY_EMAIL)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': 'OT Notification',
                'email': self._OT_NOTIFY_EMAIL,
            })
        return partner

    def _get_action_ids(self):
        """Trả về (action_id, menu_id) nếu tìm được xmlid; nếu không có trả None."""
        action_id = menu_id = None
        if self._OT_ACTION_XMLID:
            try:
                action_id = self.env.ref(self._OT_ACTION_XMLID).id
            except Exception:
                _logger.warning("Không tìm thấy action xmlid %s", self._OT_ACTION_XMLID)
        if self._OT_MENU_XMLID:
            try:
                menu_id = self.env.ref(self._OT_MENU_XMLID).id
            except Exception:
                _logger.warning("Không tìm thấy menu xmlid %s", self._OT_MENU_XMLID)
        return action_id, menu_id

    def _build_list_url(self, state=None):
        """URL mở danh sách yêu cầu OT; nếu truyền state => áp domain lọc."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        action_id, menu_id = self._get_action_ids()

        params = []
        if action_id:
            params.append('action=%s' % action_id)
        params.append('model=smartbiz_hr.overtime_request')
        params.append('view_type=list')
        if menu_id:
            params.append('menu_id=%s' % menu_id)
        # Domain lọc theo state (nếu truyền)
        if state:
            domain = json.dumps([('state', '=', state)])
            params.append('domain=%s' % quote(domain))
        url = '%s/web#%s' % (base_url, '&'.join(params))
        return url

    def _build_record_url(self, record):
        """URL mở form từng record."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/web#id=%s&model=smartbiz_hr.overtime_request&view_type=form' % (base_url, record.id)

    def _render_email_table(self, records):
        """Sinh bảng HTML liệt kê các yêu cầu."""
        rows = []
        for r in records:
            url = self._build_record_url(r)
            emp_count = len(r.employee_ids)
            start = tools.format_datetime(self.env, r.start_date, tz=self.env.user.tz or None, dt_format=False) if r.start_date else ''
            end = tools.format_datetime(self.env, r.end_date, tz=self.env.user.tz or None, dt_format=False) if r.end_date else ''
            rows.append(f"""
                <tr>
                    <td><a href="{url}">{tools.html_escape(r.name or 'Không tên')}</a></td>
                    <td style="text-align:center;">{emp_count}</td>
                    <td>{start}</td>
                    <td>{end}</td>
                    <td>{tools.html_escape(dict(self._fields['state'].selection).get(r.state, r.state))}</td>
                </tr>
            """)
        if not rows:
            rows.append('<tr><td colspan="5"><i>(Không có bản ghi)</i></td></tr>')
        table = f"""
            <table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
              <thead style="background:#eee;">
                <tr>
                  <th>Tên</th>
                  <th>Nhân viên</th>
                  <th>Bắt đầu</th>
                  <th>Kết thúc</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {''.join(rows)}
              </tbody>
            </table>
        """
        return table

    def _send_notify_email(self, purpose, target_state=None, records=None):
        """
        purpose: 'check' (cần kiểm tra) | 'approve' (cần phê duyệt)
        target_state: lọc danh sách chung trong link (vd 'to_submit', 'to_approve')
        records: recordset cụ thể vừa thao tác (mặc định self)
        """
        self.ensure_one()  # sẽ được gọi trong vòng lặp ở action; đảm bảo ít nhất 1 để lấy env
        if records is None:
            records = self

        partner = self._get_partner_for_notify()
        list_url = self._build_list_url(target_state)
        table_html = self._render_email_table(records)

        if purpose == 'check':
            subject = _("OT cần kiểm tra")
            intro = _("<p>Xin chào,<br/>Có các yêu cầu OT vừa được gửi cần kiểm tra.</p>")
        else:
            subject = _("OT cần phê duyệt")
            intro = _("<p>Xin chào,<br/>Có các yêu cầu OT đang chờ phê duyệt.</p>")

        body_html = f"""
            <div>
              {intro}
              {table_html}
              <p style="margin-top:16px;">
                <a href="{list_url}"><b>Mở danh sách các yêu cầu (lọc: {target_state or 'all'})</b></a>
              </p>
            </div>
        """

        Mail = self.env['mail.mail'].sudo()
        mail = Mail.create({
            'subject': subject,
            'email_to': partner.email,
            'body_html': body_html,
            'auto_delete': True,
        })
        # gửi ngay; nếu muốn queue cron -> bỏ comment send=False
        mail.send()

    # ======  Duration compute  =================================================
    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for rec in self:
            if rec.end_date and rec.start_date:
                rec.duration = (rec.end_date - rec.start_date).total_seconds() / 3600
            else:
                rec.duration = 0

    # ------------------------------------------------------------------
    # action_draft_submit
    # ------------------------------------------------------------------
    def action_draft_submit(self):
        for req in self:
            # Tạo / cập nhật line
            vals_list = []
            for emp in req.employee_ids:
                line = req.lines_ids.filtered(lambda l: l.employee_id == emp)
                if line:
                    line.write({
                        'start_date': req.start_date,
                        'end_date': req.end_date,
                        'state': 'to_submit',
                    })
                else:
                    vals_list.append({
                        'request_id': req.id,
                        'employee_id': emp.id,
                        'start_date': req.start_date,
                        'end_date': req.end_date,
                        'state': 'to_submit',
                    })
            if vals_list:
                self.env['smartbiz_hr.request_line'].create(vals_list)

            old = req.state
            req.write({'state': 'to_submit'})
            req._post_state_message(old)

            # >>> ADD: gửi mail thông báo cần kiểm tra
            try:
                req._send_notify_email(
                    purpose='check',
                    target_state='to_submit',
                    records=req,
                )
            except Exception as e:
                _logger.exception("Lỗi gửi mail notify action_draft_submit: %s", e)

        return True

    # ------------------------------------------------------------------
    # action_to_submit_approve
    # ------------------------------------------------------------------
    def action_to_submit_approve(self):
        for req in self:
            req._set_lines_state('to_approve')
            old = req.state
            req.state = 'to_approve'
            req._post_state_message(old)
        return True

    # ------------------------------------------------------------------
    # action_to_submit_refuse
    # ------------------------------------------------------------------
    def action_to_submit_refuse(self):
        # NOTE: biến reason chưa được truyền ở code gốc -> bỏ / hoặc thêm param
        for req in self:
            req._set_lines_state('refused')
            old = req.state
            req.write({'state': 'refused', 'approver_ids': [(4, self.env.uid)]})
            req._post_state_message(old)
            # if reason:
            #     req.message_post(body=_("Lý do từ chối: %s") % reason,
            #                      subtype_xmlid='mail.mt_comment')
        return True

    # ------------------------------------------------------------------
    # action_to_approve_approve
    # ------------------------------------------------------------------
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

            # >>> ADD: gửi mail thông báo cần phê duyệt (trước khi duyệt xong? hoặc báo đã duyệt?)
            # Ở đây theo yêu cầu: khi người dùng bấm phê duyệt thì gửi danh sách các lệnh *đang cần phê duyệt*.
            # Do record vừa chuyển sang approved, ta gửi link lọc state='to_approve' để reviewer khác duyệt tiếp các record khác.
            try:
                req._send_notify_email(
                    purpose='approve',
                    target_state='to_approve',
                    records=req,
                )
            except Exception as e:
                _logger.exception("Lỗi gửi mail notify action_to_approve_approve: %s", e)

        return True

    # ======  State sync helpers  ===============================================
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
                body=_("Trạng thái thay đổi từ <b>%s</b> → <b>%s</b> bởi %s.") %
                     (sel.get(old_state, old_state),
                      sel.get(req.state, req.state),
                      self.env.user.display_name),
                subtype_xmlid='mail.mt_comment'
            )


# ============================================================================
#   Request Line
# ============================================================================
class smartbiz_hr_RequestLine(models.Model):
    _name = "smartbiz_hr.request_line"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Request Line"

    request_id = fields.Many2one('smartbiz_hr.overtime_request', string='Request')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_submit', 'To Submit'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], string='Status', readonly=False, copy=True, index=False, tracking=True, default='draft')

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

    # ------  OT type helper (giữ nguyên như đã gửi trước) ------
    def _is_public_holiday(self, day_date, employee):
        cal = employee.resource_calendar_id or self.env.ref('resource.resource_calendar_std')
        Leave = self.env['resource.calendar.leaves']
        return bool(Leave.search([
            ('calendar_id', '=', cal.id),
            ('date_from', '<=', datetime.combine(day_date, datetime.min.time())),
            ('date_to', '>=', datetime.combine(day_date, datetime.max.time())),
        ], limit=1))

    def _get_ot_type_code(self):
        self.ensure_one()
        if not self.start_date:
            return 'ot150'
        start_local = self.start_date.astimezone()
        day_date = start_local.date()
        if self._is_public_holiday(day_date, self.employee_id):
            return 'ot300'
        if start_local.weekday() >= 5:
            return 'ot200'
        return 'ot150'

    # ------  Work Entry creator  ------
    def _create_or_update_work_entry(self):
        WE = self.env['hr.work.entry']
        WEType = self.env['hr.work.entry.type']
        for line in self.filtered(lambda l: l.state == 'approved'):
            code = line._get_ot_type_code().upper()
            wetype = WEType.search([('code', '=', code)], limit=1)
            if not wetype:
                raise UserError(_("Chưa khai báo Work Entry Type code %s.") % code)

            domain = [
                ('employee_id', '=', line.employee_id.id),
                ('date_start', '<=', line.end_date),
                ('date_stop', '>=', line.start_date),
                ('work_entry_type_id', '=', wetype.id),
            ]
            entry = WE.search(domain, limit=1)
            vals = {
                'name': 'OT',
                'employee_id': line.employee_id.id,
                'contract_id': line.employee_id.contract_id.id,
                'date_start': line.start_date,
                'date_stop': line.end_date,
                'work_entry_type_id': wetype.id,
                'state': 'validated',
            }
            if entry:
                entry.sudo().write(vals)
            else:
                WE.sudo().create(vals)

    # ----------------------------------------------------------
    #  Override write: đồng bộ state + thông báo
    # ----------------------------------------------------------
    def write(self, vals):
        state_changed = 'state' in vals
        old_states = {rec.id: rec.state for rec in self} if state_changed else {}
        res = super().write(vals)

        if state_changed:
            sel = dict(self._fields['state'].selection)
            for line in self:
                line.message_post(
                    body=_("Trạng thái thay đổi từ <b>%s</b> → <b>%s</b> bởi %s.") %
                         (sel.get(old_states[line.id], old_states[line.id]),
                          sel.get(line.state, line.state),
                          self.env.user.display_name),
                    subtype_xmlid='mail.mt_comment'
                )
            # Sau khi log → đồng bộ cha & tạo work-entry nếu cần
            self._create_or_update_work_entry()
            self.mapped('request_id')._sync_state_from_lines()
        return res


# ============================================================================
#   Work Entry Rule structures (chưa đổi)
# ============================================================================
class smartbiz_hr_WorkEntryRuleCategory(models.Model):
    _name = "smartbiz_hr.work_entry_rule_category"
    _description = "Work Entry Rule Category"

    name = fields.Char(string='Name')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    rules_ids = fields.One2many('smartbiz_hr.work_entry_rule', 'category_id')


class smartbiz_hr_WorkEntryRule(models.Model):
    _name = "smartbiz_hr.work_entry_rule"
    _description = "Work Entry Rule"

    name = fields.Char(string='Name')
    category_id = fields.Many2one('smartbiz_hr.work_entry_rule_category', string='Category')
    sequence = fields.Integer(string='Sequence')
    active = fields.Boolean(string='Active', default=True)
    when = fields.Selection([
        ('after_generate', 'After Generate'),
        ('before_generate', 'Before Generate'),
    ], string='When', default='after_generate')
    rule_type = fields.Selection([
        ('rounding', 'Rounding'),
        ('grace', 'Grace'),
        ('overtime_tier', 'Overtime Tier'),
        ('shift_differential', 'Shift Differential'),
        ('lateness', 'Lateness'),
    ], string='Rule Type', required=True)
    condition_ids = fields.One2many('smartbiz_hr.we_rule_condition', 'rule_id')
    action_ids = fields.One2many('smartbiz_hr.we_rule_action', 'rule_id')


class smartbiz_hr_WERuleCondition(models.Model):
    _name = "smartbiz_hr.we_rule_condition"
    _rec_name = "rule_id"
    _description = "WE Rule Condition"

    rule_id = fields.Many2one('smartbiz_hr.work_entry_rule', string='Rule')
    python_code = fields.Text(string='Python Code')


class smartbiz_hr_WERuleAction(models.Model):
    _name = "smartbiz_hr.we_rule_action"
    _rec_name = "rule_id"
    _description = "WE Rule Action"

    rule_id = fields.Many2one('smartbiz_hr.work_entry_rule', string='Rule')
    action_type = fields.Selection([
        ('round_start', 'Round Start'),
        ('round_stop', 'Round Stop'),
        ('adjust_rate', 'Adjust Rate'),
        ('split_interval', 'Split Interval'),
        ('create_entry', 'Create Entry'),
    ], string='Action Type')
    parameter = fields.Json(string='Parameter')


class smartbiz_hr_WERuleLog(models.Model):
    _name = "smartbiz_hr.we_rule_log"
    _description = "WE Rule Log"

    rule_id = fields.Many2one('smartbiz_hr.work_entry_rule', string='Rule')
    work_entry_id = fields.Many2one('hr.work.entry', string='Work Entry')
    employee_id = fields.Many2one('hr.employee', string='Employee')