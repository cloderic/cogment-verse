# Copyright 2021 AI Redefined Inc. <dev+cogment@ai-r.com>
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

import asyncio
import json
import logging
import os
import sys
from dotenv import load_dotenv

import cogment
from cogment_verse import RunContext
from cogment_verse_environment.base_agent_adapter import BaseAgentAdapter
from cogment_verse_environment.environment_adapter import EnvironmentAdapter

import cog_settings

load_dotenv()

PORT = int(os.getenv("COGMENT_VERSE_ENVIRONMENT_PORT", "9000"))
PROMETHEUS_PORT = int(os.getenv("COGMENT_VERSE_ENVIRONMENT_PROMETHEUS_PORT", "8000"))

TRIAL_DATASTORE_ENDPOINT = os.getenv("COGMENT_VERSE_TRIAL_DATASTORE_ENDPOINT")
MODEL_REGISTRY_ENDPOINT = os.getenv("COGMENT_VERSE_MODEL_REGISTRY_ENDPOINT")
ORCHESTRATOR_ENDPOINT = os.getenv("COGMENT_VERSE_ORCHESTRATOR_ENDPOINT")
ACTOR_ENDPOINTS = json.loads(os.getenv("COGMENT_VERSE_ACTOR_ENDPOINTS"))
ENVIRONMENT_ENDPOINTS = json.loads(os.getenv("COGMENT_VERSE_ENVIRONMENT_ENDPOINTS"))

logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)


async def main():
    context = RunContext(
        cog_settings=cog_settings,
        user_id="cogment_verse_environment",
        services_endpoints={
            "orchestrator": ORCHESTRATOR_ENDPOINT,
            "trial_datastore": TRIAL_DATASTORE_ENDPOINT,
            "model_registry": MODEL_REGISTRY_ENDPOINT,
            **ACTOR_ENDPOINTS,
            **ENVIRONMENT_ENDPOINTS,
        },
    )

    environment_adapter = EnvironmentAdapter()
    environment_adapter.register_implementations(context)

    base_agent_adapter = BaseAgentAdapter()
    base_agent_adapter.register_implementations(context)

    log.info(f"Environment service starting on port {PORT}...")
    await context.serve_all_registered(cogment.ServedEndpoint(port=PORT), prometheus_port=PROMETHEUS_PORT)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.error("process interrupted")
        sys.exit(-1)
