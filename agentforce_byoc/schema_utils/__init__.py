# Copyright (c) 2026, Salesforce, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Schema utilities for Agentforce BYOC functions."""

from agentforce_byoc.schema_utils.entry_func import entry_func
from agentforce_byoc.schema_utils.generator import (
    extract_entry_functions,
    generate_openapi,
    generate_schema,
    generate_schema_yaml,
)
from agentforce_byoc.schema_utils.schema import requestSchema, responseSchema

__all__ = [
    "entry_func",
    "requestSchema",
    "responseSchema",
    "extract_entry_functions",
    "generate_openapi",
    "generate_schema",
    "generate_schema_yaml",
]
