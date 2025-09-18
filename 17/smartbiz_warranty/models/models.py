from dateutil.relativedelta import relativedelta
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

class Repair_Order(models.Model):
    _inherit = ['repair.order']
    replacement_serial_id = fields.Many2one('stock.lot', string='Replacement Serial')
    repair_action_id = fields.Many2one('smartbiz_warranty.repair_action', string='Repair Action')
    repair_duration = fields.Float(string='Repair Duration', compute='_compute_repair_duration', store=True)
    repaired_quantity = fields.Float(string='Repaired Quantity')
    picking_id = fields.Many2one('stock.picking', string='Picking')
    done_date = fields.Datetime(string='Done Date')
    origin = fields.Char(string='Origin')


    @api.depends('done_date', 'schedule_date')
    def _compute_repair_duration(self):
        now = fields.Datetime.now
        for rec in self:
            start = rec.schedule_date or now()
            end   = rec.done_date if rec.state == 'done' and rec.done_date else now()
            rec.repair_duration = (end - start).total_seconds() / 86400.0

    def action_repair_end(self):
        res = super().action_repair_end()
        today = fields.Date.context_today(self)

        for order in self:
            lot_old = order.lot_id
            lot_new = order.replacement_serial_id

            # Chặn vòng lặp và tự thay thế chính mình
            if lot_new and lot_new == lot_old:
                raise models.ValidationError(_("Replacement serial cannot be identical to original serial."))

            # --- Serial gốc -------------------------------------------------
            if lot_old:
                vals_old = {
                    'last_repair_date': today,
                    'replacement_serial_id': lot_new.id if lot_new else False,
                }
                lot_old.write(vals_old)

            # --- Serial mới -------------------------------------------------
            if lot_new:
                vals_new = {
                    'replaced_serial_id': lot_old.id if lot_old else False,
                    'last_repair_date': today,
                }
                # Bảo lưu hạn bảo hành còn lại
                if lot_old and lot_old.warranty_expiration_date:
                    vals_new.update({
                        'warranty_activation_date': today,
                        'warranty_expiration_date': lot_old.warranty_expiration_date,
                    })
                lot_new.write(vals_new)

        return res

    def action_repair_end(self):
        res = super().action_repair_end()
        today = fields.Datetime.now()
        for order in self:
            if not order.done_date:                 # tránh ghi đè khi sửa lại
                order.done_date = today
        return res

class Stock_Lot(models.Model):
    _inherit = ['stock.lot']
    replaced_serial_id = fields.Many2one('stock.lot', string='Replaced Serial')
    replacement_serial_id = fields.Many2one('stock.lot', string='Replacement Serial')
    sell_out_date = fields.Date(string='Sell Out Date')
    warranty_activation_date = fields.Date(string='Warranty Activation Date')
    warranty_expiration_date = fields.Date(string='Warranty Expiration Date')
    last_repair_date = fields.Date(string='Last Repair Date')


    _sql_constraints = [
        ('no_self_replace',
         'CHECK (id IS NULL OR id <> replacement_serial_id)',
         'A serial cannot replace itself.'),
    ]

    @api.model
    def _cron_fill_sell_out_date(self, batch_size=500):
        """
        - Với mỗi serial chưa có sell_out_date:
          * tìm stock.move.line -> stock.move (done, outgoing) sớm nhất.
          * ghi sell_out_date, warranty_*.
        - Chạy theo batch để tránh timeout.
        """
        MoveLine = self.env['stock.move.line']
        lots = self.search([('sell_out_date', '=', False)], limit=batch_size)
        for lot in lots:
            mv = MoveLine.search([
                ('lot_id', '=', lot.id),
                ('move_id.state', '=', 'done'),
                ('move_id.picking_type_id.code', '=', 'outgoing'),
            ], order='date asc', limit=1)

            if not mv:
                continue  # chưa bán

            sell_date = fields.Date.to_date(mv.date)
            tmpl = lot.product_id.product_tmpl_id
            vals = {
                'sell_out_date': sell_date,
                'warranty_activation_date': sell_date,
            }
            if tmpl.warranty_duration:
                delta = relativedelta(**{tmpl.warranty_uom + 's': tmpl.warranty_duration})
                vals['warranty_expiration_date'] = sell_date + delta
            lot.write(vals)

        # Commit giữa chừng nếu bản ghi rất lớn
        if lots:
            self.env.cr.commit()

class Product_Template(models.Model):
    _inherit = ['product.template']
    warranty_duration = fields.Integer(string='Warranty Duration', default = 12)
    warranty_uom = fields.Selection([('day','Day'),('month','Month'),('year','Year'),], string='Warranty UoM', default = 'month')


class Stock_Picking(models.Model):
    _inherit = ['stock.picking', 'smartbiz.workflow_base']
    _name = 'stock.picking'
    repair_ids = fields.One2many('repair.order', 'picking_id')
    create_repair_order = fields.Boolean(string='Create Repair Order', compute='_compute_create_repair_order', store=True)


    @api.depends('picking_type_id')
    def _compute_create_repair_order(self):
        for record in self:
            record.create_repair_order = record.picking_type_id.create_repair_order

    def action_create_repair_order(self):
        RepairOrder  = self.env['repair.order']
        PickingType  = self.env['stock.picking.type']
        new_ro_ids   = []

        for picking in self:
            # chỉ xử lý phiếu nhập + được bật “Create Repair Order”
            if picking.picking_type_id.code != 'incoming' \
               or not picking.picking_type_id.create_repair_order:
                continue

            # ----- tìm Picking Type “repair_operation” cùng kho -----
            repair_pt = PickingType.search([
                ('warehouse_id', '=', picking.picking_type_id.warehouse_id.id),
                ('code', '=', 'repair_operation')
            ], limit=1)
            if not repair_pt:
                # fallback: lấy bất kỳ repair_operation nào
                repair_pt = PickingType.search([('code', '=', 'repair_operation')], limit=1)
            if not repair_pt:
                raise UserError(_("Không tìm thấy Picking Type với mã 'repair_operation'"))

            # ----- gom move line -----
            serial_mls = []
            prod_qty   = {}   # {product: total_qty}

            for ml in picking.move_line_ids:
                if ml.quantity <= 0:
                    continue
                prod = ml.product_id
                if prod.tracking == 'serial':
                    serial_mls.append(ml)
                else:
                    prod_qty[prod] = prod_qty.get(prod, 0) + ml.quantity

            # ----- tạo RO cho serial -----
            for ml in serial_mls:
                lot = ml.lot_id
                if not lot:
                    continue
                if RepairOrder.search_count([
                    ('picking_id', '=', picking.id),
                    ('lot_id', '=', lot.id),
                ]):
                    continue

                vals = {
                    'product_id'      : ml.product_id.id,
                    'product_qty'     : 1.0,
                    'lot_id'          : lot.id,
                    'picking_id'      : picking.id,
                    'partner_id'      : picking.partner_id.id,
                    'origin'          : picking.name,
                    'picking_type_id' : repair_pt.id,
                }
                new_ro_ids.append(RepairOrder.create(vals).id)

            # ----- tạo RO cho lot/none -----
            for prod, qty in prod_qty.items():
                if RepairOrder.search_count([
                    ('picking_id', '=', picking.id),
                    ('product_id', '=', prod.id),
                    ('lot_id', '=', False),
                ]):
                    continue

                vals = {
                    'product_id'      : prod.id,
                    'product_qty'     : qty,
                    'lot_id'          : False,
                    'picking_id'      : picking.id,
                    'partner_id'      : picking.partner_id.id,
                    'origin'          : picking.name,
                    'picking_type_id' : repair_pt.id,
                }
                new_ro_ids.append(RepairOrder.create(vals).id)

        
        
class Stock_PickingType(models.Model):
    _inherit = ['stock.picking.type']
    create_repair_order = fields.Boolean(string='Create Repair Order')


class smartbiz_warranty_WarrantyReport(models.Model):
    _name = "smartbiz_warranty.warranty_report"
    _rec_name = "serial_name"
    _auto=False
    _description = "Warranty Report"
    serial_id = fields.Many2one('stock.lot', string='Serial')
    serial_name = fields.Char(string='Serial Name')
    product_id = fields.Many2one('product.product', string='Product')
    picking_id = fields.Many2one('stock.picking', string='Picking')
    partner_id = fields.Many2one('res.partner', string='Partner')
    sell_out_date = fields.Date(string='Sell Out Date')
    warranty_expiration_date = fields.Date(string='Warranty Expiration Date')
    days_left = fields.Integer(string='Days Left')
    warranty_status = fields.Selection([('in_warranty','In Warranty'),('expired','Expired'),], string='Warranty Status')
    replaced_serial_id = fields.Many2one('stock.lot', string='Replaced Serial')
    replacement_serial_id = fields.Many2one('stock.lot', string='Replacement Serial')
    last_repair_date = fields.Date(string='Last Repair Date')


    # ---------- SQL View ----------
    def _query(self):
        return """
            WITH first_picking AS (
                SELECT
                    l.id                AS lot_id,
                    p.id                AS picking_id,
                    p.partner_id        AS partner_id,
                    p.date_done         AS date_done
                FROM stock_lot l
                JOIN stock_move_line sml      ON sml.lot_id = l.id
                JOIN stock_move sm            ON sm.id = sml.move_id
                JOIN stock_picking p          ON p.id = sm.picking_id
                JOIN stock_picking_type spt   ON spt.id = p.picking_type_id
                WHERE sm.state = 'done'
                  AND p.state  = 'done'
                  AND spt.code = 'outgoing'
                -- lấy phiếu giao hàng sớm nhất
                  AND p.date_done = (
                        SELECT MIN(p2.date_done)
                        FROM stock_move_line sml2
                        JOIN stock_move sm2   ON sm2.id = sml2.move_id
                        JOIN stock_picking p2 ON p2.id = sm2.picking_id
                        JOIN stock_picking_type spt2 ON spt2.id = p2.picking_type_id
                        WHERE sml2.lot_id = l.id
                          AND sm2.state = 'done'
                          AND p2.state = 'done'
                          AND spt2.code = 'outgoing'
                    )
            )
            SELECT
                l.id                          AS id,
                l.id                          AS serial_id,
                l.name                        AS serial_name,
                l.product_id                  AS product_id,
                fp.picking_id                 AS picking_id,
                fp.partner_id                 AS partner_id,
                l.sell_out_date               AS sell_out_date,
                l.warranty_expiration_date    AS warranty_expiration_date,
                l.replaced_serial_id          AS replaced_serial_id,
                l.replacement_serial_id       AS replacement_serial_id,
                l.last_repair_date            AS last_repair_date,
                -- days_left & status
                CASE
                    WHEN l.warranty_expiration_date IS NULL
                         THEN NULL
                    ELSE (l.warranty_expiration_date - CURRENT_DATE)
                END                           AS days_left,
                CASE
                    WHEN l.warranty_expiration_date IS NULL
                         THEN NULL
                    WHEN l.warranty_expiration_date >= CURRENT_DATE
                         THEN 'in_warranty'
                    ELSE 'expired'
                END                           AS warranty_status
            FROM stock_lot l
            LEFT JOIN first_picking fp ON fp.lot_id = l.id
        """

    @tools.ormcache()
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""CREATE OR REPLACE VIEW {self._table} AS ({self._query()})""")

class smartbiz_warranty_RepairAction(models.Model):
    _name = "smartbiz_warranty.repair_action"
    _description = "Repair Action"
    name = fields.Char(string='Name', translate="True")


