/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { session } from "@web/session";
import { renderToElement } from "@web/core/utils/render";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { SearchView } from "@ks_list_view_manager/component/search_view";
import { jsonrpc } from "@web/core/network/rpc_service";
import { getCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";
import { formatFloat,formatInteger } from "@web/views/fields/formatters";




const { useRef, onMounted , onWillStart , useExternalListener , onWillUpdateProps , Component } = owl;

patch(ListRenderer.prototype,  {
    setup() {
        var self = this;
         this.ks_serial_number = session.ks_serial_number;
         this.ks_allow_search = true;
         this.ksDomain = [];
         this.datepicker;
         this.rpc = useService("rpc");
         this.ks_datepicker_flag = 0
         this.mydomain = null;
        this.ks_autocomplete_data = {};
        this.ks_autocomplete_data_result = {};
        this.ks_lvm_mode = true;
        this.ks_remove_popup_flag = false;
        this.ks_key_fields = [];
        this.ks_field_domain_list = [];
        this.ks_field_domain_dict = {};
        this.ksBaseDomain = [];
        this.ks_advance_search_refresh = false;
        this.ks_start_date = undefined;
        this.ks_end_date = undefined;
        this.ks_start_date_id = undefined;
        this.ks_end_date_id = undefined;
        this.ks_editable = false;
        if (this.props.list.domain){
        this.default_domain = [...this.props.list.domain]
        this.ks_search_domain = [...this.props.list.domain]
        };
        if(this.env.searchModel && this.env.searchModel.globalDomain){
        this.search_default=[...this.env.searchModel.globalDomain]
        };
        this.ks_list_data = this.props.list_data ? this.props.list_data : session.list_data
        var ks_is_list_renderer = true ? this.props.list_data : false;

        this.tableRef = useRef("table");
        this.ks_is_lines = true;
        if (this.props.activeActions.type == 'view' &&  ks_is_list_renderer) {
            this.ks_is_lines = false;
        }
        onMounted(this._mounted);
            onWillUpdateProps((next_prop) => {
                this.keepColumnWidths = false;
                this.allColumns = next_prop.archInfo.columns;
                this.getOptionalActiveFields();
                this.state.columns = this.getActiveColumns(next_prop.list);
//                this._mounted();

            });
//            onWillStart(async () => {
//                 this.willStart()
//            });



        return super.setup();
    },
//      async willStart() {
//        var self= this;
//        this.ks_searchdomain = [];
//        if ((browser.localStorage.getItem("ks_model"))){
//            if ((browser.localStorage.getItem("ks_model")) === this.props.list.model.root.resModel && (browser.localStorage.getItem("search_domain")) && this.env.config.actionId == browser.localStorage.getItem("ks_actionid")){
//                this.ks_searchdomain = JSON.parse(browser.localStorage.getItem("search_domain"))
//            }else{
//                browser.localStorage.getItem("ks_actionid");
//                browser.localStorage.removeItem("search_domain");
//                browser.localStorage.removeItem("ks_model");
//                browser.localStorage.removeItem("field_dict");
//                browser.localStorage.removeItem("key_field")
//            }
//            if (this.ks_searchdomain.length){
//            this.ksBaseDomain = [...this.props.list.domain];
//            for (let ks_values of this.ks_searchdomain){
//                this.props.list.model.root.domain.push(ks_values);
//                this.env.searchModel.globalDomain.push(ks_values);
//            }
//
//            this.ks_search_domain = this.props.list.model.root.domain;
//            this.ksDomain = this.ks_searchdomain;
//            this.ks_field_domain_list = this.ks_searchdomain;
//            this.ks_field_domain_dict = JSON.parse(browser.localStorage.getItem("field_dict"));
//            this.ks_key_fields = JSON.parse(browser.localStorage.getItem("key_field"))
//            this.ks_advance_search_refresh = true;
//            this.ks_key_insert_flag =false;
//
//        }
//     }
//    },

    async _mounted() {
        if (this.isX2Many== false){
            var self = this
            var table = this.tableRef
            this.ks_allow_search = true;
            self.ks_call_flag = 1;
            $($(table.el.querySelectorAll("thead tr"))[0]).addClass("bg-primary");

            if(document.querySelector(".o_list_controller.o_list_actions_header")){
                $(document.querySelector(".o_list_controller.o_list_actions_header")).addClass("d-none")
            }
        }
    },

        get ks_field_popup(){
            var self = this;
            var ks_field_popup = {};
            if (self.ksDomain != []) {
                for (var i = 0; i < self.ksDomain.length; i++) {
                    if (!(self.ksDomain[i] === '|')) {
                        if (ks_field_popup[self.ksDomain[i][0]] === undefined) {
                            ks_field_popup[self.ksDomain[i][0]] = [self.ksDomain[i][2]]
                        } else {
                            ks_field_popup[self.ksDomain[i][0]].push(self.ksDomain[i][2])
                        }
                    }
                }
            }
            return ks_field_popup

        },

        Ks_update_advance_search_controller(ks_options) {
             var self = this;
             if (ks_options !=false){
            let rec_ids = [];
                for (let i = 0; i < this.props.list.records.length; i++) {
                    rec_ids.push(this.props.list.records[i].resId);
                }
            ks_options['rec_ids'] = [...rec_ids]
            }

        if (this.ks_lvm_mode) {
            var self = this;
            if (self.ks_remove_popup_flag === true) {
                var ks_advance_search_params = {};
                ks_advance_search_params["modelName"] = self.props.resModel;
                ks_advance_search_params["context"] = self.props.context;
                ks_advance_search_params["ids"] = ks_options.res_ids;
                ks_advance_search_params["offset"] = self.props.list.model.root.offset;
                //                    ks_advance_search_params["currentId"] = self.renderer.state.res_id;
                ks_advance_search_params["selectRecords"] = self.props.list.model.root.selection;
                ks_advance_search_params["groupBy"] = self.props.list.model.root.groupBy;
                self.ks_field_domain_list = [];

                for (var j = 0; j < self.ks_key_fields.length; j++) {
                    self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                }
                self.ks_remove_popup_flag = false;
                ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                if (self.ks_search_domain.length === 0) {
                    self.ksBaseDomain = []
                }
                if (self.ksBaseDomain === null && (self.ksDomain === null || self.ksDomain.length === 0) && self.ks_search_domain.length) {
                    self.ksBaseDomain = self.ks_search_domain
                }
                if (self.ksBaseDomain.length !== 0 || self.ks_field_domain_list.length !== 0) {
                    ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                } else {
                    ks_advance_search_params["domain"] = []
                }
                self.ksDomain = ks_advance_search_params["ksDomain"]
                self.mydomain = ks_advance_search_params["ksDomain"]
                self.ks_update(self.mydomain);

            } else {
                var ks_val_flag = false;
                if (ks_options.ks_val) {
                    ks_val_flag = ks_options.ks_val.trim() !== 0
                } else {
                    if (ks_options.ksfieldtype == "selection") {
                        ks_val_flag = $(".custom-control-searchbar-change[data-name=" + ks_options.KsSearchId + "]").val().trim() !== 0
                    } else {
                        ks_val_flag = $(".custom-control-searchbar-advance[data-name=" + ks_options.KsSearchId + "]").val() !== 0
                    }
                }

                if (Number(ks_val_flag)) {
                    self.ks_advance_search_refresh = true;
                    if (ks_options.ksfieldtype == "selection") {
                        var ks_search_value = ks_options.ks_val || $(".custom-control-searchbar-change[data-name=" + ks_options.KsSearchId + "]").val();
                    } else {
                        if(ks_options.KsSearchId === "level_progress"){
                            var ks_search_value = (ks_options.ks_val || $(".custom-control-searchbar-advance[data-name=" + ks_options.KsSearchId + "]").val())/100;
                        }else{
                        var ks_search_value = ks_options.ks_val || $(".custom-control-searchbar-advance[data-name=" + ks_options.KsSearchId + "]").val();
                        }
                    }
                    //                        var ks_search_value = ks_options.data.ks_val || $(".custom-control-searchbar-advance[data-name=" + ks_options.data.KsSearchId + "]").val();
                    var ks_advance_search_type = ks_options.ksfieldtype;
                    var ks_selection_values = [];
                    var ks_advance_search_params = {};
                    self.ks_field_domain_list = [];
                    self.ks_key_insert_flag = false;
                    var ks_data_insert_flag = false;
                    var ks_value = ks_options.KsSearchId.split("_lvm_start_date")
                    ks_advance_search_params["groupBy"] = self.props.list.model.root.groupBy
                    ks_advance_search_params["modelName"] = self.props.resModel;
                    ks_advance_search_params["context"] = self.props.context;
                    ks_advance_search_params["ids"] = ks_options.res_ids;
                    ks_advance_search_params["offset"] = self.props.list.model.root.offset;
                    //                        ks_advance_search_params["currentId"] = self.renderer.state.res_id;
                    ks_advance_search_params["selectRecords"] = self.props.list.model.root.selection

                    if (ks_value.length === 1) {
                        ks_value = ks_options.KsSearchId.split("_lvm_end_date")
                        if (ks_value.length === 2)
                            ks_options.KsSearchId = ks_value[0];
                    } else {
                        ks_options.KsSearchId = ks_value[0];
                    }

                    for (var ks_sel_check = 0; ks_sel_check < self.ks_key_fields.length; ks_sel_check++) {
                        if (ks_options.KsSearchId === self.ks_key_fields[ks_sel_check]) {
                            ks_data_insert_flag = true;
                        }
                    }

                    if ((ks_data_insert_flag === false) || (ks_data_insert_flag === true && (ks_advance_search_type === "many2one" || ks_advance_search_type === "many2many" || ks_advance_search_type === "char"))) {
                        if (!(ks_advance_search_type === "datetime" || ks_advance_search_type === "date")) {
                            if (this.ks_key_fields.length === 0) {
                                if (ks_advance_search_type === 'monetary' || ks_advance_search_type === 'integer' || ks_advance_search_type === 'float') {
                                    try {
                                        //Fixme currency
                                        var currency = getCurrency(self.props.list_data.currency);
                                        var parsed_value = parseFloat(ks_search_value);
                                        if (isNaN(parsed_value)) {
                                            throw new Error('Invalid number');
                                        }
//                                        var formatted_value = formatFloat(parsed_value || 0, {
//                                            digits: currency && currency.digits
//                                        });
//                                        ks_search_value = formatted_value
                                        self.ks_key_fields.push(ks_options.KsSearchId);
                                    } catch {
                                        this.env.services.notification.add(_t("Please enter a valid number"), {
                                            title: _t("Notification"),
                                            sticky: false,
                                            type: "info",
                                        });
                                    }
                                } else {
                                    self.ks_key_fields.push(ks_options.KsSearchId);
                                }
                            } else {
                                for (var key_length = 0; key_length < self.ks_key_fields.length; key_length++) {
                                    if ((self.ks_key_fields[key_length] === ks_options.KsSearchId)) {
                                        self.ks_key_insert_flag = true;
                                        break;
                                    }
                                }
                                if (!(self.ks_key_insert_flag)) {
                                    if (ks_advance_search_type === 'monetary' || ks_advance_search_type === 'integer' || ks_advance_search_type === 'float') {
                                        try {
                                            // Fixme currency
                                             var currency = getCurrency(self.props.list_data.currency);
                                             var parsed_value = parseFloat(ks_search_value);
                                             if (isNaN(parsed_value)) {
                                                throw new Error('Invalid number');
                                             }
                                             var formatted_value = formatFloat(parsed_value || 0, {
                                                digits: currency && currency.digits
                                             });
                                             ks_search_value = formatted_value
                                             self.ks_key_fields.push(ks_options.KsSearchId);
                                        } catch {
                                            this.env.services.notification.add(_t("Please enter a valid number"), {
                                                title: _t("Notification"),
                                                sticky: false,
                                                type: "info",
                                            });
                                        }
                                    } else {
                                        self.ks_key_fields.push(ks_options.KsSearchId);
                                    }
                                }
                            }
                        }

                        if (ks_advance_search_type === "datetime" || ks_advance_search_type === "date") {
                            if (ks_options.ksFieldIdentity === ks_options.KsSearchId + '_lvm_start_date lvm_start_date') {
                                self.ks_start_date = ks_search_value;
                                self.ks_start_date_id = ks_options.KsSearchId;
                            } else {
                                self.ks_end_date = ks_search_value;
                                self.ks_end_date_id = ks_options.KsSearchId
                            }

                            if (ks_advance_search_type === "datetime" || ks_advance_search_type === "date") {
                                if (ks_options.ksFieldIdentity === ks_options.KsSearchId + '_lvm_end_date lvm_end_date') {
                                    if (self.ks_start_date_id === self.ks_end_date_id) {
                                        self.ks_field_domain_dict[self.ks_start_date_id] = [
                                            [self.ks_start_date_id, '>=', self.ks_start_date],
                                            [self.ks_end_date_id, '<=', self.ks_end_date]
                                        ]
                                        if (self.ks_key_fields.length === 0) {
                                            self.ks_key_fields.push(self.ks_start_date_id);
                                        } else {
                                            for (var key_length = 0; key_length < self.ks_key_fields.length; key_length++) {
                                                if (!(self.ks_key_fields[key_length] === ks_options.KsSearchId)) {
                                                    self.ks_key_fields.push(self.ks_start_date_id);
                                                    break;
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        } else if (ks_advance_search_type === 'selection') {
                            if (ks_search_value === "Select a Selection") {
                                for (var j = 0; j < self.ks_key_fields.length; j++) {
                                    self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                                }
                                ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                                if (self.ks_search_domain.length === 0) {
                                    self.ksBaseDomain = []
                                }
                                ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                                self.ksDomain = ks_advance_search_params["ksDomain"]
                                self.mydomain = ks_advance_search_params["ksDomain"]
                                self.ks_update(self.mydomain);
                                //                                    self.update(ks_advance_search_params, undefined);
                            } else {

                                // obtaining values of selection
                                ks_selection_values = self.props.list.fields[ks_options.KsSearchId].selection;

                                //setting values for selection
                                for (var i = 0; i < ks_selection_values.length; i++) {
                                    if (ks_selection_values[i][1] === ks_search_value) {
                                        ks_search_value = ks_selection_values[i][0];
                                    }
                                }
                                self.ks_field_domain_dict[ks_options.KsSearchId] = [
                                    [ks_options.KsSearchId, '=', ks_search_value]
                                ]
                            }
                        } else if (ks_advance_search_type === "many2one" || ks_advance_search_type === "many2many") {
                            if (self.ks_field_domain_dict[ks_options.KsSearchId] === undefined)
                                self.ks_field_domain_dict[ks_options.KsSearchId] = [
                                    [ks_options.KsSearchId, "ilike", ks_search_value]
                                ]
                            else
                                self.ks_field_domain_dict[ks_options.KsSearchId].push([ks_options.KsSearchId, "ilike", ks_search_value])

                            if (self.ks_field_domain_dict[ks_options.KsSearchId].length > 1) {
                                self.ks_field_domain_dict[ks_options.KsSearchId].unshift("|")
                            }
                            //                                ks_advance_search_params["ids"] = self.initialState.res_id;
                        } else if (ks_advance_search_type === 'monetary' || ks_advance_search_type === 'integer' || ks_advance_search_type === 'float') {
                            self.ks_field_domain_dict[ks_options.KsSearchId] = [
                                [ks_options.KsSearchId, '=', ks_search_value]
                            ]

                        }
                        else if (ks_advance_search_type === 'char') {
                            if (self.ks_field_domain_dict[ks_options.KsSearchId] === undefined) {
                                self.ks_field_domain_dict[ks_options.KsSearchId] = [
                                    [ks_options.KsSearchId, 'ilike', ks_search_value]
                                ]
                            }
                            else { self.ks_field_domain_dict[ks_options.KsSearchId].push([ks_options.KsSearchId, 'ilike', ks_search_value]) }
                            if (self.ks_field_domain_dict[ks_options.KsSearchId].length > 1) {
                                self.ks_field_domain_dict[ks_options.KsSearchId].unshift("|")
                            }
                        }

                        else {
                            self.ks_field_domain_dict[ks_options.KsSearchId] = [
                                [ks_options.KsSearchId, "ilike", ks_search_value]
                            ]
                        }

                        if (ks_advance_search_type === "datetime" || ks_advance_search_type === "date") {
                            if (ks_options.ksFieldIdentity === ks_options.KsSearchId + '_lvm_end_date lvm_end_date') {
                                for (var j = 0; j < self.ks_key_fields.length; j++) {
                                    this.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                                }
                                ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                                if (self.ks_search_domain.length === 0) {
                                    self.ksBaseDomain = []
                                }
                                ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                                self.ksDomain = ks_advance_search_params["ksDomain"]
                                self.mydomain = ks_advance_search_params["ksDomain"]
                                self.ks_update(self.mydomain);
                                // Fixme update
                                //                                    self.update(ks_advance_search_params, undefined);
                                self.ks_start_date = undefined;
                                self.ks_end_date = undefined;
                                self.ks_start_date_id = undefined;
                                self.ks_end_date_id = undefined;
                            }
                        } else {
                            if (ks_advance_search_type === 'monetary' || ks_advance_search_type === 'integer' || ks_advance_search_type === 'float') {
                                if (!(isNaN(ks_search_value))) {
                                    for (var j = 0; j < self.ks_key_fields.length; j++) {
                                        self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                                    }
                                    ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                                    if (self.ks_search_domain.length === 0) {
                                        self.ksBaseDomain = []
                                    }
                                    ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                                    self.ksDomain = ks_advance_search_params["ksDomain"]
                                    self.mydomain = ks_advance_search_params["ksDomain"]
                                    self.ks_update(self.mydomain);
                                    // FIXME update
                                    //                                        self.update(ks_advance_search_params, undefined);
                                } else {
                                    if (self.ks_search_domain.length === 0) {
                                        self.ksBaseDomain = []
                                    }
                                    ks_advance_search_params["domain"] = self.ksDomain || []
                                    self.mydomain = ks_advance_search_params["domain"]
                                    self.ks_update(self.mydomain);
                                    // Fixme update
                                    //                                        self.update(ks_advance_search_params, undefined);
                                }
                            } else {
                                for (var j = 0; j < self.ks_key_fields.length; j++) {
                                    self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                                }
                                ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                                if (self.ks_search_domain.length === 0) {
                                    self.ksBaseDomain = []
                                }
                                ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                                self.ksDomain = ks_advance_search_params["ksDomain"];
                                self.mydomain = ks_advance_search_params["ksDomain"]
                                self.ks_update(self.mydomain);
                                // Fixme update
                                //                                    self.update(ks_advance_search_params, undefined);
                            }
                        }
                    } else {
                        for (var j = 0; j < self.ks_key_fields.length; j++) {
                            self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                        }
                        ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                        if (self.ks_search_domain.length === 0) {
                            self.ksBaseDomain = []
                        }
                        ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                        self.ksDomain = ks_advance_search_params["ksDomain"]
                        self.mydomain = ks_advance_search_params["ksDomain"]
                        self.ks_update(self.mydomain);
                        // Fixme update
                        //                            self.update(ks_advance_search_params, undefined);
                    }
                } else {
                    self.ks_advance_search_refresh = true;
                    //                        var ks_search_value = $('#' + ks_options.data.KsSearchId).val().trim();
                    if (ks_options.ksfieldtype == "selection") {
                        var ks_search_value = $(".custom-control-searchbar-change[data-name=" + ks_options.KsSearchId + "]").val().trim();
                    } else {
                        var ks_search_value = $(".custom-control-searchbar-advance[data-name=" + ks_options.KsSearchId + "]").val();
                    }
                    //                        var ks_search_value = $(".custom-control-searchbar-advance[data-name=" + ks_options.data.KsSearchId + "]").val().trim();
                    var ks_advance_search_type = ks_options.ksfieldtype;
                    var ks_selection_values = [];
                    var ks_advance_search_params = {};
                    self.ks_field_domain_list = [];
                    self.ks_key_insert_flag = false;
                    var ks_data_insert_flag = false;
                    var ks_value = ks_options.KsSearchId.split("_lvm_start_date")

                    ks_advance_search_params["modelName"] = self.props.list.resModel;
                    ks_advance_search_params["context"] = self.props.context;
                    ks_advance_search_params["ids"] = ks_options.res_ids;
                    ks_advance_search_params["offset"] = self.props.list.model.root.offset;
//                    ks_advance_search_params["currentId"] = self.renderer.state.res_id;
                    ks_advance_search_params["selectRecords"] = self.props.list.model.root.selection;
                    ks_advance_search_params["groupBy"] = [];

                    for (var j = 0; j < self.ks_key_fields.length; j++) {
                        self.ks_field_domain_list = self.ks_field_domain_list.concat(self.ks_field_domain_dict[self.ks_key_fields[j]]);
                    }
                    ks_advance_search_params["ksDomain"] = self.ks_field_domain_list;
                    if (self.ks_search_domain.length === 0) {
                        self.ksBaseDomain = []
                    }
                    ks_advance_search_params["domain"] = self.ksBaseDomain.concat(self.ks_field_domain_list)
                    self.ksDomain = ks_advance_search_params["ksDomain"]
                    self.mydomain = ks_advance_search_params["ksDomain"]
                    self.ks_update(self.mydomain);

                }
            }
        }
    },

        async ks_update(data) {
//    this.props.ks_renderer_update(data);
        const list = this.props.list.model.root;
//        list.domain = []
        this.ks_search_domain  = [];
        var browser_search_domain =[];
        this.env.searchModel.globalDomain = [];
        for (let item of this.default_domain){
            if (item != undefined){
                this.ks_search_domain.push(item);
            }
        }
        for (let items of this.search_default){
            if (items != undefined){
                this.env.searchModel.globalDomain.push(items);
            }
        }
        for(let ks_domain of data){
            if (ks_domain != undefined){
//                list.domain.push(ks_domain);
                this.env.searchModel.globalDomain.push(ks_domain);
                this.ks_search_domain.push(ks_domain)
//                browser_search_domain.push(ks_domain)
            }
        }
//        browser.localStorage.setItem("ks_actionid",this.env.config.actionId);
//        browser.localStorage.setItem("search_domain",JSON.stringify(browser_search_domain));
//        browser.localStorage.setItem("ks_model",list.resModel);
//        browser.localStorage.setItem("field_dict",JSON.stringify(this.ks_field_domain_dict));
//        browser.localStorage.setItem("key_field",JSON.stringify(this.ks_key_fields));
        await this.env.searchModel._notify();

        },

        ks_remove_popup_domain_event(e,field_type) {
        if ($(e.target).hasClass("ks_remove_popup")) {

            var div = e.target.closest('.ks_inner_search')
//            var innerSearchDivs = document.querySelectorAll('.ks_search .ks_inner_search');
//            var lastInnerSearchDiv = innerSearchDivs[innerSearchDivs.length - 1];
            $('#end_date').addClass('d-none');
            $('#start_date').removeClass('ks_date_main')
            var ks_remove_options = {
                ksDiv: div,
                ksfieldtype: e.target.parentElement.parentElement.children[1].dataset.fieldType || field_type
            };
            this.ks_remove_popup_domain(ks_remove_options);
        }
    },

        ks_remove_popup_domain(ks_options) {
        if (this.ks_lvm_mode) {
            var self = this;
            var ks_i;
            var key;
            var key_array;

            if (ks_options.ksDiv !== undefined) {
                key_array = ks_options.ksDiv.id.split("_value")
                key = key_array[0];
                if(key === 'product_template_variant'){
                    key = key+'_value'+'_ids'
                }
            } else {
                key = event.target.id;
            }

            if (self.ks_field_domain_dict[key] !== undefined) {
                if (self.ks_field_domain_dict[key].length === 1 || ks_options.ksfieldtype === "date" || ks_options.ksfieldtype === "datetime") {
                    delete self.ks_field_domain_dict[key]
                    for (ks_i = 0; ks_i < self.ks_key_fields.length; ks_i++) {
                        if (key === self.ks_key_fields[ks_i]) {
                            break;
                        }
                    }

                    if (ks_options.ksDiv !== undefined) {
//                        $("#" + ks_options.ksDiv.id).remove()
                    } else {
                        // fixme
                        //                            $("#" + $(ks_options.event.target).parent().children()[$(ks_options.data.event.target).parent().children().length - 2].id).remove();
                    }

                    self.ks_key_fields.splice(ks_i, 1);
                    self.ks_remove_popup_flag = true;
                    self.Ks_update_advance_search_controller(false);
                } else {
                    for (var j = 0; j < self.ks_field_domain_dict[key].length; j++) {
                        if (self.ks_field_domain_dict[key][j] !== '|') {
                            if (ks_options.ksDiv !== undefined) {
                                if (self.ks_field_domain_dict[key][j][2] === ks_options.ksDiv.innerText) {
                                    self.ks_field_domain_dict[key].splice(j, 1)
                                    self.ks_field_domain_dict[key].splice(0, 1);
                                    break;
                                }

                            } else {
                                self.ks_field_domain_dict[key].splice(j, 1)
                                self.ks_field_domain_dict[key].splice(0, 1);
                                break;
                            }
                        }
                    }
                    if (ks_options.ksDiv !== undefined) {
//                        $("#" + ks_options.ksDiv.id).remove()
                    } else {
                        //fixme
                        //                            $("#" + $(ks_options.data.event.target).parent().children()[$(ks_options.data.event.target).parent().children().length - 2].id).remove();
                    }
                    self.ks_remove_popup_flag = true;
                    self.Ks_update_advance_search_controller(false);
                }
            } else {
                self.ks_remove_popup_flag = true;
                self.Ks_update_advance_search_controller(false);
            }
        }
    },

        getRowClass(record) {
            var classNames = super.getRowClass(...arguments);
            if (this.props.list.selection && this.props.list.selection.length > 0) {
                $('.copy_button').css('display', 'block')
            } else {
                $('.copy_button').css('display', 'none');
            }
            if (record.selected) {
                $('.o_data_row[data-id="' + record.id + '"]').addClass('ks_highlight_row');
                classNames = "o_data_row_selected"
            }else{
            $('.o_data_row[data-id="' + record.id + '"]').removeClass('ks_highlight_row');
            }
            return classNames;
        },

    toggleSelection() {
        super.toggleSelection(...arguments);
        if (this.props.list.selection && this.props.list.selection.length === 0) {
            $('.o_data_row').removeClass('ks_highlight_row');
            $('.o_data_row').addClass('text-info');
        }
    },

    toggleRecordSelection(record) {
        super.toggleRecordSelection(...arguments);
        if (!record.selected) {
            $('.o_data_row[data-id="' + record.id + '"]').removeClass('ks_highlight_row');
            $('.o_data_row[data-id="' + record.id + '"]').addClass('text-info');
        }
    },
    onClickCapture(record, ev) {
        super.onClickCapture(...arguments);
        if ($(ev.currentTarget).hasClass("ks_highlight_row")){
            $(document.querySelectorAll(".ks_highlight_row")).removeClass("ks_highlight_row")
        }
    },
            freezeColumnWidths() {
            if (!this.ks_is_lines){
                var tableRef = this.tableRef;
        //        const headers = [...tableRef.el.querySelectorAll("thead .bg-primary th:not(.o_list_actions_header)")];
                $(tableRef.el).hasClass('o_field_many2many')
                if (session.ks_header_text_color !="white"){
                    var ks_header_text_color = session.ks_header_text_color;
//                    $(tableRef.el.querySelectorAll("thead .bg-primary")).find("th").addClass('ks_header_text_color').css('color', ks_header_text_color + ' !important')
                       (tableRef.el.querySelectorAll("thead .bg-primary th")).forEach((item) =>{item.style.setProperty("color", session.ks_header_text_color, "important")})
                }
                if (session.ks_header_color){
                    var ks_header_color = session.ks_header_color;
                    (tableRef.el.querySelectorAll("thead .bg-primary th")).forEach((item,index) =>{
                        if (index === 0){
                            item.style.setProperty("background-color", session.ks_header_color, "important")
                            const formCheckInput = item.querySelector('.form-check-input');
                            if (formCheckInput) {
                                // If it exists, set the border color
                                formCheckInput.style.setProperty("border-color", session.ks_header_text_color, "important");
                            }
                        }else{
                            item.style.setProperty("background-color", session.ks_header_color, "important")
                        }
                    })
                }
                if (tableRef.el && ($(tableRef.el).hasClass('o_field_one2many') !== false || $(tableRef.el).hasClass('o_field_many2many') !== false)) {
                    super.freezeColumnWidths();
                }
                if (!this.keepColumnWidths) {
                    this.columnWidths = null;
                }

                if ($('.o_optional_columns_dropdown').length === 1 && !session.ks_dynamic_list_show) {
                    $('.o_optional_columns_dropdown').parent().removeClass('d-none');
                }

                const headers = [...tableRef.el.querySelectorAll("thead .bg-primary th:not(.o_list_actions_header)")];

                if (!this.columnWidths || !this.columnWidths.length) {
                    tableRef.el.style.tableLayout = "fixed";
                     const allowedWidth = tableRef.el.parentNode.getBoundingClientRect().width;
                      // Set table layout auto and remove inline style to make sure that css
                        // rules apply (e.g. fixed width of record selector)
                    tableRef.el.style.tableLayout = "auto";
                    headers.forEach((th) => {
                        th.style.width = null;
                        th.style.maxWidth = null;
                    });

                    this.setDefaultColumnWidths();

                    this.columnWidths = this.computeColumnWidthsFromContent(allowedWidth);
                    tableRef.el.style.tableLayout = "fixed";
                }

                headers.forEach((th, index) => {
                    if (!th.style.width) {
                        th.style.width = `${Math.floor(this.columnWidths[index])}px`;
                    }
                    if(!parseInt(th.style.width)|| th.style.width == "100%"){
                     th.style.width = '';
                     th.style['max-width'] = '';
                     }
                });

                if (this.props.activeActions && this.props.activeActions.type === 'view') {
                    var table_width = 0
                    this.allColumns.forEach((item,index) =>{
                       if(item.attrs && item.attrs.width !== undefined &&  parseInt(item.attrs.width) != 0  && $("thead .bg-primary th[data-name="+item.name+"]").length > 0){
                            $("thead .bg-primary th[data-name="+item.name+"]")[0].style.width = `${Math.floor(parseInt(item.attrs.width))}px`;
                            $("thead .bg-primary th[data-name="+item.name+"]")[0].style['max-width'] = `${Math.floor(parseInt(item.attrs.width))}px`;
                            table_width +=parseInt(item.attrs.width)
                            }
//                        }else{
//                        table_width+=this.columnWidths[index]
//                        }

                    });
                }

//                for (let item of (tableRef.el.querySelectorAll("thead .bg-primary th"))){
//                    if(!parseInt(item.style.width)){
////                        tableRef.el.querySelector("thead").parentElement.style.tableLayout="auto";
////                        tableRef.el.querySelector("thead").parentElement.style.width=`${table_width}px`;
//                    break;
//                }
//                }
            }else{
                super.freezeColumnWidths();
            }
        },
        computeColumnWidthsFromContent(allowedWidth) {

            if (!this.ks_is_lines){

                const table = this.tableRef.el;

                // Toggle a className used to remove style that could interfere with the ideal width
                // computation algorithm (e.g. prevent text fields from being wrapped during the
                // computation, to prevent them from being completely crushed)
                table.classList.add("o_list_computing_widths");

                const headers = [...table.querySelectorAll("thead .bg-primary th")];
                const columnWidths = headers.map((th) => th.getBoundingClientRect().width);
                const getWidth = (th) => columnWidths[headers.indexOf(th)] || 0;
                const getTotalWidth = () => columnWidths.reduce((tot, width) => tot + width, 0);
                const shrinkColumns = (thsToShrink, shrinkAmount) => {
                    let canKeepShrinking = true;
                    for (const th of thsToShrink) {
                        const index = headers.indexOf(th);
                        let maxWidth = columnWidths[index] - shrinkAmount;
                        // prevent the columns from shrinking under 92px (~ date field)
                        if (maxWidth < 92) {
                            maxWidth = 92;
                            canKeepShrinking = false;
                        }
                        th.style.maxWidth = `${Math.floor(maxWidth)}px`;
                        columnWidths[index] = maxWidth;
                    }
                    return canKeepShrinking;
                };
                // Sort columns, largest first
                const sortedThs = [...table.querySelectorAll("thead .bg-primary th:not(.o_list_button)")].sort(
                    (a, b) => getWidth(b) - getWidth(a)
                );

                let totalWidth = getTotalWidth();
                for (let index = 1; totalWidth > allowedWidth; index++) {
                    // Find the largest columns
                    const largestCols = sortedThs.slice(0, index);
                    const currentWidth = getWidth(largestCols[0]);
                    for (; currentWidth === getWidth(sortedThs[index]); index++) {
                        largestCols.push(sortedThs[index]);
                    }

                    // Compute the number of px to remove from the largest columns
                    const nextLargest = sortedThs[index];
                    const toRemove = Math.ceil((totalWidth - allowedWidth) / largestCols.length);
                    const shrinkAmount = Math.min(toRemove, currentWidth - getWidth(nextLargest));

                    // Shrink the largest columns
                    const canKeepShrinking = shrinkColumns(largestCols, shrinkAmount);
                    if (!canKeepShrinking) {
                        break;
                    }

                    totalWidth = getTotalWidth();
                }

                // We are no longer computing widths, so restore the normal style
                table.classList.remove("o_list_computing_widths");
                return columnWidths;
            }else{
                return super.computeColumnWidthsFromContent(...arguments);
            }
    },


    onStartResize(ev) {
        super.onStartResize(...arguments);
        if (!this.ks_is_lines){
            const table = this.tableRef.el;
            const th = ev.target.closest("th");
            const handler = th.querySelector(".o_resize");
            table.style.width = `${Math.floor(table.getBoundingClientRect().width)}px`;
            const thPosition = [...th.parentNode.children].indexOf(th);
            const resizingColumnElements = [...table.getElementsByTagName("tr")]
                .filter((tr) => tr.children.length === th.parentNode.children.length)
                .map((tr) => tr.children[thPosition]);
            const initialX = ev.clientX;
            const initialWidth = th.getBoundingClientRect().width;
            const initialTableWidth = table.getBoundingClientRect().width;
            const resizeStoppingEvents = ["keydown", "mousedown", "mouseup"];

            const stopResize = (ev) => {
                for (const eventType of resizeStoppingEvents) {
                    window.removeEventListener(eventType, stopResize);
                }

                // we remove the focus to make sure that the there is no focus inside
                // the tr.  If that is the case, there is some css to darken the whole
                // thead, and it looks quite weird with the small css hover effect.
                document.activeElement.blur();
                this.ks_data_width = $(resizingColumnElements[0]).innerWidth();
                var ks_field_data_width = this.ks_list_data.fields_data[resizingColumnElements[0].dataset.name];
                ks_field_data_width.ks_width = this.ks_data_width;
                if (!this.ks_list_data.table_data){
                         this.props.Ks_initialize_lvm_data(this.ks_list_data.fields_data,true);
                }else{
                    this.props.Ks_update_field_data([], [ks_field_data_width], true,true);
                    }

            };
            for (const eventType of resizeStoppingEvents) {
                window.addEventListener(eventType, stopResize);
            }
        }
    },
    async onCellClicked(record, column, ev) {
    if (this.ks_is_lines){
        super.onCellClicked(...arguments);
    }
    if (this.props.activeActions.type == 'view'){
        if (window.getSelection().toString() && this.props.activeActions.type == 'view') {
            return;
        }
        if (this.ks_list_data){
            if (this.ks_lvm_mode && this.ks_list_data.table_data.ks_editable && this.props.activeActions.type == 'view') {
                if (ev.target.special_click) {
                    return;
                }
                const recordAfterResequence = async () => {
                    const recordIndex = this.props.list.records.indexOf(record);
                    await this.resequencePromise;
                    // row might have changed record after resequence
                    record = this.props.list.records[recordIndex] || record;
                };
                if (record.isInEdition && this.props.list.editedRecord === record) {
                    this.focusCell(column);
                    this.cellToFocus = null;
                } else {
                    await recordAfterResequence();
                    await record.switchMode("edit");
                    this.cellToFocus = { column, record };
                }

            } else {
                super.onCellClicked(...arguments);
            }
            }else{
                super.onCellClicked(...arguments);
            }
        }
},

  });

  ListRenderer.components = { ...ListRenderer.components , SearchView };


ListRenderer.props = [...ListRenderer.props,
    "Ks_update_field_data?",
    "Ks_initialize_lvm_data?",
    "list_data?",
];
