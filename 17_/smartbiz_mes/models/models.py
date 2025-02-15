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
            self.env['stock.move.line'].create({'move_id':data['move_id'],'product_id':data['product_id'],'product_uom_id':data['product_uom_id'],'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'state':'assigned','picked':True})
        mo = self.browse(production_id)
        if mo:
            finisheds = mo.move_finished_ids
            move_lines = finisheds[0].move_line_ids
            qty_produced = 0
            qty_producing = sum(move_lines.mapped('quantity')) if move_lines else 0
            mo.write({'qty_producing':qty_producing,'qty_produced':qty_produced})
  
        return self.get_data(production_id)
    
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

class mrp_Workcenter(models.Model):
    _inherit = ['mrp.workcenter']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    
    def get_barcode_data(self, barcode, filters, barcodeType):
    # Các trường cần lấy cho từng loại barcodeType
        fields_workcenter = ['id', 'name', 'code', 'production_line_id']  # Thêm các trường cơ bản mà bạn muốn
        filters_employee =  ['id', 'name', 'barcode']
        if barcodeType:
            if barcodeType == 'workcenters':
                # Lấy thông tin Workcenter và thêm các trường cần thiết
                record = self.env['mrp.workcenter'].search_read([('code', '=', barcode)], limit=1, fields=fields_workcenter)
            elif barcodeType == 'employees':
                # Lấy thông tin Employee và thêm các trường cần thiết
                record = self.env['hr.employee'].search_read([('barcode', '=', barcode)], limit=1, fields=filters_employee)
            
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': barcodeType, 'record': record[0], 'fromCache': False}
        
        else:
            # Nếu không có barcodeType, tìm theo 'workcenters' hoặc 'employees' mặc định
            record = self.env['mrp.workcenter'].search_read([('code', '=', barcode)], limit=1, fields=fields_workcenter)
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'workcenters', 'record': record[0], 'fromCache': False}
            
            record = self.env['hr.employee'].search_read([('barcode', '=', barcode)], limit=1, fields=filters_employee)
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'employees', 'record': record[0], 'fromCache': False}

        # Nếu không tìm thấy kết quả nào
        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False, 'fromCache': False}



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
                ok_quantity = 0
                ng_quantity = 0
                producing_ok_quantity = 0
                producing_ng_quantity = 0
                batch_quantity = 20                
                quantity = order.production_id.product_qty / order.production_id.bom_id.product_qty * comp.quantity              
                
                for pa in production_activities:
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
                    'produced_quantity':produced_quantity
                    
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
        if type == 'start':
            if remain_quantity > batch_quantity:
                quantity = batch_quantity
            else:
                quantity = remain_quantity
            
            if processing_ok:
                processing_ok.write({'quantity':quantity})
            else:
                processing_ok.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':quantity,'start':now,'quality':1})
        if type == 'ok':            
            if processing_ok:
                processing_ok.write({'quantity':producing_ok_quantity})
            else:
                processing_ok.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ok_quantity,'start':now,'quality':1})
        if type == 'ng':            
            if processing_ok:
                processing_ok.write({'quantity':producing_ok_quantity})
            else:
                processing_ok.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ok_quantity,'start':now,'quality':1})
          
            if processing_ng:
                processing_ng.write({'quantity':producing_ng_quantity})
            else:
                processing_ng.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ng_quantity,'start':now,'quality':0.8})
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
        
    def print_label(self,workorder_id,component_id):
        self = self.sudo()
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like','ZTC-ZD230-203dpi-ZPL')],limit=1)
        pa = self.env['smartbiz_mes.production_activity'].search([('work_order_id','=',workorder_id),('component_id','=',component_id)],limit=1)
        
        
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

        # Các công đoạn được chuẩn hóa
        valid_steps = {
            'flash': 'Flash',
            'sizer & dán cạnh': 'Sizer & Dán Cạnh',
            'panelsaw': 'Panelsaw',
            'insert boring': 'Insert Boring',
            'nc boring': 'NC Boring',
            'kumi đầu chuyền': 'Kumi Đầu Chuyền',
            'đặt tanaita': 'Đặt Tanaita',
            'kumi cuối chuyền': 'Kumi Cuối Chuyền',
            'qc': 'QC',
            'số lượng đóng gói': 'Số Lượng Đóng Gói'
        }

        for order in production_orders:
            # Lấy thời gian thực tế của từng công đoạn
            work_orders = order.workorder_ids
            work_times = {step: 0.0 for step in valid_steps.values()}
            
            for wo in work_orders:
                # Chuẩn hóa tên công đoạn
                step_name = wo.workcenter_id.name.strip().lower()
                if step_name in valid_steps:
                    work_times[valid_steps[step_name]] += wo.duration

            # Tạo dòng dữ liệu cho bảng tổng hợp thời gian các công đoạn
            row = {
                'stt': stt,
                'kh': order.origin,
                'lot': order.name,
                'item': order.product_id.name,
                'so_luong': order.product_qty,
                'thoi_gian_tieu_chuan': round(order.duration_expected, 2),
                'thoi_gian_thuc_te': round(sum(work_times.values()), 2),
                'flash': work_times['Flash'],
                'sizer_dan_canh': work_times['Sizer & Dán Cạnh'],
                'panelsaw': work_times['Panelsaw'],
                'insert_boring': work_times['Insert Boring'],
                'nc_boring': work_times['NC Boring'],
                'kumi_dau_chuyen': work_times['Kumi Đầu Chuyền'],
                'dat_tanaita': work_times['Đặt Tanaita'],
                'kumi_cuoi_chuyen': work_times['Kumi Cuối Chuyền'],
                'qc': work_times['QC'],
                'so_luong_dong_goi': work_times['Số Lượng Đóng Gói'],
            }
            
            dashboard_data.append(row)
            stt += 1
        
        return dashboard_data

    def get_faulty_data(self, date):
        # Lấy tất cả các lệnh sản xuất trong ngày với trạng thái khác 'draft' và 'cancel'
        production_orders = self.env['mrp.production'].search([
            ('date_start', '>=', date + ' 00:00:00'),
            ('date_start', '<=', date + ' 23:59:59'),
            ('state', 'not in', ['draft', 'cancel'])
        ])
        
        # Khởi tạo dữ liệu sản phẩm lỗi
        faulty_data = []
        stt = 1

        # Các công đoạn được chuẩn hóa
        valid_steps = {
           'flash': 'Flash',
            'sizer & dán cạnh': 'Sizer & Dán Cạnh',
            'panelsaw': 'Panelsaw',
            'insert boring': 'Insert Boring',
            'nc boring': 'NC Boring',
            'kumi đầu chuyền': 'Kumi Đầu Chuyền',
            'đặt tanaita': 'Đặt Tanaita',
            'kumi cuối chuyền': 'Kumi Cuối Chuyền',
            'qc': 'QC',
            'số lượng đóng gói': 'Số Lượng Đóng Gói'
        }

        for order in production_orders:
            # Lấy thời gian thực tế của từng công đoạn
            work_orders = order.workorder_ids
            step_faulty_data = {step: 0 for step in valid_steps.values()}
            
            for wo in work_orders:
                # Chuẩn hóa tên công đoạn
                step_name = wo.workcenter_id.name.strip().lower()

                # Lấy thông tin các component của work order
                components = wo.production_id.bom_id.components_ids.filtered(lambda c: wo.operation_id.id in c.operations_ids.ids)

                for comp in components:
                    # Lấy thông tin các sản phẩm lỗi cho từng component
                    faulty_activities = self.env['smartbiz_mes.production_activity'].search([
                        ('work_order_id', '=', wo.id),
                        ('component_id', '=', comp.id),
                        ('quality', '<', 0.9),
                        ('start', '!=', False),
                        ('finish', '!=', False)
                    ])
                    for activity in faulty_activities:
                        step_faulty_data[valid_steps[step_name]] += activity.quantity

            # Tạo dòng dữ liệu cho bảng tổng hợp sản phẩm lỗi từng công đoạn
            total_faulty = sum(step_faulty_data.values())
            if total_faulty > 0:
                faulty_row = {
                    'stt': stt,
                    'kh': order.origin,
                    'lot': order.name,
                    'item': order.product_id.name,
                    'so_luong': total_faulty,
                    'flash': step_faulty_data['Flash'],
                    'sizer_dan_canh': step_faulty_data['Sizer & Dán Cạnh'],
                    'panelsaw': step_faulty_data['Panelsaw'],
                    'insert_boring': step_faulty_data['Insert Boring'],
                    'nc_boring': step_faulty_data['NC Boring'],
                    'kumi_dau_chuyen': step_faulty_data['Kumi Đầu Chuyền'],
                    'dat_tanaita': step_faulty_data['Đặt Tanaita'],
                    'kumi_cuoi_chuyen': step_faulty_data['Kumi Cuối Chuyền'],
                    'qc': step_faulty_data['QC'],
                    'so_luong_dong_goi': step_faulty_data['Số Lượng Đóng Gói'],
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
    checkpoints_ids = fields.One2many('smartbiz_mes.check_point', 'bom_id')


class mrp_bomline(models.Model):
    _inherit = ['mrp.bom.line']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'material_id')


class mrp_routingworkcenter(models.Model):
    _inherit = ['mrp.routing.workcenter']
    components_ids = fields.Many2many('smartbiz_mes.bom_components', 'routing_bom_components_rel1', 'components_ids', 'operations_ids', string='Components')


class mrp_bombyproduct(models.Model):
    _inherit = ['mrp.bom.byproduct']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'product_id')


class smartbiz_mes_Factory(models.Model):
    _name = "smartbiz_mes.factory"
    _description = "Factory"
    name = fields.Char(string='Name')
    company_id = fields.Many2one('res.company', string='Company')
    production_lines_ids = fields.One2many('smartbiz_mes.production_line', 'factory_id')


class smartbiz_mes_ProductionLine(models.Model):
    _name = "smartbiz_mes.production_line"
    _description = "Production Line"
    name = fields.Char(string='Name')
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
    start = fields.Datetime(string='Start')
    finish = fields.Datetime(string='Finish')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)

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
                duration = (record.finish - record.start).total_seconds() / 60  # Tính thời gian bằng phút
                record.duration = duration
            else:
                record.duration = 0.0

class smartbiz_mes_BoMComponents(models.Model):
    _name = "smartbiz_mes.bom_components"
    _description = "BoM Components"
    name = fields.Char(string='Name')
    type = fields.Selection([('material','Nguyên liệu'),('product','Sản phẩm'),('main_product','Sản phẩm chính'),], string='Type', required=True)
    quantity = fields.Float(string='Quantity')
    material_id = fields.Many2one('mrp.bom.line', string='Material')
    product_id = fields.Many2one('mrp.bom.byproduct', string='Product')
    bom_id = fields.Many2one('mrp.bom', string='BoM')
    operations_ids = fields.Many2many('mrp.routing.workcenter', 'routing_bom_components_rel1', 'operations_ids', 'components_ids', string='Operations')
    checkpoints_ids = fields.One2many('smartbiz_mes.check_point', 'bom_id')


class smartbiz_mes_CheckPoint(models.Model):
    _name = "smartbiz_mes.check_point"
    _description = "Check Point"
    name = fields.Char(string='Name')
    bom_id = fields.Many2one('mrp.bom', string='BoM')
    component_id = fields.Many2one('smartbiz_mes.bom_components', string='Component')
    operation_id = fields.Many2one('mrp.routing.workcenter', string='Operation')
    type = fields.Selection([('measure','Đo lường'),('check','Kiểm tra'),], string='Type')
    attached_ids = fields.Many2many('ir.attachment', 'check_point_attachment_rel',  string='Attached')
    instruction = fields.Text(string='Instruction')
    code = fields.Text(string='Code')


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

