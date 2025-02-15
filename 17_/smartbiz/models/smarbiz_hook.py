from lxml import etree
from odoo.exceptions import AccessError, ValidationError
from odoo import api, fields, models, _
import json


def check_action_permission(method):
    method._check_permission_decorated = True  # Đánh dấu phương thức đã được trang trí

    def wrapper(self, *args, **kwargs):
        function_name = method.__name__
        for record in self:
            # Check for task_definition for the function_name
            task_definition = record._get_task_definition(record.state, function_name)

            if task_definition:
                function = task_definition.function_ids.filtered(lambda r: r.function_name == function_name)
                if function:
                    function = function[0]  # Take the first function if multiple
                    if function.rule_ids:
                        # Check access rights
                        rule, rule_users = record._check_function_permission(function)
                        if not rule:
                            raise AccessError(_("You do not have permission to perform this action."))

                        # Get current task
                        current_task = record.env['smartbiz.task'].search([
                            ('task_definition_id', '=', task_definition.id),
                            ('res_id', '=', record.id),
                            ('model', '=', self._name),
                            ('state', 'not in', ['done', 'cancel']),
                        ], limit=1, order="create_date asc")
                        if not current_task:
                            deadline = task_definition.compute_deadline()
                            current_task = record.env['smartbiz.task'].create({
                                'task_definition_id': task_definition.id,
                                'res_id': record.id,
                                'model': self._name,
                                'state': 'assigned',
                                'assignees_ids': [(6, 0, rule_users.ids)],
                                'deadline': deadline
                            })

                        # Get users who have completed the action
                        completed_users = current_task.work_log_ids.mapped('user_id') if current_task else self.env['res.users']

                        # Determine pending users (users who haven't performed the action yet)
                        pending_users = rule_users - completed_users

                        current_user = self.env.user

                        # Check access rights based on task_finish and pending_users
                        if current_user not in pending_users:
                            raise AccessError(_("You have already performed this action or do not have permission."))

                        if rule.task_finish == 'sequence':
                            # Only the first pending user can perform the action
                            if pending_users and current_user != pending_users[0]:
                                raise AccessError(_("You are not the next user in the sequence to perform this action."))

                        call_method, actions = record._get_function_actions(function, rule, rule_users, current_task)

                        # If rule allows calling the original method before actions
                        if call_method == 'before':
                            method(record, *args, **kwargs)

                        reload = record._execute_actions(actions)

                        # If rule allows calling the original method after actions
                        if call_method == 'after':
                            method(record, *args, **kwargs)

                        current_task.write({
                            'work_log_ids': [(0, 0, {
                                'rule_id': rule.id,
                                'function_id': function.id,
                                'user_id': self.env.uid,
                                'name': current_task.name + ' - ' + function.name
                            })]
                        })

                    else:
                        # If no rule, call the original method
                        return method(record, *args, **kwargs)
                else:
                    # If no function, call the original method
                    return method(record, *args, **kwargs)
            else:
                # If no task, call the original method
                return method(record, *args, **kwargs)

    return wrapper

class SmartBiz_WorkflowBase(models.AbstractModel):
    _name = "smartbiz.workflow_base"
    _description = "Workflow Base"
    tasks_ids = fields.One2many('smartbiz.task', 'res_id')
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', store=False)
    button_permissions = fields.Text(compute='_compute_button_permissions', store=False)

    @api.depends('state', 'tasks_ids', 'tasks_ids.work_log_ids')
    def _compute_button_permissions(self):
        for record in self:
            buttons_info = record._get_buttons_info()
            record.button_permissions = json.dumps(buttons_info)

    @api.depends('tasks_ids')
    def _compute_model_id(self):
        for record in self:
            record.model_id = self.env['ir.model'].sudo()._get(self._name).id

    def _register_hook(self):
        super(SmartBiz_WorkflowBase, self)._register_hook()
        # Áp dụng decorator cho các phương thức action_ trong lớp hiện tại
        for cls in self.__class__.__subclasses__():
            # Kiểm tra nếu lớp kế thừa từ workflow_base
            if issubclass(cls, SmartBiz_WorkflowBase):
                for attr_name in dir(cls):
                    if attr_name.startswith('action_'):
                        attr = getattr(cls, attr_name)
                        if callable(attr) and not getattr(attr, '_check_permission_decorated', False):
                            decorated = check_action_permission(attr)
                            setattr(cls, attr_name, decorated)


    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super(SmartBiz_WorkflowBase, self)._get_view(view_id, view_type, **options)
        if view_type == 'form':
            # Kiểm tra xem trường đã tồn tại chưa
            if not arch.xpath("//field[@name='button_permissions']"):
                # Thêm trường button_permissions vào nhóm đầu tiên trong sheet
                sheet = arch.find('.//sheet')
                if sheet:
                    group = sheet.find('.//group') or etree.SubElement(sheet, 'group')
                    field_element = etree.Element('field', {'name': 'button_permissions', 'invisible': '1'})
                    group.insert(0, field_element)

        return arch, view

    def _get_buttons_info(self):
        self.ensure_one()
        model_name = self._name
        model_id = self.env['ir.model']._get(model_name).id
        current_user = self.env.user
        buttons_info = {}

        # Lấy workflow_definition hiện tại
        workflow_definition = self.env['smartbiz.workflow_definition'].sudo().search([
            ('model_id', '=', model_id), ('state', '=', 'active')
        ], limit=1, order="version asc")
        if not workflow_definition:
            return buttons_info

        # Chỉ xử lý task_definition của trạng thái hiện tại
        task_definitions = self.env['smartbiz.task_definition'].sudo().search([
            ('workflow_definition_id', '=', workflow_definition.id),
            ('state_id.value', '=', self.state)
        ])

        for task_definition in task_definitions:
            for function in task_definition.function_ids:
                function_name = function.function_name

                # Mặc định nút không hiển thị
                button_visible = False

                for rule in function.rule_ids.sudo().sorted(key=lambda r: r.sequence):
                    # Kiểm tra điều kiện
                    conditions_met = all(
                        self._evaluate_condition(condition)
                        for condition in rule.condition_ids
                    )
                    if not conditions_met:
                        continue

                    # Lấy danh sách người dùng từ rule
                    users = self._get_users_from_rule(rule)

                    # Tìm hoặc tạo current_task
                    current_task = self.env['smartbiz.task'].search([
                        ('task_definition_id', '=', task_definition.id),
                        ('res_id', '=', self.id),
                        ('model', '=', self._name),
                        ('state', 'not in', ['done', 'cancel']),
                    ], limit=1, order="create_date asc")

                    if not current_task:
                        deadline = task_definition.compute_deadline()
                        current_task = self.env['smartbiz.task'].create({
                            'task_definition_id': task_definition.id,
                            'res_id': self.id,
                            'model': self._name,
                            'state': 'assigned',
                            'assignees_ids': [(6, 0, users.ids)],
                            'deadline': deadline
                        })

                    # Lấy danh sách người dùng đã thực hiện
                    completed_users = current_task.work_log_ids.mapped('user_id')

                    # Xác định người dùng chưa thực hiện
                    pending_users = users - completed_users

                    if current_user in pending_users:
                        if rule.task_finish in ['any', 'parallel']:
                            # Bất kỳ người dùng nào chưa thực hiện đều có thể thấy nút
                            button_visible = True
                            break
                        elif rule.task_finish == 'sequence':
                            # Chỉ người dùng đầu tiên trong pending_users mới thấy nút
                            if pending_users and current_user == pending_users[0]:
                                button_visible = True
                                break

                buttons_info[function_name] = button_visible
        return buttons_info


    def _check_function_permission(self, function):       
        for rule in function.rule_ids.sudo().sorted(key=lambda r: r.sequence):
            conditions_met = all(
                self._evaluate_condition(condition)
                for condition in rule.condition_ids
            )
            if not conditions_met:
                continue

            # Lấy danh sách người dùng
            users = self._get_users_from_rule(rule)
            if self.env.user in users:
                return rule, users
        return False, self.env['res.users']  # Không có quyền

    def _get_task_definition(self, state, function_name):
        model_name = self._name
        model_id = self.env['ir.model']._get(model_name).id

        workflow_definition = self.env['smartbiz.workflow_definition'].sudo().search([
            ('model_id', '=', model_id), ('state', '=', 'active')
        ], limit=1, order="version asc")
        if not workflow_definition:
            return False

        task = self.env['smartbiz.task_definition'].sudo().search([
            ('workflow_definition_id', '=', workflow_definition.id),
            ('function_ids.function_name', '=', function_name),
            ('state_id.value', '=', state)
        ], limit=1)
        if task:
            return task  # Tìm thấy function_name trong workflow definition
        return False  # Không tìm thấy function_name

    def _get_function_actions(self, function, rule, rule_users, current_task):
        # Lấy giá trị của call_method từ trường run_code của function
        call_method = function.run_code or 'no'  # Mặc định là 'after' nếu không được thiết lập

        # Lấy danh sách người dùng đã thực hiện hành động
        completed_users = current_task.work_log_ids.mapped('user_id')

        # Xác định người dùng chưa thực hiện
        pending_users = rule_users - completed_users

        # Lấy người dùng hiện tại
        current_user = self.env.user

        # Danh sách các action để trả về
        actions = []

        # Kiểm tra nếu rule có task_finish là 'any'
        if rule.task_finish == 'any':
            # Trả về tất cả các action có trigger_type != 'on_user_assignment'
            actions = function.action_ids.filtered(lambda a: a.trigger_type != 'on_user_assignment')
            return call_method, actions

        # Nếu còn người dùng chưa thực hiện và người dùng hiện tại chưa thực hiện
        if pending_users and current_user in pending_users:
            # Trả về các action có trigger_type = 'on_user_action'
            actions = function.action_ids.filtered(lambda a: a.trigger_type == 'on_user_action')
            return call_method, actions

        # Nếu là người cuối cùng cần thực hiện
        if not pending_users or (len(pending_users) == 1 and current_user in pending_users):
            # Trả về tất cả các action có trigger_type != 'on_user_assignment'
            actions = function.action_ids.filtered(lambda a: a.trigger_type != 'on_user_assignment')
            return call_method, actions

        # Nếu không rơi vào các điều kiện trên, không trả về action nào
        return call_method, []


    def _execute_actions(self, actions):
        reload_needed = False
        for action in actions:
            if action.type == 'send_notification':
                if action.template_id:
                    # Gửi thông báo sử dụng template
                    for record in self:
                        action.template_id.send_mail(record.id, force_send=True)
            elif action.type == 'move_to_state':
                if action.state_id:
                    # Cập nhật trường state của bản ghi
                    for record in self:
                        record.write({'state':action.state_id.value})
                        reload_needed = True  # Cần reload để cập nhật giao diện
            elif action.type == 'run_server_action':
                if action.server_action_id:
                    # Thực thi server action
                    action.server_action_id.with_context(active_model=self._name, active_ids=self.ids, active_id=self.id).run()
        return reload_needed

    def _get_users_from_rule(self, rule):
        users = self.env['res.users']
        for resource in rule.resource_ids:
            resource_users = self._get_users_from_resource(resource)
            if resource.operator == 'and':
                users = users & resource_users if users else resource_users
            else:
                users = users | resource_users if users else resource_users
        return users

    def _evaluate_condition(self, condition):
        field_name = condition.field_id.name
        operator = condition.operator
        value = condition.value

        # Lấy giá trị của trường từ bản ghi hiện tại
        record_value = getattr(self, field_name)

        # Chuyển đổi giá trị nhập vào phù hợp với kiểu dữ liệu của trường
        field_type = condition.field_id.ttype
        value_converted = self._convert_value(value, field_type)

        # Tạo biểu thức so sánh
        operators = {
            '=': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '>': lambda a, b: a > b,
            '<': lambda a, b: a < b,
            '>=': lambda a, b: a >= b,
            '<=': lambda a, b: a <= b,
            'in': lambda a, b: a in b,
            'not in': lambda a, b: a not in b,
            'like': lambda a, b: b in a,
            'ilike': lambda a, b: b.lower() in a.lower(),
        }

        try:
            result = operators[operator](record_value, value_converted)
            return result
        except Exception as e:
            _logger.error('Error evaluating condition: %s', e)
            return False

    def _get_users_from_resource(self, resource):
        Users = self.env['res.users']
        users = Users.browse()
        if resource.method == 'by_position':
            if resource.position_id:
                users = resource.position_id.users_ids
        elif resource.method == 'by_role':
            if resource.role_id:
                positions = self.env['smartbiz.position'].search([('roles_ids', 'in', resource.role_id.id)])
                users = positions.mapped('users_ids')
        elif resource.method == 'by_level':
            if resource.level_id:
                positions = self.env['smartbiz.position'].search([('level_id', '=', resource.level_id.id)])
                users = positions.mapped('users_ids')
        elif resource.method == 'by_user_field':
            if resource.user_field_id:
                user_field_name = resource.user_field_id.name
                users = getattr(self, user_field_name)
        elif resource.method == 'by_ou_field':
            if resource.role_id and resource.ou_field_id:
                ou_field_name = resource.ou_field_id.name
                ou = getattr(self, ou_field_name)
                if ou:
                    positions = self.env['smartbiz.position'].search([
                        ('organization_unit_id', '=', ou.id),
                        ('roles_ids', 'in', resource.role_id.id)
                    ])
                    users = positions.mapped('users_ids')
        return users

    def _convert_value(self, value, field_type):
        if field_type in ['char', 'text', 'html']:
            return value
        elif field_type == 'integer':
            return int(value)
        elif field_type == 'float':
            return float(value)
        elif field_type == 'boolean':
            return value.lower() in ['true', '1', 'yes']
        elif field_type == 'many2one':
            return int(value)
        elif field_type in ['date', 'datetime']:
            # Chuyển đổi giá trị sang đối tượng datetime nếu cần
            return fields.Datetime.from_string(value)
        else:
            return value
