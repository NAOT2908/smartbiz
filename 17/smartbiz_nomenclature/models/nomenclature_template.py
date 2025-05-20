from odoo import models, fields, api, exceptions,_, tools

class SmartbizNomenclatureTemplate(models.Model):
    _name = "smartbiz.nomenclature.template"
    _description = "Nomenclature Template"
    _order = "sequence"

    name             = fields.Char(required=True, translate=True)
    sequence         = fields.Integer(default=10)

    model_name       = fields.Selection([
        ('product.template', 'Product'),
        ('stock.lot',      'Stock Lot')
    ], required=True)

    # Báo cáo đích (tên model) – để trống = áp dụng cho tất cả
    report_model     = fields.Char(string="Report Model")

    # Cho phép override alias (nếu report dùng alias khác)
    alias_override   = fields.Char(string="Alias Override")

    condition_domain = fields.Text(
        help="Domain JSON hoặc eval Python, ví dụ: "
             "[('categ_id.code','=','FABRIC')]")
    regex_pattern    = fields.Char()
    separator        = fields.Char(default='_')
    active           = fields.Boolean(default=True)

    line_ids         = fields.One2many(
        'smartbiz.nomenclature.template.line', 'template_id')

    def action_rebuild_report(self):
        mixin_cls = self.env.registry['smartbiz.nomenclature.report.mixin']  # lớp mixin

        for model_cls in self.env.registry.models.values():             # class model
            if issubclass(model_cls, mixin_cls) and model_cls is not mixin_cls:
                # _name đã đăng ký ⇒ gọi cú pháp env[model_name]
                self.env[model_cls._name]._rebuild_view()
    
    def action_delete_fields(self):
        mixin_cls = self.env.registry['smartbiz.nomenclature.report.mixin']  # lớp mixin

        for model_cls in self.env.registry.models.values():             # class model
            if issubclass(model_cls, mixin_cls) and model_cls is not mixin_cls:
                # _name đã đăng ký ⇒ gọi cú pháp env[model_name]
                self.env[model_cls._name]._delete_fields()                
    # -------- helper cho hook ----------
    @api.model
    def _fields_for_reports(self, report_model):
        recs = self.search([
            ('active','=',True),
            ('report_model','in',[False,'',report_model])
        ])
        return set(recs.mapped('line_ids.target_field'))


class SmartbizNomenclatureTemplateLine(models.Model):
    _name = "smartbiz.nomenclature.template.line"
    _description = "Nomenclature Template Line"
    _order = "sequence"

    template_id   = fields.Many2one(
        'smartbiz.nomenclature.template', required=True, ondelete="cascade")
    sequence      = fields.Integer(default=10)

    target_field  = fields.Char(required=True)
    field_label   = fields.Char(required=True, translate=True)

    segment_index = fields.Integer()
    regex_group   = fields.Integer()
    cast_type     = fields.Selection([
        ('char','Char'), ('int','Integer'),
        ('float','Float'), ('date','Date')
    ], default='char')
