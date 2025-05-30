{
    "name": "SmartBiz – Nomenclature Core",
    "version": "17.0.1.0.0",
    "summary": "Tách chuỗi động • Tự chèn field & view cho báo cáo",
    "author": "SmartBiz",
    "depends": [],
    "data": [
        "security/ir.model.access.csv",
        "views/nomenclature_template_views.xml",
 
    ],
    "post_init_hook": "post_init_add_fields",
    "license": "LGPL-3",

        # Application settings
    'installable': True,
    'application': True,
}
