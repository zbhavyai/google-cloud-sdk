# -*- coding: utf-8 -*- #
# Copyright 2017 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Data objects to support the yaml command schema."""


from __future__ import absolute_import
from __future__ import annotations
from __future__ import division
from __future__ import unicode_literals

import abc
from collections.abc import Callable
import dataclasses
from typing import Any

from apitools.base.protorpclite import messages as apitools_messages
from googlecloudsdk.calliope import actions
from googlecloudsdk.calliope import arg_parsers
from googlecloudsdk.calliope import arg_parsers_usage_text as usage_text
from googlecloudsdk.command_lib.util.apis import arg_utils
from googlecloudsdk.command_lib.util.args import labels_util
from googlecloudsdk.core import module_util
from googlecloudsdk.core.util import http_encoding


NAME_FORMAT_KEY = '__name__'
RESOURCE_ID_FORMAT_KEY = '__resource_id__'
REL_NAME_FORMAT_KEY = '__relative_name__'
RESOURCE_TYPE_FORMAT_KEY = '__resource_type__'
KEY, VALUE = 'key', 'value'
ARG_OBJECT, ARG_DICT, ARG_LIST, ARG_JSON = (
    'arg_object', 'arg_dict', 'arg_list', 'arg_json')
SPEC, PARAMS, GROUP = 'spec', 'params', 'group'
FILE_TYPE = 'file_type'


def FormatResourceAttrStr(format_string, resource_ref, display_name=None,
                          display_resource_type=None):
  """Formats a string with all the attributes of the given resource ref.

  Args:
    format_string: str, The format string.
    resource_ref: resources.Resource, The resource reference to extract
      attributes from.
    display_name: the display name for the resource.
    display_resource_type:

  Returns:
    str, The formatted string.
  """
  if resource_ref:
    d = resource_ref.AsDict()
    d[NAME_FORMAT_KEY] = (
        display_name or resource_ref.Name())
    d[RESOURCE_ID_FORMAT_KEY] = resource_ref.Name()
    d[REL_NAME_FORMAT_KEY] = resource_ref.RelativeName()
  else:
    d = {NAME_FORMAT_KEY: display_name}
  d[RESOURCE_TYPE_FORMAT_KEY] = display_resource_type

  try:
    return format_string.format(**d)
  except KeyError as err:
    if err.args:
      raise KeyError('Key [{}] does not exist. Must specify one of the '
                     'following keys instead: {}'.format(
                         err.args[0], ', '.join(d.keys())))
    else:
      raise err


class Error(Exception):
  """Base class for module errors."""
  pass


class InvalidSchemaError(Error):
  """Error for when a yaml command is malformed."""
  pass


class Hook(object):
  """Represents a Python code hook declared in the yaml spec.

  A code hook points to some python element with a module path, and attribute
  path like: package.module:class.attribute.

  If arguments are provided, first the function is called with the arguments
  and the return value of that is the hook that is used. For example:

  googlecloudsdk.calliope.arg_parsers:Duration:lower_bound=1s,upper_bound=1m
  """

  @classmethod
  def FromData(cls, data, key):
    """Gets the hook from the spec data.

    Args:
      data: The yaml spec
      key: The key to extract the hook path from.

    Returns:
      The Python element to call.
    """
    path = data.get(key)
    if path:
      return cls.FromPath(path)
    return None

  @classmethod
  def FromPath(cls, path):
    """Gets the hook from the function path.

    Args:
      path: str, The module path to the hook function.

    Returns:
      The Python element to call.
    """
    return ImportPythonHook(path).GetHook()

  def __init__(self, attribute, kwargs=None):
    self.attribute = attribute
    self.kwargs = kwargs

  def GetHook(self):
    """Gets the Python element that corresponds to this hook.

    Returns:
      A Python element.
    """
    if self.kwargs is not None:
      return  self.attribute(**self.kwargs)
    return self.attribute


def ImportPythonHook(path):
  """Imports the given python hook.

  Depending on what it is used for, a hook is a reference to a class, function,
  or attribute in Python code.

  Args:
    path: str, The path of the hook to import. It must be in the form of:
      package.module:attribute.attribute where the module path is separated from
      the class name and sub attributes by a ':'. Additionally, ":arg=value,..."
      can be appended to call the function with the given args and use the
      return value as the hook.

  Raises:
    InvalidSchemaError: If the given module or attribute cannot be loaded.

  Returns:
    Hook, the hook configuration.
  """
  parts = path.split(':')
  if len(parts) != 2 and len(parts) != 3:
    raise InvalidSchemaError(
        'Invalid Python hook: [{}]. Hooks must be in the format: '
        'package(.module)+:attribute(.attribute)*(:arg=value(,arg=value)*)?'
        .format(path))
  try:
    attr = module_util.ImportModule(parts[0] + ':' + parts[1])
  except module_util.ImportModuleError as e:
    raise InvalidSchemaError(
        'Could not import Python hook: [{}]. {}'.format(path, e))

  kwargs = None
  if len(parts) == 3:
    kwargs = {}
    for arg in parts[2].split(','):
      if not arg:
        continue
      arg_parts = arg.split('=')
      if len(arg_parts) != 2:
        raise InvalidSchemaError(
            'Invalid Python hook: [{}]. Args must be in the form arg=value,'
            'arg=value,...'.format(path))
      kwargs[arg_parts[0].strip()] = arg_parts[1].strip()

  return Hook(attr, kwargs)


TRUE_FALSE_ACTION = 'store_true_false'
STATIC_ACTIONS = frozenset(('store', 'store_true', 'append'))


def ParseAction(action, flag_name):
  """Parse the action out of the argument spec.

  Args:
    action: The argument action spec data.
    flag_name: str, The effective flag name.

  Raises:
    ValueError: If the spec is invalid.

  Returns:
    The action to use as argparse accepts it. It will either be a class that
    implements action, or it will be a str of a builtin argparse type.
  """
  if not action:
    return None

  if isinstance(action, str):
    if action == TRUE_FALSE_ACTION:
      return arg_parsers.StoreTrueFalseAction
    elif action in STATIC_ACTIONS:
      return action
    else:
      return Hook.FromPath(action)

  deprecation = action.get('deprecated')
  if deprecation:
    return actions.DeprecationAction(flag_name, **deprecation)

  raise ValueError('Unknown value for action: ' + str(action))


BUILTIN_TYPES = {
    'str': str,
    'int': int,
    'long': int,
    'float': float,
    'bool': bool,
    'bytes': http_encoding.Encode,
}


def _ParseTypeFromStr(arg_type, data):
  """Parses type from string.

  Args:
    arg_type: str, string representation of type
    data: dict, raw argument data

  Returns:
    The type to use as argparse accepts it.
  """
  if arg_type == ARG_OBJECT:
    return ArgObject.FromData(data)
  elif arg_type == ARG_LIST:
    return Hook.FromPath('googlecloudsdk.calliope.arg_parsers:ArgList:')
  elif arg_type == ARG_JSON:
    return ArgJSON.FromData(data)
  elif arg_type == FILE_TYPE:
    return FileContents.FromData(data)
  elif builtin_type := BUILTIN_TYPES.get(arg_type, None):
    return builtin_type
  else:
    return Hook.FromPath(arg_type)


def ParseType(data):
  """Parse the action out of the argument spec.

  Args:
    data: dict, raw arugment data

  Raises:
    ValueError: If the spec is invalid.
    InvalidSchemaError: If spec and non arg_object type are provided.

  Returns:
    The type to use as argparse accepts it.
  """
  contains_spec = any(key in data for key in (SPEC, PARAMS, GROUP))
  if specified_type := data.get('type'):
    arg_type = specified_type
  elif contains_spec:
    arg_type = ARG_OBJECT
  else:
    arg_type = None

  if contains_spec and arg_type != ARG_OBJECT:
    arg_name = data.get('arg_name')
    raise InvalidSchemaError(
        'Only flags with type arg_object may contain a spec declaration. '
        f'Flag {arg_name} has type {arg_type}. Update the type or '
        'remove the spec declaration.')

  if not arg_type and not contains_spec:
    return None
  elif isinstance(arg_type, dict) and ARG_DICT in arg_type:
    return ArgDict.FromData(data)
  elif isinstance(arg_type, str):
    return _ParseTypeFromStr(arg_type, data)

  raise ValueError('Unknown value for type: ' + str(arg_type))


class Choice(object):
  """Holds information about a single enum choice value."""

  def __init__(self, data):
    self.arg_value = data['arg_value']
    if isinstance(self.arg_value, str):
      # We always do a case insensitive comparison.
      self.arg_value = self.arg_value.lower()
    if 'enum_value' in data:
      self.enum_value = data['enum_value']
    else:
      self.enum_value = arg_utils.ChoiceToEnumName(self.arg_value)
    self.help_text = data.get('help_text')
    self.hidden = data.get('hidden')

  @classmethod
  def ToChoiceMap(cls, choices):
    """Converts a list of choices into a map for easy value lookup.

    Args:
      choices: [Choice], The choices.

    Returns:
      {arg_value: enum_value}, A mapping of user input to the value that should
      be used. All arg_values have already been converted to lowercase for
      comparison.
    """
    if not choices:
      return {}
    return {c.arg_value: c.enum_value for c in choices}


class TypeGenerator(metaclass=abc.ABCMeta):
  """Interface for generating a type from a field."""

  @abc.abstractmethod
  def GenerateType(self, field):
    """Generates a type from a field."""


class FileContents(TypeGenerator, arg_utils.FileType):
  """Holds information about a file content argument."""

  @classmethod
  def FromData(cls, data):
    """Creates a FileContents from yaml data."""
    # Data is not used at the moment but will be used to denote additional
    # information about the file in the future.
    del data
    return cls()

  def GenerateType(self, field):
    if not field or field.variant == apitools_messages.Variant.STRING:
      return arg_parsers.FileContents(binary=False)
    if field.variant == apitools_messages.Variant.BYTES:
      return arg_parsers.FileContents(binary=True)
    else:
      raise InvalidSchemaError(
          f'Conflicting types for field: {field.name}.'
          ' Only string and bytes fields are supported when using file_type.'
      )


@dataclasses.dataclass(frozen=True)
class _FieldSpec:
  """Holds information about a field and type that is generated from it."""

  @classmethod
  def FromUserData(
      cls, field, api_field=None, field_type=None, arg_name=None,
      required=None, hidden=False
  ):
    """Creates a _FieldSpec from user input.

    If value is not provided in yaml schema by user, the value is defaulted
    to a value derived from the apitools field.

    Args:
      field: apitools field instance
      api_field: The name of the field under the repeated message that the value
        should be put.
      field_type: The type of the field if specified by user.
      arg_name: The name of the key in the dict.
      required: True if the key is required.
      hidden: True if the help text should be hidden.

    Returns:
      _FieldSpec instance

    Raises:
      ValueError: if the field contradicts the values provided by the user
    """
    field_name = api_field or field.name
    child_field_name = arg_utils.GetChildFieldName(field_name)

    if child_field_name != field.name:
      raise ValueError(
          f'Expected to receive field {child_field_name} but '
          f'got {field.name}')

    if isinstance(field_type, TypeGenerator):
      generated_field_type = field_type.GenerateType(field)
    else:
      generated_field_type = field_type

    return cls(
        field=field,
        api_field=field_name,
        arg_name=arg_name or child_field_name,
        field_type=generated_field_type,
        repeated=field.repeated,
        required=required if required is not None else field.required,
        hidden=hidden
    )

  field: apitools_messages.Field
  api_field: str
  arg_name: str
  field_type: Callable[[str], Any] | None
  repeated: bool
  required: bool
  hidden: bool | None


class EquitableType(metaclass=abc.ABCMeta):
  """Wrapper that deteremines if two message fields of same type are equal.

  This is needed because the old message may contain ouptut only fields the
  user is not able to specify. For example, a message field may contain output
  only field `uid` that the user is not able to specify. Message(foo=bar)
  should still "match" existing Message(foo=bar, uid=baz).
  """

  @abc.abstractmethod
  def Matches(self, existing_value, new_value):
    """Checks if new value matches existing value based on what user input."""


class _FieldSpecType(usage_text.DefaultArgTypeWrapper, metaclass=abc.ABCMeta):
  """Wrapper that holds the arg type and information about the type.

  Interface allows users to parse string into arg_type and then parse value
  into correct apitools field.

  Attributes:
    field: apitools field instance
    api_field: str, name of the field where value should be mapped in message.
    arg_name: str, name of key in dict.
    repeated: bool, whether the field is repeated.
    required: bool, whether the field value is required.
  """

  def __init__(self, arg_type, field_spec):
    super(_FieldSpecType, self).__init__(arg_type=arg_type)
    self.field = field_spec.field
    self.api_field = field_spec.api_field
    self.arg_name = field_spec.arg_name
    self.repeated = field_spec.repeated
    self.required = field_spec.required

  def ParseIntoMessage(self, message_instance, value):
    """Sets field in a message after value is parsed into correct type.

    Args:
      message_instance: apitools message instance we are parsing value into
      value: value we are parsing into apitools message
    """
    if value is None and self.repeated:
      field_value = []
    else:
      field_value = value
    arg_utils.SetFieldInMessage(
        message_instance, self.api_field, field_value)

  @abc.abstractmethod
  def __call__(self, arg_value):
    """Parses arg_value into apitools message using field specs provided."""


class _FieldType(_FieldSpecType, EquitableType):
  """Type that converts string into apitools field instance.

  Attributes:
    choices: list[Choice], list of valid user inputs
  """

  def __init__(self, choices=None, **kwargs):
    super(_FieldType, self).__init__(**kwargs)
    self.choices = choices

  def __call__(self, arg_value):
    """Converts string into apitools field value."""
    parsed_arg_value = self.arg_type(arg_value)
    return arg_utils.ConvertValue(
        self.field, parsed_arg_value, repeated=self.repeated,
        choices=self.choices)

  def Matches(self, existing_value, new_value):
    """Checks if new value matches existing value based on what user input."""
    if existing_value == new_value:
      return True
    elif existing_value is None or new_value is None:
      return False

    # Handle repeated fields. Convert to list if not already a list.
    new_val_list = new_value if isinstance(new_value, list) else [new_value]
    existing_val_list = (existing_value if isinstance(existing_value, list)
                         else [existing_value])
    if len(new_val_list) != len(existing_val_list):
      return False
    for val in new_val_list:
      if val not in existing_val_list:
        return False
    return True


def _SubFieldMatches(existing_value, new_value, field_spec):
  """Checks if new value matches existing value based on what user input."""
  existing_field = arg_utils.GetFieldValueFromMessage(
      existing_value, field_spec.api_field)
  new_field = arg_utils.GetFieldValueFromMessage(
      new_value, field_spec.api_field)
  return field_spec.Matches(existing_field, new_field)


class _MessageFieldType(_FieldSpecType, EquitableType):
  """Type that converts string input into apitools message.

  Attributes:
    field_specs: list[_FieldSpecType], list of message's fields
  """

  def __init__(self, field_specs, **kwargs):
    super(_MessageFieldType, self).__init__(**kwargs)
    self.field_specs = field_specs

  def _ParseFieldsIntoMessage(self, arg_value):
    """Iterates through fields and adds fields to message instance."""
    message_instance = self.field.type()
    for arg_type in self.field_specs:
      value = arg_value.get(arg_type.arg_name)
      arg_type.ParseIntoMessage(message_instance, value)
    return message_instance

  def __call__(self, arg_value):
    """Converts string into apitools message."""
    parsed_arg_value = self.arg_type(arg_value)
    if isinstance(parsed_arg_value, list):
      return [self._ParseFieldsIntoMessage(r) for r in parsed_arg_value]
    else:
      return self._ParseFieldsIntoMessage(parsed_arg_value)

  def _ContainsVal(self, new_val, all_values):
    """Checks if new value matches existing value based on what user input."""
    for val in all_values:
      matches = all(_SubFieldMatches(val, new_val, spec)
                    for spec in self.field_specs)
      if matches:
        return True
    else:
      return False

  def Matches(self, existing_value, new_value):
    """Checks if new value matches existing value based on what user input."""
    if existing_value == new_value:
      return True
    elif existing_value is None or new_value is None:
      return False

    # Handle repeated fields. Convert to list if not already a list.
    existing_val_list = (existing_value if isinstance(existing_value, list)
                         else [existing_value])
    new_val_list = (new_value if isinstance(new_value, list)
                    else [new_value])
    if len(existing_val_list) != len(new_val_list):
      return False

    for new_val in new_val_list:
      if not self._ContainsVal(new_val, existing_val_list):
        return False
    return True


class _AdditionalPropsType(_FieldSpecType, EquitableType):
  """Type converts string into list of apitools message instances for map field.

  Type function returns a list of apitools messages with key, value fields ie
  [Message(key=key1, value=value1), Message(key=key2, value=value2), etc].
  The list of messages is how apitools specifies map fields.

  Attributes:
    key_spec: _FieldSpecType, specifes expected type of key field
    value_spec: _FieldSpecType, specifies expected type of value field
  """

  def __init__(self, key_spec, value_spec, **kwargs):
    super(_AdditionalPropsType, self).__init__(**kwargs)
    self.key_spec = key_spec
    self.value_spec = value_spec

  def __call__(self, arg_value):
    parsed_arg_value = self.arg_type(arg_value)
    messages = []
    # NOTE: While repeating fields and messages are accounted for, repeating
    # maps are not. This is because repeating map fields are not allowed in
    # proto definitions. Result will never be a list of dictionaries.
    for k, v in sorted(parsed_arg_value.items()):
      message_instance = self.field.type()
      self.key_spec.ParseIntoMessage(message_instance, k)
      self.value_spec.ParseIntoMessage(message_instance, v)
      messages.append(message_instance)
    return messages

  def Matches(self, existing_value, new_value):
    if existing_value == new_value:
      return True
    elif existing_value is None or new_value is None:
      return False
    elif len(existing_value) != len(new_value):
      return False

    sub_field_map = {
        val.key: val.value for val in existing_value
    }
    for val in new_value:
      if val.key not in sub_field_map:
        return False
      if not self.value_spec.Matches(sub_field_map[val.key], val.value):
        return False
    return True


class _MapFieldType(_FieldSpecType, EquitableType):
  """Type converts string into apitools additional props field instance."""

  def __call__(self, arg_value):
    """Parses arg_value into additional props field of apitools messages."""
    additional_props_field = self.arg_type(arg_value)
    parent_message = self.field.type()
    self.arg_type.ParseIntoMessage(parent_message, additional_props_field)
    return parent_message

  def Matches(self, existing_value, new_value):
    """Checks if new value matches existing value based on what user input."""
    if existing_value == new_value:
      return True
    elif existing_value is None or new_value is None:
      return False
    else:
      return _SubFieldMatches(existing_value, new_value, self.arg_type)


def _GetFieldValueType(field):
  """Returns the input type for the apitools field.

  Args:
    field: apitools field instance

  Returns:
    Type function for apitools field input.

  Raises:
    InvalidSchemaError: if the field type is not listed in arg_utils.TYPES
  """
  arg_type = arg_utils.TYPES.get(field.variant)
  if not arg_type:
    raise InvalidSchemaError('Unknown type for field: ' + field.name)
  return arg_type


class ArgObject(arg_utils.ArgObjectType):
  """A wrapper to bind an ArgObject argument to a message or field."""

  @classmethod
  def _FieldTypeFromData(cls, data):
    """Creates ArgObject from yaml data."""
    if (data_type := data.get('type')) and data_type != ARG_OBJECT:
      return ParseType(data)
    else:
      return None

  @classmethod
  def _SpecFromData(cls, params_data, api_field, parent_field):
    """Creates ArgObject types from yaml spec data."""
    spec = []
    for field_data in params_data:
      arg_object = ArgObject.FromData(
          field_data, parent_field=api_field or parent_field)
      # Flatten specs that do not have an api_field associated with them.
      # This supports the use case where there is a mutex arg group that does
      # not have an api_field associated with it.
      if not arg_object.api_field and arg_object.spec:
        spec.extend(arg_object.spec)
      else:
        spec.append(arg_object)
    return spec

  @classmethod
  def _RelativeApiField(cls, api_field, parent_field=None):
    """Creates ArgObject from yaml data."""
    # Api field is either relative to the parent field or the root message.
    # If the field is relative to the root field, we remove the parent field
    # to make it relative to the parent message.
    if not parent_field or not api_field:
      return api_field

    prefix = f'{parent_field}.'
    if api_field.startswith(prefix):
      return api_field[len(prefix):]
    else:
      return api_field

  @classmethod
  def FromData(cls, data, disable_key_description=False, parent_field=None):
    """Creates ArgObject from yaml data."""
    if group := data.get(GROUP):
      group_data = group
    else:
      group_data = data

    api_field = group_data.get('api_field')

    if (params := group_data.get(PARAMS) or group_data.get(SPEC)) is not None:
      spec = cls._SpecFromData(params, api_field, parent_field)
    else:
      spec = None

    # The only time it's possible to generate an ArgObject without an api
    # field is when it's part of a mutex group. In which case, it will use
    # the parent api field.
    json_name = group_data.get('json_name')
    if not group_data.get('mutex') and not api_field:
      arg_name = group_data.get('arg_name') or json_name
      raise InvalidSchemaError(
          f'api_field is required for {arg_name}: '
          f'Add api_field to {arg_name} to generate a valid ArgObject.'
      )

    return cls(
        api_field=cls._RelativeApiField(api_field, parent_field),
        json_name=json_name,
        help_text=group_data.get('help_text'),
        hidden=group_data.get('hidden'),
        field_type=cls._FieldTypeFromData(group_data),
        spec=spec,
        disable_key_description=disable_key_description,
    )

  def __init__(self, api_field=None, json_name=None, help_text=None,
               hidden=None, field_type=None, spec=None,
               disable_key_description=False):
    # Represents user specified yaml data
    self.api_field = api_field
    self.json_name = json_name
    self.help_text = help_text
    self.hidden = hidden
    self.field_type = field_type
    self.spec = spec
    self.disable_key_description = disable_key_description

  def Action(self, field):
    """Returns the correct argument action.

    Args:
      field: apitools field instance

    Returns:
      str, argument action string.
    """
    if field.repeated:
      return arg_parsers.FlattenAction()
    return 'store'

  def _GetFieldTypeFromSpec(self, api_field):
    """Returns first spec field that matches the api_field."""
    default_type = ArgObject(
        disable_key_description=self.disable_key_description)
    spec = self.spec or []
    return next((f for f in spec if f.api_field == api_field), default_type)

  def _GenerateSubFieldType(self, message, api_field, is_label_field=False):
    """Retrieves the the type of the field from messsage.

    Args:
      message: Apitools message class
      api_field: str, field path of message
      is_label_field: bool, whether field is part of labels map field

    Returns:
      _FieldSpecType, Type function that returns apitools message
        instance or list of instances from string value.
    """
    f = arg_utils.GetFieldFromMessage(message, api_field)
    arg_obj = self._GetFieldTypeFromSpec(api_field)
    return arg_obj.GenerateType(
        f, is_label_field=is_label_field, is_root=False)

  def _GenerateMapType(self, field_spec, is_root=True):
    """Returns function that parses apitools map fields from string.

    Map fields are proto fields with type `map<...>` that generate
    apitools message with an additionalProperties field

    Args:
      field_spec: _FieldSpec, information about the field
      is_root: whether the type function is for the root level of the message

    Returns:
      type function that takes string like 'foo=bar' or '{"foo": "bar"}' and
        creates an apitools message additionalProperties field
    Raises:
      InvalidSchemaError: if type is specified for a map field
    """
    if field_type := field_spec.field_type:
      raise InvalidSchemaError(
          f'Field type {field_type} is not supported for map field '
          f'{self.api_field}. Remove the type declaration from spec.'
      )
    try:
      additional_props_field = arg_utils.GetFieldFromMessage(
          field_spec.field.type, arg_utils.ADDITIONAL_PROPS)
    except arg_utils.UnknownFieldError:
      raise InvalidSchemaError(
          '{name} message does not contain field "{props}". Remove '
          '"{props}" from api field name.'.format(
              name=field_spec.api_field,
              props=arg_utils.ADDITIONAL_PROPS
          ))

    is_label_field = field_spec.arg_name == 'labels'
    props_field_spec = _FieldSpec.FromUserData(
        additional_props_field, arg_name=self.json_name)
    key_type = self._GenerateSubFieldType(
        additional_props_field.type, KEY, is_label_field=is_label_field)
    value_type = self._GenerateSubFieldType(
        additional_props_field.type, VALUE, is_label_field=is_label_field)

    # Repeated not included since map fields can never be repeated
    arg_obj = arg_parsers.ArgObject(
        key_type=key_type,
        value_type=value_type,
        help_text=self.help_text,
        hidden=field_spec.hidden,
        root_level=is_root,
        disable_key_description=self.disable_key_description,
        allow_key_only=True)

    additional_prop_spec_type = _AdditionalPropsType(
        arg_type=arg_obj,
        field_spec=props_field_spec,
        key_spec=key_type,
        value_spec=value_type)

    # Uses an additional type function to map additionalProperties back into
    # parent map message
    return _MapFieldType(
        arg_type=additional_prop_spec_type,
        field_spec=field_spec)

  def _GenerateMessageType(self, field_spec, is_root=True):
    """Returns function that parses apitools message fields from string.

    Args:
      field_spec: _FieldSpec, information about the field
      is_root: whether the _MessageFieldType is for the root level of
        the message

    Returns:
      _MessageFieldType that takes string like 'foo=bar' or '{"foo": "bar"}' and
      creates an apitools message like Message(foo=bar) or [Message(foo=bar)]

    Raises:
      InvalidSchemaError: if type is specified for a message field
    """
    if field_type := field_spec.field_type:
      raise InvalidSchemaError(
          f'Field type {field_type} is not supported for message field '
          f'{self.api_field}. Remove the type declaration from spec.'
      )

    if self.spec is not None:
      field_names = [f.api_field for f in self.spec]
    else:
      output_only_fields = {'createTime', 'updateTime'}
      field_names = [
          f.name for f in field_spec.field.type.all_fields()
          if f.name not in output_only_fields]

    field_specs = [
        self._GenerateSubFieldType(field_spec.field.type, name)
        for name in field_names
    ]

    required = [f.arg_name for f in field_specs if f.required]
    arg_obj = arg_parsers.ArgObject(
        spec={f.arg_name: f for f in field_specs},
        help_text=self.help_text,
        required_keys=required,
        repeated=field_spec.repeated,
        hidden=field_spec.hidden,
        root_level=is_root,
        disable_key_description=self.disable_key_description,
        allow_key_only=True)

    return _MessageFieldType(
        arg_type=arg_obj,
        field_spec=field_spec,
        field_specs=field_specs)

  def _GenerateFieldType(self, field_spec, is_label_field=False):
    """Returns _FieldType that parses apitools field from string.

    Args:
      field_spec: _FieldSpec, information about the field
      is_label_field: bool, whether or not the field is for a labels map field.
        If true, supplies default validation and help text.

    Returns:
      _FieldType that takes string like '1' or ['1'] and parses it
      into 1 or [1] depending on the apitools field type
    """
    if is_label_field and field_spec.arg_name == KEY:
      value_type = labels_util.KEY_FORMAT_VALIDATOR
      default_help_text = labels_util.KEY_FORMAT_HELP
    elif is_label_field and field_spec.arg_name == VALUE:
      value_type = labels_util.VALUE_FORMAT_VALIDATOR
      default_help_text = labels_util.VALUE_FORMAT_HELP
    else:
      value_type = field_spec.field_type or _GetFieldValueType(field_spec.field)
      default_help_text = None

    arg_obj = arg_parsers.ArgObject(
        value_type=value_type,
        help_text=self.help_text or default_help_text,
        repeated=field_spec.repeated,
        hidden=field_spec.hidden,
        root_level=False,
        enable_file_upload=(
            not isinstance(value_type, arg_parsers.FileContents)),
        disable_key_description=self.disable_key_description
    )
    return _FieldType(
        arg_type=arg_obj,
        field_spec=field_spec,
        choices=None)

  def GenerateType(self, field, is_root=True, is_label_field=False):
    """Generates a _FieldSpecType to parse the argument.

    Args:
      field: apitools field instance we are generating ArgObject for
      is_root: bool, whether this is the first level of the ArgObject
        we are generating for.
      is_label_field: bool, whether the field is for labels map field

    Returns:
      _FieldSpecType, Type function that returns apitools message
      instance or list of instances from string value.
    """
    field_spec = _FieldSpec.FromUserData(
        field, arg_name=self.json_name, field_type=self.field_type,
        api_field=self.api_field, hidden=self.hidden)
    field_variation = arg_utils.GetFieldType(field)
    if field_variation == arg_utils.FieldType.MAP:
      return self._GenerateMapType(field_spec, is_root)
    # TODO(b/286379489): add parsing logic for cyclical fields
    elif field_variation == arg_utils.FieldType.MESSAGE:
      return self._GenerateMessageType(field_spec, is_root)
    else:
      return self._GenerateFieldType(field_spec, is_label_field)


def _GetArgDictFieldType(message, user_field_spec):
  """Retrieves the the type of the field from message.

  Args:
    message: Apitools message class
    user_field_spec: ArgDictFieldSpec, specifies the api field

  Returns:
    _FieldType, type function that returns apitools field class
  """
  field = arg_utils.GetFieldFromMessage(message, user_field_spec.api_field)
  arg_type = user_field_spec.field_type or _GetFieldValueType(field)
  field_spec = _FieldSpec.FromUserData(
      field,
      arg_name=user_field_spec.arg_name,
      api_field=user_field_spec.api_field,
      required=user_field_spec.required)

  return _FieldType(
      arg_type=arg_type,
      field_spec=field_spec,
      choices=user_field_spec.ChoiceMap())


class ArgDict(TypeGenerator, arg_utils.RepeatedMessageBindableType):
  """A wrapper to bind an ArgDict argument to a message.

  The non-flat mode has one dict per message. When the field is repeated, you
  can repeat the message by repeating the flag. For example, given a message
  with fields foo and bar, it looks like:

  --arg foo=1,bar=2 --arg foo=3,bar=4

  The Action method below is used later during argument generation to tell
  argparse to allow repeats of the dictionary and to append them.
  """

  @classmethod
  def FromData(cls, data):
    api_field = data['api_field']
    arg_name = data.get('arg_name')
    arg_type = data['type'][ARG_DICT]
    fields = [ArgDictFieldSpec.FromData(d) for d in arg_type['spec']]
    if arg_type.get('flatten'):
      if len(fields) != 2:
        raise InvalidSchemaError(
            'Flattened ArgDicts must have exactly two items in the spec.')
      return FlattenedArgDict(
          api_field=api_field, arg_name=arg_name,
          key_spec=fields[0], value_spec=fields[1])
    return cls(api_field, arg_name, fields)

  def __init__(self, api_field, arg_name, fields):
    # Represents user specified yaml data
    self.api_field = api_field
    self.arg_name = arg_name
    self.fields = fields

  def Action(self):
    return 'append'

  def GenerateType(self, field):
    """Generates an argparse type function to use to parse the argument.

    The return of the type function will be an instance of the given message
    with the fields filled in.

    Args:
      field: apitools field instance we are generating ArgObject for

    Raises:
      InvalidSchemaError: If a type for a field could not be determined.

    Returns:
      _MessageFieldType, The type function that parses the ArgDict and returns
      a message instance.
    """
    field_spec = _FieldSpec.FromUserData(
        field, arg_name=self.arg_name, api_field=self.api_field)
    field_specs = [_GetArgDictFieldType(field.type, f) for f in self.fields]
    required = [f.arg_name for f in field_specs if f.required]

    arg_dict = arg_parsers.ArgDict(
        spec={f.arg_name: f for f in field_specs},
        required_keys=required)
    return _MessageFieldType(
        arg_type=arg_dict,
        field_spec=field_spec,
        field_specs=field_specs)


class FlattenedArgDict(TypeGenerator, arg_utils.RepeatedMessageBindableType):
  """A wrapper to bind an ArgDict argument to a message with a key/value pair.

  The flat mode has one dict corresponding to a repeated field. For example,
  given a message with fields key and value, it looks like:

  --arg a=b,c=d

  Which would generate 2 instances of the message:
  [{key=a, value=b}, {key=c, value=d}]
  """

  def __init__(self, api_field, arg_name, key_spec, value_spec):
    # Represents user specified yaml data
    self.api_field = api_field
    self.arg_name = arg_name
    self.key_spec = key_spec
    self.value_spec = value_spec

  def GenerateType(self, field):
    """Generates an argparse type function to use to parse the argument.

    The return of the type function will be a list of instances of the given
    message with the fields filled in.

    Args:
      field: apitools field instance we are generating ArgObject for

    Raises:
      InvalidSchemaError: If a type for a field could not be determined.

    Returns:
      _AdditionalPropsType, The type function that parses the ArgDict
        and returns a list of message instances.
    """
    field_spec = _FieldSpec.FromUserData(
        field, arg_name=self.arg_name, api_field=self.api_field)
    key_type = _GetArgDictFieldType(field.type, self.key_spec)
    value_type = _GetArgDictFieldType(field.type, self.value_spec)
    arg_dict = arg_parsers.ArgDict(key_type=key_type, value_type=value_type)

    return _AdditionalPropsType(
        arg_type=arg_dict,
        field_spec=field_spec,
        key_spec=key_type,
        value_spec=value_type)


@dataclasses.dataclass(frozen=True)
class ArgDictFieldSpec:
  """Attributes about the fields that make up an ArgDict spec.

  Attributes:
    api_field: The name of the field under the repeated message that the value
      should be put.
    arg_name: The name of the key in the dict.
    field_type: The argparse type of the value of this field.
    required: True if the key is required.
    choices: A static map of choice to value the user types.
  """

  @classmethod
  def FromData(cls, data):
    data_choices = data.get('choices')
    choices = [Choice(d) for d in data_choices] if data_choices else None
    return cls(
        api_field=data['api_field'],
        arg_name=data.get('arg_name'),
        field_type=ParseType(data),
        required=data.get('required', True),
        choices=choices,
    )

  api_field: str | None
  arg_name: str | None
  field_type: Callable[[str], Any] | None
  required: bool
  choices: list[Choice] | None

  def ChoiceMap(self):
    return Choice.ToChoiceMap(self.choices)


class _ArgJSONType(usage_text.DefaultArgTypeWrapper):
  """Parse json into apitools type but preserve arg_json help text."""

  def __init__(self, arg_type, field_spec):
    super(_ArgJSONType, self).__init__(arg_type=arg_type)
    self.field = field_spec.field
    self.repeated = field_spec.repeated
    self.field_type = arg_utils.GetFieldType(field_spec.field)

  def _EncodeInput(self, value):
    # Only return list if field is explicitly repeated.
    # Otherwise, we want to to map to array_value.
    if isinstance(value, list) and self.repeated:
      return [self._EncodeInput(v) for v in value]

    if (self.field_type == arg_utils.FieldType.JSON and
        not isinstance(value, dict)):
      raise arg_parsers.ArgumentTypeError(
          'Expecting map format i.e. {"foo": "bar"}')

    return arg_utils.EncodeToMessage(self.field.type, value)

  def __call__(self, arg_value):
    parsed_arg_value = self.arg_type(arg_value)
    try:
      return self._EncodeInput(parsed_arg_value)
    except arg_parsers.ArgumentTypeError as e:
      raise arg_parsers.ArgumentTypeError(f'Bad value [{arg_value}]: {e}')


class ArgJSON(TypeGenerator, arg_utils.ArgJSONType):
  """A wrapper to bind an ArgJSON argument to a message."""

  @classmethod
  def FromData(cls, data):
    """Creates ArgJSON from yaml data."""
    del data
    return cls()

  def GenerateType(self, field):
    # We only recommend arg_json for struct field types.
    # arg_object is similar to arg_json but allows for better error handling
    # and more control over help text. arg_object is preferred for struct
    # fields because (1) they are recursive (2) have special JSON to proto
    # conversion logic.
    field_type = arg_utils.GetFieldType(field)
    if (field_type != arg_utils.FieldType.JSON and
        field_type != arg_utils.FieldType.JSON_VALUE):
      raise InvalidSchemaError(
          'Invalid type: arg_json cannot be used for non-struct field types.'
          'Recommend changing to arg_object.')

    field_spec = _FieldSpec.FromUserData(field)
    return _ArgJSONType(arg_type=arg_parsers.ArgJSON(), field_spec=field_spec)
