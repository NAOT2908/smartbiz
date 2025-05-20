import json
import logging
import requests
from odoo import  http, api, fields, models, _
from odoo.exceptions import ValidationError
from gtts import gTTS
import base64
from odoo.tools import config
import pandas as pd
import io
from urllib.parse import quote

_logger = logging.getLogger(__name__)


class KsDashboardNInjaAI(models.TransientModel):
    _name = 'ks_dashboard_ninja.arti_int'
    _description = 'AI Dashboard'

    ks_type = fields.Selection([('ks_model', 'Model'), ('ks_keyword', 'Keywords')],
                               string="Ks AI Type", default='ks_model')

    ks_import_model_id = fields.Many2one('ir.model', string='Model ID',
                                  domain="[('access_ids','!=',False),('transient','=',False),"
                                         "('model','not ilike','base_import%'),'|',('model','not ilike','ir.%'),('model','=ilike','_%ir.%'),"
                                         "('model','not ilike','web_editor.%'),('model','not ilike','web_tour.%'),"
                                         "('model','!=','mail.thread'),('model','not ilike','ks_dash%'),('model','not ilike','ks_to%')]",
                                  help="Data source to fetch and read the data for the creation of dashboard items. ")

    ks_import_model = fields.Many2one('ir.model', string='Model',
                                         domain="[('access_ids','!=',False),('transient','=',False),"
                                                "('model','not ilike','base_import%'),('model','not ilike','ir.%'),"
                                                "('model','not ilike','web_editor.%'),('model','not ilike','web_tour.%'),"
                                                "('model','!=','mail.thread'),('model','not ilike','ks_dash%'),('model','not ilike','ks_to%')]",
                                         help="Data source to fetch and read the data for the creation of dashboard items. ")
    ks_input_keywords = fields.Char("Ks Keywords")
    ks_model_show = fields.Boolean(default = False, compute='_compute_show_model')

    @api.onchange('ks_input_keywords')
    def _compute_show_model(self):
        if self.ks_input_keywords and self.ks_type=="ks_keyword":
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.dn_api_key')
            url = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.url')
            if api_key and url:
                json_data = {'name': api_key,
                             'type': self.ks_type,
                             'keyword': self.ks_input_keywords
                             }
                url = url + "/api/v1/ks_dn_keyword_gen"
                ks_response = requests.post(url, data=json_data)
                if json.loads(ks_response.text) == False:
                    self.ks_model_show = True
                else:
                    self.ks_model_show = False
        else:
            self.ks_model_show = False

    @api.model
    def ks_get_keywords(self):
        url = self.env['ir.config_parameter'].sudo().get_param(
            'ks_dashboard_ninja.url')
        if url:
            url = url + "/api/v1/ks_dn_get_keyword"
            ks_response = requests.post(url)
            if ks_response.status_code == 200:
                return json.loads(ks_response.text)
            else:
                return []


    def ks_do_action(self):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json",
                   "Catch-Control": "no-cache",
                   }

        if self.ks_import_model_id:
            ks_model_name = self.ks_import_model_id.model
            ks_fields = self.env[ks_model_name].fields_get()
            ks_filtered_fields = {key: val for key, val in ks_fields.items() if val['type'] not in ['many2many', 'one2many', 'binary'] and'name' in val and val['name'] != 'id' and val['name'] != 'sequence' and val['store'] == True}
            ks_fields_name = {val['name']:val['type'] for val in ks_filtered_fields.values()}
            question = ("columns: "+ f"{ks_fields_name}")

            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.dn_api_key')
            url = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.url')
            if api_key and url:
                json_data = {'name': api_key,
                        'question':question,
                        'type': self.ks_type,
                        'url': self.env['ir.config_parameter'].sudo().get_param('web.base.url'),
                        'db_name': self.env.cr.dbname
                        }
                url = url+"/api/v1/ks_dn_main_api"
                ks_ai_response = requests.post(url, data=json_data)
                if ks_ai_response.status_code == 200:
                    ks_ai_response = json.loads(ks_ai_response.text)
                    # create dummy dash to create items on the dashboard, later deleted it.
                    ks_create_record = self.env['ks_dashboard_ninja.board'].create({
                        'name': 'AI dashboard',
                        'ks_dashboard_menu_name': 'AI menu',
                        'ks_dashboard_default_template': self.env.ref('ks_dashboard_ninja.ks_blank', False).id,
                        'ks_dashboard_top_menu_id': self.env['ir.ui.menu'].search([('name', '=', 'My Dashboards')])[0].id,
                    })
                    ks_dash_id = ks_create_record.id

                    ks_result = self.env['ks_dashboard_ninja.item'].create_ai_dash(ks_ai_response, ks_dash_id,
                                                                                   ks_model_name)
                    context = {'ks_dash_id': self._context['ks_dashboard_id'],
                               'ks_dash_name': self.env['ks_dashboard_ninja.board'].search([
                                   ('id','=',self._context['ks_dashboard_id'])]).name,'ks_delete_dash_id':ks_dash_id }

                    # return client action created through js for AI dashboard to render items on dummy dashboard
                    if (ks_result == "success"):
                        return {
                            'type': 'ir.actions.client',
                            'name': 'Generate items with AI',
                            'params': {'ks_dashboard_id': ks_create_record.id, 'explain_ai_whole': True},
                            'tag': 'ks_ai_dashboard_ninja',
                            'context': context,
                            'target':'new'
                        }
                    else:
                        self.env['ks_dashboard_ninja.board'].browse(ks_dash_id).unlink()
                        raise ValidationError(_("Items didn't render because AI provides invalid response for this model.Please try again"))
                else:
                    raise ValidationError(_("AI Responds with the following status:- %s") % ks_ai_response.text)
            else:
                raise ValidationError(_("Please enter URL and API Key in General Settings"))
        else:
            raise ValidationError(_("Please enter the Model"))



    def ks_generate_item(self):
            if self.ks_input_keywords:
                api_key = self.env['ir.config_parameter'].sudo().get_param(
                    'ks_dashboard_ninja.dn_api_key')
                url = self.env['ir.config_parameter'].sudo().get_param(
                    'ks_dashboard_ninja.url')
                if api_key and url:
                    json_data = {'name': api_key,
                                 'type': self.ks_type,
                                 'keyword':self.ks_input_keywords
                                 }
                    url = url + "/api/v1/ks_dn_keyword_gen"
                    ks_response = requests.post(url, data=json_data)
                else:
                    raise ValidationError(_("Please put API key and URL"))
                if  json.loads(ks_response.text) != False and ks_response.status_code==200 :
                    ks_ai_response = json.loads(ks_response.text)
                    ks_dash_id = self._context['ks_dashboard_id']
                    ks_model_name = ks_ai_response[0]['model']
                    ks_result = self.env['ks_dashboard_ninja.item'].create_ai_dash(ks_ai_response, ks_dash_id,
                                                                               ks_model_name)
                    if ks_result == "success":
                        return{
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                        }
                    else:
                        raise ValidationError(_("Items didn't render, please try again!"))
                else:
                    ks_model_name = self.ks_import_model.model
                    ks_fields = self.env[ks_model_name].fields_get()
                    ks_filtered_fields = {key: val for key, val in ks_fields.items() if
                                          val['type'] not in ['many2many', 'one2many', 'binary'] and 'name' in val and val[
                                              'name'] != 'id' and val['name'] != 'sequence' and val['store'] == True}
                    ks_fields_name = {val['name']: val['type'] for val in ks_filtered_fields.values()}
                    question = ("schema: " + f"{ks_fields_name}")
                    model =("model:" + f"{ks_model_name}")
                    api_key = self.env['ir.config_parameter'].sudo().get_param(
                        'ks_dashboard_ninja.dn_api_key')
                    url = self.env['ir.config_parameter'].sudo().get_param(
                        'ks_dashboard_ninja.url')
                    if api_key and url:
                        json_data = {'name': api_key,
                                     'question': self.ks_input_keywords,
                                     'type':self.ks_type,
                                     'schema':question,
                                     'model':model,
                                     'url': self.env['ir.config_parameter'].sudo().get_param('web.base.url'),
                                     'db_name': self.env.cr.dbname
                                     }
                        url = url + "/api/v1/ks_dn_main_api"
                        ks_ai_response = requests.post(url, data=json_data)
                        if ks_ai_response.status_code == 200:
                            ks_ai_response = json.loads(ks_ai_response.text)
                            ks_dash_id = self._context['ks_dashboard_id']
                            ks_model_name = (ks_ai_response[0]['model']).lower()
                            if self.env['ir.model'].search([('model','=',ks_model_name)]).id or self.env['ir.model'].search([('name','=',ks_model_name)]).id:
                                if self.env['ir.model'].search([('name','=',ks_model_name)]).id:
                                    ks_model_name = self.env['ir.model'].search([('name','=',ks_model_name)]).model
                                else:
                                    ks_model_name = (ks_ai_response[0]['model']).lower()
                                ks_result = self.env['ks_dashboard_ninja.item'].create_ai_dash(ks_ai_response, ks_dash_id,ks_model_name)
                                if ks_result == "success":
                                    return {
                                        'type': 'ir.actions.client',
                                        'tag': 'reload',
                                    }
                                else:
                                    raise ValidationError(_("Items didn't render, please try again!"))
                            else:
                                raise ValidationError(_("%s model does not exist.Please install")% ks_model_name)
                        else:
                            raise ValidationError(
                                _("AI Responds with the following status:- %s") % ks_ai_response.text)

                    else:
                        raise ValidationError(_("Please enter URL and API Key in General Settings"))
            else:
                raise ValidationError(_("Enter the input keywords to render the item"))

    @api.model
    def ks_generate_analysis(self,ks_items_explain,ks_rest_items,dashboard_id):
        if ks_items_explain:
            result = []
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.dn_api_key')
            ks_url = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.url')
            words = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.ks_analysis_word_length')
            url = ks_url + "/api/v1/ks_dn_main_api"
            for i in range(0,len(ks_items_explain)):
                if api_key and url :
                    json_data = {'name': api_key,
                                 'items':json.dumps(ks_items_explain[i]),
                                 'type':'ks_ai_explain',
                                 'url': self.env['ir.config_parameter'].sudo().get_param('web.base.url'),
                                 'db_name': self.env.cr.dbname,
                                 'words':  words if words else 100
                                 }
                    ks_response = requests.post(url, data=json_data)
                    if ks_response.status_code == 200 and json.loads(ks_response.text):
                        ks_ai_response = json.loads(ks_response.text)
                        item = ks_ai_response[0]
                        if item['analysis'] or item['insights']:
                            try:
                                self.env['ks_dashboard_ninja.item'].browse(item['id']).write({
                                'ks_ai_analysis': item['analysis']+'ks_gap'+item['insights']
                                })
                                result.append(True)
                            except:
                                result
                        else:
                            result

                    else:
                        result
                else:
                    raise ValidationError(_("Please put API key and URL"))
            if len(result):
                if self.env.context.get('explain_items_with_ai', False):
                    self.env['ks_dashboard_ninja.board'].browse(dashboard_id).write({
                        'ks_ai_explain_dash': False
                    })
                else:
                    self.env['ks_dashboard_ninja.board'].browse(dashboard_id).write({
                        'ks_ai_explain_dash': True
                    })
                return True
            else:
                raise ValidationError(_("AI Responds with the wrong analysis. Please try again "))
        elif ks_rest_items:
            if self.env.context.get('explain_items_with_ai', False):
                self.env['ks_dashboard_ninja.board'].browse(dashboard_id).write({
                    'ks_ai_explain_dash': False
                })
            else:
                self.env['ks_dashboard_ninja.board'].browse(dashboard_id).write({
                    'ks_ai_explain_dash': True
                })
            return True
        else:
            return False

    def get_ai_explain(self, item_id):
        print(item_id)
        res = self.env['ks_dashboard_ninja.item'].browse(item_id).ks_ai_analysis
        return res

    @api.model
    def ks_switch_default_dashboard(self,dashboard_id):
        self.env['ks_dashboard_ninja.board'].browse(dashboard_id).write({
            'ks_ai_explain_dash':False
        })
        return True
    @api.model
    def ks_generatetext_to_speech(self,item_id):
        if (item_id):
            try:
                ks_text = self.env['ks_dashboard_ninja.item'].browse(item_id).ks_ai_analysis
                if ks_text:
                    language = 'en'
                    ks_myobj = gTTS(text=ks_text, lang=language, slow=False)
                    audio_data = io.BytesIO()
                    ks_myobj.write_to_fp(audio_data)
                    audio_data.seek(0)
                    binary_data = audio_data.read()
                    wav_file = base64.b64encode( binary_data).decode('UTF-8')
                    data = {"snd": wav_file}
                    return json.dumps(data)
                else:
                    return False
            except Exception as e:
                _logger.error(e)
                raise ValidationError(_("Some problem in audio generation."))

        else:
            return False

    @api.model
    def ks_gen_chat_res(self,**kwargs):
        ks_question = kwargs.get('ks_question')
        url =  self.env['ir.config_parameter'].sudo().get_param(
            'ks_dashboard_ninja.url') + "/api/v1/get_sql_query"
        data = {
            "question": ks_question,
        }
        try:
            ks_response = requests.post(url,data=data)
            if (ks_response.status_code == 200):
                ks_response = json.loads(ks_response.text)['response']['Query']
                return self.ks_gen_dataframe(ks_response,ks_question)
            else:
                _logger.error('Unexpected error occurs')
                return False
        except Exception as e:
            _logger.error(e)
            return False



    def ks_gen_dataframe(self,ks_query,question):
        host = config.get('db_host', False)
        user = quote(config.get('db_user', False))
        port = config.get('db_port', False) or 5432
        password =  quote(config.get('db_password', False))
        db = config.get('db_name', False) or self.env.cr.dbname
        if not all([host, user, port, password, db]):
            _logger.error('some credentials are missing')
            return False
        else:
            sql_uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
            ks_fixed_url = self.env['ir.config_parameter'].sudo().get_param(
                'ks_dashboard_ninja.url') + "/api/v1/get_fixed_query"
            try:
                df = pd.read_sql(ks_query, sql_uri)
            except Exception as e:
                ks_query_data = {
                    'query':ks_query,
                    'error':e
                }
                fixed_query = requests.post(ks_fixed_url, data=ks_query_data)
                if fixed_query.status_code == 200:
                    ks_corrected_query = fixed_query.text
                    df = pd.read_sql(ks_corrected_query, sql_uri)
                else:
                    _logger.error('Error in generating Dataframe')
                    return False
            if any(df.dtypes == 'datetime64[ns]'):
                datetime_columns = [col for col in df.columns if df[col].dtype == 'datetime64[ns]']
                df[datetime_columns] = df[datetime_columns].astype(str)

            # Convert DataFrame to JSON
            if len(df) >= 100:
                df = df.head(100)
                partial_data = True

            df_json = df.to_json(orient='records')

            ans = "As dataframe having more data to analyse we are not showing dataframe summary"
            # Generate answer
            if len(df) < 13:
                ks_ans_url = self.env['ir.config_parameter'].sudo().get_param(
                    'ks_dashboard_ninja.url') + "/api/v1/get_answer"
                ks_ans_data = {'df':df.to_dict(orient='records'),'question':question}
                ans = requests.post(ks_ans_url, json = ks_ans_data)
                if ans.status_code == 200:
                    ans = ans.text
                    response_json = {
                        "Dataframe": df_json,
                        "Answer": ans,
                    }
                else:
                    _logger.error('Error in generating answer')
                    return False
            else:
                response_json = {
                    "Dataframe": df_json,
                    "Answer": ans,
                }
            return response_json
