from lxml import etree
from odoo.exceptions import AccessError, ValidationError
from odoo import api, fields, models, _,tools
import json, logging
from jinja2 import Template


_logger = logging.getLogger(__name__)

class SmartbizReportBase(models.AbstractModel):
    _name = "smartbiz.report_base"
    _description = "Mixin • Auto-generated SQL report"

    _sqltools_source_table  = ''
    _sqltools_primary_keys  = []
    _sqltools_extra_filters = ''

    @classmethod
    def _build_view(cls, env):
        SQLReportBuilder.build(env, cls)

    @api.model
    def init(self):
        self._build_view(self.env)

    def action_refresh_view(self):
        self._build_view(self.env)
        return {"type": "ir.actions.act_window_close"}
        
class SQLReportBuilder:
    """Build view, fields & Odoo view extensions."""

    @classmethod
    def build(cls, env, model_cls):
        # Nếu chưa cấu hình source_table, skip hoàn toàn
        source = getattr(model_cls, '_sqltools_source_table', False) or ''
        if not source.strip():
            _logger.debug("SQLTools: skip build for %s, no _sqltools_source_table defined", model_cls._name)
            return
        model = model_cls._name
        view  = model.replace('.', '_') + '_view'

        splits = env['smartbiz.report_split_rule'].search([
            ('model_name','=',model),('active','=',True)],
            order='template_id,seq')
        aggs   = env['smartbiz.report_split_rule'].search([
            ('model_name','=',model),('active','=',True)],
            order='template_id,seq')

        # 1) SELECT/GROUP BY
        if splits or aggs:
            select_cols, group_cols, dyn_fields = \
                cls._build_select_with_rules(env, model_cls, splits, aggs)
        else:
            # fallback, giữ nguyên mọi cột gốc
            select_cols = ['*']
            group_cols  = []
            dyn_fields  = []

        where = model_cls._sqltools_extra_filters or 'TRUE'
        src   = model_cls._sqltools_source_table
        sel   = ",\n            ".join(select_cols)
        grp   = f"GROUP BY {', '.join(group_cols)}" if group_cols else ''

        sql = f"""
        CREATE OR REPLACE VIEW {view} AS
        SELECT
            row_number() OVER() AS id,
            {sel}
        FROM {src}
        WHERE {where}
        {grp}
        """
        tools.drop_view_if_exists(env.cr, view)
        env.cr.execute(sql)

        # 2) ensure fields
        if splits or aggs:
            manual = cls._collect_manual_fields(model_cls, dyn_fields)
        else:
            manual = cls._introspect_view(env, view, model)
        all_fields = dyn_fields + manual
        cls._ensure_fields(env, model_cls, all_fields)

        # 3) update Odoo views
        cls._ensure_view_extensions(env, model_cls,
                                    [f[0] for f in all_fields])
        _logger.info("SQLTools: rebuilt %s", view)

    @classmethod
    def _build_select_with_rules(cls, env, model_cls, splits, aggs):
        select_cols = list(model_cls._sqltools_primary_keys)
        group_cols  = list(model_cls._sqltools_primary_keys)
        dyn_fields  = []

        # SPLIT rules
        for s in splits:
            fname = s.field_code
            dyn_fields.append((fname, s.ttype, s.label, s.relation))
            p = json.loads(s.param_json or '{}')
            if s.method == 'identity':
                base = s.source_field
            elif s.method == 'delimiter':
                sep = p.get('sep','/'); idx = int(p.get('index',0))+1
                base = f"SPLIT_PART({s.source_field},'{sep}',{idx})"
            elif s.method == 'regex':
                pat = p.get('pattern','.*'); grp = p.get('group',0)
                base = f"REGEXP_MATCH({s.source_field},'{pat}')[{grp}]"
            else:  # json
                path = p.get('path','$')
                base = f"JSON_EXTRACT_PATH_TEXT({s.source_field},'{path}')"

            if s.ttype == 'integer':
                expr = f"CAST(({base}) AS INTEGER)"
            elif s.ttype == 'float':
                expr = f"CAST(({base}) AS NUMERIC)"
            elif s.ttype == 'many2one':
                expr = f"CAST(({base}) AS INTEGER)"
            else:
                expr = base
            select_cols.append(f"{expr} AS {fname}")

        # AGGREGATE rules
        ctx = {}
        if hasattr(model_cls, '_sqltools_get_ctx'):
            ctx = model_cls._sqltools_get_ctx(env)
        tin, tout = [], []
        for a in aggs:
            fname = a.field_code
            dyn_fields.append((fname, a.ttype, a.label, a.relation))
            raw = Template(a.expr_template).render(**ctx)
            if a.ttype == 'integer':
                sql_expr = f"CAST(({raw}) AS INTEGER)"
            elif a.ttype == 'char':
                sql_expr = f"CAST(({raw}) AS TEXT)"
            else:
                sql_expr = raw
            select_cols.append(f"COALESCE({sql_expr},0) AS {fname}")
            if a.include_total:
                (tin if 'in' in fname else tout).append(fname)

        if tin:
            select_cols.append(f"({' + '.join(tin)}) AS total_in")
            dyn_fields.append(('total_in','float','Total In',False))
        if tout:
            select_cols.append(f"({' + '.join(tout)}) AS total_out")
            dyn_fields.append(('total_out','float','Total Out',False))

        return select_cols, group_cols, dyn_fields

    @staticmethod
    def _collect_manual_fields(model_cls, dyn_fields):
        dyn_names = {f[0] for f in dyn_fields}
        out = []
        for name, fld in model_cls._fields.items():
            if name in dyn_names or name == 'id' or name.startswith('_'):
                continue
            if fld.compute or fld.related or getattr(fld,'store',True) is False:
                continue
            t = fld.type
            if t == 'many2one':
                ttype, rel = 'many2one', fld.comodel_name
            elif t == 'monetary':
                ttype, rel = 'monetary', False
            elif t in ('float','integer','char','date','datetime'):
                ttype, rel = t, False
            else:
                ttype, rel = 'char', False
            label = fld.string or name.replace('_',' ').title()
            out.append((name, ttype, label, rel))
        return out

    @staticmethod
    def _introspect_view(env, view_name, model):
        env.cr.execute("""
            SELECT column_name, data_type
              FROM information_schema.columns
             WHERE table_name = %s
        """, (view_name,))
        rows = env.cr.fetchall()
        out = []
        for col, pg in rows:
            if col == 'id': continue
            # map PG type → Odoo ttype (xài char/float/int)
            if pg in ('integer','bigint'):
                ttype = 'integer'
            elif pg in ('numeric','double precision'):
                ttype = 'float'
            elif pg.startswith('timestamp'):
                ttype = 'datetime'
            elif pg == 'date':
                ttype = 'date'
            else:
                ttype = 'char'
            label = col.replace('_',' ').title()
            out.append((col, ttype, label, False))
        return out

    @staticmethod
    def _ensure_fields(env, model_cls, specs):
        for fname, ttype, label, rel in specs:
            if env['ir.model.fields'].sudo().search([
                ('model','=',model_cls._name),
                ('name','=',fname)], limit=1):
                continue
            vals = {
                'name': fname,
                'model': model_cls._name,
                'field_description': label,
                'state': 'manual'
            }
            if ttype == 'many2one':
                vals.update({'ttype':'many2one','relation':rel or ''})
            elif ttype == 'monetary':
                vals.update({'ttype':'monetary','currency_field':'currency_id'})
            else:
                vals['ttype'] = ttype
            env['ir.model.fields'].sudo().create(vals)

    @staticmethod
    def _ensure_view_extensions(env, model_cls, field_names):
        model = model_cls._name
        pmap  = getattr(model_cls, '_sqltools_parent_views', {})
        for vtype in ('tree','pivot','graph'):
            parent = pmap.get(vtype) and env.ref(pmap[vtype], False) or \
                env['ir.ui.view'].search([
                    ('model','=',model),('type','=',vtype),
                    ('inherit_id','=',False)], limit=1)
            if not parent: continue
            ext = env['ir.ui.view'].search([
                ('inherit_id','=',parent.id),
                ('name','=',f"{model}_{vtype}_auto_ext")], limit=1)
            existing = set(env[parent.model]._fields)
            new = [f for f in field_names if f not in existing]
            if not new: continue
            lines = ''.join(
                f'<field name="{new[-1]}" position="after">'
                f'<field name="{f}"/></field>'
                if i==len(new)-1 else
                f'<field name="{new[i]}" position="after">'
                f'<field name="{new[i+1]}"/></field>'
                for i,f in enumerate(new)
            )
            arch = f'<data><xpath expr="/*" position="inside">{lines}</xpath></data>'
            vals = {
                'name':f"{model}_{vtype}_auto_ext",
                'model':model,'type':vtype,
                'inherit_id':parent.id,'mode':'extension',
                'arch':arch,'arch_base':False
            }
            if ext:
                ext.sudo().with_context(no_update=True).write(vals)
            else:
                env['ir.ui.view'].sudo().with_context(no_update=True).create(vals)
