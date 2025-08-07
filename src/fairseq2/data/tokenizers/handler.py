# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, TypeVar, final

from typing_extensions import override

from fairseq2.assets import (
    AssetCard,
    AssetCardError,
    AssetConfigLoader,
    AssetDownloadManager,
)
from fairseq2.data.tokenizers.tokenizer import Tokenizer
from fairseq2.error import InternalError, raise_operational_system_error
from fairseq2.file_system import FileSystem
from fairseq2.runtime.dependency import DependencyContainer, DependencyResolver


class TokenizerFamilyHandler(ABC):
    @abstractmethod
    def get_tokenizer_config(self, card: AssetCard) -> object: ...

    @abstractmethod
    def load_tokenizer(
        self, card: AssetCard, config: object | None, progress: bool
    ) -> Tokenizer: ...

    @abstractmethod
    def load_custom_tokenizer(self, path: Path, config: object) -> Tokenizer: ...

    @property
    @abstractmethod
    def family(self) -> str: ...

    @property
    @abstractmethod
    def config_kls(self) -> type[object]: ...


class TokenizerModelError(Exception):
    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)

        self.path = path


TokenizerConfigT_contra = TypeVar("TokenizerConfigT_contra", contravariant=True)


class TokenizerLoader(Protocol[TokenizerConfigT_contra]):
    def __call__(self, path: Path, config: TokenizerConfigT_contra) -> Tokenizer: ...


TokenizerConfigT = TypeVar("TokenizerConfigT")


@final
class StandardTokenizerFamilyHandler(TokenizerFamilyHandler):
    _config_kls: type[object]
    _loader: TokenizerLoader[Any]

    def __init__(
        self,
        family: str,
        config_kls: type[TokenizerConfigT],
        loader: TokenizerLoader[TokenizerConfigT],
        file_system: FileSystem,
        asset_download_manager: AssetDownloadManager,
        asset_config_loader: AssetConfigLoader,
    ) -> None:
        self._family = family
        self._config_kls = config_kls
        self._loader = loader
        self._file_system = file_system
        self._asset_download_manager = asset_download_manager
        self._asset_config_loader = asset_config_loader

    @override
    def get_tokenizer_config(self, card: AssetCard) -> object:
        try:
            default_config = self._config_kls()
        except TypeError as ex:
            raise InternalError(
                f"Default configuration of the {self._family} tokenizer family cannot be constructed."
            ) from ex

        return self._asset_config_loader.load(
            card, default_config, config_key="tokenizer_config"
        )

    @override
    def load_tokenizer(
        self, card: AssetCard, config: object | None, progress: bool
    ) -> Tokenizer:
        name = card.name

        uri = card.field("tokenizer").as_uri()

        if uri.scheme not in self._asset_download_manager.supported_schemes:
            msg = f"tokenizer URI scheme of the {name} asset card is expected to be a supported scheme, but is {uri.scheme} instead."

            raise AssetCardError(name, msg)

        path = self._asset_download_manager.download_tokenizer(
            uri, name, progress=progress
        )

        # Load the configuration.
        if config is None:
            config = self.get_tokenizer_config(card)

            has_custom_config = False
        else:
            if not isinstance(config, self._config_kls):
                raise TypeError(
                    f"`config` must be of type `{self._config_kls}`, but is of type `{type(config)}` instead."
                )

            has_custom_config = True

        try:
            return self._loader(path, config)
        except ValueError as ex:
            if has_custom_config:
                raise

            msg = f"tokenizer_config field of the {name} asset card is not a valid {self._family} tokenizer configuration."

            raise AssetCardError(name, msg) from ex
        except TokenizerModelError as ex:
            msg = f"Tokenizer model of the {name} asset card cannot be loaded."

            raise AssetCardError(name, msg) from ex
        except FileNotFoundError as ex:
            if uri.scheme != "file":
                raise_operational_system_error(ex)

            msg = f"{path} pointed to by the tokenizer field of the {name} asset card is not found."

            raise AssetCardError(name, msg)
        except OSError as ex:
            raise_operational_system_error(ex)

    @override
    def load_custom_tokenizer(self, path: Path, config: object) -> Tokenizer:
        if not isinstance(config, self._config_kls):
            raise TypeError(
                f"`config` must be of type `{self._config_kls}`, but is of type `{type(config)}` instead."
            )

        return self._loader(path, config)

    @property
    @override
    def family(self) -> str:
        return self._family

    @property
    @override
    def config_kls(self) -> type[object]:
        return self._config_kls


class AdvancedTokenizerLoader(Protocol[TokenizerConfigT_contra]):
    def __call__(
        self, resolver: DependencyResolver, path: Path, config: TokenizerConfigT_contra
    ) -> Tokenizer: ...


def register_tokenizer_family(
    container: DependencyContainer,
    family: str,
    config_kls: type[TokenizerConfigT],
    *,
    loader: TokenizerLoader[TokenizerConfigT] | None = None,
    advanced_loader: AdvancedTokenizerLoader[TokenizerConfigT] | None = None,
) -> None:
    def create_handler(resolver: DependencyResolver) -> TokenizerFamilyHandler:
        nonlocal loader

        if advanced_loader is not None:
            if loader is not None:
                raise ValueError(
                    "`loader` and `advanced_loader` must not be specified at the same time."
                )

            def load_tokenizer(path: Path, config: TokenizerConfigT) -> Tokenizer:
                return advanced_loader(resolver, path, config)

            loader = load_tokenizer
        elif loader is None:
            raise ValueError("`loader` or `advanced_loader` must be specified.")

        file_system = resolver.resolve(FileSystem)

        asset_download_manager = resolver.resolve(AssetDownloadManager)

        asset_config_loader = resolver.resolve(AssetConfigLoader)

        return StandardTokenizerFamilyHandler(
            family,
            config_kls,
            loader,
            file_system,
            asset_download_manager,
            asset_config_loader,
        )

    container.register(TokenizerFamilyHandler, create_handler, key=family)
