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

class RES_Users(models.Model):
    _inherit = ['res.users']
    workcenter_id = fields.Many2one('mrp.workcenter', string='WorkCenter')
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')


class mrp_Production(models.Model):
    _inherit = ['mrp.production']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    name = fields.Char(store='True', readonly=False)
    production_request_id = fields.Many2one('smartbiz_mes.request', string='Production Request')
    lot_name = fields.Char(string='Lot Name')
    plan_start = fields.Datetime(string='Plan Start', default = lambda self: fields.Datetime.now())
    plan_finish = fields.Datetime(string='Plan Finish', default = lambda self: fields.Datetime.now() + timedelta(days=1))


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
            
    def validate(self, production_id):
        production = self.browse(production_id)
        if not production:
            raise UserError("MO không tồn tại.")

        if production.product_qty <= 0:
            raise UserError("Số lượng cần sản xuất của MO = 0 => dữ liệu sai.")

        # -------------------------------------------------------------------------
        # 0. Hai biến cục bộ (hardcode cho ví dụ). Sau này bạn lấy từ config, v.v.
        # -------------------------------------------------------------------------
        require_packing = True  # Bắt buộc đóng gói
        free_ratio = False      # Tỉ lệ tự do

        # -------------------------------------------------------------------------
        # A. Kiểm tra bắt buộc đóng gói: nếu require_packing=True,
        #    mọi move line (raw + finished) đều phải có package_id
        # -------------------------------------------------------------------------
        if require_packing:
            # Lấy toàn bộ move (nguyên liệu + thành phẩm) chưa done/cancel
            all_moves = (production.move_finished_ids).filtered(lambda m: m.state not in ('done','cancel'))
            # Tương tự cho move line chưa done/cancel
            all_lines = all_moves.mapped('move_line_ids').filtered(lambda ml: ml.state not in ('done','cancel'))

            # Nếu bất kỳ line nào không có package => raise
            any_line_missing_package = any(not ml.result_package_id for ml in all_lines)
            if any_line_missing_package:
                raise UserError(_(
                    "Sản phẩm này yêu cầu đóng gói bắt buộc, nhưng có dòng xuất/nhận chưa có package.\n"
                    "Vui lòng bổ sung package cho tất cả dòng."
                ))

        # -------------------------------------------------------------------------
        # B. Lấy/tạo move line cho SP chính (Step 1) => partial_qty, ratio
        # -------------------------------------------------------------------------
        finished_moves = production.move_finished_ids.filtered(lambda m: m.product_id == production.product_id)
        if finished_moves:
            finished_lines = finished_moves.mapped('move_line_ids').filtered(lambda ml: ml.state not in ('done','cancel'))
            if finished_lines:
                partial_qty = sum(finished_lines.mapped('quantity'))
            else:
                # Có move nhưng chưa có line => đặt partial_qty = product_qty
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
            # Chưa có move thành phẩm => tạo mới
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

        # -------------------------------------------------------------------------
        # C. Tự động tạo line cho BYPRODUCT nếu chưa có line (theo ratio)
        #    (Áp dụng khi BOM có byproduct, user chưa tạo line -> ta tạo)
        # -------------------------------------------------------------------------
        byproducts = production.move_finished_ids.filtered(lambda m: m.product_id != production.product_id and m.state not in ('done','cancel'))
        for byp_move in byproducts:
            existing_lines = byp_move.move_line_ids.filtered(lambda ml: ml.state not in ('done','cancel'))
            sum_lines = sum(existing_lines.mapped('quantity'))
            if sum_lines <= 0:
                # Tính qty theo BOM * ratio
                qty_create = byp_move.product_uom_qty * ratio
                # Tạo 1 move line, state='assigned' (nếu sp phụ là inbound, bạn chỉnh logic tuỳ ý)
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

        for move in production.move_raw_ids.filtered(lambda mv: mv.state not in ('done','cancel')):
            old_demand = move.product_uom_qty
            new_demand = old_demand * ratio

            existing_lines = move.move_line_ids.filtered(lambda ml: ml.state not in ('done','cancel'))
            sum_lines = sum(existing_lines.mapped('quantity'))

            if abs(sum_lines - new_demand)/new_demand >= 0.1:
                if sum_lines > new_demand:
                    diff = sum_lines - new_demand
                    for ml in reversed(existing_lines):
                        if diff <= 0:
                            break
                        if ml.quantity <= diff:
                            diff -= ml.quantity
                            ml.unlink()
                        else:
                            ml.write({'quantity': ml.quantity - diff})
                            diff = 0
                elif sum_lines < new_demand:
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

        # -------------------------------------------------------------------------
        # E. Kiểm tra byproduct theo yêu cầu "free_ratio" hay BOM strict/flexible
        #    (Step 4)
        # -------------------------------------------------------------------------
        for byp_move in byproducts:
            byp_done = sum(byp_move.mapped('quantity'))
            expected = byp_move.product_uom_qty * ratio

            # 1) free_ratio=True => cấm lệch
            if free_ratio:
                if abs(byp_done - expected) > 1e-4:
                    raise UserError(_(
                        "Byproduct %s lệch tỉ lệ khi 'tỉ lệ tự do' đang bật.\n"
                        "Đã = %.3f, Kỳ vọng = %.3f (ratio=%.2f)."
                    ) % (byp_move.product_id.display_name, byp_done, expected, ratio))
            # 2) free_ratio=False => logic BOM cũ
            else:
                if abs(byp_done - expected) > 1e-4:
                    if production.bom_id and production.bom_id.consumption == 'strict':
                        raise UserError(_(
                            "Byproduct %s không khớp tỉ lệ (strict BOM).\n"
                            "Đã=%.3f, Kỳ vọng=%.3f (ratio=%.2f)."
                        ) % (byp_move.product_id.display_name, byp_done, expected, ratio))
                    # flexible => cho qua

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
                # Thực ra trường hợp này hiếm, vì ở trên ta đã tạo finished_moves nếu chưa có
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
        # H. Tách backorder nếu partial (Step 8) + Step 6 cài qty_producing
        # -------------------------------------------------------------------------
        backorders = self.env['mrp.production']
        if 0 < partial_qty < production.product_qty:
            splitted = production._split_productions(
                amounts={production: [partial_qty, production.product_qty - partial_qty]},
                cancel_remaining_qty=False,
                set_consumed_qty=True
            )
            backorders = splitted - production

            # Step 6: Cập nhật qty_producing
            production.write({
                'qty_producing': partial_qty + production.qty_produced,
            })

            # Xử lý byproduct trong backorder
            for bo in backorders:
                # Bỏ move line cũ
                bo.move_finished_ids.move_line_ids.unlink()
                for bo_byp in bo.move_finished_ids.filtered(lambda m: m.product_id != production.product_id):
                    product_id = bo_byp.product_id.id
                    expected_goc = byproduct_expected_map.get(product_id, bo_byp.product_uom_qty)
                    # Tính sp phụ đã sản xuất
                    goc_byp_moves = production.move_finished_ids.filtered(lambda m: m.product_id.id == product_id)
                    produced_qty = sum(goc_byp_moves.mapped('quantity'))
                    new_qty = max(0, expected_goc - produced_qty)
                    bo_byp.write({'product_uom_qty': new_qty})
                    # Nếu muốn auto tạo line byproduct cho backorder, có thể tạo move line ở đây

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
        
    def print_move(self,move_id,printer_name,label_name):
        move = self.env['stock.move'].browse(move_id)
        printer = self.env.user.printing_printer_id or self.env['printing.printer'].search([('name','like',printer_name)],limit=1)      
        label = self.env['printing.label.zpl2'].search([('name','=',label_name)],limit=1)
        if label and printer:
            for ml in move.filtered(lambda ml: ml.result_package_id):
                label.print_label(printer, ml)

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
        users = self.env['res.users'].search([]).read(['name','barcode','workcenter_id','production_line_id'], load=False)
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
            # Lấy thông tin công đoạn
            work_orders = order.workorder_ids
            step_data = {}  # Dữ liệu cho từng công đoạn (thời gian, trạng thái)

            for step in all_steps:
                step_data[step_display_names[step]] = {
                    'duration': 0.0,
                    'state': 'pending'  # Mặc định là 'pending'
                }

            for wo in work_orders:
                step_name = wo.workcenter_id.name.strip().lower()
                display_name = step_display_names[step_name]

                if display_name in step_data:
                    step_data[display_name]['duration'] = wo.duration
                    step_data[display_name]['state'] = wo.state  # Lấy trạng thái thực tế

            # Tạo dòng dữ liệu cho bảng tổng hợp
            row = {
                'stt': stt,
                'kh': order.origin,
                'lot': order.name,
                'item': order.product_id.name,
                'so_luong': order.product_qty,
                'thoi_gian_tieu_chuan': round(order.duration_expected, 2),
                'thoi_gian_thuc_te': round(sum(step_data[step]['duration'] for step in step_display_names.values()), 2),
            }

            # Thêm dữ liệu từng công đoạn
            for step in step_display_names.values():
                row[step] = step_data[step]  # Lưu trữ cả thời gian và trạng thái

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
                            **{step: {'quantity': 0, 'state': 'pending'} for step in step_display_names.values()} #them state vao
                        }

                    component_data = grouped_faulty_data[lot_key]['components'][component.id]
                    component_data['total_faulty'] += activity.quantity
                    component_data[step_display_name]['quantity'] += activity.quantity
                    component_data[step_display_name]['state'] = wo.state #Lay state cua work order

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

