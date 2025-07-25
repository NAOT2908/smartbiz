
from exponent_server_sdk import (
    PushClient,
    PushMessage,
) 
from requests.exceptions import ConnectionError, HTTPError
from lxml import etree
from odoo import api, fields, models, _
import pika
import logging
import traceback
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.safe_eval import safe_eval, test_python_expr
import threading
import requests
from requests.auth import HTTPBasicAuth
import json
_logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os,json,re
import base64,pytz,logging,unidecode,textwrap
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

class RES_Partner(models.Model):
    _inherit = ['res.partner']
    partner_type = fields.Selection([('account','Account'),('site','Site'),('requester','Requester'),('user','User'),], string='Partner type')
    account_id = fields.Many2one('res.partner', string='Account')
    site_id = fields.Many2one('res.partner', string='Site')
    sites_ids = fields.One2many('res.partner', 'account_id')
    requesters_ids = fields.One2many('res.partner', 'site_id')
    users_ids = fields.One2many('res.partner', 'site_id')
    invoice_name = fields.Char(string='Invoice Name')


class RES_Groups(models.Model):
    _inherit = ['res.groups']
    type = fields.Selection([('product','Product'),('level','Level'),('roles','Roles'),('ou','OU'),('function','Function'),('position','Position'),], string='Type')


class SmartBiz_WorkflowDefinition(models.Model):
    _name = "smartbiz.workflow_definition"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Workflow Definition"
    name = fields.Char(string='Name')
    model_id = fields.Many2one('ir.model', string='Model')
    version = fields.Integer(string='Version', default = 1)
    task_definition_ids = fields.One2many('smartbiz.task_definition', 'workflow_definition_id')
    state_ids = fields.One2many('smartbiz.workflow_state', 'workflow_definition_id')
    function_ids = fields.One2many('smartbiz.function', 'workflow_definition_id')
    auto_job_ids = fields.Many2many('ir.cron', string='Auto Job')
    state = fields.Selection([('active','Active'),('inactive','Inactive'),], string= 'Status', readonly= False, copy = True, index = False, default = 'active')


    def action_active_create_state(self):
        field = self.env['ir.model.fields'].search([('model','=',self.model_id.model),('name','=','state')])

        selections = self.env['ir.model.fields.selection'].search([('field_id','=',field.id)])
        for s in selections:
            state = self.state_ids.search([('value','=',s.value),('workflow_definition_id','=',self.id)])
            if not state:
                self.write({'state_ids':[[0,0,{'name':s.name,'value':s.value,'sequence':s.sequence}]]})

        
        
    def action_active_create_function(self):
        model = self.env[self.model_id.model]
        view = self.env['ir.ui.view'].search([
            ('model', '=', self.model_id.model),
            ('type', '=', 'form')
        ], limit=1)
        
        if not view:
            return []
        
        arch_xml = view.read_combined(['arch_db'])['arch_db']
        doc = etree.fromstring(arch_xml)
        
        buttons = doc.xpath("//header/button")
        
        button_info = []
        for button in buttons:
            name = button.get('name')
            string = button.get('string')
            type_ = button.get('type')
            button_info.append({
                'name': name,
                'string': string,
                'type': 'button',
            })
        for btinfo in button_info:
            function = self.function_ids.search([('function_name','=',btinfo['name'])])
            if not function:
                self.write({'function_ids':[[0,0,{'name':btinfo['string'],'function_name':btinfo['name'],'type':btinfo['type']}]]})

        
        
    def action_inactive_reactivate(self):
        self.write({'state': 'active'})

        
        
class SmartBiz_RabbitmqSever(models.Model):
    _name = "smartbiz.rabbitmq_sever"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Rabbitmq Sever"
    name = fields.Char(string='Name')
    host = fields.Char(string='Host')
    user = fields.Char(string='User')
    password = fields.Char(string='Password')
    port = fields.Integer(string='Port', default = 5672)
    channel_number = fields.Integer(string='Channel Number')
    type = fields.Selection([('produce','Produce'),('consumer','Consumer'),], string='Type')
    routing_key = fields.Char(string='Routing key')
    exchange = fields.Char(string='Exchange')
    queue_name = fields.Char(string='Queue name')
    exchange_type = fields.Selection([('direct','Direct'),('fanout','Fanout'),('topic','Topic'),('headers','Headers'),], string='Exchange Type')
    passive = fields.Boolean(string='Passive')
    durable = fields.Boolean(string='Durable')
    auto_delete = fields.Boolean(string='Auto Delete')
    internal = fields.Boolean(string='Internal')
    model_id = fields.Many2one('ir.model', string='Model')
    code = fields.Text(string='Code')
    state = fields.Selection([('stopped','Stopped'),('running','Running'),], compute='_compute_state', store=True, string= 'Status', readonly= False, copy = True, index = False, default = 'stopped')


    def _compute_state(self):
        try:
            host = f"http://{self.host}:15672/api/queues"
            res = requests.get(host,
                               auth=HTTPBasicAuth(self.user, self.password)).json()
            if not res:
                self.state = "stopped"
            else:
                for item in res:
                    if item['name'] == self.queue_name and item['consumers'] > 0:
                        self.state = "running"
            if not self.state:
                self.state = "stopped"

        except Exception as err:
            self.state = "stopped"
            _logger.error(f"...{traceback.format_exc()}")

    def action_stopped_run(self):
        try:
            if self.state != 'running':
                channel = self.get_client()
                self.state = 'running'
                _logger.info(f"rabbit server:{self.name}")
                t = threading.Thread(target=channel.start_consuming)
                t.setDaemon(True)
                t.start()
        except Exception as err:
            self.state = 'stopped'
            _logger.error(f"：{traceback.format_exc()}")

        
        
    def publish(self, body, type="plain"):
      
        try:
            if type == "json":
                body = json.dumps(body)
            credential = pika.PlainCredentials(self.user, self.password)
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host=self.host, credentials=credential))
            channel = conn.channel(
                self.channel_number if self.channel_number else None)
            channel.exchange_declare(
                exchange=self.exchange, exchange_type=self.exchange_type, durable=self.durable, passive=self.passive,
                auto_delete=self.auto_delete, internal=self.internal)
            channel.basic_publish(
                exchange=self.exchange, routing_key=self.routing_key or "", body=body)
            _logger.info(f"{self.exchange}：{body}")
        except Exception as err:
            _logger.error(
                f"{self.exchange}：{body}：{traceback.format_exc()}")

    @api.constrains('code')
    def _check_python_code(self):
        for action in self.sudo().filtered('code'):
            msg = test_python_expr(expr=action.code.strip(), mode="exec")
            if msg:
                raise ValidationError(msg)


    @api.model
    def _get_eval_context(self, action=None):
        """ Prepare the context used when evaluating python code, like the
        python formulas or code server actions.

        :param action: the current server action
        :type action: browse record
        :returns: dict -- evaluation context given to (safe_)safe_eval """
        def log(message, level="info"):
            with self.pool.cursor() as cr:
                cr.execute("""
                    INSERT INTO ir_logging(create_date, create_uid, type, dbname, name, level, message, path, line, func)
                    VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (self.env.uid, 'server', self._cr.dbname, __name__, level, message, "action", action.id, action.name))

        eval_context = super(SmartBiz_RabbitmqSever, self)._get_eval_context(action=action)
        model_name = action.model_id.sudo().model
        model = self.env[model_name]
        record = None
        records = None
        if self._context.get('active_model') == model_name and self._context.get('active_id'):
            record = model.browse(self._context['active_id'])
        if self._context.get('active_model') == model_name and self._context.get('active_ids'):
            records = model.browse(self._context['active_ids'])
        if self._context.get('onchange_self'):
            record = self._context['onchange_self']
        eval_context.update({
            # orm
            'env': self.env,
            'model': model,
            # Exceptions
            #'Warning': Warning,
            # record
            'record': record,
            'records': records,
            # helpers
            'log': log,
        })
        return eval_context


    def call_back(self, ch, method, properties, body):
        _logger.info(f"rabbitmq:{body}")
        with api.Environment.manage():
            new_cr = self.pool.cursor()
            self = self.with_env(self.env(cr=new_cr))

            eval_context = self._get_eval_context(self)
            eval_context['body'] = json.loads(body.decode())
            safe_eval(self.code.strip(), eval_context, mode="exec", nocopy=True)
            # committed
            new_cr.commit()
            new_cr.close()
            if ch.is_open:
                ch.basic_ack(method.delivery_tag)

    def get_client(self):
       
        try:
            credential = pika.PlainCredentials(self.user, self.password)
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host=self.host, credentials=credential))
            channel = conn.channel(
                self.channel_number if self.channel_number else None)
            channel.exchange_declare(
                exchange=self.exchange, exchange_type=self.exchange_type, durable=self.durable, passive=self.passive,
                auto_delete=self.auto_delete, internal=self.internal)
            queue_name = self.queue_name if self.queue_name else ""
            result = channel.queue_declare(queue_name, durable=True)
            if not queue_name:
                self.queue_name = result.method.queue

            channel.queue_bind(exchange=self.exchange, queue=self.queue_name)
            channel.basic_consume(self.queue_name, self.call_back)
            return channel

        except Exception as err:
            _logger.error(f"RabbimtMq:{traceback.format_exc()}")

    def check_running(self):
        for record in self.search([]):
            try:

                if record.state != 'running':
                    channel = record.get_client()
                    record.state = 'running'
                    _logger.info(f"rabbit server:{self.name}")
                    t = threading.Thread(target=channel.start_consuming)
                    t.setDaemon(True)
                    t.start()
            except Exception as err:
                record.state = 'stopped'
                _logger.error(f"：{traceback.format_exc()}")

class SmartBiz_DeviceRegister(models.Model):
    _name = "smartbiz.device_register"
    _description = "Device Register"
    name = fields.Char(string='Name')
    user_id = fields.Many2one('res.users', string='User')
    token = fields.Char(string='Token')
    active_date = fields.Datetime(string='Active Date')


    def register(self,name,uid,token):
        res = self.search([('name','=',name),('user_id','=',uid),('token','=',token)],limit=1)
        if res:
            res.write({'active_date',datetime.now()})
        else:
            self.create({'name':name,'user_id':uid,'token':token,'active_date':datetime.now()})

    def unregister(self,name,uid,token):
        res = self.search([('name', '=', name), ('user_id', '=', uid), ('token', '=', token)])
        for record in res:
            record.unlink()

class SmartBiz_WorkflowState(models.Model):
    _name = "smartbiz.workflow_state"
    _description = "Workflow State"
    sequence = fields.Integer(string='Sequence', default = 10)
    name = fields.Char(string='State')
    value = fields.Char(string='Value')
    workflow_definition_id = fields.Many2one('smartbiz.workflow_definition', string='Workflow Definition', ondelete='cascade')


class SmartBiz_Delegation(models.Model):
    _name = "smartbiz.delegation"
    _rec_name = "delegator_id"
    _description = "Delegation"
    delegator_id = fields.Many2one('res.users', string='Delegator')
    delegatee_id = fields.Many2one('res.users', string='Delegatee')
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    task_type_id = fields.Many2one('smartbiz.task_type', string='Task Type')
    active = fields.Boolean(string='Active')


    def get_actual_assignees(self, user_ids):
        actual_users = self.env['res.users']
        for user in user_ids:
            delegation = self.env['delegation'].search([
                ('delegator_id', '=', user.id),
                ('start_date', '<=', fields.Datetime.now()),
                ('end_date', '>=', fields.Datetime.now()),
                ('active', '=', True),
            ], limit=1)
            if delegation:
                actual_users |= delegation.delegatee_id
            else:
                actual_users |= user
        return actual_users

class SmartBiz_OrganizationUnit(models.Model):
    _name = "smartbiz.organization_unit"
    _description = "Organization Unit"
    name = fields.Char(string='Unit Name')
    parent_unit_id = fields.Many2one('smartbiz.organization_unit', string='Parent Unit')
    child_units_ids = fields.One2many('smartbiz.organization_unit', 'parent_unit_id')
    position_ids = fields.One2many('smartbiz.position', 'organization_unit_id')
    established_date = fields.Datetime(string='Established Date')
    history = fields.Char(string='History')


class SmartBiz_Role(models.Model):
    _name = "smartbiz.role"
    _description = "Role"
    name = fields.Char(string='Role Name')
    level_id = fields.Many2one('smartbiz.level', string='Level')


class SmartBiz_Position(models.Model):
    _name = "smartbiz.position"
    _description = "Position"
    name = fields.Char(string='Position Name')
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit')
    level_id = fields.Many2one('smartbiz.level', string='Level')
    users_ids = fields.Many2many('res.users', 'position_users_rel',  string='Users')
    roles_ids = fields.Many2many('smartbiz.role', string='Roles')
    reports_to_ids = fields.Many2many('smartbiz.position', 'position_position_rel_1', 'reports_to_ids_1', 'reports_to_ids_2', string='Reports To')


class SmartBiz_Level(models.Model):
    _name = "smartbiz.level"
    _description = "Level"
    name = fields.Char(string='Level Name')
    hierarchy_order = fields.Integer(string='Hierarchy Order')


class SmartBiz_TaskType(models.Model):
    _name = "smartbiz.task_type"
    _description = "Task Type"
    name = fields.Char(string='Name')
    code = fields.Char(string='Code')
    description = fields.Text(string='Description')
    can_delegate = fields.Boolean(string='Can Delegate')
    duration_type = fields.Selection([('hours','Hours'),('days','Days'),('weeks','Weeks'),('months','Months'),], string='Duration Type', default = 'days')
    default_duration = fields.Float(string='Default Duration')
    allowed_positions_ids = fields.Many2many('smartbiz.position', string='Allowed Positions')
    allowed_roles_ids = fields.Many2many('smartbiz.role', string='Allowed Roles')
    allowed_levels_ids = fields.Many2many('smartbiz.level', string='Allowed Levels')
    allowed_organization_units_ids = fields.Many2many('smartbiz.organization_unit', 'task_type_organization_unit_rel',  string='Allowed Organization Units')
    task_definition_ids = fields.One2many('smartbiz.task_definition', 'task_type_id')


class SmartBiz_TaskDefinition(models.Model):
    _name = "smartbiz.task_definition"
    _description = "Task Definition"
    name = fields.Char(string='Task Name')
    workflow_definition_id = fields.Many2one('smartbiz.workflow_definition', string='Workflow Definition', required=True)
    state_id = fields.Many2one('smartbiz.workflow_state', string='State')
    duration_type = fields.Selection([('hours','Hours'),('days','Days'),('weeks','Weeks'),('months','Months'),], string='Duration Type', default = 'days')
    duration = fields.Float(string='Duration')
    can_delegate = fields.Boolean(string='Can Delegate', default = lambda self: self.task_type_id.can_delegate)
    delegate_template_id = fields.Many2one('mail.template', string='Delegate Template')
    task_type_id = fields.Many2one('smartbiz.task_type', string='Task Type', required=True)
    function_ids = fields.Many2many('smartbiz.function', string='Function')
    notification_ids = fields.Many2many('smartbiz.notification_condition', 'task_definition_notification_condition_rel',  string='Notification')
    transfer_ids = fields.Many2many('smartbiz.transfer_condition', 'task_definition_transfer_condition_rel',  string='Transfer')
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=True)


    @api.depends('workflow_definition_id')
    def _compute_model_id(self):
        for record in self:
            record.model_id = record.workflow_definition_id.model_id.id

    def compute_deadline(self, start_date=None):
        for record in self:
            duration_type = record.duration_type
            duration = record.duration or 0
            if start_date is None:
                start_date = datetime.now()  # Ngày hiện tại
            else:
                start_date = datetime.strptime(start_date, '%Y-%m-%d')  # Chuyển đổi từ chuỗi sang đối tượng datetime

            # Tính toán deadline dựa trên duration_type
            if duration_type == 'days':
                deadline = start_date + timedelta(days=duration)
            elif duration_type == 'weeks':
                deadline = start_date + timedelta(weeks=duration)
            elif duration_type == 'hours':
                deadline = start_date + timedelta(hours=duration)
            else:
                deadline = start_date
            return deadline

class SmartBiz_Rule(models.Model):
    _name = "smartbiz.rule"
    _description = "Rule"
    sequence = fields.Integer(string='Sequence', default = 10)
    name = fields.Char(string='Rule Name', required=True, default = 'New')
    function_id = fields.Many2one('smartbiz.function', string='Function', required=True, ondelete='cascade')
    task_finish = fields.Selection([('any','Any'),('parallel','Parallel'),('sequence','Sequence'),], string='Task Finish', default = 'any')
    condition_ids = fields.One2many('smartbiz.condition', 'rule_id')
    resource_ids = fields.One2many('smartbiz.resource', 'rule_id')


    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz.rule') or 'New'


        res = super().create(values)


        return res

class SmartBiz_Condition(models.Model):
    _name = "smartbiz.condition"
    _description = "Condition"
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=True)
    name = fields.Char(string='Condition Name', compute='_compute_name', store=True)
    rule_id = fields.Many2one('smartbiz.rule', string='Rule', ondelete='cascade')
    field_id = fields.Many2one('ir.model.fields', string='Field')
    operator = fields.Selection([('=','Equal to'),('!=','Not equal to'),('>','Greater than'),('<','Less than'),('>=','Greater than or equal to'),('<=','Less than or equal to'),('in','In (in set)'),('not in','Not in (not in set)'),('like','LIKE (case-sensitive)'),('ilike','ILIKE (case-insensitive)'),], string='Operator')
    value = fields.Char(string='Value')


    @api.depends('rule_id')
    def _compute_model_id(self):
        for record in self:
            record.model_id = record.rule_id.function_id.workflow_definition_id.model_id.id

    @api.depends('field_id', 'operator', 'value')
    def _compute_name(self):
        for record in self:
            record.name = (record.field_id.name or '') + ' ' + (record.operator or '') + ' ' + (record.value or '')

class SmartBiz_Resource(models.Model):
    _name = "smartbiz.resource"
    _description = "Resource"
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=False)
    name = fields.Char(string='Resource Name', compute='_compute_name', store=True)
    rule_id = fields.Many2one('smartbiz.rule', string='Rule', ondelete='cascade')
    method = fields.Selection([('by_position','By Position'),('by_role','By Role'),('by_level','By Level'),('by_ou','By OU'),('by_user_field','By User Field'),('by_ou_field','By OU Field'),], string='Method', required=True)
    operator = fields.Selection([('and','AND'),('or','OR'),], string='Operator', default = 'or')
    position_id = fields.Many2one('smartbiz.position', string='Position')
    role_id = fields.Many2one('smartbiz.role', string='Role')
    level_id = fields.Many2one('smartbiz.level', string='Level')
    user_field_id = fields.Many2one('ir.model.fields', string='User Field')
    ou_field_id = fields.Many2one('ir.model.fields', string='OU Field')
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit')
    organization_scope = fields.Selection([('self','Self'),('parent','Parent'),('children','Children'),('self-parent','Self-Parent'),('self-children','Self-Children'),], string='Organization Scope', default = 'self')


    @api.depends('rule_id')
    def _compute_model_id(self):
        for record in self:
            record.model_id = record.rule_id.function_id.workflow_definition_id.model_id.id

    @api.depends('method', 'position_id', 'role_id', 'level_id', 'user_field_id', 'ou_field_id', 'organization_unit_id')
    def _compute_name(self):
        for record in self:
            name = ''
            if record.method == 'by_position':
                name = 'Vị trí: ' + (record.position_id.name or '')
            if record.method == 'by_role':
                name = 'Vai trò: ' + (record.role_id.name or '')
            if record.method == 'by_level':
                name = 'Cấp bậc: ' + (record.level_id.name or '')
            if record.method == 'by_ou':
                name = 'Đơn vị tổ chức: ' + (record.organization_unit_id.name or '')
            if record.method == 'by_user_field':
                name = 'Trường user: ' + (record.user_field_id.name or '')
            if record.method == 'by_ou_field':
                name = 'Trường OU: ' + (record.ou_field_id.name or '')
            record.name = name

class SmartBiz_Action(models.Model):
    _name = "smartbiz.action"
    _description = "Action"
    workflow_definition_id = fields.Many2one('smartbiz.workflow_definition', string='Workflow Definition', compute='_compute_workflow_definition_id', store=True)
    name = fields.Char(string='Action Name', compute='_compute_name', store=True)
    function_id = fields.Many2one('smartbiz.function', string='Function', ondelete='cascade')
    type = fields.Selection([('send_notification','Send Notification'),('move_to_state','Move to State'),('run_server_action','Run Server Action'),], string='Type', index=True)
    trigger_type = fields.Selection([('on_user_assignment','On User Assignment'),('on_user_action','On User Action'),('on_task_complete','On Task Complete'),], string='Trigger Type', index=True)
    server_action_id = fields.Many2one('ir.actions.server', string='Server Action')
    template_id = fields.Many2one('mail.template', string='Template')
    state_id = fields.Many2one('smartbiz.workflow_state', string='State')
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=True)


    @api.depends('function_id')
    def _compute_workflow_definition_id(self):
        for record in self:
            record.workflow_definition_id = record.function_id.workflow_definition_id.id

    @api.depends('type', 'trigger_type')
    def _compute_name(self):
        for record in self:
            record.name = (record.type or '') + ' - ' + (record.trigger_type or '')

    @api.depends('workflow_definition_id')
    def _compute_model_id(self):
        for record in self:
            record.model_id = record.workflow_definition_id.model_id.id

class SmartBiz_Function(models.Model):
    _name = "smartbiz.function"
    _description = "Function"
    name = fields.Char(string='Name')
    function_name = fields.Char(string='Function Name')
    workflow_definition_id = fields.Many2one('smartbiz.workflow_definition', string='Workflow Definition', ondelete='cascade')
    type = fields.Selection([('button','Button'),('system','System'),], string='Type', default = 'button')
    run_code = fields.Selection([('after','After'),('before','Before'),], string='Run Code')
    rule_ids = fields.One2many('smartbiz.rule', 'function_id')
    action_ids = fields.One2many('smartbiz.action', 'function_id')


class SmartBiz_Task(models.Model):
    _name = "smartbiz.task"
    _description = "Task"
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    model = fields.Char(string='Model', required=True)
    res_id = fields.Integer(string='Res ID', required=True)
    document_name = fields.Char(string='Document Name', compute='_compute_document_name', store=True)
    task_definition_id = fields.Many2one('smartbiz.task_definition', string='Task Definition', required=True, ondelete='cascade')
    deadline = fields.Datetime(string='Deadline')
    assignees_ids = fields.Many2many('res.users', 'task_users_rel',  string='Assignees')
    actual_users_ids = fields.Many2many('res.users', 'task_users_rel_12',  string='Actual Users')
    start = fields.Datetime(string='Start', default = lambda self: fields.datetime.now())
    finish = fields.Datetime(string='Finish')
    duration = fields.Float(string='Duration')
    state = fields.Selection([('assigned','Assigned'),('processing','Processing'),('overdue','Overdue'),('done','Done'),('cancel','Cancel'),], string='State', default = 'assigned')
    work_log_ids = fields.One2many('smartbiz.work_log', 'task_id')
    notification_log_ids = fields.One2many('smartbiz.notification_log', 'task_id')
    transfer_log_ids = fields.One2many('smartbiz.transfer_log', 'task_id')
    state_iteration = fields.Integer(string='State Iteration', default = 0)
    document_state = fields.Char(string='Document State')
    pending_users_ids = fields.Many2many('res.users', 'task_users_rel_11',  string='Pending Users')
    completed_users_ids = fields.Many2many('res.users', 'task_users_rel_10',  string='Completed Users')


    @api.depends('document_name', 'task_definition_id')
    def _compute_name(self):
        for record in self:
            record.name =  (record.document_name or '') + ' - ' + (record.task_definition_id.name or '')

    @api.depends('model', 'res_id')
    def _compute_document_name(self):
        for record in self:
            record.document_name =  self.env[record.model].browse(record.res_id).display_name

    def check_task_conditions(self):
        tasks = self.env['smartbiz.task'].search([('state', 'not in', ['done', 'cancel'])])
        current_time = fields.Datetime.now()
        for task in tasks:
            # Kiểm tra điều kiện thông báo
            for notification in task.task_definition_id.notification_ids:
                days_before_overdue = notification.days_before_overdue
                interval_hours = notification.interval_hours
                max_notice = notification.max_notice

                # Tính thời gian cảnh báo
                deadline_alert = task.deadline - timedelta(days=days_before_overdue)
                if current_time >= deadline_alert:
                    last_notice = task.notification_log_ids.filtered(
                        lambda log: log.notification_condition_id == notification
                    ).sorted(key=lambda l: l.time, reverse=True)
                    if not last_notice or (current_time - last_notice[0].time).total_seconds() >= interval_hours * 3600:
                        # Gửi thông báo và ghi log
                        template = notification.notification_template_id
                        if template:
                            template.send_mail(task.id, force_send=True)

                        reason = 'Thông báo trước hạn' if current_time < task.deadline else 'Quá hạn'
                        self.env['smartbiz.notification_log'].create({
                            'task_id': task.id,
                            'notification_condition_id': notification.id,
                            'time': current_time,
                            'users_ids': [(6, 0, task.assignees_ids.ids)],
                            'reason': reason,
                        })
                        # Không hủy task khi đạt max_notice

            # Kiểm tra điều kiện điều chuyển
            for transfer in task.task_definition_id.transfer_ids:
                if transfer.overdue_transfer and current_time > task.deadline:
                    transfer_count = len(task.transfer_log_ids.filtered(
                        lambda l: l.transfer_condition_id == transfer
                    ))
                    if transfer_count < transfer.max_transfer:
                        # Xác định người nhận điều chuyển
                        to_users = self.env['res.users']
                        if transfer.to_manager:
                            # Tìm manager của người dùng hiện tại
                            current_user = task.assignees_ids and task.assignees_ids[0] or False
                            if current_user:
                                manager = self.get_manager(current_user)
                                if manager:
                                    to_users |= manager
                                else:
                                    _logger.warning("Không tìm thấy manager cho người dùng hiện tại.")
                            else:
                                _logger.warning("Không xác định được người dùng hiện tại để tìm manager.")
                        else:
                            # Sử dụng người dùng được chỉ định
                            to_users = transfer.to_users_ids

                        if to_users:
                            # Ghi log điều chuyển
                            self.env['smartbiz.transfer_log'].create({
                                'task_id': task.id,
                                'transfer_condition_id': transfer.id,
                                'time': current_time,
                                'from_user_id': task.assignees_ids and task.assignees_ids[0].id or False,
                                'to_users_ids': [(6, 0, to_users.ids)],
                                'reason': 'Điều chuyển do quá hạn',
                            })
                            # Cập nhật người thực hiện task
                            task.assignees_ids = [(6, 0, to_users.ids)]
                            # Gửi thông báo
                            if transfer.notification_template_id:
                                transfer.notification_template_id.send_mail(task.id, force_send=True)

                            if transfer.create_new_task:
                                # Tạo task mới nếu cần
                                new_task = task.copy({
                                    'state': 'assigned',
                                    'start': fields.Datetime.now(),
                                    'deadline': task.deadline + timedelta(days=1),
                                })
                        else:
                            _logger.warning("Không có người dùng để điều chuyển task.")
                    else:
                        task.state = 'cancel'

    def get_manager(self, user):
        """Tìm manager của người dùng dựa trên mô hình tổ chức."""
        if not user:
            return False
        # Giả sử mỗi người dùng liên kết với một vị trí (position)
        positions = self.env['smartbiz.position'].search([('users_ids', 'in', user.id)])
        if positions:
            # Lấy vị trí quản lý (reports_to_ids)
            manager_positions = positions.mapped('reports_to_ids')
            if manager_positions:
                # Lấy người dùng trong vị trí quản lý
                managers = manager_positions.mapped('users_ids')
                return managers
        return False
    
    def transfer_task(self, to_user, reason):
        self.ensure_one()
        # Cập nhật người thực hiện
        self.assignees_ids = [(4, to_user.id)]
        # Ghi log điều chuyển
        self.env['smartbiz.transfer_log'].create({
            'task_id': self.id,
            'time': fields.Datetime.now(),
            'from_user_id': self.env.uid,
            'to_users_ids': [(6, 0, [to_user.id])],
            'reason': reason,
        })
        # Gửi thông báo
        template = self.task_definition_id.delegate_template_id
        if template:
            template.send_mail(self.id, force_send=True)

class SmartBiz_WorkLog(models.Model):
    _name = "smartbiz.work_log"
    _description = "Work Log"
    name = fields.Char(string='Name')
    task_id = fields.Many2one('smartbiz.task', string='Task', ondelete='cascade')
    function_id = fields.Many2one('smartbiz.function', string='Function')
    rule_id = fields.Many2one('smartbiz.rule', string='Rule')
    user_id = fields.Many2one('res.users', string='User')
    date = fields.Datetime(string='Date', default = lambda self: fields.datetime.now())
    state_iteration = fields.Integer(string='State Iteration')
    document_state = fields.Char(string='Document State')


class SmartBiz_NotificationCondition(models.Model):
    _name = "smartbiz.notification_condition"
    _description = "Notification Condition"
    name = fields.Char(string='Name')
    days_before_overdue = fields.Float(string='Days before Overdue')
    time_in_day = fields.Float(string='Time in day')
    interval_hours = fields.Float(string='Interval Hours')
    max_notice = fields.Integer(string='Max Notice')
    notification_template_id = fields.Many2one('mail.template', string='Notification Template')
    model_id = fields.Many2one('ir.model', string='Model')


class SmartBiz_TransferCondition(models.Model):
    _name = "smartbiz.transfer_condition"
    _description = "Transfer Condition"
    name = fields.Char(string='Name')
    overdue_transfer = fields.Boolean(string='Overdue Transfer')
    max_transfer = fields.Integer(string='Max Transfer')
    to_manager = fields.Boolean(string='To Manager')
    to_users_ids = fields.Many2many('res.users', 'transfer_condition_users_rel',  string='To Users')
    create_new_task = fields.Boolean(string='Create New Task')
    notification_template_id = fields.Many2one('mail.template', string='Notification Template')
    model_id = fields.Many2one('ir.model', string='Model')


class SmartBiz_NotificationLog(models.Model):
    _name = "smartbiz.notification_log"
    _rec_name = "notification_condition_id"
    _description = "Notification Log"
    task_id = fields.Many2one('smartbiz.task', string='Task', ondelete='cascade')
    notification_condition_id = fields.Many2one('smartbiz.notification_condition', string='Notification Condition')
    time = fields.Datetime(string='Time')
    users_ids = fields.Many2many('res.users', 'notification_log_users_rel',  string='Users')
    reason = fields.Char(string='Reason')


class SmartBiz_TransferLog(models.Model):
    _name = "smartbiz.transfer_log"
    _rec_name = "transfer_condition_id"
    _description = "Transfer Log"
    task_id = fields.Many2one('smartbiz.task', string='Task', ondelete='cascade')
    transfer_condition_id = fields.Many2one('smartbiz.transfer_condition', string='Transfer Condition')
    time = fields.Datetime(string='Time')
    from_user_id = fields.Many2one('res.users', string='From User')
    to_users_ids = fields.Many2many('res.users', 'transfer_log_users_rel',  string='To Users')
    reason = fields.Char(string='Reason')


