# -*- coding: utf-8 -*-
"""smartbiz_nomenclature.models.sql_tools – dynamic field & view generator"""

from odoo import api, fields as _f, SUPERUSER_ID, tools
import json, re
from odoo.exceptions import UserError, ValidationError
class SQLTools:
    """Helper class được dùng bởi các model báo cáo để:

    1. Sinh câu `SELECT … GROUP BY` trích xuất phân đoạn tên.
    2. Đảm bảo các trường `x_…` tồn tại trong **ir_model_fields** _và_ trong
       registry hiện tại (để có thể render view ngay).
    3. Tạo/ cập nhật tree / pivot / graph view kế thừa hiển thị các trường.
    """

    # ------------------------------------------------------------------
    # ctor
    # ------------------------------------------------------------------
    def __init__(self, env):
        self.env  = env
        self.Tmpl = env['smartbiz.nomenclature.template']

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _domain_sql(self, model_name, domain, alias):
        """Chuyển domain Python/JSON thành SQL và thay table bằng *alias*."""
        if not domain:
            return "TRUE"
        dom = json.loads(domain) if isinstance(domain, str) and domain.strip().startswith('[') else eval(domain)
        wc  = self.env[model_name]._where_calc(dom)
        sql = wc.to_sql()
        return re.sub(r'\b%s\b' % self.env[model_name]._table, alias, sql)

    @staticmethod
    def _expr(self,tmpl, line, alias):
        """
        Sinh biểu thức SQL để trích đoạn từ alias.name, có:
         - nếu name là JSONB (dịch đa ngôn ngữ) → lấy alias.name->>'lang'
         - ngược lại → lấy alias.name trực tiếp
        Sau đó áp dụng regex hoặc split_part như bình thường.
        """
        src = 'name'
        # 1. Xác định ngôn ngữ đang dùng
        lang = (self.env.context.get('lang') or
                self.env.user.lang or
                'en_US')

        # 2. Kiểm tra kiểu cột trong model
        model_name = tmpl.model_name      # vd. 'product.template'
        model_cls  = self.env[model_name]
        field_def  = model_cls._fields.get(src)
        is_translatable = bool(field_def and getattr(field_def, 'translate', False))
        # 3. Xây dựng biểu thức lấy giá trị text
        if is_translatable:
            # cột name dạng JSONB lưu đa ngôn ngữ
            col = f"{alias}.{src}->>'{lang}'"
        else:
            # cột name bình thường (text, char,…)
            col = f"{alias}.{src}"

        # 4. Nếu có regex_pattern → dùng regexp_match
        if tmpl.regex_pattern:
            regexp = tmpl.regex_pattern.replace("'", "''")
            return f"(regexp_match({col}, '{regexp}'))[{line.regex_group}]"

        # 5. Ngược lại thì tách theo separator
        sep = (tmpl.separator or '_').replace("'", "''")

        # với segment_index = 1, thêm CASE WHEN để fallback khi không có dấu phân cách
        if line.segment_index == 1:
            return (
                f"CASE WHEN position('{sep}' in {col}) = 0 "
                f"THEN {col} "
                f"ELSE split_part({col}, '{sep}', 1) END"
            )

        # tách phần thứ N
        return f"split_part({col}, '{sep}', {line.segment_index})"

    # ------------------------------------------------------------------
    # API cho report – build SELECT/GROUP
    # ------------------------------------------------------------------
    def select_group(self, report_model, alias_map):
        """Trả về:
        - select  : chuỗi `expr AS field`
        - group   : chuỗi biểu thức cho GROUP BY
        - labels  : {field: {lang: label}}
        """
        Lang   = self.env['res.lang']
        langs  = Lang.search([('active', '=', True)]).mapped('code')
        field_rules, labels = {}, {}

        # -----------------------------------------------------------
        # 1. Thu thập quy tắc tách cho từng alias
        # -----------------------------------------------------------
        for alias, model_name in alias_map.items():
            tpls = self.Tmpl.search([
                ('model_name', '=', model_name),
                ('active', '=', True),
                ('report_model', 'in', [False, '', report_model])
            ], order='sequence')

            for t in tpls:
                cond = self._domain_sql(model_name,
                                        t.condition_domain,
                                        t.alias_override or alias)
                for ln in t.line_ids:
                    field_rules.setdefault(ln.target_field, []).append(
                        (cond, self._expr(self,t, ln, t.alias_override or alias), ln)
                    )

        # -----------------------------------------------------------
        # 2. Xây dựng SELECT / GROUP BY / LABELS
        # -----------------------------------------------------------
        selects, groups = [], set()

        for fld, rules in field_rules.items():
            # 2.1 Nhãn đa ngôn ngữ
            rec   = rules[0][2]
            multi = {code: rec.with_context(lang=code).field_label or fld
                    for code in langs}
            labels[fld] = multi

            # 2.2 Ghép biểu thức
            expr_parts = []
            for cond, expr_raw, _ln in rules:
                # Bỏ lớp CASE WHEN TRUE … END
                if not cond or cond.strip().upper() == 'TRUE':
                    expr_parts.append(expr_raw)
                else:
                    expr_parts.append(f"CASE WHEN {cond} THEN {expr_raw} END")

            # Một hay nhiều quy tắc → COALESCE
            if len(expr_parts) == 1:
                expr = f"({expr_parts[0]})"
            else:
                expr = f"(COALESCE({', '.join(expr_parts)}))"

            selects.append(f"{expr} AS {fld}")
            groups.add(expr)          # cần GROUP BY cùng biểu thức

        if not selects:
            return "", "", {}

        return (
            ",\n        ".join(selects),      # SELECT …
            ", ".join(sorted(groups)),        # GROUP BY …
            labels
        )

    def delete_fields(self, model_map):
        cr = self.env.cr
        # Chuẩn hoá model_map thành model -> {field: label}
        norm_map = {}
        for model, spec in model_map.items():
            if isinstance(spec, (list, set, tuple)):
                norm_map[model] = {f: f for f in spec}
            else:
                norm_map[model] = dict(spec)

        for model, name_label in norm_map.items():
            cr.execute("""
                DELETE FROM ir_model_fields
                WHERE model = %s
                AND substr(name, 1, 2) = 'x_'
            """, (model,))
        cr.commit()  

    # ------------------------------------------------------------------
    # Đồng bộ trường tuỳ biến
    # ------------------------------------------------------------------
    def sync_fields(self, model_map,reset=False):

        cr = self.env.cr
        # Chuẩn hoá model_map thành model -> {field: label}
        norm_map = {}
        for model, spec in model_map.items():
            if isinstance(spec, (list, set, tuple)):
                norm_map[model] = {f: f for f in spec}
            else:
                norm_map[model] = dict(spec)

                # Xoá các trường dư: giữ lại `keep`
        if reset:
            for model, name_label in norm_map.items():
                cr.execute("""
                    DELETE FROM ir_model_fields
                    WHERE model = %s
                    AND substr(name, 1, 2) = 'x_'
                """, (model,))
        else:
            for model, name_label in norm_map.items():
                keep = list(name_label.keys())
                cr.execute("""
                    DELETE FROM ir_model_fields
                    WHERE model = %s
                    AND substr(name, 1, 2) = 'x_'
                    AND NOT (name = ANY (%s))
                """, (model, keep))
        cr.commit()
        # Tạo / Cập nhật các trường cần thiết
        self.ensure_fields(norm_map)

    def ensure_fields(self, model_map):
        """Tạo/cập nhật trường *manual* và **đăng ký** ngay với registry."""
        cr      = self.env.cr
        IrModel = self.env['ir.model'].sudo()
        lang    = self.env.user.lang or 'en_US'
        log = []
        for model, mp in model_map.items():
            if isinstance(mp, (list, tuple, set)):
                mp = {f: f for f in mp}

            mdl = IrModel.search([('model', '=', model)], limit=1)
            if mdl:
                model_id = mdl.id
                model_cls = self.env[model]

                for fname, labels in mp.items():
                    # 'labels' là dict có dạng {'en_US': 'Tên sản phẩm', 'vi_VN': 'Tên sản phẩm'}
                    desc_json = json.dumps(labels)  # labels chính là nhãn cho các ngôn ngữ
                    # Chuẩn bị SQL và params
                    sql_str = """
                        INSERT INTO ir_model_fields (
                            name, model, model_id, ttype, state,
                            readonly, store, field_description
                        ) VALUES (%s, %s, %s, 'char', 'manual', FALSE, TRUE, %s::jsonb)
                        ON CONFLICT (model, name)
                        DO UPDATE SET field_description = EXCLUDED.field_description
                    """
                    params = (fname, model, model_id, desc_json)

                    # Thực thi SQL
                    cr.execute(sql_str, params)
                    log.append((sql_str.strip(), params))

                    # Đăng ký với registry hiện tại nếu chưa có
                    if fname not in model_cls._fields:
                        dyn = _f.Char( readonly=False, store=True)
                        model_cls._add_field(fname, dyn)
        cr.commit()
        #raise UserError(log)

    # ------------------------------------------------------------------
    # Generate dynamic view extensions
    # ------------------------------------------------------------------
    @staticmethod
    def _tree_arch(labels):
        cols = "\n            ".join(
            f'<field name="{f}"  optional="show"/>' for f, l in labels.items())
        return f"""
                <xpath expr="//tree" position="inside">
                    {cols}
                </xpath>
            """

    @staticmethod
    def _pivot_arch(labels):
        cols = "\n        ".join(
            f'<field name="{f}"/>' for f in labels)
        return f'<pivot>{cols}</pivot>'

    @staticmethod
    def _graph_arch(labels):
        cols = "\n        ".join(
            f'<field name="{f}"/>' for f in labels)
        return f'<graph>{cols}</graph>'

    # ------------------------------------------------------------
    # View helper
    # ------------------------------------------------------------
    def _parent_view(self, model, vtype, base_xmlid):
        View = self.env['ir.ui.view']
        try:
            base = self.env.ref(base_xmlid)
            if base.type == vtype:
                return base
        except ValueError:
            pass
        return View.search([
            ('model', '=', model),
            ('type',  '=', vtype),
            ('inherit_id', '=', False)
        ], order='priority', limit=1) or None

    def ensure_view_ext(self, model, base_xmlid, labels):
        """
        Sinh các view tree / pivot / graph kế thừa, đảm bảo:
        • Mỗi lần gọi đều *xóa sạch* bản cũ (xmlid *_dyn) rồi tạo lại.
        • Không để lại orphan trong ir.model.data.
        """
        if not labels:
            return

        View    = self.env['ir.ui.view']
        IMD     = self.env['ir.model.data']

        def _create(vtype, arch_fn):
            parent      = self._parent_view(model, vtype, base_xmlid)
            xmlid_name  = f"{base_xmlid}_{vtype}_dyn"
            xmlid_full  = f"smartbiz_nomenclature.{xmlid_name}"

            # ------------------------------------------------------------------
            # 1. Xoá view / ir.model.data cũ (nếu có)
            # ------------------------------------------------------------------
            data_rec = IMD.sudo().search([
                ('module', '=', 'smartbiz_nomenclature'),
                ('name',   '=', xmlid_name),
                ('model',  '=', 'ir.ui.view')
            ], limit=1)

            if data_rec:
                old_view = View.browse(data_rec.res_id)
                old_view.sudo().unlink()
                data_rec.sudo().unlink()

            # ------------------------------------------------------------------
            # 2. Tạo view mới
            # ------------------------------------------------------------------
            vals = {
                'name'     : f"Nomenclature {vtype.title()} – {model}",
                'model'    : model,
                'type'     : vtype,
                'priority' : (parent.priority + 5) if parent else 16,
                'arch_base': arch_fn(labels),
            }
            if parent:
                vals['inherit_id'] = parent.id

                new_view = View.sudo().create(vals)

                # 3. Đăng ký lại XML-ID để lần sau có thể tìm bằng env.ref
                IMD.sudo().create({
                    'module' : 'smartbiz_nomenclature',
                    'name'   : xmlid_name,
                    'model'  : 'ir.ui.view',
                    'res_id' : new_view.id,
                    'noupdate': True,
                })

        # ----------------------------------------------------------------------
        # Gọi cho cả 3 loại view
        # ----------------------------------------------------------------------
        for _t in ('tree', 'pivot', 'graph'):
            _create(_t, getattr(self, f"_{_t}_arch"))

