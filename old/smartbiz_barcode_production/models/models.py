# -*- coding: utf-8 -*-

from odoo.osv import expression
from odoo import models, fields, api, exceptions,_, tools
import os
import base64,pytz,logging
from datetime import datetime, timedelta
import datetime as date_time
import random
from odoo.exceptions import UserError, ValidationError
_logger = logging.getLogger(__name__)
from io import BytesIO
import xlsxwriter
from openpyxl import load_workbook
from odoo.tools import float_round, float_compare


class mrp_Production(models.Model):
    _inherit = ['mrp.production']
    production_line_id = fields.Many2one('smartbiz_mes.production_line', string='Production Line')
    name = fields.Char(store='True', readonly=False)

    def open_mrp_kanban(self):
        """ Mở Kanban view cho MRP Production """
        view_id = self.env.ref('smartbiz_barcode_production.mrp_production_kanban').id  # Đổi module nếu cần
        context = {
            'search_default_state': ['confirmed', 'progress', 'to_close'],  # Lọc trạng thái đơn sản xuất đang chạy
            'search_default_product_id': self.product_id.id if self.product_id else False,
            'default_product_id': self.product_id.id if self.product_id else False,
            'default_company_id': self.company_id.id,
            'search_default_workcenter_id': self.workcenter_id.id if self.workcenter_id else False,
            'search_default_production_line_id': self.production_line_id.id if self.production_line_id else False,
        }
        
        action = {
            'type': 'ir.actions.act_window',
            'views': [(view_id, 'kanban')],
            'name': _("Manufacturing Orders"),
            'res_model': 'mrp.production',
            'target': 'current',
            'context': context
        }
        return action
    def get_barcode_data(self, barcode, filters, barcodeType):
        # Khởi tạo biến record là None để tránh lỗi truy cập khi chưa gán giá trị
        record = None

        # Kiểm tra xem có barcodeType không
        if barcodeType:
            if barcodeType == 'lots':
                record = self.env['stock.lot'].search_read(
                    [('name', '=', barcode), ('product_id', '=', filters.get('product_id'))],
                    limit=1, fields=self._get_fields('stock.lot')
                )
            elif barcodeType == 'products':
                record = self.env['product.product'].search_read(
                    [('barcode', '=', barcode)],
                    limit=1, fields=self._get_fields('product.product')
                )
            elif barcodeType == 'locations':
                record = self.env['stock.location'].search_read(
                    [('barcode', '=', barcode)],
                    limit=1, fields=self._get_fields('stock.location')
                )
            elif barcodeType == 'packages':
                record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
                if record:
                    # Xử lý các quant liên quan đến package
                    prods = []
                    for quant in record.quant_ids:
                        prods.append({
                            'product_id': quant.product_id.id,
                            'product_name': quant.product_id.display_name,
                            'location_id': quant.location_id.id,
                            'quantity': quant.quantity,
                            'lot_id': quant.lot_id.id,
                            'lot_name': quant.lot_id.name,
                            'product_uom_id': quant.product_uom_id.id,
                            'product_uom': quant.product_uom_id.name,
                            'location_name': quant.location_id.display_name,
                            'available_quantity': quant.available_quantity,
                            'expiration_date': quant.lot_id.expiration_date,
                        })
                    record = [{
                        'id': record.id,
                        'name': record.name,
                        'location': record.location_id.id,
                        'location_name': record.location_id.display_name,
                        'products': prods
                    }]
        
        # Nếu barcodeType không được chỉ định, tìm kiếm mặc định theo filters và barcode
        if not record:
            if filters:
                record = self.env['stock.lot'].search_read(
                    [('name', '=', barcode), ('product_id', '=', filters.get('product_id'))],
                    limit=1, fields=self._get_fields('stock.lot')
                )
                if record:
                    return {'barcode': barcode, 'match': True, 'barcodeType': 'lots', 'record': record[0], 'fromCache': False}

            # Tìm kiếm sản phẩm
            record = self.env['product.product'].search_read(
                [('barcode', '=', barcode)], limit=1, fields=self._get_fields('product.product')
            )
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'products', 'record': record[0], 'fromCache': False}

            # Tìm kiếm vị trí
            record = self.env['stock.location'].search_read(
                [('barcode', '=', barcode)], limit=1, fields=self._get_fields('stock.location')
            )
            if record:
                return {'barcode': barcode, 'match': True, 'barcodeType': 'locations', 'record': record[0], 'fromCache': False}

            # Tìm kiếm package
            record = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if record:
                prods = []
                for quant in record.quant_ids:
                    prods.append({
                        'product_id': quant.product_id.id,
                        'product_name': quant.product_id.display_name,
                        'location_id': quant.location_id.id,
                        'quantity': quant.quantity,
                        'lot_id': quant.lot_id.id,
                        'lot_name': quant.lot_id.name,
                        'product_uom_id': quant.product_uom_id.id,
                        'product_uom': quant.product_uom_id.name,
                        'location_name': quant.location_id.display_name,
                        'available_quantity': quant.available_quantity,
                        'expiration_date': quant.lot_id.expiration_date,
                    })
                record = {
                    'id': record.id,
                    'name': record.name,
                    'location': record.location_id.id,
                    'location_name': record.location_id.display_name,
                    'products': prods
                }
                return {'barcode': barcode, 'match': True, 'barcodeType': 'packages', 'record': record, 'fromCache': False}

        # Nếu không tìm thấy bất kỳ record nào
        return {'barcode': barcode, 'match': False, 'barcodeType': barcodeType, 'record': False, 'fromCache': False}

    def create_package(self,package_name):
        if package_name:
            package = self.env['stock.quant.package'].search([('name','=',package_name)],limit=1)
            if package:
                package_id = package
                package_name = package.name
            else:
                package_id = self.env['stock.quant.package'].create({'name':package_name})
                
        else:
            package_id = self.env['stock.quant.package'].create({})
            package_name = package_id.name
            

        return {'id':package_id.id,'name':package_name}
    
    @api.model
    def filter_base_on_barcode(self, barcode):
        """ Tìm kiếm đơn sản xuất dựa trên barcode của sản phẩm, số lot, workcenter hoặc tên đơn. """
        barcode_type = None
        nomenclature = self.env.company.nomenclature_id
        if nomenclature.is_gs1_nomenclature:
            parsed_results = nomenclature.parse_barcode(barcode)
            if parsed_results:
                for result in parsed_results[::-1]:
                    if result['rule'].type in ('product', 'lot', 'workcenter', 'production'):
                        barcode_type = result['rule'].type
                        break

        active_id = self.env.context.get('active_id')
        production_domain = [('state', 'not in', ['done', 'cancel'])]

        production_nums = 0
        additional_context = {'active_id': active_id}

        # Kiểm tra barcode sản phẩm
        if barcode_type == 'product' or not barcode_type:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            if product:
                production_nums = self.search_count(production_domain + [('product_id', '=', product.id)])
                additional_context['search_default_product_id'] = product.id

        # Kiểm tra barcode số lô
        if self.env.user.has_group('stock.group_production_lot') and (barcode_type == 'lot' or (not barcode_type and not production_nums)):
            lot = self.env['stock.lot'].search([('name', '=', barcode)], limit=1)
            if lot:
                lot_domain = [('lot_producing_id', '=', lot.id)]
                production_nums = self.search_count(production_domain + lot_domain)
                additional_context['search_default_lot_id'] = lot.id

        # Kiểm tra barcode workcenter
        if barcode_type == 'workcenter' or (not barcode_type and not production_nums):
            workcenter = self.env['mrp.workcenter'].search([('code', '=', barcode)], limit=1)
            if workcenter:
                production_nums = self.search_count(production_domain + [('workcenter_id', '=', workcenter.id)])
                additional_context['search_default_workcenter_id'] = workcenter.id
        
        # Kiểm tra barcode production
        if barcode_type == 'production' or (not barcode_type and not production_nums):
            production = self.env['smartbiz_mes.production_line'].search([('code', '=', barcode)], limit=1)
            if production:
                production_nums = self.search_count(production_domain + [('production_line_id', '=', production.id)])
                additional_context['search_default_production_line_id'] = production.id

        # Nếu không tìm thấy theo barcode, thử tìm theo tên đơn sản xuất
        if not barcode_type and not production_nums:
            production_nums = self.search_count(production_domain + [('name', '=', barcode)])
            additional_context['search_default_name'] = barcode

        if not production_nums:
            return {
                'warning': {
                    'title': _('No matching production order found'),
                    'message': _('Scan a product, lot, workcenter, or production name to filter the manufacturing orders.'),
                }
            }
        # Thêm điều kiện lọc theo trạng thái
        production_domain.append(('state', 'in', ['confirmed', 'progress', 'to_close']))
        
        # Mở view Kanban cho MRP Production
        action = self.open_mrp_kanban()
        action['domain'] = production_domain
        action['context'] = additional_context
        return {'action': action}
        
    @api.model
    def open_new_production_barcode(self):
        """ Tạo một đơn sản xuất mới và mở nó.

        :return: Action mở đơn sản xuất hoặc False nếu không thành công
        """
        context = self.env.context
        if context.get('active_model') == 'mrp.production':
            new_production = self.create_new_production()
            return new_production.id if new_production else False
        return False
    
    @api.model
    def create_new_production(self):
        """ Tạo đơn sản xuất mới với thông tin mặc định. """
        default_bom = self.env['mrp.bom'].search([], limit=1)
        if not default_bom:
            raise UserError(_("No Bill of Materials found. Please create one before proceeding."))

        new_production = self.create({
            'product_id': default_bom.product_tmpl_id.product_variant_id.id,
            'product_qty': 1.0,
            'bom_id': default_bom.id,
            'workcenter_id': self.env['mrp.workcenter'].search([], limit=1).id,
        })
        return new_production

    
    
    # ------------------------------------------------------------------
    # Helper – total of picked quantities on a move
    # ------------------------------------------------------------------
    def _prepared_qty(self, move):
        """Sum *quantity* on move‑lines that the user marked as *picked*."""
        return sum(
            move.move_line_ids.filtered(lambda l: l.picked and l.quantity).mapped("quantity")
        )

    def _split_create_child(self, move, qty):
        vals = move._split(qty)              # list[dict]
        if not vals:
            return False
        return self.env['stock.move'].create(vals)[0]

    # ------------------------------------------------------------------
    # 1. Post a production/consumption batch prepared by the operator
    # ------------------------------------------------------------------
    def button_post_prepared_lines(self, production_id):
        """Record (``_action_done``) every picked move‑line in the MO.

        The method is idempotent: it can be pressed multiple times during
        the same manufacturing order.  On each call it:
        1. Collects every *raw* + *finished* move that still awaits
           completion and has at least one picked line.
        2. Splits the move into a *child* covering exactly the prepared
           quantity.
        3. Moves the picked lines ➀ to the child ➁ and posts the child
           ➂.
        4. Updates :pyattr:`qty_produced` on the MO when the child belongs
           to the main product.
        """
        self = self.browse(production_id)

        moves = (self.move_finished_ids | self.move_raw_ids).filtered(
            lambda m: m.state not in ('done', 'cancel') and self._prepared_qty(m) > 0
        )
        if not moves:
            raise UserError(_("Không có dòng nào picked."))

        for move in moves:
            qty_post   = self._prepared_qty(move)
            remaining  = move.product_uom_qty

            # ── 1. CÓ phần dư  → split
            if qty_post < remaining - 1e-6:
                child_move = self._split_create_child(move, qty_post)
                child_move.picked = True
                move.move_line_ids.filtered(lambda l: l.picked and l.quantity).write(
                    {'move_id': child_move.id}
                )
                post_move = child_move
            # ── 2. Đủ 100 % → dùng move gốc
            else:
                move.picked = True
                post_move = move

            # ── 3. Ghi sổ
            post_move._action_done(cancel_backorder=True)

            # ── 4. Cập nhật sản lượng chính
            if post_move in self.move_finished_ids and post_move.product_id == self.product_id:
                self.qty_produced = float_round(
                    self.qty_produced + qty_post,
                    precision_rounding=self.product_uom_id.rounding,
                )
        return self.get_data(self.id)

    # ------------------------------------------------------------------
    # 2. Finish MO theo thực tế – có / không Back-Order, KHÔNG wizard
    # ------------------------------------------------------------------
    def action_finish_actual(self, split_backorder: bool = False):
        """
        Đóng lệnh sản xuất dựa trên sản lượng đã ghi (move-line.picked=True)
        mà không bao giờ bật wizard khớp tiêu hao Odoo.

        Returns
        -------
            dict  { 'action': ir.actions | False,  'data': <get_data> }
        """
        self.ensure_one()
        rounding = self.product_uom_id.rounding

        # 1) Sản lượng thực tế của thành phẩm chính
        real_main_qty = sum(
            self.move_finished_ids
                .filtered(lambda m: m.product_id == self.product_id)
                .mapped(self._prepared_qty)
        )

        # 2) (tuỳ chọn) tạo Back-Order trước – demand vẫn còn nguyên
        action = False
        if split_backorder:
            action = self.action_split_backorder_custom()   # tạo BO, trả action

        # 3) Co nhỏ demand của MO gốc = sản lượng thực tế, finalize các move
        self.product_qty = float_round(real_main_qty, precision_rounding=rounding)
        self._finalise_open_moves()                        # done/cancel move còn mở

        # 4) Ghi sổ kho (không Back-Order nữa) và set trạng thái DONE
        self._post_inventory(cancel_backorder=True)
        self.write({
            "state": "done",
            "is_locked": True,
            "date_finished": fields.Datetime.now(),
        })

        # 5) Payload duy nhất
        return {
            "action": action,               # False nếu không tách BO
            "data":   self.get_data(self.id)
        }


    # ------------------------------------------------------------------
    # 3. Custom back‑order split – 100 % controlled
    # ------------------------------------------------------------------
    def action_split_backorder_custom(self):
        """Produce a new MO for the still‑missing quantities.

        *Move* and *move‑line* traces, costs, etc. are preserved via
        ``stock.move._split``.  The parent MO keeps all finished quantity;
        the child MO starts in **confirmed** state and can be processed
        normally.
        Returns the standard *window action* that opens the BO form.
        """
        self.ensure_one()

        done_qty = sum(
            self.move_finished_ids.filtered(lambda m: m.product_id == self.product_id).mapped(
                self._prepared_qty
            )
        )
        remaining_qty = self.product_qty - done_qty
        if remaining_qty <= 0:
            raise UserError(_("Không còn số lượng cần back‑order."))

        # 1) Copy MO skeleton
        bo = self.copy(
            {
                "name": f"{self.name}-BO",
                "origin": self.origin or self.name,
                "product_qty": remaining_qty,
                "state": "confirmed",
            }
        )

        # 2) Split every unfinished move & send remainder to BO
        for move in (self.move_finished_ids | self.move_raw_ids).filtered(
            lambda m: m.state not in ("done", "cancel")
        ):
            qty_done = self._prepared_qty(move)
            qty_missing = move.product_uom_qty - qty_done
            if qty_missing <= 0:
                if qty_done and move.state != "done":
                    move._action_done(cancel_backorder=True)
                continue

            bo_move =  self._split_create_child(move, qty_missing)
            bo_move.write({"production_id": bo.id})
            # keep reservation for BO if needed: bo_move._action_assign()

            if qty_done and move.state != "done":
                move._action_done(cancel_backorder=True)

        # 3) Update demand of parent MO to match real output
        self.product_qty = done_qty

        bo._onchange_move_finished()  # reset produced qty in BO
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
            "res_id": bo.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _finalise_open_moves(self):
        """Close any remaining open finished/by‑product moves to match real qty."""
        for move in self.move_finished_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            real_qty = self._prepared_qty(move)
            move.product_uom_qty = real_qty
            if real_qty:
                move.move_line_ids.filtered(lambda l: l.picked).write({"picked": False})
                move._action_done(cancel_backorder=True)

        # Cancel or unreserve raw moves we didn't touch
        for raw in self.move_raw_ids.filtered(
            lambda m: m.state not in ("done", "cancel") and self._prepared_qty(m) == 0
        ):
            if raw.state == "assigned":
                raw._do_unreserve()
            raw._action_cancel()

    def _get_fields(self,model):
        if model == 'mrp.production':
            return ['name','state','product_id','product_uom_id','lot_producing_id','lot_name','product_uom_qty','qty_produced','qty_producing','date_start','date_deadline','date_finished','company_id','user_id']
        if model == 'stock.move':
            return ['state','date','date_deadline','product_id','product_uom','product_uom_qty','quantity','product_qty','location_id','location_dest_id','picked','production_id','workorder_id','workcenter_id','bom_id','raw_material_production_id','move_line_ids','move_dest_ids']
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
        material_moves = []
        finished_moves = []
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
        for mv in finisheds:
            finished_moves.append({
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
        for mv in materials:
            material_moves.append({
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
        mvs.extend(material_moves)
        mvs.extend(finished_moves)
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
            
            'materials': material_moves,
            
            'finisheds': finished_moves,
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