/**@odoo-module **/
import {Component,useState,useRef,onPatched} from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class KschatwithAI extends Component{
    setup(){
        this.user = this.env.services.user.name;
        this.name_title = this.user.split(' ').length>1 ? this.user.split(' ')[0].charAt(0)+this.user.split(' ')[1].charAt(0):this.user.split(' ')[0].charAt(0);
        this.state = useState({ messages:[{sender:'ai',text:'Hello I am AI Assistant, How may i help you ?',frame:false}]})
        this.ks_question = useRef("ks_question")
        onPatched(()=>{
            $(".chat-sec")[0].scrollTop = $(".chat-sec")[0].scrollHeight
        });
        this.send_request = true
    }
     ks_key_check(ev){
        if (ev.keyCode == 13){
            if (this.send_request == true){
                this.ks_send_request(ev)
            }
        }
    }
    ks_send_request(ev){
        let self = this;
        ev.stopPropagation();
        ev.preventDefault();
        let user_question= $(this.ks_question.el).val()
        if (user_question.length>1 && this.send_request){
            let user_obj = {sender:"user",text:user_question,frame:false}
            this.state.messages = [...this.state.messages,user_obj,{sender:'ai',text:'loading',frame:false}]
            $(this.ks_question.el).val('')
            this.send_request = false
            this.env.services.rpc('/web/dataset/call_kw/ks_dashboard_ninja.arti_int/ks_gen_chat_res',{
                model:'ks_dashboard_ninja.arti_int',
                method:'ks_gen_chat_res',
                args:[],
                kwargs:{ks_question:user_question}
            }).then((result)=>{
                if (result['Answer']){
                    let answer = result['Answer'].split('\n').join('')
                    if (answer.indexOf('Summary')!= -1){
                       answer = answer.slice(0,answer.indexOf('Summary'))
                    }
                    else{
                        answer = answer
                    }
                    self.state.messages.pop()
                    let frame  = JSON.parse(result['Dataframe']).length>5? JSON.parse(result['Dataframe']):false;
                    self.state.messages.push({sender:'ai',text:answer,frame})
                    this.send_request = true
                }else{
                    self.state.messages.pop()
                    self.state.messages.push({sender:'ai',text:'AI unable to Generate Response'})
                    this.send_request = true
                }
            })
        }else{
            $(this.ks_question.el).val('')
            let user_obj = {sender:"user",text:user_question,frame:false}
            let res_obj = {sender:'ai',text:'Either you have not asked any question or AI Unable to generate response',frame:false}
            this.state.messages = [...this.state.messages,user_obj,res_obj]

        }
    }

};
KschatwithAI.components = { Dialog };
KschatwithAI.template = "Kschatwithai"