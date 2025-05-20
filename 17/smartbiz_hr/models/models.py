# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging,unidecode
from datetime import datetime, timedelta, time
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

from collections import defaultdict


class HR_WorkEntry(models.Model):
    _inherit = ['hr.work.entry']
    workcenter_id = fields.Many2one('mrp.workcenter', string='Workcenter')
    ok_quantity = fields.Float(string='OK Quantity')
    ng_quantity = fields.Float(string='NG Quantity')


   

class HR_Payslip(models.Model):
    _inherit = ['hr.payslip']
    name = fields.Char(store='True')


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
        dt_stop  = datetime.combine(self.date_to,   time.max)

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
        total   = _init()

        for act in acts:
            wc_id = act.workcenter_id.id
            duration_min = act.duration or 0.0            # phút
            duration_hr  = duration_min / 60.0            # giờ
            cost_hour    = act.workcenter_id.costs_hour or 0.0
            cost         = duration_hr * cost_hour

            s = summary[wc_id]
            s['records']  += act
            s['quantity'] += act.quantity or 0.0
            s['duration'] += duration_min
            s['quality']  += act.quality or 0.0
            s['cost']     += cost

            total['records']  += act
            total['quantity'] += act.quantity or 0.0
            total['duration'] += duration_min
            total['quality']  += act.quality or 0.0
            total['cost']     += cost

        # Ép defaultdict về dict
        summary = {k: dict(v, records=v['records']) for k, v in summary.items()}
        total   = dict(total,  records=total['records'])
        return summary, total

    # ------------------------------------------------------------------
    # Đưa dữ liệu vào localdict
    # ------------------------------------------------------------------
    def _get_localdict(self):
        localdict = super()._get_localdict()
        localdict['env'] = self.env
        prod_wc, prod_total = self._get_production_activity_summary()
        localdict.update({
            'prod_wc'   : prod_wc,     # chi tiết theo workcenter
            'prod_total': prod_total,  # tổng toàn kỳ
        })
        return localdict    

class smartbiz_hr_OvertimeRequest(models.Model):
    _name = "smartbiz_hr.overtime_request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Overtime Request"
    name = fields.Char(string='Name')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    contract_id = fields.Many2one('hr.contract', string='Contract')
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    note = fields.Text(string='Note')
    approver_ids = fields.Many2many('res.users', string='Approver', readonly=True)
    state = fields.Selection([('draft','Draft'),('to_approve','To Approve'),('approved','Approved'),('refused','Refused'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for rec in self:
            if rec.end_date and rec.start_date:
                rec.duration = (rec.end_date - rec.start_date).total_seconds() / 3600
            else:
                rec.duration = 0

    def action_draft_send_to_approve(self):
        self.write({'state': 'to_approve'})

    def _is_public_holiday(self, day_date, employee):
        """
        Kiểm tra day_date (date) có phải ngày nghỉ lễ công ty.
        Dựa trên resource.calendar.leaves được gắn với calendar của employee.
        """
        cal = employee.resource_calendar_id or self.env.ref('resource.resource_calendar_std')
        Leave = self.env['resource.calendar.leaves']
        return bool(Leave.search([
            ('calendar_id', '=', cal.id),
            ('date_from', '<=', datetime.combine(day_date, datetime.min.time())),
            ('date_to',   '>=', datetime.combine(day_date, datetime.max.time())),
        
        ], limit=1))

    def _get_ot_type_code(self):
        """
        Trả về chuỗi 'ot150' / 'ot200' / 'ot300' cho bản ghi self
        (dựa trên ngày bắt đầu OT)
        """
        self.ensure_one()
        start_local = self.start_date.astimezone()   # dùng tz môi trường
        day_date = start_local.date()
        emp = self.employee_id

        # 1) Ưu tiên lễ
        if self._is_public_holiday(day_date, emp):
            return 'ot300'
        # 2) Cuối tuần
        if start_local.weekday() >= 5:          # 5=thứ7, 6=chủ nhật
            return 'ot200'
        # 3) Bình thường
        return 'ot150'          
        
    def action_to_approve_approve(self):
        WEType = self.env['hr.work.entry.type']

        for rec in self:
            if rec.state != 'to_approve':
                raise UserError(_("Only requests awaiting approval can be approved."))

            # Xác định mã OT: OT150 / OT200 / OT300
            type_code = rec._get_ot_type_code().upper()      # 'OT150' ...

            # Tìm Work Entry Type có code tương ứng (tạo tay)
            wetype = WEType.search([('code', '=', type_code)], limit=1)
            if not wetype:
                raise UserError(_(
                    "Work Entry Type with code %s not found. "
                    "Please create it in Settings → Work Entry Types.") % type_code)

            # Đổi trạng thái & tạo Work Entry OT
            rec.write({'state': 'approved', 'approver_ids': [(4,self.env.uid)]})
            self.env['hr.work.entry'].create({
                'name': 'OT',
                'employee_id'       : rec.employee_id.id,
                'contract_id'       : rec.employee_id.contract_id.id,
                'date_start'        : rec.start_date,
                'date_stop'         : rec.end_date,
                'work_entry_type_id': wetype.id,
                'state'             : 'validated',
            })

        
        
    def action_to_approve_refuce(self):
        self.write({'state': 'refused', 'approver_ids': [(4,self.env.uid)]})

        
        
class smartbiz_hr_WorkEntryRuleCategory(models.Model):
    _name = "smartbiz_hr.work_entry_rule_category"
    _description = "Work Entry Rule Category"
    name = fields.Char(string='Name')
    sequence = fields.Integer(string='Sequence', default = 10)
    active = fields.Boolean(string='Active', default = 'True')
    rules_ids = fields.One2many('smartbiz_hr.work_entry_rule', 'category_id')


class smartbiz_hr_WorkEntryRule(models.Model):
    _name = "smartbiz_hr.work_entry_rule"
    _description = "Work Entry Rule"
    name = fields.Char(string='Name')
    category_id = fields.Many2one('smartbiz_hr.work_entry_rule_category', string='Category')
    sequence = fields.Integer(string='Sequence')
    active = fields.Boolean(string='Active', default = 'True')
    when = fields.Selection([('after_generate','After Generate'),('before_generate','Before Generate'),], string='When', default = 'after_generate')
    rule_type = fields.Selection([('rounding','Rounding'),('grace','Grace'),('overtime_tier','Overtime Tier'),('shift_differential','Shift Differential'),('lateness','Lateness'),], string='Rule Type', required=True)
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
    action_type = fields.Selection([('round_start','Round Start'),('round_stop','Round Stop'),('adjust_rate','Adjust Rate'),('split_interval','Split Interval'),('create_entry','Create Entry'),], string='Action Type')
    parameter = fields.Json(string='Parameter')


class smartbiz_hr_WERuleLog(models.Model):
    _name = "smartbiz_hr.we_rule_log"
    _description = "WE Rule Log"
    rule_id = fields.Many2one('smartbiz_hr.work_entry_rule', string='Rule')
    work_entry_id = fields.Many2one('hr.work.entry', string='Work Entry')
    employee_id = fields.Many2one('hr.employee', string='Employee')


