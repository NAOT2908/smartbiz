/** @odoo-module **/
import { Ksdashboardgraph } from '@ks_dashboard_ninja/components/ks_dashboard_graphs/ks_dashboard_graphs';
import {CustomDialog} from '@ks_dashboard_ninja/js/ks_custom_dialog';
import { patch } from "@web/core/utils/patch";

patch(Ksdashboardgraph.prototype,{

    _onButtonClick(e) {
        e.stopPropagation();
        let openDialog = () => {
            this.env.services.dialog.add(CustomDialog,{
                    ks_dashboard_manager: this.props.ks_dashboard_manager,
                    ks_dashboard_items: this.props.dashboard_data.ks_dashboard_items_ids,
                    ks_dashboard_data: this.ks_dashboard_data,
                    item: this.ks_dashboard_data.ks_item_data[this.props.item.id],
                    ks_dashboard_item_type: this.item.ks_dashboard_item_type,
                    dashboard_data: this.props.dashboard_data,
                    ksdatefilter: this.props.ksdatefilter,
                    ks_speak: this.props.ks_speak,
                    ksDateFilterSelection: this.props.ksdatefilter,
                    pre_defined_filter: this.props.pre_defined_filter,
                    custom_filter: this.props.custom_filter,
                    title:"Hello",
                    hideButtons: 0,
                    current_graph: this,
            });
        }
        let item = this.props.item
        let self = this
        if(!item.ks_ai_analysis) {
           self._rpc("/web/dataset/call_kw/ks_dashboard_ninja.arti_int/ks_generate_analysis",{
                 model: 'ks_dashboard_ninja.arti_int',
                 method: 'ks_generate_analysis',
                 args: [[item],[],item.ks_dashboard_id],
                 kwargs:{context: {explain_items_with_ai: true}},
           }).then(function(result) {
                    if (result){
                        self._rpc("/web/dataset/call_kw/ks_dashboard_ninja.arti_int/get_ai_explain",{
                            model: 'ks_dashboard_ninja.arti_int',
                            method: 'get_ai_explain',
                            args: [item.id, item.id],
                            kwargs:{ },
                        }).then(function(res) {
                            self.props.item.ks_ai_analysis = res
                            openDialog();
                        });

                    }
           });
        }
        else {
            openDialog();
        }
    }

});
