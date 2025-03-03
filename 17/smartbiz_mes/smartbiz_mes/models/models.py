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

class mrp_Production(models.Model):
    _inherit = ['mrp.production']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    name = fields.Char(store='True', readonly=False)
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')


    def _get_fields(self,model):
        if model == 'mrp.production':
            return ['name','state','product_id','product_uom_id','product_uom_qty','qty_produced','qty_producing','date_start','date_deadline','date_finished','company_id','user_id']
        if model == 'stock.move':
            return ['state','date','date_deadline','product_id','product_uom','product_uom_qty','quantity','product_qty','location_id','location_dest_id']
        if model == 'stock.move.line':
            return ['state','move_id','date','product_id','product_uom_id','quantity','location_id','location_dest_id','package_id','result_package_id','lot_id']
        if model == 'product.product':
            return ['barcode', 'default_code', 'tracking', 'display_name', 'uom_id']
        if model == 'stock.location':
            return ['display_name', 'barcode', 'parent_path']
        if model == 'stock.package.type':
            return ['barcode', 'name']
        if model == 'stock.quant.package':
            return ['name','location_id']
        if model == 'stock.lot':
            return ['name', 'ref', 'product_id','expiration_date','create_date','product_qty']
        if model == 'uom.uom':
            return ['name','category_id','factor','rounding',]
        if model == 'stock.quant':
            return ['product_id','location_id','inventory_date','inventory_quantity','inventory_quantity_set','quantity','product_uom_id','lot_id','package_id','owner_id','inventory_diff_quantity','user_id',]
        return []
 
    
    def get_orders(self,domain):
        orders = self.search(domain)
        products = orders.product_id
        uoms = orders.product_uom_id
        users = self.env['res.users'].search([]).read(['name','barcode'], load=False),
        data = {
            'orders':orders.read(orders._get_fields('mrp.production'), load=False),
            'order_products': products.read(orders._get_fields('product.product'), load=False),
            'order_uoms':uoms.read(orders._get_fields('uom.uom'), load=False),
            'users':users[0]
        }
        return data
        
    def validate(self,production_id):
        self = self.browse(production_id)
        # res = self.pre_button_mark_done()
        # if res is not True:
        #     return res

        self.move_finished_ids._action_done()

        if self.env.context.get('mo_ids_to_backorder'):
            productions_to_backorder = self.browse(self.env.context['mo_ids_to_backorder'])
            productions_not_to_backorder = self - productions_to_backorder
        else:
            productions_not_to_backorder = self
            productions_to_backorder = self.env['mrp.production']

        self.workorder_ids.button_finish()

        backorders = productions_to_backorder and productions_to_backorder._split_productions()
        backorders = backorders - productions_to_backorder

        productions_not_to_backorder._post_inventory(cancel_backorder=True)
        productions_to_backorder._post_inventory(cancel_backorder=True)

        # if completed products make other confirmed/partially_available moves available, assign them
        done_move_finished_ids = (productions_to_backorder.move_finished_ids | productions_not_to_backorder.move_finished_ids).filtered(lambda m: m.state == 'done')
        done_move_finished_ids._trigger_assign()

        # Moves without quantity done are not posted => set them as done instead of canceling. In
        # case the user edits the MO later on and sets some consumed quantity on those, we do not
        # want the move lines to be canceled.
        (productions_not_to_backorder.move_raw_ids | productions_not_to_backorder.move_finished_ids).filtered(lambda x: x.state not in ('done', 'cancel')).write({
            'state': 'done',
            'product_uom_qty': 0.0,
        })
        for production in self:
            production.write({
                'date_finished': fields.Datetime.now(),
                'priority': '0',
                'is_locked': True,
                'state': 'done',
            })
        return self.get_data(production_id)

    def save_order(self,production_id,data):
        quantity = float(data['quantity'])
        if data['id']:
            self.env['stock.move.line'].browse(data['id']).write({'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'state':'assigned','picked':True})
        else:
            self.env['stock.move.line'].create({'move_id':data['move_id'],'product_id':data['product_id'],'product_uom_id':data['product_uom_id'],'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'package_id':data['package_id'],'result_package_id':data['result_package_id'],'state':'assigned','picked':True})
        mo = self.browse(production_id)
        if mo:
            finisheds = mo.move_finished_ids
            move_lines = finisheds[0].move_line_ids
            qty_produced = 0
            qty_producing = sum(move_lines.mapped('quantity')) if move_lines else 0
            mo.write({'qty_producing':qty_producing,'qty_produced':qty_produced})
  
        return self.get_data(production_id)
    def cancel_order(self,production_id):
        self.env['mrp.production'].browse(production_id).action_cancel()
        
    def create_lot(self,production_id,product_id,company_id,lot_name = False):
        if lot_name:
            lot_id = self.env['stock.lot'].search([['product_id','=',product_id],['name','=',lot_name],['company_id','=',company_id]],limit=1)
            if not lot_id:
                lot_id = self.env['stock.lot'].create({'product_id':product_id,'name':lot_name,'company_id':company_id})
        else:
            lot_id = self.env['stock.lot'].create({'product_id':product_id,'company_id':company_id})
        data = self.get_data(production_id)
        data['lot_id'] = lot_id.id
        data['lot_name'] = lot_id.name
        return data
        
    def pack_move_line(self,production_id,data):     
        quantity = float(data['quantity'])
        if data['id']:
            ml =  self.env['stock.move.line'].browse(data['id'])
            if ml.result_package_id:
                ml.write({'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'picked':True})
            else:
                package = self.env['stock.quant.package'].create({})
                ml.write({'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'result_package_id':package.id,'picked':True})
        else:
            package = self.env['stock.quant.package'].create({})
            self.env['stock.move.line'].create({'move_id':data['move_id'],'product_id':data['product_id'],'product_uom_id':data['product_uom_id'],'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'result_package_id':package.id,'picked':True})
        mo =   self.search([['id','=',production_id]],limit=1)
        if mo:
            finisheds = mo.move_finished_ids
            move_lines = finisheds[0].move_line_ids
            qty_producing = sum(move_lines.mapped('quantity')) if move_lines else 0
            mo.write({'qty_producing':qty_producing})
            
        return self.get_data(production_id)
        
    def print_move_line(self,production_id,data,printer_name,label_name):
        quantity = float(data['quantity'])
        if data['id']:
            record = self.env['stock.move.line'].browse(data['id'])
        else:
            record = self.env['stock.move.line'].create({'move_id':data['move_id'],'product_id':data['product_id'],'product_uom_id':data['product_uom_id'],'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'picked':True})

        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like',printer_name)],limit=1)
        
        label = self.env['printing.label.zpl2'].search([('name','=',label_name)],limit=1)
        #return {'printer':printer,'label':label}
        if label and printer:
            label.print_label(printer, record)
        return self.get_data(production_id)
        
    def delete_move_line(self,production_id,move_line_id):
        ml = self.env['stock.move.line'].browse(move_line_id)
        move = ml.move_id
        move.write({'move_line_ids':[(2,move_line_id)]})
        if not move.move_line_ids:
            move.picked = False
        return self.get_data(production_id)
    
    def get_data(self,production_id):
        order = self.browse(production_id)
        materials = order.move_raw_ids
        byproducts = order.move_byproduct_ids
        finisheds = order.move_finished_ids
        
        products = materials.product_id|byproducts.product_id|finisheds.product_id
       
        uoms = materials.product_uom | byproducts.product_uom | finisheds.product_uom
      
        move_lines = materials.move_line_ids | byproducts.move_line_ids|finisheds.move_line_ids
        moves = materials | byproducts | finisheds
        mls = []
        mvs = []
        for ml in move_lines:
            mls.append({
                'id': ml.id,
                'move_id': ml.move_id.id,
                'production_id': production_id,
                'state': ml.state,
                'date': ml.date,
                'product_id': ml.product_id.id,
                'product_name': ml.product_id.display_name or '',
                'product_barcode': ml.product_id.barcode or '',
                'product_tracking': ml.product_id.tracking,
                'product_uom': ml.product_id.uom_id.name or '',
                'product_uom_id': ml.product_id.uom_id.id,
                'quantity': ml.quantity,
                'qty_done': ml.quantity,
                'lot_id': ml.lot_id.id,
                'lot_name': ml.lot_name or ml.lot_id.name,
                'location_id': ml.location_id.id,
                'location_name': ml.location_id.display_name or '',
                'location_barcode': ml.location_id.barcode or '',
                'location_dest_id': ml.location_dest_id.id,
                'location_dest_name': ml.location_dest_id.display_name or '',
                'location_dest_barcode': ml.location_dest_id.barcode or '',
                'result_package_id': ml.result_package_id.id,
                'result_package_name': ml.result_package_id.name or '',
                'package_id': ml.package_id.id,
                'package_name': ml.package_id.name or '',
                'picked': ml.picked or False,
            })
        for mv in moves:
            mvs.append({
                'id': mv.id,
                'production_id': production_id,
                'state': mv.state,
                'date': mv.date,
                'product_id': mv.product_id.id,
                'product_name': mv.product_id.display_name or '',
                'product_barcode': mv.product_id.barcode or '',
                'product_tracking': mv.product_id.tracking,
                'product_uom': mv.product_id.uom_id.name or '',
                'product_uom_id': mv.product_id.uom_id.id,
                'product_uom_qty': mv.product_uom_qty,
                'quantity': mv.quantity,
                'product_qty': mv.product_qty,
                'location_id': mv.location_id.id,
                'location_name': mv.location_id.display_name or '',
                'location_barcode': mv.location_id.barcode or '',
                'location_dest_id': mv.location_dest_id.id,
                'location_dest_name': mv.location_dest_id.display_name or '',
                'location_dest_barcode': mv.location_dest_id.barcode or '',
                'picked': mv.picked or False,

            })
        
        packages = move_lines.package_id | move_lines.result_package_id

        pre_production_packages = self.env['stock.quant'].search([('location_id','=',order.location_src_id.id),
                                                                    ('product_id','in',products.ids),
                                                                    ('package_id', '!=', False)
                                                                  ])
        lots = move_lines.lot_id|self.env['stock.lot'].search( [('company_id', '=', order.company_id.id), ('product_id', 'in', products.ids)])
        locations = move_lines.location_id | move_lines.location_dest_id | materials.location_id | finisheds.location_id| materials.location_dest_id | finisheds.location_dest_id
        
        
        finished_move_lines = finisheds.move_line_ids
        qty_producing = sum(finished_move_lines.mapped('quantity')) if finished_move_lines else 0
        
        data = {
            
            'materials': materials.read(order._get_fields('stock.move')),
            'byproducts': byproducts.read(order._get_fields('stock.move')),
            'finisheds': finisheds.read(order._get_fields('stock.move')),
            'moves':mvs,
            'move_lines': move_lines.read(order._get_fields('stock.move.line')),
            'moveLines':mls,
            'packages': packages.read(order._get_fields('stock.quant.package')),
            'lots': lots.read(order._get_fields('stock.lot')),
            'locations': locations.read(order._get_fields('stock.location')),
            'products': products.read(order._get_fields('product.product')),
            'uoms':uoms.read(order._get_fields('uom.uom')),
            'company_id': order.company_id.id,
            'qty_producing':qty_producing, 
            'order':order.read(order._get_fields('mrp.production')),
            'pre_production_packages':pre_production_packages.read(order._get_fields('stock.quant'))
        }
        return data
        
    def get_quants(self,package):
        package = self.env['stock.quant.package'].search([('name','like',package)],limit=1)
        quants = []
        for quant in package.quant_ids:
            quants.append({
                'id':quant.id,
                'package':quant.package_id.name,
                'package_id':quant.package_id.id,
                'product_id':quant.product_id.id,
                'product_name':quant.product_id.name,
                'quantity':quant.quantity,
                'lot_id':quant.lot_id.id,
                'lot_name':quant.lot_id.name,
                'product_uom':quant.product_id.uom_id.name,
                'product_uom_id':quant.product_id.uom_id.id,
                'location_id':quant.location_id.id,
                'location_name':quant.location_id.name
                
            })
        return quants
        
    def create_production_return(self, production_id, quants, label_name=''):
        transfer_groups = {}
        # Lấy các materials từ production order
        production_order = self.env['mrp.production'].browse(production_id)
        materials = production_order.move_raw_ids

        # 1. Tạo các `picking` cho các phần sản phẩm còn thừa (quantity_remain > 0)
        for material in materials:
            for quant in quants:
                # Tạo picking cho sản phẩm còn thừa (phần quantity_remain > 0)
                if quant['quantity_remain'] > 0 and quant['product_id'] == material.product_id.id:
                    location = self.env['stock.location'].browse(quant['location_id'])
                    
                    # Lấy kiểu điều chuyển nội bộ dựa trên location_id
                    internal_picking_type = self.env['stock.picking.type'].search([
                        ('code', '=', 'internal'),
                        ('warehouse_id', '=', location.warehouse_id.id)
                    ], limit=1)

                    if not internal_picking_type:
                        continue

                    # Nhóm các bản ghi theo kiểu điều chuyển
                    picking_type_id = internal_picking_type.id
                    if picking_type_id not in transfer_groups:
                        transfer_groups[picking_type_id] = {
                            'internal_picking_type': internal_picking_type,
                            'quants': []
                        }

                    transfer_groups[picking_type_id]['quants'].append(quant)
        
        # 2. Tạo move_line để tiêu thụ materials của production_order
        for material in materials:
            for quant in quants:
                if quant['product_id'] == material.product_id.id:
                    quantity_to_consume = quant['quantity'] - quant['quantity_remain']
                    if quantity_to_consume > 0:
                        # Tạo move line để tiêu thụ số lượng
                        move_line_vals = {
                            'move_id': material.id,
                            'product_id': material.product_id.id,
                            'product_uom_id': material.product_uom.id,
                            'quantity': quantity_to_consume,
                            'location_id': quant['location_id'],
                            'location_dest_id': material.location_dest_id.id,
                            'lot_id': quant['lot_id'],
                            'package_id': quant['package_id'],
                            'state':'assigned',
                            'picked':True
                        }
                        self.env['stock.move.line'].create(move_line_vals)
                    
        # Tạo lệnh điều chuyển cho từng nhóm
        for picking_type_id, group in transfer_groups.items():
            internal_picking_type = group['internal_picking_type']
            group_quants = group['quants']

            # Tạo một picking mới cho từng kiểu điều chuyển
            picking_vals = {
                'location_id': group_quants[0]['location_id'],
                'location_dest_id': internal_picking_type.default_location_dest_id.id,
                'picking_type_id': internal_picking_type.id,
            }
            picking = self.env['stock.picking'].create(picking_vals)

            for quant in group_quants:
                # Tạo package mới cho mỗi dòng
                new_package = self.env['stock.quant.package'].create({})

                # Tạo move line trực tiếp
                move_line_vals = {
                    'product_id': quant['product_id'],
                    'product_uom_id': quant['product_uom_id'],
                    'quantity': quant['quantity_remain'],
                    'location_id': quant['location_id'],
                    'location_dest_id': internal_picking_type.default_location_dest_id.id,
                    'package_id': quant['package_id'],
                    'result_package_id': new_package.id,
                    'picking_id': picking.id,
                    'lot_id': quant['lot_id']
                }
                line = self.env['stock.move.line'].create(move_line_vals)

                # Kiểm tra và in nhãn nếu có
                if label_name != '':
                    printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name', 'like', 'ZTC-ZD230-203dpi-ZPL')], limit=1)
                    label = self.env['printing.label.zpl2'].search([('name', '=', label_name)], limit=1)
                    if label and printer:
                        label.print_label(printer, line)

            # Xác nhận picking để thực hiện chuyển kho
            picking.action_confirm()
            picking.action_assign()
            picking.button_validate()
        return self.get_data(production_id)

    @api.onchange('production_line_id')
    def _onchange_production_line_id(self):
        for record in self:
            if record.production_line_id:
                record.picking_type_id = record.production_line_id.picking_type_id

class mrp_Workcenter(models.Model):
    _inherit = ['mrp.workcenter']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')


class mrp_Workorder(models.Model):
    _inherit = ['mrp.workorder']
    product_quality_ids = fields.One2many('smartbiz_mes.production_activity', 'work_order_id')


    def get_orders(self,domain):
        orders = self.search(domain)
        users = self.env['res.users'].search([]).read(['name','barcode'], load=False)
        order_data = []
        for order in orders:
            order_data.append({
                'id':order.id,
                'name':order.name,
                'production_id':order.production_id.id,
                'production_name':order.production_id.name,
                'product_id':order.product_id.id,
                'product_name':order.product_id.name,
                'quantity':order.qty_production,
                'state':order.state
            })
        data = {
            'orders':order_data,
            'users':users
        }
        return data
    
    def get_data(self,workorder_id):
        order = self.browse(workorder_id)
        components = []
        for comp in order.production_id.bom_id.components_ids:
            if order.operation_id.id in comp.operations_ids.ids:
                if comp.type == 'main_product':
                    product_id = order.production_id.product_id.id
                    product_name = order.production_id.product_id.display_name
                elif comp.type == 'product':
                    product_id = comp.product_id.product_id.id
                    product_name = comp.product_id.product_id.display_name
                elif comp.type == 'material':
                    product_id = comp.material_id.product_id.id
                    product_name = comp.material_id.product_id.display_name
                else:
                    product_id = False
                    product_name = ''
                
                production_activities = self.env['smartbiz_mes.production_activity'].search([('work_order_id','=',workorder_id),('component_id','=',comp.id)])
                activities = []
                
                ok_quantity = 0
                ng_quantity = 0
                producing_ok_quantity = 0
                producing_ng_quantity = 0
                batch_quantity = 20                
                quantity = order.production_id.product_qty / order.production_id.bom_id.product_qty * comp.quantity              
                
                for pa in production_activities:
                    
                    activities.append({
                        'id':pa.id,
                        'name':pa.name,
                        'quantity':pa.quantity,
                        'quality':pa.quality,
                        'lot_id':pa.lot_id.id,
                        'package':pa.package_id.name,
                        'package_id':pa.package_id.id,
                        'lot_name':pa.lot_id.name,
                        'status':pa.status,
                        'start':pa.start,
                        'finish':pa.finish
                        
                    })
                    if pa.start and pa.finish:
                        if pa.quality > 0.9:
                            ok_quantity += pa.quantity
                        else:
                            ng_quantity += pa.quantity
                    elif pa.start and not pa.finish:
                        if pa.quality > 0.9:
                            producing_ok_quantity += pa.quantity
                        else:
                            producing_ng_quantity += pa.quantity
                        
                lot_id =  order.production_id.lot_producing_id.id       
                lot_name =  order.production_id.lot_producing_id.name
                producing_quantity = producing_ok_quantity + producing_ng_quantity
                produced_quantity = ok_quantity + ng_quantity
                remain_quantity = quantity - (producing_quantity + produced_quantity)
                if remain_quantity < 0:
                    remain_quantity = 0
   
                components.append({
                    'id':comp.id,
                    'work_order_id':order.id,
                    'name':comp.name,
                    'type':comp.type,
                    'product_id':product_id,
                    'product_name':product_name,
                    'quantity':quantity,
                    'batch_quantity':batch_quantity,
                    'ok_quantity':ok_quantity,
                    'ng_quantity':ng_quantity,
                    'producing_quantity':producing_quantity,
                    'remain_quantity':remain_quantity,
                    'producing_ok_quantity':producing_ok_quantity,
                    'producing_ng_quantity':producing_ng_quantity,
                    'lot_id':lot_id,
                    'lot_name':lot_name,
                    'produced_quantity':produced_quantity,
                    'activities':activities
                    
                })
        workOrder = {
            'id':order.id,
            'name':order.name,
            'production_id':order.production_id.id,
            'production_name':order.production_id.name,
            'product_id':order.product_id.id,
            'product_name':order.product_id.name,
            'product_uom':order.product_uom_id.name, 
            'qty_production':order.qty_production,
            'state':order.state,
            'is_user_working':order.is_user_working,
            'duration_expected':order.duration_expected,
            'duration':order.duration,
            'duration_unit':order.duration_unit,
            'qty_remaining':order.qty_remaining,
            'qty_produced':order.qty_produced
            
        }
        data = {
            'components':components,
            'workOrder':workOrder
        }
        return data
    
    def delete_activity(self,workorder_id,production_activity):        
        activity = self.env['smartbiz_mes.production_activity'].browse(production_activity)
        package = activity.package_id
        if package:
            package.write({'current_workorder_id':False,'current_step':'','current_component_id':False,'last_qty':0})        
        activity.unlink()
        
        return self.get_data(workorder_id)
    
    def update_activity(self,workorder_id,data):
        activity = self.env['smartbiz_mes.production_activity'].browse(data['id'])
        package = activity.package_id
        if package:
            package.write({'last_qty':data['quantity']})  
        activity.write(data)
        return self.get_data(workorder_id)
    
    def update_component(self,type,component):
        processing_ok = self.env['smartbiz_mes.production_activity'].search([('work_order_id','=',component['work_order_id']),
                                                                            ('component_id','=',component['id']),
                                                                            ('start','!=',False),
                                                                            ('finish','=',False),
                                                                            ('quality','>=',0.9),
                                                                            ],limit=1)
        processing_ng = self.env['smartbiz_mes.production_activity'].search([('work_order_id','=',component['work_order_id']),
                                                                            ('component_id','=',component['id']),
                                                                            ('start','!=',False),
                                                                            ('finish','=',False),
                                                                            ('quality','<',0.9),
                                                                            ],limit=1)
        remain_quantity = component['remain_quantity']
        batch_quantity = component['batch_quantity']
        work_order_id = component['work_order_id']
        component_id = component['id']    
        now = fields.Datetime.now()
        producing_ok_quantity = component['producing_ok_quantity']
        producing_ng_quantity = component['producing_ng_quantity']

        if type == 'ok_action':
            if processing_ok:
                processing_ok.write({'quantity':producing_ok_quantity,'finish':now})
            else:
                processing_ok.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ok_quantity,'start':now,'finish':now,'quality':1})
        if type == 'ng_action':
            if processing_ng:
                processing_ng.write({'quantity':producing_ng_quantity,'finish':now})
            else:
                processing_ng.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ng_quantity,'start':now,'finish':now,'quality':0.8})

        data =  self.get_data(work_order_id)
        
        if type in ['start','ok_action','ng_action']:
            workorder_remain = 0
            workorder_producing = 0
            for comp in data['components']:
                workorder_remain += comp['remain_quantity']
                workorder_producing += comp['producing_quantity']
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(work_order_id) 
            else:
                self.start_workorder(work_order_id)
        return data
        
    def handle_package_scan(self, workorder_id, component_id, qr_code,
                            button_type=False, force=False, quantity=None):
        """
        - Nếu qr_code rỗng + button_type='ok_action' => Tìm OK đang mở => finish với quantity 
          hoặc tạo activity mới => finish ngay.
        - Nếu qr_code rỗng + button_type='ng_action' => Tương tự cho NG.
        - Nếu chỉ qr_code="" (không button_type) => Tạo package + activity OK (bắt đầu).
        - Nếu qr_code.startswith("OK") => Quét logic toggle OK (bắt đầu / kết thúc).
        - Nếu qr_code.startswith("NG") => Quét logic NG (cộng dồn).
        - Mỗi nhánh xong => check finish_workorder.
        """

        if not workorder_id or not component_id:
            raise UserError(_("workorder_id và component_id là bắt buộc."))

        workorder = self.env['mrp.workorder'].browse(workorder_id)
        if not workorder:
            raise UserError(_("WorkOrder ID=%s không tồn tại!") % workorder_id)

        bom_component = self.env['smartbiz_mes.bom_components'].browse(component_id)
        if not bom_component:
            raise UserError(_("Component ID=%s không tồn tại!") % component_id)

        # final_quantity: nếu người dùng không truyền => lấy bom_component.package_quantity
        final_quantity = quantity if quantity is not None else (bom_component.package_quantity or 1.0)

        Package = self.env['smartbiz_mes.package']
        Activity = self.env['smartbiz_mes.production_activity']
        now = fields.Datetime.now()

        def lock_package(pkg, wo_id, comp_id):
            """Khóa package vào 1 workorder & component duy nhất."""
            if pkg.current_workorder_id and pkg.current_workorder_id.id != wo_id:
                raise UserError(_(
                    "Package '%s' đang được xử lý ở WorkOrder '%s'. "
                    "Không thể thao tác ở WorkOrder '%s'."
                ) % (pkg.name, pkg.current_workorder_id.name, workorder.name))
            if pkg.current_component_id and pkg.current_component_id.id != comp_id:
                raise UserError(_(
                    "Package '%s' đã được gắn với Component '%s'. "
                    "Không thể thao tác ở Component '%s'."
                ) % (pkg.name, pkg.current_component_id.name, bom_component.name))
            pkg.write({'current_workorder_id': wo_id, 'current_component_id': comp_id})

        #-----------------------------------------------
        # TH 0: qr_code rỗng + button_type => Nút bấm OK/NG action
        #-----------------------------------------------
        if not qr_code and button_type:
            # ========== OK ACTION ==========
            if button_type == 'ok_action':
                # Tìm activity OK đang mở
                act_ok_open = Activity.search([
                    ('work_order_id','=',workorder_id),
                    ('component_id','=',component_id),
                    ('quality','>=',0.9),
                    ('finish','=',False),
                ], limit=1)

                if act_ok_open:
                    # finish + cập nhật quantity
                    old_qty = act_ok_open.quantity
                    act_ok_open.write({
                        'finish': now,
                        'quantity': final_quantity,   # Ghi nhận quantity do người dùng truyền
                    })
                else:
                    # Không thấy => tạo package + activity => finish ngay
                    new_pkg = Package.create({
                        'name': 'New-OK',
                        'current_step': workorder.operation_id.name if workorder.operation_id else '',
                        'current_component_id': bom_component.id,
                        'last_qty': final_quantity,
                        'current_workorder_id': workorder.id,
                    })
                    new_act_ok = Activity.create({
                        'work_order_id': workorder.id,
                        'component_id': bom_component.id,
                        'package_id': new_pkg.id,
                        'start': now,
                        'finish': now,
                        'quantity': final_quantity,  # quantity do người dùng truyền
                        'quality': 1, 
                    })

                data = self.get_data(workorder_id)
                # Kiểm tra finish workorder
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder_id)
                else:
                    self.start_workorder(workorder_id)
                return data

            # ========== NG ACTION ==========
            if button_type == 'ng_action':
                # Tìm activity NG (một activity duy nhất)
                act_ng = Activity.search([
                    ('work_order_id','=',workorder_id),
                    ('component_id','=',component_id),
                    ('quality','<',0.9),
                ], limit=1)

                if act_ng and not act_ng.finish:
                    # Cộng quantity, finish
                    old_qty = act_ng.quantity
                    new_qty = old_qty + final_quantity
                    act_ng.write({
                        'finish': now,
                        'quantity': new_qty
                    })
                else:
                    # Tạo package + activity NG => finish ngay
                    new_pkg = Package.create({
                        'name': 'New-NG',
                        'current_step': workorder.operation_id.name if workorder.operation_id else '',
                        'current_component_id': bom_component.id,
                        'last_qty': final_quantity,
                        'current_workorder_id': workorder.id,
                    })
                    Activity.create({
                        'work_order_id': workorder.id,
                        'component_id': bom_component.id,
                        'package_id': new_pkg.id,
                        'start': now,
                        'finish': now,
                        'quantity': final_quantity,
                        'quality': 0.8,
                    })

                # Trừ OK
                act_ok_open = Activity.search([
                    ('work_order_id','=',workorder_id),
                    ('component_id','=',component_id),
                    ('quality','>=',0.9),
                    ('finish','=',False),
                ], limit=1)
                if act_ok_open:
                    if act_ok_open.quantity < final_quantity and not force:
                        raise UserError(_(
                            "OK còn %.2f, không đủ trừ %.2f => force=True."
                        ) % (act_ok_open.quantity, final_quantity))
                    act_ok_open.write({'quantity': act_ok_open.quantity - final_quantity})

                data = self.get_data(workorder_id)
                # Kiểm tra finish workorder
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder_id)
                else:
                    self.start_workorder(workorder_id)
                return data

        #-----------------------------------------------
        # TH 1: qr_code = "" => Tạo package & activity OK (bắt đầu)
        # (KHÔNG có button_type)
        #-----------------------------------------------
        if not qr_code:
            new_package = Package.create({
                'name': 'New',
                'current_step': workorder.operation_id.name if workorder.operation_id else '',
                'current_component_id': bom_component.id,
                'last_qty': final_quantity,
                'current_workorder_id': workorder.id, 
            })
            Activity.create({
                'work_order_id': workorder.id,
                'component_id': bom_component.id,
                'package_id': new_package.id,
                'start': now,
                'quantity': final_quantity,
                'quality': 1,
            })
            data = self.get_data(workorder_id)

            workorder_remain = sum(c['remain_quantity'] for c in data['components'])
            workorder_producing = sum(c['producing_quantity'] for c in data['components'])
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(workorder_id) 
            else:
                self.start_workorder(workorder_id)
            return data

        #-----------------------------------------------
        # TH 2: qr_code.startswith("OK")
        #-----------------------------------------------
        if qr_code.startswith("OK"):
            package = Package.search([('name', '=', qr_code)], limit=1)
            if not package:
                package = Package.create({
                    'name': qr_code,
                    'current_step': workorder.operation_id.name if workorder.operation_id else '',
                    'current_component_id': bom_component.id,
                    'last_qty': final_quantity,
                })
            else:
                # Tùy logic, final_quantity <= package.last_qty?
                final_quantity = min(final_quantity, package.last_qty)

            lock_package(package, workorder.id, bom_component.id)

            # Tìm activity OK đang mở
            act_ok_open = Activity.search([
                ('work_order_id', '=', workorder.id),
                ('component_id', '=', component_id),
                ('package_id', '=', package.id),
                ('quality', '>=', 0.9),
                ('finish', '=', False),
            ], limit=1)

            if act_ok_open:
                # => Finish
                time_spent = (now - (act_ok_open.start or now)).total_seconds() / 60.0
                if time_spent < 0.1 and not force:
                    raise UserError(_("Thời gian quá ngắn (%.2f phút). force=True để bỏ qua.") % time_spent)

                old_qty = act_ok_open.quantity
                act_ok_open.write({
                    'finish': now,
                    # 'quantity': final_quantity, # Tùy logic, có thể ghi đè
                })
                package.write({
                    'current_step': workorder.operation_id.name if workorder.operation_id else '',
                    'current_component_id': bom_component.id,
                    'last_qty': act_ok_open.quality,
                    'current_workorder_id': False,
                })
                data = self.get_data(workorder_id)
            else:
                # => Bắt đầu
                act_ok_done = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', component_id),
                    ('package_id', '=', package.id),
                    ('quality', '>=', 0.9),
                    ('finish','!=',False),
                ], limit=1)
                if act_ok_done and not force:
                    raise UserError(_(
                        "Bạn đã hoàn thành package '%s'. force=True nếu muốn làm lại."
                    ) % qr_code)
                new_act_ok = Activity.create({
                    'work_order_id': workorder.id,
                    'component_id': component_id,
                    'package_id': package.id,
                    'start': now,
                    'quantity': final_quantity,
                    'quality': 1,
                })
                package.write({
                    'current_step': workorder.operation_id.name if workorder.operation_id else '',
                    'current_component_id': bom_component.id,
                    'last_qty': final_quantity,
                    'current_workorder_id': workorder.id,
                })
                data = self.get_data(workorder_id)

            workorder_remain = sum(c['remain_quantity'] for c in data['components'])
            workorder_producing = sum(c['producing_quantity'] for c in data['components'])
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(workorder_id) 
            else:
                self.start_workorder(workorder_id)
            return data

        #-----------------------------------------------
        # TH 3: qr_code.startswith("NG")
        #-----------------------------------------------
        if qr_code.startswith("NG"):
            final_quantity = quantity if quantity is not None else 1
            package = Package.search([('name', '=', qr_code)], limit=1)
            if not package:
                package = Package.create({
                    'name': qr_code,
                    'current_step': workorder.operation_id.name if workorder.operation_id else '',
                    'current_component_id': bom_component.id,
                    'last_qty': 0.0,
                })
            lock_package(package, workorder.id, bom_component.id)

            act_ng = Activity.search([
                ('work_order_id','=', workorder_id),
                ('component_id','=', component_id),
                ('package_id','=', package.id),
                ('quality','<',0.9),
            ], order='id asc', limit=1)
            old_ng_qty = act_ng.quantity if act_ng else 0.0

            if not act_ng:
                # Tạo
                act_ng = Activity.create({
                    'work_order_id': workorder.id,
                    'component_id': component_id,
                    'package_id': package.id,
                    'start': now,
                    'quantity': 0.0,
                    'quality': 0.8,
                })
            else:
                if act_ng.finish and not force:
                    raise UserError(_("Activity NG đã finish => force=True để cập nhật."))

            new_ng_qty = old_ng_qty + final_quantity
            act_ng.write({
                'finish': now,
                'quantity': new_ng_qty,
            })

            # Trừ OK
            act_ok_open = Activity.search([
                ('work_order_id','=', workorder.id),
                ('component_id','=', component_id),
                ('quality','>=',0.9),
                ('finish','=',False),
            ], order='create_date desc', limit=1)
            if not act_ok_open and not force:
                raise UserError(_("Không có OK để trừ => force=True."))
            elif act_ok_open:
                if act_ok_open.quantity < final_quantity and not force:
                    raise UserError(_(
                        "OK có %.2f, không đủ => force=True."
                    ) % act_ok_open.quantity)
                act_ok_open.write({'quantity': act_ok_open.quantity - final_quantity})

            package.write({
                'current_step': workorder.operation_id.name if workorder.operation_id else '',
                'current_component_id': bom_component.id,
                'last_qty': new_ng_qty,
                'current_workorder_id': False,
            })

            data = self.get_data(workorder_id)
            workorder_remain = sum(c['remain_quantity'] for c in data['components'])
            workorder_producing = sum(c['producing_quantity'] for c in data['components'])
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(workorder_id)
            else:
                self.start_workorder(workorder_id)
            return data

        #-----------------------------------------------
        # ELSE => không hợp lệ
        #-----------------------------------------------
        raise UserError(_(
            "Mã '%s' không hợp lệ. Vui lòng để trống, hoặc bắt đầu bằng 'OK'/'NG'."
        ) % qr_code)

        
    def print_label(self,workorder_id,activity_id):
        self = self.sudo()
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like','ZTC-ZD230-203dpi-ZPL')],limit=1)
        pa = self.env['smartbiz_mes.production_activity'].browse(activity_id)
        
        
        if pa and printer:
            if pa.component_id.type == 'product':
                label = self.env['printing.label.zpl2'].search([('name','=','tem_san_pham')],limit=1)
            else:
                label = self.env['printing.label.zpl2'].search([('name','=','tem_dau_vao_mes')],limit=1)
            label.print_label(printer, pa)
            label = self.env['printing.label.zpl2'].search([('name','=','tem_dau_vao_mes')],limit=1)
            #return {'pa':pa.read(),'label':label.read(),'printer':printer.read()} 
        
        return self.get_data(workorder_id)
    
    def get_dashboard_data(self, date):
        # Lấy tất cả các lệnh sản xuất trong ngày với trạng thái khác 'draft' và 'cancel'
        production_orders = self.env['mrp.production'].search([
            ('date_start', '>=', date + ' 00:00:00'),
            ('date_start', '<=', date + ' 23:59:59'),
            ('state', 'not in', ['draft', 'cancel'])
        ])
        
        # Khởi tạo dữ liệu tổng hợp
        dashboard_data = []
        stt = 1

        # Thu thập tất cả các công đoạn từ work orders
        all_steps = set()
        for order in production_orders:
            for wo in order.workorder_ids:
                step_name = wo.workcenter_id.name.strip().lower()
                all_steps.add(step_name)

        # Sắp xếp và chuẩn hóa các công đoạn
        all_steps = sorted(all_steps)
        step_display_names = {step: step.capitalize() for step in all_steps}

        for order in production_orders:
            # Lấy thời gian thực tế của từng công đoạn
            work_orders = order.workorder_ids
            work_times = {step: 0.0 for step in all_steps}
            
            for wo in work_orders:
                step_name = wo.workcenter_id.name.strip().lower()
                if step_name in work_times:
                    work_times[step_name] += wo.duration

            # Tạo dòng dữ liệu cho bảng tổng hợp
            row = {
                'stt': stt,
                'kh': order.origin,
                'lot': order.name,
                'item': order.product_id.name,
                'so_luong': order.product_qty,
                'thoi_gian_tieu_chuan': round(order.duration_expected, 2),
                'thoi_gian_thuc_te': round(sum(work_times.values()), 2),
            }

            # Thêm dữ liệu từng công đoạn
            for step in all_steps:
                row[step_display_names[step]] = work_times[step]

            dashboard_data.append(row)
            stt += 1
        
        return {
            'steps': [step_display_names[step] for step in all_steps],
            'data': dashboard_data
        }
    
    def get_faulty_data(self, date):
        # Lấy các công đoạn sản xuất từ tất cả work orders trong ngày
        production_orders = self.env['mrp.production'].search([
            ('date_start', '>=', f"{date} 00:00:00") if date else (),
            ('date_start', '<=', f"{date} 23:59:59") if date else (),
            ('state', 'not in', ['draft', 'cancel'])
        ])

        # Tạo danh sách các bước sản xuất (chuẩn hóa tên)
        all_steps = set()
        for order in production_orders:
            for wo in order.workorder_ids:
                step_name = wo.workcenter_id.name.strip().lower()
                all_steps.add(step_name)
        all_steps = sorted(all_steps)
        step_display_names = {step: step.capitalize() for step in all_steps}

        # Khởi tạo dữ liệu lỗi gộp theo `lot` và `component`
        grouped_faulty_data = {}

        for order in production_orders:
            lot_key = order.name  # Sử dụng `lot` làm key để gộp
            if lot_key not in grouped_faulty_data:
                grouped_faulty_data[lot_key] = {
                    'kh': order.origin,
                    'lot': order.name,
                    'item': order.product_id.name,
                    'components': {},  # Chứa lỗi từng component
                }

            for wo in order.workorder_ids:
                # Lọc các hoạt động lỗi cho work order này
                faulty_activities = self.env['smartbiz_mes.production_activity'].search([
                    ('work_order_id', '=', wo.id),
                    ('quality', '<', 0.9),
                    ('start', '!=', False),
                    ('finish', '!=', False)
                ])

                for activity in faulty_activities:
                    component = activity.component_id
                    step_name = wo.workcenter_id.name.strip().lower()
                    step_display_name = step_display_names.get(step_name, step_name.capitalize())

                    # Gộp lỗi vào component
                    if component.id not in grouped_faulty_data[lot_key]['components']:
                        grouped_faulty_data[lot_key]['components'][component.id] = {
                            'component_name': component.name,
                            'total_faulty': 0,
                            **{step: 0 for step in step_display_names.values()}
                        }

                    component_data = grouped_faulty_data[lot_key]['components'][component.id]
                    component_data['total_faulty'] += activity.quantity
                    component_data[step_display_name] += activity.quantity

        # Chuyển dữ liệu từ dictionary sang danh sách
        faulty_data = []
        stt = 1
        for lot_data in grouped_faulty_data.values():
            for component_data in lot_data['components'].values():
                faulty_row = {
                    'stt': stt,
                    'kh': lot_data['kh'],
                    'lot': lot_data['lot'],
                    'item': lot_data['item'],
                    **component_data,
                }
                faulty_data.append(faulty_row)
                stt += 1

        return faulty_data

    def start_workorder(self,workorder_id):
        order = self.browse(workorder_id)
        order.button_start()
        return self.get_data(workorder_id)
        
    def pause_workorder(self,workorder_id):
        order = self.browse(workorder_id)
        order.button_pending()
        return self.get_data(workorder_id)
        
    def finish_workorder(self,workorder_id):
        order = self.browse(workorder_id)
        order.button_finish()
        return self.get_data(workorder_id)

class mrp_BoM(models.Model):
    _inherit = ['mrp.bom']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'bom_id')


class mrp_bomline(models.Model):
    _inherit = ['mrp.bom.line']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'material_id')


class mrp_routingworkcenter(models.Model):
    _inherit = ['mrp.routing.workcenter']
    components_ids = fields.Many2many('smartbiz_mes.bom_components', 'routing_bom_components_rel1', 'components_ids', 'operations_ids', string='Components')


class mrp_bombyproduct(models.Model):
    _inherit = ['mrp.bom.byproduct']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'product_id')


class Stock_picking(models.Model):
    _inherit = ['stock.picking']
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')


    @api.model
    def create(self, vals):
        picking = super(Stock_picking, self).create(vals)
        
        # Nếu có đơn mua (purchase order) và purchase order có trường production_request_id thì gán cho picking
        if picking.purchase_id and picking.purchase_id.production_request_id:
            picking.production_request_id = picking.purchase_id.production_request_id.id

        return picking

class smartbiz_mes_Package(models.Model):
    _name = "smartbiz_mes.package"
    _description = "Package"
    name = fields.Char(string='Name', default = 'New')
    current_step = fields.Char(string='Current Step')
    current_component_id = fields.Many2one('smartbiz_mes.bom_components', string='Current Component')
    last_qty = fields.Float(string='Last Qty')
    current_workorder_id = fields.Many2one('product.product', string='Current Workorder')


    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_mes.package') or 'New'


        res = super().create(values)


        return res

class smartbiz_mes_Factory(models.Model):
    _name = "smartbiz_mes.factory"
    _description = "Factory"
    name = fields.Char(string='Name')
    company_id = fields.Many2one('res.company', string='Company')
    production_lines_ids = fields.One2many('smartbiz_mes.production_line', 'code')


class smartbiz_mes_ProductionLine(models.Model):
    _name = "smartbiz_mes.production_line"
    _description = "Production Line"
    name = fields.Char(string='Name')
    code = fields.Char(string='Code')
    type_id = fields.Many2one('smartbiz_mes.production_line_type', string='Type')
    picking_type_id = fields.Many2one('stock.picking.type', string='Picking Type')
    factory_id = fields.Many2one('smartbiz_mes.factory', string='Factory')
    work_centers_ids = fields.One2many('mrp.workcenter', 'production_line_id')


class smartbiz_mes_ProductionActivity(models.Model):
    _name = "smartbiz_mes.production_activity"
    _description = "Production Activity"
    work_order_id = fields.Many2one('mrp.workorder', string='Work Order')
    component_id = fields.Many2one('smartbiz_mes.bom_components', string='Component')
    quantity = fields.Float(string='Quantity')
    quality = fields.Float(string='Quality')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    package_id = fields.Many2one('smartbiz_mes.package', string='Package')
    start = fields.Datetime(string='Start')
    finish = fields.Datetime(string='Finish')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    status = fields.Selection([('new','New'),('started','Started'),('paused','Paused'),('finished','Finished'),], string='Status', default = 'new')


    @api.depends('work_order_id', 'component_id')
    def _compute_name(self):
        for record in self:
            # Kiểm tra nếu work_order_id.name và component_id.name có giá trị hợp lệ
            work_order_name = record.work_order_id.name if record.work_order_id.name else ''
            component_name = record.component_id.name if record.component_id.name else ''
            
            # Gán giá trị cho trường name
            record.name = work_order_name + " - " + component_name

    @api.depends('start', 'finish')
    def _compute_duration(self):
        for record in self:
            if record.start and record.finish:
                duration = (record.finish - record.start).total_seconds() / 60 
                record.duration = duration
            else:
                record.duration = 0.0

class smartbiz_mes_BoMComponents(models.Model):
    _name = "smartbiz_mes.bom_components"
    _description = "BoM Components"
    name = fields.Char(string='Name')
    type = fields.Selection([('material','Material'),('product','Product'),('main_product','Main Product'),], string='Type', required=True)
    quantity = fields.Float(string='Quantity')
    material_id = fields.Many2one('mrp.bom.line', string='Material')
    product_id = fields.Many2one('mrp.bom.byproduct', string='Product')
    bom_id = fields.Many2one('mrp.bom', string='BoM')
    operations_ids = fields.Many2many('mrp.routing.workcenter', 'routing_bom_components_rel1', 'operations_ids', 'components_ids', string='Operations')
    package_quantity = fields.Float(string='Package Quantity')
    print_label = fields.Boolean(string='Print Label')


class smartbiz_mes_ProductionLineType(models.Model):
    _name = "smartbiz_mes.production_line_type"
    _description = "Production Line Type"
    name = fields.Char(string='Name')


class smartbiz_mes_ProductionReport(models.Model):
    _name = "smartbiz_mes.production_report"
    _rec_name = "product_id"
    _auto=False
    _description = "Production Report"
    production_order_id = fields.Many2one('mrp.production', string='Production Order')
    product_id = fields.Many2one('product.product', string='Product')
    currency_id = fields.Many2one('res.currency', string='Currency')
    date = fields.Datetime(string='Date')
    planned_quantity = fields.Float(string='Planned Quantity')
    produced_quantity = fields.Float(string='Produced Quantity')
    remaining_quantity = fields.Float(string='Remaining Quantity')
    yield_percentage = fields.Float(string='Yield Percentage')
    component_cost = fields.Monetary(string='Component Cost')
    operation_cost = fields.Monetary(string='Operation Cost')
    total_cost = fields.Monetary(string='Total Cost')
    component_cost_per_unit = fields.Monetary(string='Component Cost per Unit')
    operation_cost_per_unit = fields.Monetary(string='Operation Cost per Unit')
    cost_per_unit = fields.Monetary(string='Cost per Unit')
    expected_duration = fields.Float(string='Expected Duration')
    duration = fields.Float(string='Duration')
    duration_per_unit = fields.Float(string='Duration per Unit')
    byproduct_cost = fields.Float(string='ByProduct Cost')


    def init(self):
        tools.drop_view_if_exists(self._cr, 'smartbiz_mes_production_report')
        self._cr.execute("""
            CREATE OR REPLACE VIEW smartbiz_mes_production_report AS (
                SELECT
                    mp.id AS id,
                    mp.name AS name,
                    mp.id AS production_order_id,
                    mp.product_id AS product_id,
                    mp.company_id AS company_id,
                    rc.currency_id AS currency_id,
                    mp.date_start AS date,
                    mp.product_qty AS planned_quantity,
                    COALESCE(mf.quantity, 0) AS produced_quantity,
                    (mp.product_qty - COALESCE(mf.quantity, 0)) AS remaining_quantity,
                    CASE
                        WHEN mp.product_qty > 0 THEN (COALESCE(mf.quantity, 0) / mp.product_qty) * 100
                        ELSE 0
                    END AS yield_percentage,
                    (SELECT SUM(svl.unit_cost * sm.quantity)
                     FROM stock_move sm
                     JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
                     WHERE sm.raw_material_production_id = mp.id AND sm.state = 'done') AS component_cost,
                    (SELECT SUM(wc.costs_hour * (wo.duration / 60.0))
                     FROM mrp_workcenter wc
                     JOIN mrp_workorder wo ON wo.workcenter_id = wc.id
                     WHERE wo.production_id = mp.id AND wo.state = 'done') AS operation_cost,
                    (SELECT SUM(sm.price_unit * sm.quantity)
                     FROM stock_move sm
                     WHERE sm.production_id = mp.id AND sm.state = 'done' AND sm.byproduct_id IS NOT NULL) AS byproduct_cost,
                    ((SELECT SUM(svl.unit_cost * sm.quantity)
                      FROM stock_move sm
                      JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
                      WHERE sm.raw_material_production_id = mp.id AND sm.state = 'done') +
                     (SELECT SUM(wc.costs_hour * (wo.duration / 60.0))
                      FROM mrp_workcenter wc
                      JOIN mrp_workorder wo ON wo.workcenter_id = wc.id
                      WHERE wo.production_id = mp.id AND wo.state = 'done')) AS total_cost,
                    CASE
                        WHEN COALESCE(mf.quantity, 0) > 0 THEN (SELECT SUM(svl.unit_cost * sm.quantity)
                                                               FROM stock_move sm
                                                               JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
                                                               WHERE sm.raw_material_production_id = mp.id AND sm.state = 'done') / mf.quantity
                        ELSE 0
                    END AS component_cost_per_unit,
                    CASE
                        WHEN COALESCE(mf.quantity, 0) > 0 THEN (SELECT SUM(wc.costs_hour * (wo.duration / 60.0))
                                                               FROM mrp_workcenter wc
                                                               JOIN mrp_workorder wo ON wo.workcenter_id = wc.id
                                                               WHERE wo.production_id = mp.id AND wo.state = 'done') / mf.quantity
                        ELSE 0
                    END AS operation_cost_per_unit,
                    CASE
                        WHEN COALESCE(mf.quantity, 0) > 0 THEN ((SELECT SUM(svl.unit_cost * sm.quantity)
                                                               FROM stock_move sm
                                                               JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
                                                               WHERE sm.raw_material_production_id = mp.id AND sm.state = 'done') +
                                                              (SELECT SUM(wc.costs_hour * (wo.duration / 60.0))
                                                               FROM mrp_workcenter wc
                                                               JOIN mrp_workorder wo ON wo.workcenter_id = wc.id
                                                               WHERE wo.production_id = mp.id AND wo.state = 'done')) / mf.quantity
                        ELSE 0
                    END AS cost_per_unit,
                    (SELECT SUM(wo.duration_expected / 60.0)
                     FROM mrp_workorder wo
                     WHERE wo.production_id = mp.id) AS expected_duration,
                    (SELECT SUM(wo.duration / 60.0)
                     FROM mrp_workorder wo
                     WHERE wo.production_id = mp.id) AS duration,
                    CASE
                        WHEN COALESCE(mf.quantity, 0) > 0 THEN 
                            (SELECT SUM(wo.duration / 60.0)
                             FROM mrp_workorder wo
                             WHERE wo.production_id = mp.id) / mf.quantity
                        ELSE 0
                    END AS duration_per_unit
                FROM
                    mrp_production mp
                JOIN
                    res_company rc ON rc.id = mp.company_id
                LEFT JOIN
                    (SELECT move.production_id, SUM(move.quantity) AS quantity
                     FROM stock_move move
                     WHERE move.state = 'done' AND move.production_id IS NOT NULL
                     GROUP BY move.production_id) mf ON mp.id = mf.production_id
            )
        """)

class smartbiz_mes_Process(models.Model):
    _name = "smartbiz_mes.process"
    _description = "Process"
    name = fields.Char(string='Name')
    product_id = fields.Many2one('product.template', string='Product')
    operations_ids = fields.Many2many('smartbiz_mes.operation', 'process_operation_rel1', 'operations_ids', 'process_id', string='Operations')


class smartbiz_mes_Operation(models.Model):
    _name = "smartbiz_mes.operation"
    _description = "Operation"
    name = fields.Char(string='Name')
    process_id = fields.Many2one('smartbiz_mes.process', string='Process')
    production_line_type_id = fields.Many2one('smartbiz_mes.production_line_type', string='Production Line Type')
    product_id = fields.Many2one('product.product', string='Product')
    bom_id = fields.Many2one('mrp.bom', string='BOM')


    product_tmpl_id = fields.Many2one('product.template', 'Product Template', related='product_id.product_tmpl_id')

class smartbiz_mes_Request(models.Model):
    _name = "smartbiz_mes.request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Request"
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    code = fields.Char(string='Code', default = 'New')
    title = fields.Char(string='Title')
    partner_id = fields.Many2one('res.partner', string='Partner')
    request_type = fields.Selection([('sales','Sales'),('purchase','Purchase'),('production','Production'),('outsource','Outsource'),('inventory','Inventory'),], string='Request Type')
    parent_request_id = fields.Many2one('smartbiz_mes.request', string='Parent Request')
    product_template_id = fields.Many2one('product.template', string='Product Template')
    product_id = fields.Many2one('product.product', string='Product')
    process_id = fields.Many2one('smartbiz_mes.process', string='Process')
    quantity = fields.Float(string='Quantity')
    processing_quantity = fields.Float(string='Processing Quantity')
    done_quantity = fields.Float(string='Done Quantity')
    remain_quantity = fields.Float(string='Remain Quantity')
    plan_start = fields.Datetime(string='Plan Start')
    schedule_start = fields.Datetime(string='Schedule Start')
    start = fields.Datetime(string='Start')
    plan_finish = fields.Datetime(string='Plan Finish')
    schedule_finish = fields.Datetime(string='Schedule Finish')
    finish = fields.Datetime(string='Finish')
    production_ids = fields.One2many('mrp.production', 'production_request_id')
    picking_ids = fields.One2many('stock.picking', 'production_request_id')
    purchase_ids = fields.One2many('purchase.order', 'production_request_id')
    move_ids = fields.One2many('stock.move', 'production_request_id')
    sub_request_ids = fields.One2many('smartbiz_mes.request', 'parent_request_id')
    sub_request = fields.Integer(string='Sub Request', compute='_compute_sub_request', store=False)
    production = fields.Integer(string='Production', compute='_compute_production', store=False)
    picking = fields.Integer(string='Picking', compute='_compute_picking', store=False)
    purchase = fields.Integer(string='Purchase', compute='_compute_purchase', store=False)
    move = fields.Integer(string='Move', compute='_compute_move', store=False)
    state = fields.Selection([('draft','Draft'),('confirmed','Confirmed'),('processing','Processing'),('done','Done'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    @api.depends('code', 'title')
    def _compute_name(self):
        for record in self:
            if record.parent_request_id:
                record.name = (record.parent_request_id.code or '') + '-' +  (record.code or '') + '-' + (record.title or '')
            else:
                record.name = (record.code or '') + '-' + (record.title or '')

    @api.depends('production_ids')
    def _compute_sub_request(self):
        for record in self:
            count = record.sub_request_ids.search_count([('parent_request_id', '=', record.id)])
            record.sub_request = count

    @api.depends('picking_ids')
    def _compute_production(self):
        for record in self:
            count = record.production_ids.search_count([('production_request_id', '=', record.id)])
            record.production = count

    @api.depends('purchase_ids')
    def _compute_picking(self):
        for record in self:
            count = record.picking_ids.search_count([('production_request_id', '=', record.id)])
            record.picking = count

    @api.depends('move_ids')
    def _compute_purchase(self):
        for record in self:
            count = record.purchase_ids.search_count([('production_request_id', '=', record.id)])
            record.purchase = count  

    @api.depends('sub_request_ids')
    def _compute_move(self):
        for record in self:
            count = record.move_ids.search_count([('production_request_id', '=', record.id)])
            record.move = count

    def action_draft_confirm(self):
        self.write({'state': 'confirmed'})

        
        
    def action_confirmed_create_mos(self):
        return True

        
        
    def action_confirmed_create_sub_request(self):
        return True

        
        
    def action_sub_request(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_smartbiz_mes_request_2_smartbiz_mes_request")
        context = eval(action['context'])
        context.update(dict(self._context,default_parent_request_id=self.id))
        action['context'] = context
        action['domain'] = [('parent_request_id', '=', self.id)]

        return action

    def action_productions(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_smartbiz_mes_request_2_mrp_production")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_request_id=self.id))
        action['context'] = context
        action['domain'] = [('production_request_id', '=', self.id)]

        return action

    def action_purchases(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_smartbiz_mes_request_2_purchase_order")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_request_id=self.id))
        action['context'] = context
        action['domain'] = [('production_request_id', '=', self.id)]

        return action

    def action_pickings(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_smartbiz_mes_request_2_stock_picking")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_request_id=self.id))
        action['context'] = context
        action['domain'] = [('production_request_id', '=', self.id)]

        return action

    def action_moves(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_smartbiz_mes_request_2_stock_move")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_request_id=self.id))
        action['context'] = context
        action['domain'] = [('production_request_id', '=', self.id)]

        return action

    @api.model
    def create(self, values):
        if values.get('code', 'New') == 'New':
           values['code'] = self.env['ir.sequence'].next_by_code('smartbiz_mes.request') or 'New'


        res = super().create(values)


        return res

class purchase_order(models.Model):
    _inherit = ['purchase.order']
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')


class Stock_move(models.Model):
    _inherit = ['stock.move']
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')


    @api.model
    def create(self, vals):
        # Gọi hàm create của lớp cha để tạo record stock.move
        move = super(Stock_move, self).create(vals)
        
        # Nếu có picking và picking có trường production_request_id thì gán cho move
        if move.picking_id and move.picking_id.production_request_id:
            move.production_request_id = move.picking_id.production_request_id.id
        # Nếu không có picking, kiểm tra nếu move liên kết với mrp.production (thông qua trường raw_material_production_id)
        # và production đó có production_request_id thì gán cho move
        elif move.raw_material_production_id and move.raw_material_production_id.production_request_id:
            move.production_request_id = move.raw_material_production_id.production_request_id.id
        
        return move

