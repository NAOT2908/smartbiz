/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const { Component,useRef,useState,onWillStart } = owl;

export class KsKeywordSelection extends Component {
    static template = 'KsKeywordSelection';
    setup() {
        super.setup();
        this.props.record.data.ks_import_id;
        this.input = useRef('ks_input');
        this.search = useRef('ks_search');
        this.ks_sample_final_data = [];
        this.state = useState({ values: []});
        this._rpc = useService("rpc");
//        this.sharedState = useService("shared_state");
//        this.state.values = this.sharedState.getValue();
        onWillStart(async()=>{
            this.ks_data_model = await this._rpc('/web/dataset/call_kw/ks_dashboard_ninja.arti_int/ks_get_keywords',{
                model:'ks_dashboard_ninja.arti_int',
                method:'ks_get_keywords',
                args:[],
                kwargs: {},
            })
            this.state.values = this.ks_data_model;
        });
    }

    _onKeyup(ev) {
        var value = ev.target.value;
        var self=this;
        var ks_active_target =  $(self.search.el).find(".active")
//        this.sharedState.setValue({"value":value,'id':this.state.values.length})
//        this.state.values = this.sharedState.getValue();
        if (value.length){
            var ks_value = value.toUpperCase();
            self.state.values =[];
            if (this.ks_data_model){
                this.ks_data_model.forEach((item) =>{
                    if (item.value.toUpperCase().indexOf(ks_value) >-1 && item.value !== value){
                        self.state.values.push(item)
                    }
                })
                self.state.values.splice(0,0,{"value":value,'id':0})

                $(self.search.el).removeClass('d-none');
                $(self.search.el).addClass('d-block')
            }
        }else{
            this.state.values = this.ks_data_model
            $(self.search.el).removeClass('d-none');
            $(self.search.el).addClass('d-block')
            this.props.record.update({[this.props.name]: ""})
        }
    }

   _onResponseSelect(ev) {
        var self = this;
         var value = $(ev.currentTarget).find(".ai-title")[0].textContent;
         this.props.record.update({[this.props.name]: value });
//        self.props.update(value);
         this.input.el.value = value;
         $('#ks_keywords_container .createAI-card').each(function() {
            if ($(this).hasClass('active')) {
                $(this).removeClass('active');
            }
        });
         $(ev.currentTarget).addClass("active");
    }

}
export const KsKeywordSelectionfield = {
    component: KsKeywordSelection,
}

registry.category("fields").add('ks_keyword_selection', KsKeywordSelectionfield);

//const sharedStateService = {
//    start(env) {
//        let recent_search = [];
//        return {
//            getValue() {
//                return recent_search;
//            },
//            setValue(value) {
//                if(recent_search.length == 5) {
//                    recent_search.pop();
//                    recent_search.unshift(value);
//                }
//                else {
//                    recent_search.unshift(value);
//                }
//            },
//        };
//    },
//};
//
//registry.category("services").add("shared_state", sharedStateService);