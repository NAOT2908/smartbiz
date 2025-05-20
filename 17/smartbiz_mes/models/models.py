import math
def remove_accents_and_upper(text):
    if not text:
        return ""
    # unidecode sẽ chuyển chữ có dấu (Unicode) sang ASCII tương đương
    text_noaccent = unidecode.unidecode(text)
    # chuyển sang chữ in hoa
    return text_noaccent.upper()
# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging,unidecode
from datetime import datetime, timedelta
import random
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, float_compare
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook

class RES_Users(models.Model):
    _inherit = ['res.users']
    workcenter_id = fields.Many2one('mrp.workcenter', string='WorkCenter')
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')


class mrp_Production(models.Model):
    _inherit = ['mrp.production', 'smartbiz.workflow_base']
    _name = 'mrp.production'
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    name = fields.Char(store='True', readonly=False)
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')
    lot_name = fields.Char(string='Lot Name')
    plan_start = fields.Datetime(string='Plan Start', default = lambda self: fields.Datetime.now())
    plan_finish = fields.Datetime(string='Plan Finish', default = lambda self: fields.Datetime.now() + timedelta(days=1))
    shift_id = fields.Many2one('smartbiz_mes.shift', string='Shift')
    activities_created = fields.Boolean(string='Activities Created', compute='_compute_activities_created', store=True)
    activities_printed = fields.Boolean(string='Activities Printed')
    production_activities_ids = fields.One2many('smartbiz_mes.production_activity', 'production_id')
    production_activities = fields.Integer(string='Production Activities', compute='_compute_production_activities', store=True)
    production_packages_ids = fields.One2many('smartbiz_mes.package', 'production_id')
    production_packages = fields.Integer(string='Production Packages', compute='_compute_production_packages', store=True)


    @api.depends('workorder_ids', 'workorder_ids.production_activity_ids')
    def _compute_activities_created(self):
        for record in self:
            if record.workorder_ids.production_activity_ids:
                record.activities_created = True
            else:
                record.activities_created = False

    @api.depends('production_activities_ids')
    def _compute_production_activities(self):
        for record in self:
            count = record.production_activities_ids.search_count([('production_id', '=', record.id)])
            record.production_activities = count

    @api.depends('production_packages_ids')
    def _compute_production_packages(self):
        for record in self:
            count = record.production_packages_ids.search_count([('production_id', '=', record.id)])
            record.production_packages = count

    def action_create_activities(self):
        """
        1. Kiểm tra xem có workorder nào pack_method == 'external_list' không.
           - Nếu không có -> gọi create_activities() trực tiếp.
           - Nếu có -> mở wizard để cho phép nhập package theo từng component.
        """
        self.ensure_one()
        # Tìm xem có WO dạng external_list ko
        wos_external = self.workorder_ids.filtered(
            lambda w: w.operation_id and w.operation_id.pack_method == 'external_list'
        )
        if wos_external:
            # Mở wizard
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'smartbiz_mes.external_list_wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_production_id': self.id,
                }
            }
        else:
            # Tạo activity luôn
            self.workorder_ids.create_activities()
            return True

        
        
    def action_print_activities(self):
        for record in self:
            record.workorder_ids.print_activities()
            record.activities_printed = True

        
        
    def action_reprint_activities(self):
        for record in self:
            record.workorder_ids.print_activities()

        
        
    def _get_fields(self,model):
        if model == 'mrp.production':
            return ['name','state','product_id','product_uom_id','lot_producing_id','lot_name','product_uom_qty','qty_produced','qty_producing','date_start','date_deadline','date_finished','company_id','user_id']
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
            
    def validate(self, production_id, create_backorder=True):
        production = self.browse(production_id)
        if not production:
            raise UserError("MO không tồn tại.")

        if production.product_qty <= 0:
            raise UserError("Số lượng cần sản xuất của MO = 0 => dữ liệu sai.")

        # -------------------------------------------------------------------------
        # 0. Các biến cục bộ (hardcode cho ví dụ). Sau này có thể lấy từ config, v.v.
        # -------------------------------------------------------------------------
        require_packing = True  # Bắt buộc đóng gói
        free_ratio = False      # Tỉ lệ tự do

        # -------------------------------------------------------------------------
        # A. Kiểm tra bắt buộc đóng gói
                                                                          
        # -------------------------------------------------------------------------
        if require_packing:
                                                                                      
            all_moves = (production.move_finished_ids).filtered(lambda m: m.state not in ('done','cancel'))
                                                          
            all_lines = all_moves.mapped('move_line_ids').filtered(lambda ml: ml.state not in ('done','cancel'))

                                                                    
            any_line_missing_package = any(not ml.result_package_id for ml in all_lines)
            if any_line_missing_package:
                raise UserError(_(
                    "Sản phẩm này yêu cầu đóng gói bắt buộc, nhưng có dòng xuất/nhận chưa có package.\n"
                    "Vui lòng bổ sung package cho tất cả dòng."
                ))

        # -------------------------------------------------------------------------
        # B. Lấy/tạo move line cho SP chính (Step 1)
        # -------------------------------------------------------------------------
        finished_moves = production.move_finished_ids.filtered(lambda m: m.product_id == production.product_id)
        if finished_moves:
            finished_lines = finished_moves.mapped('move_line_ids').filtered(lambda ml: ml.state not in ('done','cancel'))
            if finished_lines:
                partial_qty = sum(finished_lines.mapped('quantity'))
            else:
                                                                                    
                partial_qty = production.product_qty
                finished_moves.write({'product_uom_qty': partial_qty})
                self.env['stock.move.line'].create({
                    'move_id': finished_moves[0].id,
                    'product_id': production.product_id.id,
                    'product_uom_id': production.product_uom_id.id,
                    'quantity': partial_qty,
                    'location_id': production.location_src_id.id,
                    'location_dest_id': production.location_dest_id.id,
                    'state': 'assigned',
                })
        else:
                                                         
            partial_qty = production.product_qty
            new_fin_move = self.env['stock.move'].create({
                'production_id': production.id,
                'product_id': production.product_id.id,
                'product_uom_qty': production.product_qty,
                'location_id': production.location_src_id.id,
                'location_dest_id': production.location_dest_id.id,
            })
            self.env['stock.move.line'].create({
                'move_id': new_fin_move.id,
                'product_id': production.product_id.id,
                'product_uom_id': production.product_uom_id.id,
                'quantity': production.product_qty,
                'location_id': production.location_src_id.id,
                'location_dest_id': production.location_dest_id.id,
                'state': 'assigned',
            })

        # Tính ratio
        ratio = partial_qty / production.product_qty if production.product_qty else 1.0
        if ratio > 0.9:
            create_backorder = False
        # -------------------------------------------------------------------------
        # C. Tự động tạo line cho BYPRODUCT nếu chưa có (Step 4)
                                                                                  
        # -------------------------------------------------------------------------
        byproducts = production.move_finished_ids.filtered(lambda m: m.product_id != production.product_id and m.state not in ('done','cancel'))
        for byp_move in byproducts:
            existing_lines = byp_move.move_line_ids.filtered(lambda ml: ml.state not in ('done','cancel'))
            sum_lines = sum(existing_lines.mapped('quantity'))
            if sum_lines <= 0:
                                            
                qty_create = byp_move.product_uom_qty * ratio
                                                                                                                
                self.env['stock.move.line'].create({
                    'move_id': byp_move.id,
                    'product_id': byp_move.product_id.id,
                    'product_uom_id': byp_move.product_uom.id,
                    'quantity': qty_create,
                    'location_id': byp_move.location_id.id,
                    'location_dest_id': byp_move.location_dest_id.id,
                    'state': 'assigned',
                })

        # -------------------------------------------------------------------------
        # D. Xử lý raw moves (Step 3) - Cập nhật theo ratio
        # -------------------------------------------------------------------------
        from odoo.tools.float_utils import float_compare

        for move in production.move_raw_ids.filtered(lambda mv: mv.state not in ('done', 'cancel')):
            old_demand = move.product_uom_qty
            new_demand = old_demand * ratio
            existing_lines = move.move_line_ids.filtered(lambda ml: ml.state not in ('done','cancel'))
            sum_lines = sum(existing_lines.mapped('quantity'))                                                                                                   
            diff = sum_lines - new_demand                                           
            diff_percent = diff / new_demand                                   
            if diff < 0:  # Thiếu nguyên liệu
                missing = new_demand - sum_lines
                taken_quantity = move._update_reserved_quantity(
                    need=missing,
                    location_id=move.location_id,
                    lot_id=False,
                    package_id=False,
                    owner_id=False,
                    strict=False
                )

                if float_compare(taken_quantity, missing, precision_rounding=move.product_uom.rounding) < 0:
                    raise UserError(_(
                        "Không đủ tồn kho cho sản phẩm '%s' tại kho/lô xuất '%s'.\n"
                        "Cần thêm: %.2f, khả dụng: %.2f."
                    ) % (move.product_id.display_name,
                        move.location_id.display_name,
                        missing,
                        taken_quantity))

            elif diff > 0:  # Dư nguyên liệu
                for ml in reversed(existing_lines):
                    if diff <= 0:
                        break
                    if ml.quantity <= diff:
                        diff -= ml.quantity
                        ml.unlink()
                    else:
                        ml.write({'quantity': ml.quantity - diff})
                        diff = 0
                # if diff_percent > 0.1:
                #     raise UserError(_(
                #         "Lượng tiêu thụ cho sản phẩm '%s' tại kho/lô xuất '%s' vượt tiêu chuẩn quá 10%%.\n"
                #         "Thừa: %.2f%%."
                #     ) % (move.product_id.display_name,
                #         move.location_id.display_name,
                #         diff_percent * 100))
                # else:
                #     pass
            else:
                pass

        # -------------------------------------------------------------------------
        # E. Kiểm tra byproduct theo yêu cầu "free_ratio" hay BOM strict/flexible (Step 4)
                     
        # -------------------------------------------------------------------------
        for byp_move in byproducts:
            byp_done = sum(byp_move.mapped('quantity'))
            expected = byp_move.product_uom_qty * ratio

                                                
            if free_ratio:
                if abs(byp_done - expected) > 1e-4:
                    raise UserError(_(
                        "Byproduct %s lệch tỉ lệ khi 'tỉ lệ tự do' đang bật.\n"
                        "Đã = %.3f, Kỳ vọng = %.3f (ratio=%.2f)."
                    ) % (byp_move.product_id.display_name, byp_done, expected, ratio))
                                                  
            else:
                if abs(byp_done - expected) > 1e-4:
                    if production.bom_id and production.bom_id.consumption == 'strict':
                        raise UserError(_(
                            "Byproduct %s không khớp tỉ lệ (strict BOM).\n"
                            "Đã=%.3f, Kỳ vọng=%.3f (ratio=%.2f)."
                        ) % (byp_move.product_id.display_name, byp_done, expected, ratio))
                    # Với BOM flexible thì bỏ qua

        # -------------------------------------------------------------------------
        # F. Đảm bảo move line chính >= partial_qty (Step 5)
        # -------------------------------------------------------------------------
        finished_moves = production.move_finished_ids.filtered(lambda m: m.product_id == production.product_id)
        main_lines = finished_moves.mapped('move_line_ids').filtered(lambda ml: ml.state not in ('done','cancel'))
        total_finished = sum(main_lines.mapped('quantity'))
        if total_finished < partial_qty:
            missing_main = partial_qty - total_finished
            if finished_moves:
                self.env['stock.move.line'].create({
                    'move_id': finished_moves[0].id,
                    'product_id': production.product_id.id,
                    'product_uom_id': production.product_uom_id.id,
                    'quantity': missing_main,
                    'location_id': production.location_src_id.id,
                    'location_dest_id': production.location_dest_id.id,
                    'state': 'assigned',
                })
            else:
                                                                                                                   
                new_fin_move2 = self.env['stock.move'].create({
                    'production_id': production.id,
                    'product_id': production.product_id.id,
                    'product_uom_qty': production.product_qty,
                    'location_id': production.location_src_id.id,
                    'location_dest_id': production.location_dest_id.id,
                })
                self.env['stock.move.line'].create({
                    'move_id': new_fin_move2.id,
                    'product_id': production.product_id.id,
                    'product_uom_id': production.product_uom_id.id,
                    'quantity': missing_main,
                    'location_id': production.location_src_id.id,
                    'location_dest_id': production.location_dest_id.id,
                    'state': 'assigned',
                })

        # -------------------------------------------------------------------------
        # G. Lưu expected gốc byproduct (Step 7)
        # -------------------------------------------------------------------------
        byproduct_expected_map = {}
        for byp in byproducts:
            byproduct_expected_map[byp.product_id.id] = byp.product_uom_qty

        # -------------------------------------------------------------------------
        # H. Tách backorder nếu partial (Step 8)
        # -------------------------------------------------------------------------
        backorders = self.env['mrp.production']
        if create_backorder and (0 < partial_qty < production.product_qty):
            splitted = production._split_productions(
                amounts={production: [partial_qty, production.product_qty - partial_qty]},
                cancel_remaining_qty=False,
                set_consumed_qty=True
            )
            backorders = splitted - production

            # Cập nhật qty_producing cho MO gốc
            production.write({
                'qty_producing': partial_qty + production.qty_produced,
            })

            # Xử lý byproduct trong backorder
            for bo in backorders:
                                    
                bo.move_finished_ids.move_line_ids.unlink()
                for bo_byp in bo.move_finished_ids.filtered(lambda m: m.product_id != production.product_id):
                    product_id = bo_byp.product_id.id
                    expected_goc = byproduct_expected_map.get(product_id, bo_byp.product_uom_qty)
                                                      
                    goc_byp_moves = production.move_finished_ids.filtered(lambda m: m.product_id.id == product_id)
                    produced_qty = sum(goc_byp_moves.mapped('quantity'))
                    new_qty = max(0, expected_goc - produced_qty)
                    bo_byp.write({'product_uom_qty': new_qty})
                    # Nếu cần tự tạo move line cho backorder, thêm code tại đây
        else:
            # Nếu không tạo backorder nhưng partial_qty < product_qty,
            # bạn có thể cập nhật MO gốc để đánh dấu toàn bộ đã hoàn thành (hoặc xử lý theo nghiệp vụ yêu cầu)
            if partial_qty < production.product_qty:
                production.write({
                    'qty_producing': partial_qty + production.qty_produced,
                })

        # -------------------------------------------------------------------------
        # I. _post_inventory (Step 9)
        # -------------------------------------------------------------------------
        production._post_inventory(cancel_backorder=True)

        # -------------------------------------------------------------------------
        # J. Set MO => Done (Step 10)
        # -------------------------------------------------------------------------
        production.write({
            'date_finished': fields.Datetime.now(),
            'is_locked': True,
            'state': 'done',
            'qty_producing': partial_qty
        })

        # -------------------------------------------------------------------------
        # K. Trả về kết quả (Step 11)
        # -------------------------------------------------------------------------
        if backorders:
            return self.get_data(backorders[0].id)
        return self.get_data(production.id)

    def save_order(self,production_id,data):
        quantity = float(data['quantity'])
        if data['id']:
            self.env['stock.move.line'].browse(data['id']).write({'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'package_id':data['package_id'],'result_package_id':data['result_package_id'],'state':'assigned','picked':True})
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
        
    def print_move_line(self,production_id,data,printer_name):
        quantity = float(data['quantity'])
        if data['id']:
            record = self.env['stock.move.line'].browse(data['id'])
        else:
            record = self.env['stock.move.line'].create({'move_id':data['move_id'],'product_id':data['product_id'],'product_uom_id':data['product_uom_id'],'quantity':quantity,'location_id':data['location_id'],'location_dest_id':data['location_dest_id'],'lot_id':data['lot_id'],'picked':True})

        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like',printer_name)],limit=1)      
        label = self.env['printing.label.zpl2']
        label.print_label_auto(printer, record)
        return self.get_data(production_id)
        

    def delete_move_line(self,production_id,move_line_id):
        ml = self.env['stock.move.line'].browse(move_line_id)
        move = ml.move_id
        move.write({'move_line_ids':[(2,move_line_id)]})
        if not move.move_line_ids:
            move.picked = False
        return self.get_data(production_id)

    def print_package(self,production_id,package_id):
        lines = self.env['stock.move.line'].search([('result_package_id','=',package_id)])
        # for ml in lines:
        #     ml.write({'result_package_id':False})  
        return self.get_data(production_id)

    def delete_package(self,production_id,package_id):
        lines = self.env['stock.move.line'].search([('result_package_id','=',package_id)])
        for ml in lines:
            ml.write({'result_package_id':False})  
        return self.get_data(production_id)
    
    def update_package(self,production_id,lines):
        for l in lines:  
            line = self.env['stock.move.line'].browse(l['id'])
            qty = float(l['quantity'])
            #raise UserError(_("line %s" % line ))
            if qty <= 0:
                line.write({'result_package_id':False})
            else:
                line.write({'result_package_id':l['result_package_id'],'quantity':qty})
            
        return self.get_data(production_id)

    def create_packages(self,production_id,lines):
        for data in lines:
            move_id = data['move_id']
            product_id = data['product_id']
            product = self.env['product.product'].browse(product_id)
            product_uom_id = product.uom_id.id
            lot_id = False
            if data['lot_id']:
                lot_id = data['lot_id']
            elif data['lot_name']:
                lot_id = self.env['stock.lot'].search([('name','=',data['lot_name']),('product_id','=',product_id)],limit=1)
                if not lot_id:
                    lot_id = self.env['stock.lot'].create({'name':data['lot_name'],'product_id':product_id})
                lot_id = lot_id.id
            quantity = data['quantity']
            #raise UserError("data %s lot_name %s lot_id %s" % (data ,data['lot_name'],lot_id) )
            self.env['stock.move.line'].create({
                'move_id':move_id,
                'product_id':product_id,
                'product_uom_id':product_uom_id,
                'quantity':quantity,
                'location_id':data['location_id'],
                'location_dest_id':data['location_dest_id'],
                'lot_id':lot_id,
                'package_id':data['package_id'],
                'result_package_id':data['result_package_id'],
                'state':'assigned',
                'picked':True
            })
            
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

        # Tính finish_packages: chỉ tính các move line có result_package_id (không rỗng)
        pkg_data = {}
        for ml in finisheds.move_line_ids.filtered(lambda ml: ml.result_package_id):
            pkg_id = ml.result_package_id.id
            pkg_name = ml.result_package_id.name or ''
            prod_id = ml.product_id.id
            product_uom = ml.product_id.uom_id.name
            product_uom_id = ml.product_id.uom_id.id
            prod_name = ml.product_id.display_name or ''
            product_uom_qty = ml.move_id.product_uom_qty
            qty = ml.quantity
            remain_qty = product_uom_qty - qty

            # Nếu package chưa tồn tại trong pkg_data, khởi tạo
            if pkg_id not in pkg_data:
                pkg_data[pkg_id] = {
                    'name': pkg_name,
                    'package_id': pkg_id,
                    'products': {},
                    'lines': []  # Khởi tạo danh sách lines rỗng
                }
            
            # Tính toán thông tin sản phẩm trong package
            if prod_id not in pkg_data[pkg_id]['products']:
                pkg_data[pkg_id]['products'][prod_id] = {
                    'id': prod_id,
                    'product_name': prod_name,
                    'product_uom': product_uom,
                    'product_uom_id':product_uom_id,
                    'quantity': 0,
                    'product_uom_qty': product_uom_qty,
                    'remain_qty': remain_qty
                }
            pkg_data[pkg_id]['products'][prod_id]['quantity'] += qty

            # Thêm thông tin move line vào danh sách lines của package
            line_data = ml.read(order._get_fields('stock.move.line'))
            pkg_data[pkg_id]['lines'].append(line_data[0])

        # Tạo danh sách finish_packages với cả thông tin products và lines
        finish_packages = []
        for pkg in pkg_data.values():
            product_list = []
            for prod in pkg['products'].values():
                product_list.append(prod)
            finish_packages.append({
                'name': pkg['name'],
                'id': pkg['package_id'],
                'products': product_list,
                'lines': pkg['lines'],  # Bổ sung thông tin các move line cho package
            })
        unpacked_move_lines = finisheds.move_line_ids.filtered(lambda ml: not ml.result_package_id)
        unpacked_products = []
        for mv in finisheds:
            total_finished_qty = mv.product_uom_qty or 0.0
            # Hoặc có thể xài move.quantity (tuỳ code cũ)
            
            # Tính tổng quantity đã được đóng gói (có result_package_id)
            packed_lines = mv.move_line_ids.filtered(lambda ml: ml.result_package_id)
            
            total_packed_qty = sum(packed_lines.mapped('quantity'))

            available_qty = total_finished_qty - total_packed_qty
            if available_qty > 0:
                # Gom thông tin cho form "đóng gói"
                # Gắn kèm move_id, product tracking, location... tuỳ ý
                product_data = {
                    'move_id': mv.id,
                    'product_id': mv.product_id.id,
                    'product_name': mv.product_id.display_name or '',
                    'product_tracking': mv.product_id.tracking,
                    'location_id': mv.location_id.id,
                    'location_dest_id': mv.location_dest_id.id,
                    'available_quantity': available_qty,
                    # Tuỳ logic: 
                    #   - Mặc định 'qtyPerPackage' = 0 (người dùng sẽ nhập)
                    #   - 'packageCount' = 0 
                }
                unpacked_products.append(product_data)

       


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
            'finish_packages': finish_packages,
            'unpacked_moves':unpacked_products,
            'unpacked_move_lines':unpacked_move_lines.read(order._get_fields('stock.move.line')),
            'pre_production_packages':pre_production_packages.read(order._get_fields('stock.quant')),
            'state':order.state,
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
        
    def create_production_return(self, production_id, quants, print_lable=False):
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
                if print_lable:
                    printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name', 'like', 'ZTC-ZD230-203dpi-ZPL')], limit=1)
                    label = self.env['printing.label.zpl2']
                    label.print_label_auto(printer, line)

            # Xác nhận picking để thực hiện chuyển kho
            picking.action_confirm()
            picking.action_assign()
            picking.button_validate()
        return self.get_data(production_id)

    def write(self, vals):
        """
        Khi MO thay đổi state, qty_producing, date_start/date_deadline/date_finished...
        => ta tự động cập nhật Request liên quan.
        """
        res = super().write(vals)

        # Kiểm tra xem các field quan trọng có bị thay đổi không
        fields_trigger = {'state','qty_producing','qty_produced',
                          'date_start','date_deadline','date_finished'}
        if any(f in vals for f in fields_trigger):
            # Lấy tất cả request liên quan
            requests = self.mapped('production_request_id')
            if requests:
                requests._update_from_mos()

        return res

    def action_confirm(self):
        super().action_confirm()
        self.write({'date_start':datetime.now()})

    def multi_create_activities(self):
        """
        Khi chọn nhiều production order, hàm sẽ kiểm tra:
        - Nếu workorder nào pack_method != 'external_list' => tạo activity luôn (tương tự action_create_activities).
        - Nếu workorder có pack_method = 'external_list' => tự sinh external_data với package mặc định,
          rồi gọi create_activities(external_data=...) mà không mở wizard.
        """

        for production in self:
            # Xác định các WO dạng external_list
            wos_external = production.workorder_ids.filtered(
                lambda w: w.operation_id and w.operation_id.pack_method == 'external_list'
            )

            if wos_external:
                # Build external_data giống logic wizard action_confirm
                external_data = {}
                for wo in wos_external:
                    bom = wo.production_id.bom_id
                    if not bom:
                        continue

                    # Lặp BOM components, kiểm tra component nào thuộc operation này
                    for comp in bom.components_ids:
                        if wo.operation_id.id not in comp.operations_ids.ids:
                            continue
                        comp_quantity = (production.product_qty / (bom.product_qty or 1.0)) * comp.quantity
                        if comp_quantity <= 0:
                            continue

                        # Ở đây ta mặc định pack_quantity = 1, rồi chia ra số package
                        pack_quantity = 1.0
                        num_packages = int(math.ceil(comp_quantity / pack_quantity))
                        
                        # Tên WO, Component (viết gọn, có thể bỏ dấu...)
                        wo_name = wo.display_name or 'WO'
                        comp_name = comp.name or 'COMP'
                        
                        package_names = []
                        for i in range(1, num_packages + 1):
                            pkg_name = f"{wo_name}-{comp_name}-{i}"
                            package_names.append(pkg_name)

                        list_package_tuples = [(pkg, pack_quantity) for pkg in package_names]
                        external_data.setdefault(wo.id, {})[comp.id] = list_package_tuples

                # Sau khi có external_data, gọi create_activities cho nhóm WO external
                wos_external.create_activities(external_data=external_data)

                # Ngoài các WO external_list, nếu có WO khác (pack_method khác),
                # bạn vẫn muốn gọi create_activities() cho chúng:
                wos_non_external = production.workorder_ids - wos_external
                if wos_non_external:
                    wos_non_external.create_activities()
            else:
                # Nếu không có WO external_list nào => giống như action_create_activities
                production.workorder_ids.create_activities()

        # Kết thúc
        return True

    def action_production_activities(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_mrp_production_2_smartbiz_mes_production_activity")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_id=self.id))
        action['context'] = context
        action['domain'] = [('production_id', '=', self.id)]

        return action

    def action_production_packages(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_mes.act_mrp_production_2_smartbiz_mes_package")
        context = eval(action['context'])
        context.update(dict(self._context,default_production_id=self.id))
        action['context'] = context
        action['domain'] = [('production_id', '=', self.id)]

        return action

    @api.onchange('production_line_id')
    def _onchange_production_line_id(self):
        for record in self:
            if record.production_line_id:
                record.picking_type_id = record.production_line_id.picking_type_id

class mrp_Workcenter(models.Model):
    _inherit = ['mrp.workcenter']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    equipment_quantity = fields.Integer(string='Equipment Quantity')


class mrp_Workorder(models.Model):
    _inherit = ['mrp.workorder']
    production_activity_ids = fields.One2many('smartbiz_mes.production_activity', 'work_order_id')
    name = fields.Char(store='True')


    def get_orders(self,domain):
        orders = self.search(domain)
        users = self.env['res.users'].search([]).read(['name','barcode','workcenter_id','production_line_id','employee_id'], load=False)
        employees = self.env['hr.employee'].search([]).read(['name','barcode'], load=False)
        order_data = []
        for order in orders:
            order_data.append({
                'id':order.id,
                'name':order.name,
                'production_id':order.production_id.id,
                'production_name':order.production_id.name,
                'product_id':order.product_id.id,
                'workcenter_id':order.workcenter_id.id,
                'product_name':order.product_id.name,
                'quantity':order.qty_production,
                'state':order.state
            })
        data = {
            'orders':order_data,
            'users':users,
            'employees':employees
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
                cancel_quantity = 0
                producing_ok_quantity = 0
                producing_ng_quantity = 0
                producing_cancel_quantity = 0
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
                        'finish':pa.finish,
                        'note':pa.note,
                        'reason': pa.reason_id.name,
                        'activity_type':pa.activity_type
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
                    elif pa.activity_type == 'cancel':
                        cancel_quantity += pa.quantity
                        
                lot_id =  order.production_id.lot_producing_id.id       
                lot_name =  order.production_id.lot_producing_id.name
                producing_quantity = producing_ok_quantity + producing_ng_quantity
                produced_quantity = ok_quantity + ng_quantity + cancel_quantity
                remain_quantity = quantity - (producing_quantity + produced_quantity )
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
                    'cancel_quantity':cancel_quantity,
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
    
    def cancel_activity(self,workorder_id,production_activity):        
        activity = self.env['smartbiz_mes.production_activity'].browse(production_activity)
        now = fields.Datetime.now()
        activity.write({
            'activity_type':'cancel',
            'start': now,
            'finish': now,
            'status':'cancel'
            })
        
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
        user_id = component['user_id']
        now = fields.Datetime.now()
        producing_ok_quantity = component['producing_ok_quantity']
        producing_ng_quantity = component['producing_ng_quantity']

        if type == 'ok_action':
            if processing_ok:
                processing_ok.write({'quantity':producing_ok_quantity,'finish':now})
            else:
                processing_ok.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ok_quantity,'start':now,'finish':now,'quality':1,'user_id':user_id})
        if type == 'ng_action':
            if processing_ng:
                processing_ng.write({'quantity':producing_ng_quantity,'finish':now})
            else:
                processing_ng.create({'work_order_id':work_order_id,'component_id':component_id,'quantity':producing_ng_quantity,'start':now,'finish':now,'quality':0.8,'user_id':user_id})

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

    def lock_package_new(self, pkg, workorder, bom_component, force=False, mode='start'):
        """
        Chỉ dùng start_dependency của operation hiện tại để quyết định cho 'start' hoặc 'finish' công đoạn này.

        Tham số:
          - pkg: record smartbiz_mes.package
          - workorder: record mrp.workorder
          - bom_component: record smartbiz_mes.bom_components
          - force: True => cho qua nếu vi phạm
          - mode: 'start' hoặc 'finish' => ta sẽ xét 'start_to_...' hay 'finish_to_...' tương ứng

        Các check:
          1) pkg.production_id == workorder.production_id (nếu pkg.production_id tồn tại)
          2) Dựa vào start_dependency => tìm operation trước => kiểm tra activity
        """

        # 1) Check production_id
        if pkg.production_id and pkg.production_id != workorder.production_id:
            # Nếu pkg.production_id rỗng => ta set
            raise UserError(_(
                "Package '%s' (thuộc MO '%s') không trùng với MO '%s'. Không được phép scan."
            ) % (pkg.name, pkg.production_id.name, workorder.production_id.name))
        elif not pkg.production_id:
            # Nếu bạn muốn auto gán production_id khi nó trống
            pkg.write({'production_id': workorder.production_id.id})

        operation = workorder.operation_id
        if not operation:
            # Không có operation => coi như không ràng buộc => pass
            return

        dependency = operation.start_dependency or 'none'
        if dependency == 'none':
            return  # Không có ràng buộc => pass

        # Tìm công đoạn trước
        routing_ops = operation.bom_id.operation_ids.sorted(key=lambda op: op.sequence)
        ops_list = list(routing_ops)  # Chuyển sang list
        if operation not in routing_ops:
            # Trường hợp hiếm => op ko thuộc routing => pass
            return
        idx = ops_list.index(operation)  # Lúc này sẽ không báo AttributeError nữa
        if idx <= 0:
            # Công đoạn đầu => không có op trước => pass
            return
        prev_op = routing_ops[idx - 1]

        # Tìm workorder của công đoạn trước
        prev_wo = self.env['mrp.workorder'].search([
            ('operation_id', '=', prev_op.id),
            ('production_id', '=', workorder.production_id.id),
            ('state', '!=', 'cancel'),
        ], limit=1)
        if not prev_wo:
            # Không có WO trước => pass
            return

        # Tìm activity package ở prev_wo
        Activity = self.env['smartbiz_mes.production_activity']
        acts_prev = Activity.search([
            ('work_order_id', '=', prev_wo.id),
            ('package_id', '=', pkg.id),
        ])

        # ----------------------------
        # Xác định logic
        # ----------------------------
        if mode == 'start':
            # => finish_to_start / start_to_start
            if dependency == 'finish_to_start':
                # Muốn START công đoạn này => prev_op phải finish => cấm acts_open
                open_acts = acts_prev.filtered(lambda a: not a.finish)
                if open_acts and not force:
                    raise UserError(_(
                        "Package '%s' chưa FINISH ở công đoạn trước (%s). "
                        "start_dependency='finish_to_start' => cấm START công đoạn này."
                    ) % (pkg.name, prev_op.name))

            elif dependency == 'start_to_start':
                # Muốn START => prev_op phải start => cần ít nhất 1 activity có .start
                if not any(a.start for a in acts_prev) and not force:
                    raise UserError(_(
                        "Package '%s' chưa START ở công đoạn trước (%s). "
                        "start_dependency='start_to_start' => cấm START công đoạn này."
                    ) % (pkg.name, prev_op.name))

            # mode='start' => start_to_finish, finish_to_finish => không áp dụng
            # (vì 2 kiểu đó ràng buộc khi FINISH công đoạn này)

        elif mode == 'finish':
            # => start_to_finish / finish_to_finish
            if dependency == 'start_to_finish':
                # Muốn FINISH công đoạn này => prev_op phải START
                # => acts_prev phải có .start
                if not any(a.start for a in acts_prev) and not force:
                    raise UserError(_(
                        "start_dependency='start_to_finish':\n"
                        "Không thể FINISH gói '%s' ở công đoạn này vì công đoạn trước (%s) chưa START gói."
                    ) % (pkg.name, prev_op.name))

            elif dependency == 'finish_to_finish':
                # Muốn FINISH => prev_op phải FINISH => acts_prev không được còn act_open
                open_acts = acts_prev.filtered(lambda a: not a.finish)
                if open_acts and not force:
                    raise UserError(_(
                        "start_dependency='finish_to_finish':\n"
                        "Không thể FINISH gói '%s' vì công đoạn trước (%s) chưa FINISH xong."
                    ) % (pkg.name, prev_op.name))

            # finish_to_start, start_to_start => không áp dụng cho giai đoạn FINISH
            # (chúng áp dụng cho START)

        # Done. Nếu qua hết => pass.
        return

    @api.model
    def handle_package_scan(self, workorder_id, component_id, qr_code, employee_id,
                            button_type=False, force=False, quantity=None, ng_qty=None, note=None,reason_id=None):

        if not workorder_id or not component_id:
            raise UserError(_("workorder_id và component_id là bắt buộc."))

        workorder = self.env['mrp.workorder'].browse(workorder_id)
        if not workorder:
            raise UserError(_("WorkOrder ID=%s không tồn tại!") % workorder_id)

        bom_component = self.env['smartbiz_mes.bom_components'].browse(component_id)
        if not bom_component:
            raise UserError(_("Component ID=%s không tồn tại!") % component_id)

        final_quantity = quantity if quantity is not None else (bom_component.package_quantity or 1.0)
        Activity = self.env['smartbiz_mes.production_activity']
        ng_qty     = ng_qty if ng_qty is not None else 0.0
        Package = self.env['smartbiz_mes.package']
        now = fields.Datetime.now()


        def lock_package_with_mode(pkg, is_finish=False):
            """
            - is_finish=False => mode='start'
            - is_finish=True  => mode='finish'
            """
            mode = 'finish' if is_finish else 'start'
            self.lock_package_new(pkg, workorder, bom_component, force=force, mode=mode)

        def _close_paused_open():
            paused_open = Activity.search([
                ('work_order_id', '=', workorder.id),
                ('component_id',  '=', bom_component.id),
                ('activity_type', '=', 'paused'),
                ('finish', '=', False)
            ])
            if paused_open:
                paused_open.write({'finish': now})

        if not qr_code and button_type:
            _close_paused_open()  
            if button_type == 'ok_action':
                

                ok_open = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', bom_component.id),
                    ('quality', '>=', 0.9),
                    ('finish', '=', False),
                ], limit=1)
                quantity = quantity if quantity else ok_open.quantity
                if ok_open:
                    if ok_open.quantity > quantity:
                        Activity.create({
                            'work_order_id': workorder.id,
                            'component_id':  bom_component.id,
                            'workcenter_id':  workorder.workcenter_id.id,
                            'quantity':      ok_open.quantity - quantity,
                            'package_id': ok_open.package_id.id,
                            'quality':       1,
                            'start':         False,
                            'finish':        False,
                            'employee_id':   employee_id,
                            'shift_id': workorder.production_id.shift_id.id,
                            'product_id': workorder.production_id.product_id.id,
                            'activity_type': 'ok',
                            'reason_id':     False,
                            'note':          '',
                        })
                    if ok_open.start:
                        ok_open.write({'finish': now, 'quantity': quantity})
                    else:
                        ok_open.write({'start': now,'finish': now, 'quantity': quantity})

                               
                                 
                    pkg = ok_open.package_id
                    lock_package_with_mode(pkg, is_finish=True)  # start_dependency check
                    
                                      
                                                   
                      
                    pkg.write({
                        'current_step': workorder.operation_id.name or '',
                        'current_component_id': False,
                        'last_qty': ok_open.quantity,
                        'current_workorder_id': False,
                    })
                else:
                    # -> Tạo package + activity => 
                    #   vì code gốc finish ngay => ta lock với_mode(is_finish=True) 
                    mo_name = remove_accents_and_upper(workorder.production_id.name or "MO")
                    comp_name = remove_accents_and_upper(bom_component.name or f"COMP-{bom_component.id}")
                    package_name = f"OK-{mo_name}-{comp_name}"
                    new_pkg = Package.create({
                        'name': package_name,
                        'current_step': workorder.operation_id.name or '',
                        'current_component_id': bom_component.id,
                        'last_qty': final_quantity,
                        'current_workorder_id': workorder.id,
                        'production_id': workorder.production_id.id
                    })
                    lock_package_with_mode(new_pkg, is_finish=True) 
                    Activity.create({
                        'work_order_id': workorder.id,
                        'component_id': bom_component.id,
                        'package_id': new_pkg.id,
                        'start': now,
                        'finish': now,
                        'quantity': final_quantity,
                        'quality': 1,
                        'employee_id': employee_id,
                        'shift_id': workorder.production_id.shift_id.id,
                        'product_id': workorder.production_id.product_id.id,
                        'activity_type': 'ok',
                    })
              
                                                     

                data = self.get_data(workorder.id)
                # Kiểm tra finish_workorder
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder.id)
                else:
                    self.start_workorder(workorder.id)
                return data
            if button_type == 'start_action':
                ok_open = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', bom_component.id),
                    ('quality', '>=', 0.9),
                    ('finish', '=', False),
                    ('start', '=', False),
                ], limit=1)
                if ok_open:
                    ok_open.write({'start': now})
                data = self.get_data(workorder.id)
                # check finish
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder.id)
                else:
                    self.start_workorder(workorder.id)
                return data
            
            if button_type == 'ng_action':
                                     
                act_ng = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', bom_component.id),
                    ('quality', '<', 0.9),
                ], limit=1)
                if act_ng and not act_ng.finish:
                    # => finish
                    pkg = act_ng.package_id
                    lock_package_with_mode(pkg, is_finish=True)
                    new_qty = act_ng.quantity + ng_qty 
                    act_ng.write({
                        'finish': now,
                        'quantity': new_qty,
                        'finish': now,
                    })
                else:
                    # Tạo package => finish luôn
                    mo_name = remove_accents_and_upper(workorder.production_id.name or "MO")
                    comp_name = remove_accents_and_upper(bom_component.name or f"COMP-{bom_component.id}")
                    package_name = f"NG-{mo_name}-{comp_name}"
                    new_pkg = Package.create({
                        'name': package_name,
                        'current_step': workorder.operation_id.name or '',
                        'current_component_id': bom_component.id,
                        'last_qty': final_quantity,
                        'current_workorder_id': workorder.id,
                        'production_id': workorder.production_id.id
                    })
                    lock_package_with_mode(new_pkg, is_finish=True)
                    Activity.create({
                        'work_order_id': workorder.id,
                        'component_id': bom_component.id,
                        'package_id': new_pkg.id,
                        'start': now,
                        'finish': now,
                        'quantity': ng_qty,
                        'quality': 0.8,
                        'employee_id': employee_id,
                        'shift_id': workorder.production_id.shift_id.id,
                        'product_id': workorder.production_id.product_id.id,
                        'activity_type': 'ng',
                        'reason_id':     reason_id,
                        'note':          note,
                    })
                # Trừ OK
                act_ok_open = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', bom_component.id),
                    ('quality', '>=', 0.9),
                    ('finish', '=', False),
                ], limit=1)
                if act_ok_open:
                    if act_ok_open.quantity < ng_qty and not force:
                        raise UserError(_("OK còn %.2f, không đủ trừ %.2f => force=True.") 
                                        % (act_ok_open.quantity, ng_qty))
                    act_ok_open.write({'quantity': act_ok_open.quantity - ng_qty})

                data = self.get_data(workorder.id)
                # check finish
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder.id)
                else:
                    self.start_workorder(workorder.id)
                return data

            if button_type == 'pause_action':
                ok_open = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id',  '=', bom_component.id),
                    ('quality', '>', 0.9),
                    ('activity_type', '!=', 'paused'),
                    ('finish', '=', False)
                ], limit=1)
                quantity = quantity if quantity else ok_open.quantity
                if ok_open:
                    if ok_open.quantity > quantity:
                        Activity.create({
                            'work_order_id': workorder.id,
                            'component_id':  bom_component.id,
                            'workcenter_id':  workorder.workcenter_id.id,
                            'quantity':      ok_open.quantity - quantity,
                            'package_id': ok_open.package_id.id,
                            'quality':       1,
                            'start':         False,
                            'finish':        False,
                            'employee_id':   employee_id,
                            'shift_id': workorder.production_id.shift_id.id,
                            'product_id': workorder.production_id.product_id.id,
                            'activity_type': 'ok',
                            'reason_id':     False,
                            'note':          '',
                        })
                    if ok_open.start:
                        ok_open.write({'finish': now, 'quantity': quantity})
                    else:
                        ok_open.write({'start': now,'finish': now, 'quantity': quantity})

                if ng_qty:
                    Activity.create({
                        'work_order_id': workorder.id,
                        'component_id':  bom_component.id,
                        'workcenter_id':  workorder.workcenter_id.id,
                        'quantity':      ng_qty,
                        'quality':       0.8,
                        'start':         now,
                        'finish':        now,
                        'employee_id':   employee_id,
                        'shift_id': workorder.production_id.shift_id.id,
                        'product_id': workorder.production_id.product_id.id,
                        'activity_type': 'ng',
                        'reason_id':     reason_id,
                        'note':          note or _('NG khi Pause'),
                    })

                # activity “pause” để log
                Activity.create({
                    'work_order_id': workorder.id,
                    'component_id':  bom_component.id,
                    'workcenter_id':  workorder.workcenter_id.id,
                    'quantity':      0,
                    'quality':       1,
                    'start':         now,
                    'employee_id':   employee_id,
                    'shift_id': workorder.production_id.shift_id.id,
                    'product_id': workorder.production_id.product_id.id,
                    'activity_type': 'paused',
                    'reason_id':     reason_id,
                    'note':          note,
                })
                data = self.get_data(workorder.id)
                # check finish
                workorder_remain = sum(c['remain_quantity'] for c in data['components'])
                workorder_producing = sum(c['producing_quantity'] for c in data['components'])
                if not workorder_remain and not workorder_producing:
                    self.finish_workorder(workorder.id)
                else:
                    self.start_workorder(workorder.id)
                return data

        if not qr_code.startswith("OK") and not qr_code.startswith("NG") and not button_type:
            _close_paused_open()  
            package = Package.search([('name', '=', qr_code)], limit=1)
            if not package:
                raise UserError("Số serial %s không có trong lệnh!" % qr_code)
            else:
                # Tùy logic, final_quantity <= package.last_qty?
                final_quantity = min(final_quantity, package.last_qty)

            #lock_package(package, workorder.id, bom_component.id)

            act_ok_open = Activity.search([
                ('work_order_id', '=', workorder.id),
                ('component_id', '=', bom_component.id,),
                ('package_id', '=', package.id),
                ('quality', '>=', 0.9),
                ('finish', '=', False),
            ], limit=1)

            if act_ok_open:
                act_ok_open.write({
                    'start':now,
                    'finish': now,
                    # 'quantity': final_quantity, # Tùy logic, có thể ghi đè
                })
    
            data = self.get_data(workorder_id)

        if qr_code.startswith("OK"):
            _close_paused_open()  
            package = Package.search([('name', '=', qr_code)], limit=1)
            if not package:
                package = Package.create({
                    'name': qr_code,
                    'current_step': workorder.operation_id.name or '',
                    'current_component_id': bom_component.id,
                    'last_qty': final_quantity,
                    'production_id': workorder.production_id.id
                })

            act_ok_open = Activity.search([
                ('work_order_id', '=', workorder.id),
                ('component_id', '=', bom_component.id),
                ('package_id', '=', package.id),
                ('quality', '>=', 0.9),
                ('finish', '=', False),
            ], limit=1)
            if act_ok_open:
                if not act_ok_open.start:
                    # => "bắt đầu"
                    lock_package_with_mode(package, is_finish=False) # mode='start'
                    act_ok_open.write({
                        'start': now,
                        'employee_id': employee_id,
                    })
                else:
                    # => "kết thúc"
                    lock_package_with_mode(package, is_finish=True)  # mode='finish'
                    time_spent = (now - act_ok_open.start).total_seconds() / 60.0
                    if time_spent < 0.1 and not force:
                        raise UserError(_("Thời gian quá ngắn (%.2f phút). force=True để bỏ qua.") % time_spent)
                    act_ok_open.write({'finish': now})
                    package.write({
                        'current_step': workorder.operation_id.name or '',
                        'current_component_id': bom_component.id,
                        'last_qty': act_ok_open.quantity,
                        'current_workorder_id': False,
                    })
            else:
                # => Chưa có activity => "bắt đầu" mới
                act_ok_done = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', bom_component.id),
                    ('package_id', '=', package.id),
                    ('quality', '>=', 0.9),
                    ('finish', '!=', False),
                ], limit=1)
                if act_ok_done and not force:
                    raise UserError(_(
                        "Package '%s' đã hoàn thành trước đó. force=True nếu muốn làm lại."
                    ) % qr_code)

                lock_package_with_mode(package, is_finish=False) # => start
                new_act_ok = Activity.create({
                    'work_order_id': workorder.id,
                    'component_id': bom_component.id,
                    'package_id': package.id,
                    'start': now,
                    'quantity': final_quantity,
                    'quality': 1,
                    'employee_id': employee_id,
                    'shift_id': workorder.production_id.shift_id.id,
                    'product_id': workorder.production_id.product_id.id,
                    'activity_type': 'ok',
                })
                package.write({
                    'current_step': workorder.operation_id.name or '',
                    'current_component_id': bom_component.id,
                    'last_qty': final_quantity,
                    'current_workorder_id': workorder.id,
                })

            data = self.get_data(workorder.id)
            workorder_remain = sum(c['remain_quantity'] for c in data['components'])
            workorder_producing = sum(c['producing_quantity'] for c in data['components'])
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(workorder.id)
            else:
                self.start_workorder(workorder.id)
            return data

        if qr_code.startswith("NG"):
            _close_paused_open()  
            final_qty = quantity if quantity is not None else 1
            package = Package.search([('name', '=', qr_code)], limit=1)
            if not package:
                package = Package.create({
                    'name': qr_code,
                    'current_step': workorder.operation_id.name or '',
                    'current_component_id': bom_component.id,
                    'last_qty': 0.0,
                    'production_id': workorder.production_id.id
                })

            # Quét NG => code gốc finish luôn => => lock_package_with_mode(..., is_finish=True)
            lock_package_with_mode(package, is_finish=True) 

            act_ng = Activity.search([
                ('work_order_id','=', workorder.id),
                ('component_id','=', bom_component.id),
                ('package_id','=', package.id),
                ('quality','<', 0.9),
            ], limit=1, order='id asc')

            old_ng_qty = act_ng.quantity if act_ng else 0.0
            if not act_ng:
                act_ng = Activity.create({
                    'work_order_id': workorder.id,
                    'component_id': bom_component.id,
                    'package_id': package.id,
                    'start': now,
                    'quantity': 0.0,
                    'quality': 0.8,
                    'employee_id': employee_id,
                    'shift_id': workorder.production_id.shift_id.id,
                    'product_id': workorder.production_id.product_id.id,
                    'activity_type': 'ng',
                    'reason_id':     reason_id,
                    'note':          note,
                })
            else:
                if act_ng.finish and not force:
                    raise UserError(_("Activity NG đã finish => force=True để cập nhật."))

            new_ng_qty = old_ng_qty + ng_qty
            act_ng.write({
                'finish': now,
                'quantity': new_ng_qty,
            })
            # Trừ OK
            act_ok_open = Activity.search([
                ('work_order_id','=', workorder.id),
                ('component_id','=', bom_component.id),
                ('quality','>=',0.9),
                ('finish','=',False),
            ], limit=1, order='create_date desc')
            if not act_ok_open and not force:
                raise UserError(_("Không có OK để trừ => force=True."))
            elif act_ok_open:
                if act_ok_open.quantity < ng_qty and not force:
                    raise UserError(_("OK có %.2f, không đủ => force=True.") % act_ok_open.quantity)
                act_ok_open.write({'quantity': act_ok_open.quantity - ng_qty})

            package.write({
                'current_step': workorder.operation_id.name or '',
                'current_component_id': bom_component.id,
                'last_qty': new_ng_qty,
                'current_workorder_id': False,
            })

            data = self.get_data(workorder.id)
            workorder_remain = sum(c['remain_quantity'] for c in data['components'])
            workorder_producing = sum(c['producing_quantity'] for c in data['components'])
            if not workorder_remain and not workorder_producing:
                self.finish_workorder(workorder.id)
            else:
                self.start_workorder(workorder.id)
            return data

        # Không rơi vào TH nào => return
        return self.get_data(workorder.id)
        
    def print_label(self,workorder_id,activity_id):
        self = self.sudo()
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like','ZTC-ZD230-203dpi-ZPL')],limit=1)
        pa = self.env['smartbiz_mes.production_activity'].browse(activity_id)    
        if pa:
            label = self.env['printing.label.zpl2']
            label.print_label_auto(printer, pa)      
        return self.get_data(workorder_id)
    
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

    def create_activities(self, external_data=None):
        if external_data is None:
            external_data = {}

        Package = self.env['smartbiz_mes.package']
        Activity = self.env['smartbiz_mes.production_activity']

        for workorder in self:
            bom = workorder.production_id.bom_id
            if not bom:
                continue

            operation = workorder.operation_id
            if not operation:
                continue

            pack_method = operation.pack_method or 'order'
            product_qty = workorder.production_id.product_qty
            bom_qty = bom.product_qty or 1.0
            mo_name = remove_accents_and_upper(workorder.production_id.name or "MO")
            wc_id = workorder.workcenter_id.id if workorder.workcenter_id else False

            # Lặp các component
            for comp in bom.components_ids:
                # Chỉ tạo hoạt động nếu operation có chứa comp
                if operation.id not in comp.operations_ids.ids:
                    continue

                # Kiểm tra nếu đã có activity (workorder + comp) thì bỏ qua (tuỳ nghiệp vụ)
                existing_act = Activity.search([
                    ('work_order_id', '=', workorder.id),
                    ('component_id', '=', comp.id),
                ], limit=1)
                if existing_act:
                    continue

                # Số lượng cần
                comp_quantity = (product_qty / bom_qty) * comp.quantity
                if comp_quantity <= 0:
                    continue

                if pack_method == 'order':
                    # Tạo 1 package + 1 activity
                    comp_name = remove_accents_and_upper(comp.name or f"COMP-{comp.id}")
                    package_name = f"OK-{mo_name}-{comp_name}"

                    existing_pkg = Package.search([('name', '=', package_name)], limit=1)
                    if existing_pkg:
                        pkg = existing_pkg
                    else:
                        pkg = Package.create({'name': package_name,'production_id':workorder.production_id.id})

                    Activity.create({
                        'work_order_id':  workorder.id,
                        'component_id':   comp.id,
                        'product_id':     workorder.production_id.product_id.id,
                        'workcenter_id':  wc_id,
                        'quantity':       comp_quantity,
                        'quality':        1.0,
                        'package_id':     pkg.id,
                        'shift_id':       workorder.production_id.shift_id.id,
                    })

                elif pack_method == 'order-component':
                    # Tạo nhiều package + activity, mỗi cái quantity=comp.package_quantity (trừ cuối)
                    remaining_qty = comp_quantity
                    index = 1
                    while remaining_qty > 0:
                        activity_qty = min(comp.package_quantity, remaining_qty) if comp.package_quantity else remaining_qty

                        comp_name = remove_accents_and_upper(comp.name or f"COMP-{comp.id}")
                        package_name = f"OK-{mo_name}-{comp_name}-{index}"

                        existing_pkg = Package.search([('name', '=', package_name)], limit=1)
                        if existing_pkg:
                            pkg = existing_pkg
                        else:
                            pkg = Package.create({'name': package_name,'production_id':workorder.production_id.id})

                        Activity.create({
                            'work_order_id':  workorder.id,
                            'component_id':   comp.id,
                            'product_id':     workorder.production_id.product_id.id,
                            'workcenter_id':  wc_id,
                            'quantity':       activity_qty,
                            'quality':        1.0,
                            'package_id':     pkg.id,
                            'shift_id':       workorder.production_id.shift_id.id,
                        })

                        remaining_qty -= activity_qty
                        index += 1

                elif pack_method == 'external_list':
                    # Dựa vào external_data
                    comp_data = external_data.get(workorder.id, {}).get(comp.id, [])
                    if not comp_data:
                        # Không có dữ liệu wizard -> bỏ qua (hoặc raise tùy ý)
                        continue

                    for (pkg_name, pkg_qty) in comp_data:
                        existing_pkg = Package.search([('name', '=', pkg_name)], limit=1)
                        if existing_pkg:
                            pkg = existing_pkg
                        else:
                            pkg = Package.create({'name': pkg_name,'production_id':workorder.production_id.id})

                        Activity.create({
                            'work_order_id':  workorder.id,
                            'component_id':   comp.id,
                            'product_id':     workorder.production_id.product_id.id,
                            'workcenter_id':  wc_id,
                            'quantity':       pkg_qty,
                            'quality':        1.0,
                            'package_id':     pkg.id,
                            'shift_id':       workorder.production_id.shift_id.id,
                        })

                else:
                    # Nếu pack_method không xác định thì xử lý như 'order' (hoặc tuỳ ý)
                    comp_name = remove_accents_and_upper(comp.name or f"COMP-{comp.id}")
                    package_name = f"OK-{mo_name}-{comp_name}"

                    existing_pkg = Package.search([('name', '=', package_name)], limit=1)
                    if existing_pkg:
                        pkg = existing_pkg
                    else:
                        pkg = Package.create({'name': package_name,'production_id':workorder.production_id.id})

                    Activity.create({
                        'work_order_id':  workorder.id,
                        'component_id':   comp.id,
                        'product_id':     workorder.production_id.product_id.id,
                        'workcenter_id':  wc_id,
                        'quantity':       comp_quantity,
                        'quality':        1.0,
                        'package_id':     pkg.id,
                        'shift_id':       workorder.production_id.shift_id.id,
                    })

    def print_activities(self,code_print = 'all'):
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like','ZTC-ZD230-203dpi-ZPL')],limit=1)
        label = self.env['printing.label.zpl2']
        for record in self:
            production_activity = record.production_activity_ids.filtered(lambda a: a.work_order_id.operation_id.print_label)
            if code_print != 'all':
                production_activity = production_activity.filtered(lambda a: a.work_order_id.operation_id.print_label == code_print)
            for act in production_activity:
                label.print_label_auto(printer, act)

class mrp_BoM(models.Model):
    _inherit = ['mrp.bom']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'bom_id')


class mrp_bomline(models.Model):
    _inherit = ['mrp.bom.line']
    components_ids = fields.One2many('smartbiz_mes.bom_components', 'material_id')


class mrp_routingworkcenter(models.Model):
    _inherit = ['mrp.routing.workcenter']
    components_ids = fields.Many2many('smartbiz_mes.bom_components', 'routing_bom_components_rel1', 'components_ids', 'operations_ids', string='Components')
    pack_method = fields.Selection([('order','Order'),('order-component','Order-Component'),('external_list','External List'),], string='Pack Method')
    duration_check_method = fields.Selection([('estimated_duration','Estimated Duration'),('no_check','No Check'),], string='Duration Check Method')
    deviation = fields.Float(string='Deviation')
    print_label = fields.Char(string='Print Label')
    start_dependency = fields.Selection([('none','None'),('start_to_start','Start to Start'),('start_to_finish','Start to Finish'),('finish_to_start','Finish to Start'),('finish_to_finish','Finish to Finish'),], string='Start Dependency', default = 'none')


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
    current_workorder_id = fields.Many2one('mrp.workorder', string='Current Workorder')
    production_id = fields.Many2one('mrp.production', string='Production')


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
    production_lines_ids = fields.One2many('smartbiz_mes.production_line', 'factory_id')


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
    product_id = fields.Many2one('product.product', string='Product')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Workcenter', index=True)
    work_order_id = fields.Many2one('mrp.workorder', string='Work Order', index=True)
    shift_id = fields.Many2one('smartbiz_mes.shift', string='Shift')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    component_id = fields.Many2one('smartbiz_mes.bom_components', string='Component', index=True)
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    quantity = fields.Float(string='Quantity')
    quality = fields.Float(string='Quality')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('smartbiz_mes.package', string='Package')
    start = fields.Datetime(string='Start')
    finish = fields.Datetime(string='Finish')
    duration = fields.Float(string='Duration', compute='_compute_duration', store=True)
    status = fields.Selection([('new','New'),('started','Started'),('paused','Paused'),('finished','Finished'),('cancel','Cancel'),], string='Status', compute='_compute_status', store=True, default = 'new')
    note = fields.Text(string='Note')
    reason_id = fields.Many2one('smartbiz_mes.pause_reason', string='Reason')
    activity_type = fields.Selection([('ok','OK'),('ng','NG'),('paused','Paused'),('cancel','Cancel'),], string='Activity Type', default = 'ok')
    production_id = fields.Many2one('mrp.production', string='Production', compute='_compute_production_id', store=True)


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

    @api.depends('start', 'finish')
    def _compute_status(self):
        for record in self:
            if record.start and record.finish:
                record.status = 'finished'
            elif record.start and not record.finish:
                record.status = 'started'
            elif record.activity_type == 'cancel':
                record.status = 'cancel'
            elif record.activity_type == 'paused':
                record.status = 'paused'
            else:
                record.status = 'new'

    @api.depends('work_order_id')
    def _compute_production_id(self):
        for record in self:
            if record.work_order_id:
                record.production_id = record.work_order_id.production_id
            else:
                record.production_id = False

    @api.model
    def auto_close_open_activity(self):
        """
        - Chạy 5 phút một lần (cron bên dưới).
        - Với mọi activity chưa finish:
              + Nếu NOW không thuộc ca làm việc của Workorder
                --> kết thúc activity, rồi sinh 1 activity 'paused'
                   (reason = 'Tự đóng – Ngoài giờ')
        Ca làm việc xác định theo shift của MO.  Nếu WO không có shift
        --> bỏ qua (coi như làm 24/24).
        """
        now = fields.Datetime.now()

        # lấy reason mặc định
        reason = self.env.ref(
            'smartbiz_mes.reason_auto_close', raise_if_not_found=False)

        open_act = self.search([('finish', '=', False)])

        for act in open_act:
            wo = act.work_order_id
            shift = wo.production_id.shift_id
            if not shift:
                continue    # không có ca, bỏ qua

            # chuyển giờ hiện tại về tz của user (hoặc tz hệ thống)
            # để so sánh với giờ bắt đầu – kết thúc ca
            user_tz = self.env.user.tz or 'UTC'
            local_now = fields.Datetime.context_timestamp(self, now)\
                                       .astimezone(fields.pytz.timezone(user_tz))

            # Giờ trong ca
            start_hour = shift.hour_from          # ví dụ 8.0
            end_hour   = shift.hour_to            # ví dụ 17.0
            local_hour = local_now.hour + local_now.minute/60.0

            # Nếu đang ngoài ca
            if not (start_hour <= local_hour < end_hour):
                # kết thúc activity
                act.finish = now

                # sinh activity 'paused'
                self.create({
                    'work_order_id': wo.id,
                    'component_id':  act.component_id.id,
                    'quantity':      0,
                    'quality':       1,
                    'start':         now,
                    'activity_type': 'paused',
                    'reason_id':     reason and reason.id or False,
                    'note':          _('Auto pause – Outside shift'),
                })

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


class smartbiz_mes_ProductionLineType(models.Model):
    _name = "smartbiz_mes.production_line_type"
    _description = "Production Line Type"
    name = fields.Char(string='Name')


class smartbiz_mes_Shift(models.Model):
    _name = "smartbiz_mes.shift"
    _description = "Shift"
    name = fields.Char(string='Name')
    start = fields.Float(string='Start')
    end = fields.Float(string='End')


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
    processing_quantity = fields.Float(string='Processing Quantity', readonly=True)
    done_quantity = fields.Float(string='Done Quantity', readonly=True)
    remain_quantity = fields.Float(string='Remain Quantity', readonly=True)
    plan_start = fields.Datetime(string='Plan Start')
    plan_finish = fields.Datetime(string='Plan Finish')
    schedule_start = fields.Datetime(string='Schedule Start', readonly=True)
    schedule_finish = fields.Datetime(string='Schedule Finish', readonly=True)
    start = fields.Datetime(string='Start', readonly=True)
    finish = fields.Datetime(string='Finish', readonly=True)
    production_ids = fields.One2many('mrp.production', 'production_request_id')
    picking_ids = fields.One2many('stock.picking', 'production_request_id')
    purchase_ids = fields.One2many('purchase.order', 'production_request_id')
    move_ids = fields.One2many('stock.move', 'production_request_id')
    sub_request_ids = fields.One2many('smartbiz_mes.request', 'parent_request_id')
    sub_request = fields.Integer(string='Sub Request', compute='_compute_sub_request', store=True)
    production = fields.Integer(string='Production', compute='_compute_production', store=True)
    picking = fields.Integer(string='Picking', compute='_compute_picking', store=True)
    purchase = fields.Integer(string='Purchase', compute='_compute_purchase', store=True)
    move = fields.Integer(string='Move', compute='_compute_move', store=True)
    state = fields.Selection([('draft','Draft'),('confirmed','Confirmed'),('processing','Processing'),('done','Done'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    @api.depends('code', 'title')
    def _compute_name(self):
        for record in self:
            if record.parent_request_id:
                record.name = (record.parent_request_id.code or '') + '-' +  (record.code or '') + '-' + (record.title or '')
            else:
                record.name = (record.code or '') + '-' + (record.title or '')

    @api.depends('sub_request_ids')
    def _compute_sub_request(self):
        for record in self:
            count = record.sub_request_ids.search_count([('parent_request_id', '=', record.id)])
            record.sub_request = count

    @api.depends('production_ids')
    def _compute_production(self):
        for record in self:
            count = record.production_ids.search_count([('production_request_id', '=', record.id)])
            record.production = count

    @api.depends('picking_ids')
    def _compute_picking(self):
        for record in self:
            count = record.picking_ids.search_count([('production_request_id', '=', record.id)])
            record.picking = count

    @api.depends('purchase_ids')
    def _compute_purchase(self):
        for record in self:
            count = record.purchase_ids.search_count([('production_request_id', '=', record.id)])
            record.purchase = count  

    @api.depends('move_ids')
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

        
        
    def _update_from_mos(self):
        """
        Cập nhật số lượng, thời gian kế hoạch (schedule), thời gian thực tế (start/finish)
        và trạng thái của Request dựa trên MO liên kết. Chú ý: dùng 'quantity' thay cho 'qty_done'.
        """
        StockMoveLine = self.env['stock.move.line']
        for request in self:
            # Lọc MO chưa bị huỷ
            mos = request.production_ids.filtered(lambda m: m.state != 'cancel')

            # 1) Tính done_quantity và processing_quantity
            finished_moves = mos.mapped('move_finished_ids')

            # Tính done_data bằng 'quantity:sum'
            done_data = StockMoveLine.read_group(
                [('move_id', 'in', finished_moves.ids), ('state', '=', 'done')],
                ['quantity:sum'],
                []
            )
            total_done = done_data[0]['quantity'] if done_data else 0.0

            # Tính processing_data bằng 'quantity:sum' cho move line chưa done/cancel
            processing_data = StockMoveLine.read_group(
                [('move_id', 'in', finished_moves.ids), ('state', 'not in', ('done','cancel'))],
                ['quantity:sum'],
                []
            )
            total_processing = processing_data[0]['quantity'] if processing_data else 0.0

            remain_quantity = max(0.0, request.quantity - total_done)

            # 2) Tính 'schedule_start'/'schedule_finish' (kế hoạch) – ví dụ từ MO.plan_start / plan_finish
            valid_plan_starts = mos.filtered(lambda m: m.plan_start).mapped('plan_start')
            schedule_start = min(valid_plan_starts) if valid_plan_starts else False

            valid_plan_finishes = mos.filtered(lambda m: m.plan_finish).mapped('plan_finish')
            schedule_finish = max(valid_plan_finishes) if valid_plan_finishes else False

            # 3) Tính thời gian thực tế (start/finish)
            valid_actual_starts = mos.filtered(lambda m: m.date_start).mapped('date_start')
            actual_start = min(valid_actual_starts) if valid_actual_starts else False

            valid_actual_finishes = mos.filtered(lambda m: m.state == 'done' and m.date_finished).mapped('date_finished')
            actual_finish = max(valid_actual_finishes) if valid_actual_finishes else False

            # 4) Tính trạng thái Request
            state = request._compute_request_state_by_mos(mos)

            # 5) Ghi kết quả
            request.write({
                'done_quantity': total_done,
                'processing_quantity': total_processing,
                'remain_quantity': remain_quantity,
                'schedule_start': schedule_start,
                'schedule_finish': schedule_finish,
                'start': actual_start,
                'finish': actual_finish,
                'state': state,
            })

        # Cập nhật đệ quy cho Request cha
        self._cascade_update_to_parent()

    def _compute_request_state_by_mos(self, mos):
        """
        Xác định trạng thái Request dựa trên danh sách MO (đã lọc cancel).
        Logic như sau:
        - Nếu KHÔNG có MO => nếu Request đang ở draft/confirmed, giữ nguyên.
        Nếu Request đang ở (cancel, done, processing) thì giữ nguyên hay
        tùy nghiệp vụ. Ở ví dụ này, ta giả sử Request mới => 'draft'.
        - Nếu tất cả MO = done => Request done
        - Nếu có ít nhất 1 MO đang (progress, confirmed, waiting, ready...) => Request processing
        - Nếu không rơi vào đâu => 'confirmed' (VD: MO = draft chẳng hạn)
        Bạn điều chỉnh logic tùy ý.
        """
        self.ensure_one()

        # Nếu không có MO
        if not mos:
            # Nếu request đang ở 'draft' hoặc 'confirmed' => giữ nguyên (hoặc set 'draft')
            if self.state in ('draft', 'confirmed'):
                return self.state
            # Còn nếu state đang là cancel, done hay processing do cũ => bạn có thể
            # quyết định giữ nguyên hay set 'draft' tùy nghiệp vụ.
            # Ở đây tạm giữ nguyên:
            return self.state

        # Có MO => lấy trạng thái
        # 1) Tất cả MO done => request done
        if all(m.state == 'done' for m in mos):
            return 'done'
        # 2) Bất kỳ MO nào đang "tiến hành" => request processing
        if any(m.state in ('confirmed','progress','to_close','waiting','ready') for m in mos):
            return 'processing'
        # 3) Nếu không rơi vào 2 trên => ta coi là 'confirmed'
        return 'confirmed'

    def _cascade_update_to_parent(self):
        """
        Cập nhật lên Request cha bằng cách tổng hợp tất cả sub_request_ids.
        Gọi đệ quy đến khi không còn cha.
        """
        parents = self.mapped('parent_request_id').filtered(lambda r: r)
        if not parents:
            return

        for parent in parents:
            sub_requests = parent.sub_request_ids

            # Tính số lượng
            done_quantity = sum(sr.done_quantity for sr in sub_requests)
            processing_quantity = sum(sr.processing_quantity for sr in sub_requests)
            remain_quantity = max(0.0, parent.quantity - done_quantity)

            # Tính schedule
            valid_schedule_starts = [r.schedule_start for r in sub_requests if r.schedule_start]
            schedule_start = min(valid_schedule_starts) if valid_schedule_starts else False

            valid_schedule_finishes = [r.schedule_finish for r in sub_requests if r.schedule_finish]
            schedule_finish = max(valid_schedule_finishes) if valid_schedule_finishes else False

            # Thời gian thực tế
            valid_starts = [r.start for r in sub_requests if r.start]
            actual_start = min(valid_starts) if valid_starts else False

            valid_finishes = [r.finish for r in sub_requests if r.finish]
            actual_finish = max(valid_finishes) if valid_finishes else False

            # Tính trạng thái cha
            state = parent._compute_parent_state()

            parent.write({
                'done_quantity': done_quantity,
                'processing_quantity': processing_quantity,
                'remain_quantity': remain_quantity,
                'schedule_start': schedule_start,
                'schedule_finish': schedule_finish,
                'start': actual_start,
                'finish': actual_finish,
                'state': state,
            })

        # Đệ quy tiếp
        parents._cascade_update_to_parent()

    def _compute_parent_state(self):
        """
        Tính trạng thái của Request cha dựa trên trạng thái các con (sub_request_ids).
        
        Logic:
        1) Không có con => giữ nguyên state của cha (thường là draft hoặc confirmed).
        2) Nếu tất cả con 'cancel' => cha 'cancel'
        3) Nếu tất cả con in ('done','cancel') => cha 'done'
        4) Nếu có bất kỳ con 'processing' => cha 'processing'
        5) Nếu có bất kỳ con 'confirmed' => cha 'confirmed'
        6) Nếu có bất kỳ con 'draft' => cha 'draft'
        7) Còn lại => giữ nguyên hoặc draft, tùy ý
        """
        self.ensure_one()
        children = self.sub_request_ids
        if not children:
            # không có con => giữ nguyên
            return self.state

        states = children.mapped('state')

        # 1) Tất cả con cancel
        if all(st == 'cancel' for st in states):
            return 'cancel'
        # 2) Tất cả con done hoặc cancel => cha done
        if all(st in ('done','cancel') for st in states):
            return 'done'
        # 3) Có bất kỳ con 'processing'
        if any(st == 'processing' for st in states):
            return 'processing'
        # 4) Có bất kỳ con 'confirmed'
        if any(st == 'confirmed' for st in states):
            return 'confirmed'
        # 5) Có bất kỳ con 'draft'
        if any(st == 'draft' for st in states):
            return 'draft'

        # 6) nếu chưa rơi vào đâu => tạm giữ nguyên (hoặc bạn muốn gán 'draft')
        return self.state      

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

class smartbiz_mes_PauseReason(models.Model):
    _name = "smartbiz_mes.pause_reason"
    _description = "Pause Reason"
    name = fields.Char(string='Name')
    type = fields.Selection([('pause','Pause'),('ng','NG'),('cancel','Cancel'),], string='Type')
    active = fields.Boolean(string='Active', default = 'True')


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

class stock_moveline(models.Model):
    _inherit = ['stock.move.line']
    name = fields.Char(store='True')


    @api.model_create_multi
    def create(self, vals_list):
        move_lines = super(stock_moveline, self).create(vals_list)
        # Gọi trigger cập nhật theo batch để tránh gọi lặp lại nhiều lần
        move_lines._trigger_update_request(batch=True)
        return move_lines

    def write(self, vals):
        res = super(stock_moveline, self).write(vals)
        # Chỉ trigger nếu các trường quan trọng thay đổi
        if any(field in vals for field in ['state', 'quantity']):
            self._trigger_update_request(batch=True)
        return res

    def unlink(self):
        self._trigger_update_request(batch=True)
        return super(stock_moveline, self).unlink()

    def _trigger_update_request(self, batch=False):
        """
        Tìm các Request liên quan thông qua: move_id -> production_id -> production_request_id.
        Nếu batch=True, gom các Request và gọi cập nhật một lần.
        """
        requests_to_update = set()
        for move in self.mapped('move_id'):
            if move.production_id and move.production_id.production_request_id:
                requests_to_update.add(move.production_id.production_request_id.id)
        if batch:
            self.env['smartbiz_mes.request'].browse(list(requests_to_update))._update_from_mos()
        else:
            for request in self.env['smartbiz_mes.request'].browse(list(requests_to_update)):
                request._update_from_mos()

class smartbiz_mes_ExternalListWizard(models.TransientModel):
    _name = "smartbiz_mes.external_list_wizard"
    _description = "External List Wizard"
    production_id = fields.Many2one('mrp.production', string='Production')
    lines_ids = fields.One2many('smartbiz_mes.external_list_wizard_line', 'wizard_id')


    def action_confirm(self):
        """
        Khi bấm Xác nhận, gom dữ liệu từ line_ids -> external_data
        rồi gọi create_activities(external_data=...).
        """
        self.ensure_one()
        external_data = {}
        for line in self.lines_ids:
            wo_id = line.workorder_id.id
            comp_id = line.component_id.id
            if not wo_id or not comp_id:
                continue

            # Tách danh sách package
            package_names = []
            if line.packages:
                package_names = [p.strip() for p in line.packages.split(',') if p.strip()]
            else:
                # Nếu không nhập, tự động sinh dựa theo component_quantity và pack_quantity
                wo_name = line.workorder_id.display_name or ''
                comp_name = line.component_id.name or ''
                total_quantity = line.component_quantity
                pack_qty = line.pack_quantity if line.pack_quantity > 0 else 1

                num_packages = int(math.ceil(total_quantity / pack_qty))
                package_names = []
                for i in range(1, num_packages + 1):
                    # Ghép tên Workorder, tên Component và số thứ tự
                    package_names.append(f"{wo_name}-{comp_name}-{i}")

            list_package_tuples = [(pkg, line.pack_quantity) for pkg in package_names]

            # Gom vào external_data
            external_data.setdefault(wo_id, {})[comp_id] = list_package_tuples

        # Gọi create_activities trên toàn bộ workorders (hoặc chỉ wos_external)
        workorders = self.production_id.workorder_ids
        workorders.create_activities(external_data=external_data)

        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def default_get(self, fields_list):
        """
        Tự động tạo line_ids tương ứng (workorder, component) cho các WO có pack_method = 'external_list'.
        """
        res = super(smartbiz_mes_ExternalListWizard, self).default_get(fields_list)
        production_id = self.env.context.get('default_production_id')
        if not production_id:
            return res

        production = self.env['mrp.production'].browse(production_id)
        if not production:
            return res

        wos_external = production.workorder_ids.filtered(
            lambda w: w.operation_id and w.operation_id.pack_method == 'external_list'
        )

        lines_data = []
        for wo in wos_external:
            bom = wo.production_id.bom_id
            if not bom:
                continue
            for comp in bom.components_ids:
                if wo.operation_id.id not in comp.operations_ids.ids:
                    continue

                comp_quantity = (wo.production_id.product_qty / (bom.product_qty or 1.0)) * comp.quantity
                lines_data.append((0, 0, {
                    'workorder_id':  wo.id,
                    'component_id':  comp.id,
                    'component_quantity':  comp_quantity,
                }))

        if lines_data:
            res['lines_ids'] = lines_data
        return res

class smartbiz_mes_ExternalListWizardLine(models.TransientModel):
    _name = "smartbiz_mes.external_list_wizard_line"
    _description = "External List Wizard Line"
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder')
    component_id = fields.Many2one('smartbiz_mes.bom_components', string='Component')
    component_quantity = fields.Float(string='Component Quantity')
    packages = fields.Char(string='Packages')
    pack_quantity = fields.Float(string='Pack Quantity', default = 1)
    wizard_id = fields.Many2one('smartbiz_mes.external_list_wizard', string='Wizard')


