# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging
from datetime import datetime, timedelta
import datetime as date_time
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

class purchase_order(models.Model):
    _inherit = ['purchase.order']
    purchase_requisition_id = fields.Many2one('smartbiz_purchase.requisition', string='Purchase Requisition')
    quotation_id = fields.Many2one('smartbiz_purchase.quotation', string='Quotation')


class purchase_orderline(models.Model):
    _inherit = ['purchase.order.line']
    requisition_line_id = fields.Many2one('smartbiz_purchase.requisition_line', string='Requisition Line')
    request_line_id = fields.Many2one('smartbiz_purchase.request_line', string='Request Line')
    quotation_line_id = fields.Many2one('smartbiz_purchase.quotation_line', string='Quotation Line')


class smartbiz_purchase_Request(models.Model):
    _name = "smartbiz_purchase.request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Request"
    name = fields.Char(string='Request', copy=False, default = 'New')
    requester_id = fields.Many2one('res.users', string='Requester', default = lambda self: self.env.user)
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit', required=True)
    request_category_id = fields.Many2one('smartbiz_purchase.request_category', string='Request Category')
    date = fields.Datetime(string='Date')
    budget_period_id = fields.Many2one('smartbiz_purchase.budget_period', string='Budget Period', required=True)
    budget_remain = fields.Float(string='Budget Remain', compute='_compute_budget_remain', store=True)
    request_amount = fields.Float(string='Request Amount', compute='_compute_request_amount', store=True)
    lines_ids = fields.One2many('smartbiz_purchase.request_line', 'request_id')
    description = fields.Text(string='Description')
    requisition_id = fields.Many2one('smartbiz_purchase.requisition', string='Requisition')
    state = fields.Selection([('draft','Draft'),('processing','Processing'),('approved','Approved'),('rejected','Rejected'),('ordering','Ordering'),('ordered','Ordered'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = False, index = False, default = 'draft')


    @api.depends('organization_unit_id', 'budget_period_id')
    def _compute_budget_remain(self):
        for record in self:  
            budget = self.env['smartbiz_purchase.budget'].search([
                    ['organization_unit_id','=',record.organization_unit_id.id],
                    ['period_id','=',record.budget_period_id.id],
                ],limit=1)
            record.budget_remain = budget.remain_amount or 0

    @api.depends('lines_ids', 'lines_ids.total_price')
    def _compute_request_amount(self):
        for record in self:  
            total = sum(line.total_price for line in record.lines_ids) or 0
            record.request_amount = total

    def action_draft_send_to_approve(self):
        self.write({'state': 'processing'})

        
        
    def action_processing_approve(self):
        self.write({'state': 'approved'})

        
        
    def action_processing_reject(self):
        self.write({'state': 'rejected'})

        
        
    def action_processing_redo(self):
        self.write({'state': 'draft'})

        
        
    def action_cancel_cancel(self):
        self.write({'state': 'cancel'})

        
        
    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_purchase.request') or 'New'


        res = super().create(values)


        return res

class smartbiz_purchase_RequestLine(models.Model):
    _name = "smartbiz_purchase.request_line"
    _description = "Request Line"
    name = fields.Char(string='Name')
    product_id = fields.Many2one('product.product', string='Product')
    description = fields.Text(string='Description')
    quantity = fields.Float(string='Quantity')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom_id', store=True)
    unit_price = fields.Float(string='Unit Price')
    total_price = fields.Float(string='Total Price', compute='_compute_total_price', store=True)
    delivery_date = fields.Datetime(string='Delivery Date')
    request_id = fields.Many2one('smartbiz_purchase.request', string='Request')
    requisition_line_id = fields.Many2one('smartbiz_purchase.requisition_line', string='Requisition Line')


    @api.depends('product_id')
    def _compute_uom_id(self):
        for record in self:
            record.uom_id = record.product_id.uom_id.id

    @api.depends('quantity', 'unit_price')
    def _compute_total_price(self):
        for record in self:  
            record.total_price = record.quantity * record.unit_price

class smartbiz_purchase_RequestCategory(models.Model):
    _name = "smartbiz_purchase.request_category"
    _description = "Request Category"
    name = fields.Char(string='Category')
    description = fields.Text(string='Description')


class smartbiz_purchase_Requisition(models.Model):
    _name = "smartbiz_purchase.requisition"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Requisition"
    name = fields.Char(string='Name', copy=False, default = 'New')
    date = fields.Datetime(string='Date')
    delivery_date = fields.Datetime(string='Delivery Date')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    requisition_amount = fields.Float(string='Requisition Amount', compute='_compute_requisition_amount', store=True)
    order_amount = fields.Float(string='Order Amount', compute='_compute_order_amount', store=True)
    lines_ids = fields.One2many('smartbiz_purchase.requisition_line', 'requisition_id')
    requests_ids = fields.One2many('smartbiz_purchase.request', 'requisition_id')
    quotation_ids = fields.One2many('smartbiz_purchase.quotation', 'requisition_id')
    quotations = fields.Integer(string='Quotations', compute='_compute_quotations', store=False)
    purchase_order_ids = fields.One2many('purchase.order', 'purchase_requisition_id')
    purchase_orders = fields.Integer(string='Purchase Orders', compute='_compute_purchase_orders', store=False)
    quotation_lines_ids = fields.One2many('smartbiz_purchase.quotation_line', 'requisition_id')
    quotation_lines = fields.Integer(string='Quotation Lines', compute='_compute_quotation_lines', store=False)
    state = fields.Selection([('draft','Draft'),('pr_processing','PR Processing'),('pr_approved','PR Approved'),('po_processing','PO Processing'),('po_approved','PO Approved'),('ordered','Ordered'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = False, index = False, default = 'draft')


    @api.depends('lines_ids', 'lines_ids.request_price')
    def _compute_requisition_amount(self):
        for record in self:  
            total = sum(line.request_total for line in record.lines_ids) or 0
            record.requisition_amount = total

    @api.depends('lines_ids', 'lines_ids.unit_price')
    def _compute_order_amount(self):
        for record in self:  
            total = sum(line.total_price for line in record.lines_ids) or 0
            record.order_amount = total

    @api.depends('quotation_ids')
    def _compute_quotations(self):
        for record in self:
            count = record.quotation_ids.search_count([('requisition_id', '=', record.id)])
            record.quotations = count

    @api.depends('purchase_order_ids')
    def _compute_purchase_orders(self):
        for record in self:
            count = record.purchase_order_ids.search_count([('purchase_requisition_id', '=', record.id)])
            record.purchase_orders = count

    @api.depends('quotation_lines_ids')
    def _compute_quotation_lines(self):
        for record in self:
            count = record.quotation_lines_ids.search_count([('requisition_id', '=', record.id)])
            record.quotation_lines = count

    def action_draft_create_product(self):
        for record in self:
            for request_line in record.requests_ids.lines_ids:
                if not request_line.requisition_line_id.id:
                    line = record.lines_ids.create({
                        'name':request_line.name,
                        'product_id':request_line.product_id.id,
                        'description':request_line.description,
                        'uom_id':request_line.uom_id.id,
                        'quantity':request_line.quantity,
                        'requisition_id':record.id
                    })
                    request_line.write({'requisition_line_id':line.id})

        
        
    def action_draft_send_for_approve(self):
        self.write({'state': 'pr_processing'})

        
        
    def action_pr_processing_approve(self):
        self.write({'state': 'pr_approved'})

        
        
    def action_pr_processing_redo(self):
        self.write({'state': 'draft'})

        
        
    def action_pr_approved_create_rfq(self):
        for record in self:
            quotation = record.quotation_ids.create({'currency_id':record.currency_id.id,'requisition_id':record.id})
            for line in record.lines_ids:
                quotation.write({'lines_ids':[(0,0,{
                    'name':line.name,
                    'product_id':line.product_id.id,
                    'description':line.description,
                    'uom_id':line.uom_id.id,
                    'quantity':line.quantity,
                    'unit_price':line.unit_price,
                    'requisition_line_id':line.id,
                    'requisition_id':record.id
                })]})

        
        
    def action_po_processing_po_approve(self):
        self.write({'state': 'po_approved'})

        
        
    def action_po_processing_po_redo(self):
        self.write({'state': 'pr_approved'})

        
        
    def action_po_approved_create_po(self):
        for record in self:
            for line in record.lines_ids:
                if line.quantity != line.order_quantity:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'show_confirm_dialog',  # Gọi hành động JavaScript
                        'params': {
                            'title': 'Số lượng không khớp',
                            'message': 'Số lượng đặt hàng và số lượng yêu cầu không khớp. Bạn có muốn tiếp tục?',
                            'method': 'create_po',  # Hàm cần gọi khi xác nhận
                            'model': self._name  # Gửi model hiện tại
                        }
                    }
            record.create_po()

    def create_po(self):
        PurchaseOrder = self.env['purchase.order']
        PurchaseOrderLine = self.env['purchase.order.line']
        
        for requisition in self:
            # Lọc các quotation lines có order_quantity > 0
            valid_quotation_lines = requisition.quotation_lines_ids.filtered(lambda line: line.order_quantity > 0)

            if not valid_quotation_lines:
                raise UserError(_("Không có dòng báo giá nào có số lượng đặt hàng lớn hơn 0."))

            # Tạo một dictionary để nhóm các dòng theo nhà cung cấp
            supplier_quotation_lines = {}
            for line in valid_quotation_lines:
                supplier = line.quotation_id.supplier_id
                if supplier not in supplier_quotation_lines:
                    supplier_quotation_lines[supplier] = []
                supplier_quotation_lines[supplier].append(line)

            # Tạo đơn hàng mua cho mỗi nhà cung cấp
            for supplier, lines in supplier_quotation_lines.items():
                purchase_order_vals = {
                    'partner_id': supplier.id,
                    'date_order': fields.Datetime.now(),
                    'quotation_id': lines[0].quotation_id.id,
                    'purchase_requisition_id': requisition.id,
                    'currency_id': requisition.currency_id.id,  # Sửa lại để lấy ID của currency
                    'order_line': [],
                }

                # Tạo các dòng chi tiết của đơn hàng mua
                for line in lines:
                    if not line.product_id:
                        raise UserError(_("Thiếu sản phẩm trên dòng báo giá."))
                    if not line.uom_id:
                        raise UserError(_("Thiếu đơn vị đo lường trên dòng báo giá."))
                    if line.order_quantity <= 0:
                        raise UserError(_("Số lượng đặt hàng phải lớn hơn 0."))
                    if not line.unit_price:
                        raise UserError(_("Thiếu giá đơn vị trên dòng báo giá."))

                    purchase_order_vals['order_line'].append((0, 0, {
                        'product_id': line.product_id.id,
                        'name': line.name or line.product_id.name,
                        'product_qty': line.order_quantity,
                        'product_uom': line.uom_id.id,
                        'price_unit': line.unit_price,
                        'date_planned': line.delivery_date or fields.Datetime.now(),
                        'quotation_line_id': line.id,
                    }))

                # Tạo đơn hàng mua
                PurchaseOrder.create(purchase_order_vals)

        
        
    def action_cancel_cancel(self):
        self.write({'state': 'cancel'})

        
        
    @api.model
    def write(self, values):
        res = super().write(values)
        for record in self:
            if record.state == 'pr_processing':
                for req in record.requests_ids.filtered(lambda x: x.state != 'cancel'):
                    req.write({'state':'ordering'})
            if record.state == 'ordered':
                for req in record.requests_ids.filtered(lambda x: x.state != 'cancel'):
                    req.write({'state':'ordered'})

    def action_quotations(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_purchase.act_smartbiz_purchase_requisition_2_smartbiz_purchase_quotation")
        context = eval(action['context'])
        context.update(dict(self._context,default_requisition_id=self.id))
        action['context'] = context
        action['domain'] = [('requisition_id', '=', self.id)]

        return action

    def action_purchase_orders(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_purchase.act_smartbiz_purchase_requisition_2_purchase_order")
        context = eval(action['context'])
        context.update(dict(self._context,default_purchase_requisition_id=self.id))
        action['context'] = context
        action['domain'] = [('purchase_requisition_id', '=', self.id)]

        return action

    def action_quotation_lines(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_purchase.act_smartbiz_purchase_requisition_2_smartbiz_purchase_quotation_line")
        context = eval(action['context'])
        context.update(dict(self._context,default_requisition_id=self.id))
        action['context'] = context
        action['domain'] = [('requisition_id', '=', self.id)]

        return action

    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_purchase.requisition') or 'New'


        res = super().create(values)


        return res

class smartbiz_purchase_RequisitionLine(models.Model):
    _name = "smartbiz_purchase.requisition_line"
    _description = "Requisition Line"
    name = fields.Char(string='Name')
    product_id = fields.Many2one('product.product', string='Product')
    description = fields.Text(string='Description')
    request_quantity = fields.Float(string='Request Quantity', compute='_compute_request_quantity', store=True)
    request_price = fields.Float(string='Request Price', compute='_compute_request_price', store=True)
    request_total = fields.Float(string='Request Total', compute='_compute_request_total', store=True)
    quantity = fields.Float(string='Quantity')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom_id', store=True)
    order_quantity = fields.Float(string='Order Quantity', compute='_compute_order_quantity', store=True)
    unit_price = fields.Float(string='Unit Price', compute='_compute_unit_price', store=True)
    total_price = fields.Float(string='Total Price', compute='_compute_total_price', store=True)
    delivery_date = fields.Datetime(string='Delivery Date')
    requisition_id = fields.Many2one('smartbiz_purchase.requisition', string='Requisition')
    request_lines_ids = fields.One2many('smartbiz_purchase.request_line', 'requisition_line_id')
    quotation_lines_ids = fields.One2many('smartbiz_purchase.quotation_line', 'requisition_line_id')


    @api.depends('request_lines_ids', 'request_lines_ids.quantity')
    def _compute_request_quantity(self):
        for record in self:
            quantity = sum(line.quantity for line in record.request_lines_ids.search([('requisition_line_id', '=', record.id)]))
            record.request_quantity = quantity

    @api.depends('request_lines_ids', 'request_lines_ids.quantity')
    def _compute_request_price(self):
        for record in self:
            for rl in record.request_lines_ids:
                record.request_price = rl.unit_price
                break            

    @api.depends('request_quantity', 'request_price')
    def _compute_request_total(self):
        for record in self:
            record.request_total = record.request_price * record.request_quantity

    @api.depends('product_id')
    def _compute_uom_id(self):
        for record in self:
            record.uom_id = record.product_id.uom_id.id

    @api.depends('quotation_lines_ids', 'quotation_lines_ids.order_quantity')
    def _compute_order_quantity(self):
        for record in self:
            quantity = sum(line.order_quantity for line in record.quotation_lines_ids.search([('requisition_line_id', '=', record.id)]))
            record.order_quantity = quantity

    @api.depends('quotation_lines_ids', 'quotation_lines_ids.order_quantity', 'quotation_lines_ids.unit_price')
    def _compute_unit_price(self):
        for record in self:
            lines = record.quotation_lines_ids.search([('requisition_line_id', '=', record.id)])
            total_quantity = sum(line.order_quantity for line in lines)
            total_value = sum(line.order_quantity * line.unit_price for line in lines)
            record.unit_price = total_value / total_quantity if total_quantity else 0 

    @api.depends('order_quantity', 'unit_price')
    def _compute_total_price(self):
        for record in self:
            record.total_price = record.unit_price * record.order_quantity

class smartbiz_purchase_RequisitionCategory(models.Model):
    _name = "smartbiz_purchase.requisition_category"
    _description = "Requisition Category"
    name = fields.Char(string='Name')
    description = fields.Text(string='Description')


class smartbiz_purchase_Quotation(models.Model):
    _name = "smartbiz_purchase.quotation"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Quotation"
    name = fields.Char(string='Name', copy=False, default = 'New')
    supplier_id = fields.Many2one('res.partner', string='Supplier')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    date = fields.Datetime(string='Date')
    delivery_date = fields.Datetime(string='Delivery Date')
    lines_ids = fields.One2many('smartbiz_purchase.quotation_line', 'quotation_id')
    requisition_id = fields.Many2one('smartbiz_purchase.requisition', string='Requisition')
    state = fields.Selection([('draft','Draft'),('processing','Processing'),('approved','Approved'),('ordering','Ordering'),('ordered','Ordered'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = False, index = False, default = 'draft')


    def action_draft_send_to_supplier(self):
        self.write({'state': 'processing'})

        
        
    def action_processing_approve(self):
        self.write({'state': 'approved'})

        
        
    def action_cancel_cancel(self):
        self.write({'state': 'cancel'})

        
        
    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_purchase.quotation') or 'New'


        res = super().create(values)


        return res

class smartbiz_purchase_QuotationLine(models.Model):
    _name = "smartbiz_purchase.quotation_line"
    _description = "Quotation Line"
    name = fields.Char(string='Name')
    product_id = fields.Many2one('product.product', string='Product')
    description = fields.Text(string='Description')
    quantity = fields.Float(string='Quantity')
    order_quantity = fields.Float(string='Order Quantity')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom_id', store=True)
    unit_price = fields.Float(string='Unit Price')
    total_price = fields.Float(string='Total Price', compute='_compute_total_price', store=True)
    delivery_date = fields.Datetime(string='Delivery Date')
    quotation_id = fields.Many2one('smartbiz_purchase.quotation', string='Quotation')
    requisition_id = fields.Many2one('smartbiz_purchase.requisition', string='Requisition')
    requisition_line_id = fields.Many2one('smartbiz_purchase.requisition_line', string='Requisition Line')


    @api.depends('product_id')
    def _compute_uom_id(self):
        for record in self:
            record.uom_id = record.product_id.uom_id.id

    @api.depends('unit_price', 'quantity')
    def _compute_total_price(self):
        for record in self:
            record.total_price = record.unit_price * record.quantity

class smartbiz_purchase_Budget(models.Model):
    _name = "smartbiz_purchase.budget"
    _description = "Budget"
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    period_id = fields.Many2one('smartbiz_purchase.budget_period', string='Period', required=True)
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit', required=True)
    budget_amount = fields.Float(string='Budget Amount', compute='_compute_budget_amount', store=True)
    used_amount = fields.Float(string='Used Amount', compute='_compute_used_amount', store=True)
    remain_amount = fields.Float(string='Remain Amount', compute='_compute_remain_amount', store=True)
    budget_line_ids = fields.One2many('smartbiz_purchase.budget_line', 'budget_id', readonly=True)


    @api.depends('period_id', 'organization_unit_id')
    def _compute_name(self):
        for record in self:
            record.name =  (record.organization_unit_id.name or '') + ' - ' + (record.period_id.name or '')

    @api.depends('budget_line_ids', 'budget_line_ids.state')
    def _compute_budget_amount(self):
        for record in self:
            budget_lines = record.budget_line_ids.filtered(lambda c: c.type =='in' and c.state == 'posted')
            record.budget_amount = sum(line.amount for line in budget_lines)

    @api.depends('budget_line_ids', 'budget_line_ids.state')
    def _compute_used_amount(self):
        for record in self:
            budget_lines = record.budget_line_ids.filtered(lambda c: c.type =='out' and c.state == 'posted')
            record.used_amount = sum(line.amount for line in budget_lines)

    @api.depends('budget_amount', 'used_amount')
    def _compute_remain_amount(self):
        for record in self:
            record.remain_amount = record.budget_amount - record.used_amount

class smartbiz_purchase_BudgetLine(models.Model):
    _name = "smartbiz_purchase.budget_line"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Budget Line"
    period_id = fields.Many2one('smartbiz_purchase.budget_period', string='Period', required=True)
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit', required=True)
    type = fields.Selection([('in','In'),('out','Out'),], string='Type')
    amount = fields.Float(string='Amount')
    budget_id = fields.Many2one('smartbiz_purchase.budget', string='Budget')
    budget_order_id = fields.Many2one('smartbiz_purchase.budget_order', string='Budget Order')
    state = fields.Selection([('draft','Draft'),('posted','Posted'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_post(self):
        self.write({'state': 'posted'})

        
        
    @api.model
    def create(self, values):
        res = super().create(values)
        for record in res:
            budget = self.env['smartbiz_purchase.budget'].search([
                    ['organization_unit_id','=',record.organization_unit_id.id],
                    ['period_id','=',record.period_id.id],
                ],limit=1)
            if not budget:
                budget = self.env['smartbiz_purchase.budget'].create({'organization_unit_id':record.organization_unit_id.id,'period_id':record.period_id.id})
            record.write({'budget_id':budget.id})

class smartbiz_purchase_BudgetOrder(models.Model):
    _name = "smartbiz_purchase.budget_order"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Budget Order"
    name = fields.Char(string='Order', default = 'New')
    type = fields.Selection([('in','In'),('out','Out'),('transfer','Transfer'),], string='Type')
    period_id = fields.Many2one('smartbiz_purchase.budget_period', string='Period', required=True)
    destination_period_id = fields.Many2one('smartbiz_purchase.budget_period', string='Destination Period')
    organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Organization Unit', required=True)
    destination_organization_unit_id = fields.Many2one('smartbiz.organization_unit', string='Destination Organization Unit')
    amount = fields.Float(string='Amount')
    remain_amount = fields.Float(string='Remain Amount', compute='_compute_remain_amount', store=False)
    budget_line_ids = fields.One2many('smartbiz_purchase.budget_line', 'budget_order_id', readonly=True)
    state = fields.Selection([('draft','Draft'),('processing','Processing'),('approved','Approved'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    @api.depends('period_id', 'organization_unit_id')
    def _compute_remain_amount(self):
        for record in self:  
            budget = self.env['smartbiz_purchase.budget'].search([
                    ['organization_unit_id','=',record.organization_unit_id.id],
                    ['period_id','=',record.period_id.id],
                ],limit=1)
            record.remain_amount = budget.remain_amount or 0

    def action_draft_confirm(self):
        self.write({'state': 'processing'})

        
        
    def action_processing_approve(self):
        for record in self:
            if record.amount - record.remain_amount > 0 and record.type != 'in':
                raise ValidationError(_("Ngân sách hiện tại không đủ để thực hiện. Vui lòng kiểm tra lại."))

            if record.type == 'transfer':      
                self.env['smartbiz_purchase.budget_line'].create(
                    {
                        'organization_unit_id':record.organization_unit_id.id,
                        'type':'out',
                        'period_id':record.period_id.id,
                        'budget_order_id':record.id,
                        'amount': record.amount,
                        'state':'posted'
                    }) 
                self.env['smartbiz_purchase.budget_line'].create(
                    {
                        'organization_unit_id':record.destination_organization_unit_id.id or record.organization_unit_id.id,
                        'type':'in',
                        'period_id':record.destination_period_id.id or record.period_id.id,
                        'budget_order_id':record.id,
                        'amount': record.amount,
                        'state':'posted'
                    }) 
            else:
                self.env['smartbiz_purchase.budget_line'].create(
                    {
                        'organization_unit_id':record.organization_unit_id.id,
                        'type':record.type,
                        'period_id':record.period_id.id,
                        'budget_order_id':record.id,
                        'amount': record.amount,
                        'state':'posted'
                    }) 
            record.write({'state':'approved'})

        
        
    def action_approved_cancel(self):
        for record in self:
            for l in record.budget_line_ids:
                l.write({'state':'cancel'})
            record.write({'state':'cancel'})

        
        
    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_purchase.budget_order') or 'New'


        res = super().create(values)


        return res

class smartbiz_purchase_BudgetPeriod(models.Model):
    _name = "smartbiz_purchase.budget_period"
    _description = "Budget Period"
    name = fields.Char(string='Period')
    active = fields.Boolean(string='Active')


