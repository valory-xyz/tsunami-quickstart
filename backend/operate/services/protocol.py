#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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
"""This module implements the onchain manager."""

import binascii
import contextlib
import io
import json
import logging
import tempfile
import time
import typing as t
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from aea.configurations.data_types import PackageType
from aea.crypto.base import Crypto, LedgerApi
from aea.helpers.base import IPFSHash, cd
from aea_ledger_ethereum.ethereum import EthereumCrypto
from autonomy.chain.base import registry_contracts
from autonomy.chain.config import ChainConfigs, ChainType, ContractConfigs
from autonomy.chain.service import get_agent_instances, get_service_info
from autonomy.chain.tx import TxSettler
from autonomy.cli.helpers.chain import MintHelper as MintManager
from autonomy.cli.helpers.chain import OnChainHelper
from autonomy.cli.helpers.chain import ServiceHelper as ServiceManager
from hexbytes import HexBytes
from operate.data import DATA_DIR
from operate.data.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)
from operate.ledger.profiles import CONTRACTS

from ._subgraph import SubgraphClient

ZERO_ETH = 0


class StakingState(Enum):
    """Staking state enumeration for the staking."""

    UNSTAKED = 0
    STAKED = 1
    EVICTED = 2


NULL_ADDRESS: str = "0x" + "0" * 40
MAX_UINT256 = 2**256 - 1


class SafeOperation(Enum):
    """Operation types."""

    CALL = 0
    DELEGATE_CALL = 1
    CREATE = 2


class MultiSendOperation(Enum):
    """Operation types."""

    CALL = 0
    DELEGATE_CALL = 1


def hash_payload_to_hex(
    safe_tx_hash: str,
    ether_value: int,
    safe_tx_gas: int,
    to_address: str,
    data: bytes,
    operation: int = SafeOperation.CALL.value,
    base_gas: int = 0,
    safe_gas_price: int = 0,
    gas_token: str = NULL_ADDRESS,
    refund_receiver: str = NULL_ADDRESS,
    use_flashbots: bool = False,
    gas_limit: int = 0,
    raise_on_failed_simulation: bool = False,
) -> str:
    """Serialise to a hex string."""
    if len(safe_tx_hash) != 64:  # should be exactly 32 bytes!
        raise ValueError(
            "cannot encode safe_tx_hash of non-32 bytes"
        )  # pragma: nocover

    if len(to_address) != 42 or len(gas_token) != 42 or len(refund_receiver) != 42:
        raise ValueError("cannot encode address of non 42 length")  # pragma: nocover

    if (
        ether_value > MAX_UINT256
        or safe_tx_gas > MAX_UINT256
        or base_gas > MAX_UINT256
        or safe_gas_price > MAX_UINT256
        or gas_limit > MAX_UINT256
    ):
        raise ValueError(
            "Value is bigger than the max 256 bit value"
        )  # pragma: nocover

    if operation not in [v.value for v in SafeOperation]:
        raise ValueError("SafeOperation value is not valid")  # pragma: nocover

    if not isinstance(use_flashbots, bool):
        raise ValueError(
            f"`use_flashbots` value ({use_flashbots}) is not valid. A boolean value was expected instead"
        )

    ether_value_ = ether_value.to_bytes(32, "big").hex()
    safe_tx_gas_ = safe_tx_gas.to_bytes(32, "big").hex()
    operation_ = operation.to_bytes(1, "big").hex()
    base_gas_ = base_gas.to_bytes(32, "big").hex()
    safe_gas_price_ = safe_gas_price.to_bytes(32, "big").hex()
    use_flashbots_ = use_flashbots.to_bytes(32, "big").hex()
    gas_limit_ = gas_limit.to_bytes(32, "big").hex()
    raise_on_failed_simulation_ = raise_on_failed_simulation.to_bytes(32, "big").hex()

    concatenated = (
        safe_tx_hash
        + ether_value_
        + safe_tx_gas_
        + to_address
        + operation_
        + base_gas_
        + safe_gas_price_
        + gas_token
        + refund_receiver
        + use_flashbots_
        + gas_limit_
        + raise_on_failed_simulation_
        + data.hex()
    )
    return concatenated


def skill_input_hex_to_payload(payload: str) -> dict:
    """Decode payload."""
    tx_params = dict(
        safe_tx_hash=payload[:64],
        ether_value=int.from_bytes(bytes.fromhex(payload[64:128]), "big"),
        safe_tx_gas=int.from_bytes(bytes.fromhex(payload[128:192]), "big"),
        to_address=payload[192:234],
        operation=int.from_bytes(bytes.fromhex(payload[234:236]), "big"),
        base_gas=int.from_bytes(bytes.fromhex(payload[236:300]), "big"),
        safe_gas_price=int.from_bytes(bytes.fromhex(payload[300:364]), "big"),
        gas_token=payload[364:406],
        refund_receiver=payload[406:448],
        use_flashbots=bool.from_bytes(bytes.fromhex(payload[448:512]), "big"),
        gas_limit=int.from_bytes(bytes.fromhex(payload[512:576]), "big"),
        raise_on_failed_simulation=bool.from_bytes(
            bytes.fromhex(payload[576:640]), "big"
        ),
        data=bytes.fromhex(payload[640:]),
    )
    return tx_params


class StakingManager(OnChainHelper):
    """Helper class for staking a service."""

    def __init__(self, key: Path, chain_type: ChainType = ChainType.CUSTOM) -> None:
        """Initialize object."""
        super().__init__(key=key, chain_type=chain_type)
        self.staking_ctr = t.cast(
            ServiceStakingTokenContract,
            ServiceStakingTokenContract.from_dir(
                directory=str(DATA_DIR / "contracts" / "service_staking_token")
            ),
        )

    def status(self, service_id: int, staking_contract: str) -> StakingState:
        """Is the service staked?"""
        return StakingState(
            self.staking_ctr.get_instance(
                ledger_api=self.ledger_api,
                contract_address=staking_contract,
            )
            .functions.getServiceStakingState(service_id)
            .call()
        )

    def slots_available(self, staking_contract: str) -> bool:
        """Check if there are available slots on the staking contract"""
        instance = self.staking_ctr.get_instance(
            ledger_api=self.ledger_api,
            contract_address=staking_contract,
        )
        available = instance.functions.maxNumServices().call() - len(
            instance.functions.getServiceIds().call()
        )
        return available > 0

    def service_info(self, staking_contract: str, service_id: int) -> dict:
        """Get the service onchain info"""
        return self.staking_ctr.get_service_info(
            self.ledger_api,
            staking_contract,
            service_id,
        ).get("data")

    def stake(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
    ) -> None:
        """Stake the service"""
        status = self.status(service_id, staking_contract)
        if status == StakingState.STAKED:
            raise ValueError("Service already stacked")

        if status == StakingState.EVICTED:
            raise ValueError("Service is evicted")

        if not self.slots_available(staking_contract):
            raise ValueError("No sataking slots available.")

        tx_settler = TxSettler(
            ledger_api=self.ledger_api,
            crypto=self.crypto,
            chain_type=self.chain_type,
            timeout=self.timeout,
            retries=self.retries,
            sleep=self.sleep,
        )

        # we make use of the ERC20 contract to build the approval transaction
        # since it has the same interface as ERC721 we might want to create
        # a ERC721 contract package

        def _build_approval_tx(*args, **kargs) -> t.Dict:
            return registry_contracts.erc20.get_approve_tx(
                ledger_api=self.ledger_api,
                contract_address=service_registry,
                spender=staking_contract,
                sender=self.crypto.address,
                amount=service_id,
            )

        setattr(tx_settler, "build", _build_approval_tx)
        tx_settler.transact(
            method=lambda: {},
            contract="",
            kwargs={},
            dry_run=False,
        )

        def _build_staking_tx(*args, **kargs) -> t.Dict:
            return self.ledger_api.build_transaction(
                contract_instance=self.staking_ctr.get_instance(
                    ledger_api=self.ledger_api,
                    contract_address=staking_contract,
                ),
                method_name="stake",
                method_args={"serviceId": service_id},
                tx_args={
                    "sender_address": self.crypto.address,
                },
                raise_on_try=True,
            )

        setattr(tx_settler, "build", _build_staking_tx)
        tx_settler.transact(
            method=lambda: {},
            contract="",
            kwargs={},
            dry_run=False,
        )

    def _can_unstake_service(
        self,
        service_id: int,
        staking_contract: str,
    ) -> bool:
        """Check unstaking availability"""
        ts_start = t.cast(int, self.service_info(staking_contract, service_id)[3])
        available_rewards = t.cast(
            int,
            self.staking_ctr.available_rewards(self.ledger_api, staking_contract).get(
                "data"
            ),
        )
        minimum_staking_duration = t.cast(
            int,
            self.staking_ctr.get_min_staking_duration(
                self.ledger_api, staking_contract
            ).get("data"),
        )
        staked_duration = time.time() - ts_start
        if staked_duration < minimum_staking_duration and available_rewards > 0:
            return False
        return True

    def unstake(self, service_id: int, staking_contract: str) -> None:
        """Unstake the service"""
        if (
            self.status(service_id=service_id, staking_contract=staking_contract)
            != StakingState.STAKED
        ):
            raise ValueError("Service not staked.")

        if not self._can_unstake_service(service_id, staking_contract):
            raise ValueError("Service cannot be unstaked yet.")

        tx_settler = TxSettler(
            ledger_api=self.ledger_api,
            crypto=self.crypto,
            chain_type=self.chain_type,
            timeout=self.timeout,
            retries=self.retries,
            sleep=self.sleep,
        )

        def _build_unstaking_tx(*args, **kargs) -> t.Dict:
            return self.ledger_api.build_transaction(
                contract_instance=self.staking_ctr.get_instance(
                    ledger_api=self.ledger_api,
                    contract_address=staking_contract,
                ),
                method_name="unstake",
                method_args={"serviceId": service_id},
                tx_args={
                    "sender_address": self.crypto.address,
                },
                raise_on_try=True,
            )

        setattr(tx_settler, "build", _build_unstaking_tx)
        tx_settler.transact(
            method=lambda: {},
            contract="",
            kwargs={},
            dry_run=False,
        )


class OnChainManager:
    """On chain service management."""

    def __init__(self, rpc: str, key: Path, contracts: t.Dict) -> None:
        """On chain manager."""
        self.rpc = rpc
        self.key = key
        self.chain_type = ChainType.CUSTOM
        self.contracts = contracts

    def _patch(self) -> None:
        """Patch contract and chain config."""
        ChainConfigs.get(self.chain_type).rpc = self.rpc
        if self.chain_type != ChainType.CUSTOM:
            return

        for name, address in self.contracts.items():
            ContractConfigs.get(name=name).contracts[self.chain_type] = address

    @property
    def crypto(self) -> Crypto:
        """Load crypto object."""
        self._patch()
        _, crypto = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type,
            key=self.key,
        )
        return crypto

    @property
    def ledger_api(self) -> LedgerApi:
        """Load ledger api object."""
        self._patch()
        ledger_api, _ = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type,
            key=self.key,
        )
        return ledger_api

    def info(self, token_id: int) -> t.Dict:
        """Get service info."""
        self._patch()
        ledger_api, _ = OnChainHelper.get_ledger_and_crypto_objects(
            chain_type=self.chain_type
        )
        (
            security_deposit,
            multisig_address,
            config_hash,
            threshold,
            max_agents,
            number_of_agent_instances,
            service_state,
            cannonical_agents,
        ) = get_service_info(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            token_id=token_id,
        )
        instances = get_agent_instances(
            ledger_api=ledger_api,
            chain_type=self.chain_type,
            token_id=token_id,
        ).get("agentInstances", [])
        return dict(
            security_deposit=security_deposit,
            multisig=multisig_address,
            config_hash=config_hash.hex(),
            threshold=threshold,
            max_agents=max_agents,
            number_of_agent_instances=number_of_agent_instances,
            service_state=service_state,
            cannonical_agents=cannonical_agents,
            instances=instances,
        )

    def mint(
        self,
        package_path: Path,
        agent_id: int,
        number_of_slots: int,
        cost_of_bond: int,
        threshold: int,
        nft: Optional[Union[Path, IPFSHash]],
        update_token: t.Optional[int] = None,
        token: t.Optional[str] = None,
    ):
        "Mint service."
        # TODO: Support for update
        self._patch()
        manager = MintManager(
            chain_type=self.chain_type,
            key=self.key,
            update_token=update_token,
        )
        manager.subgraph = SubgraphClient()

        # Prepare for minting
        (
            manager.load_package_configuration(
                package_path=package_path, package_type=PackageType.SERVICE
            )
            .load_metadata()
            .verify_nft(nft=nft)
            .verify_service_dependencies(agent_id=agent_id)
            .publish_metadata()
        )

        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with cd(temp):
                method = (
                    manager.mint_service
                    if update_token is None
                    else manager.update_service
                )
                method(
                    number_of_slots=number_of_slots,
                    cost_of_bond=cost_of_bond,
                    threshold=threshold,
                    token=token,
                )
                (metadata,) = Path(temp).glob("*.json")
                published = {
                    "token": int(Path(metadata).name.replace(".json", "")),
                    "metadata": json.loads(Path(metadata).read_text(encoding="utf-8")),
                }
        return published

    def activate(
        self,
        service_id: int,
        token: t.Optional[str] = None,
    ) -> None:
        """Activate service."""
        logging.info(f"Activating service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.key,
            ).check_is_service_token_secured(
                token=token,
            ).activate_service()

    def register(
        self,
        service_id: int,
        instances: t.List[str],
        agents: t.List[int],
        token: t.Optional[str] = None,
    ) -> None:
        """Register instance."""
        logging.info(f"Registering service {service_id}...")
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.key,
            ).check_is_service_token_secured(
                token=token,
            ).register_instance(
                instances=instances,
                agent_ids=agents,
            )

    def deploy(
        self,
        service_id: int,
        reuse_multisig: bool = False,
        token: t.Optional[str] = None,
    ) -> None:
        """Deploy service."""
        logging.info(f"Deploying service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.key,
            ).check_is_service_token_secured(
                token=token,
            ).deploy_service(
                reuse_multisig=reuse_multisig,
            )

    def swap(
        self,
        service_id: int,
        multisig: str,
        owner_key: str,
    ) -> None:
        """Swap safe owner."""
        logging.info(f"Swapping safe for service {service_id} [{multisig}]...")
        self._patch()
        manager = ServiceManager(
            service_id=service_id,
            chain_type=self.chain_type,
            key=self.key,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir, "key.txt")
            key_file.write_text(owner_key)
            owner_crypto = EthereumCrypto(private_key_path=str(key_file))
        owner_cryptos: list[EthereumCrypto] = [owner_crypto]
        owners = [
            manager.ledger_api.api.to_checksum_address(owner_crypto.address)
            for owner_crypto in owner_cryptos
        ]
        owner_to_swap = owners[0]
        multisend_txs = []
        txd = registry_contracts.gnosis_safe.get_swap_owner_data(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            old_owner=manager.ledger_api.api.to_checksum_address(owner_to_swap),
            new_owner=manager.ledger_api.api.to_checksum_address(
                manager.crypto.address
            ),
        ).get("data")
        multisend_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": multisig,
                "value": 0,
                "data": HexBytes(txd[2:]),
            }
        )
        multisend_txd = registry_contracts.multisend.get_tx_data(  # type: ignore
            ledger_api=manager.ledger_api,
            contract_address=ContractConfigs.multisend.contracts[self.chain_type],
            multi_send_txs=multisend_txs,
        ).get("data")
        multisend_data = bytes.fromhex(multisend_txd[2:])
        safe_tx_hash = registry_contracts.gnosis_safe.get_raw_safe_transaction_hash(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            value=0,
            data=multisend_data,
            safe_tx_gas=0,
            operation=SafeOperation.DELEGATE_CALL.value,
        ).get("tx_hash")[2:]
        payload_data = hash_payload_to_hex(
            safe_tx_hash=safe_tx_hash,
            ether_value=0,
            safe_tx_gas=0,
            to_address=ContractConfigs.multisend.contracts[self.chain_type],
            data=multisend_data,
        )
        tx_params = skill_input_hex_to_payload(payload=payload_data)
        safe_tx_bytes = binascii.unhexlify(tx_params["safe_tx_hash"])
        owner_to_signature = {}
        for owner_crypto in owner_cryptos:
            signature = owner_crypto.sign_message(
                message=safe_tx_bytes,
                is_deprecated_mode=True,
            )
            owner_to_signature[
                manager.ledger_api.api.to_checksum_address(owner_crypto.address)
            ] = signature[2:]
        tx = registry_contracts.gnosis_safe.get_raw_safe_transaction(
            ledger_api=manager.ledger_api,
            contract_address=multisig,
            sender_address=owner_crypto.address,
            owners=tuple(owners),  # type: ignore
            to_address=tx_params["to_address"],
            value=tx_params["ether_value"],
            data=tx_params["data"],
            safe_tx_gas=tx_params["safe_tx_gas"],
            signatures_by_owner=owner_to_signature,
            operation=SafeOperation.DELEGATE_CALL.value,
        )
        stx = owner_crypto.sign_transaction(tx)
        tx_digest = manager.ledger_api.send_signed_transaction(stx)
        receipt = manager.ledger_api.api.eth.wait_for_transaction_receipt(tx_digest)
        if receipt["status"] != 1:
            raise RuntimeError("Error swapping owners")

    def terminate(self, service_id: int, token: t.Optional[str] = None) -> None:
        """Terminate service."""
        logging.info(f"Terminating service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.key,
            ).check_is_service_token_secured(
                token=token,
            ).terminate_service()

    def unbond(self, service_id: int, token: t.Optional[str] = None) -> None:
        """Unbond service."""
        logging.info(f"Unbonding service {service_id}...")
        self._patch()
        with contextlib.redirect_stdout(io.StringIO()):
            ServiceManager(
                service_id=service_id,
                chain_type=self.chain_type,
                key=self.key,
            ).check_is_service_token_secured(
                token=token,
            ).unbond_service()

    def staking_slots_available(self, staking_contract: str) -> bool:
        """Stake service."""
        self._patch()
        return StakingManager(
            key=self.key,
            chain_type=self.chain_type,
        ).slots_available(
            staking_contract=staking_contract,
        )

    def stake(
        self,
        service_id: int,
        service_registry: str,
        staking_contract: str,
    ) -> None:
        """Stake service."""
        self._patch()
        StakingManager(
            key=self.key,
            chain_type=self.chain_type,
        ).stake(
            service_id=service_id,
            service_registry=service_registry,
            staking_contract=staking_contract,
        )

    def unstake(self, service_id: int, staking_contract: str) -> None:
        """Unstake service."""
        self._patch()
        StakingManager(
            key=self.key,
            chain_type=self.chain_type,
        ).unstake(
            service_id=service_id,
            staking_contract=staking_contract,
        )
