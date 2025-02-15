# -*- coding: utf-8 -*-

{
    'name': "SmartBiz Barcode",
    'summary': "SmartBiz Barcode",
    'description': "SmartBiz Barcode",
    'author': "SmartBiz",
    'website': "https://www.sbiz.vn",

    # Categories can be used to filter modules in modules listing
    'category': 'SmartBiz Apps',
    'license': 'Other proprietary',
    'version': '1.0',

    # Any module necessary for this one to work correctly
    'depends': [
        'base','stock','stock_picking_batch',
        'mail',
    ],

    # always loaded
    'data': [
        'security/securities.xml',
        'security/ir.model.access.csv',
        'views/views.xml',
        'report/report.xml',
        'report/report_templates.xml',
        'data/data.xml',
        'views/res_config_settings_views.xml',
    ],

    'assets': {
        'web.assets_backend': [
              'smartbiz_barcode/static/src/**/*.js',
              'smartbiz_barcode/static/src/**/*.scss',
              'smartbiz_barcode/static/src/**/*.xml',
         ],
        'web.assets_qweb': [
         ],
     },

    'qweb': [
    ],

    # only loaded in demonstration mode
    'demo': [
    ],

    # Application settings
    'installable': True,
    'application': True,
    'images': ['static/description/icon.png'],
}
