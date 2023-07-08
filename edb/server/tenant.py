#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2023-present MagicStack Inc. and the EdgeDB authors.
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
#

from __future__ import annotations
from typing import *

import functools

if TYPE_CHECKING:
    from edb.pgsql import params as pgparams

    from . import pgcluster
    from . import server as edbserver


class Tenant:
    _server: edbserver.Server | None
    _cluster: pgcluster.BaseCluster
    _tenant_id: str

    def __init__(self, cluster: pgcluster.BaseCluster):
        self._server = None
        self._cluster = cluster
        self._tenant_id = self.get_backend_runtime_params().tenant_id

    def set_server(self, server: edbserver.Server) -> None:
        self._server = server

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def get_pg_dbname(self, dbname: str) -> str:
        return self._cluster.get_db_name(dbname)

    def get_pgaddr(self) -> Dict[str, Any]:
        return self._cluster.get_connection_spec()

    @functools.lru_cache
    def get_backend_runtime_params(self) -> pgparams.BackendRuntimeParams:
        return self._cluster.get_runtime_params()