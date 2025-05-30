from odoo import api, SUPERUSER_ID
from .models.sql_tools import SQLTools

def post_init_add_fields(env):
    tools = SQLTools(env)
    tmpl  = env['smartbiz.nomenclature.template']

    # 1. Chuẩn bị map model -> field names
    report_models = {}
    mixin_cls = env.registry['smartbiz.nomenclature.report.mixin']
    for mdl in env.registry.models.values():
        if mdl is mixin_cls or not issubclass(mdl, mixin_cls):
            continue
        report_models[mdl._name] = tmpl._fields_for_reports(mdl._name)

    # 2. Tạo tất cả field ảo
    tools.sync_fields(report_models)

