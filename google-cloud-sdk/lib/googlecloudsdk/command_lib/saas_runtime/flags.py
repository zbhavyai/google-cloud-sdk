# -*- coding: utf-8 -*- #
# Copyright 2025 Google LLC. All Rights Reserved.
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
"""Flags for saas runtime commands."""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

from googlecloudsdk.calliope.concepts import concepts
from googlecloudsdk.command_lib.util.apis import yaml_data
from googlecloudsdk.command_lib.util.concepts import concept_parsers


def AddUnitKindArgToParser(parser, required=True, help_text='UnitKind.'):
  """Sets up the UnitKind argument for the command."""
  unit_kind_data = yaml_data.ResourceYAMLData.FromPath('saas_runtime.unit_kind')
  return concept_parsers.ConceptParser.ForResource(
      '--unit-kind',
      concepts.ResourceSpec.FromYaml(unit_kind_data.GetData()),
      help_text,
      required=required,
  ).AddToParser(parser)


def AddProjectLocationArgToParser(parser, required=True, help_text='location.'):
  """Sets up the location argument for the command."""
  project_location_data = yaml_data.ResourceYAMLData.FromPath(
      'saas_runtime.project_location'
  )
  return concept_parsers.ConceptParser.ForResource(
      '--project-location',
      concepts.ResourceSpec.FromYaml(project_location_data.GetData()),
      help_text,
      required=required,
  ).AddToParser(parser)
