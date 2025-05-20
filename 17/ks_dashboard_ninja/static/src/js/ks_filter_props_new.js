/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { Dialog } from "@web/core/dialog/dialog";
import {KsDashboardNinja} from "@ks_dashboard_ninja/js/ks_dashboard_ninja_new";
import { _t } from "@web/core/l10n/translation";
import { renderToElement,renderToString,renderToFragment } from "@web/core/utils/render";
import { isBrowserChrome, isMobileOS } from "@web/core/browser/feature_detection";
import { Ksdashboardtile } from '@ks_dashboard_ninja/components/ks_dashboard_tile_view/ks_dashboard_tile';
import { getDomainDisplayedOperators } from "@web/core/domain_selector/domain_selector_operator_editor";
import { getOperatorLabel } from "@web/core/tree_editor/tree_editor_operator_editor";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
const { DateTime } = luxon;
import {formatDate,formatDateTime} from "@web/core/l10n/dates";
import {parseDateTime,parseDate,} from "@web/core/l10n/dates";
import { serializeDateTime, serializeDate } from "@web/core/l10n/dates";
import { session } from "@web/session";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component } from "@odoo/owl";


const ks_field_type = {
    binary: "binary",
    boolean: "boolean",
    char: "char",
    date: "date",
    datetime: "datetime",
    float: "number",
    html: "char",
    id: "id",
    integer: "number",
    many2many: "char",
    many2one:"char",
    monetary: "number",
    one2many: "char",
    selection: "selection",
    text: "char"
}


export class FavFilterWizard extends Component{

    setup(){

    }

}

FavFilterWizard.template = "ks_dashboard_ninja.FavFilterWizard"

FavFilterWizard.components = { Dialog }


patch(KsDashboardNinja.prototype,{
    ks_fetch_items_data(){
        var self = this;
        return super.ks_fetch_items_data().then(function(){
            if (self.ks_dashboard_data.ks_dashboard_domain_data) self.ks_init_domain_data_index();
        });
    },

    ks_init_domain_data_index(){
        var self = this;
        // TODO: Make domain data index from backend : loop wasted
        var temp_data = {};
        var to_insert = Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{
            return x.type==='filter' && x.active && self.ks_dashboard_data.ks_dashboard_domain_data[x.model].ks_domain_index_data.length === 0
        });
        (to_insert).forEach((x)=>{
            this.isPredefined = true
            if(x['categ'] in temp_data) {
               temp_data[x['categ']]['domain']= temp_data[x['categ']]['domain'].concat(x['domain']);
               temp_data[x['categ']]['label']= temp_data[x['categ']]['label'].concat(x['name']);
            } else {
                temp_data[x['categ']] = {'domain': x['domain'], 'label': [x['name']], 'categ': x['categ'], 'model': x['model']};
            }
        })
        Object.values(temp_data).forEach((x)=>{
            this.isModelVisePredefined[x.model] = true;
            self.ks_dashboard_data.ks_dashboard_domain_data[x.model].ks_domain_index_data.push(x);
        })
    },
    onKsDnDynamicFilterSelect(ev){
        var self = this;
        if(this.isFavFilter){
            self.ks_dashboard_data.ks_dashboard_domain_data = {}
            self.header.el?.querySelector('.ks_fav_filters_checked')?.classList.remove('ks_fav_filters_checked', 'global-active')
        }
        this.isFavFilter = false;
        self.header.el?.querySelector('.predefined-filters')?.classList.add('disabled')

        if($(ev.currentTarget).hasClass('dn_dynamic_filter_selected')){
            self._ksRemoveDynamicFilter(ev.currentTarget.dataset['filterId']);
            $(ev.currentTarget).removeClass('dn_dynamic_filter_selected');
        } else {
            self._ksAppendDynamicFilter(ev.currentTarget.dataset['filterId']);
            $(ev.currentTarget).addClass('dn_dynamic_filter_selected');
        }
        var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
        if(storedData !== null ){
            this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
        }
        if(Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).length !==0){
            this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, self.ks_dashboard_data.ks_dashboard_domain_data, 1);
        }else{
            this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, {}, 1);
        }
    },

    _ksAppendDynamicFilter(filterId){
        // Update predomain data -> Add into Domain Index -> Add or remove class
        this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].active = true;

        var action = 'add_dynamic_filter';

        var categ = this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].categ;
        var params = {
            'model': this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].model,
            'model_name': this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].model_name,
        }
        this._ksUpdateAddDomainIndexData(action, categ, params);
    },

    _ksRemoveDynamicFilter(filterId){
         // Update predomain data -> Remove from Domain Index -> Add or remove class
        this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].active = false;

        var action = 'remove_dynamic_filter';
        var categ = this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].categ;
        var params = {
            'model': this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].model,
            'model_name': this.ks_dashboard_data.ks_dashboard_pre_domain_filter[filterId].model_name,
        }
        this._ksUpdateRemoveDomainIndexData(action, categ, params);
    },

    _ksUpdateAddDomainIndexData(action, categ, params){
        // Update Domain Index: Add or Remove model related data, Update its domain, item ids
        // Fetch records for the effected items
        // Re-render Search box of this name if the value is add
        var self = this;
        self.header.el?.querySelector('.custom-filter-tab')?.classList.remove('disabled-div');
        this.isPredefined = true
        var model = params['model'] || false;
        this.isModelVisePredefined[model] = true;
        var model_name = params['model_name'] || '';
        $(".ks_dn_filter_applied_container").removeClass('ks_hide');

        var filters_to_update = Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{return x.active === true && x.categ === categ});
        var domain_data = self.ks_dashboard_data.ks_dashboard_domain_data[model];
        if (domain_data) {
            var domain_index = (domain_data.ks_domain_index_data).find((x)=>{return x.categ === categ});
            if (domain_index) {
                domain_index['domain'] = [];
                domain_index['label'] = [];
                (filters_to_update).forEach((x)=>{
                    if (domain_index['domain'].length>0) domain_index['domain'].unshift('|');
                    domain_index['domain'] = domain_index['domain'].concat(x['domain']);
                    domain_index['label'] = domain_index['label'].concat(x['name']);
                })
            } else {
                domain_index = {
                    categ: categ,
                    domain: [],
                    label: [],
                    model: model,
                };
                filters_to_update.forEach((x)=>{
                    if (domain_index['domain'].length>0) domain_index['domain'].unshift('|');
                    domain_index['domain'] = domain_index['domain'].concat(x['domain']);
                    domain_index['label'] = domain_index['label'].concat(x['name']);
                });
                domain_data.ks_domain_index_data.push(domain_index);
            }

        } else {
            var domain_index = {
                    categ: categ,
                    domain: [],
                    label: [],
                    model: model,
            };
            filters_to_update.forEach((x)=>{
                if (domain_index['domain'].length>0) domain_index['domain'].unshift('|');
                domain_index['domain'] = domain_index['domain'].concat(x['domain']);
                domain_index['label'] = domain_index['label'].concat(x['name']);
            });
            domain_data = {
                'domain': [],
                'model_name': model_name,
                'item_ids': self.ks_dashboard_data.ks_model_item_relation[model],
                'ks_domain_index_data': [domain_index],
            };
            self.ks_dashboard_data.ks_dashboard_domain_data[model] = domain_data;
        }

        domain_data['domain'] = self._ksMakeDomainFromDomainIndex(domain_data.ks_domain_index_data);
        self.state.pre_defined_filter = {...domain_data}
        self.state.ksDateFilterSelection = 'none'
        self.state.custom_filter = {}
        var storedPredefinedData = this.getObjectFromCookie('PredefinedData' + self.ks_dashboard_id);
        if(storedPredefinedData !== null ){
            this.eraseCookie('PredefinedData' + self.ks_dashboard_id);
        }
        if(Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).length !==0){
            this.setObjectInCookie('PredefinedData' + self.ks_dashboard_id, self.ks_dashboard_data.ks_dashboard_pre_domain_filter, 1);
        }else{
            this.setObjectInCookie('PredefinedData' + self.ks_dashboard_id, {}, 1);
        }
    },

    _ksUpdateRemoveDomainIndexData(action, categ, params){
        var self = this;
        var model = params['model'] || false;
        var model_name = params['model_name'] || '';
        var filters_to_update = Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{return x.active === true && x.categ === categ});
        var domain_data = self.ks_dashboard_data.ks_dashboard_domain_data[model];
        var domain_index = (domain_data?.ks_domain_index_data)?.find((x)=>{return x.categ === categ});


        if (filters_to_update.length<1) {
            if (domain_data.ks_domain_index_data.length>1){
                domain_data.ks_domain_index_data.splice(domain_data.ks_domain_index_data.indexOf(domain_index),1);
//                $('.o_searchview_facet[data-ks-categ="'+ categ + '"]').remove();
            }else {
//                $('.ks_dn_filter_section_container[data-ks-model-selector="'+ model + '"]').remove();
                delete self.ks_dashboard_data.ks_dashboard_domain_data[model];
                if(!Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).length){
                    $(".ks_dn_filter_applied_container").addClass('ks_hide');
                }
            }
        } else{
            domain_index['domain'] = [];
            domain_index['label'] = [];
            (filters_to_update).forEach((x)=>{
                if (domain_index['domain'].length>0) domain_index['domain'].unshift('|');
                domain_index['domain'] = domain_index['domain'].concat(x['domain']);
                domain_index['label'] = domain_index['label'].concat(x['name']);
            })
        }

        if(!domain_index) return;

        if(!Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{return x.active === true}).length){
            this.isPredefined = false
        }
        if(!Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{return x.active === true && x.model === model}).length)
                this.isModelVisePredefined[model] = false;

        domain_data['domain'] = self._ksMakeDomainFromDomainIndex(domain_data.ks_domain_index_data);
        domain_data['ks_remove'] = true
         self.state.pre_defined_filter = {...domain_data}
         if(domain_data['domain'].length != 0){
                var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
                var storedPredefinedData = this.getObjectFromCookie('PredefinedData' + self.ks_dashboard_id);
                if(storedData !== null || storedPredefinedData !== null){
                    this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
                    this.eraseCookie('PredefinedData' + self.ks_dashboard_id);
                }
                if(Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).length !==0){
                    this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, self.ks_dashboard_data.ks_dashboard_domain_data, 1);
                    this.setObjectInCookie('PredefinedData' + self.ks_dashboard_id, this.ks_dashboard_data.ks_dashboard_pre_domain_filter, 1);
                }else{
                    this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, {}, 1);
                    this.setObjectInCookie('PredefinedData' + self.ks_dashboard_id, {}, 1);
                }
            }else{
                var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
                if(storedData){
                   this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
                   var storedPredefinedData = this.getObjectFromCookie('PredefinedData' + self.ks_dashboard_id);
                   if (storedPredefinedData) this.eraseCookie('PredefinedData' + self.ks_dashboard_id);
                }
                this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, {}, 1);
                 this.setObjectInCookie('PredefinedData' + self.ks_dashboard_id, {}, 1);
            }
         self.state.ksDateFilterSelection = 'none'
         self.state.custom_filter = {}
    },

    _ksMakeDomainFromDomainIndex(ks_domain_index_data){
        var domain = [];
        (ks_domain_index_data).forEach((x)=>{
            if (domain.length>0) domain.unshift('&');
            domain = domain.concat((x['domain']));
        })
        return domain;
    },
    ksOnRemoveFilterFromSearchPanel(ev){
        var self = this;
        ev.stopPropagation();
//        ev.preventDefault();
        self.header.el?.querySelector('.predefined-filters')?.classList.add('disabled')
        var $search_section = $(ev.currentTarget).parent().parent();
        var model = $search_section.attr('ksmodel');
        if ($search_section.attr('kscateg') != '0'){
            var categ = $search_section.attr('kscateg');
            var action = 'remove_dynamic_filter';
            var $selected_pre_define_filter = $(".dn_dynamic_filter_selected.dn_filter_click_event_selector[data-ks-categ='"+ categ +"']");
            $selected_pre_define_filter.removeClass("dn_dynamic_filter_selected");
            ($selected_pre_define_filter).toArray().forEach((x)=>{
                var filter_id = $(x).data('filterId');
                self.ks_dashboard_data.ks_dashboard_pre_domain_filter[filter_id].active = false;
            })
            var params = {
                'model': model,
                'model_name': $search_section.attr('modelName'),
            }
//            $search_section.remove();
            this._ksUpdateRemoveDomainIndexData(action, categ, params);
        } else {
            var domain_data_index = $search_section.index();
            var domain_data = self.ks_dashboard_data.ks_dashboard_domain_data[model];
            domain_data.ks_domain_index_data.forEach((ks_domain_index_data, index)=>{
                if(ks_domain_index_data.isCustomFilter && domain_data_index >= 0){
                    if(domain_data_index === 0){
                        domain_data.ks_domain_index_data.splice(index, 1);
                    }
                    domain_data_index -= 1
                }
            })

            if (domain_data.ks_domain_index_data.length === 0) {
                $('.ks_dn_filter_section_container[data-ks-model-selector="'+ model + '"]').remove();
                delete self.ks_dashboard_data.ks_dashboard_domain_data[model];
                if(!Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).length){
                    $(".ks_dn_filter_applied_container").addClass('ks_hide');
                }
                }
//            } else {
//                $search_section.remove();
//            }
//            $search_section.remove();
            if(!Object.values(this.ks_dashboard_data.ks_dashboard_pre_domain_filter).filter((x)=>{return x.active === true}).length)
                this.isPredefined = false
            domain_data['domain'] = self._ksMakeDomainFromDomainIndex(domain_data.ks_domain_index_data);
            domain_data['ks_remove'] = true
            self.state.pre_defined_filter = {}
            self.state.ksDateFilterSelection = 'none'
            self.state.custom_filter = {...domain_data}
            if(domain_data['domain'].length != 0){
                var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
                if(storedData !== null ){
                    this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
                }
                this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, self.ks_dashboard_data.ks_dashboard_domain_data, 1);
            }else{
                var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
                if(storedData){
                   this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
                }
                this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, {}, 1);
            }

        }
    },

     ksGetParamsForItemFetch(item_id) {
        var self = this;
        let isCarouselParentClass = false;
        if(item_id.isCarouselParentClass){
            isCarouselParentClass = item_id.isCarouselParentClass
            item_id = item_id.item_id
        }
        var model1 = self.ks_dashboard_data.ks_item_model_relation[item_id][0];
        var model2 = self.ks_dashboard_data.ks_item_model_relation[item_id][1];

        if(model1 in self.ks_dashboard_data.ks_model_item_relation) {
            if (self.ks_dashboard_data.ks_model_item_relation[model1].indexOf(item_id)<0)
                self.ks_dashboard_data.ks_model_item_relation[model1].push(item_id);
        }else {
            self.ks_dashboard_data.ks_model_item_relation[model1] = [item_id];
        }

        if(model2 in self.ks_dashboard_data.ks_model_item_relation) {
            if (self.ks_dashboard_data.ks_model_item_relation[model2].indexOf(item_id)<0)
                self.ks_dashboard_data.ks_model_item_relation[model2].push(item_id);
        }else {
            self.ks_dashboard_data.ks_model_item_relation[model2] = [item_id];
        }

        var ks_domain_1 = self.ks_dashboard_data.ks_dashboard_domain_data[model1] && self.ks_dashboard_data.ks_dashboard_domain_data[model1]['domain'] || [];
        var ks_domain_2 = self.ks_dashboard_data.ks_dashboard_domain_data[model2] && self.ks_dashboard_data.ks_dashboard_domain_data[model2]['domain'] || [];

        if(isCarouselParentClass){
            return this.env.bus.trigger(`TV:List_Load_More_${item_id}`, {
                ks_domain_1: ks_domain_1,
                ks_domain_2: ks_domain_2,
            });
        }
        else{
            return {
                ks_domain_1: ks_domain_1,
                ks_domain_2: ks_domain_2,
            }
        }
    },

    ksRenderDashboard(){
        var self = this;
        $('<script>').attr('type', 'text/javascript')
            .attr('src', 'https://code.jquery.com/ui/1.13.2/jquery-ui.min.js')
            .appendTo('head');
        $('<link>')
        .attr('rel', 'stylesheet')
        .attr('href', 'https://code.jquery.com/ui/1.13.2/themes/base/jquery-ui.css')
        .appendTo('head');
        super.ksRenderDashboard();
        var show_remove_option = false;
         this.ks_custom_filter_option = {};
//        if (Object.values(self.ks_dashboard_data.ks_dashboard_custom_domain_filter).length>0) self.ks_render_custom_filter(show_remove_option);
    },
    ks_render_custom_filter(show_remove_option){
        let table_row_id = $('#ks_dn_custom_filters_container .ks_dn_custom_filter_input_container_section').length + 1;
        let $newRow = $('<div id="div-' + table_row_id + '" class="ks_dn_custom_filter_input_container_section table-row"></div>');
        var self = this;
        var $container = $(renderToFragment('ks_dn_custom_filter_input_container', {
                          ks_dashboard_custom_domain_filter: Object.values(this.ks_dashboard_data.ks_dashboard_custom_domain_filter),
                          show_remove_option: show_remove_option,
                          self: self,
                          trId: "div-" + table_row_id
                          }));
        $newRow.append($container);
        var first_field_select = Object.values(this.ks_dashboard_data.ks_dashboard_custom_domain_filter)[0]
        var relation = first_field_select.relation
        var field_type = first_field_select.type;
        var ks_operators = getDomainDisplayedOperators(first_field_select);
        var  operatorsinfo = ks_operators.map((x)=> getOperatorLabel(x));
        this.operators = ks_operators.map((val,index)=>{
            return{
                'symbol': val,
                'description': operatorsinfo[index]
            }

         })

        var operator_type = this.operators[0];
        var $operator_input = $(renderToElement('ks_dn_custom_domain_input_operator', {
                                    operators: this.operators,
                                    self:self,
                                    trId: "div-" + table_row_id
                                }));
        $newRow.append($operator_input);
      
        var $value_input = this._ksRenderCustomFilterInputSection(relation, operator_type?.symbol , ks_field_type[field_type], first_field_select.special_data,
         show_remove_option,"div-" + table_row_id)
        if ($value_input) $newRow.append($value_input);

        $("#ks_dn_custom_filters_container").append($newRow);
    },

    async ks_render_filter_options(ev,relation,context,domain,name){
        var self = this;
        var filter_id = $(ev.currentTarget).parent().parent().parent().find('.custom_filter_current_value_section').attr('data-index')
        var ks_current_operator_value = $(ev.currentTarget).parent().parent().parent().find('.operator_current_value_section').attr('data-value')
        var ks_path = "/web/dataset/call_kw/"+relation+"/name_search"
        var result = await self._rpc(ks_path,{
                        model: relation,
                        method: "name_search",
                        args: [],
                        kwargs: {
                            name: name,
                            args: domain,
                            operator: "ilike",
                            limit: 10
                        }
                    });
        self.ks_custom_filter_option[filter_id] = result
        self.ks_autocomplete_data_result = result.map((item)=> item[1]);
//            $(ev.target).autocomplete({
//                source: self.ks_autocomplete_data_result
//            });
        $(ev.target).autocomplete({
            source: function(request,response){
                var term = request.term;
                if (term.indexOf(', ') > 0) {
                    var index = term.lastIndexOf(', ');
                    term = term.substring(index + 2);
                }
                var re = $.ui.autocomplete.escapeRegex(term);
                var matcher = new RegExp('^' + re, 'i');
                var regex_validated_array = $.grep(self.ks_autocomplete_data_result, function (item, index) {
                    return matcher.test(item);
                });
                response($.ui.autocomplete.filter(regex_validated_array,
                    (request.term).split( /,\s*/ ).pop()));
                $.ui.autocomplete("search", "")

            },
            response: function(event, ui) {
                if (!ui.content.length) {
                    var noResult = { value:"",label:"No results found" };
                    ui.content.push(noResult);
                }
            },
            autoFocus: true,
            minLength: 0,
            search:"",
            select: function( event, ui ) {
                event.stopPropagation();
                if (ks_current_operator_value == 'in'){
                    var terms =  this.value.split( /,\s*/ )
                    terms.pop();
                    terms.push( ui.item.value );
                    terms.push( "" );
                    this.value = terms.join( ", " );
                    return false;
                }
            }
        });
    },
    onksrenderfilteroptions(ev){
        var relation = ev.currentTarget.dataset.relation
        this.ks_render_filter_options(ev,relation,this.state.context,this.state.domain,'')

    },

    _ksRenderCustomFilterInputSection(relation, operator_type, field_type, special_data, show_remove_option,trId){
        let self = this;
        var $value_input;
        switch (field_type) {
            case 'boolean':
                 $value_input = $(renderToFragment('ks_dn_custom_domain_boolean', {
                                                            show_remove_option: show_remove_option,
                                                            self: self,
                                                            ksOnCustomFilterConditionRemove: self.ksOnCustomFilterConditionRemove,
                                                            relation:relation,
                                                            operator:operator_type,
                                                            }));
                break;
            case 'selection':
                if (!operator_type) return false;
                else $value_input = $(renderToFragment('ks_dn_custom_domain_input_selection', {
                                    selection_input: special_data['select_options'] || [],
                                    show_remove_option: show_remove_option,
                                    ksOnCustomFilterConditionRemove: self.ksOnCustomFilterConditionRemove,
                                    onCustomFilterSelectionFieldSelect: self.onCustomFilterSelectionFieldSelect,
                                    self: self,
                                    relation:relation,
                                    operator:operator_type,
                                    trId
                                }));
                break;
            case 'date':
            case 'datetime':
                if (!operator_type) return false;
                $value_input = this._ksRenderDateTimeFilterInput(operator_type, field_type, show_remove_option);
                break;
            case 'char':
            case 'id':
            case 'number' :
                if (!operator_type) return false;
                else $value_input = $(renderToFragment('ks_dn_custom_domain_input_text', {
                                                            show_remove_option: show_remove_option,
                                                            self: self,
                                                            ksOnCustomFilterConditionRemove: self.ksOnCustomFilterConditionRemove,
                                                            relation:relation,
                                                            operator:operator_type,
                                                            trId
                                                            }));
                break;
            default:
                return;
        }
        return $value_input;
    },
    onCustomFilterSelectionFieldSelect(ev){
        let targetRowId = '#' + ev.target.dataset?.trId;
        let changedValue = ev.currentTarget.textContent;
        let valueAttribute = ev.currentTarget.getAttribute('value');
        $('#ks_dn_custom_filters_container ' + targetRowId + ' .o_generator_menu_value_td .o_generator_menu_value').text(changedValue);
        $('#ks_dn_custom_filters_container ' + targetRowId + ' .o_generator_menu_value_td .o_generator_menu_value').data('value', valueAttribute);
    },

    _ksRenderDateTimeFilterInput(operator, field_type, show_remove_option){
        var self = this;
        var $value_container = $(renderToFragment('ks_dn_custom_domain_input_date',{
            operator:operator,
            field_type:field_type,
            show_remove_option: show_remove_option,
            ksOnCustomFilterConditionRemove: self.ksOnCustomFilterConditionRemove
        }));

        if (field_type == 'date'){
            $value_container.find("#datetimepicker1").each((index,item)=>{
                item.value = formatDate(DateTime.now(),{format: "yyyy-MM-dd" })
            })

        }else{
            $value_container.find("#datetimepicker1").each((index,item)=>{
                item.value = new Date(DateTime.now() + new Date().getTimezoneOffset() * -60 * 1000).toISOString().slice(0, 19)
            })
        }
        return $value_container;
    },

    ksOnCustomFilterApply(ev){
        var self = this;
        var model_domain = {};
        if(this.isFavFilter){
            self.ks_dashboard_data.ks_dashboard_domain_data = {}
        }
        this.isFavFilter = false;
        $('.ks_dn_custom_filter_input_container_section').each((index, filter_container) => {
            var field_id = $(filter_container).find('.custom_filter_current_value_section').attr('data-index');
            var field_select = this.ks_dashboard_data.ks_dashboard_custom_domain_filter[field_id];
            var field_type = field_select.type;
            var domainValue = [];
            var domainArray = [];

            var ks_operators = getDomainDisplayedOperators(field_select);
            var  operatorsinfo = ks_operators.map((x)=> getOperatorLabel(x));
            this.operators = ks_operators.map((val,index)=>{
                return{
                    'symbol': val,
                    'description': operatorsinfo[index]
                }
            })


            var operator = getDomainDisplayedOperators(field_select)[$(filter_container).find('.operator_current_value_section').attr('data-index')];
            var ks_label = this.operators.filter((x) => x.symbol === operator)

            var label = field_select.name + ' ' + ks_label[0].description;
            if (['date', 'datetime'].includes(field_type)) {
                var dateValue = [];
                $(filter_container).find(".o_generator_menu_value_td .o_datepicker").each((index, $input_val) => {
                    var a = $($input_val).val();;
                    if (field_type === 'datetime'){
                        var b = formatDateTime(DateTime.fromISO(a),{ format: "yyyy-MM-dd HH:mm:ss" });
                        var c = formatDateTime(DateTime.fromISO(a),{ format: "dd/MM/yyyy HH:mm:ss" })  ;
                    }else{
                        var b = formatDate(DateTime.fromFormat(a,'yyyy-MM-dd'),{ format: "yyyy-MM-dd" });
                        var c = formatDate(DateTime.fromFormat(a,'yyyy-MM-dd'),{ format: "dd/MM/yyyy" });
                    }

                    domainValue.push(b);
                    dateValue.push(c);
                });
                label = label +' ' + dateValue.join(" and " );
            } else if (field_type === 'selection') {
                domainValue = [$(filter_container).find(".o_generator_menu_value_td .o_generator_menu_value").text()]
                label = label + ' ' + $(filter_container).find(".o_generator_menu_value_td .o_generator_menu_value").text();
            }
            else {
                if (operator === 'in'){
                    var ks_input_value = $(filter_container).find(".o_generator_menu_value_td textarea").val().split(',')
                    ks_input_value.pop();
                    ks_input_value = ks_input_value.map((x)=> x.trim());
                    var ks_filter_options = this.ks_custom_filter_option[field_id]
                    const ks_domain_array = (ks_filter_options)?.filter((item)=> ks_input_value.includes(item[1])).map((value)=>value[0])
                    if(ks_domain_array) domainValue = [...ks_domain_array]
                    else domainValue = []
                     label = label +' ' + $(filter_container).find(".o_generator_menu_value_td textarea").val();
                }else{
                    domainValue = [$(filter_container).find(".o_generator_menu_value_td input").val()];
                    label = label +' ' + $(filter_container).find(".o_generator_menu_value_td input").val();
                }
            }

            if (operator === 'between') {
                domainArray.push(
                    [field_select.field_name, '>=', domainValue[0]],
                    [field_select.field_name, '<=', domainValue[1]]
                );
                domainArray.unshift('&');
            } else {
                if(operator === 'in'){
                    domainArray.push([field_select.field_name, operator, domainValue]);

                }else{
                    domainArray.push([field_select.field_name, operator, domainValue[0]]);
                }
            }

            if(field_select.model in model_domain){
                model_domain[field_select.model]['domain'] = model_domain[field_select.model]['domain'].concat(domainArray);
                model_domain[field_select.model]['domain'].unshift('|');
                model_domain[field_select.model]['label'] = model_domain[field_select.model]['label'] + ' or ' +  label;
            } else {
                model_domain[field_select.model] = {
                    'domain': domainArray,
                    'label': label,
                    'model_name': field_select.model_name,
                }
            }
        });
        this.ksAddCustomDomain(model_domain);
    },

    eraseCookie(name) {
        document.cookie = name + '=; Max-Age=-99999999; path=/';
    },

    setCookie(name, value, days) {
        var expires = "";
        if (days) {
            var date = new Date();
            date.setTime(date.getTime() + (days*24*60*60*1000));
            expires = "; expires=" + date.toUTCString();
        }
        document.cookie = name + "=" + (value || "") + expires + "; path=/";
    },

     setObjectInCookie(name, object, days) {
        var jsonString = JSON.stringify(object);
        this.setCookie(name, jsonString, days);
    },

    getCookie(name) {
        var nameEQ = name + "=";
        var ca = document.cookie.split(';');
        for (var i = 0; i < ca.length; i++) {
            var c = ca[i];
            while (c.charAt(0) == ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
        }
        return null;
    },

    getObjectFromCookie(name) {
        var jsonString = this.getCookie(name);
        return jsonString ? JSON.parse(jsonString) : null;
    },

    ksAddCustomDomain(model_domain){
        var self = this;
        $(".ks_dn_filter_applied_container").removeClass('ks_hide');
        Object.entries(model_domain).map(([model,val])=>{
            var domain_data = self.ks_dashboard_data.ks_dashboard_domain_data[model];
            var domain_index = {
                categ: false,
                domain: val['domain'],
                label: [val['label']],
                model: model,
                isCustomFilter: true,
            }

            if (domain_data) {
                domain_data.ks_domain_index_data.push(domain_index);
            } else {
                domain_data = {
                    'domain': [],
                    'model_name': val.model_name,
                    'item_ids': self.ks_dashboard_data.ks_model_item_relation[model],
                    'ks_domain_index_data': [domain_index],
                }
                self.ks_dashboard_data.ks_dashboard_domain_data[model] = domain_data;
            }

            $("#ks_dn_custom_filters_container").empty();
            var show_remove_option = false;
            self.ks_render_custom_filter(show_remove_option);

            domain_data['domain'] = self._ksMakeDomainFromDomainIndex(domain_data.ks_domain_index_data);
            self.state.custom_filter = {...domain_data}

            if(domain_data['domain'][0] !== undefined && domain_data['domain'].length != 0){
                var storedData = this.getObjectFromCookie('FilterOrderData' + self.ks_dashboard_id);
                if(storedData !== null ){
                    this.eraseCookie('FilterOrderData' + self.ks_dashboard_id);
                }
                this.setObjectInCookie('FilterOrderData' + self.ks_dashboard_id, self.ks_dashboard_data.ks_dashboard_domain_data, 1);
            }

            self.state.pre_defined_filter = {}
            self.state.ksDateFilterSelection = 'none'
        })
    },

    ksOnCustomFilterFieldSelect(ev){
        var self =this;
        let targetRowId = '#' + ev.target.dataset?.trId
        let displayed_filter_container = $(targetRowId + ' .custom_filter_current_value_section');
        if(displayed_filter_container)  {
            displayed_filter_container.text(ev.currentTarget.text);
            displayed_filter_container.attr('data-index', ev.currentTarget.dataset?.value);
        }
        var $parent_container = $('#ks_custom_filter_table');
        $parent_container.find(targetRowId + ' .ks_operator_option_selector_td').remove();
        $parent_container.find(targetRowId + ' .o_generator_menu_value_td').remove();
        $parent_container.find(targetRowId + ' .customFilterDeleteBtn').remove();
        var field_id = ev.currentTarget.dataset.value;
        var field_select = self.ks_dashboard_data.ks_dashboard_custom_domain_filter[field_id];
        var relation = field_select.relation
        var field_type = field_select.type;
        var ks_operators = getDomainDisplayedOperators(field_select);
        var  operatorsinfo = ks_operators.map((x)=> getOperatorLabel(x));
        this.operators = ks_operators.map((val,index)=>{
            return{
                'symbol': val,
                'description': operatorsinfo[index]
            }

         })
        var operator_type = self.operators[0];
        var $operator_td = $(renderToElement('ks_dn_custom_domain_input_operator', {
                                   operators: self.operators,
                                   self:self,
                                   trId: ev.target.dataset?.trId
                               }));

        $(targetRowId).append($operator_td);
        let isShowDeleteBtn = $('#ks_dn_custom_filters_container').children().length <= 1 || ev.target.dataset?.trId === 'div-1' ? false : true;
        var $value_input = self._ksRenderCustomFilterInputSection(relation, operator_type?.symbol ,  ks_field_type[field_type], field_select.special_data, isShowDeleteBtn, ev.target.dataset?.trId)
        if ($value_input) $(targetRowId).append($value_input);
    },

    ksOnCustomFilterOperatorSelect(ev){
        var $parent_container = $('#ks_custom_filter_table');
        let targetRowId = '#' + ev.target.dataset?.trId
        let displayed_operator_container = $(targetRowId + ' .operator_current_value_section');
        if(displayed_operator_container){
            displayed_operator_container.text(ev.currentTarget.text);
            displayed_operator_container.attr('data-index', ev.currentTarget.dataset?.index);
            displayed_operator_container.attr('data-value', ev.currentTarget.dataset?.value);
        }
        var operator_symbol = ev.currentTarget.dataset?.value;
        var field_id = $parent_container.find(targetRowId + ' .custom_filter_current_value_section').attr('data-index');
        var field_select = this.ks_dashboard_data.ks_dashboard_custom_domain_filter[field_id];
        var relation = field_select.model
        var field_type = field_select.type;
        var relation = field_select.model;
        var ks_operators = getDomainDisplayedOperators(field_select);
        var operator_type = ks_operators[ev.currentTarget.dataset?.index];
      
        $parent_container.find(targetRowId + ' .o_generator_menu_value_td').remove();
        $parent_container.find(targetRowId + ' .customFilterDeleteBtn').remove();
        let isShowDeleteBtn = $('#ks_dn_custom_filters_container').children().length <= 1 || ev.target.dataset?.trId === 'div-1' ? false : true;
        var $value_td = this._ksRenderCustomFilterInputSection(relation, operator_type, ks_field_type[field_type], field_select.special_data, isShowDeleteBtn, ev.target.dataset?.trId)
        if ($value_td) $(targetRowId).append($value_td);
    },

    ksOnCustomFilterConditionAdd(){
        var show_remove_option = true;
        this.ks_render_custom_filter(show_remove_option);
    },
    ksOnCustomFilterConditionRemove(ev){
        ev.stopPropagation();
        $(ev.currentTarget.parentElement).remove();
    },

    searchPredefinedFilter(ev){
        let searchName = ev.currentTarget.value;
        let searchedPredefinedFilters;
        if(ev.currentTarget.value !== ''){
            searchedPredefinedFilters = Object.values(this.state.ks_dn_pre_defined_filters).filter(
                (filter) => filter.name.toLowerCase().includes(searchName.toLowerCase()) || filter.type === 'separator'
            );
            while(searchedPredefinedFilters.length && searchedPredefinedFilters[searchedPredefinedFilters.length - 1].type === 'separator')
                searchedPredefinedFilters.pop();
            while(searchedPredefinedFilters.length && searchedPredefinedFilters[0].type === 'separator')   searchedPredefinedFilters.shift();
        }
        else{
            searchedPredefinedFilters = this.state.ks_dn_pre_defined_filters ;
        }

        let $filterSection = $(ev.currentTarget.closest('.ks_dn_pre_filter_menu'))?.find('.predefined_filters_section');
        this.attachSearchFilter($filterSection, searchedPredefinedFilters);
    },

    predefinedSearchFocusout(ev){
        let $input = $(ev.currentTarget)?.find('.dropdown-menu.show .predefinedFilterSearchInput');
        if($input)  $input.val('');
        let $filterSection = $(ev.currentTarget)?.find('.dropdown-menu.show .predefined_filters_section');
        this.attachSearchFilter($filterSection, Object.values(this.state.ks_dn_pre_defined_filters));
    },

    attachSearchFilter($filterSection, searchedPredefinedFilters){
        if($filterSection.length){
            let $searchedFilters = $(renderToElement("search_filter_dropdown", {
                searchedPredefinedFilters: searchedPredefinedFilters,
                onKsDnDynamicFilterSelect: this.onKsDnDynamicFilterSelect.bind(this)
            }));
            $filterSection.replaceWith($searchedFilters);
        }

    },

    favFilterLayoutToggle(ev){

        this.env.services.dialog.add(FavFilterWizard,{
                ks_save_favourite: this.ks_save_favourite.bind(this)
            });
    },

    ks_save_favourite(ev, dialogCloseCallback){
        ev.preventDefault();
        ev.stopPropagation();
        var self = this;
        var ks_filter_name = $('#favourite_filter_name').val();
        var ks_is_fav_filter_shared = $('#favFilterShareBool').prop('checked')
        if (!ks_filter_name.length){
            this.notification.add(_t("A name for your favorite filter is required."), {
                    type: "warning",
                });

        }else{
            var ks_saved_fav_filters = Object.keys(self.ks_dashboard_data.ks_dashboard_favourite_filter)
            const favourite = ks_saved_fav_filters.find(item => item == ks_filter_name)
            if (favourite?.length){
                this.notification.add(_t("A filter with same name already exists."), {
                    type: "warning",
                });
            }
            else{
                var ks_filter_to_save = JSON.stringify(self.ks_dashboard_data.ks_dashboard_domain_data)
                self._rpc("/web/dataset/call_kw/ks_dashboard_ninja.favourite_filters/create", {
                    model: 'ks_dashboard_ninja.favourite_filters',
                    method: 'create',
                    args: [{
                        name:ks_filter_name,
                        ks_dashboard_board_id: self.ks_dashboard_id,
                        ks_filter: ks_filter_to_save,
                        ks_access_id: ks_is_fav_filter_shared ? false :session.user_context.uid
                    }],
                    kwargs: {}
                }).then(function(result){
                    var ks_filter_obj = {
                                id:result,
                                filter: JSON.parse(JSON.stringify(self.ks_dashboard_data.ks_dashboard_domain_data)),
                                name:ks_filter_name,
                                ks_access_id: ks_is_fav_filter_shared ? false :session.user_context.uid
                    };
                    self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_filter_name] = ks_filter_obj
//                    self.state.stateToggle = !self.state.stateToggle
                    var $filter_container = $(renderToElement('dn_favourite_filter_dropdown', {
                        ks_favourite_filters: self.ks_dashboard_data.ks_dashboard_favourite_filter,
                        onksfavfilterselected: self.onksfavfilterselected.bind(self),
                        ks_delete_favourite_filter: self.ks_delete_favourite_filter.bind(self),
                        ks_dashboard_data: self.ks_dashboard_data,
                        self:self
                    }));

                    $('#favFilterMain').replaceWith($filter_container);
                    $('#favFilterMain').removeClass('ks_hide');
                    dialogCloseCallback();
                });
            }
        }
    },



    ks_delete_favourite_filter(ev){
        ev.stopPropagation();
        ev.preventDefault();
        var self = this;
        var ks_filter_id_to_del = $(ev.currentTarget).attr('fav-id');
        var ks_filter_name_to_del = $(ev.currentTarget).attr('fav-name');
        var ks_filter_domain = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_filter_name_to_del].filter;
        var ks_access_id = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_filter_name_to_del].ks_access_id;
        var ks_remove_filter_models = Object.keys(ks_filter_domain)
        const ks_items_to_update_remove = self.ks_dashboard_data.ks_dashboard_items_ids.filter((item) =>
               ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][0])|| ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][1])
        );
        if (ks_access_id){
            self.dialogService.add(ConfirmationDialog, {
            body: _t("Are you sure you want to remove this filter?"),
            confirmLabel: _t("Delete Filter"),
            title: _t("Delete Filter"),
            confirm: () => {
                self.ks_delete_fav_filter(ks_filter_name_to_del,ks_filter_id_to_del,ks_items_to_update_remove)
            }
            })
        }else{
            self.dialogService.add(ConfirmationDialog, {
            body: _t("This filter is global and will be removed for everybody if you continue."),
            confirmLabel: _t("Delete Filter"),
            title: _t("Delete Filter"),
            confirm: () => {
                    self.ks_delete_fav_filter(ks_filter_name_to_del,ks_filter_id_to_del,ks_items_to_update_remove)
                }
            })
        }
    },



    ks_delete_fav_filter(ks_filter_name_to_del,ks_filter_id_to_del,ks_items_to_update_remove){
         var self = this;
         this.isFavFilter = false;
         self._rpc("/web/dataset/call_kw/ks_dashboard_ninja.favourite_filters/unlink", {
            model: 'ks_dashboard_ninja.favourite_filters',
            method: 'unlink',
            args: [Number(ks_filter_id_to_del)],
            kwargs: {}
        }).then(function(result) {
            delete self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_filter_name_to_del]
            var $filter_container = $(renderToElement('dn_favourite_filter_dropdown', {
                                        ks_favourite_filters: self.ks_dashboard_data.ks_dashboard_favourite_filter,
                                        onksfavfilterselected: self.onksfavfilterselected.bind(self),
                                         ks_delete_favourite_filter: self.ks_delete_favourite_filter.bind(self),
                                         ks_dashboard_data: self.ks_dashboard_data,
                                        self:self
                                    }));
            $('#favFilterMain').replaceWith($filter_container);
            $('#favFilterMain').removeClass('ks_hide');
            if(!$('.favFilterListItems').length)    $('#favFilterMain').addClass('ks_hide');

            Object.keys(self.ks_dashboard_data.ks_dashboard_domain_data).forEach((model) => {
                self.state.pre_defined_filter = self.ks_dashboard_data.ks_dashboard_domain_data[model];
            })


            self.state['domain_data']=self.ks_dashboard_data.ks_dashboard_domain_data;
        });
    },

    ksFavFilterFacetRemove(ev){
        ev.preventDefault();
        ev.stopPropagation();
        this.isFavFilter = false;
        this.header.el?.querySelector('.custom-filter-tab')?.classList.remove('disabled-div')
        let FilterModels = Object.keys(this.ks_dashboard_data.ks_dashboard_domain_data);
        if (FilterModels.length){
            let domain_data = {
                item_ids: [],
            };
            FilterModels.forEach((model)=>{
                let item_ids = this.ks_dashboard_data.ks_dashboard_favourite_filter[this.activeFavFilterName].filter[model]?.item_ids
                if(item_ids)
                    domain_data.item_ids = [ ...domain_data['item_ids'],...item_ids];
            })
            this.state.pre_defined_filter = {...domain_data};
        }
        this.state.stateToggle = !this.state.stateToggle
        ev.currentTarget.parentElement.parentElement?.remove();
        this.ks_dashboard_data.ks_dashboard_domain_data = {}
        $(this.header.el)?.find('.ks_fav_filters_checked').removeClass('ks_fav_filters_checked global-active');
    },

    onksfavfilterselected(ev){
        var self = this;
        ev.stopPropagation();
        ev.preventDefault();
        this.env.bus.trigger("Clear:Custom-Filter-Facets",{})
        this.env.bus.trigger("Clear:Custom-Filter",{})
        // remove pre define filters first
        var ks_filters_to_remove = $('.ks_dn_filter_applied_container .ks_dn_filter_section_container .o_searchview_facet');
        this.ks_pre_define_filters_model = [];
        ks_filters_to_remove.each(function(item,filter){
           var ks_filter_model = $(filter).attr('ksmodel');
           var categ = $(filter).attr('kscateg');
           // to update the domain only once for the item having both custom and pre-define filters.
           if (!self.ks_pre_define_filters_model.includes(ks_filter_model)){
               var filters = JSON.parse(JSON.stringify(self.ks_dashboard_data.ks_dashboard_favourite_filter))
               self.ks_dashboard_data.ks_dashboard_domain_data[ks_filter_model].domain = [];
               self.ks_dashboard_data.ks_dashboard_favourite_filter = filters
               // to restrict one fetch update for the item with same model in pre-define and fav filters when more than one filters are selected in pre-define
               var ks_filters = Object.keys(self.ks_dashboard_data.ks_dashboard_favourite_filter[$(ev.currentTarget).attr('fav-name')].filter)
               self.ks_pre_define_filters_model.push(ks_filter_model);
               if (!ks_filters.includes(ks_filter_model)){
                    self._ksUpdateRemoveDomain(self.ks_dashboard_data.ks_dashboard_domain_data[ks_filter_model]);
               }
           }
        });
//        $('.ks_dn_filter_applied_container .ks_dn_filter_section_container .o_searchview_facet').remove();
        $('.dn_dynamic_filter_selected').each(function(item,filter){
           var filter_id = $(filter).attr('data-filter-id');
            self.ks_dashboard_data.ks_dashboard_pre_domain_filter[filter_id].active = false;
            $(filter).removeClass('dn_dynamic_filter_selected global-active')

        });
        $('.ks_dn_filter_applied_container .ks_dn_filter_section_container').remove()
//        $(".ks_dn_filter_applied_container").addClass('ks_hide');

        // unchecked the checked filters first
        var ks_filter_to_uncheck = $(ev.currentTarget).parent().parent().find('.ks_fav_filters_checked');
        if (ks_filter_to_uncheck.length){
            self.isFavFilter = false;
            self.header.el?.querySelector('.custom-filter-tab')?.classList.remove('disabled-div')
            var ks_remove_filter_name = ks_filter_to_uncheck.attr('fav-name');
            var ks_remove_filter_domain = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_remove_filter_name].filter;
            var ks_remove_filter_models = Object.keys(ks_remove_filter_domain)
            const ks_items_to_update_remove = self.ks_dashboard_data.ks_dashboard_items_ids.filter((item) =>
               ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][0])|| ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][1])
            );
             if (ks_items_to_update_remove.length && ks_filter_to_uncheck.attr('fav-name') === $(ev.currentTarget)?.attr('fav-name')){
                let domain_data = {
                    item_ids: [],
                };
                self.ks_dashboard_data.ks_dashboard_domain_data = {}
                ks_remove_filter_models.forEach((model)=>{
                    let item_ids = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_remove_filter_name].filter[model].item_ids
                    if(item_ids)
                        domain_data.item_ids = [ ...domain_data['item_ids'],...item_ids];
                })
                self.state.pre_defined_filter = {...domain_data};
            }
                this.state.stateToggle = !this.state.stateToggle

             $(ev.currentTarget).parent().parent().find('.ks_fav_filters_checked').removeClass('ks_fav_filters_checked global-active');
        }
        // Apply the fav filter
        if (ks_filter_to_uncheck.attr('fav-name') != $(ev.currentTarget)?.attr('fav-name')){
            self.isFavFilter = true;
            self.header.el?.querySelector('.custom-filter-tab')?.classList.add('disabled-div')
            var ks_applied_filter_name = $(ev.currentTarget).attr('fav-name');
            self.activeFavFilterName = ks_applied_filter_name;
            $(ev.currentTarget).addClass('ks_fav_filters_checked');
            var ks_applied_filter_domain = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_applied_filter_name].filter;
            var ks_applied_filter_models = Object.keys(ks_applied_filter_domain)
            const ks_items_to_update = self.ks_dashboard_data.ks_dashboard_items_ids.filter((item) =>
               ks_applied_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][0])|| ks_applied_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][1])
            );
            $(ev.currentTarget).addClass('ks_fav_filters_checked global-active');
            if (ks_items_to_update.length){
                let domain_data = {
                    item_ids: [],
                };
                self.ks_dashboard_data.ks_dashboard_domain_data = {...ks_applied_filter_domain}
                self.state['domain_data'] = self.ks_dashboard_data.ks_dashboard_domain_data;
                ks_applied_filter_models.forEach((model)=>{
                    let item_ids = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_applied_filter_name].filter[model].item_ids
                    if(item_ids)
                        domain_data.item_ids = [ ...domain_data['item_ids'],...item_ids];
                })
                self.state.pre_defined_filter = {...domain_data};

            }
            this.state.stateToggle = !this.state.stateToggle
        }
    },

    ks_remove_favourite_filter(filter){
        var self = this;
        var ks_remove_filter_name = filter;
        var ks_remove_filter_domain = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_remove_filter_name].filter;
        var ks_remove_filter_models = Object.keys(ks_remove_filter_domain)
        const ks_items_to_update_remove = self.ks_dashboard_data.ks_dashboard_items_ids.filter((item) =>
           ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][0])|| ks_remove_filter_models.includes(self.ks_dashboard_data.ks_item_model_relation[item][1])
        );
         if (ks_items_to_update_remove.length){
            let domain_data = {
                    item_ids: [],
                };
            self.ks_dashboard_data.ks_dashboard_domain_data = {}
            ks_remove_filter_models.forEach((model)=>{
                let item_ids = self.ks_dashboard_data.ks_dashboard_favourite_filter[ks_remove_filter_name].filter[model].item_ids;
                if(item_ids)
                    domain_data.item_ids = [ ...domain_data['item_ids'],...item_ids];
            })
            self.state.pre_defined_filter = {...domain_data}
        }
    },
  
    _ksUpdateRemoveDomain(domain_data){
        var self =this;
        self.state.pre_defined_filter = {...domain_data}
    },

    clear_filters(ev){
        $('#ks_dn_custom_filters_container').empty();
        this.ks_render_custom_filter(false);
    },

    onksrenderautocomplete(ev){
        if ($(ev.currentTarget).autocomplete("widget").is(":visible")) {
            $(ev.currentTarget).autocomplete("close");
        } else {
            $(ev.currentTarget).autocomplete("search", '');
        }
    },

    filterTableDropdownShow(e) {
        let targetElement = e.target.closest('.filter_dropdown');

        if (targetElement) {
            let dropdownMenu = targetElement.querySelector('.dropdown-menu');
            var dropdownToggle = targetElement.querySelector('.dropdown-toggle');

            if (dropdownMenu && dropdownToggle) {
                document.body.appendChild(dropdownMenu);
                var targetRect = targetElement.getBoundingClientRect();

                dropdownMenu.style.display = 'block';
                dropdownMenu.style.position = 'absolute';
                dropdownMenu.style.top = (targetRect.top + window.scrollY + targetElement.offsetHeight) + 'px';
                dropdownMenu.style.left = (targetRect.left + window.scrollX) + 'px';

                dropdownMenu.style.width = dropdownToggle.offsetWidth + 'px';
            }
        }
    },

    filterTableDropdownHide(e) {
        var targetElement = e.target.closest('.filter_dropdown');
        let dropdownMenu = document.querySelector('.customFilterDropdown.show');

        if (targetElement && dropdownMenu) {
            targetElement.appendChild(dropdownMenu);
            dropdownMenu.style.display = 'none';
        }
    },

});