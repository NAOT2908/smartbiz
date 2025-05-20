# -*- coding: utf-8 -*-
from odoo import models, api, SUPERUSER_ID, tools
from .sql_tools import SQLTools            # <-- luôn import được

class NomenclatureReportMixin(models.AbstractModel):
    _name = "smartbiz.nomenclature.report.mixin"
    _description = "Mixin tự động tách chuỗi cho báo cáo"

    # ---- khai báo ở lớp con ----------------------------------
    def _core_sql(self):       raise NotImplementedError
    def _aliases(self):        raise NotImplementedError
    def _base_view_xmlid(self):raise NotImplementedError
    # ----------------------------------------------------------

    # Odoo luôn gọi init() cho abstract => chặn lại
    def init(self):
        if self._name == self.__class__._name:     # chính bản thân mixin
            return
        try:
            super().init()
        except AttributeError:
            pass
        self._rebuild_view()

    # ----------------------------------------------------------
    def _rebuild_view(self):
        env      = api.Environment(self._cr, SUPERUSER_ID, {})
        sqltools = SQLTools(env)
        sel, grp, labels = sqltools.select_group(self._name, self._aliases())

        sqltools.sync_fields({self._name: labels})

        sqltools.ensure_view_ext(self._name, self._base_view_xmlid(), labels)

        # chèn trực tiếp, không thêm dấu ',' dư thừa
        base_sql = self._core_sql()
        sql = base_sql.replace("--[[EXTRA_SELECT]]", sel and f"{sel},\n" or "")
        sql = sql.replace("--[[EXTRA_GROUP]]",  grp and f", {grp}" or "")
        sql = sql.format(from_date='2000-01-01', to_date='3000-01-01')
        tools.drop_view_if_exists(self._cr, self._view_name())
        self._cr.execute(f"CREATE OR REPLACE VIEW {self._view_name()} AS ({sql})")

    def _view_name(self):
        return self._table

    def _delete_fields(self):
        env      = api.Environment(self._cr, SUPERUSER_ID, {})
        sqltools = SQLTools(env)
        sel, grp, labels = sqltools.select_group(self._name, self._aliases())

        sqltools.delete_fields({self._name: labels})


    # helper trả về instance SQLTools tái sử dụng
    def _sql_tools(self):
        """Trả về singleton SQLTools gắn với self.env."""
        if not hasattr(self.env, '_sql_tools_cached'):
            self.env._sql_tools_cached = SQLTools(self.env)
        return self.env._sql_tools_cached