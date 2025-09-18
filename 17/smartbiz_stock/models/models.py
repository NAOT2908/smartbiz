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
from collections import defaultdict

class Product_Product(models.Model):
    _inherit = ['product.product']
    default_code = fields.Char(store='True', tracking=True)


    @api.model
    def create(self, vals):
        #Kiểm tra default_code
        if 'default_code' in vals and vals['default_code']:
            existed = self.search([
                ('default_code', '=', vals['default_code'])
            ], limit=1)
            if existed:
                raise ValidationError(
                    "Sản phẩm với mã {} đã tồn tại!".format(vals['default_code'])
                )
        return super().create(vals)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___product_readonly_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Product_Template(models.Model):
    _inherit = ['product.template']
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')
    default_code = fields.Char(store='True', tracking=True)


    @api.model
    def create(self, vals):
        #Kiểm tra default_code
        if 'default_code' in vals and vals['default_code']:
            existed = self.search([
                ('default_code', '=', vals['default_code'])
            ], limit=1)
            if existed:
                raise ValidationError(
                    "Sản phẩm với mã {} đã tồn tại!".format(vals['default_code'])
                )
        return super().create(vals)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___product_readonly_4','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Quant(models.Model):
    _inherit = ['stock.quant']
    warehouse_id = fields.Many2one('stock.warehouse', store='True')


    def action_apply_inventory(self):
        if self.env.user.has_group('smartbiz_stock.group_roles_inventory_adjustment___allow_apply_3') :
            return super().action_apply_inventory()
        raise UserError('Bạn không có quyền để thực hiện tác vụ này. Liên hệ với quản trị để cấp quyền vào nhóm: Kiểm kê - Được phép áp dụng nếu muốn truy cập.')

    def _onchange_product_id(self):
        self = self.sudo()
        super()._onchange_product_id()
        
    def _get_gather_domain_(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False):
        domain = [('product_id', '=', product_id.id)]
        if not strict:
            if lot_id:
                domain = expression.AND([['|', ('lot_id', '=', lot_id.ids), ('lot_id', '=', False)], domain])
            if package_id:
                domain = expression.AND([[('package_id', '=', package_id.id)], domain])
            if owner_id:
                domain = expression.AND([[('owner_id', '=', owner_id.id)], domain])
            domain = expression.AND([[('location_id', 'child_of', location_id.id)], domain])
        else:
            domain = expression.AND([['|', ('lot_id', '=', lot_id.ids), ('lot_id', '=', False)] if lot_id else [('lot_id', '=', False)], domain])
            domain = expression.AND([[('package_id', '=', package_id and package_id.id or False)], domain])
            domain = expression.AND([[('owner_id', '=', owner_id and owner_id.id or False)], domain])
            domain = expression.AND([[('location_id', '=', location_id.id)], domain])
        if self.env.context.get('with_expiration'):
            domain = expression.AND([['|', ('expiration_date', '>=', self.env.context['with_expiration']), ('expiration_date', '=', False)], domain])
        return domain

    @api.constrains("product_id", "quantity")
    def check_negative_qty(self):
        p = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        check_negative_qty = (
            config["test_enable"] and self.env.context.get("test_stock_no_negative")
        ) or not config["test_enable"]
        if not check_negative_qty:
            return

        for quant in self:
            disallowed_by_product = (
                not quant.product_id.allow_negative_stock
                and not quant.product_id.categ_id.allow_negative_stock
            )
            disallowed_by_location = not quant.location_id.allow_negative_stock
            if (
                float_compare(quant.quantity, 0, precision_digits=p) == -1
                and quant.product_id.type == "product"
                and quant.location_id.usage in ["internal", "transit"]
                and disallowed_by_product
                and disallowed_by_location
            ):
                msg_add = ""
                if quant.lot_id:
                    msg_add = _(" lot {}").format(quant.lot_id.name_get()[0][1])
                raise ValidationError(
                    _(
                        "You cannot validate this stock operation because the "
                        "stock level of the product '{name}'{name_lot} would "
                        "become negative "
                        "({q_quantity}) on the stock location '{complete_name}' "
                        "and negative stock is "
                        "not allowed for this product and/or location."
                    ).format(
                        name=quant.product_id.display_name,
                        name_lot=msg_add,
                        q_quantity=quant.quantity,
                        complete_name=quant.location_id.complete_name,
                    )
                )

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Lot(models.Model):
    _inherit = ['stock.lot']
    product_qty = fields.Float(store='True')


    @api.model
    def update_serial(self, *args, **kwargs):
        """
        Payload chấp nhận:
        {
          "records": [{"code","name","serial","act","exp"}, ...],
          "warehouse_code": "Z",              # hoặc
          "location_barcode": "KZ-STOCK",     # ưu tiên nếu có
          "company_id": 1,
          "apply_inventory": true,
          "limits": { "IN_CHUNK": 8000, "CREATE_CHUNK": 2000, "APPLY_CHUNK": 3000 },
          "commit_every": 0                   # 0 = không commit giữa chừng; >0 = commit mỗi N lots/quant mới
        }
        Kết quả: { ok, received, product{existing,created}, lot{existing,created}, quant{existing,created,applied}, warehouse/location... }
        """

        # ------- Helpers -------
        def last_dict_arg(_args, _kwargs):
            if _args and isinstance(_args[-1], dict):
                return _args[-1]
            if "data" in _kwargs and isinstance(_kwargs["data"], dict):
                return _kwargs["data"]
            return _kwargs

        def chunk_list(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i+n]

        def ctx_reduce(recset):
            # tắt tracking/mail để giảm overhead khi create-multi lớn
            return recset.with_context(
                tracking_disable=True,
                mail_create_nolog=True,
                prefetch_fields=False,
            )

        # ------- Lấy & chuẩn hoá payload -------
        data = last_dict_arg(args, kwargs) or {}
        records = data.get("records") or []
        warehouse_code  = data.get("warehouse_code") or "Z"
        location_barcode = data.get("location_barcode")
        apply_inventory = bool(data.get("apply_inventory", True))

        limits = data.get("limits") or {}
        IN_CHUNK     = int(limits.get("IN_CHUNK", 8000))
        CREATE_CHUNK = int(limits.get("CREATE_CHUNK", 2000))
        APPLY_CHUNK  = int(limits.get("APPLY_CHUNK", 3000))
        commit_every = int(data.get("commit_every") or 0)

        company_id = data.get("company_id") or self.env.company.id
        Company = self.env["res.company"].browse(company_id)
        if not Company.exists():
            return {"ok": False, "error": "Invalid company_id"}

        self = self.with_context(
            allowed_company_ids=[company_id],
            force_company=company_id,
        ).with_company(Company).sudo()

        Product = self.env["product.product"]
        Lot     = self.env["stock.lot"]
        Quant   = self.env["stock.quant"]
        Wh      = self.env["stock.warehouse"]
        Loc     = self.env["stock.location"]

        # ------- Tiền xử lý input (dedup + map nhanh) -------
        cleaned = []
        code_set = set()
        pair_seen = set()  # (code, serial) để khử trùng trong batch
        for rec in records:
            code   = (rec.get("code") or rec.get("name") or "").strip()
            name   = (rec.get("name") or rec.get("code") or "").strip()
            serial = (rec.get("serial") or "").strip()
            if not code or not serial:
                continue
            key = (code, serial)
            if key in pair_seen:
                continue
            pair_seen.add(key)
            cleaned.append({
                "code": code, "name": name, "serial": serial,
                "act": rec.get("act") or False,
                "exp": rec.get("exp") or False,
            })
            code_set.add(code)

        received = len(cleaned)
        if not received:
            return {
                "ok": True, "received": 0,
                "product": {"existing": 0, "created": 0},
                "lot": {"existing": 0, "created": 0},
                "quant": {"existing": 0, "created": 0, "applied": 0},
                "note": "No valid records"
            }

        # ------- Xác định location đích -------
        location = None
        if location_barcode:
            location = Loc.search([("barcode", "=", location_barcode),
                                   ("company_id", "in", [False, company_id])], limit=1)
            if not location:
                return {"ok": False, "error": "Không tìm thấy location theo barcode %s" % location_barcode}
        else:
            wh = Wh.search([("code", "=", warehouse_code),
                            ("company_id", "=", company_id)], limit=1)
            if not wh:
                wh = Wh.create({"name": warehouse_code, "code": warehouse_code, "company_id": company_id})
            location = wh.lot_stock_id
            if not location:
                location = Loc.search([("usage", "=", "internal"),
                                       ("company_id", "in", [False, company_id])], limit=1)
                if not location:
                    return {"ok": False, "error": "Không tìm được Internal Location để đặt quant."}

        # =========================
        # 1) PRODUCTS
        # =========================
        code_list = list(code_set)
        code2prod = {}
        product_existing = 0
        product_created  = 0

        for part in chunk_list(code_list, IN_CHUNK):
            prods = Product.search([("default_code", "in", part)])
            for p in prods:
                code2prod[p.default_code] = p
            product_existing += len(prods)

        missing_vals = []
        # map nhanh code -> name (từ cleaned) để tạo product
        code2name = {}
        for c in cleaned:
            if c["code"] not in code2name:
                code2name[c["code"]] = c["name"] or c["code"]

        for code in code_list:
            if code not in code2prod:
                missing_vals.append({
                    "name": code2name.get(code) or code,
                    "default_code": code,
                    "barcode": code,
                    "detailed_type": "product",
                    "tracking": "serial",
                    "use_expiration_date": False,
                    "company_id": company_id,
                })
        if missing_vals:
            for pack in chunk_list(missing_vals, CREATE_CHUNK):
                new_prods = ctx_reduce(Product).create(pack)
                for p in new_prods:
                    code2prod[p.default_code] = p
                product_created += len(new_prods)
                if commit_every and product_created % commit_every == 0:
                    self.env.cr.commit()

        # Chuẩn bị map pid → {serial → info} (1 lần, dùng cho Lots & Quants)
        pid2serial_info = defaultdict(dict)
        for c in cleaned:
            pid = code2prod[c["code"]].id
            pid2serial_info[pid][c["serial"]] = c

        # =========================
        # 2) LOTS (serial) – per pid, nhưng không quét cleaned lặp lại
        # =========================
        prodser2lot = {}  # (pid, serial) -> lot rec
        lot_existing = 0
        lot_created  = 0

        for pid, serial_map in pid2serial_info.items():
            serials = list(serial_map.keys())

            # Đọc lot đã có cho pid này
            for part in chunk_list(serials, IN_CHUNK):
                lots = Lot.search([
                    ("product_id", "=", pid),
                    ("name", "in", part),
                    ("company_id", "in", [False, company_id]),
                ])
                for l in lots:
                    prodser2lot[(pid, l.name)] = l
                lot_existing += len(lots)

            # Tạo thiếu
            need = [s for s in serials if (pid, s) not in prodser2lot]
            if need:
                vals_buf = []
                for s in need:
                    info = serial_map.get(s)
                    vals_buf.append({
                        "name": s,
                        "product_id": pid,
                        "ref": (info and info["code"]) or False,
                        "warranty_activation_date": (info and info["act"]) or False,
                        "warranty_expiration_date": (info and info["exp"]) or False,
                        "company_id": company_id,
                    })
                # create theo lô + savepoint để tự hồi phục khi đụng unique
                for pack in chunk_list(vals_buf, CREATE_CHUNK):
                    with self.env.cr.savepoint():
                        try:
                            new_lots = ctx_reduce(Lot).create(pack)
                        except Exception:
                            self.env.cr.rollback()
                            # đọc lại chỉ các serial pack
                            names = [v["name"] for v in pack]
                            lots2 = Lot.search([
                                ("product_id", "=", pid),
                                ("name", "in", names),
                                ("company_id", "in", [False, company_id]),
                            ])
                            new_lots = lots2
                        for l in new_lots:
                            prodser2lot[(pid, l.name)] = l
                        lot_created += len(new_lots)
                        if commit_every and lot_created % commit_every == 0:
                            self.env.cr.commit()

        # =========================
        # 3) QUANTS tại location đích (tạo thiếu, apply cho mới)
        # =========================
        lot_ids = list({l.id for l in prodser2lot.values()})
        quant_existing = 0
        quant_created  = 0
        quant_applied  = 0

        if lot_ids:
            have_map = {}
            for part in chunk_list(lot_ids, IN_CHUNK):
                quants = Quant.search([
                    ("location_id", "=", location.id),
                    ("lot_id", "in", part),
                ])
                for q in quants:
                    have_map[q.lot_id.id] = q
                quant_existing += len(quants)

            # Tạo quant còn thiếu
            to_create = []
            for (pid, serial), lot in prodser2lot.items():
                if lot.id not in have_map:
                    to_create.append({
                        "product_id": lot.product_id.id,
                        "lot_id": lot.id,
                        "location_id": location.id,
                        "company_id": company_id,
                    })

            if to_create:
                # create theo lô + savepoint
                created_quants = self.env["stock.quant"].browse()
                for pack in chunk_list(to_create, CREATE_CHUNK):
                    with self.env.cr.savepoint():
                        try:
                            qs = ctx_reduce(Quant).create(pack)
                        except Exception:
                            self.env.cr.rollback()
                            # đọc lại những cái vừa định tạo để idempotent
                            lot_ids_pack = [v["lot_id"] for v in pack]
                            qs = Quant.search([
                                ("location_id", "=", location.id),
                                ("lot_id", "in", lot_ids_pack),
                            ])
                        created_quants |= qs
                        quant_created += len(qs)
                        if commit_every and quant_created % commit_every == 0:
                            self.env.cr.commit()

                # apply inventory (chỉ cho quant mới)
                if apply_inventory and created_quants:
                    for pack in chunk_list(created_quants.ids, APPLY_CHUNK):
                        recs = Quant.browse(pack).with_context(inventory_mode=True)
                        recs.write({
                            "inventory_quantity": 1,
                            "inventory_date": fields.Datetime.now(),
                        })
                        recs.action_apply_inventory()
                        quant_applied += len(recs)
                        if commit_every and quant_applied % commit_every == 0:
                            self.env.cr.commit()

        return {
            "ok": True,
            "received": received,
            "product": {"existing": product_existing, "created": product_created},
            "lot":     {"existing": lot_existing,  "created": lot_created},
            "quant":   {"existing": quant_existing,"created": quant_created, "applied": quant_applied},
            "warehouse": {
                "code": warehouse_code,
                "location_id": location.id,
                "location_name": location.display_name,
                "location_barcode": location.barcode,
            }
        }

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Move(models.Model):
    _inherit = ['stock.move']
    lots = fields.Many2many('stock.lot', string='Lots')
    product_id = fields.Many2one('product.product', store='True')
    transfer_request_line_id = fields.Many2one('smartbiz_stock.transfer_request_line', string='Transfer Request Line')


    def _update_reserved_quantity(self, need, location_id, quant_ids=None, lot_id=None, package_id=None, owner_id=None, strict=True):
        if self.lots:
            lot_id = self.lots
        return super()._update_reserved_quantity(need=need,location_id=location_id,quant_ids=quant_ids,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict)
        
        
    def _get_available_quantity(self, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, allow_negative=False):
        if self.lots:
            lot_id = self.lots
        return super()._get_available_quantity(location_id=location_id,lot_id=lot_id,package_id=package_id,owner_id=owner_id,strict=strict,allow_negative=allow_negative)

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Warehouse(models.Model):
    _inherit = ['stock.warehouse']
    customize_reception = fields.Boolean(string='Customize Reception', default = 'True')


    def write(self, vals):
        super().write(vals)
        for warehouse in self:
            input_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-INPUT'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            quality_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-QUALITY'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            stock_loc = self.env['stock.location'].search([('barcode', '=',warehouse.code + '-STOCK'),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            
            barcode = warehouse.code + '-INPUT-QC'
            qc_picking_type = self.env['stock.picking.type'].search([('barcode', '=',barcode),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            if not qc_picking_type:
                qc_picking_type = self.env['stock.picking.type'].create({
                    'name': 'Kiểm tra chất lượng', 'barcode': barcode, 'sequence_code': 'INPUT-QC', 'warehouse_id': warehouse.id, 
                    'code': 'internal', 'show_operations': True, 'use_create_lots': False, 'use_existing_lots': True, 
                    'default_location_src_id': input_loc.id, 'default_location_dest_id': quality_loc.id })
            barcode = warehouse.code + '-STORE'
            store_picking_type = self.env['stock.picking.type'].search([('barcode', '=',barcode),'|',('active', '=', False), ('active', '!=', False)],limit=1)
            if not store_picking_type:
                store_picking_type = self.env['stock.picking.type'].create({
                    'name': 'Lưu kho', 'barcode': barcode, 'sequence_code': 'STORE', 'warehouse_id': warehouse.id, 
                    'code': 'internal', 'show_operations': True, 'use_create_lots': False, 'use_existing_lots': True, 
                    'default_location_src_id': quality_loc.id, 'default_location_dest_id': stock_loc.id })
                
            qc_rule = self.env['stock.rule'].search([('location_src_id', '=', input_loc.id), ('location_dest_id', '=', quality_loc.id)],limit=1)
            store_rule_3 = self.env['stock.rule'].search([('location_src_id', '=', quality_loc.id), ('location_dest_id', '=', stock_loc.id)],limit=1)
            store_rule_2 = self.env['stock.rule'].search([('location_src_id', '=', input_loc.id), ('location_dest_id', '=', stock_loc.id)],limit=1)
            if warehouse.reception_steps == 'three_steps' and warehouse.customize_reception:
                qc_picking_type.write({'active':True})
                store_picking_type.write({'active':True,'default_location_src_id': quality_loc.id, 'default_location_dest_id': stock_loc.id})
                qc_rule.write({ 'picking_type_id': qc_picking_type.id })
                store_rule_3.write({ 'picking_type_id': store_picking_type.id })
            elif warehouse.reception_steps == 'two_steps' and warehouse.customize_reception:
                qc_picking_type.write({'active':False})
                store_picking_type.write({'active':True,'default_location_src_id': input_loc.id, 'default_location_dest_id': stock_loc.id})
                store_rule_2.write({ 'picking_type_id': store_picking_type.id })
            else:
                qc_picking_type.write({'active':False})
                store_picking_type.write({'active':False})


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_PickingType(models.Model):
    _inherit = ['stock.picking.type']
    name = fields.Char(store='True')
    scan_product = fields.Boolean(string='Scan Product')
    scan_source_location = fields.Boolean(string='Scan Source Location')
    scan_destination_location = fields.Boolean(string='Scan Destination Location')
    scan_lot = fields.Boolean(string='Scan Lot')
    scan_package = fields.Boolean(string='Scan Package')
    get_full_package = fields.Boolean(string='Get Full Package')
    all_move_done = fields.Boolean(string='All Move Done')
    all_move_line_picked = fields.Boolean(string='All Move Line Picked')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Product_Category(models.Model):
    _inherit = ['product.category']
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Uom_Uom(models.Model):
    _inherit = ['uom.uom']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Uom_Category(models.Model):
    _inherit = ['uom.category']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_MoveLine(models.Model):
    _inherit = ['stock.move.line']
    picking_type_id = fields.Many2one('stock.picking.type', store='True')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Location(models.Model):
    _inherit = ['stock.location']
    capacity = fields.Float(string='Capacity')
    capacity_type = fields.Selection([('quantity','Quantity'),('weight','Weight'),('volume','Volume'),], string='Capacity Type')
    allow_negative_stock = fields.Boolean(string='Allow Negative Stock')


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Route(models.Model):
    _inherit = ['stock.route']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_Rule(models.Model):
    _inherit = ['stock.rule']


    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___configuaration_readonly_5','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class Stock_quantpackage(models.Model):
    _inherit = ['stock.quant.package']
    _sql_constraints = [
                ('uniq_name', 'unique(name)', "Name Exiting!"),
    ]
    name = fields.Char(store='True')


class Stock_Picking(models.Model):
    _inherit = ['stock.picking']
    lot = fields.Char(string='Lot')
    picking_order_ids = fields.Many2many('stock.picking', 'picking_picking_rel_1', 'picking_order_ids_1', 'picking_order_ids_2', string='Picking Order')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', compute='_compute_warehouse_id', store=True)
    picking_type_id = fields.Many2one('stock.picking.type', store='True')
    transfer_request_id = fields.Many2one('smartbiz_stock.transfer_request', string='Transfer Request')
    name = fields.Char(string='Name', readonly=False)


    @api.depends('picking_type_id')
    def _compute_warehouse_id(self):
        for record in self:
            record.warehouse_id = record.picking_type_id.warehouse_id

    def action_confirm(self):
        for pk in self:
            if any(not record.group_id for record in pk.move_ids):
                group_id = pk.group_id.create({
                    'name': pk.name,
                    'partner_id': pk.partner_id.id,
                    'move_type':'one'
                })
                for move in pk.move_ids:
                    move.write({'group_id':group_id})
        return super().action_confirm()

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if self.env.su:
            return True
        permissions = [{'group':'smartbiz_stock.group_roles_inventory___move_readonly_6','read':True,'write':False,'create':False,'unlink':False },]
        if any(self.env.user.has_group(perm['group']) for perm in permissions):
            return any(self.env.user.has_group(perm['group']) and perm[operation] for perm in permissions)
        return super().check_access_rights(operation, raise_exception=raise_exception)
class SmartbizStock_StockReport(models.Model):
    _name = "smartbiz_stock.stock_report"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Stock Report"
    from_date = fields.Date(string='From Date')
    to_date = fields.Date(string='To Date')
    name = fields.Char(string='Name', compute='_compute_name', store=True)
    dynamic_template_id = fields.Many2one('smartbiz_stock.dynamic_report_template', string='Dynamic Template')
    picking_group_template_id = fields.Many2one('smartbiz_stock.picking_group_template', string='Picking Group Template')
    state = fields.Selection([('not_viewed','Not Viewed'),('viewed','Viewed'),], string= 'Status', readonly= False, copy = True, index = False, default = 'not_viewed')


    @api.depends('from_date', 'to_date')
    def _compute_name(self):
        for record in self:
            record.name = "Từ "+ str(record.from_date) + " Đến " + str(record.to_date)

    def action_not_viewed_view_report(self):
        self.ensure_one()
        tz = self.env.user.tz or 'UTC'
        df = datetime.combine(self.from_date, time.min).replace(tzinfo=ZoneInfo(tz))
        dt = datetime.combine(self.to_date, time.max).replace(tzinfo=ZoneInfo(tz))
        df_utc = df.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%M:%S')
        dt_utc = dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%M:%S')

        self.write({'state':'viewed'})

        action =  self.env['smartbiz_stock.inventory_report']._rebuild_view(
            df_utc=df_utc, dt_utc=dt_utc,
            return_action=True        # hoặc =1
        )
        return action 

        
        
    def action_not_viewed_view_dynamic_report(self):
        self.ensure_one()
        tz = self.env.user.tz or 'UTC'
        df = datetime.combine(self.from_date, time.min).replace(tzinfo=ZoneInfo(tz))
        dt = datetime.combine(self.to_date, time.max).replace(tzinfo=ZoneInfo(tz))
        df_utc = df.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%M:%S')
        dt_utc = dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%M:%S')

        self.write({'state':'viewed'})
        
        action = self.env['smartbiz_stock.dynamic_inventory_report']._rebuild_view(
            template_rec=self.picking_group_template_id, df_utc=df_utc, dt_utc=dt_utc,
            return_action=True        # hoặc =1
        )
        return action 

        
        
    def save_excel(self,workbook,file_name):
        output = BytesIO()
        workbook.save(output)

        #workbook.close()

        # Tạo response
        file_data = base64.b64encode(output.getvalue())
        output.close()

        # Tạo attachment
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': file_data,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id
        })

        # Trả về action để download file
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }
        
    def load_excel(self,file_name):
        current_dir = os.path.dirname(__file__)
        # Lùi lại hai cấp thư mục để đến thư mục gốc của module
        module_dir = os.path.abspath(os.path.join(current_dir, os.pardir))

        # Xây dựng đường dẫn đến file template
        template_path = os.path.join(module_dir, 'data', file_name)

        return load_workbook(template_path)

class SmartbizStock_TransferRequest(models.Model):
    _name = "smartbiz_stock.transfer_request"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Transfer Request"
    name = fields.Char(string='Request', default = 'New')
    date = fields.Datetime(string='Date')
    transfer_request_type_id = fields.Many2one('smartbiz_stock.transfer_request_type', string='Transfer Request Type')
    transfer_request_line_ids = fields.One2many('smartbiz_stock.transfer_request_line', 'transfer_request_id')
    picking_ids = fields.One2many('stock.picking', 'transfer_request_id')
    state = fields.Selection([('draft','Draft'),('done','Done'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    def action_draft_create_order(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']

        for req in self.filtered(lambda r: r.state != 'done'):
            grouped = {}
            for line in req.transfer_request_line_ids:
                product = line.product_id
                qty = line.quantity
                # Lấy default location từ default_picking_type của request type
                default_pick = req.transfer_request_type_id.picking_type_id
                default_loc = default_pick and default_pick.default_location_src_id or self.env['stock.location']
                quants = self.env['stock.quant'].search([
                    ('location_id', 'child_of', default_loc.id),
                    ('product_id', '=', product.id),
                    ('lot_id', 'in', line.lots_ids.ids)
                ])
                onhand = sum(quants.mapped('quantity'))
                rule = req._find_applicable_rule(line, onhand)
                items = req._prepare_items_from_rule(line, qty, onhand, rule)
                for it in items:
                    key = it['picking_type'].id
                    grouped.setdefault(key, []).append(it)

            for picking_type_id, items in grouped.items():
                pt = self.env['stock.picking.type'].browse(picking_type_id)
                picking = Picking.create({
                    'picking_type_id': pt.id,
                    'location_id': pt.default_location_src_id.id,
                    'location_dest_id': pt.default_location_dest_id.id,
                    'transfer_request_id': req.id,
                    'origin': req.name,
                })
                for it in items:
                    Move.create({
                        'name': it['product'].display_name,
                        'product_id': it['product'].id,
                        'product_uom_qty': it['quantity'],
                        'product_uom': it['product'].uom_id.id,
                        'picking_id': picking.id,
                        'location_id': it['location_src'].id,
                        'location_dest_id': it['location_dest'].id,
                        'transfer_request_line_id': it['transfer_request_line_id'],
                        'lot_ids': [(6, 0, it['lots_ids'])],
                    })
                picking.action_confirm()
            req.write({'state': 'done'})

        
        
    def _find_applicable_rule(self, line, onhand):
        rules = line.transfer_request_id.transfer_request_type_id.transfer_request_type_detail_ids.sorted('sequence')
        for rule in rules:
            if rule.product_id and rule.product_id != line.product_id:
                continue
            if rule.product_category_id and rule.product_category_id != line.product_id.categ_id:
                continue
            if rule.name_contains and rule.name_contains.lower() not in (line.product_id.name or '').lower():
                continue
            if onhand < rule.min_onhand:
                continue
            if rule.max_onhand and onhand >= rule.max_onhand:
                continue
            if not rule._evaluate_custom(line, onhand):
                continue
            return rule
        # fallback về default của request type hoặc rule đầu tiên
        default_pick = line.transfer_request_id.transfer_request_type_id.default_picking_type_id
        if default_pick:
            return self.env['smartbiz_stock.transfer_request_type_detail'].create({
                'transfer_request_type_id': line.transfer_request_id.transfer_request_type_id.id,
                'sequence': 9999,
                'picking_type_id': default_pick.id,
            })
        return rules and rules[0] or False

    def _prepare_items_from_rule(self, line, qty, onhand, rule):
        items = []
        src_main = rule.picking_type_id.default_location_src_id
        dst_main = rule.picking_type_id.default_location_dest_id
        if not rule.split_when_not_enough or onhand >= qty or not rule.fallback_picking_type_id:
            items = [{
                'product': line.product_id,
                'quantity': qty,
                'location_src': src_main,
                'location_dest': dst_main,
                'lots_ids': line.lots_ids.ids,
                'transfer_request_line_id': line.id,
                'picking_type': rule.picking_type_id,
            }]
        else:
            if onhand > 0:
                items.append({
                    'product': line.product_id,
                    'quantity': onhand,
                    'location_src': src_main,
                    'location_dest': dst_main,
                    'lots_ids': line.lots_ids.ids,
                    'transfer_request_line_id': line.id,
                    'picking_type': rule.picking_type_id,
                })
            fallback = rule.fallback_picking_type_id
            items.append({
                'product': line.product_id,
                'quantity': qty - onhand,
                'location_src': fallback.default_location_src_id,
                'location_dest': fallback.default_location_dest_id,
                'lots_ids': line.lots_ids.ids,
                'transfer_request_line_id': line.id,
                'picking_type': fallback,
            })
        return items

    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_stock.transfer_request') or 'New'


        res = super().create(values)


        return res

class SmartbizStock_TransferRequestLine(models.Model):
    _name = "smartbiz_stock.transfer_request_line"
    _description = "Transfer Request Line"
    product_id = fields.Many2one('product.product', string='Product')
    lots_ids = fields.Many2many('stock.lot', string='Lots')
    quantity = fields.Float(string='Quantity')
    transfer_request_id = fields.Many2one('smartbiz_stock.transfer_request', string='Transfer Request')


class SmartbizStock_TransferRequestType(models.Model):
    _name = "smartbiz_stock.transfer_request_type"
    _description = "Transfer Request Type"
    name = fields.Char(string='Name')
    picking_type_id = fields.Many2one('stock.picking.type', string='Picking Type')
    transfer_request_type_detail_ids = fields.One2many('smartbiz_stock.transfer_request_type_detail', 'transfer_request_type_id')


class SmartbizStock_TransferRequestTypeDetail(models.Model):
    _name = "smartbiz_stock.transfer_request_type_detail"
    _description = "Transfer Request Type Detail"
    sequence = fields.Integer(string='Sequence')
    transfer_request_type_id = fields.Many2one('smartbiz_stock.transfer_request_type', string='Transfer Request Type')
    picking_type_id = fields.Many2one('stock.picking.type', string='Picking Type')
    split_when_not_enough = fields.Boolean(string='Split When Not Enough')
    fallback_picking_type_id = fields.Many2one('stock.picking.type', string='Fallback Picking Type')
    product_id = fields.Many2one('product.product', string='Product')
    product_category_id = fields.Many2one('product.category', string='Product Category')
    name_contains = fields.Char(string='Name Contains')
    min_onhand = fields.Float(string='Min Onhand')
    max_onhand = fields.Float(string='Max Onhand')
    python_condition = fields.Text(string='Python Condition')


    @api.model
    def _evaluate_custom(self, line, onhand):
        if not self.python_condition:
            return True
        ctx = {
            'line': line,
            'record': line.transfer_request_id,
            'env': self.env,
            'onhand': onhand,
            'time': __import__('time'),
        }
        return bool(safe_eval(self.python_condition, ctx))

class SmartbizStock_DynamicReportTemplate(models.Model):
    _name = "smartbiz_stock.dynamic_report_template"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Dynamic Report Template"
    name = fields.Char(string='Name')
    alias_ids = fields.Many2many('smartbiz_stock.dynamic_report_alias', 'dynamic_report_template_dynamic_report_alias_rel',  string='Alias')
    state = fields.Selection([('active','Active'),('inactive','Inactive'),], string= 'Status', readonly= False, copy = True, index = False, default = 'active')


    def action_active_rebuild_reports(self):
        mixin_cls = self.env.registry['smartbiz_stock.dynamic_report_base'] 
        for model_cls in self.env.registry.models.values():             # class model
            if issubclass(model_cls, mixin_cls) and model_cls is not mixin_cls:
                self.env[model_cls._name]._rebuild_view()

        
        
    def action_active_deactive(self):
        self.write({'state': 'inactive'})

        
        
    def action_inactive_active(self):
        self.write({'state': 'active'})

        
        
class SmartbizStock_DynamicReportAlias(models.Model):
    _name = "smartbiz_stock.dynamic_report_alias"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Dynamic Report Alias"
    name = fields.Char(string='Name', required=True)
    report_model = fields.Char(string='Report Model')
    alias = fields.Char(string='Alias', required=True)
    separator = fields.Char(string='Separator', default = '_')
    regex_pattern = fields.Char(string='Regex Pattern')
    lines_ids = fields.One2many('smartbiz_stock.dynamic_report_alias_line', 'alias_id')
    state = fields.Selection([('active','Active'),('inactive','Inactive'),], string= 'Status', readonly= False, copy = True, index = False, default = 'active')


    def action_active_deactive(self):
        self.write({'state': 'inactive'})

        
        
    def action_inactive_active(self):
        self.write({'state': 'active'})

        
        
class SmartbizStock_DynamicReportAliasLine(models.Model):
    _name = "smartbiz_stock.dynamic_report_alias_line"
    _description = "Dynamic Report Alias Line"
    alias_id = fields.Many2one('smartbiz_stock.dynamic_report_alias', string='Alias', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default = 10)
    field_name = fields.Char(string='Field Name', required=True)
    field_label = fields.Char(string='Field Label', required=True, translate="True")
    field_type = fields.Selection([('char','Char'),('integer','Integer'),('float','Float'),('date','Date'),], string='Field Type', required=True, default = 'char')
    segment_index = fields.Integer(string='Segment Index')
    regex_group = fields.Integer(string='Regex Group')
    is_computed = fields.Boolean(string='Is Computed')
    compute_expression = fields.Char(string='Compute Expression')


    # --- auto thêm “x_” ---
    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('field_name') and not v['field_name'].startswith('x_'):
                v['field_name'] = f"x_{v['field_name'].strip().lower()}"
        return super().create(vals_list)

    def write(self, vals):
        if 'field_name' in vals and vals['field_name']:
            if not vals['field_name'].startswith('x_'):
                vals['field_name'] = f"x_{vals['field_name'].strip().lower()}"
        return super().write(vals)

    @api.constrains('is_computed','compute_expression')
    def _check_expr(self):
        for rec in self:
            if rec.is_computed and not rec.compute_expression:
                raise ValidationError(_("Field '%s' thiếu công thức.") % rec.field_name)

class SmartbizStock_DynamicReportBase(models.AbstractModel):
    _name = "smartbiz_stock.dynamic_report_base"
    _description = "Dynamic Report Base"
    dummy = fields.Boolean(string='Dummy')


    DEFAULT_OUTER = "report_outer"
    DEFAULT_BASE  = "base"

    # ---- Helper thay token trong compute_expression ----
    def _replace_tokens(self, expr: str, kw: dict) -> str:
        """Giữ nguyên {df_utc}/{dt_utc} cho _safe_format_sql xử lý; còn lại
        biến thành NULLIF(COALESCE(alias,0),0) để an toàn phép chia."""
        pattern = r"\{([a-zA-Z_][a-zA-Z0-9_\.]*)\}"

        def _sub(match):
            tok = match.group(1)
            if tok in (kw or {}):
                return "{" + tok + "}"
            if "." in tok:
                return f"NULLIF(COALESCE({tok},0),0)"
            return f"NULLIF(COALESCE({self.DEFAULT_OUTER}.{tok},0),0)"

        return re.sub(pattern, _sub, expr)

    # ---- abstract ----
    def _core_sql(self):
        raise NotImplementedError

    # ---- Chỉ format các key có cung cấp (có default) ----
    def _safe_format_sql(self, sql: str, kw: dict) -> str:
        """
        Chỉ thay các khóa ta cung cấp (df_utc/dt_utc), tránh .format nuốt {...} khác.
        Có giá trị mặc định để rebuild tổng không bị thiếu tham số.
        """
        defaults = {
            'df_utc': '1970-01-01 00:00:00',
            'dt_utc': '2099-12-31 23:59:59',
        }
        data = {**defaults, **(kw or {})}
        for k, v in data.items():
            sql = sql.replace(f'{{{k}}}', str(v))
        # nếu còn placeholder bắt buộc thì báo
        if '{df_utc}' in sql or '{dt_utc}' in sql:
            raise UserError(_("Thiếu tham số df_utc/dt_utc cho SQL."))
        return sql

    # ---- Layer-3: computed alias (dựa vào available_fields) ----
    def _build_dynamic_parts(self, available_fields=None, **fmt):
        specs, w_select = [], []
        ALN = self.env['smartbiz_stock.dynamic_report_alias_line'].sudo()
        known = set(self._fields) | set(available_fields or [])
        token_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_\.]*)\}")

        for ln in ALN.search([('is_computed', '=', True)]):
            raw_expr = ln.compute_expression or ""
            missing = []
            for tok in token_re.findall(raw_expr):
                if '.' in tok or tok in fmt:
                    continue
                if tok not in known:
                    missing.append(tok)
            if missing:
                _logger.warning("[DynamicReport] Skip '%s' thiếu cột: %s", ln.field_name, ", ".join(missing))
                continue

            expr = self._replace_tokens(raw_expr, fmt)
            w_select.append(f"({expr}) AS {ln.field_name}")

            langs = self.env['res.lang'].search([('active', '=', True)]).mapped('code')
            specs.append({
                'name': ln.field_name,
                'field_type': ln.field_type,
                'desc_json': {c: ln.with_context(lang=c).field_label or ln.field_name for c in langs},
            })

        return {
            'cte_select': "",
            'outer_select': "",
            'wrapper_select': ",\n        ".join(w_select),
            'group_by': "",
            'specs': specs,
        }

    # ---- Template (non-computed lines) ----
    def _template_parts(self):
        """
        Đọc alias đang active của Template phù hợp với model, NHƯNG
        chỉ giữ các alias mà biểu thức 'alias' của chúng tham chiếu các
        alias bảng thực sự tồn tại trong _core_sql() của model này.
        """
        import re
        TPL = self.env['smartbiz_stock.dynamic_report_template'].sudo()
        AL  = self.env['smartbiz_stock.dynamic_report_alias'].sudo()

        # Phân tích alias bảng hiện có trong core SQL của model này
        core_sql = self._core_sql()

        # Bắt alias sau FROM/JOIN:  ... FROM table t  | JOIN schema.table AS tt | JOIN (subquery) wh ...
        # Hỗ trợ AS tùy chọn.
        alias_pat = re.compile(
            r'\b(?:FROM|JOIN)\s+(?:\([^\)]*\)|[a-zA-Z0-9_\."]+)\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b',
            re.IGNORECASE
        )
        table_aliases = set(alias_pat.findall(core_sql))

        def _aliases_in_expr(expr: str) -> set:
            """
            Trích các 'prefix' dạng   <alias>.<field>   trong biểu thức alias.
            Ví dụ: 'pt.name' -> {'pt'},  'split_part(pp.default_code, ...)' -> {'pp'}.
            """
            # Cho phép dạng "alias.field" hoặc "alias.\"FieldName\"" trong biểu thức
            hits = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.', expr or '')
            return set(hits)

        # 1) tìm template phù hợp
        tpl = TPL.search([
            ('alias_ids.report_model','in',[self._name, False, '']),
            ('state', '=', 'active'),
        ], limit=1)
        if not tpl:
            return "", "", []

        sel, grp, specs = [], [], []
        langs = self.env['res.lang'].search([('active','=',True)]).mapped('code')
        CAST  = {'integer':'::int','float':'::numeric','date':'::date'}

        def _alias_text(expr: str) -> str:
            # Lấy label theo ngôn ngữ đang duyệt
            lang = (self.env.context.get('lang') or self.env.user.lang or "en_US").replace("'", "''")
            # Xử lý jsonb -> text nếu cần, còn lại ép về text
            return (f"CASE WHEN pg_typeof({expr})='jsonb'::regtype "
                    f"THEN COALESCE(({expr})::jsonb ->> '{lang}', ({expr})::jsonb ->> 'en_US') "
                    f"ELSE ({expr})::text END")

        # 2) lặp qua alias active
        for a in tpl.alias_ids.filtered(lambda a: a.state == 'active'):
            raw = (a.alias or '').strip()
            if not raw:
                continue

            # --- LỌC: nếu biểu thức alias tham chiếu alias bảng không có trong core SQL → bỏ ---
            needed = _aliases_in_expr(raw)
            # Cho phép không có alias (chỉ là tên cột/biểu thức thuần), ví dụ "lot", "regexp_replace(...)".
            if needed and not needed.issubset(table_aliases):
                _logger.info("[DynamicReport] Bỏ alias '%s' (expr=%s) vì thiếu table alias: %s; core có: %s",
                             a.name, raw, ", ".join(sorted(needed - table_aliases)), ", ".join(sorted(table_aliases)))
                continue

            src_txt = _alias_text(raw)
            sep     = (a.separator or '_').replace("'", "''")
            regex   = (a.regex_pattern or '').replace("'", "''")

            # 3) dòng tĩnh (không is_computed)
            for ln in a.lines_ids.filtered(lambda l: not l.is_computed).sorted('sequence'):
                base = src_txt
                if ln.segment_index:
                    base = f"split_part({src_txt},'{sep}',{ln.segment_index})"
                elif ln.regex_group:
                    if not regex:
                        raise UserError(_("Alias '%s' thiếu regex_pattern.") % a.name)
                    base = f"(regexp_match({src_txt},'{regex}'))[{ln.regex_group}]"

                cast = CAST.get(ln.field_type, "")
                sel.append(f"NULLIF({base},''){cast} AS {ln.field_name}")
                grp.append(base)
                specs.append({
                    'name'      : ln.field_name,
                    'field_type': ln.field_type,
                    'desc_json' : {c: ln.with_context(lang=c).field_label or ln.field_name for c in langs},
                })

        return ",\n                    ".join(sel), ", ".join(grp), specs

    # ---- UI helpers ----
    @api.model
    def _set_field_translations(self, field_rec, translations):
        base_lang = 'en_US' if 'en_US' in translations else next(iter(translations))
        if field_rec.with_context(lang=base_lang).field_description != translations[base_lang]:
            field_rec.with_context(lang=base_lang).write({'field_description': translations[base_lang]})
        for lang_code, text in translations.items():
            if lang_code == base_lang:
                continue
            if field_rec.with_context(lang=lang_code).field_description != text:
                field_rec.with_context(lang=lang_code).write({'field_description': text})

    def sync_dynamic_fields(self, model_name, field_specs, reset=False):
        IrModel = self.env['ir.model'].sudo()
        mdl = IrModel.search([('model', '=', model_name)], limit=1)
        if not mdl:
            return
        cr = self.env.cr
        if reset:
            cr.execute("""
                DELETE FROM ir_model_fields
                 WHERE model=%s AND substr(name,1,2)='x_'
            """, (model_name,))
        else:
            keep = [fs['name'] for fs in field_specs]
            cr.execute("""
                DELETE FROM ir_model_fields
                 WHERE model=%s AND substr(name,1,2)='x_' AND NOT (name = ANY(%s))
            """, (model_name, keep))
        cr.commit()

        TTYPE_MAP = {"char":"char", "integer":"integer", "float":"float", "date":"date"}
        IrField = self.env['ir.model.fields'].sudo()
        for fs in field_specs:
            fname, ttype = fs['name'], TTYPE_MAP.get(fs['field_type'], 'char')
            translations = fs.get('desc_json') or {'en_US': fname}
            fld = IrField.search([('model', '=', model_name), ('name', '=', fname)], limit=1)
            if not fld:
                fld = IrField.create({
                    'name': fname,
                    'model_id': mdl.id,
                    'ttype': ttype,
                    'state': 'manual',
                    'readonly': False,
                    'store': True,
                    'field_description': translations.get('en_US') or fname,
                })
            self._set_field_translations(fld, translations)

    def _ensure_view_ext(self, field_names):
        View = self.env['ir.ui.view'].sudo()
        xml = ''.join(f"<field name='{f}'  optional='show'/>" for f in field_names)
        for vt in ('tree', 'pivot', 'graph'):
            base = View.search([
                ('model', '=', self._name), ('type', '=', vt), ('inherit_id', '=', False)
            ], limit=1)
            if not base:
                continue
            name = f"{self._name}_{vt}_dyn"
            View.search([('inherit_id', '=', base.id), ('name', '=', name)]).unlink()
            View.create({
                'name': name,
                'model': self._name,
                'type': vt,
                'inherit_id': base.id,
                'mode': 'extension',
                'arch': f"<data><xpath expr='/*' position='inside'>{xml}</xpath></data>",
            })

    def _default_action_for_model(self):
        Act = self.env['ir.actions.act_window'].sudo()
        View = self.env['ir.ui.view'].sudo()
        act = Act.search([('res_model', '=', self._name)], limit=1)
        if act:
            return act.read()[0]
        modes = []
        for vt in ('tree', 'pivot', 'graph', 'form'):
            if View.search([('model', '=', self._name), ('type', '=', vt), ('inherit_id', '=', False)], limit=1):
                modes.append(vt)
        view_mode = ','.join(modes) or 'tree'
        return {
            'type': 'ir.actions.act_window',
            'name': self._description or self._name,
            'res_model': self._name,
            'view_mode': view_mode,
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    # ---- REBUILD VIEW (đã vá 2-phase) ----
    def _rebuild_view(self, reset_fields=True, return_action=False, **kw):
        alias_outer = self.DEFAULT_OUTER
        sel_tpl, grp_tpl, specs_tpl = self._template_parts()

        # Phase 1: lấy outer_select (nếu subclass cung cấp)
        dyn_1 = self._build_dynamic_parts(**kw)
        outer_select_1 = (dyn_1.get('outer_select') or '')

        def _extract_aliases(sql_chunk: str):
            return set(re.findall(r"\sAS\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_chunk or '', flags=re.IGNORECASE))
        future_aliases = _extract_aliases(sel_tpl) | _extract_aliases(outer_select_1)

        # Phase 2: build computed cho phép tham chiếu alias layer-2
        dyn = self._build_dynamic_parts(available_fields=future_aliases, **kw)

        cte_select = ",\n    ".join(x for x in [sel_tpl, dyn.get('cte_select') or ''] if x)
        group_by   = ", ".join  (x for x in [grp_tpl, dyn.get('group_by')   or ''] if x)
        specs      = (specs_tpl or []) + (dyn.get('specs') or [])

        sql_core = self._core_sql()

        def _smart_insert_list(sql: str, token: str, items_sql: str) -> str:
            if token not in sql:
                return sql
            if not (items_sql and items_sql.strip()):
                return sql.replace(token, '')
            left, right = sql.split(token, 1)
            m = re.search(r"([^\s])\s*$", left)
            prev = m.group(1) if m else ''
            sep_left = ' ' if prev == ',' else ', '
            need_trailing = True
            rstrip = right.lstrip()
            if not rstrip or re.match(r"^(FROM|WHERE|GROUP|ORDER|LIMIT|\))\b", rstrip, re.IGNORECASE) or rstrip.startswith(','):
                need_trailing = False
            sep_right = ', ' if need_trailing else ''
            return left + sep_left + items_sql.strip() + sep_right + right

        inner_sql = sql_core
        inner_sql = _smart_insert_list(inner_sql, '--[[EXTRA_SELECT]]', cte_select or '')
        inner_sql = _smart_insert_list(inner_sql, '--[[EXTRA_GROUP]]',  group_by   or '')

        outer_select  = (dyn.get('outer_select')   or '').strip()
        wrapper_select= (dyn.get('wrapper_select') or '').strip()

        final_sql = inner_sql
        if outer_select or wrapper_select:
            final_sql  = "WITH base AS (\n" + inner_sql + "\n)\n"
            final_sql += f",\n{alias_outer} AS (\n"
            if outer_select:
                final_sql += f"    SELECT base.*, {outer_select}\n    FROM base\n)\n"
            else:
                final_sql += "    SELECT base.*\n    FROM base\n)\n"
            final_sql += f"SELECT {alias_outer}.*"
            if wrapper_select:
                final_sql += ",\n       " + wrapper_select
            final_sql += f"\nFROM {alias_outer}"

        final_sql = self._safe_format_sql(final_sql, kw)
        final_sql = re.sub(r",\s*,\s*", ", ", final_sql)
        for kwd in ("FROM","GROUP","ORDER","LIMIT"):
            final_sql = re.sub(rf",\s*(?=\b{kwd}\b)", "", final_sql, flags=re.IGNORECASE)

        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute(f"CREATE OR REPLACE VIEW {self._table} AS (\n{final_sql}\n)")

        self.sync_dynamic_fields(self._name, specs, reset=reset_fields)
        self._ensure_view_ext([s['name'] for s in specs])
        self.env.invalidate_all()
        return self._default_action_for_model() if return_action else True

class SmartbizStock_OnhandReport(models.Model):
    _name = "smartbiz_stock.onhand_report"
    _rec_name = "product_id"
    _inherit = ['smartbiz_stock.dynamic_report_base']
    _auto=False
    _description = "Onhand Report"
    location_id = fields.Many2one('stock.location', string='Location')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    last_inventory_date = fields.Datetime(string='Last Inventory Date')
    quantity = fields.Float(string='Quantity')


    # ======= SQL gốc + placeholder =======
    def _core_sql(self):
        return """
            SELECT
                sq.id          AS id,
                sq.location_id,
                sq.product_id,
                sq.lot_id,
                --[[EXTRA_SELECT]]
                sq.package_id,
                MAX(sm.date)   AS last_inventory_date,
                sq.quantity
            FROM stock_quant sq
            JOIN stock_move_line sml ON (
                (sq.lot_id IS NULL OR sq.lot_id = sml.lot_id)
                AND sq.product_id = sml.product_id
                AND (
                    (sq.location_id = sml.location_id
                     AND (sq.package_id IS NULL OR sq.package_id = sml.package_id))
                  OR (sq.location_id = sml.location_dest_id
                     AND (sq.package_id IS NULL OR sq.package_id = sml.result_package_id))
                )
            )
            JOIN stock_move sm ON sml.move_id = sm.id
            JOIN product_product pp ON pp.id = sq.product_id
            LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN stock_lot sl  ON sl.id = sq.lot_id
            WHERE sm.is_inventory IS TRUE
            GROUP BY
                sq.id, sq.location_id, sq.product_id, sq.lot_id,
                sq.package_id, sq.quantity
                --[[EXTRA_GROUP]]
        """

class SmartbizStock_InventoryReport(models.Model):
    _name = "smartbiz_stock.inventory_report"
    _rec_name = "product_id"
    _inherit = ['smartbiz_stock.dynamic_report_base']
    _auto=False
    _description = "Inventory Report"
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    uom_id = fields.Many2one('uom.uom', string='UoM')
    initial_quantity = fields.Float(string='Initial Quantity')
    initial_weight = fields.Float(string='Initial Weight')
    normal_in_quantity = fields.Float(string='Normal In Quantity')
    normal_in_weight = fields.Float(string='Normal In Weight')
    adjustment_in_quantity = fields.Float(string='Adjustment In Quantity')
    adjustment_in_weight = fields.Float(string='Adjustment In Weight')
    total_in_quantity = fields.Float(string='Total In Quantity')
    total_in_weight = fields.Float(string='Total In Weight')
    normal_out_quantity = fields.Float(string='Normal Out Quantity')
    normal_out_weight = fields.Float(string='Normal Out Weight')
    adjustment_out_quantity = fields.Float(string='Adjustment Out Quantity')
    adjustment_out_weight = fields.Float(string='Adjustment Out Weight')
    total_out_quantity = fields.Float(string='Total Out Quantity')
    total_out_weight = fields.Float(string='Total Out Weight')
    final_quantity = fields.Float(string='Final Quantity')
    final_weight = fields.Float(string='Final Weight')
    currency_id = fields.Many2one('res.currency', string='Currency')
    initial_value = fields.Monetary(string='Initial Value')
    normal_in_value = fields.Monetary(string='Normal In Value')
    adjustment_in_value = fields.Monetary(string='Adjustment In Value')
    total_in_value = fields.Monetary(string='Total In Value')
    normal_out_value = fields.Monetary(string='Normal Out Value')
    adjustment_out_value = fields.Monetary(string='Adjustment Out Value')
    total_out_value = fields.Monetary(string='Total Out Value')
    final_value = fields.Monetary(string='Final Value')


    # ---------- SQL gốc + placeholder ----------
    def _core_sql(self):
        # rút gọn phần WITH ... SELECT ... tính toán cho ngắn
        return """
            WITH inventory_data AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    pt.weight as product_weight,
                    uom.id as uom_id,  -- UOM (Đơn vị tính)
                    uom.factor as uom_factor,  -- Tỉ lệ chuyển đổi đơn vị tính
                    uom_category.name->>'en_US' as uom_category,  -- Trích xuất giá trị 'en_US' từ JSON của uom_category.name
                    sm.price_unit AS price_unit,  -- Price Unit from Stock Move
                    rc.currency_id,  -- Lấy currency_id từ bảng res_company
                    SUM(CASE WHEN sm.date < '{df_utc}' AND sml.state = 'done' THEN sml.quantity ELSE 0 END) as initial_quantity,
                    
                    -- Normal In: Sản phẩm được nhập vào vị trí nội bộ và không phải là điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{df_utc}' AND sm.date <= '{dt_utc}' 
                             AND sml.state = 'done' 
                             AND loc_dest.usage = 'internal' 
                             AND loc_src.usage != 'internal'  -- Loại bỏ giao dịch nội bộ trong cùng một kho
                             AND loc_src.usage != 'inventory'  -- Loại bỏ điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as normal_in_quantity,
                    
                    -- Adjustment In: Sản phẩm được nhập vào từ điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{df_utc}' AND sm.date <= '{dt_utc}' 
                             AND sml.state = 'done' 
                             AND loc_dest.usage = 'internal'  -- Nhập vào kho nội bộ
                             AND loc_src.usage = 'inventory'  -- Nguồn từ điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as adjustment_in_quantity,
                    
                    -- Normal Out: Sản phẩm được xuất khỏi kho đến một vị trí không phải là điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{df_utc}' AND sm.date <= '{dt_utc}' 
                             AND sml.state = 'done' 
                             AND loc_src.usage = 'internal'  -- Xuất từ kho nội bộ
                             AND loc_dest.usage != 'internal'  -- Không phải di chuyển nội bộ trong kho
                             AND loc_dest.usage != 'inventory'  -- Không phải điều chỉnh tồn kho
                             THEN sml.quantity ELSE 0 END) as normal_out_quantity,
                    
                    -- Adjustment Out: Sản phẩm được xuất từ điều chỉnh tồn kho
                    SUM(CASE WHEN sm.date >= '{df_utc}' AND sm.date <= '{dt_utc}' 
                             AND sml.state = 'done' 
                             AND loc_src.usage = 'inventory'  -- Nguồn từ điều chỉnh tồn kho
                             AND loc_dest.usage = 'internal'  -- Xuất vào kho nội bộ
                             THEN sml.quantity ELSE 0 END) as adjustment_out_quantity,
                    
                    -- Final Quantity: Tổng số lượng tồn kho cuối kỳ
                    SUM(CASE WHEN sm.date <= '{dt_utc}' AND sml.state = 'done' THEN sml.quantity ELSE 0 END) as final_quantity,
                    
                    -- Warehouse ID (dựa trên nguồn hoặc đích)
                    CASE WHEN loc_src.usage = 'internal' THEN loc_src.warehouse_id ELSE loc_dest.warehouse_id END as warehouse_id
                FROM 
                    stock_move_line sml
                JOIN
                    stock_move sm ON sml.move_id = sm.id
                JOIN
                    stock_location loc_src ON sml.location_id = loc_src.id
                JOIN
                    stock_location loc_dest ON sml.location_dest_id = loc_dest.id
                JOIN
                    product_product pp ON sml.product_id = pp.id
                JOIN
                    product_template pt ON pp.product_tmpl_id = pt.id
                JOIN
                    uom_uom uom ON sml.product_uom_id = uom.id  -- Thêm UOM (Đơn vị tính) vào JOIN
                JOIN
                    uom_category ON uom.category_id = uom_category.id  -- Thêm uom_category vào JOIN
                JOIN
                    res_company rc ON sm.company_id = rc.id  -- Thêm liên kết với bảng res_company để lấy currency_id
                WHERE sml.state = 'done'
                GROUP BY 
                    sml.product_id, sml.lot_id, pt.weight, sm.price_unit, rc.currency_id, uom.id, uom.factor, uom_category.name, loc_src.warehouse_id, loc_dest.warehouse_id, loc_src.usage, loc_dest.usage
            )
            SELECT 
                ROW_NUMBER() OVER() as id,
                inv.warehouse_id,
                inv.product_id,
                inv.lot_id,
                --[[EXTRA_SELECT]]
                inv.uom_id,  -- UOM ID (Đơn vị tính)
                inv.currency_id,  -- Thêm trường currency_id vào view
                inv.initial_quantity,
                
                -- Tính trọng lượng dựa trên UOM (Nếu thuộc nhóm khối lượng, sử dụng factor, nếu không, sử dụng weight)
                CASE WHEN inv.uom_category = 'Weight' THEN inv.initial_quantity / inv.uom_factor ELSE inv.initial_quantity * inv.product_weight END as initial_weight,
                
                inv.normal_in_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_in_quantity / inv.uom_factor ELSE inv.normal_in_quantity * inv.product_weight END as normal_in_weight,
                
                inv.adjustment_in_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_in_quantity / inv.uom_factor ELSE inv.adjustment_in_quantity * inv.product_weight END as adjustment_in_weight,
                
                (inv.normal_in_quantity + inv.adjustment_in_quantity) as total_in_quantity,
                (CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_in_quantity / inv.uom_factor ELSE inv.normal_in_quantity * inv.product_weight END 
                + CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_in_quantity / inv.uom_factor ELSE inv.adjustment_in_quantity * inv.product_weight END) as total_in_weight,
                
                inv.normal_out_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_out_quantity / inv.uom_factor ELSE inv.normal_out_quantity * inv.product_weight END as normal_out_weight,
                
                inv.adjustment_out_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_out_quantity / inv.uom_factor ELSE inv.adjustment_out_quantity * inv.product_weight END as adjustment_out_weight,
                
                (inv.normal_out_quantity + inv.adjustment_out_quantity) as total_out_quantity,
                (CASE WHEN inv.uom_category = 'Weight' THEN inv.normal_out_quantity / inv.uom_factor ELSE inv.normal_out_quantity * inv.product_weight END 
                + CASE WHEN inv.uom_category = 'Weight' THEN inv.adjustment_out_quantity / inv.uom_factor ELSE inv.adjustment_out_quantity * inv.product_weight END) as total_out_weight,
                
                inv.final_quantity,
                CASE WHEN inv.uom_category = 'Weight' THEN inv.final_quantity / inv.uom_factor ELSE inv.final_quantity * inv.product_weight END as final_weight,
                
                -- Calculating values based on price_unit
                inv.initial_quantity * inv.price_unit as initial_value,
                inv.normal_in_quantity * inv.price_unit as normal_in_value,
                inv.adjustment_in_quantity * inv.price_unit as adjustment_in_value,
                (inv.normal_in_quantity * inv.price_unit + inv.adjustment_in_quantity * inv.price_unit) as total_in_value,
                inv.normal_out_quantity * inv.price_unit as normal_out_value,
                inv.adjustment_out_quantity * inv.price_unit as adjustment_out_value,
                (inv.normal_out_quantity * inv.price_unit + inv.adjustment_out_quantity * inv.price_unit) as total_out_value,
                inv.final_quantity * inv.price_unit as final_value
            FROM 
                inventory_data inv
            JOIN product_product pp ON pp.id = inv.product_id
            JOIN stock_lot sl  ON sl.id = inv.lot_id
            LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    
           
        """

class SmartbizStock_MoveLineReport(models.Model):
    _name = "smartbiz_stock.move_line_report"
    _rec_name = "product_id"
    _inherit = ['smartbiz_stock.dynamic_report_base']
    _auto=False
    _description = "Move Line Report"
    create_date = fields.Datetime(string='Create Date')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one('uom.uom', string='Product UoM')
    quantity = fields.Float(string='Quantity')
    date = fields.Datetime(string='Date')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    result_package_id = fields.Many2one('stock.quant.package', string='Result Package')
    location_id = fields.Many2one('stock.location', string='Location')
    location_dest_id = fields.Many2one('stock.location', string='Location Dest')
    picking_type_id = fields.Many2one('stock.picking.type', string='Picking Type')
    picking_id = fields.Many2one('stock.picking', string='Picking')
    move_id = fields.Many2one('stock.move', string='Move')
    partner_id = fields.Many2one('res.partner', string='Partner')
    state = fields.Selection([('draft','Draft'),('waiting','Waiting'),('confirmed','Confirmed'),('partially_available','Partially Available'),('assigned','Assigned'),('done','Done'),('cancel','Cancel'),], string='State')


    def _core_sql(self):
        return """
            SELECT
                sml.id                  AS id,
                sml.product_id,
                --[[EXTRA_SELECT]]
                sml.product_uom_id,
                sml.quantity            AS quantity,
                sml.create_date,
                sml.date,
                sml.lot_id,
                sml.package_id,
                sml.result_package_id,
                sml.location_id,
                sml.location_dest_id,
                sm.picking_type_id,
                sm.picking_id,
                sm.id                   AS move_id,
                sp.partner_id           AS partner_id,
                sm.state
            FROM   stock_move_line sml
            LEFT JOIN   stock_move      sm  ON sm.id = sml.move_id
            JOIN   product_product pp  ON pp.id = sml.product_id
            LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN stock_lot sl ON sl.id = sml.lot_id    
            LEFT JOIN stock_picking sp ON sp.id = sm.picking_id
            GROUP BY
                sml.id,
                sml.product_id,
                sml.product_uom_id,
                sml.quantity,
                sml.date,
                sml.lot_id,
                sml.package_id,
                sml.result_package_id,
                sml.location_id,
                sml.location_dest_id,
                sm.picking_type_id,
                sm.picking_id,
                sm.id,
                sp.partner_id,
                sm.state
                --[[EXTRA_GROUP]]
        """

class stock_packagelevel(models.Model):
    _inherit = ['stock.package_level']
    name = fields.Char(store='True')


    def _generate_moves(self):
        return

class SmartbizStock_InventoryPeriod(models.Model):
    _name = "smartbiz_stock.inventory_period"
    _description = "Inventory Period"
    name = fields.Char(string='Name')
    date_start = fields.Date(string='Date Start')
    date_end = fields.Date(string='Date End')
    company_id = fields.Many2one('res.company', string='Company')
    inventory_ids = fields.One2many('smartbiz_stock.inventory', 'period_id')


class SmartbizStock_Inventory(models.Model):
    _name = "smartbiz_stock.inventory"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Inventory"
    name = fields.Char(string='Name', default = 'New')
    date = fields.Datetime(string='Date', required=True)
    period_id = fields.Many2one('smartbiz_stock.inventory_period', string='Period', required=True)
    set_count = fields.Selection([('empty','Empty'),('current_quantity','Current Quantity'),], string='Set Count', default = 'empty')
    user_id = fields.Many2one('res.users', string='User')
    company_id = fields.Many2one('res.company', string='Company')
    warehouse_ids = fields.Many2many('stock.warehouse', string='Warehouse')
    location_ids = fields.Many2many('stock.location', string='Location')
    category_ids = fields.Many2many('product.category', string='Category')
    product_ids = fields.Many2many('product.product', string='Product')
    lot_ids = fields.Many2many('stock.lot', string='Lot')
    line = fields.Integer(string='Line', compute='_compute_line', store=True)
    line_ids = fields.One2many('smartbiz_stock.inventory_line', 'inventory_id')
    state = fields.Selection([('draft','Draft'),('in_progress','In Progress'),('done','Done'),('cancel','Cancel'),], string= 'Status', readonly= False, copy = True, index = False, default = 'draft')


    @api.depends('line_ids')
    def _compute_line(self):
        for record in self:
            count = record.line_ids.search_count([('inventory_id', '=', record.id)])
            record.line = count

    def action_draft_start_inventory(self):
        """ Bắt đầu kiểm kê - lọc danh sách kiểm kê theo location nếu có """
        self.state = 'in_progress'
        self.line_ids.unlink()
        self._generate_inventory_lines()

        
        
    def action_draft_generate_inventory(self):
        """ Bắt đầu kiểm kê - lọc danh sách kiểm kê theo location nếu có """
        self.line_ids.unlink()
        self._generate_inventory_lines()

        
        
    def action_draft_select_quant(self):
        action = self.env.ref('smartbiz_inventory.action_open_stock_quant_editable').sudo().read()[0]  
        action['domain'] = [('company_id', '=', self.company_id.id),('location_id.usage', '=', 'internal')]  
        action['context'] = {
            'default_inventory_id': self.id,
            'from_inventory_select': True,
            'search_default_internal_location': 1,
        }
        return action

        
        
    def action_in_progress_validate(self):
        return {
            'name': 'Xác nhận kiểm kê',
            'type': 'ir.actions.act_window',
            'res_model': 'smartbiz_inventory.inventory_validate_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inventory_id': self.id},
        } 

        
        
    def action_in_progress_cancel(self):
        return {
            'name': 'Hủy kiểm kê',
            'type': 'ir.actions.act_window',
            'res_model': 'smartbiz_inventory.inventory_cancel_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inventory_id': self.id},
        }

        
        
    def action_in_progress_back_to_draft(self):
        for inventory in self:
            lines = self.env['smartbiz.inventory.line'].search([('inventory_id', '=', inventory.id)])
            if lines:
                lines.unlink()
            inventory.state = 'draft'

        
        
    def _generate_inventory_lines(self):
        """Tạo danh sách kiểm kê dựa trên location hoặc warehouse nếu có"""
        domain = [('company_id', '=', self.company_id.id)]

        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        if self.category_ids:
            domain.append(('product_categ_id', 'in', self.category_ids.ids))

        location_domain = []

        # Nếu có warehouse_ids, lấy toàn bộ vị trí con của các kho
        if self.warehouse_ids:
            for warehouse in self.warehouse_ids:
                warehouse_locations = self.env['stock.location'].search([
                    ('id', 'child_of', warehouse.view_location_id.id)
                ]).ids
                location_domain.extend(warehouse_locations)

        # Nếu có inventory_location_ids, chỉ dùng danh sách này và bỏ qua vị trí từ kho
        if self.location_ids:
            location_domain = self.location_ids.ids

        # Thêm domain lọc theo vị trí nếu có dữ liệu hợp lệ
        if location_domain:
            domain.append(('location_id', 'in', location_domain))

        quants = self.env['stock.quant'].search(domain, order='location_id, product_id desc')

        vals_list = [{
            'inventory_id': self.id,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'package_id': quant.package_id.id if quant.package_id else False,
            'location_id': quant.location_id.id,
            'company_id': self.company_id.id,
            'quantity': quant.quantity,
            'quantity_counted': 0 if self.set_count == 'empty' else quant.quantity,
            'quant_id': quant.id,
            'note': '',
        } for quant in quants]

        if vals_list:
            self.env['smartbiz_stock.inventory_line'].create(vals_list)

    def action_count_detail(self):
        action = self.env["ir.actions.actions"]._for_xml_id("smartbiz_stock.act_smartbiz_stock_inventory_2_smartbiz_stock_inventory_line")
        context = eval(action['context'])
        context.update(dict(self._context,default_inventory_id=self.id))
        action['context'] = context
        action['domain'] = [('inventory_id', '=', self.id)]

        return action

    @api.model
    def create(self, values):
        if values.get('name', 'New') == 'New':
           values['name'] = self.env['ir.sequence'].next_by_code('smartbiz_stock.inventory') or 'New'


        res = super().create(values)


        return res

class SmartbizStock_InventoryLine(models.Model):
    _name = "smartbiz_stock.inventory_line"
    _inherit = ['smartbiz.workflow_base', 'mail.thread', 'mail.activity.mixin']
    _description = "Inventory Line"
    inventory_id = fields.Many2one('smartbiz_stock.inventory', string='Inventory', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    location_id = fields.Many2one('stock.location', string='Location')
    company_id = fields.Many2one('res.company', string='Company')
    quantity = fields.Float(string='Quantity')
    quantity_counted = fields.Float(string='Quantity Counted')
    difference = fields.Float(string='Difference', compute='_compute_difference', store=True)
    note = fields.Text(string='Note')
    quant_id = fields.Many2one('stock.quant', string='Quant')
    state = fields.Selection([('pending','Pending'),('counting','Counting'),('done','Done'),('error','Error'),], string= 'Status', readonly= False, copy = True, index = False, default = 'pending')


    @api.depends('quantity', 'quantity_counted')
    def _compute_difference(self):
        for record in self:
            record.difference = record.quantity_counted - record.quantity

class SmartbizStock_InventoryHistory(models.Model):
    _name = "smartbiz_stock.inventory_history"
    _description = "Inventory History"
    inventory_id = fields.Many2one('smartbiz_stock.inventory', string='Inventory')
    date = fields.Date(string='Date')
    company_id = fields.Many2one('res.company', string='Company')
    product_id = fields.Many2one('product.product', string='Product')
    location_id = fields.Many2one('stock.location', string='Location')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    package_id = fields.Many2one('stock.quant.package', string='Package')
    note = fields.Text(string='Note')
    quantity = fields.Float(string='Quantity')
    quantity_after = fields.Float(string='Quantity After')
    difference = fields.Float(string='Difference')


class SmartbizStock_InventoryValidateWizard(models.TransientModel):
    _name = "smartbiz_stock.inventory_validate_wizard"
    _description = "Inventory Validate Wizard"
    inventory_id = fields.Many2one('smartbiz_stock.inventory', string='Inventory')
    apply_inventory = fields.Boolean(string='Apply Inventory', default = 'True')
    has_pending_line = fields.Boolean(string='Has Pending Line', compute='_compute_has_pending_line', store=True)


    @api.depends('inventory_id')
    def _compute_has_pending_line(self):
        for wizard in self:
            pending_lines = wizard.inventory_id.line_ids.filtered(lambda l: l.state != 'counting')

    def action_confirm(self):
        if self.apply_inventory:
            # Gọi validate nhưng chỉ cho dòng đã đếm
            lines_to_validate = self.inventory_id.line_ids.filtered(lambda l: l.state == 'counting' or l.state == 'done')
            lines_to_validate.write({'state': 'done'})
            
            for line in lines_to_validate:
                self.env['smartbiz.inventory.history'].create({
                    'inventory_id': self.inventory_id.id,
                    'name': self.inventory_id.name,
                    'product_id': line.product_id.id,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                    'package_id': line.package_id.id if line.package_id else False,
                    'location_id': line.location_id.id,
                    'company_id': self.inventory_id.company_id.id,
                    'user_id': self.inventory_id.user_id.id if self.inventory_id.user_id else False,
                    'quantity': line.quantity,
                    'quantity_after': line.quantity_counted,
                    'difference': line.difference,
                    'date': fields.Datetime.now(),
                    'note': line.note,
                })
            self.inventory_id.state = 'done'

            # Tạo kiểm kê mới cho các dòng chưa kiểm kê
            pending_lines = self.inventory_id.line_ids.filtered(lambda l: l.state == 'pending')
            if pending_lines:
                new_inv = self.env['smartbiz.inventory'].create({
                    'name': self._generate_inventory_name(),
                    'company_id': self.inventory_id.company_id.id,
                    'user_id': self.inventory_id.user_id.id,
                    'inventory_period_id': self.inventory_id.inventory_period_id.id,
                })
                for line in pending_lines:
                    self.env['smartbiz.inventory.line'].create({
                        'inventory_id': new_inv.id,
                        'product_id': line.product_id.id,
                        'lot_id': line.lot_id.id if line.lot_id else False,
                        'package_id': line.package_id.id if line.package_id else False,
                        'location_id': line.location_id.id,
                        'quantity': line.quantity,
                        'state': 'pending',
                    })
                
                # Xóa các dòng pending trong đơn kiểm kê cũ sau khi đã chuyển sang đơn mới
                pending_lines.unlink()

        return {'type': 'ir.actions.act_window_close'}

    def _generate_inventory_name(self):
        """ Tạo tên kiểm kê mới theo format '<tên gốc> + số thứ tự tăng dần' """
        base_name = self.inventory_id.name

        # Tìm tất cả các bản ghi có tên bắt đầu bằng tên gốc
        existing_names = self.env['smartbiz.inventory'].search([
            ('name', 'ilike', base_name)
        ])

        max_number = 0
        for rec in existing_names:
            suffix = rec.name.replace(base_name, '').strip()
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))

        new_number = str(max_number + 1).zfill(3)
        return f"{base_name}-{new_number}"

class SmartbizStock_InventoryCancelWizard(models.TransientModel):
    _name = "smartbiz_stock.inventory_cancel_wizard"
    _description = "Inventory Cancel Wizard"
    inventory_id = fields.Many2one('smartbiz_stock.inventory', string='Inventory')


    def action_confirm(self):
        """Hủy, không làm gì cả"""
        """Gọi action_cancel để thực hiện hủy kiểm kê"""
        
        self.inventory_id.action_cancel()
        return {'type': 'ir.actions.act_window_close'}

class SmartbizStock_PickingGroupTemplate(models.Model):
    _name = "smartbiz_stock.picking_group_template"
    _description = "Picking Group Template"
    name = fields.Char(string='Name')
    calculate_package = fields.Boolean(string='Calculate Package')
    calculate_value = fields.Boolean(string='Calculate Value')
    picking_group_ids = fields.One2many('smartbiz_stock.picking_group', 'template_id')


class SmartbizStock_PickingGroup(models.Model):
    _name = "smartbiz_stock.picking_group"
    _description = "Picking Group"
    name = fields.Char(string='Name', translate="True")
    field_name = fields.Char(string='Field Name')
    move_type = fields.Selection([('in','In'),('out','Out'),], string='Move Type')
    picking_type_ids = fields.Many2many('stock.picking.type', string='Picking Type')
    template_id = fields.Many2one('smartbiz_stock.picking_group_template', string='Template')


    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('field_name') and not v['field_name'].startswith('x_'):
                v['field_name']=f"x_{v['field_name'].strip().lower()}"
        return super().create(vals_list)

    def write(self, vals):
        if 'field_name' in vals and vals['field_name'] and not vals['field_name'].startswith('x_'):
            vals['field_name']=f"x_{vals['field_name'].strip().lower()}"
        return super().write(vals)

class SmartbizStock_DynamicInventoryReport(models.Model):
    _name = "smartbiz_stock.dynamic_inventory_report"
    _rec_name = "product_id"
    _inherit = ['smartbiz_stock.dynamic_report_base']
    _auto=False
    _description = "Dynamic Inventory Report"
    product_id = fields.Many2one('product.product', string='Product')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    lot_id = fields.Many2one('stock.lot', string='Lot')
    begin_quantity = fields.Float(string='Begin Quantity')
    total_in = fields.Float(string='Total In')
    total_out = fields.Float(string='Total Out')
    end_quantity = fields.Float(string='End Quantity')


    # CORE: để layer-2 bơm chỉ tiêu; join loc_src/loc_dest để nhận biết điều chỉnh
    def _core_sql(self):
        return """
            SELECT
                row_number() OVER() AS id,
                sml.product_id,
                wh.warehouse_id,
                sml.lot_id
                --[[EXTRA_SELECT]]
            FROM  stock_move_line sml
            JOIN  stock_move      sm  ON sm.id = sml.move_id
            JOIN  product_product pp  ON pp.id = sml.product_id
            LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN stock_lot sl  ON sl.id = sml.lot_id
            JOIN stock_location loc_src  ON sm.location_id      = loc_src.id
            JOIN stock_location loc_dest ON sm.location_dest_id = loc_dest.id
            JOIN (
                SELECT id AS location_id, warehouse_id
                FROM stock_location
                WHERE usage='internal'
            ) wh ON wh.location_id IN (sm.location_id, sm.location_dest_id)
            WHERE sm.state = 'done'
            GROUP BY
                sml.product_id, wh.warehouse_id, sml.lot_id
                --[[EXTRA_GROUP]]
        """

    # Layer-2: Template + Adjustment (cộng dồn & SINH FIELD ĐỘNG)
    def _build_group_parts(self, template_rec, df_utc, dt_utc):
        """
        Trả về:
          - cte_select   : SUM/COUNT theo nhóm template + adjustment
          - outer_select : begin/total_in/total_out/end (+ cột adjustment động)
          - group_by     : không thêm
          - specs        : field động (để sync_dynamic_fields tạo x_*)
        """
        calc_pkg = bool(template_rec and template_rec.calculate_package)
        calc_val = bool(template_rec and template_rec.calculate_value)

        langs = self.env['res.lang'].search([('active', '=', True)]).mapped('code')
        def _desc(vi, en):
            return {'vi_VN': vi, 'en_US': en, **{c: en for c in langs if c not in ('vi_VN', 'en_US')}}
        def _sum(cols):
            return " + ".join([f"COALESCE(base.{c},0)" for c in cols]) or "0"

        cte_sel, specs = [], []
        qty_bgn_in, qty_bgn_out = [], []
        qty_in, qty_out = [], []
        pkg_bgn_in, pkg_bgn_out = [], []
        pkg_in, pkg_out = [], []

        # ===== ADJUSTMENT (luôn tính & có cột riêng, đồng thời cộng dồn vào tổng) =====
        # inventory -> internal (nhập điều chỉnh)
        cte_sel.append(f"""
            SUM(CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                     AND sm.state='done'
                     AND loc_src.usage = 'inventory'
                     AND loc_dest.usage = 'internal'
                     AND loc_dest.id = wh.location_id
                 THEN sml.quantity ELSE 0 END) AS adj_in_qty
        """)
        # internal -> inventory (xuất điều chỉnh)
        cte_sel.append(f"""
            SUM(CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                     AND sm.state='done'
                     AND loc_src.usage = 'internal'
                     AND loc_dest.usage = 'inventory'
                     AND sm.location_id = wh.location_id
                 THEN sml.quantity ELSE 0 END) AS adj_out_qty
        """)

        pkg_expr = "COALESCE(sml.result_package_id, sml.package_id)"
        if calc_pkg:
            cte_sel.append(f"""
                COUNT(DISTINCT CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                         AND sm.state='done'
                         AND loc_src.usage = 'inventory'
                         AND loc_dest.usage = 'internal'
                         AND loc_dest.id = wh.location_id
                    THEN {pkg_expr} END) AS adj_in_pkg
            """)
            cte_sel.append(f"""
                COUNT(DISTINCT CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                         AND sm.state='done'
                         AND loc_src.usage = 'internal'
                         AND loc_dest.usage = 'inventory'
                         AND sm.location_id = wh.location_id
                    THEN {pkg_expr} END) AS adj_out_pkg
            """)

        # ===== TEMPLATE GROUPS (LOẠI HẲN inventory để tránh đếm trùng) =====
        # common filter để chặn mọi dịch chuyển liên quan 'inventory'
        not_inventory = "AND loc_src.usage <> 'inventory' AND loc_dest.usage <> 'inventory'"

        if template_rec and template_rec.picking_group_ids:
            for g in template_rec.picking_group_ids:
                code = (g.field_name or '').strip().lower()
                if not code:
                    continue
                ids_sql   = ", ".join(map(str, g.picking_type_ids.ids or [0]))
                is_in     = (g.move_type == 'in')
                loc_field = 'sm.location_dest_id' if is_in else 'sm.location_id'

                qb = f"{code}_bgn"      # trước kỳ
                qd = f"{code}"          # trong kỳ

                # Quantity
                cte_sel.append(f"""
                    SUM(CASE WHEN sml.date < '{df_utc}'
                              AND sm.state='done'
                              AND sm.picking_type_id IN ({ids_sql})
                              AND {loc_field} = wh.location_id
                              {not_inventory}
                         THEN sml.quantity ELSE 0 END) AS {qb},
                    SUM(CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                              AND sm.state='done'
                              AND sm.picking_type_id IN ({ids_sql})
                              AND {loc_field} = wh.location_id
                              {not_inventory}
                         THEN sml.quantity ELSE 0 END) AS {qd}
                """)

                (qty_bgn_in if is_in else qty_bgn_out).append(qb)
                (qty_in if is_in else qty_out).append(qd)

                specs.append({
                    'name': qd, 'field_type': 'float',
                    'desc_json': {c: g.with_context(lang=c).name for c in langs},
                })

                # Packages cho Template (nếu bật) — cũng loại inventory
                if calc_pkg:
                    pb = f"{code}_pkg_bgn"
                    pd = f"{code}_pkg"
                    cte_sel.append(f"""
                        COUNT(DISTINCT CASE WHEN sml.date < '{df_utc}'
                              AND sm.state='done'
                              AND sm.picking_type_id IN ({ids_sql})
                              AND {loc_field} = wh.location_id
                              {not_inventory}
                        THEN {pkg_expr} END) AS {pb},
                        COUNT(DISTINCT CASE WHEN sml.date BETWEEN '{df_utc}' AND '{dt_utc}'
                              AND sm.state='done'
                              AND sm.picking_type_id IN ({ids_sql})
                              AND {loc_field} = wh.location_id
                              {not_inventory}
                        THEN {pkg_expr} END) AS {pd}
                    """)
                    (pkg_bgn_in if is_in else pkg_bgn_out).append(pb)
                    (pkg_in if is_in else pkg_out).append(pd)

                    specs.append({
                        'name': pd, 'field_type': 'integer',
                        'desc_json': {c: g.with_context(lang=c).name + ' (Pkg)' for c in langs},
                    })

        # ===== GHÉP TỔNG (đã cộng dồn adjustment) =====
        expr_bgn_q  = f"(({_sum(qty_bgn_in)}) - ({_sum(qty_bgn_out)}))"
        expr_in_q   = f"(({_sum(qty_in)})  + COALESCE(base.adj_in_qty,0))"
        expr_out_q  = f"(({_sum(qty_out)}) + COALESCE(base.adj_out_qty,0))"
        expr_end_q  = f"(({expr_bgn_q}) + ({expr_in_q}) - ({expr_out_q}))"

        outer_parts = [
            f"{expr_bgn_q} AS begin_quantity",
            f"{expr_in_q}  AS total_in",
            f"{expr_out_q} AS total_out",
            f"{expr_end_q} AS end_quantity",
            # cột điều chỉnh (động) để bạn vẫn xem riêng
            "COALESCE(base.adj_in_qty,0)  AS x_adjustment_in",
            "COALESCE(base.adj_out_qty,0) AS x_adjustment_out",
        ]
        specs += [
            {'name':'x_adjustment_in','field_type':'float','desc_json':_desc('Điều chỉnh nhập','Adjustment In')},
            {'name':'x_adjustment_out','field_type':'float','desc_json':_desc('Điều chỉnh xuất','Adjustment Out')},
        ]

        # ===== PACKAGES (nếu bật): cộng dồn adj + có cột adj riêng =====
        if calc_pkg:
            expr_bgn_p = f"(({_sum(pkg_bgn_in)}) - ({_sum(pkg_bgn_out)}))"
            expr_in_p  = f"(({_sum(pkg_in)})  + COALESCE(base.adj_in_pkg,0))"
            expr_out_p = f"(({_sum(pkg_out)}) + COALESCE(base.adj_out_pkg,0))"
            expr_end_p = f"(({expr_bgn_p}) + ({expr_in_p}) - ({expr_out_p}))"

            outer_parts += [
                f"{expr_bgn_p} AS x_begin_pkg",
                f"{expr_in_p}  AS x_total_pkg_in",
                f"{expr_out_p} AS x_total_pkg_out",
                f"{expr_end_p} AS x_end_pkg",
                "COALESCE(base.adj_in_pkg,0)  AS x_adjustment_pkg_in",
                "COALESCE(base.adj_out_pkg,0) AS x_adjustment_pkg_out",
            ]
            specs += [
                {'name':'x_begin_pkg','field_type':'integer','desc_json':_desc('Tồn gói đầu kỳ','Opening Packages')},
                {'name':'x_total_pkg_in','field_type':'integer','desc_json':_desc('Tổng gói nhập','Packages In')},
                {'name':'x_total_pkg_out','field_type':'integer','desc_json':_desc('Tổng gói xuất','Packages Out')},
                {'name':'x_end_pkg','field_type':'integer','desc_json':_desc('Tồn gói cuối kỳ','Closing Packages')},
                {'name':'x_adjustment_pkg_in','field_type':'integer','desc_json':_desc('Gói điều chỉnh nhập','Adj Packages In')},
                {'name':'x_adjustment_pkg_out','field_type':'integer','desc_json':_desc('Gói điều chỉnh xuất','Adj Packages Out')},
            ]

        # ===== VALUE (nếu bật): dùng cost theo kho; total_* đã gồm adj =====
        if calc_val:
            begin_cost_expr = f"""COALESCE((
                SELECT SUM(svl.value)/NULLIF(SUM(svl.quantity),0)
                  FROM stock_valuation_layer svl
                  JOIN stock_move sm2 ON sm2.id = svl.stock_move_id
                  JOIN stock_location eff ON eff.id = CASE
                        WHEN svl.quantity >= 0 THEN sm2.location_dest_id
                        ELSE sm2.location_id
                      END
                 WHERE svl.product_id = base.product_id
                   AND eff.usage = 'internal'
                   AND eff.warehouse_id = base.warehouse_id
                   AND svl.create_date <= '{df_utc}'
            ),0)"""
            end_cost_expr = f"""COALESCE((
                SELECT SUM(svl.value)/NULLIF(SUM(svl.quantity),0)
                  FROM stock_valuation_layer svl
                  JOIN stock_move sm2 ON sm2.id = svl.stock_move_id
                  JOIN stock_location eff ON eff.id = CASE
                        WHEN svl.quantity >= 0 THEN sm2.location_dest_id
                        ELSE sm2.location_id
                      END
                 WHERE svl.product_id = base.product_id
                   AND eff.usage = 'internal'
                   AND eff.warehouse_id = base.warehouse_id
                   AND svl.create_date <= '{dt_utc}'
            ),0)"""

            outer_parts += [
                f"({expr_bgn_q}) * ({begin_cost_expr}) AS x_begin_value",
                f"({expr_in_q})  * ({end_cost_expr})   AS x_total_in_value",
                f"({expr_out_q}) * ({end_cost_expr})   AS x_total_out_value",
                f"({expr_end_q}) * ({end_cost_expr})   AS x_end_value",
                # value riêng cho adjustment
                f"(COALESCE(base.adj_in_qty,0))  * ({end_cost_expr}) AS x_adjustment_in_value",
                f"(COALESCE(base.adj_out_qty,0)) * ({end_cost_expr}) AS x_adjustment_out_value",
            ]
            specs += [
                {'name':'x_begin_value','field_type':'float','desc_json':_desc('Giá trị đầu kỳ','Opening Value')},
                {'name':'x_total_in_value','field_type':'float','desc_json':_desc('Giá trị nhập','Value In')},
                {'name':'x_total_out_value','field_type':'float','desc_json':_desc('Giá trị xuất','Value Out')},
                {'name':'x_end_value','field_type':'float','desc_json':_desc('Giá trị cuối kỳ','Closing Value')},
                {'name':'x_adjustment_in_value','field_type':'float','desc_json':_desc('Giá trị điều chỉnh nhập','Adj In Value')},
                {'name':'x_adjustment_out_value','field_type':'float','desc_json':_desc('Giá trị điều chỉnh xuất','Adj Out Value')},
            ]

        return (
            ",\n                    ".join(cte_sel),          # cte_select
            ",\n        ".join(outer_parts),                 # outer_select
            "",                                              # group_by
            specs
        )

    # Gộp layer-3 (base) + layer-2 (template + adjustment)
    def _build_dynamic_parts(self, **kw):
        template_rec = kw.get('template_rec')
        df_utc = kw.get('df_utc'); dt_utc = kw.get('dt_utc')
        base = super()._build_dynamic_parts(**kw)
        c2, o2, g2, s2 = self._build_group_parts(template_rec, df_utc, dt_utc)
        return {
            'cte_select': ",\n    ".join(filter(None, [base['cte_select'], c2])),
            'outer_select': ",\n        ".join(filter(None, [base['outer_select'], o2])),
            'wrapper_select': base['wrapper_select'],
            'group_by': ", ".join(filter(None, [base['group_by'], g2])),
            'specs': base['specs'] + s2,
        }

