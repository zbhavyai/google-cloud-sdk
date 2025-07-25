# -*- coding: utf-8 -*- #
# Copyright 2023 Google LLC. All Rights Reserved.
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
"""Useful commands for interacting with the Cloud Firestore Admin API."""


from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

from googlecloudsdk.api_lib.util import apis


FIRESTORE_API_VERSION = 'v1'


def GetMessages():
  """Import and return the appropriate admin messages module."""
  return apis.GetMessagesModule('firestore', FIRESTORE_API_VERSION)


def GetClient():
  """Returns the Cloud Firestore client for the appropriate release track."""
  return apis.GetClientInstance('firestore', FIRESTORE_API_VERSION)


def FormatDurationString(duration):
  """Returns the duration string.

  Args:
    duration: the duration, an int. The unit is seconds.

  Returns:
    a duration with string format.
  """
  return '{}s'.format(duration)


def ParseTagsForTagsValue(tags, tags_value_message_type):
  """Returns the TagsValue message.

  Args:
    tags: the tags, a dictionary.
    tags_value_message_type: the TagsValue message type.

  Returns:
    a TagsValue message.
  """
  tags_value = None
  if tags:
    additional_properties = [
        tags_value_message_type.AdditionalProperty(
            key=key, value=value
        )
        for key, value in tags.items()
    ]
    tags_value = (
        tags_value_message_type(
            additionalProperties=additional_properties
        )
    )
  return tags_value
