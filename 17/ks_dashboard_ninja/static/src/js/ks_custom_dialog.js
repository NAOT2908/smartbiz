/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Ksdashboardgraph } from './../components/ks_dashboard_graphs/ks_dashboard_graphs';
import { Ksdashboardtile } from './../components/ks_dashboard_tile_view/ks_dashboard_tile';
import { Ksdashboardtodo } from './../components/ks_dashboard_to_do_item/ks_dashboard_to_do';
import { Ksdashboardkpiview } from './../components/ks_dashboard_kpi_view/ks_dashboard_kpi';

export class CustomDialog extends Component {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.graphRef =  useRef("graph_div");
        this.ks_question = useRef("ks_question")
        this.user = this.env.services.user.name;
        this.name_title = this.user.split(' ').length>1 ? this.user.split(' ')[0].charAt(0)+this.user.split(' ')[1].charAt(0):this.user.split(' ')[0].charAt(0);
        this.dashboard_container =  useRef("ks_gridstack_container");
        this._rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = useState({
            explain_ai: true,
            newItem: false,
            chart_ks_dashboard_id: this.props.item.ks_dashboard_id,
            toggleState: true,
            confirm_notification: false,
            messages:[{sender:'ai',text:'Hello I am AI Assistant, How may i help you ?'}],
            confirm_notification: false,
            switch_layout: false,
        });
    }


    switch_bar_chart(new_item) {
        this.ks_item = Object.assign({},this.props.item)
        this.ks_item['ks_dashboard_item_type'] = new_item
        $(this.graphRef.el).find('.ks_chart_card_body').remove();
        if(new_item == 'ks_funnel_chart'){
            Ksdashboardgraph.prototype.ksrenderfunnelchart($(this.graphRef.el), this.ks_item);
        }
        else{
            Ksdashboardgraph.prototype.ks_render_graphs($(this.graphRef.el), this.ks_item, this.props.dashboard_data?.zooming_enabled);
        }
        this.state.newItem = new_item;
        this.state.switch_layout = true;
    }

    ks_switch_layout() {
        var self =this
            let selectedItem = this.state.newItem;
            let item_id = this.props.item.id
            let chart_id = this.state.chart_ks_dashboard_id;
            this._rpc("/web/dataset/call_kw/ks_dashboard_ninja.item/write",{
                model: 'ks_dashboard_ninja.item',
                method: 'write',
                args: [item_id, {
                    'ks_dashboard_item_type': selectedItem
                }],
                kwargs:{}
            }).then(function(result) {
                self.props.current_graph.item.ks_dashboard_item_type = selectedItem;
                self.props.current_graph.ksFetchUpdateItem(item_id, chart_id, {}, {})
            })
            .then(() => {
                self.state.confirm_notification = true;
            });
    }
    ks_key_check(ev){
        if (ev.keyCode == 13){
            this.ks_send_request(ev);
        }
    }
    ks_send_request(ev){
        let self = this;
        ev.stopPropagation();
        let user_question= $(this.ks_question.el).val()
        let user_obj = {sender:"user",text:user_question}
        this.state.messages = [...this.state.messages,user_obj,{sender:'ai',text:'loading'}]
        $(this.ks_question.el).val('')
        this.env.services.rpc('/web/dataset/call_kw/ks_dashboard_ninja.arti_int/ks_gen_chat_res',{
            model:'ks_dashboard_ninja.arti_int',
            method:'ks_gen_chat_res',
            args:[],
            kwargs:{ks_question:user_question}
        }).then((result)=>{
            if (result['Answer']){
                let answer = result['Answer'].split('\n').join('')
                self.state.messages.pop()
                self.state.messages.push({sender:'ai',text:answer})
            }else{
                self.state.messages.pop()
                self.state.messages.push({sender:'ai',text:'AI unable to Generate Response'})
            }
        })
    }

    closeNotification(){
        this.state.confirm_notification = false;
    }

}
CustomDialog.props = {
    title: { type: String, optional:true},
    ks_dashboard_manager: { type: Boolean, optional: true },
    ks_dashboard_items: Object,
    ks_dashboard_data: Object,
    ks_dashboard_item_type: { type: String, optional: true },
    ksdatefilter: { type: String, optional: true },
    pre_defined_filter: { type:Object, optional:true},
    custom_filter: { type:Object, optional:true},
    dashboard_data: Object,
    item: { type: Object, optional: true },
    ks_speak: { type: Function, optional: true },
    ksDateFilterSelection: { type: String, optional: true },
    close: { type: Function, optional: true },
    hideButtons: { type: Number, optional: true },
    update_graph: { type: Function, optional: true },
    current_graph: { type: Object, optional: true },


}


CustomDialog.components = { Dialog, Ksdashboardgraph, Ksdashboardtile, Ksdashboardkpiview, Ksdashboardtodo };

CustomDialog.template = "ks_dashboard_ninja.CustomDialog";




