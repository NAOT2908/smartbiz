# smartbiz_nomenclature/services/rebuild_wizard.py
from odoo import models

class RebuildNomenclatureWizard(models.TransientModel):
    _name = "smartbiz.nomenclature.rebuild.wizard"
    _description = "Rebuild tất cả báo cáo dùng mixin"

    def action_rebuild(self):
        mixin_cls = self.env.registry['smartbiz.nomenclature.report.mixin']  # lớp mixin

        for model_cls in self.env.registry.models.values():             # class model
            if issubclass(model_cls, mixin_cls) and model_cls is not mixin_cls:
                # _name đã đăng ký ⇒ gọi cú pháp env[model_name]
                self.env[model_cls._name]._rebuild_view()
