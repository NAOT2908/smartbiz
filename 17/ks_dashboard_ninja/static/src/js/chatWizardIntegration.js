/** @odoo-module **/

import { chatWizard } from '@ks_dashboard_ninja/js/chatWizard';
import { Ksdashboardgraph } from '@ks_dashboard_ninja/components/ks_dashboard_graphs/ks_dashboard_graphs';
import { Ksdashboardtodo } from '@ks_dashboard_ninja/components/ks_dashboard_to_do_item/ks_dashboard_to_do';
import { Ksdashboardtile } from '@ks_dashboard_ninja/components/ks_dashboard_tile_view/ks_dashboard_tile';
import { patch } from "@web/core/utils/patch";
import { Ksdashboardkpiview } from '@ks_dashboard_ninja/components/ks_dashboard_kpi_view/ks_dashboard_kpi';

patch(Ksdashboardgraph.prototype,{

    async _openChatWizard(ev){
        ev.stopPropagation();
        let internal_chat_thread;
        let channelId = await this._rpc("/web/dataset/call_kw/discuss.channel/getId",{
            model: 'discuss.channel',
            method: 'ks_chat_wizard_channel_id',
            args: [[]],
            kwargs:{
                item_id: this.item.id,
                dashboard_id: this.ks_dashboard_id,
                dashboard_name: this.ks_dashboard_data.name,
                item_name: this.item.name,
            }
        })

        // FIXME : Dont close all chat popover windows . only close charts visible popovers


        this.mailChatService.visible?.forEach?.( (visibleChatWindow) => {
            this.mailChatService.close(visibleChatWindow)
        })

        //
        if(channelId)   internal_chat_thread = this.threadService.getThread("discuss.channel", channelId)
        if(internal_chat_thread){
            if(internal_chat_thread.name)   internal_chat_thread.name = this.ks_dashboard_data.name + ' - ' + this.item.name
            this.mailChatService?.open(internal_chat_thread)
        }

    }
});

patch(Ksdashboardkpiview.prototype,{

    async _openChatWizard(ev){
        ev.stopPropagation();
        let internal_chat_thread;
        let channelId = await this._rpc("/web/dataset/call_kw/discuss.channel/getId",{
            model: 'discuss.channel',
            method: 'ks_chat_wizard_channel_id',
            args: [[]],
            kwargs:{
                item_id: this.item.id,
                dashboard_id: this.ks_dashboard_id,
                dashboard_name: this.ks_dashboard_data.name,
                item_name: this.item.name,
            }
        })

        // FIXME : Dont close all chat popover windows . only close charts visible popovers


        this.mailChatService.visible?.forEach?.( (visibleChatWindow) => {
            this.mailChatService.close(visibleChatWindow)
        })

        //
        if(channelId)   internal_chat_thread = this.threadService.getThread("discuss.channel", channelId)
        if(internal_chat_thread)
            this.mailChatService?.open(internal_chat_thread)
    }
});


patch(Ksdashboardtodo.prototype,{

    async _openChatWizard(ev){
        ev.stopPropagation();
        let internal_chat_thread;
        let channelId = await this._rpc("/web/dataset/call_kw/discuss.channel/getId",{
            model: 'discuss.channel',
            method: 'ks_chat_wizard_channel_id',
            args: [[]],
            kwargs:{
                item_id: this.item.id,
                dashboard_id: this.ks_dashboard_id,
                dashboard_name: this.ks_dashboard_data.name,
                item_name: this.item.name,
            }
        })

        // FIXME : Dont close all chat popover windows . only close charts visible popovers

        this.mailChatService.visible?.forEach?.( (visibleChatWindow) => {
            this.mailChatService.close(visibleChatWindow)
        })

        //
        if(channelId)   internal_chat_thread = this.threadService.getThread("discuss.channel", channelId)
        if(internal_chat_thread)
            this.mailChatService?.open(internal_chat_thread)
    }
});

patch(Ksdashboardtile.prototype,{

    async _openChatWizard(ev){
        ev.stopPropagation();
        let internal_chat_thread;
        let channelId = await this._rpc("/web/dataset/call_kw/discuss.channel/getId",{
            model: 'discuss.channel',
            method: 'ks_chat_wizard_channel_id',
            args: [[]],
            kwargs:{
                item_id: this.item.id,
                dashboard_id: this.ks_dashboard_id,
                dashboard_name: this.ks_dashboard_data.name,
                item_name: this.item.name,
            }
        })

        // FIXME : Dont close all chat popover windows . only close charts visible popovers

        this.mailChatService.visible?.forEach?.( (visibleChatWindow) => {
            this.mailChatService.close(visibleChatWindow)
        })

        //
        if(channelId)   internal_chat_thread = this.threadService.getThread("discuss.channel", channelId)
        if(internal_chat_thread)
            this.mailChatService?.open(internal_chat_thread)
    }
});

