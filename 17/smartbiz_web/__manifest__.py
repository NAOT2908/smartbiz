# -*- coding: utf-8 -*-

{
    'name': "SmartBiz Web",
    'summary': "SmartBiz Web",
    'description': "SmartBiz Web",
    'author': "SmartBiz",
    'website': "https://www.sbiz.vn",

    # Categories can be used to filter modules in modules listing
    'category': 'SmartBiz Apps',
    'license': 'Other proprietary',
    'version': '1.0',

    # Any module necessary for this one to work correctly
    'depends': [
        'base',
        'mail',
    ],
    'excludes': ['web_enterprise'],
    # always loaded
    'data': [

    ],

    'assets': {
        'web._assets_primary_variables': [
            ('after', 'web/static/src/scss/primary_variables.scss', 'smartbiz_web/static/src/**/*.variables.scss'),
            ('before', 'web/static/src/scss/primary_variables.scss', 'smartbiz_web/static/src/scss/primary_variables.scss'),
        ],
        'web._assets_secondary_variables': [
            ('before', 'web/static/src/scss/secondary_variables.scss', 'smartbiz_web/static/src/scss/secondary_variables.scss'),
        ],
        'web._assets_backend_helpers': [
            ('before', 'web/static/src/scss/bootstrap_overridden.scss', 'smartbiz_web/static/src/scss/bootstrap_overridden.scss'),
        ],
        'web.assets_frontend': [
            'smartbiz_web/static/src/webclient/home_menu/home_menu_background.scss', # used by login page
            'smartbiz_web/static/src/webclient/navbar/navbar.scss',
        ],
        'web.assets_backend': [
            #'smartbiz/static/src/**/*.js',
            #'smartbiz/static/src/**/*.scss',
            
            'smartbiz_web/static/src/webclient/navbar/navbar.scss',
            'smartbiz_web/static/src/webclient/navbar/navbar.variables.scss',
            'smartbiz_web/static/src/webclient/home_menu/home_menu.scss',

            'smartbiz_web/static/src/core/**/*',
            'smartbiz_web/static/src/webclient/**/*.js',
            'smartbiz_web/static/src/webclient/**/*.xml',
           
         ],
        
        'web.assets_web': [
            ('replace', 'web/static/src/main.js', 'smartbiz_web/static/src/main.js'),
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
}
