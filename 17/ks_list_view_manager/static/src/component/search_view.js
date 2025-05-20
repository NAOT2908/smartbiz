/** @odoo-module */

import { Component,useState,useExternalListener,useRef} from "@odoo/owl";
import { jsonrpc } from "@web/core/network/rpc_service";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import {formatDate,formatDateTime} from "@web/core/l10n/dates";
import {parseDateTime,parseDate,} from "@web/core/l10n/dates";
import { formatFloat,formatInteger } from "@web/views/fields/formatters";



export class SearchView extends Component {
   setup()  {
          this.state = useState({
                startdate:false,
                enddate:false,
          })
          this.start_date = null;
          this.end_date = null;
          this.ks_autocomplete_data = {};
         this.ks_autocomplete_data_result = {};
         this.root = useRef("root");
         this.ks_allow_search = true;


   }

   async ks_advance_searchbar(request) {
            // block of code for Autocomplete
            var self = this;
            this.ks_allow_search = true;
            var ks_field_type = self.props.ks_field_type;
            var ks_field_name = self.props.ks_field_id;
            var ks_one2many_relation;
            var ks_input_val = request.target.value;

            if (ks_input_val){


                if (ks_field_type === "one2many") {
                    ks_one2many_relation = self.props.list.fields[ks_field_name].relation
                }

                this.env.services.orm.searchRead(self.props.model,[[ks_field_name,"ilike",ks_input_val]],[ks_field_name]).then(function(ks_auto_Data){

                        self.ks_autocomplete_data_result = ks_auto_Data
                        if (self.props.model === 'hr.employee.skill.report' && ks_field_name === 'level_progress'){
                            for (var i=0; i< ks_auto_Data.length; i++){
                                ks_auto_Data[i]['level_progress'] = (ks_auto_Data[i]['level_progress'])*100

                            }

                        }

                        if (!(ks_field_type === "date" || ks_field_type === "datetime" || ks_field_type === "selection")) {
                            var ks_unique_data = {}
                            self.ks_autocomplete_data[ks_field_name] = [];

                            if (ks_field_type === 'one2many') {
                                for (var i = 0; i < self.ks_autocomplete_data_result.length; i++) {

                                    if (!(ks_unique_data[self.ks_autocomplete_data_result[i]])) {
                                        self.ks_autocomplete_data[ks_field_name].push(String(self.ks_autocomplete_data_result[i]));
                                        ks_unique_data[self.ks_autocomplete_data_result[i]] = true;
                                    }
                                }
                            } else if (ks_field_type === 'many2many' || ks_field_type === 'many2one') {
                                for (var i = 0; i < self.ks_autocomplete_data_result.length; i++) {

                                    if (!(ks_unique_data[self.ks_autocomplete_data_result[i][ks_field_name][1]])) {
                                        self.ks_autocomplete_data[ks_field_name].push(String(self.ks_autocomplete_data_result[i][ks_field_name][1]));
                                        ks_unique_data[self.ks_autocomplete_data_result[i][ks_field_name][1]] = true;
                                    }
                                }
                            } else {
                                for (var i = 0; i < self.ks_autocomplete_data_result.length; i++) {

                                    if (!(ks_unique_data[self.ks_autocomplete_data_result[i][ks_field_name]])) {
                                        self.ks_autocomplete_data[ks_field_name].push(String(self.ks_autocomplete_data_result[i][ks_field_name]));
                                        ks_unique_data[self.ks_autocomplete_data_result[i][ks_field_name]] = true;
                                    }
                                }
                            }



                           if (ks_field_type != 'many2many'){
                            $(".custom-control-searchbar-advance[data-name=" + ks_field_name + "]").autocomplete({
                                source: self.ks_autocomplete_data[ks_field_name],
                                response: function (event, ui) {
                                    if (!ui.content.length) {
                                        var noResult = { value: "", label: "No results found" };
                                        ui.content.push(noResult);
                                    }
                                }

                            }).keydown(function(event) {
                                if (event.keyCode == 13) { // Check if Enter key is pressed
                                    $(this).autocomplete("close"); // Close the autocomplete dropdown
                                }
                            });
                        }


                }

                });

                if (request.keyCode == 8 && this.ks_allow_search) {
                    if (request.target.parentNode.children.length !== 1) {
                        this.props.ks_remove_search(request);
                        this.ks_allow_search = false;
                    }
                }
            if (request.keyCode == 13 && this.ks_allow_search) {
                var options = {
                    ksFieldName: self.props.ks_description,
                    KsSearchId: self.props.ks_field_id,
                    ksfieldtype: self.props.ks_field_type,
                };

                this.props.ks_search_event(options)
                this.ks_allow_search = false;
            }

            }


    }

   ks_on_start_date_filter_change(date,check){
        var self=this
        var ks_date_field_name = self.props.ks_field_id
        if (check === 1){
                self.start_date = $('#start_date').find('#input_start_val').val();
                var ks_date_widget = new Date(self.start_date);
                var search_id = self.props.ks_field_id + "_lvm_start_date"
                var field_identity = search_id + " lvm_start_date"
        }else{
                self.end_date = $('#end_date').find('#input_end_val').val();
                var ks_date_widget = new Date(self.end_date);
                var search_id = self.props.ks_field_id + "_lvm_end_date"
                var field_identity = search_id + " lvm_end_date"
        }
        if (self.start_date){
            $('#end_date').removeClass('d-none');
            $('#start_date').addClass('ks_date_main')

          var ks_options = {
                ksFieldName: self.props.ks_description,
                KsSearchId: search_id,
                ksfieldtype: self.props.ks_field_type,
                ksFieldIdentity:field_identity,
                ks_val: ks_date_widget.toISOString()
          }
          this.props.ks_search_event(ks_options);
        }else{
            $('#end_date').addClass('d-none');
            $('#start_date').removeClass('ks_date_main')
        }
   }


     ks_change_event(e) {
        var self=this;
            if (self.props.ks_field_type !== "datetime" && self.props.ks_field_type !== 'date') {
                var ks_options = {
                    ksFieldName: self.props.ks_description,
                    KsSearchId: self.props.ks_field_id,
                    ksfieldtype: self.props.ks_field_type,
                }
                this.props.ks_search_event(ks_options)

            }

    }

    format_text(data){
        return formatFloat(parseFloat(data),{digits: [0, 2]})
    }
    get placeholder(){
        if (!(this.props.ks_field_type === 'many2one' || this.props.ks_field_type === 'many2many' || this.props.ks_field_type === 'one2many') && !this.props.ks_field_search_info[this.props.ks_field_id]){
            return "Search..."
        }
        else if(this.props.ks_field_type === 'many2one' || this.props.ks_field_type === 'many2many' || this.props.ks_field_type === 'one2many'){
            return "Search..."
        }else{
            return ""
        }
    }
    get value(){
        return ''
    }


   };

    SearchView.template = "Ks_list_view_advance_search";
    SearchView.props = {
                   ks_field_id : { type: String ,Optional:true } ,
                   ks_description: { type: String,Optional:true },
                   ks_field_type:  { type: String, Optional:true },
//                   ks_field_identity: { type: String, Optional:true },
                   ks_selection_values: { type: Array , Optional:true },
                   ks_search_event : {type:Function,Optional:true},
                   model:{type:String,Optional:true},
                   ks_field_search_info:{type:Object , optional:true},
                   ks_remove_search:{type:Function,optional:true}
                };
     SearchView.components={DateTimeInput}
