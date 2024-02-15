# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Types module."""

import enum
import typing as t

from typing_extensions import NotRequired, TypedDict

_ACTIONS = {
    "status": 0,
    "build": 1,
    "deploy": 2,
    "stop": 3,
}


_CHAIN_NAME_TO_ENUM = {
    "ethereum": 0,
    "goerli": 1,
    "gnosis": 2,
    "solana": 3,
}

_CHAIN_ID_TO_CHAIN_NAME = {
    1: "ethereum",
    5: "goerli",
    100: "gnosis",
    1399811149: "solana",
}

_LEDGER_TYPE_TO_ENUM = {
    "ethereum": 0,
    "solana": 1,
}


class LedgerType(enum.IntEnum):
    """Ledger type enum."""

    ETHEREUM = 0
    SOLANA = 1

    @classmethod
    def from_string(cls, chain: str) -> "LedgerType":
        """Load from string."""
        return cls(_LEDGER_TYPE_TO_ENUM[chain.lower()])


class ChainType(enum.IntEnum):
    """Chain type enum."""

    ETHEREUM = 0
    GOERLI = 1
    GNOSIS = 2
    SOLANA = 3

    @classmethod
    def from_string(cls, chain: str) -> "ChainType":
        """Load from string."""
        return cls(_CHAIN_NAME_TO_ENUM[chain.lower()])

    @classmethod
    def from_id(cls, cid: int) -> "ChainType":
        """Load from chain ID."""
        return cls(_CHAIN_NAME_TO_ENUM[_CHAIN_ID_TO_CHAIN_NAME[cid]])


class ContractAddresses(TypedDict):
    """Contracts templates."""

    service_manager: str
    service_registry: str
    service_registry_token_utility: str
    gnosis_safe_proxy_factory: str
    gnosis_safe_same_address_multisig: str
    multisend: str


class LedgerConfig(TypedDict):
    """Ledger config."""

    rpc: str
    type: LedgerType
    chain: ChainType


LedgerConfigs = t.List[LedgerConfig]


class KeyType(TypedDict):
    """Key type."""

    address: str
    private_key: str
    ledger: ChainType


KeysType = t.List[KeyType]


class VariableType(TypedDict):
    """Variable type."""

    key: str
    value: str


VariablesType = t.List[VariableType]


class ServiceState(enum.IntEnum):
    """
    Service state
    """

    NON_EXISTENT = 0
    PRE_REGISTRATION = 1
    ACTIVE_REGISTRATION = 2
    FINISHED_REGISTRATION = 3
    DEPLOYED = 4
    TERMINATED_BONDED = 5


class ChainData(TypedDict):
    """Chain data for service."""

    instances: NotRequired[t.List[str]]  # Agent instances registered as safe owners
    token: NotRequired[int]
    multisig: NotRequired[str]


class ChainDeployment(TypedDict):
    """Chain deployment template."""

    nft: str
    agent_id: int
    cost_of_bond: int
    threshold: int
    required_funds: float


class LocalDeployment(TypedDict):
    """Local deployment template."""

    ports: t.Dict
    volumes: t.Dict[str, str]


class DeploymentConfig(TypedDict):
    """Deployments template."""

    chain: ChainDeployment
    local: LocalDeployment


class ServiceType(TypedDict):
    """Service payload."""

    name: str
    hash: str
    keys: KeysType
    readme: NotRequired[str]
    ledger: NotRequired[LedgerConfig]
    chain_data: NotRequired[ChainData]


ServicesType = t.List[ServiceType]


class ServiceTemplate(TypedDict):
    """Service template."""

    rpc: str
    name: str
    hash: str
    image: str
    description: str


class Action(enum.IntEnum):
    """Action payload."""

    STATUS = 0
    BUILD = 1
    DEPLOY = 2
    STOP = 3

    @classmethod
    def from_string(cls, action: str) -> "Action":
        """Load from string."""
        return cls(_ACTIONS[action])


class Status(enum.IntEnum):
    """Status payload."""

    CREATED = 0
    BUILT = 1
    DEPLOYING = 2
    DEPLOYED = 3
    STOPPING = 4
    STOPPED = 5
    DELETED = 6
