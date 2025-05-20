{
    'name': 'List View Manager',

    'summary': """
        List view search,Global Search,Quick Search,Search engine,advance filter,Field Search,
        advanced search,Tree view,document management system,Resize columns,Export Current View,
        auto suggestion,Hide column,show column,rename column,reorder column
""",

    'description': """
List View ,
	Advance Search ,
	Read/Edit Mode ,
	Dynamic List ,
	Hide/Show list view columns ,
	List View Manager ,
	Odoo List View ,
	Odoo Advanced Search ,
	Odoo Connector ,
	Odoo Manage List View ,
	Drag and edit columns ,
	Dynamic List View Apps , 
	Advance Dynamic Tree View ,
	Dynamic Tree View Apps ,
	Advance Tree View Apps ,
	List/Tree View Apps ,
	Tree/List View Apps  ,
	Freeze List View Header ,
	List view Advance Search ,
	Tree view Advance Search ,
	Best List View Apps ,
	Best Tree View Apps ,
	Tree View Apps ,
	List View Apps ,
	List View Management Apps ,
	Treeview ,
	Listview ,
	Tree View ,
	one2many view, 
        list one2many view, 
        sticky header, 
        report templates, 
        sale order lists, 
        approval check lists, 
        pos order lists, 
        orders list in odoo,
        top app, 
        best app, 
        best apps
""",

    'author': 'Ksolves India Ltd.',

    'sequence': 1,

    'website': 'https://store.ksolves.com',

    'live_test_url': 'http://lvm15.kappso.in/web/login',

    'category': 'Tools',

    'version': '17.0.1.0.3',

    'depends': ['base', 'base_setup','web'],

    'license': 'OPL-1',

    'currency': 'EUR',

    'price': 171,

    'maintainer': 'Ksolves India Ltd.',

    'support': 'sales@ksolves.com',

    'images': ['static/description/Odoo GIF .gif'],

    'data': [
        'views/ks_res_config_settings.xml',
        'security/ir.model.access.csv',
        'security/ks_security_groups.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'ks_list_view_manager/static/src/css/ks_list_view_manager.scss',
             'ks_list_view_manager/static/src/css/sticky.scss',
            'ks_list_view_manager/static/lib/jquery.ui/jquery-ui.js',
            'ks_list_view_manager/static/lib/jquery.ui/jquery-ui.css',
             # 'ks_list_view_manager/static/src/js/ks_lvm_renderer.js',
             'ks_list_view_manager/static/src/js/lvm_render.js',
             'ks_list_view_manager/static/src/component/search_view.js',
             'ks_list_view_manager/static/src/js/ks_lvm_controller.js',
             'ks_list_view_manager/static/src/xml/rownumber.xml',
             'ks_list_view_manager/static/src/component/ks_advance_search.xml',
             'ks_list_view_manager/static/src/xml/lvm_button.xml',
             'ks_list_view_manager/static/src/xml/ks_lvm_button.xml',
             'ks_list_view_manager/static/src/xml/search_view.xml',
             'ks_list_view_manager/static/src/xml/ks_list_templates.xml',
             'ks_list_view_manager/static/src/xml/ks_cancel_edit_template.xml',
            'ks_list_view_manager/static/src/xml/props.xml',



            #         # 'ks_list_view_manager/static/src/js/lvm_controller.js',
        ],
        #
    },

    'post_init_hook': 'post_install_hook',

    'uninstall_hook': 'uninstall_hook',
}
# -*- coding: utf-8 -*-
